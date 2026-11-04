# LCMS_KnowledgeBase

离线 Windows 桌面程序，用来浏览 LC-MS 的 mzML / mzXML，并建立自己的谱库。界面是简体中文。

本目录可以单独构建，不依赖仓库里的其他项目。

- 使用说明：[docs/使用说明.md](docs/使用说明.md)
- 测过什么、没测过什么：[docs/兼容性说明.md](docs/兼容性说明.md)
- 测试：[docs/测试报告.md](docs/测试报告.md)
- 许可证：[docs/许可证审计.md](docs/许可证审计.md) 与 [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)

开发：

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
python -m lcms_kb
```

Windows 便携目录：

```bat
scripts\build_windows.bat
dist\LCMS_KnowledgeBase\LCMS_KnowledgeBase.exe --self-test
```
