"""Shared labels and the product disclaimer."""

DISCLAIMER = (
    "本软件仅用于实验室内部试剂台账与库存流程辅助，"
    "不能替代危险化学品安全管理的法定职责、审批、备案、储存条件或应急预案。"
    "相容性信息仅来自管理员手工录入，仅供参考；本软件不会自动判断化学品能否混储。"
)

DISCLAIMER_SHORT = "本软件不能替代危险化学品法定安全管理，相容性备注仅供人工参考。"

TX_TYPE_LABELS = {
    "inbound": "入库",
    "issue": "领用",
    "return": "归还",
    "transfer": "调拨",
    "dispose": "处置",
    "adjust_pos": "盘盈",
    "adjust_neg": "盘亏",
    "reversal": "冲正",
}

STATUS_LABELS = {
    "in_stock": "在库",
    "issued": "已领空",
    "disposed": "已处置",
    "empty": "空瓶",
}

SESSION_STATUS_LABELS = {
    "open": "进行中",
    "closing": "结算中",
    "closed": "已确认",
    "cancelled": "已取消",
}
