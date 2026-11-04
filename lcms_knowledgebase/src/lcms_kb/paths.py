"""应用数据目录。缓存、数据库和备份都在这里，不写回原始数据旁边。"""

from __future__ import annotations

import os
from pathlib import Path


APP_DIR_NAME = "LCMS_KnowledgeBase"


def app_home() -> Path:
    """返回本程序的数据目录，并创建备份与导出子目录。"""
    override = os.environ.get("LCMS_KB_HOME")
    if override:
        root = Path(override)
    elif os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            base = str(Path.home() / "AppData" / "Local")
        root = Path(base) / APP_DIR_NAME
    else:
        root = Path.home() / ".local" / "share" / APP_DIR_NAME
    root.mkdir(parents=True, exist_ok=True)
    (root / "backups").mkdir(exist_ok=True)
    (root / "exports").mkdir(exist_ok=True)
    (root / "converted").mkdir(exist_ok=True)
    return root


def database_path() -> Path:
    return app_home() / "lcms_knowledgebase.sqlite"


def font_path() -> Path:
    """随程序分发的中文字体。"""
    return Path(__file__).resolve().parent / "resources" / "fonts" / "wqy-microhei.ttc"
