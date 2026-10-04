import re
import traceback
from string import Formatter


# ---------- 版本号 ----------

COMPILER_VERSION = '0.1.5'


# ---------- 寄存器与常量定义 ----------

REG_WRITABLE = {'A', 'B', 'C', 'E', 'F', 'x', 'y', 'M', '@'}
REG_INDICATOR = {'M'}
REG_NON_WRITABLE = {'Ans', 'PreAns'}
REG_ANY = REG_WRITABLE | REG_INDICATOR | REG_NON_WRITABLE

TYPE_REGISTRY = {
    'writable': REG_WRITABLE,
    'indicator': REG_INDICATOR,
    'non_writable': REG_NON_WRITABLE,
    'any_reg': REG_ANY,
}

# 组合类型：一个名字展开成多个选项，任一匹配即可
COMBINED_TYPES = {
    'operand': ['any_reg', 'constant'],
}

# 常量：十进制浮点数，允许 #1、#-1、#1.5、#-3.14，不允许十六进制
_CONSTANT_RE = re.compile(r'^#-?\d+(\.\d+)?$')


def _is_constant(s: str) -> bool:
    return bool(_CONSTANT_RE.match(s))


# ---------- 全局模板 ----------

TEMPLATES = {
    'mov':  ('{0}={1}',      ['writable', 'operand']),
    'load': ('{0}={1}',      ['writable', 'operand']),
    'sto':  ('{0}={1}',      ['writable', 'operand']),
    'add':  ('{0}={0}+{1}',  ['writable', 'operand']),
    'sub':  ('{0}={0}+{1}',  ['writable', 'operand']),
    'inc':  ('{0}={0}+1',    ['writable']),
    'dec':  ('{0}={0}-1',    ['writable']),
    'mul':  ('{0}={0}×{1}',  ['writable', 'operand']),
    'div':  ('{0}={0}÷{1}',  ['writable', 'operand']),
    'neg':  ('{0}=-{0}',     ['writable']),
    'abs':  ('{0}=Abs({0})', ['writable']),
    'sqr':  ('{0}={0}²',     ['writable']),
    'sqrt': ('{0}=√({0})',   ['writable']),
    'init':     ('{0}',      ['writable']),
    'init_end': ('{0}=1',    ['writable']),
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
            line=line, token=token,
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
            line=line, token=token,
        )


class CompileTypeError(AsmCompileError):
    """token 是合法寄存器名或常量，但不满足期望的类型。"""
    def __init__(self, name, expected_type, line=None, token=None):
        self.name = name
        self.expected_type = expected_type
        super().__init__(
            f"'{name}' does not satisfy expected type: {expected_type}",
            line=line, token=token,
        )


# ---------- 类型匹配 ----------

def _split_type_spec(type_spec: str) -> list[str]:
    """把 'any_reg|constant' 拆成 ['any_reg', 'constant']。"""
    return [opt.strip() for opt in type_spec.split('|')]


def _matches_option(arg: str, opt: str) -> bool:
    if opt == 'any':
        return True
    if opt == 'constant':
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


# ---------- 模板配置校验 ----------

def _validate_templates(templates: dict) -> None:
    """
    在解析写出前一次性校验模板配置，出错直接抛 TemplateSettingsError，
    不捕获，让程序异常退出。
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
                if opt in ('any', 'constant'):
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
    返回 [(原始行号, 助记符, 参数列表), ...]。
    行号从 1 开始，空行/纯注释行也占用行号，只是不会被返回。

    切分规则：按任意空白或逗号切分，所以 'mov a,b' 和 'mov a, b'
    都会得到 ['mov', 'a', 'b']。

    同时检查 init / init_end 的数量：
    - 超过一个 init   -> AsmSyntaxError
    - 超过一个 init_end -> AsmSyntaxError
    - 无 init 有 init_end -> AsmSyntaxError
    以上错误不捕获，直接退出。
    """
    result: list[tuple[int, str, list[str]]] = []

    for line_no, line in enumerate(text.splitlines(), start=1):
        code = re.split(r';', line, maxsplit=1)[0]
        tokens = [t for t in re.split(r'[\s,]+', code.strip()) if t]
        if not tokens:
            continue
        result.append((line_no, tokens[0], tokens[1:]))

    init_count = sum(1 for _, m, _ in result if m == 'init')
    init_end_count = sum(1 for _, m, _ in result if m == 'init_end')

    if init_count > 1:
        raise AsmSyntaxError("More than one 'init' command found")
    if init_end_count > 1:
        raise AsmSyntaxError("More than one 'init_end' command found")
    if init_count == 0 and init_end_count > 0:
        raise AsmSyntaxError("'init_end' found without 'init'")

    return result


