# 技术选型

审查日期：2026-11-08。结论依据是各项目当时的公开许可证、PyPI/仓库说明和本工具实际要的能力（稳定锚点、编号还原、修订、最小 XML 改写）。没有把这些项目的源码复制进本仓库。许可不清楚的代码没有使用。

本包运行时只依赖三个宽松许可证库，外加 Python 标准库：

| 组件 | 本次开发环境版本 | 许可证 | 用途 |
| --- | --- | --- | --- |
| lxml | 6.1.3 | BSD-3-Clause | 读取 OOXML、还原 `numbering.xml`、样式继承、修订、批注、表格合并；只改指定元素后写回 |
| openpyxl | 3.1.5 | MIT | 读 XLSX 的公式、缓存值、合并、隐藏、批注、数据有效性、数字格式 |
| xlrd | 2.0.2 | BSD-3-Clause（许可证正文为 3 条；PyPI 元数据只写 BSD） | 读旧版 `.xls` 的缓存值、合并单元格、隐藏行列和表 |

测试额外使用 pytest（MIT）和 xlwt 1.3.0（BSD，只用来生成 `.xls` 样本，不进入运行时）。

选择这组的原因：招投标场景要的是“这句话在包内的哪个部件、哪一个元素”，以及改一个 run / 一个单元格时别的部件字节不变。这些都落在 OOXML 零件上。lxml 直接读零件，不重写整个文档模型。openpyxl 补上 Excel 的有效性、批注和格式，这些是纯 XML 行走也能做、但它已经维护好了。xlrd 是仍在 PyPI 上的 `.xls` 读取器。三者都是纯 Python 或带现成轮子的成熟库，安装不需要 Rust / JVM / .NET。

同一仓库里未合并的 `bid-review`（PR #15）已经用 lxml + openpyxl 做只读审查。本包不 import 它（它不在 `main` 上，而且是带界面的审查程序）。中文整数读法与那里的 `numbers.py` 使用同一套规则，在本包里单独实现。

## 点名项目

| 项目 | 是否存在 | 许可证 | 维护与能力 | 决定 |
| --- | --- | --- | --- | --- |
| python-docx | 存在，PyPI 1.2.0 | MIT | 适合生成 docx。不还原编号显示值，不把修订、批注范围、`gridSpan`/`vMerge` 和样式继承做成稳定锚点；保存时会重写包 | 运行时不用 |
| docx2python | 存在 | MIT | 把正文抽成嵌套列表，适合拿文本，不提供元素路径和修订模型 | 不用 |
| Mammoth | 存在 | BSD-2-Clause | docx 转 HTML，丢掉位置、修订和有效格式 | 不用 |
| Open XML SDK | 存在，`dotnet/Open-XML-SDK` | MIT | .NET 的 OOXML SDK，能处理编号、批注、修订。本工具是 Python，不附带运行时 | 不链接。元素名来自 ECMA-376，不是从 SDK 抄的 |
| Open-Xml-PowerTools | 存在 | MIT | .NET 的比较和清洗工具 | 不链接、不复制 |
| openpyxl | 存在 | MIT | 见上表 | **采用** |
| python-calamine | 存在，PyPI 0.9.x | MIT | Rust 绑定，读 xls/xlsx 值和合并，较新版本可选用读公式。不管数据有效性、批注和字体 | 不放进核心，避免再增加原生扩展。xlsx 用 openpyxl；xls 公式文本列为已知缺口 |
| xlrd | 存在 | BSD-3-Clause | 见上表。2.0 不再读 xlsx。公式文本、批注、数据有效性官方说明为不支持 | **采用**，只用于 `.xls` |
| Apache POI | 存在 | Apache-2.0 | Java | 不嵌入 JVM |
| Docling | 存在 | MIT | 版面分析和模型管线，依赖重，不是 OOXML 锚点工具 | 不用 |
| MarkItDown | 存在，微软 | MIT | 转 Markdown，丢失可回写的 XML 路径 | 不用 |
| Unstructured | 存在 | Apache-2.0 | 面向 NLP 的分块，依赖重，不保证元素级锚点 | 不用 |
| MinerU | 存在 | Apache-2.0 **另加**商业门槛和在线服务署名条款（以仓库 `LICENSE.md` 为准，不是纯 Apache，也不是 AGPL） | PDF/OCR 模型栈，和“最小改 docx/xlsx”不是同一件事 | 不用 |
| docx-trackdiff | 存在（2026-08 新建，体量很小） | MIT | 单脚本把两个 docx 做成修订红线。不成熟，且会生成新的修订文档，不是本工具要的“只改一个元素” | 不用、不复制 |
| docx-toolkit | **名字不唯一** | 不统一 | 检索到的是互不相关的小项目或代理技能，其中一个标注 MIT + Commons Clause。没有一个可当作稳定库来接 | 不用 |
| unoserver | 存在 | MIT | 常驻 LibreOffice 的服务。一次性转换不需要它 | 不 import。`.doc` 改为调用外部 `soffice`/`libreoffice` |

LibreOffice 本体是 MPL-2.0。它只作为可选外部进程，读的是临时副本，失败或未安装时明确返回 `converter_unavailable`，不把 MPL 代码链进本包。

没有把 GPL/AGPL 项目放进核心，也没有把上述库的源码内嵌进仓库。
