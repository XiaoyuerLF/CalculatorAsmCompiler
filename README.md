<div align="center">

## CalculatorAsmCompiler（CAC）
**CalculatorAsmCompiler（CAC）是一个将自定义汇编语法编译为计算器可执行表达式的编译器。它利用计算器的数值运算与精度特性，在计算器上模拟汇编程序运行，而不依赖 CPU 级汇编或机器码。项目由 @小鱼儿LF 开发，开发过程中使用 AIGC 辅助。**

<img src="https://img.shields.io/badge/版本-v0.2.6-green" alt="主版本: v0.2.6">
<a href="LICENSE">
  <img src="https://img.shields.io/badge/许可证-GPL--3.0-blue" alt="License" />
</a>

</div>

---

## 项目介绍

**重要：本项目还在开发调试阶段，部分功能还未完善。**
本项目主要使用Python语言开发。

**已实现的功能**
- [x] 汇编语法解析
- [x] 汇编指令翻译
- [x] 较完善的汇编指令集
  - [x] MOV指令
  - [x] 四则运算指令
  - [x] 条件跳转指令JCC
  - [x] 条件移动指令CMOV
  - [x] 更多指令见文档
- [x] 编译成品.calc文件的语法高亮
      
**未实现的功能（已有相关计划）**
- [ ] 命令行式编译
- [ ] 多模式编译
- [ ] 表达式自动压缩简化
- [ ] 成品表达式长度检查

**目前支持的计算器型号**
- [x] CASIO fx-991CN X全版本

**其他可能受支持的计算器（经测试后会移入“受支持”栏目）**
- [ ] CASIO fx-jp900系列（理论上支持，实际未测试）
- [ ] CASIO fx-991 CNCW (I / II) （可能支持，实际未测试）
- [ ] CASIO fx-999系列 （可能出现功能残缺）

## 环境要求

- Python 3.10+（编译器本体需要）
- MT管理器2.x；Android 5.0+（语法高亮需要）

## 仓库说明

- `/compiler.py`是当下最新版的编译器代码，**但不意味着稳定**
- `/history/`存放的是历史版本的编译器代码
- `/syntax/`存放的是用于MT管理器的.mtsx语法文件，用于.calc文件的语法高亮

## 常见问题

- Q:这个项目怎么来的？干什么的？
- A:首先，这是f吧/B站各大热衷于研究计算器的大佬们与我本人对计算器的深入研究共同整合而成的成果；其次，是为了简化计算器上的开发思路，降低开发成本；然后，也为的是其中（可能有）的教学价值

- Q:为啥仓库里一大堆版本，Release只发几个文件？
- A:仓库的/history目录存放的都是历史版本的编译器，Release里发的是我认为当下最新的稳定版本。因为AIGC可能要迭代两三个版本才能真正把一个功能改好。

- Q:语法文件.mtsx怎么用？
- A:通过[MT管理器官网](https://mt2.cn)下载最新版MT管理器，并下载.mtsx文件。在MT管理器内打开.mtsx文件，点击安装即表示文件已安装。目前MT管理器仅支持Android设备，VSCode等平台的语法解析将后期逐步跟进。

- Q:其他问题…
- A:可查看开发文档

## 使用方式

1. 从Release页面下载最新版本的编译器Python源码
2. 在您的系统上安装Python 3.10+（支持手机端Termux等终端环境）
3. 安装完毕之后，编辑.py文件，把文件尾部 `if __name__ == "__main__":` 后的 `text = """..."""`字符串改成你的汇编程序
4. 保存，运行.py文件，此时将在当前目录下生成一个 `result.calc` 文件，里面就是编译好的汇编程序（包含块标记和换行等便于阅读）

> 注意：目前的使用方式只是临时的，后期会添加命令行式的编译

示例：
```asm
; 条件移动
CMOVNZ C, A, B
; INIT块
INIT M
CMP A, B, C
JE C, L_INIT_OK
    ADD A, #1
L_INIT_OK:
INIT_END M
; JCC块
CMP A, B, M
JE M, L1
    CMOVZ C, A, B
L1:
; 减法指令
SUB A, #1
```
编译为
```text
x:
C=1-2^((Abs(A-B-1)-(A-B-1))²D):
A=A+C*(B-A):
M: #$ INIT
C=C+M(2^((A)²D):-C)
A=A+M(A+C*(1-A):-A)
M=1: #$ INIT_END
M=2^((A-B)²D): #$ JCC L1
C=C+M(2^((A)²D):-C)
A=A+M(A+C*(B-A):-A) #$ JCC_END L1
A=A-1
```

## 文档

请访问金山文档查看：[开发文档](https://www.kdocs.cn/l/chOG4LRbFy1h)。
文档还在持续更新完善中。
**若文档链接无法访问，请提交Issue告知。**
后续可能把文档重新整合为Markdown格式文档。


## 免责声明

- CalculatorAsmCompiler（下称“本项目”或“CAC”） 是一个由我（@小鱼儿LF，下称“我”“本人”）维护的开源项目，遵循 [GPL-3.0](https://www.gnu.org/licenses/gpl-3.0) 许可证，详情请参见 [LICENSE](./LICENSE) 文件。
- 本项目为自由及开源软件，旨在利用数学算法与精度特性，实现计算器上汇编算法模拟运行，主要用于汇编语言和数学算法的学习。
- 使用本软件时请遵守相关法律法规，严禁任何形式的滥用。
- 本项目仅进行本地编译，不涉及任何隐私信息收集与读写上传。
- 本软件按“原样”提供，不附带任何明示或暗示的担保，包括但不限于适销性或特定用途的适用性。
- 维护者不对因使用或无法使用本软件而导致的任何直接或间接损失负责。
- 本项目使用了 AIGC 辅助开发，但程序逻辑与设计由作者自行完成。
- 本项目与卡西欧（Casio Computer Co., Ltd.）无任何官方关联。

感谢您对 CalculatorAsmCompiler（CAC） 项目的支持与理解。

## 联系我们

- [@GitHub（小鱼儿LF）](https://github.com/XiaoyuerLF)
- [@Bilibili（小鱼儿LF）](https://b23.tv/iizwpyR)

## 贡献者

- 感谢fx-ms(es)吧内的各位大佬带我入坑了这个圈子。
- 感谢B站用户 @站在矮人的肩膀上 的[笔记](https://b23.tv/QgS9JiY)中对计算器图灵完备性的证明与设计，为本项目提供了设计思路。
- 感谢我自己（@小鱼儿LF）对这个项目的执着并写了开发文档。
- 感谢 DeepSeek 等 AIGC 工具在开发过程中提供代码辅助。



