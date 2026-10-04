import re
import traceback
from string import Formatter


# ---------- 版本号 ----------
COMPILER_VERSION = '0.2.7'


# ---------- 终端颜色 ----------
YELLOW = '\033[33m'         # 一级警告：黄字
LEVEL2 = '\033[43;31m'      # 二级警告：黄底红字
RED = '\033[31m'
RESET = '\033[0m'


# ---------- 寄存器与常量定义 ----------
REG_WRITABLE = {'A', 'B', 'C', 'E', 'F', 'x', 'y', 'M', '@', 'D'}
REG_INDICATOR = {'M'}
REG_NON_WRITABLE = {'Ans', 'PreAns'}
CONST_REG = {'D'}
REG_ANY = REG_WRITABLE | REG_INDICATOR | REG_NON_WRITABLE

TYPE_REGISTRY = {
    'WRITABLE': REG_WRITABLE,
    'INDICATOR': REG_INDICATOR,
    'NON_WRITABLE': REG_NON_WRITABLE,
    'ANY_REG': REG_ANY,
    'CONST_REG': CONST_REG,
}

# 组合类型：一个名字展开成多个选项，任一匹配即可
# 目前 OPERAND 直接硬编码在 _matches_option 里，
# 此字典保留作为未来扩展的占位
COMBINED_TYPES = {}

# 常量：十进制浮点数，支持科学计数法
_CONSTANT_RE = re.compile(r'^#[+-]?\d+(\.\d+)?([eE][+-]?\d+)?$')


def _is_constant(s: str) -> bool:
    """判断字符串是否为合法的常量形式。"""
    return bool(_CONSTANT_RE.match(s))


def _format_constant(arg: str) -> str:
    """
    把常量参数格式化为计算器表达式。

    - 去掉开头的 '#'；
    - 科学计数法的 e/E 替换为 '(×10^)'。
    """
    s = arg[1:] if arg.startswith('#') else arg
    return re.sub(r'[eE]', '(×10^)', s)


# ---------- CMP / JCC 助记符 ----------
CMP_MNEMONICS = {'CMP'}
JCC_MNEMONICS = {'JE', 'JNE', 'JG', 'JGE', 'JL', 'JLE'}
RESERVED_MNEMONICS = CMP_MNEMONICS | JCC_MNEMONICS

# ---------- CMOV 助记符 ----------
CMOV_MNEMONICS = {'CMOVZ', 'CMOVNZ', 'CMOVNE', 'CMOVG', 'CMOVGE',
                  'CMOVL', 'CMOVLE'}
RESERVED_MNEMONICS = RESERVED_MNEMONICS | CMOV_MNEMONICS


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


CONDITION_MACROS = {
    'JE':  _cond_eq,
    'JNE': _cond_ne,
    'JG':  _cond_gt,
    'JGE': _cond_ge,
    'JL':  _cond_lt,
    'JLE': _cond_le,
}


# ---------- CMOV 条件宏 ----------
def _cmov_z(a, b):
    """若 a==0，标志置 1。b 不参与。"""
    return f'2^(({a})²D)'


def _cmov_nz(a, b):
    """若 a!=0，标志置 1。b 不参与。"""
    return f'1-2^(({a})²D)'


CMOV_CONDITION_MACROS = {
    'CMOVZ':  _cmov_z,
    'CMOVNZ': _cmov_nz,
    'CMOVNE': _cond_ne,
    'CMOVG':  _cond_gt,
    'CMOVGE': _cond_ge,
    'CMOVL':  _cond_lt,
    'CMOVLE': _cond_le,
}


# ---------- 全局模板 ----------
TEMPLATES = {
    'MOV':  ('{0}={1}',      ['WRITABLE', 'OPERAND']),
    'ADD':  ('{0}={0}+{1}',  ['WRITABLE', 'OPERAND']),
    'SUB':  ('{0}={0}-{1}',  ['WRITABLE', 'OPERAND']),
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
    'LAND': ('{0}={0}*{1}',           ['WRITABLE', 'OPERAND']),
    'LOR':  ('{0}={0}+{1}-{0}*{1}',   ['WRITABLE', 'OPERAND']),
    'LXOR': ('{0}={0}+{1}-2*{0}*{1}', ['WRITABLE', 'OPERAND']),
    'LNOT': ('{0}=1-{0}',             ['WRITABLE']),
}

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


