# 测试报告（含 V0.2）

- 执行时间：2026-11-03（Asia/Shanghai）
- 环境：Linux Python 3.12.3 + pytest 9.2.0
- 命令：`PYTHONPATH=src python -m pytest tests -v`
- 结果：**23 passed / 0 failed**

## V0.1 用例（保留）

出入库数量、权限、禁止删流水、管制领用双人、调拨人工确认、预警、审计、备份权限、盘点差异、危险类别审核 — 全部 PASS。

## V0.2 新增回归 / 异常场景

| 用例 | 验证点 | 结果 |
|------|--------|------|
| test_p0_adjust_requires_dual_for_controlled | 调整绕过双人被拒 | PASS |
| test_p0_reversal_requires_dual_for_controlled | 冲正须双人 | PASS |
| test_p0_inventory_adjust_requires_dual_and_no_repeat_close | 盘点管制差异复核 + 禁重复关闭 | PASS |
| test_p0_inventory_blocks_mutations_and_settles_against_live_qty | 盘中锁库存 + live 结算 | PASS |
| test_p0_demo_forbidden_in_production | 正式禁演示数据/账户 | PASS |
| test_p0_production_rejects_demo_login_after_mode_lock | 模式锁定 | PASS |
| test_p0_full_backup_includes_sds_qr_and_hash | 完整备份与篡改检测 | PASS |
| test_p0_stock_and_audit_chain_and_atomic | 原子提交 + 哈希链 | PASS |
| test_p1_rejects_nan_inf_negative_and_disposed_reuse | 数值/状态机 | PASS |
| test_p1_viewer_cannot_stock_or_inventory | 权限 | PASS |
| test_p1_duplicate_inventory_line_rejected | 盘点行唯一 | PASS |

## 未自动化

见 `09_windows_verification.md`（EXE/断网/条码枪）。
