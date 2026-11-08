# 招投标文件审查助手（Bid Review Assistant）

Windows **完全离线**的中文招投标文件**只读**审查工具。  
优先可靠核查，不自动改写 Word，不上传文件，不调用云端 API。

## 功能

1. 导入多个 DOCX / PDF / XLSX，建立文档·章节·段落·表格·来源位置索引  
2. 对照官方 Word 模板检查字体、字号、行距、页边距、分节、页眉页脚、表格结构等  
3. 检查未填写占位、缺失章节、重复段落、修订痕迹与批注  
4. 抽取项目名称、工期、金额、数量单位、技术指标、资质、联合体等字段  
5. 跨文件一致性检查；结合上下文条件与效力顺序，避免“数值不同=矛盾”的误判  
6. 问题带原文、文件名、章节、结构位置；PDF 尽量给页码  
7. 严重程度：确定错误 / 疑似冲突 / 缺少依据 / 需要人工判断  
8. 输出 Excel、HTML、Markdown（及 JSON）报告  
9. 原始文件 SHA-256 校验，确保核查前后字节不变  

## 快速开始

```bash
cd bid_review_assistant
python -m pip install -r requirements.txt
export PYTHONPATH=src   # Windows: set PYTHONPATH=src
python -m bid_review --gui
# 或
python -m bid_review 招标正文.docx 合同.docx 预算.xlsx -t 官方模板.docx -o 审查输出
```

## 测试

```bash
python -m pip install -r requirements-dev.txt
python scripts/build_fixtures.py
PYTHONPATH=src python -m pytest tests -q
python scripts/eval_detection.py
```

## Windows 打包

在 Windows 上执行：

```powershell
.\scripts\build_windows.ps1
```

产物：`dist/BidReviewAssistant-windows-x64.zip`。

## 文档

- [用户手册](docs/用户手册.md)
- [测试报告](docs/测试报告.md)
- [第三方与许可证](docs/第三方与许可证.md)

## 严格限制

- 默认不对原始 Word 写操作  
- 不擅自统一格式、删空白、改编号、重建表格  
- 不编造招标要求、资质或法律标准  
- 无依据空缺不自动填写  
- AI/规则判断受证据约束；无法确认转人工  

## 许可证

MIT。详见 `LICENSE` 与 `docs/第三方与许可证.md`。
