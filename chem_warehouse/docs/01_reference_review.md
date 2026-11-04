# 参考项目审查报告（V0.2 复核）

> 审查原则：仅借鉴功能与设计思路，**禁止复制第三方源代码**。本项目采用独立实现（Python + PySide6 + SQLite）。  
> 复核时间：2026-11-03（Asia/Shanghai），以 GitHub API 为准。

## 1. rudolphi/open_enventory

| 项 | 内容 |
|---|---|
| 地址 | https://github.com/rudolphi/open_enventory |
| 技术栈 | PHP / MySQL，浏览器端 ELN + 化学品库存 |
| 许可证 | **AGPL-3.0**（API `license.spdx_id=AGPL-3.0`） |
| 可借鉴功能 | 容器级试剂管理、CAS/位置检索、安全数据关联、出入库流转 |
| 不可照搬 | 全部源码与品牌标识；因 AGPL 传染性与本离线桌面产品形态不符，仅作需求对照 |
| 结论 | **不引入代码**。借鉴“瓶级追踪 + 安全信息绑定”的领域概念。 |

## 2. mbmera/ChemicalManagementSystem

| 项 | 内容 |
|---|---|
| 地址 | https://github.com/mbmera/ChemicalManagementSystem |
| 核查（V0.1） | 当时公开检索未稳定命中，文档曾误记为“仓库不存在” |
| 核查（V0.2） | **仓库存在**（创建于 2026-10-14）；描述为 Streamlit 化学品库存/流转/SDS 管理 |
| 许可证 | **未声明**（GitHub API `license: null`）。无许可证时默认保留版权，**不得复制其代码** |
| 可借鉴思路 | 本地库存、SDS、Streamlit 桌面化运维形态 |
| 相关项目 | `mbmera/LEMS`（实验室设备管理，**MIT**）— 非危化品系统，仅作本地 SQLite/预警形态参考 |
| 结论 | **不引入代码**。修正 V0.1 文档错误：仓库已存在但无开源许可证声明。 |

## 3. grocy/grocy

| 项 | 内容 |
|---|---|
| 地址 | https://github.com/grocy/grocy |
| 技术栈 | PHP Web，SQLite/自托管家用库存 |
| 许可证 | **MIT**（API 确认） |
| 可借鉴功能 | 采购/消耗事务模型、位置、最低库存、有效期、条码枪键入、盘点对账 |
| 不可照搬 | 源码与 UI；领域为食品家用，需按危化品合规重写 |
| 结论 | **不引入代码**。借鉴“以库存事务驱动数量变更 + 条码优先录入”。 |

## 4. 对本项目的设计启示（已落地）

1. 瓶/容器唯一编号 → `containers.container_code` + 二维码。
2. 库存只通过事务变更 → `stock_transactions` 只增不删 + 冲正。
3. 本地文件库 + 完整备份（DB/SDS/QR + 哈希）。
4. 条码枪键盘楔入。
5. 中国法规特有：双人复核、SDS 审核、管制标识、核定储量、演示/正式模式隔离——参考项目均未按中国《危险化学品安全法》实现，需独立设计。