class KeyRegisterError(ConditionalBlockError):
    """在 CMP-JCC 块内写入关键寄存器。"""
    pass


class CmpJccValidationError(AsmCompileError):
    """CMP/JCC 参数校验失败。"""
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
    if opt == 'BOOL':
        # BOOL 的匹配集与 OPERAND 相同，但解析规则不同
        return arg in REG_ANY or _is_constant(arg)
    if opt == 'OPERAND':
        return arg in REG_ANY or _is_constant(arg)
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


def _resolve_bool(arg: str) -> str:
    """
    把 BOOL 参数解析为最终值。

    - 寄存器名：原样返回
    - #0：返回 '0'
    - 其他常量：返回 '1'
    """
    if arg in REG_ANY:
        return arg
    if arg == '#0':
        return '0'
    return '1'


def _err_type_for(arg: str) -> str:
    """根据参数形态选择合适的异常类型名。"""
    if arg in REG_ANY or arg.startswith('#'):
        return 'CompileTypeError'
    return 'RegisterNameError'


# ---------- 别名表构建 ----------
def _build_alias_map(aliases: dict) -> dict:
    """把 {规范名: [别名, ...]} 反转为 {别名: 规范名}。"""
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
    """校验模板配置，出错抛 TemplateSettingsError。"""
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
                if opt in ('ANY', 'CONSTANT', 'BOOL', 'OPERAND'):
                    continue
                if opt in COMBINED_TYPES:
                    continue
                if opt not in TYPE_REGISTRY:
                    raise TemplateSettingsError(
                        f"Unknown type option '{opt}' in '{mnemonic}'"
                    )


# ---------- 解析 ----------
def parse_asm(text: str) -> list[tuple[int, str, list[str], str]]:
    """解析汇编风格的多行字符串。"""
    result: list[tuple[int, str, list[str], str]] = []
    case_warnings: list[tuple[int, str]] = []

    for line_no, line in enumerate(text.splitlines(), start=1):
        code = re.split(r';', line, maxsplit=1)[0].strip()
        if not code:
            continue

        if code.endswith(':'):
            inner = code[:-1].strip()
            if inner and not re.search(r'[\s,]', inner):
                result.append((line_no, 'LABEL', [inner], code))
                continue
            raise AsmSyntaxError(
                f"Invalid label definition at line {line_no}: '{code}'"
            )

        tokens = [t for t in re.split(r'[\s,]+', code) if t]
        if not tokens:
            continue
        mnemonic = tokens[0]
        if mnemonic != mnemonic.upper():
            case_warnings.append((line_no, mnemonic))
        result.append((line_no, mnemonic, tokens[1:], code))

    _structural_checks(result, case_warnings)
    return result


