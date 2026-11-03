# 开发计划 V0.1

## 里程碑

| 阶段 | 内容 | 交付物 |
|------|------|--------|
| M1 | 参考项目与许可证审查 | `01_reference_review.md` |
| M2 | 需求/模型/法规/计划 | docs 02–05 |
| M3 | 可运行最小系统 + 模拟数据 | `src/chem_wh`、种子数据 |
| M4 | 自动化测试 | `tests/` |
| M5 | Windows 打包配置 | `packaging/`、`scripts/build_windows.bat` |
| M6 | 测试报告与合规缺口 | `06_test_report.md`、`07_compliance_gaps.md` |

## V0.1 实现边界

优先交付可验证的库存与出入库核心；预警、SDS、权限、备份同步交付最小可用形态。禁忌混储规则引擎、监管备案导出、技防设备联动列入后续版本。

## 技术架构

```
UI (PySide6) → services (业务规则) → db (SQLite)
                 ↑
            pytest（无 GUI）
```

业务规则集中在 `services/`，GUI 仅调用服务，便于离线自动化测试与后续打包。
