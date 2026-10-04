import re
import traceback
from string import Formatter


# ---------- 异常定义 ----------

class AsmCompileError(Exception):
    """汇编编译相关错误的基类。"""
    pass


class CompileTemplateError(AsmCompileError):
    """模板编译相关错误的基类。"""
    pass


class UnknownMnemonicError(CompileTemplateError):
    """未知的助记符，或当前未支持的助记符。"""
    def __init__(self, mnemonic: str, operands: list[str]):
        self.mnemonic = mnemonic
        self.operands = operands
        super().__init__(f"Unknown or unsupported mnemonic: '{mnemonic}'")


class TemplateMismatchError(CompileTemplateError):
    """模板参数数量不匹配。"""
    def __init__(self, mnemonic: str, expected: int, given: int):
        self.mnemonic = mnemonic
        self.expected = expected
        self.given = given
        super().__init__(
            f"Template for '{mnemonic}' needs {expected} arguments but {given} given"
        )


# ---------- 解析 ----------

def parse_asm(text: str) -> list[tuple[str, list[str]]]:
    """
    解析汇编风格的多行字符串，返回 [(助记符, 参数列表), ...]，
    保留原始顺序和重复项。
    """
    result: list[tuple[str, list[str]]] = []

    for line in text.splitlines():
        # 分号及其后内容全部丢弃
        code = re.split(r';', line, maxsplit=1)[0]

        # 按任意空白切分并过滤空字符串
        tokens = [t for t in re.split(r'\s+', code.strip()) if t]

        # 空行、纯空白行、纯注释行丢弃
        if not tokens:
            continue

        mnemonic = tokens[0]
        args = tokens[1:]
        result.append((mnemonic, args))

    return result


# ---------- 编译写出 ----------

def _count_template_args(template: str) -> int:
    """
    统计模板中不同占位符的个数。
    例如 '{0}={1}' -> 2，'{0}={0}+{1}' -> 2。
    """
    fields = {field for _, field, _, _ in Formatter().parse(template) if field is not None}
    return len(fields)


def write_asm(data: list[tuple[str, list[str]]], output_path: str) -> None:
    """
    根据模板将解析后的汇编数据结构写入文件。

    - 模板匹配成功 -> 写展开结果；
    - 未知助记符   -> 打印 Traceback，写 '#mnemonic args'；
    - 参数不匹配   -> 打印 Traceback，写 '#!! mnemonic args'；
    - 每行独立处理，一行出错不影响其它行。
    """
    templates = {
        'mov': '{0}={1}',
        'add': '{0}={0}+{1}',
    }

    lines: list[str] = []

    for mnemonic, args in data:
        # 去掉参数末尾的逗号，用于填充模板
        cleaned_args = [arg.rstrip(',') for arg in args]

        try:
            if mnemonic not in templates:
                raise UnknownMnemonicError(mnemonic, args)

            tmpl = templates[mnemonic]
            expected = _count_template_args(tmpl)
            if len(cleaned_args) != expected:
                raise TemplateMismatchError(mnemonic, expected, len(cleaned_args))

            line = tmpl.format(*cleaned_args)

        except UnknownMnemonicError:
            traceback.print_exc()
            line = '#' + mnemonic
            if args:
                line += ' ' + ' '.join(args)

        except TemplateMismatchError:
            traceback.print_exc()
            line = '#!! ' + mnemonic
            if args:
                line += ' ' + ' '.join(args)

        lines.append(line)

    with open(output_path, 'w', encoding='utf-8') as f:
        for line in lines:
            f.write(line + '\n')


# ---------- 测试 ----------

if __name__ == "__main__":
    text = """
mov   eax, ebx   ; 把 ebx 移到 eax
add eax, 1
; 这一行只有注释

ret
mov ecx;comment
"""

    parsed = parse_asm(text)
    print("解析结果：")
    print(parsed)

    output_file = './result.calc'
    write_asm(parsed, output_file)
    print(f"\n已写入文件：{output_file}")