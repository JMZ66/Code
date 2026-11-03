# 参考项目审查报告（V0.1）

> 审查原则：仅借鉴功能与设计思路，**禁止复制第三方源代码**。本项目采用独立实现（Python + PySide6 + SQLite）。

## 1. rudolphi/open_enventory

| 项 | 内容 |
|---|---|
| 地址 | https://github.com/rudolphi/open_enventory |
| 技术栈 | PHP / MySQL，浏览器端 ELN + 化学品库存 |
| 许可证 | **AGPL-3.0**（传染性 copyleft；商标 “open enventory” 受保护） |
| 可借鉴功能 | 容器级试剂管理、CAS/位置检索、安全数据关联、出入库流转 |
| 不可照搬 | 全部源码与品牌标识；因 AGPL 与本离线桌面产品形态不符，仅作需求对照 |
| 结论 | **不引入代码**。借鉴“瓶级追踪 + 安全信息绑定”的领域概念。 |

## 2. mbmera/ChemicalManagementSystem

| 项 | 内容 |
|---|---|
| 核查结果 | **公开仓库未找到**（2026-11 检索）。作者公开项目为 `mbmera/LEMS`（实验室设备管理系统，Streamlit + SQLite） |
| 可借鉴思路 | 桌面/本地 SQLite、Excel 导出、到期预警、Windows 部署 |
| 结论 | **无可用源码可复制**；仅参考“本地 SQLite + 预警仪表盘”产品形态。 |

## 3. grocy/grocy

| 项 | 内容 |
|---|---|
| 地址 | https://github.com/grocy/grocy |
| 技术栈 | PHP Web，SQLite/自托管家用库存 |
| 许可证 | **MIT** |
| 可借鉴功能 | 采购/消耗事务模型、位置层级、最低库存、有效期、条码枪键入、盘点对账、操作流水不可随意抹除 |
| 不可照搬 | 源码与 UI；领域为食品家用，需按危化品合规重写 |
| 结论 | **不引入代码**。借鉴“以库存事务驱动数量变更 + 条码优先录入”的交互与数据模式。 |

## 4. 对本项目的设计启示（已落地）

1. **瓶/容器唯一编号**（open_enventory 思路）→ `containers.container_code` + 二维码。
2. **库存只通过事务变更**（grocy 思路）→ `stock_transactions` 只增不删。
3. **本地文件库 + 备份**（LEMS/grocy）→ SQLite + 备份/恢复服务。
4. **条码枪即键盘楔入**（grocy）→ 界面焦点捕获快速扫码。
5. **中国法规特有**：双人复核、SDS 审核状态、管制标识、核定储量——参考项目均未覆盖，需独立设计。
