import re
import traceback
from string import Formatter


# ---------- 版本号 ----------
COMPILER_VERSION = '0.1.8'


# ---------- 终端颜色 ----------
YELLOW = '\033[33m'
RESET = '\033[0m'


# ---------- 寄存器与常量定义 ----------
REG_WRITABLE = {'A', 'B', 'C', 'E', 'F', 'x', 'y', 'M', '@'}
REG_INDICATOR = {'M'}
REG_NON_WRITABLE = {'Ans', 'PreAns'}
REG_ANY = REG_WRITABLE | REG_INDICATOR | REG_NON_WRITABLE

TYPE_REGISTRY = {
    'WRITABLE': REG_WRITABLE,
    'INDICATOR': REG_INDICATOR,
    'NON_WRITABLE': REG_NON_WRITABLE,
    'ANY_REG': REG_ANY,
}

# 组合类型：一个名字展开成多个选项，任一匹配即可
COMBINED_TYPES = {
    'OPERAND': ['ANY_REG', 'CONSTANT'],
}

# 常量：十进制浮点数，允许 #1、#-1、#1.5、#-3.14，不允许十六进制
_CONSTANT_RE = re.compile(r'^#-?\d+(\.\d+)?$')


def _is_constant(s: str) -> bool:
    """判断字符串是否为合法的常量形式。"""
    return bool(_CONSTANT_RE.match(s))


# ---------- 全局模板 ----------
TEMPLATES = {
    'MOV':  ('{0}={1}',      ['WRITABLE', 'OPERAND']),
    'ADD':  ('{0}={0}+{1}',  ['WRITABLE', 'OPERAND']),
    'SUB':  ('{0}={0}+{1}',  ['WRITABLE', 'OPERAND']),
    'INC':  ('{0}={0}+1',    ['WRITABLE']),
    'DEC':  ('{0}={0}-1',    ['WRITABLE']),
    'MUL':  ('{0}={0}×{1}',  ['WRITABLE', 'OPERAND']),
    'DIV':  ('{0}={0}÷{1}',  ['WRITABLE', 'OPERAND']),
    'NEG':  ('{0}=-{0}',     ['WRITABLE']),
    'ABS':  ('{0}=Abs({0})', ['WRITABLE']),
    'SQR':  ('{0}={0}²',     ['WRITABLE']),
    'SQRT': ('{0}=√({0})',   ['WRITABLE']),
    'INIT':     ('{0}',      ['WRITABLE']),
    'INIT_END': ('{0}=1',    ['WRITABLE']),
    # 逻辑运算
    'LAND': ('{0}={0}*{1}',           ['WRITABLE', 'OPERAND']),
    'LOR':  ('{0}={0}+{1}-{0}*{1}',   ['WRITABLE', 'OPERAND']),
    'LXOR': ('{0}={0}+{1}-2*{0}*{1}', ['WRITABLE', 'OPERAND']),
    'LNOT': ('{0}=1-{0}',             ['WRITABLE']),
}

# 别名表：规范名 -> 别名列表
ALIASES = {
    'MOV': ['STO', 'STORE', 'LOAD'],
}


# ---------- 异常定义 ----------
class AsmCompileError(Exception):
    """所有汇编编译错误的基类，自动携带 line / token 位置。"""
    def __init__(self, message, line=None, token=None):
        self.line = line
        self.token = token
        self.raw_message = message
        if line is not None:
            message = f"[line {line}, token {token}] {message}"
        super().__init__(message)


class AsmSyntaxError(AsmCompileError):
    """语法级错误，不捕获，直接退出。"""
    pass


class CompileTemplateError(AsmCompileError):
    """模板相关错误的基类。"""
    pass


class UnknownMnemonicError(CompileTemplateError):
    """未知或不支持的助记符。"""
    pass


