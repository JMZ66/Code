# 危化品仓库管理系统 V0.2

面向中国企业分析化学检测实验室的 **Windows 离线**危化品仓库管理软件。

技术栈：Python 3.10+ · PySide6 · SQLite（完全离线，无云端 API）。

**本软件是台账与流程辅助工具，不能仅凭自身满足全部危化品安全法定义务。**

## 功能

- 化学品电子台账；瓶级容器唯一编号与二维码
- 入库/领用/归还/调拨/处置/冲正（流水不可删除；hash 链）
- 管制品双人复核覆盖领用/归还/调拨/处置/**调整**/冲正/盘点差异
- 演示模式 / 正式模式锁定隔离（正式禁止演示账户与模拟数据）
- SDS 本地存档（含文件哈希）、已审核危险类别（**不做 AI 混储判定**）
- 预警、盘点 live 结算、完整备份（DB+SDS+QR+manifest）
- 用户权限、操作审计（与库存事务原子提交）

## 快速开始

```bash
cd chem_warehouse
pip install -r requirements.txt
export PYTHONPATH=src   # Windows: set PYTHONPATH=src
python -m chem_wh.main --mode demo          # 演示
# python -m chem_wh.main --mode production  # 正式（无预置账户）
```

演示模式账号（**仅 demo**）：

| 用户 | 密码 | 角色 |
|------|------|------|
| admin | Admin@123 | 管理员 |
| warehouse1 / warehouse2 | Wh@12345 | 库管 |
| safety1 | Sf@12345 | 安全员 |
| viewer1 | Vw@12345 | 只读 |

数据库默认：`~/.chem_warehouse/chem_warehouse.db`。

## 测试

```bash
export PYTHONPATH=src
python -m pytest tests -v
```

当前：**23 passed**。

## Windows EXE 打包

在 Windows 上执行 `scripts\build_windows.bat`。  
**云端 Linux 环境未完成本地 EXE 断网验证**，见 `docs/09_windows_verification.md`。

## 文档

| 文档 | 说明 |
|------|------|
| `docs/01_reference_review.md` | 参考项目与许可证（V0.2 已复核） |
| `docs/03_regulation_mapping.md` | 《危险化学品安全法》等映射 |
| `docs/06_test_report.md` | 测试报告 |
| `docs/07_compliance_gaps.md` | 合规缺口 |
| `docs/08_security_review_v02.md` | V0.2 安全审查与变更清单 |
| `docs/09_windows_verification.md` | Windows 验证状态 |

## 许可证声明

独立实现。参考项目仅作功能对照，未复制源代码。`mbmera/ChemicalManagementSystem` 无许可证声明，禁止复制其代码。
