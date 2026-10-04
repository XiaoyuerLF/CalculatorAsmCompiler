import re
import traceback
from string import Formatter


# ---------- 版本号 ----------
COMPILER_VERSION = '0.2.1'


# ---------- 终端颜色 ----------
YELLOW = '\033[33m'
RED = '\033[31m'
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


# ---------- CMP / JCC 助记符 ----------
CMP_MNEMONICS = {'CMP'}
JCC_MNEMONICS = {'JE', 'JNE', 'JG', 'JGE', 'JL', 'JLE'}
RESERVED_MNEMONICS = CMP_MNEMONICS | JCC_MNEMONICS


# ---------- 条件宏生成 ----------
def _cond_eq(a, b):
    """A == B 的条件宏。"""
    return f'2^(({a}-{b})²D)'


def _cond_ne(a, b):
    """A != B 的条件宏。"""
    return f'1-2^(({a}-{b})²D)'


def _cond_gt(a, b):
    """A > B 的条件宏。"""
    return f'2^((Abs({a}-{b}-1)-({a}-{b}-1))²D)'


def _cond_ge(a, b):
    """A >= B 的条件宏。"""
    return f'2^((Abs({a}-{b})-({a}-{b}))²D)'


def _cond_lt(a, b):
    """A < B 的条件宏。"""
    return f'1-2^((Abs({a}-{b})-({a}-{b}))²D)'


def _cond_le(a, b):
    """A <= B 的条件宏。"""
    return f'1-2^((Abs({a}-{b}-1)-({a}-{b}-1))²D)'


# JCC 助记符 -> 条件宏生成函数
CONDITION_MACROS = {
    'JE':  _cond_eq,
    'JNE': _cond_ne,
    'JG':  _cond_gt,
    'JGE': _cond_ge,
    'JL':  _cond_lt,
    'JLE': _cond_le,
}


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