def _structural_checks(result: list[tuple[int, str, list[str], str]],
                       case_warnings: list[tuple[int, str]]) -> None:
    """对解析结果做整体结构检查。"""
    # ----- 收集 label 定义与引用 -----
    label_defs: dict[str, int] = {}
    label_refs: dict[str, list[int]] = {}

    for line_no, mnemonic, args, _ in result:
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

    for name, ref_lines in label_refs.items():
        if name not in label_defs:
            raise AsmSyntaxError(
                f"Undefined label: '{name}' referenced at line(s) "
                f"{', '.join(str(n) for n in ref_lines)}"
            )

    for name, ref_lines in label_refs.items():
        def_line = label_defs[name]
        for ref_line in ref_lines:
            if def_line <= ref_line:
                raise AsmSyntaxError(
                    f"Label '{name}' referenced at line {ref_line} "
                    f"is defined before the JCC (line {def_line}). "
                    f"Labels must be defined after the JCC that references them."
                )

    unreferenced_labels: list[tuple[int, str]] = []
    for name, def_line in label_defs.items():
        if name not in label_refs:
            unreferenced_labels.append((def_line, name))

    # ----- INIT / INIT_END 检查 -----
    init_line, init_args = None, None
    init_end_line, init_end_args = None, None
    init_count = 0
    init_end_count = 0
    for line_no, mnemonic, args, _ in result:
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

    # ----- 遍历做 CMP/JCC 配对、嵌套、半嵌套、空块、INIT 重叠检查 -----
    independent_jcc_warnings: list[tuple[int, str]] = []
    nesting_warnings: list[tuple[int, str]] = []
    shared_flag_warnings: list[tuple[int, str]] = []
    cmp_init_warnings: list[tuple[int, str]] = []
    empty_block_warnings: list[tuple[int, str]] = []

    block_stack: list[tuple[str, str, int, bool]] = []
    i = 0
    while i < len(result):
        line_no, mnemonic, args, _ = result[i]
        canonical = mnemonic.upper()

        # INIT 进入时，JCC 块必须为空
        if canonical == 'INIT':
            if block_stack:
                raise AsmSyntaxError(
                    f"INIT at line {line_no} overlaps "
                    f"with an active JCC block"
                )
            i += 1
            continue

        # INIT_END 出现时，JCC 块必须为空
        if canonical == 'INIT_END':
            if block_stack:
                raise AsmSyntaxError(
                    f"INIT_END at line {line_no} overlaps "
                    f"with an active JCC block"
                )
            i += 1
            continue

        if mnemonic == 'LABEL':
            name = args[0]
            label_index = i
            popped: list[tuple[str, str, int, bool]] = []
            while block_stack and block_stack[-1][1] == name:
                popped.append(block_stack.pop())
            if any(entry[1] == name for entry in block_stack):
                raise AsmSyntaxError(
                    f"Semi-nested conditional block: label '{name}' at line "
                    f"{line_no} closes an outer JCC whose inner JCC "
                    f"is not closed yet"
                )
            for entry in popped:
                _, target, jcc_idx, _ = entry
                if label_index == jcc_idx + 1:
                    empty_block_warnings.append((line_no, target))
            i += 1
            continue

        if canonical == 'CMP':
            if i + 1 >= len(result):
                raise AsmSyntaxError(
                    f"CMP at line {line_no} is not followed by a JCC"
                )
            next_line_no, next_mnemonic, next_args, _ = result[i + 1]
            next_canonical = next_mnemonic.upper()
            if next_canonical not in JCC_MNEMONICS:
                raise AsmSyntaxError(
                    f"CMP at line {line_no} is not followed by a JCC "
                    f"(found '{next_mnemonic}' at line {next_line_no})"
                )

            if len(args) >= 3 and len(next_args) >= 2:
                cmp_flag = args[2]
                jcc_flag = next_args[0]
                if cmp_flag != jcc_flag:
                    raise AsmSyntaxError(
                        f"CMP flag '{cmp_flag}' at line {line_no} does not "
                        f"match JCC flag '{jcc_flag}' at line {next_line_no}"
                    )
                cmp_flag_for_warn = cmp_flag
            else:
                cmp_flag_for_warn = None

            if (init_reg_name is not None and cmp_flag_for_warn is not None
                    and cmp_flag_for_warn == init_reg_name):
                cmp_init_warnings.append((line_no, cmp_flag_for_warn))

            jcc_label = next_args[-1]

            if block_stack:
                nesting_warnings.append((line_no, mnemonic))
                if (cmp_flag_for_warn is not None
                        and any(f == cmp_flag_for_warn
                                for f, _, _, _ in block_stack)):
                    shared_flag_warnings.append((line_no, mnemonic))

            block_stack.append(
                (cmp_flag_for_warn if cmp_flag_for_warn is not None else '?',
                 jcc_label, i + 1, True)
            )
            i += 2
            continue

        if canonical in JCC_MNEMONICS:
            independent_jcc_warnings.append((line_no, mnemonic))

            jcc_flag = args[0] if len(args) == 2 else None
            jcc_label = args[-1]

            if (init_reg_name is not None and jcc_flag is not None
                    and jcc_flag == init_reg_name):
                cmp_init_warnings.append((line_no, jcc_flag))

            if block_stack:
                nesting_warnings.append((line_no, mnemonic))
                if (jcc_flag is not None
                        and any(f == jcc_flag for f, _, _, _ in block_stack)):
                    shared_flag_warnings.append((line_no, mnemonic))

            block_stack.append(
                (jcc_flag if jcc_flag is not None else '?',
                 jcc_label, i, False)
            )
            i += 1
            continue

        i += 1

    if case_warnings:
        _print_case_warnings(case_warnings)
    if independent_jcc_warnings:
        _print_independent_jcc_warnings(independent_jcc_warnings)
    if unreferenced_labels:
        _print_unreferenced_label_warnings(unreferenced_labels)
    if nesting_warnings:
        _print_nesting_warnings(nesting_warnings, shared_flag_warnings)
    if empty_block_warnings:
        _print_empty_block_warnings(empty_block_warnings)
    if cmp_init_warnings:
        _print_cmp_init_warnings(cmp_init_warnings)