class TemplateMismatchError(CompileTemplateError):
    """模板参数数量不匹配。"""
    def __init__(self, mnemonic, expected, given, line=None, token=None):
        self.mnemonic = mnemonic
        self.expected = expected
        self.given = given
        super().__init__(
            f"Template for '{mnemonic}' needs {expected} arguments but {given} given",
            line=line,
            token=token,
        )


class TemplateSettingsError(CompileTemplateError):
    """模板配置本身有问题，不捕获，直接异常退出。"""
    pass


class RegisterNameError(CompileTemplateError):
    """token 不是任何一个已定义的寄存器名。"""
    def __init__(self, name, expected_type, line=None, token=None):
        self.name = name
        self.expected_type = expected_type
        super().__init__(
            f"'{name}' is not a valid register name; expected type: {expected_type}",
            line=line,
            token=token,
        )


class CompileTypeError(AsmCompileError):
    """token 是合法寄存器名或常量，但不满足期望的类型。"""
    def __init__(self, name, expected_type, line=None, token=None):
        self.name = name
        self.expected_type = expected_type
        super().__init__(
            f"'{name}' does not satisfy expected type: {expected_type}",
            line=line,
            token=token,
        )


# ---------- 类型匹配 ----------
def _split_type_spec(type_spec: str) -> list[str]:
    """把 'ANY_REG|CONSTANT' 拆成 ['ANY_REG', 'CONSTANT']。"""
    return [opt.strip() for opt in type_spec.split('|')]


def _matches_option(arg: str, opt: str) -> bool:
    """判断单个类型选项是否匹配。"""
    if opt == 'ANY':
        return True
    if opt == 'CONSTANT':
        return _is_constant(arg)
    if opt in COMBINED_TYPES:
        return any(_matches_option(arg, sub) for sub in COMBINED_TYPES[opt])
    reg_set = TYPE_REGISTRY.get(opt)
    if reg_set is None:
        return False
    return arg in reg_set


def _matches_type(arg: str, type_spec: str) -> bool:
    """任一选项匹配就算通过。"""
    for opt in _split_type_spec(type_spec):
        if _matches_option(arg, opt):
            return True
    return False


# ---------- 别名表构建 ----------
def _build_alias_map(aliases: dict) -> dict:
    """
    把 {规范名: [别名, ...]} 反转为 {别名: 规范名}。

    同时检测别名冲突：
    - 同一个别名出现在多个规范名下；
    - 别名和模板键重名；
    - 别名列表里有重复项。
    出错抛 TemplateSettingsError，不捕获。
    """
    alias_map: dict[str, str] = {}

    for canonical, alias_list in aliases.items():
        if canonical not in TEMPLATES:
            raise TemplateSettingsError(
                f"Alias group '{canonical}' is not a template key"
            )
        if not isinstance(alias_list, list):
            raise TemplateSettingsError(
                f"Aliases for '{canonical}' must be a list"
            )
        seen = set()
        for alias in alias_list:
            if alias in seen:
                raise TemplateSettingsError(
                    f"Duplicate alias '{alias}' in group '{canonical}'"
                )
            seen.add(alias)
            if alias in TEMPLATES:
                raise TemplateSettingsError(
                    f"Alias '{alias}' conflicts with template key"
                )
            if alias in alias_map:
                raise TemplateSettingsError(
                    f"Alias '{alias}' already defined for "
                    f"'{alias_map[alias]}', cannot redefine for '{canonical}'"
                )
            alias_map[alias] = canonical

    return alias_map