# ---------- 写出 ----------

def write_asm(data, output_path: str) -> None:
    _validate_templates(TEMPLATES)

    lines: list[str] = []
    init_reg = None        # 当前 init 寄存器
    init_failed = False    # init 出错后，等待 init_end 同步忽略

    for line_no, mnemonic, args in data:
        # init 失败后，init_end 同步忽略：写 #!! 行，不带错误名
        if mnemonic == 'init_end' and init_failed:
            original = ' '.join([mnemonic] + args)
            lines.append(f"#!! {original}")
            init_failed = False
            init_reg = None
            continue

        try:
            # 1. 模板匹配
            if mnemonic not in TEMPLATES:
                raise UnknownMnemonicError(
                    f"Unknown or unsupported mnemonic: '{mnemonic}'",
                    line=line_no, token=1,
                )

            fmt, types = TEMPLATES[mnemonic]

            # 2. 参数数量
            if len(args) != len(types):
                raise TemplateMismatchError(
                    mnemonic, len(types), len(args),
                    line=line_no, token=1,
                )

            # 3. 类型 + 4. 寄存器名
            for j, (arg, t) in enumerate(zip(args, types)):
                token_no = j + 2   # 助记符是 token 1
                if _matches_type(arg, t):
                    continue
                if arg in REG_ANY or arg.startswith('#'):
                    raise CompileTypeError(arg, t, line=line_no, token=token_no)
                raise RegisterNameError(arg, t, line=line_no, token=token_no)

            # 写入前：常量去掉 # 号
            final_args = [a[1:] if a.startswith('#') else a for a in args]
            result_line = fmt.format(*final_args)

            # init 特殊处理：记录寄存器，进入替换模式，标记写在冒号后
            if mnemonic == 'init':
                init_reg = final_args[0]
                lines.append(result_line + ': #$ INIT')
                continue

            # init_end 特殊处理：结束替换模式，本身不替换，标记写在冒号后
            if mnemonic == 'init_end':
                init_reg = None
                init_failed = False
                lines.append(result_line + ': #$ INIT_END')
                continue

            # 替换逻辑：init 模式下，展开后含 '=' 的行才替换
            if init_reg is not None and '=' in result_line:
                left, right = result_line.split('=', 1)
                result_line = f"{left}={left}+{init_reg}({right}-{left})"

            lines.append(result_line + ':')

        except AsmCompileError as e:
            traceback.print_exc()
            original = ' '.join([mnemonic] + args)

            if mnemonic == 'init':
                # init 失败：标记，后续 init_end 同步忽略
                init_failed = True
                lines.append(f"#!! {original} ;{type(e).__name__}")
            elif mnemonic == 'init_end':
                # init_end 失败：写错误行，结束替换模式
                init_reg = None
                init_failed = False
                lines.append(f"#!! {original} ;{type(e).__name__}")
            else:
                lines.append(f"#!! {original} ;{type(e).__name__}")

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(f'#? Compiler_CALC_version_{COMPILER_VERSION}\n')
        for line in lines:
            f.write(line + '\n')


# ---------- 测试 ----------

if __name__ == "__main__":
    text = """
init M
add A, #1
mov B, C
neg A
sub A, B
init_end x
add A, #1
"""

    parsed = parse_asm(text)
    print("解析结果（行号, 助记符, 参数）：")
    for row in parsed:
        print(row)

    output_file = './result.calc'
    write_asm(parsed, output_file)
    print(f"\n已写入文件：{output_file}")