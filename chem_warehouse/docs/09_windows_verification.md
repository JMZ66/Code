# Windows 验证

V1.0.0 以 `docs/测试报告.md` 和发布包里的 `windows-verification.txt` 为准。在该文件由 Windows 工作流写出来之前，不能把 EXE 断网运行写成已经通过。

以下是 V0.2 留下的记录。

# Windows EXE / 离线验证状态（V0.2）

## 已提供

- `packaging/chem_warehouse.spec`（PyInstaller）
- `scripts/build_windows.bat`（于 Windows 10/11 + Python 3.10+ 执行）

## 本轮云环境验证结果

| 项目 | 状态 | 说明 |
|------|------|------|
| 在 Windows 上实际构建 EXE | **未验证** | 当前代理运行于 Linux，无 Windows 构建机 |
| 断网启动 EXE | **未验证** | 依赖上项 |
| 安装/杀毒白名单 | **未验证** | 需目标环境人工完成 |
| 条码枪楔入 GUI | **未验证** | 需 Windows 桌面 |
| Linux 自动化业务测试 | **已通过** | `pytest` 23 passed |
| 无 GUI 业务冒烟（seed/报表） | **已通过** | 见开发过程冒烟 |

## 建议验收步骤（目标 Windows 机）

1. 安装 Python 3.10+，执行 `scripts\build_windows.bat`
2. 断开网络，运行 `dist\ChemWarehouse.exe --mode production`
3. 创建正式管理员（强密码），确认无演示账户
4. 导入真实数据后做双人复核与备份恢复抽检
5. 记录杀毒软件误报与依赖 DLL 问题

**未完成上述步骤前，不得声称“已完成 Windows 离线运行包验证”。**
