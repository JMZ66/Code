# 招投标文件审查助手 1.0

Windows **单机离线** 的中文招投标文件 **只读** 审查工具。用于核查 DOCX / PDF / XLSX 的格式符合性、占位残留与跨文件一致性，**不改写原文件**，不上传企业文档，不调用云端 API。

## 给业务同事

1. 从 [GitHub Releases](https://github.com/JMZ66/Code/releases) 下载 `BidReviewAssistant` 便携包。
2. 解压后双击 `BidReviewAssistant.exe`。
3. 添加招标正文、预算表、技术附件、合同等文件；可选指定官方 Word 模板。
4. 点击「开始只读审查」，在报告目录查看 Excel / HTML / Markdown 报告。

详细步骤见 `docs/使用说明.md`。

## 能力概览

| 能力 | 说明 |
|------|------|
| 结构索引 | 文档 / 章节 / 段落 / 表格 / 来源位置；PDF 尽量给页码 |
| 格式审查 | 对照模板或 JSON：字体、字号、行距、页边距、分节、页眉页脚、表格结构 |
| 占位残留 | 未填、空白填空、修订痕迹、批注、重复占位 |
| 字段抽取 | 项目名称、工期、金额、数量、单位、技术指标、资质、联合体等 |
| 一致性 | 跨文件比对；结合条件句与效力顺序，避免“数字不同就判矛盾” |
| 严重程度 | 确定错误 / 疑似冲突 / 缺少依据 / 需要人工判断 |
| 完整性 | 核查前后 SHA-256，原文件必须不变 |

## 给维护者

```bash
cd bid_review_assistant
python -m pip install -r requirements.txt -r requirements-dev.txt
export PYTHONPATH=src
python scripts/build_fixture_pack.py
python -m pytest tests -q
python -m bid_review.main --gui
# 或 CLI：
python -m bid_review.main 文件1.docx 文件2.xlsx -t 模板.docx -o ./reports
```

Windows 打包：`scripts\build_windows.ps1`。CI 见 `.github/workflows/bid-review-assistant.yml`。

## 开源参考与许可证结论

本项目 **自行实现** 核心逻辑，未复制授权不明代码。调研结论：

| 项目 | 许可 | 处理 |
|------|------|------|
| AZ123IT/BidGuard-AI | MIT | 仅参考“证据优先”产品方向；其为 Web/向量库架构，不适合本离线只读工具 |
| heavenoracle/han-docx-lint | MIT | 参考只读 OOXML / 占位检查思路，**未复制其源码** |
| zwt0204/standardize-docx-format | **无许可** | **不复制** |
| dotnet/Open-XML-SDK | MIT | C# SDK；本项目用 python-docx + lxml |
| ShayHill/docx2python | MIT | 可选思路；当前未作为硬依赖 |
| tender-eval-ai/tender-evaluation-assistant | **AGPL-3.0** | **不复制代码**；评标场景不同 |

第三方运行时依赖见 `docs/第三方说明.md`。

## 限制（请先读）

- 不是自动排版 / 自动改标工具。
- 不编造法规、资质标准或技术指标；缺依据只标“缺少依据”。
- PDF 文本层质量依赖原文件；扫描件无文字层时无法可靠抽取。
- 一致性判断基于规则与启发式，复杂法务表述仍需人工。
- 本仓库 CI 的 Windows 打包跑在 GitHub `windows-latest` 服务器上，**不等于**已在每台 Win10/11 桌面人工点验。

## 许可证

MIT（见 `LICENSE`）。