# ---------- Warning 打印 ----------
def _print_colored(color: str, lines: list[str]) -> None:
    """把多行文本用指定颜色打印。"""
    print(f'{color}' + '\n'.join(lines) + f'{RESET}')


def _print_cols(header: str, items: list[str], color: str = YELLOW) -> None:
    """把 items 按每行 3 项、列对齐打印成指定颜色的警告。"""
    width = max(len(s) for s in items)
    out = [header]
    for i in range(0, len(items), 3):
        chunk = items[i:i + 3]
        row = ', '.join(s.ljust(width) for s in chunk).rstrip()
        out.append(row)
    _print_colored(color, out)


def _print_case_warnings(warnings: list[tuple[int, str]]) -> None:
    items = [f'[Line {ln} | "{mn}"]' for ln, mn in warnings]
    header = (
        'Level 1 Warning: your code contains non-uppercase mnemonics. '
        'Uppercase mnemonics (e.g. "MOV") are recommended. '
        'The following mnemonics are not fully uppercase:'
    )
    _print_cols(header, items, YELLOW)


def _print_independent_jcc_warnings(warnings: list[tuple[int, str]]) -> None:
    items = [f'[Line {ln} | "{mn}"]' for ln, mn in warnings]
    header = (
        'Level 1 Warning: the following JCC commands are not paired with a CMP. '
        'They will be treated as pure JCC blocks:'
    )
    _print_cols(header, items, YELLOW)


def _print_unreferenced_label_warnings(warnings: list[tuple[int, str]]) -> None:
    items = [f'[Line {ln} | "{name}"]' for ln, name in warnings]
    header = (
        'Level 1 Warning: the following labels are defined but never referenced:'
    )
    _print_cols(header, items, YELLOW)


def _print_nesting_warnings(nesting: list[tuple[int, str]],
                            shared: list[tuple[int, str]]) -> None:
    items = [f'[Line {ln} | "{mn}"]' for ln, mn in nesting]
    header = (
        'Level 1 Warning: nested conditional blocks are not recommended, '
        'this will make the expression very long:'
    )
    _print_cols(header, items, YELLOW)

    if shared:
        items2 = [f'[Line {ln} | "{mn}"]' for ln, mn in shared]
        header2 = (
            'Level 1 Warning: nested conditional blocks share the same flag '
            'register, please make sure the flag is saved and restored manually:'
        )
        _print_cols(header2, items2, YELLOW)


def _print_empty_block_warnings(warnings: list[tuple[int, str]]) -> None:
    items = [f'[Line {ln} | label "{name}"]' for ln, name in warnings]
    header = 'Level 1 Warning: the following conditional blocks are empty:'
    _print_cols(header, items, YELLOW)


def _print_cmp_init_warnings(warnings: list[tuple[int, str]]) -> None:
    items = [f'[Line {ln} | flag "{f}"]' for ln, f in warnings]
    header = (
        'Level 2 Warning: the following CMP/JCC flag registers are the same '
        'as the INIT register. This may cause conflicts:'
    )
    _print_cols(header, items, LEVEL2)


