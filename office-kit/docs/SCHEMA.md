# JSON 模型

机器可读的约束在 `schema/document.schema.json` 和 `schema/finding.schema.json`。下面是代理需要记住的约定。

## 源文件

每份结果都有 `source`：

- `path`、`filename`、`format`（`docx` / `doc` / `xlsx` / `xls` / `pdf`）
- `sha256`：原文件字节的 SHA-256，不是转换后的临时文件
- `size`
- `converter`：只有 `.doc` 经 LibreOffice 转成临时 docx 时才有，值为 `libreoffice`

`status`：

| 值 | 含义 |
| --- | --- |
| `ok` | 已解析 |
| `converter_unavailable` | `.doc` 但本机没有 LibreOffice，原文件未改 |
| `reserved` | PDF 接口已留，未抽取内容 |
| `error` | 包损坏或转换失败 |

解析结果是源文观察。只有核对报告里 `origin="inference"` 的条目才是推断。

## 锚点

锚点是稳定 ID，形式为 `部件名#路径`。

Word 正文示例：

```text
word/document.xml#/document/body[0]/p[3]/r[0]/t[0]
word/document.xml#/document/body[0]/tbl[0]/tr[1]/tc[0]
```

方括号里的数字是**同名兄弟中的 0 起序号**，不是 XPath 的 1 起序号。根元素写成 `/document`，不再加下标。

Excel：

```text
xl/worksheets/sheet1.xml#cell:B12
xl/worksheets/sheet1.xml#validation:F3:F5
```

`.xls` 没有 XML 部件，锚点是 `xls/工作表名#cell:B12`。行号、列号都按 Excel 界面的 1 起计。

引用一条证据时同时带上 `source.sha256` 和 `anchor`。只给文字不够。

## Word

`word.paragraphs[]` 按阅读顺序包含正文和表格内段落。

- `text_accepted`：接受修订后的文本（保留插入、去掉删除和移出）
- `text_original`：拒绝修订后的文本
- `number_label`：按 `numbering.xml` 算出的显示编号，例如 `第一章`、`1.1`、`（1）`。编号不在 `w:t` 里
- `display`：编号加正文，编号和正文之间用一个空格。`number_suffix` 仍保留 `tab` / `space` / `nothing`
- `heading_level`：1 起。来自 `outlineLvl` 或标题样式名
- `heading_path`：该段之前尚未结束的标题
- `formatting.resolved_east_asia`：经过 docDefaults、`basedOn`、段落 `rPr`、字符样式、run `rPr` 之后的东亚字体。写明的 `eastAsia` 优先于 `eastAsiaTheme`
- `runs[]`：每个 `w:t` / `w:delText` 的锚点，供最小改写

`word.tables[]` 只收顶层表。嵌套表在单元格的 `nested_tables`。`coverage` 把 `gridSpan` 和 `vMerge` 铺成网格，`origin_anchor` 指向占位的主单元格。

`word.sections[]` 按分节符切。页眉页脚按 `default` / `even` / `first` 分开，文本在对应部件里。

`word.comments[]` 含作者、正文，以及 `range_anchor`（批注范围所在段落）。

`word.revisions[]` 的 `kind` 可以是 `ins`、`del`、`moveFrom`、`moveTo`、`rPrChange`、`pPrChange`。

## Excel

`excel.sheets[]`：

- `state`：`visible` / `hidden` / `veryHidden`
- `merged_ranges`：如 `A1:D1`
- `hidden_rows`、`hidden_columns`
- `data_validations[]`：`sqref`、`type`、`formula1`、`formula2`
- `cells[]`：非空单元格。`formula` 是表达式（带 `=`），`cached_value` / `cached_text` 是文件里的缓存。本工具不算公式。`hidden_row` / `hidden_column` 标在单元格上，隐藏格仍然返回

## 核对发现

见 `finding.schema.json`。`origin` 只有 `source` 和 `inference`。`category` 用：确定错误、疑似冲突、缺少依据、需要人工判断。每条 `evidence` 至少有 `sha256`、`anchor`、`quote`。
