# 危化品仓库管理系统 V0.1

面向中国企业分析化学检测实验室的 **Windows 离线**危化品仓库管理软件。

技术栈：Python 3.10+ · PySide6 · SQLite（完全离线，无云端 API）。

## 功能（V0.1）

- 化学品电子台账（名称/CAS/浓度/规格/厂家/批次/有效期）
- 瓶级容器唯一编号与二维码
- 入库/领用/归还/调拨/处置事务（流水不可删除）
- 仓库-分区-柜-层位置与储存条件
- SDS 本地存档与审核状态
- 已审核危险类别标识（**不做 AI 混储判定**）
- 过期/低库存/超核定/缺 SDS 预警
- 库存汇总、流水、月消耗、盘点差异
- 用户权限、操作审计、备份恢复
- 管制品双人独立账户复核

## 快速开始

```bash
cd chem_warehouse
pip install -r requirements.txt
export PYTHONPATH=src   # Windows: set PYTHONPATH=src
python -m chem_wh.main
```

演示账号：

| 用户 | 密码 | 角色 |
|------|------|------|
| admin | Admin@123 | 管理员 |
| warehouse1 / warehouse2 | Wh@12345 | 库管 |
| safety1 | Sf@12345 | 安全员 |
| viewer1 | Vw@12345 | 只读 |

首次启动自动写入模拟试剂数据。数据库默认：`~/.chem_warehouse/chem_warehouse.db`。

## 测试

```bash
export PYTHONPATH=src
python -m pytest tests -v
```

## Windows EXE 打包

在 Windows 上执行 `scripts\build_windows.bat`，产物为 `dist\ChemWarehouse.exe`。

## 文档

| 文档 | 说明 |
|------|------|
| `docs/01_reference_review.md` | 参考项目与许可证审查 |
| `docs/02_requirements.md` | 需求规格 |
| `docs/03_regulation_mapping.md` | 法规功能对应清单 |
| `docs/04_database_model.md` | 数据库模型 |
| `docs/05_development_plan.md` | 开发计划 |
| `docs/06_test_report.md` | 测试报告 |
| `docs/07_compliance_gaps.md` | 未完成安全合规事项 |

## 许可证声明

本项目为独立实现。参考项目（open_enventory AGPL-3.0、grocy MIT 等）**仅作功能对照，未复制其源代码**。
