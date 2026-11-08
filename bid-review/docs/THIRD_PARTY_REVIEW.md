# 第三方项目与依赖审查

审查日期：2026-11-08。结论依据是各仓库当时的公开说明、许可证字段和目录，不是对每个提交的逐行审计。

本目录下的审查程序是新写的。下面这些仓库都没有被复制进源码，也没有作为运行时依赖安装。许可不清楚的代码没有使用。

## 任务点名的参考项目

### AZ123IT/BidGuard-AI

- 仓库存在。GitHub 许可证字段为 **MIT**。
- 实际内容是 FastAPI + Next.js + SQLite/pgvector 的检索问答和风险规则演示，文档处理覆盖 PDF 文本和轻量 DOCX/TXT。可选路径使用 OpenAI 兼容的 embedding 和 LLM（说明里包括 Ollama 与 DeepSeek）。
- 它不是离线的版式审查器，也不能保证原 Word 不被改写这一目标。不引用、不打包。

### heavenoracle/han-docx-lint

- 仓库存在。许可证 **MIT**。仓库体积很小（API 显示约 38 KB 量级）。
- 实际能力：本地、无第三方运行库的命令行，直接读 OOXML，检查学术 DOCX 的占位词、重复标点、中英空格、过长段落、空段、参考文献标题和标题样式。明确不改文件、不上传。
- 它不抽取工期和金额，不做跨文件效力和预算表比对。思路（只读 OOXML、占位符可配置）与本工具一致，实现没有抄它的代码，而是按招标审查重写。

### zwt0204/standardize-docx-format

- 仓库存在。GitHub 许可证字段为空。README 写明：**当前仓库未附加开源许可证。未经版权所有者明确授权，默认保留全部权利。**
- 实际能力是按模板改写 DOCX（套用格式、修复计划、重排）。这与“默认不改原文件”相反。
- **未复制任何文件，未改写使用。**

### dotnet/Open-XML-SDK

- 仓库存在。许可证 **MIT**（.NET Foundation）。
- 它是 .NET 的 Office Open XML SDK，能读写 DOCX 的样式、分节、编号、批注和修订。本工具是 Python 程序，不附带 .NET 运行时，因此不引用该包。
- 段落、`sectPr`、`styles`、`numbering`、`comments`、`w:ins` / `w:del` 这些名称来自 ECMA-376 / OOXML，不是从 SDK 源码抄来的。

### ShayHill/docx2python

- 仓库存在。许可证 **MIT**。PyPI 描述为从 DOCX 抽取页眉页脚、正文、脚注和图片。
- 它适合抽取文本，不直接提供“相对模板的字体、行距、分节、修订是否仍生效”的审查。为了位置稳定且少一个依赖，DOCX 由本工具用 lxml 只读解析。未复制其源码。

### tender-eval-ai/tender-evaluation-assistant

- 仓库存在。许可证 **AGPL-3.0**。
- 实际是一套投标评审流水线：从招标 PDF 建条款树和规则，再对投标（含扫描件）做抽取、评分并导出 Word。README 说明演示配置使用云端 API 或本地 vLLM/Ollama，并警告不要把真实标书送进云端。测试规模大，但是另一类产品。
- 不依赖、不链接、不复制。AGPL 的传染范围也使它不适合被包进这个 MIT 工具。

## 实际使用的库

运行时（随程序安装，源码不内嵌这些库的实现）：

| 组件 | 版本（开发环境） | 许可证 | 用途 |
| --- | --- | --- | --- |
| lxml | 6.1.3 | BSD-3-Clause | 只读解析 OOXML |
| openpyxl | 3.1.5 | MIT | 只读 XLSX；写出审查报告 xlsx |
| pypdf | 7.0.0 | BSD-3-Clause | 只读 PDF 文本层和页码 |

测试和样本生成（不进入 `BidReview.exe` 的审查路径；PyInstaller spec 排除了它们）：

| 组件 | 许可证 | 用途 |
| --- | --- | --- |
| pytest | MIT | 测试 |
| python-docx | MIT | 生成合成 DOCX。审查器不调用它来打开用户文件 |
| reportlab | BSD | 用内置 CID 字体名 STSong-Light 生成带文本层的合成 PDF。没有随仓库分发字体文件 |

Python 标准库（argparse、hashlib、tkinter、zipfile、json、html）没有额外许可文本。Tkinter 在 Windows 官方 Python 安装中自带，界面用它而不是 Qt。

打包只在 GitHub Actions 里执行：

- **PyInstaller** 使用 GNU GPL-2.0-or-later，并带有官方 bootloader 例外，允许用它生成非 GPL 的可执行文件。这里不把 PyInstaller 源码放进仓库。应用程序自身的代码保持 MIT。例外的原文以 PyInstaller 仓库的 `COPYING.txt` 为准：<https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt>。

## 分发时要保留的声明

- 本目录 `LICENSE`（MIT）覆盖 `src/bidreview` 和文档。
- `docs/licenses/MIT.txt`、`docs/licenses/BSD-3-Clause.txt` 是上述运行时库使用的许可证文本。
- 若再发布 Windows 目录，请连同 `docs/` 和 `LICENSE` 一起分发。

没有把 WenQuanYi、Noto 或其他字体打进程序。合成 PDF 的中文依赖 ReportLab 已注册的 STSong-Light 名称，仅用于测试样本。
