from __future__ import annotations

import shutil
from pathlib import Path

from chem_wh.db.database import Database
from chem_wh.services.audit import AuditService
from chem_wh.services.auth import AuthService, UserSession
from chem_wh.services.exceptions import ValidationError
from chem_wh.utils.timeutil import now_iso


class BackupService:
    def __init__(self, db: Database, auth: AuthService, audit: AuditService):
        self.db = db
        self.auth = auth
        self.audit = audit

    def backup(self, operator: UserSession, dest_dir: str | Path) -> Path:
        self.auth.require(operator, "backup")
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        # Checkpoint WAL before copy
        self.db.conn.execute("PRAGMA wal_checkpoint(FULL)")
        stamp = now_iso().replace(":", "").replace("+", "_")
        target = dest / f"chem_warehouse_backup_{stamp}.db"
        shutil.copy2(self.db.path, target)
        self.audit.log(operator.id, "backup.create", "database", None, {"path": str(target)})
        return target

    def restore(self, operator: UserSession, backup_file: str | Path) -> None:
        self.auth.require(operator, "backup")
        src = Path(backup_file)
        if not src.exists():
            raise ValidationError("备份文件不存在")
        self.db.conn.close()
        shutil.copy2(src, self.db.path)
        # Reopen
        self.db._conn = __import__("sqlite3").connect(
            str(self.db.path), check_same_thread=False
        )
        self.db._conn.row_factory = __import__("sqlite3").Row
        self.db._conn.execute("PRAGMA foreign_keys = ON")
        self.audit.log(operator.id, "backup.restore", "database", None, {"path": str(src)})