# ---------- 模板配置校验 ----------
def _validate_templates(templates: dict) -> None:
    """
    在解析写出前一次性校验模板配置。

    出错直接抛 TemplateSettingsError，不捕获，让程序异常退出。
    """
    for mnemonic, spec in templates.items():
        if not isinstance(spec, tuple) or len(spec) != 2:
            raise TemplateSettingsError(f"Invalid template spec for '{mnemonic}'")

        fmt, types = spec
        if not isinstance(types, list) or not types:
            raise TemplateSettingsError(f"Empty type list for '{mnemonic}'")

        fields = [f for _, f, _, _ in Formatter().parse(fmt) if f is not None]
        distinct = set(fields)
        if len(distinct) != len(types):
            raise TemplateSettingsError(
                f"Template for '{mnemonic}' has {len(distinct)} placeholder(s) "
                f"but {len(types)} type spec(s)"
            )

        for t in types:
            if not t:
                raise TemplateSettingsError(f"Empty type spec in '{mnemonic}'")
            for opt in _split_type_spec(t):
                if not opt:
                    raise TemplateSettingsError(
                        f"Empty option in type spec '{t}' for '{mnemonic}'"
                    )
                if opt in ('ANY', 'CONSTANT'):
                    continue
                if opt in COMBINED_TYPES:
                    continue
                if opt not in TYPE_REGISTRY:
                    raise TemplateSettingsError(
                        f"Unknown type option '{opt}' in '{mnemonic}'"
                    )


# ---------- 解析 ----------
def parse_asm(text: str) -> list[tuple[int, str, list[str]]]:
    """
    解析汇编风格的多行字符串。

    返回 [(原始行号, 原始助记符, 参数列表), ...]。
    行号从 1 开始，空行/纯注释行也占用行号，只是不会被返回。
    助记符保留原始大小写形式，供错误消息和 #!! 行使用。

    切分规则：按任意空白或逗号切分，所以 'mov a,b' 和 'mov a, b'
    都会得到 ['mov', 'a', 'b']。

    同时检查 INIT / INIT_END 的数量：
    - 超过一个 INIT     -> AsmSyntaxError
    - 超过一个 INIT_END -> AsmSyntaxError
    - 无 INIT 有 INIT_END -> AsmSyntaxError
    以上错误不捕获，直接退出。

    另外收集非全大写的助记符，解析完成后统一打印黄色警告。
    """
    result: list[tuple[int, str, list[str]]] = []
    warnings: list[tuple[int, str]] = []

    for line_no, line in enumerate(text.splitlines(), start=1):
        code = re.split(r';', line, maxsplit=1)[0]
        tokens = [t for t in re.split(r'[\s,]+', code.strip()) if t]
        if not tokens:
            continue
        mnemonic = tokens[0]
        if mnemonic != mnemonic.upper():
            warnings.append((line_no, mnemonic))
        result.append((line_no, mnemonic, tokens[1:]))

    init_count = sum(1 for _, m, _ in result if m.upper() == 'INIT')
    init_end_count = sum(1 for _, m, _ in result if m.upper() == 'INIT_END')

    if init_count > 1:
        raise AsmSyntaxError("More than one 'INIT' command found")
    if init_end_count > 1:
        raise AsmSyntaxError("More than one 'INIT_END' command found")
    if init_count == 0 and init_end_count > 0:
        raise AsmSyntaxError("'INIT_END' found without 'INIT'")

    if warnings:
        _print_case_warnings(warnings)

    return result


def _print_case_warnings(warnings: list[tuple[int, str]]) -> None:
    """打印非全大写助记符的黄色警告，每行最多 3 项，列对齐。"""
    items = [f'[Line {ln} | "{mn}"]' for ln, mn in warnings]
    width = max(len(s) for s in items)

    header = (
        'Warning: your code contains non-uppercase mnemonics. '
        'Uppercase mnemonics (e.g. "MOV") are recommended. '
        'The following mnemonics are not fully uppercase:'
    )

    out = [header]
    for i in range(0, len(items), 3):
        chunk = items[i:i + 3]
        row = ', '.join(s.ljust(width) for s in chunk).rstrip()
        out.append(row)

    print(f'{YELLOW}' + '\n'.join(out) + f'{RESET}')


