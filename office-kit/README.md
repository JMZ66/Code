# office-kit

给下游智能体用的 Word / Excel 解析、核对和最小改写工具。面向中文招投标文件、技术规范书、评分细则、合同和清单。

它回答三件事：这句话在文件的哪个锚点、多份文件里的数字和条款是否对得上、改一个 run 或一个单元格时其余部件有没有被动过。默认不调用模型，也不上传文件。

运行时依赖只有 lxml（BSD-3-Clause）、openpyxl（MIT）、xlrd（BSD-3-Clause）。选型说明见 [docs/TECH_SELECTION.md](docs/TECH_SELECTION.md)。调用方式、MCP 配置和规则列表见 [docs/调用说明.md](docs/调用说明.md)。

```bash
python -m pip install -r requirements.txt
python -m pytest
python -m office_kit mcp
```

与本仓库里尚未合并的 `bid-review` 审查助手不是同一个程序：那边是只读的桌面审查，这边是可被代理调用的库。本包不引用它的代码。

已知做不到的事情写在 [docs/已知限制.md](docs/已知限制.md)。