def _print_d_write_warnings(warnings: list[tuple[int, str]]) -> None:
    items = [f'[Line {ln} | "{mn}"]' for ln, mn in warnings]
    header = (
        'Level 2 Warning: register D is used as a target. D is a constant '
        'register used for comparisons; please make sure it is restored to '
        '#-1e40 afterwards. The following lines write to D:'
    )
    _print_cols(header, items, LEVEL2)


# ---------- CMP / JCC 参数校验 ----------
def _validate_cmp_jcc(cmp_args, jcc_mnemonic, jcc_args):
    """校验 CMP + JCC 配对参数。"""
    err_label = jcc_args[-1] if jcc_args else None

    if len(cmp_args) != 3:
        return (('TemplateMismatchError', err_label), None)
    if len(jcc_args) != 2:
        return (('TemplateMismatchError', err_label), None)

    cmp_a, cmp_b, cmp_flag = cmp_args
    jcc_flag, jcc_label = jcc_args

    for arg in (cmp_a, cmp_b):
        if not _matches_type(arg, 'OPERAND'):
            return ((_err_type_for(arg), err_label), None)

    if not _matches_type(cmp_flag, 'WRITABLE'):
        return ((_err_type_for(cmp_flag), err_label), None)

    if not _matches_type(jcc_flag, 'BOOL'):
        return ((_err_type_for(jcc_flag), err_label), None)

    return (None, None)


def _validate_standalone_jcc(jcc_args):
    """校验独立 JCC 参数。"""
    err_label = jcc_args[-1] if jcc_args else None

    if len(jcc_args) != 2:
        return (('TemplateMismatchError', err_label), None)

    jcc_flag, jcc_label = jcc_args
    if not _matches_type(jcc_flag, 'BOOL'):
        return ((_err_type_for(jcc_flag), err_label), None)

    return (None, None)


# ---------- 写出 ----------
def _expand_line(result_line: str, init_reg, block_stack, line_no, mnemonic):
    """对一行展开后的文本套用 INIT 和 JCC 条件包裹。"""
    if init_reg is not None and '=' in result_line:
        left, right = result_line.split('=', 1)
        result_line = f"{left}={left}+{init_reg}({right}-{left})"

    if block_stack and '=' in result_line:
        left, right = result_line.split('=', 1)
        for flag, negate, _, _, _, _ in reversed(block_stack):
            flag_expr = f'(1-{flag})' if negate else flag
            right = f'{left}+{flag_expr}({right}-{left})'
        result_line = f'{left}={right}'

    return result_line


