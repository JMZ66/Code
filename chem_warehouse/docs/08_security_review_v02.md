# V0.2 安全审查报告与变更清单

审查基准：V0.1 静态代码审查发现的 P0/P1 问题。  
验证环境：Linux Python 3.12 + pytest（2026-11-03，Asia/Shanghai）。  
**本软件不能仅凭自身声称满足全部危化品安全法规。**

## 1. 问题复现与修复验证

| ID | 问题 | 复现要点 | 修复 | 回归测试 | 结果 |
|----|------|----------|------|----------|------|
| P0-1 | 管制品可通过 `adjust_*` / 盘点差异 / 冲正绕过双人复核 | 对丙酮直接 `adjust_neg` 无复核人 | `DUAL_CONTROL_TX_TYPES` 覆盖 adjust/reversal/return；盘点关闭预检管制差异 | `test_p0_adjust_*` / `test_p0_reversal_*` / `test_p0_inventory_adjust_*` | PASS |
| P0-2 | 演示账户/固定密码/模拟数据可进入“正式”使用 | `ensure_seed` 无条件执行 | `app_mode` 锁定；production 禁 seed/demo 用户/弱密码 | `test_p0_demo_forbidden_*` / mode lock | PASS |
| P0-3 | 盘点可重复关闭、差异按旧账面结算 | 关闭两次；盘中改库存 | `closing/closed` + `adjustments_posted`；按 live qty 结算；盘中禁变更 | `test_p0_inventory_*` | PASS |
| P0-4 | 备份仅 DB，无 SDS/QR/哈希 | 仅 `.db` 拷贝 | ZIP 含 DB+sds+qr+manifest sha256；恢复前校验 | `test_p0_full_backup_*` | PASS |
| P0-5 | 事务与审计非原子；流水可静默改 | 审计在 commit 后另写 | 同事务写入；hash 链；明确管理员可直改 DB 的剩余风险 | `test_p0_stock_and_audit_chain_*` | PASS |
| P1 | 数值/状态/权限校验不足 | NaN、已处置再入库、viewer 写库存 | 校验与状态机加强 | `test_p1_*` | PASS |

自动化总计：**23 passed**（含 V0.1 原有用例，未删除）。

## 2. 变更清单（代码）

- `db/schema.py` / `database.py`：settings、hash 字段、盘点状态、qty_version、migrations
- `services/stock.py`：双人范围、冲正、hash 链、盘点锁、状态机、原子审计
- `services/inventory_count.py`：单次关闭、live 结算、管制差异复核
- `services/backup.py`：完整 ZIP 备份/校验/恢复
- `services/settings.py`、`seed.py`、`auth.py`、`chemicals.py`、`app_context.py`、`main.py`：模式隔离
- `utils/integrity.py`：文件/链式哈希
- `tests/test_v02_security.py`：回归与异常场景
- 文档：`03`/`01` 更新，`08`/`09`/`06` 增补

## 3. 剩余风险（必须告知）

1. **本地 SQLite 可被拥有文件系统权限的管理员直接修改**；hash 链只能检测应用路径外的篡改痕迹，不能对抗有意删库/改库后重算链或替换程序。
2. 无磁盘加密、无 HSM/智能卡签名；密码仅本地 PBKDF2。
3. 双人复核是**应用层账户隔离**，不能替代现场双人双锁与监控。
4. 管制目录、禁忌配存、备案报送仍依赖单位人工维护与外部流程。
5. **Windows EXE 断网安装验证：本云环境为 Linux，未在本轮实际完成**（见 `09_windows_verification.md`）。

## 4. 合规声明

修复提升了台账防绕过与审计完整性，但**不等于**符合《危险化学品安全法》及配套标准的全部义务。单位仍须履行许可、备案、现场管理与专业审核。
