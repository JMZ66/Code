# 测试报告 V0.1

- 执行时间：2026-11-03（Asia/Shanghai）
- 环境：Linux Python 3.12.3 + pytest 9.2.0
- 命令：`PYTHONPATH=src python -m pytest tests -v`
- 结果：**12 passed / 0 failed**（约 3.7s）

## 覆盖范围

| 用例 | 验证点 | 结果 |
|------|--------|------|
| test_login_and_permission | 登录成功/失败、角色权限拒绝 | PASS |
| test_inbound_issue_quantity_tracking | 领用/归还数量结余正确 | PASS |
| test_insufficient_stock | 超额领用抛错 | PASS |
| test_cannot_delete_transactions | 禁止删除流水 | PASS |
| test_dual_control_required_for_precursor | 管制品须双人；同账户拒绝 | PASS |
| test_transfer_requires_human_compat_confirm | 调拨须人工确认相容性 | PASS |
| test_alerts_cover_expiry_low_missing_sds | 过期与缺 SDS 预警 | PASS |
| test_audit_log_on_login_and_stock | 登录与出入库审计 | PASS |
| test_backup_and_restore | 备份恢复 | PASS |
| test_viewer_cannot_backup | 只读无权备份 | PASS |
| test_inventory_variance_posts_adjustment | 盘点差异生成调整事务 | PASS |
| test_hazard_must_be_approved | 仅已审核危险类别可关联 | PASS |

## 未自动化（需人工/Windows）

- PySide6 图形界面交互与条码枪楔入
- PyInstaller 生成 EXE 后的安装启动
- Excel/PDF 中文字体在目标机显示效果
- 真实管制品制度流程的业务验收

## 结论

V0.1 核心库存事务、权限、双人复核、审计与备份逻辑可验证通过，满足“可独立运行的库存与出入库系统”交付门槛。