class ConditionalBlockError(AsmCompileError):
    """条件块内的错误，例如无等号命令或修改标志寄存器。"""
    pass


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
    - 别名和模板键或保留助记符重名；
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
            if alias in RESERVED_MNEMONICS:
                raise TemplateSettingsError(
                    f"Alias '{alias}' conflicts with reserved mnemonic"
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

    label 定义（如 'L1:'）会以特殊助记符 'LABEL' 返回，参数为 [label_name]。

    本阶段还负责结构性检查，详见 _structural_checks。
    """
    result: list[tuple[int, str, list[str]]] = []
    case_warnings: list[tuple[int, str]] = []

    for line_no, line in enumerate(text.splitlines(), start=1):
        code = re.split(r';', line, maxsplit=1)[0].strip()
        if not code:
            continue

        # label 定义：整体一个 token，以 ':' 结尾，内部无空白和逗号
        if code.endswith(':'):
            inner = code[:-1].strip()
            if inner and not re.search(r'[\s,]', inner):
                result.append((line_no, 'LABEL', [inner]))
                continue
            code = code[:-1]

        tokens = [t for t in re.split(r'[\s,]+', code) if t]
        if not tokens:
            continue
        mnemonic = tokens[0]
        if mnemonic != mnemonic.upper():
            case_warnings.append((line_no, mnemonic))
        result.append((line_no, mnemonic, tokens[1:]))

    _structural_checks(result, case_warnings)
    return result


def _structural_checks(result: list[tuple[int, str, list[str]]],
                       case_warnings: list[tuple[int, str]]) -> None:
    """
    对解析结果做整体结构检查。

    - Error 抛 AsmSyntaxError，不捕获，直接退出。
    - Warning 统一收集后打印。
    """
    # ----- 收集 label 定义与引用 -----
    label_defs: dict[str, int] = {}
    label_refs: dict[str, list[int]] = {}

    for line_no, mnemonic, args in result:
        if mnemonic == 'LABEL':
            name = args[0]
            if name in label_defs:
                raise AsmSyntaxError(
                    f"Duplicate label definition: '{name}' at line {line_no}"
                )
            label_defs[name] = line_no
        elif mnemonic.upper() in JCC_MNEMONICS:
            if not args:
                raise AsmSyntaxError(
                    f"JCC at line {line_no} has no label argument"
                )
            end_label = args[-1]
            label_refs.setdefault(end_label, []).append(line_no)

    # ----- label 未定义引用 -> Error -----
    for name, ref_lines in label_refs.items():
        if name not in label_defs:
            raise AsmSyntaxError(
                f"Undefined label: '{name}' referenced at line(s) "
                f"{', '.join(str(n) for n in ref_lines)}"
            )

    # ----- label 未引用 -> Warning -----
    unreferenced_labels: list[tuple[int, str]] = []
    for name, def_line in label_defs.items():
        if name not in label_refs:
            unreferenced_labels.append((def_line, name))

    # ----- INIT / INIT_END 检查 -----
    init_line, init_args = None, None
    init_end_line, init_end_args = None, None
    init_count = 0
    init_end_count = 0
    for line_no, mnemonic, args in result:
        u = mnemonic.upper()
        if u == 'INIT':
            init_count += 1
            init_line, init_args = line_no, args
        elif u == 'INIT_END':
            init_end_count += 1
            init_end_line, init_end_args = line_no, args

    if init_count > 1:
        raise AsmSyntaxError("More than one 'INIT' command found")
    if init_end_count > 1:
        raise AsmSyntaxError("More than one 'INIT_END' command found")
    if init_count == 0 and init_end_count > 0:
        raise AsmSyntaxError("'INIT_END' found without 'INIT'")

    if init_count == 1 and init_end_count == 1:
        init_reg = init_args[0] if init_args else None
        init_end_reg = init_end_args[0] if init_end_args else None
        if init_reg != init_end_reg:
            raise AsmSyntaxError(
                f"INIT register '{init_reg}' at line {init_line} "
                f"does not match INIT_END register '{init_end_reg}' "
                f"at line {init_end_line}"
            )

    init_reg_name = init_args[0] if init_args else None

    # ----- 遍历做 CMP/JCC 配对、嵌套、重叠检查 -----
    independent_jcc_warnings: list[tuple[int, str]] = []
    nesting_warnings: list[tuple[int, str]] = []
    shared_flag_warnings: list[tuple[int, str]] = []
    cmp_init_warnings: list[tuple[int, str]] = []

    block_stack: list[tuple[str, str]] = []  # (flag, target_label)
    in_init_block = False
    i = 0
    while i < len(result):
        line_no, mnemonic, args = result[i]
        canonical = mnemonic.upper()

        if canonical == 'INIT':
            in_init_block = True
            i += 1
            continue
        if canonical == 'INIT_END':
            in_init_block = False
            i += 1
            continue

        if mnemonic == 'LABEL':
            name = args[0]
            # 只弹栈顶匹配的 label，避免顺序结构被误判为嵌套
            if block_stack and block_stack[-1][1] == name:
                block_stack.pop()
            i += 1
            continue

        if canonical == 'CMP':
            if i + 1 >= len(result):
                raise AsmSyntaxError(
                    f"CMP at line {line_no} is not followed by a JCC"
                )
            next_line_no, next_mnemonic, next_args = result[i + 1]
            next_canonical = next_mnemonic.upper()
            if next_canonical not in JCC_MNEMONICS:
                raise AsmSyntaxError(
                    f"CMP at line {line_no} is not followed by a JCC "
                    f"(found '{next_mnemonic}' at line {next_line_no})"
                )

            cmp_flag = args[2] if len(args) >= 3 else 'M'
            jcc_flag = next_args[0] if len(next_args) >= 2 else 'M'
            if cmp_flag != jcc_flag:
                raise AsmSyntaxError(
                    f"CMP flag '{cmp_flag}' at line {line_no} does not match "
                    f"JCC flag '{jcc_flag}' at line {next_line_no}"
                )

            if in_init_block:
                raise AsmSyntaxError(
                    f"CMP/JCC block starting at line {line_no} overlaps "
                    f"with INIT/INIT_END block"
                )

            if init_reg_name is not None and cmp_flag == init_reg_name:
                cmp_init_warnings.append((line_no, cmp_flag))

            jcc_label = next_args[-1]

            if block_stack:
                nesting_warnings.append((line_no, mnemonic))
                if any(f == cmp_flag for f, _ in block_stack):
                    shared_flag_warnings.append((line_no, mnemonic))

            block_stack.append((cmp_flag, jcc_label))
            i += 2
            continue

        if canonical in JCC_MNEMONICS:
            # 独立 JCC
            independent_jcc_warnings.append((line_no, mnemonic))

            jcc_flag = args[0] if len(args) >= 2 else 'M'
            jcc_label = args[-1]

            if in_init_block:
                raise AsmSyntaxError(
                    f"JCC block starting at line {line_no} overlaps "
                    f"with INIT/INIT_END block"
                )

            if init_reg_name is not None and jcc_flag == init_reg_name:
                cmp_init_warnings.append((line_no, jcc_flag))

            if block_stack:
                nesting_warnings.append((line_no, mnemonic))
                if any(f == jcc_flag for f, _ in block_stack):
                    shared_flag_warnings.append((line_no, mnemonic))

            block_stack.append((jcc_flag, jcc_label))
            i += 1
            continue

        i += 1

    # ----- 统一打印 Warning -----
    if case_warnings:
        _print_case_warnings(case_warnings)
    if independent_jcc_warnings:
        _print_independent_jcc_warnings(independent_jcc_warnings)
    if unreferenced_labels:
        _print_unreferenced_label_warnings(unreferenced_labels)
    if nesting_warnings:
        _print_nesting_warnings(nesting_warnings, shared_flag_warnings)
    if cmp_init_warnings:
        _print_cmp_init_warnings(cmp_init_warnings)


# ---------- Warning 打印 ----------
def _print_yellow(lines: list[str]) -> None:
    """把多行文本用黄色打印。"""
    print(f'{YELLOW}' + '\n'.join(lines) + f'{RESET}')


def _print_cols(header: str, items: list[str]) -> None:
    """把 items 按每行 3 项、列对齐打印成黄色警告。"""
    width = max(len(s) for s in items)
    out = [header]
    for i in range(0, len(items), 3):
        chunk = items[i:i + 3]
        row = ', '.join(s.ljust(width) for s in chunk).rstrip()
        out.append(row)
    _print_yellow(out)


def _print_case_warnings(warnings: list[tuple[int, str]]) -> None:
    """打印非全大写助记符的黄色警告。"""
    items = [f'[Line {ln} | "{mn}"]' for ln, mn in warnings]
    header = (
        'Warning: your code contains non-uppercase mnemonics. '
        'Uppercase mnemonics (e.g. "MOV") are recommended. '
        'The following mnemonics are not fully uppercase:'
    )
    _print_cols(header, items)


def _print_independent_jcc_warnings(warnings: list[tuple[int, str]]) -> None:
    """打印独立 JCC 的黄色警告。"""
    items = [f'[Line {ln} | "{mn}"]' for ln, mn in warnings]
    header = (
        'Warning: the following JCC commands are not paired with a CMP. '
        'They will be treated as pure JCC blocks:'
    )
    _print_cols(header, items)


def _print_unreferenced_label_warnings(warnings: list[tuple[int, str]]) -> None:
    """打印未引用 label 的黄色警告。"""
    items = [f'[Line {ln} | "{name}"]' for ln, name in warnings]
    header = 'Warning: the following labels are defined but never referenced:'
    _print_cols(header, items)


def _print_nesting_warnings(nesting: list[tuple[int, str]],
                            shared: list[tuple[int, str]]) -> None:
    """打印嵌套条件块警告。"""
    items = [f'[Line {ln} | "{mn}"]' for ln, mn in nesting]
    header = (
        'Warning: nested conditional blocks are not recommended, '
        'this will make the expression very long:'
    )
    _print_cols(header, items)

    if shared:
        items2 = [f'[Line {ln} | "{mn}"]' for ln, mn in shared]
        header2 = (
            'Warning: nested conditional blocks share the same flag register, '
            'please make sure the flag is saved and restored manually:'
        )
        _print_cols(header2, items2)


def _print_cmp_init_warnings(warnings: list[tuple[int, str]]) -> None:
    """打印 CMP 标志与 INIT 标志相同的警告。"""
    items = [f'[Line {ln} | flag "{f}"]' for ln, f in warnings]
    header = (
        'Warning: the following CMP/JCC flag registers are the same '
        'as the INIT register. This may cause conflicts:'
    )
    _print_cols(header, items)


# ---------- 写出 ----------
def write_asm(data, output_path: str) -> None:
    """按模板将解析结果写出到文件。"""
    _validate_templates(TEMPLATES)
    alias_map = _build_alias_map(ALIASES)

    lines: list[str] = []
    init_reg = None        # 当前 INIT 寄存器
    init_failed = False    # INIT 出错后，等待 INIT_END 同步忽略
    block_stack: list[tuple[str, bool, str]] = []   # (标志, 是否取反, 目标 label)

    i = 0
    n = len(data)
    while i < n:
        line_no, mnemonic, args = data[i]

        # ----- label 定义行 -----
        if mnemonic == 'LABEL':
            label_name = args[0]
            if block_stack and block_stack[-1][2] == label_name:
                block_stack.pop()
            i += 1
            continue

        mnemonic_upper = mnemonic.upper()
        canonical = alias_map.get(mnemonic_upper, mnemonic_upper)

        # ----- CMP + JCC 配对 -----
        if canonical == 'CMP':
            jcc_mnemonic = data[i + 1][1].upper()
            jcc_args = data[i + 1][2]

            cmp_a = args[0]
            cmp_b = args[1]
            cmp_flag = args[2] if len(args) >= 3 else 'M'

            cond_expr = CONDITION_MACROS[jcc_mnemonic](cmp_a, cmp_b)
            lines.append(f'{cmp_flag}={cond_expr}:')

            jcc_flag = jcc_args[0] if len(jcc_args) >= 2 else 'M'
            jcc_label = jcc_args[-1]
            negate = (jcc_mnemonic == 'JNE')
            block_stack.append((jcc_flag, negate, jcc_label))

            i += 2
            continue

        # ----- 独立 JCC -----
        if canonical in JCC_MNEMONICS:
            jcc_flag = args[0] if len(args) >= 2 else 'M'
            jcc_label = args[-1]
            negate = (canonical == 'JNE')
            block_stack.append((jcc_flag, negate, jcc_label))
            i += 1
            continue

        # ----- INIT 失败后，INIT_END 同步忽略 -----
        if canonical == 'INIT_END' and init_failed:
            original = ' '.join([mnemonic] + args)
            lines.append(f"#!! {original}")
            init_failed = False
            init_reg = None
            i += 1
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

            # ----- INIT 特殊处理 -----
            if canonical == 'INIT':
                init_reg = final_args[0]
                lines.append(result_line + ': #$ INIT')
                i += 1
                continue

            if canonical == 'INIT_END':
                init_reg = None
                init_failed = False
                lines.append(result_line + ': #$ INIT_END')
                i += 1
                continue

            # ----- 条件块内检查 -----
            if block_stack:
                if '=' not in result_line:
                    raise ConditionalBlockError(
                        f"Non-assignment command inside conditional block: "
                        f"'{mnemonic}'",
                        line=line_no,
                        token=1,
                    )
                target = result_line.split('=', 1)[0]
                for flag, _, _ in block_stack:
                    if target == flag:
                        raise ConditionalBlockError(
                            f"Cannot modify flag register '{flag}' "
                            f"inside conditional block",
                            line=line_no,
                            token=1,
                        )

            # ----- INIT 展开 -----
            if init_reg is not None and '=' in result_line:
                left, right = result_line.split('=', 1)
                result_line = f"{left}={left}+{init_reg}({right}-{left})"

            # ----- 条件展开 -----
            if block_stack and '=' in result_line:
                left, right = result_line.split('=', 1)
                for flag, negate, _ in reversed(block_stack):
                    flag_expr = f'(1-{flag})' if negate else flag
                    right = f'{left}+{flag_expr}({right}-{left})'
                result_line = f'{left}={right}'

            lines.append(result_line + ':')

        except AsmCompileError as e:
            print(f'{RED}{traceback.format_exc()}{RESET}', end='')
            original = ' '.join([mnemonic] + args)

            if canonical == 'INIT':
                init_failed = True
                lines.append(f"#!! {original} ;{type(e).__name__}")
            elif canonical == 'INIT_END':
                init_reg = None
                init_failed = False
                lines.append(f"#!! {original} ;{type(e).__name__}")
            else:
                lines.append(f"#!! {original} ;{type(e).__name__}")

        i += 1

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(f'#? Compiler_CALC_version_{COMPILER_VERSION}\n')
        f.write('x:\n')
        for idx, line in enumerate(lines):
            if idx == len(lines) - 1:
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
INIT_END M

CMP A, B, M
JE M, L1
    ADD A, #1
    MOV C, #2
L1:
    SUB A, #1

CMP A, B, C
JNE C, L2
    ADD A, #1
L2:
"""

    parsed = parse_asm(text)
    print("\n解析结果（行号, 原始助记符, 参数）：")
    for row in parsed:
        print(row)

    output_file = './result.calc'
    write_asm(parsed, output_file)
    print(f"\n已写入文件：{output_file}")