import re


def parse_asm(text: str) -> list[tuple[str, list[str]]]:
    """
    解析汇编风格的多行字符串。

    规则：
    - 按换行符分割；
    - 丢弃空行、纯空白行、纯注释行；
    - 分号及其后内容全部视为注释并丢弃；
    - 按任意空白切分 token；
    - 第一个 token 为助记符，其余为参数；
    - 返回 [(助记符, 参数列表), ...]，保留原始顺序和重复项。
    """
    result: list[tuple[str, list[str]]] = []

    for line in text.splitlines():
        # 用 re.split 截断注释，maxsplit=1 表示只分割一次
        code = re.split(r';', line, maxsplit=1)[0]

        # 用 re.split 按任意空白切分，并过滤掉空字符串
        tokens = [t for t in re.split(r'\s+', code.strip()) if t]

        # 空行、纯空白行、纯注释行都会在这里被丢弃
        if not tokens:
            continue

        mnemonic = tokens[0]   # 第一个 token 作为助记符
        args = tokens[1:]      # 后面的 token 作为参数

        result.append((mnemonic, args))

    return result


def write_asm(data: list[tuple[str, list[str]]], output_path: str) -> None:
    """
    根据模板将解析后的汇编数据结构写入文件。

    :param data: parse_asm 的返回值，形如 [('mov', ['eax,', 'ebx']), ...]
    :param output_path: 输出文件路径，例如 './result.calc'
    """
    # 模板字典：助记符 -> 格式字符串
    # {0} 表示第一个参数，{1} 表示第二个参数，以此类推
    templates = {
        'mov': '{0}={1}',
        'add': '{0}={0}+{1}',
    }

    lines = []

    for mnemonic, args in data:
        # 清理参数：去掉末尾的逗号，用于填充模板
        cleaned_args = [arg.rstrip(',') for arg in args]

        if mnemonic in templates:
            tmpl = templates[mnemonic]
            try:
                # 尝试用清理后的参数填充模板
                line = tmpl.format(*cleaned_args)
            except (IndexError, KeyError):
                # 参数数量不匹配，按不匹配处理
                line = '#!! ' + mnemonic
                if args:
                    line += ' ' + ' '.join(args)
        else:
            # 没有对应模板，用 # 开头原样保留
            line = '#' + mnemonic
            if args:
                line += ' ' + ' '.join(args)

        lines.append(line)

    # 写入文件，每行末尾换行
    with open(output_path, 'w', encoding='utf-8') as f:
        for line in lines:
            f.write(line + '\n')


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