def write_asm(data, output_path: str) -> None:
    """按模板将解析结果写出到文件。"""
    _validate_templates(TEMPLATES)
    alias_map = _build_alias_map(ALIASES)

    label_ref_count: dict[str, int] = {}
    for item in data:
        mnemonic = item[1]
        args = item[2]
        if mnemonic.upper() in JCC_MNEMONICS and args:
            label = args[-1]
            label_ref_count[label] = label_ref_count.get(label, 0) + 1

    lines: list[str | None] = []
    init_reg = None
    init_failed = False
    block_stack: list[tuple[str, bool, str, int, int, bool]] = []
    label_error_count: dict[str, int] = {}
    d_write_warnings: list[tuple[int, str]] = []

    i = 0
    n = len(data)
    while i < n:
        item = data[i]
        line_no, mnemonic, args, raw_code = item

        # ----- label 定义行 -----
        if mnemonic == 'LABEL':
            label_name = args[0]
            label_index = i

            popped: list[tuple[str, bool, str, int, int, bool]] = []
            while block_stack and block_stack[-1][2] == label_name:
                popped.append(block_stack.pop())

            if any(entry[2] == label_name for entry in block_stack):
                raise AsmSyntaxError(
                    f"Semi-nested conditional block at label '{label_name}'"
                )

            err = label_error_count.get(label_name, 0)
            ref = label_ref_count.get(label_name, 0)

            if ref > 0 and err >= ref:
                lines.append(f"#!! {raw_code} ;ConditionalBlockError")
            elif popped:
                for entry in popped:
                    _, _, lab, jcc_idx, li, is_cmp = entry
                    is_empty = (label_index == jcc_idx + 1)
                    if is_empty:
                        if not is_cmp:
                            lines[li] = None
                    else:
                        if is_cmp:
                            lines[li] = (lines[li] or '') + f' #$ JCC {lab}'
                        else:
                            lines[li] = f'#$ JCC {lab}'

                outermost = popped[-1]
                outer_jcc_idx = outermost[3]
                outer_empty = (label_index == outer_jcc_idx + 1)
                if not outer_empty:
                    last_idx = -1
                    for k in range(len(lines) - 1, -1, -1):
                        if (lines[k] is not None
                                and not lines[k].startswith('#!!')):
                            last_idx = k
                            break
                    if last_idx >= 0:
                        lines[last_idx] = (
                            (lines[last_idx] or '')
                            + f' #$ JCC_END {label_name}'
                        )
            i += 1
            continue

        mnemonic_upper = mnemonic.upper()
        canonical = alias_map.get(mnemonic_upper, mnemonic_upper)

        # ----- CMP + JCC 配对 -----
        if canonical == 'CMP':
            jcc_item = data[i + 1]
            jcc_line_no, jcc_mnemonic, jcc_args, jcc_raw = jcc_item
            jcc_canonical = jcc_mnemonic.upper()

            err_info, _ = _validate_cmp_jcc(args, jcc_canonical, jcc_args)
            if err_info is not None:
                err_type, err_label = err_info
                try:
                    raise CmpJccValidationError(
                        f"{err_type} for CMP at line {line_no}"
                    )
                except AsmCompileError:
                    print(f'{RED}{traceback.format_exc()}{RESET}', end='')
                lines.append(f"#!! {raw_code} ;{err_type}")
                lines.append(f"#!! {jcc_raw} ;{err_type}")
                if err_label is not None:
                    label_error_count[err_label] = (
                        label_error_count.get(err_label, 0) + 1
                    )
                i += 2
                continue

            cmp_a, cmp_b, cmp_flag = args
            jcc_flag, jcc_label = jcc_args
            resolved_jcc_flag = _resolve_bool(jcc_flag)
            cond_expr = CONDITION_MACROS[jcc_canonical](cmp_a, cmp_b)
            negate = (jcc_canonical == 'JNE')

            lines.append(f'{cmp_flag}={cond_expr}:')
            block_stack.append(
                (resolved_jcc_flag, negate, jcc_label,
                 i + 1, len(lines) - 1, True)
            )

            if cmp_flag == 'D':
                d_write_warnings.append((line_no, mnemonic))

            i += 2
            continue

        # ----- 独立 JCC -----
        if canonical in JCC_MNEMONICS:
            err_info, _ = _validate_standalone_jcc(args)
            if err_info is not None:
                err_type, err_label = err_info
                try:
                    raise CmpJccValidationError(
                        f"{err_type} for JCC at line {line_no}"
                    )
                except AsmCompileError:
                    print(f'{RED}{traceback.format_exc()}{RESET}', end='')
                lines.append(f"#!! {raw_code} ;{err_type}")
                if err_label is not None:
                    label_error_count[err_label] = (
                        label_error_count.get(err_label, 0) + 1
                    )
                i += 1
                continue

            jcc_flag, jcc_label = args
            resolved_jcc_flag = _resolve_bool(jcc_flag)
            negate = (canonical == 'JNE')
            lines.append(None)
            block_stack.append(
                (resolved_jcc_flag, negate, jcc_label,
                 i, len(lines) - 1, False)
            )
            i += 1
            continue

        # ----- CMOV -----
        if canonical in CMOV_MNEMONICS:
            if len(args) != 3:
                err_type = 'TemplateMismatchError'
                try:
                    raise TemplateMismatchError(
                        mnemonic, 3, len(args),
                        line=line_no, token=1,
                    )
                except AsmCompileError:
                    print(f'{RED}{traceback.format_exc()}{RESET}', end='')
                lines.append(f"#!! {raw_code} ;{err_type}")
                i += 1
                continue

            flag, a, b = args

            err_type = None
            if not _matches_type(flag, 'WRITABLE'):
                err_type = _err_type_for(flag)
            elif not _matches_type(a, 'WRITABLE'):
                err_type = _err_type_for(a)
            elif not _matches_type(b, 'OPERAND'):
                err_type = _err_type_for(b)

            if err_type is not None:
                try:
                    exc_class = {
                        'CompileTypeError': CompileTypeError,
                        'RegisterNameError': RegisterNameError,
                    }[err_type]
                    if exc_class is CompileTypeError:
                        raise CompileTypeError(
                            flag if err_type else a,
                            'WRITABLE' if err_type else 'OPERAND',
                            line=line_no, token=1,
                        )
                    else:
                        raise RegisterNameError(
                            flag if err_type else a,
                            'WRITABLE' if err_type else 'OPERAND',
                            line=line_no, token=1,
                        )
                except AsmCompileError:
                    print(f'{RED}{traceback.format_exc()}{RESET}', end='')
                lines.append(f"#!! {raw_code} ;{err_type}")
                i += 1
                continue

            resolved_flag = _resolve_bool(flag) if flag in REG_ANY else flag
            resolved_b = (
                _format_constant(b) if b.startswith('#') else b
            )

            cond_expr = CMOV_CONDITION_MACROS[canonical](a, resolved_b)

            line1 = f'{resolved_flag}={cond_expr}:'
            line2 = f'{a}={a}+{resolved_flag}*({resolved_b}-{a}):'

            line1_expanded = _expand_line(
                line1, init_reg, block_stack, line_no, mnemonic
            )
            line2_expanded = _expand_line(
                line2, init_reg, block_stack, line_no, mnemonic
            )

            if resolved_flag == 'D':
                d_write_warnings.append((line_no, mnemonic))
            if a == 'D':
                d_write_warnings.append((line_no, mnemonic))

            if block_stack:
                is_cmp_block = block_stack[-1][5]
                if is_cmp_block:
                    target1 = line1.split('=', 1)[0]
                    target2 = line2.split('=', 1)[0]
                    if target1 == 'D' or target2 == 'D':
                        try:
                            raise KeyRegisterError(
                                f"Key register 'D' cannot be modified "
                                f"inside a CMP-JCC block",
                                line=line_no,
                                token=1,
                            )
                        except AsmCompileError:
                            print(
                                f'{RED}{traceback.format_exc()}{RESET}',
                                end=''
                            )
                        lines.append(
                            f"#!! {raw_code} ;KeyRegisterError"
                        )
                        i += 1
                        continue

            if block_stack:
                conflict = False
                for flag_expr, _, _, _, _, _ in block_stack:
                    t1 = line1_expanded.split('=', 1)[0]
                    t2 = line2_expanded.split('=', 1)[0]
                    if t1 == flag_expr or t2 == flag_expr:
                        try:
                            raise ConditionalBlockError(
                                f"Cannot modify flag register '{flag_expr}' "
                                f"inside conditional block",
                                line=line_no,
                                token=1,
                            )
                        except AsmCompileError:
                            print(
                                f'{RED}{traceback.format_exc()}{RESET}',
                                end=''
                            )
                        lines.append(
                            f"#!! {raw_code} ;ConditionalBlockError"
                        )
                        conflict = True
                        break
                if conflict:
                    i += 1
                    continue

            lines.append(line1_expanded)
            lines.append(line2_expanded)
            i += 1
            continue

        # ----- INIT 失败后，INIT_END 同步忽略 -----
        if canonical == 'INIT_END' and init_failed:
            lines.append(f"#!! {raw_code}")
            init_failed = False
            init_reg = None
            i += 1
            continue

        try:
            if canonical not in TEMPLATES:
                raise UnknownMnemonicError(
                    f"Unknown or unsupported mnemonic: '{mnemonic}'",
                    line=line_no,
                    token=1,
                )

            fmt, types = TEMPLATES[canonical]

            if len(args) != len(types):
                raise TemplateMismatchError(
                    mnemonic,
                    len(types),
                    len(args),
                    line=line_no,
                    token=1,
                )

            for j, (arg, t) in enumerate(zip(args, types)):
                token_no = j + 2
                if _matches_type(arg, t):
                    continue
                if arg in REG_ANY or arg.startswith('#'):
                    raise CompileTypeError(
                        arg, t, line=line_no, token=token_no
                    )
                raise RegisterNameError(
                    arg, t, line=line_no, token=token_no
                )

            final_args: list[str] = []
            for arg, t in zip(args, types):
                options = _split_type_spec(t)
                if 'BOOL' in options and _is_constant(arg):
                    final_args.append(_resolve_bool(arg))
                elif arg.startswith('#'):
                    final_args.append(_format_constant(arg))
                else:
                    final_args.append(arg)

            result_line = fmt.format(*final_args)

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

            target = result_line.split('=', 1)[0] if '=' in result_line else None

            if block_stack and target == 'D':
                is_cmp_block = block_stack[-1][5]
                if is_cmp_block:
                    raise KeyRegisterError(
                        f"Key register 'D' cannot be modified "
                        f"inside a CMP-JCC block",
                        line=line_no,
                        token=1,
                    )

            if target == 'D':
                d_write_warnings.append((line_no, mnemonic))

            if block_stack:
                if '=' not in result_line:
                    raise ConditionalBlockError(
                        f"Non-assignment command inside conditional block: "
                        f"'{mnemonic}'",
                        line=line_no,
                        token=1,
                    )
                for flag, _, _, _, _, _ in block_stack:
                    if target == flag:
                        raise ConditionalBlockError(
                            f"Cannot modify flag register '{flag}' "
                            f"inside conditional block",
                            line=line_no,
                            token=1,
                        )

            if init_reg is not None and '=' in result_line:
                left, right = result_line.split('=', 1)
                result_line = f"{left}={left}+{init_reg}({right}-{left})"

            if block_stack and '=' in result_line:
                left, right = result_line.split('=', 1)
                for flag, negate, _, _, _, _ in reversed(block_stack):
                    flag_expr = f'(1-{flag})' if negate else flag
                    right = f'{left}+{flag_expr}({right}-{left})'
                result_line = f'{left}={right}'

            lines.append(result_line + ':')

        except AsmCompileError as e:
            print(f'{RED}{traceback.format_exc()}{RESET}', end='')

            if canonical == 'INIT':
                init_failed = True
                lines.append(f"#!! {raw_code} ;{type(e).__name__}")
            elif canonical == 'INIT_END':
                init_reg = None
                init_failed = False
                lines.append(f"#!! {raw_code} ;{type(e).__name__}")
            else:
                lines.append(f"#!! {raw_code} ;{type(e).__name__}")

        i += 1

    final_lines = [ln for ln in lines if ln is not None]
    if final_lines and not final_lines[-1].startswith('#!!'):
        final_lines[-1] = final_lines[-1].replace(':', '', 1)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(f'#? Compiler_CALC_version_{COMPILER_VERSION}\n')
        if not (final_lines and final_lines[0] == 'x:'):
            f.write('x:\n')
        for line in final_lines:
            f.write(line + '\n')

    if d_write_warnings:
        _print_d_write_warnings(d_write_warnings)


# ---------- 测试 ----------
if __name__ == "__main__":
    text = """
; ===== 一级警告：非全大写 =====
mov A, B

; ===== CMOV 普通用法 =====
CMOVZ C, A, B
CMOVNZ C, A, B

; ===== JCC 在 INIT 内：合法 =====
INIT M
CMP A, B, C
JE C, L_INIT_OK
    ADD A, #1
L_INIT_OK:
INIT_END M

; ===== CMOV 在 CMP-JCC 块内 =====
CMP A, B, M
JE M, L1
    CMOVZ C, A, B
L1:
    SUB A, #1
"""

    parsed = parse_asm(text)
    print("\n解析结果（行号, 原始助记符, 参数, 原始文本）：")
    for row in parsed:
        print(row)

    output_file = './result.calc'
    write_asm(parsed, output_file)
    print(f"\n已写入文件：{output_file}")