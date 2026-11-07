# 测量不确定度与分析方法验证助手

离线 Windows 桌面程序，目录独立于 `chem_warehouse`、`gcms_knowledgebase` 和 `lcms_knowledgebase`。

- 源码：`src/labuv`
- 手册与标准清单：`docs/`
- 示例：`src/labuv/data/examples`
- 测试：`PYTHONPATH=src python -m pytest tests -q`

发布包是完整便携目录的 zip。解压后运行 `LabUncertainty.exe`，不要只复制 exe。程序未签名。GitHub 的 Windows 构建机是 Windows Server，不是 Windows 10/11 桌面。

科学范围、未实现内容和许可见 `docs/已知限制.md`、`docs/标准与公式清单.md` 和 `docs/依赖许可.md`。
