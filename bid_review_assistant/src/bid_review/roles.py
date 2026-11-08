"""根据文件名与内容启发式推断文档角色与效力顺序。"""

from __future__ import annotations

import re

ROLE_PATTERNS: list[tuple[str, list[str]]] = [
    ("模板", [r"模板", r"template", r"范本"]),
    ("正文", [r"招标文件", r"招标公告", r"投标邀请", r"采购文件", r"正文"]),
    ("合同", [r"合同", r"协议", r"contract"]),
    ("技术", [r"技术规格", r"技术要求", r"技术附件", r"技术规范", r"需求规格"]),
    ("预算", [r"预算", r"报价", r"清单", r"工程量", r"采购清单", r"控制价"]),
    ("附件", [r"附件", r"appendix", r"annex"]),
]


def infer_role(filename: str, text: str = "") -> str:
    blob = f"{filename}\n{text[:2000]}"
    for role, patterns in ROLE_PATTERNS:
        for pat in patterns:
            if re.search(pat, blob, flags=re.IGNORECASE):
                return role
    return "未知"