# ---------- 写出 ----------
def write_asm(data, output_path: str) -> None:
    """按模板将解析结果写出到文件。"""
    _validate_templates(TEMPLATES)
    alias_map = _build_alias_map(ALIASES)

    lines: list[str] = []
    init_reg = None        # 当前 INIT 寄存器
    init_failed = False    # INIT 出错后，等待 INIT_END 同步忽略

    for line_no, mnemonic, args in data:
        mnemonic_upper = mnemonic.upper()
        canonical = alias_map.get(mnemonic_upper, mnemonic_upper)

        # INIT 失败后，INIT_END 同步忽略：写 #!! 行，不带错误名
        if canonical == 'INIT_END' and init_failed:
            original = ' '.join([mnemonic] + args)
            lines.append(f"#!! {original}")
            init_failed = False
            init_reg = None
            continue

        try:
            # 1. 模板匹配
            if canonical not in TEMPLATES:
                raise UnknownMnemonicError(
                    f"Unknown or unsupported mnemonic: '{mnemonic}'",
                    line=line_no,
                    token=1,
                )

            fmt, types = TEMPLATES[canonical]

            # 2. 参数数量
            if len(args) != len(types):
                raise TemplateMismatchError(
                    mnemonic,
                    len(types),
                    len(args),
                    line=line_no,
                    token=1,
                )

            # 3. 类型 + 4. 寄存器名
            for j, (arg, t) in enumerate(zip(args, types)):
                token_no = j + 2   # 助记符是 token 1
                if _matches_type(arg, t):
                    continue
                if arg in REG_ANY or arg.startswith('#'):
                    raise CompileTypeError(
                        arg, t, line=line_no, token=token_no
                    )
                raise RegisterNameError(
                    arg, t, line=line_no, token=token_no
                )

            # 写入前：常量去掉 # 号
            final_args = [a[1:] if a.startswith('#') else a for a in args]
            result_line = fmt.format(*final_args)

            # INIT 特殊处理：记录寄存器，进入替换模式，标记写在冒号后
            if canonical == 'INIT':
                init_reg = final_args[0]
                lines.append(result_line + ': #$ INIT')
                continue

            # INIT_END 特殊处理：结束替换模式，本身不替换，标记写在冒号后
            if canonical == 'INIT_END':
                init_reg = None
                init_failed = False
                lines.append(result_line + ': #$ INIT_END')
                continue

            # 替换逻辑：INIT 模式下，展开后含 '=' 的行才替换
            if init_reg is not None and '=' in result_line:
                left, right = result_line.split('=', 1)
                result_line = f"{left}={left}+{init_reg}({right}-{left})"

            lines.append(result_line + ':')

        except AsmCompileError as e:
            traceback.print_exc()
            original = ' '.join([mnemonic] + args)

            if canonical == 'INIT':
                # INIT 失败：标记，后续 INIT_END 同步忽略
                init_failed = True
                lines.append(f"#!! {original} ;{type(e).__name__}")
            elif canonical == 'INIT_END':
                # INIT_END 失败：写错误行，结束替换模式
                init_reg = None
                init_failed = False
                lines.append(f"#!! {original} ;{type(e).__name__}")
            else:
                lines.append(f"#!! {original} ;{type(e).__name__}")

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(f'#? Compiler_CALC_version_{COMPILER_VERSION}\n')
        f.write('x:\n')
        for i, line in enumerate(lines):
            if i == len(lines) - 1:
                # 最末一行去掉第一个冒号
                line = line.replace(':', '', 1)
            f.write(line + '\n')


# ---------- 测试 ----------
if __name__ == "__main__":
    text = """
mov A, B
STORE A, B
sto A, B
LOAD A, B
mOv A, B
init M
add A, #1
INIT_END x
"""

    parsed = parse_asm(text)
    print("\n解析结果（行号, 原始助记符, 参数）：")
    for row in parsed:
        print(row)

    output_file = './result.calc'
    write_asm(parsed, output_file)
    print(f"\n已写入文件：{output_file}")