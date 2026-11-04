# 危化品仓库管理系统 1.0.0

给分析化学实验室用的 **Windows 单机离线**试剂台账。界面是简体中文。不需要安装 Python，也不连接服务器。

**本软件不能替代危险化学品安全管理的法定职责、审批、备案或应急制度。** 相容性内容只保存管理员手工录入的备注，软件不会判断能不能混放。

## 给实验室同事

1. 从 [GitHub Releases](https://github.com/JMZ66/Code/releases) 下载便携版压缩包。
2. 解压，双击 `ChemWarehouse.exe`。
3. 第一次按向导创建管理员。没有预置账户，也没有示例试剂。
4. 用法见压缩包里的 `docs/用户手册.pdf`，或仓库里的 `docs/用户手册.md`。

演示模式默认关闭，并且使用另一份数据库。不要把演示库当成真实台账。

数据在当前用户目录的 `.chem_warehouse` 里。卸载或删除程序文件夹不会删掉这份数据。

## 给维护的人

技术选择：Python 3.12、PySide6、SQLite（WAL，`synchronous=FULL`）。界面和打包用 PyInstaller 的文件夹形式，而不是单文件，避免 Qt 插件解压不稳定。PDF 嵌入 Droid Sans Fallback（Apache-2.0），离线也能显示中文。

```bash
cd chem_warehouse
python -m pip install -r requirements.txt -r requirements-dev.txt
export PYTHONPATH=src
export QT_QPA_PLATFORM=offscreen
python -m pytest tests -q
python -m chem_wh.main
```

正式库默认路径：`~/.chem_warehouse/chem_warehouse.db`。  
演示库：`~/.chem_warehouse/demo/chem_warehouse_demo.db`（只有 `--demo` 或 `CHEM_WH_MODE=demo` 才会打开）。

Windows 打包：`scripts\build_windows.ps1`。持续集成见 `.github/workflows/chem-warehouse.yml`。测试记录见 `docs/测试报告.md`。

## 文档

| 文件 | 内容 |
|------|------|
| `docs/用户手册.md` | 给库管和实验人员 |
| `docs/测试报告.md` | 实际跑过的测试和还没在 Win10/11 桌面上做过的事 |
| `docs/03_regulation_mapping.md` | 法规对照，不是合规认证 |
| `docs/07_compliance_gaps.md` | 软件做不到的法定事项 |
