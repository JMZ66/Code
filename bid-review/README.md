# 招投标文件审查助手

Offline, read-only checker for Chinese tender packages (DOCX, PDF, XLSX). It does not rewrite Word files, does not fill blanks, and does not call a cloud API.

中文使用说明见 [docs/用户手册.md](docs/用户手册.md)。第三方许可审查见 [docs/THIRD_PARTY_REVIEW.md](docs/THIRD_PARTY_REVIEW.md)。

## 它做什么

对一套招标/投标文件做只读审查：

- 建立文件、章节、段落、表格和来源位置索引；PDF 在文本层可读时给出页码
- 按指定 Word 模板检查已经写明的字体、字号、行距、页边距、分节、页眉页脚、编号和表头
- 检查未填写、模板残留、相邻重复、修订痕迹和批注
- 抽取项目名称、工期、金额、数量、单位、技术参数、资质和联合体表述
- 跨正文、预算、技术文件和合同做一致性比较
- 同一事项结合条件、单位和文件里写明的效力顺序判断；数字不同不等于冲突
- 每条问题带原文、文件名、章节、结构位置；能确定时带 PDF 页码
- 分类为确定错误、疑似冲突、缺少依据、需要人工判断
- 输出 Excel、HTML、Markdown 报告，并核对审查前后 SHA-256

不统一版式，不删除空行，不改编号，不重建表格，不编造法规、资质或技术标准。

## 合成测试集

`tests/corpus_builder.py` 会生成一套虚构的「滨江市第一人民医院信息化机房改造项目」文件，包含严格模板、隐藏在不同章节里的工期矛盾、金额/数量/单位不一致、条件不同因而不应报冲突的近似条款、缺失附件和资质等级差异、修订、批注、未填占位，以及文字相同但格式被改过的段落。金标写在同一文件的 `EXPECTED` / `NEGATIVES` 中。

指标定义：

- **漏报率** = 未按类别和证据命中的金标问题 / 金标问题数
- **误报率** = 命中了「不应报告」负样本的条数 / 负样本数
- **额外发现**单独计数，不放进误报率分母

在当前测试集上：

| 项目 | 结果 |
| --- | --- |
| 金标问题 | 28 |
| 负样本 | 15 |
| 漏报率 | **0**（0/28） |
| 误报率 | **0**（0/15） |
| 额外发现 | **0** |
| 报告条数 | 28（确定错误 25，疑似冲突 1，需要人工判断 1，缺少依据 1） |

这是可控合成集上的结果，不是对真实招标项目的现场准确率。限制见 [docs/已知限制.md](docs/已知限制.md)。

## 运行

```bash
cd bid-review
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
python -m bidreview self-test
python -m bidreview check --manifest 清单.json --out 审查输出
python -m bidreview
```

无参数启动图形界面。命令行也可以 `bidreview hash 文件.docx`。

Windows 便携目录由 `.github/workflows/bid-review.yml` 在 `windows-latest` 上用 PyInstaller 生成。本开发环境是 Linux，不能在这里打出 Windows EXE。标签 `bid-review-v*` 会把该 EXE 目录的 zip 传到 GitHub Release。

## 结构

```text
src/bidreview/
  docx_reader.py / pdf_reader.py / xlsx_reader.py   只读解析
  facts.py                                       字段与效力顺序
  checks.py                                      格式、残留、一致性
  engine.py                                      哈希、调度、报告
  report_writer.py                               xlsx / html / md
  cli.py / gui.py                                命令行与 Tkinter
tests/corpus_builder.py                          合成标书与金标
```

运行时依赖只有 lxml、openpyxl、pypdf，加上 Python 标准库。测试用 python-docx 和 reportlab 生成样本，不进入审查运行路径。
