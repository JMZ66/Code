"""备份与恢复。恢复前先做一份当前库的备份，校验失败则不替换。"""

from __future__ import annotations

import json
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from lcms_kb.db.database import Database
from lcms_kb.errors import BackupError
from lcms_kb.hashing import sha256_bytes, sha256_file
from lcms_kb.version import __version__

BACKUP_FORMAT = "lcms-kb-backup"
BACKUP_VERSION = 1


def _now_stamp() -> str:
    # 带微秒，避免同一秒内的备份互相覆盖。
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _checkpoint(db: Database) -> None:
    db.conn.execute("PRAGMA wal_checkpoint(FULL)")


def create_backup(db: Database, dest_dir: Path | None = None) -> Path:
    """把当前数据库打成带清单的 zip。不包含原始谱图文件。"""
    _checkpoint(db)
    folder = Path(dest_dir) if dest_dir else db.path.parent / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"lcms-backup-{_now_stamp()}.zip"
    while target.exists():
        target = folder / f"lcms-backup-{_now_stamp()}.zip"
    payload = db.path.read_bytes()
    manifest = {
        "format": BACKUP_FORMAT,
        "version": BACKUP_VERSION,
        "software_version": __version__,
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "files": [{
            "name": "database.sqlite",
            "sha256": sha256_bytes(payload),
            "size": len(payload),
        }],
    }
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr("database.sqlite", payload)
    return target


def inspect_backup(path: Path) -> dict:
    """打开清单并核对哈希。损坏时抛出 BackupError，不修改任何数据库。"""
    path = Path(path)
    if not path.is_file():
        raise BackupError(f"找不到备份文件：{path}")
    try:
        archive = zipfile.ZipFile(path, "r")
    except zipfile.BadZipFile as exc:
        raise BackupError("备份不是有效的 zip，已拒绝。") from exc
    with archive:
        names = set(archive.namelist())
        if "manifest.json" not in names or "database.sqlite" not in names:
            raise BackupError("备份缺少 manifest.json 或 database.sqlite，已拒绝。")
        try:
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BackupError("备份清单无法解析，已拒绝。") from exc
        if manifest.get("format") != BACKUP_FORMAT:
            raise BackupError("这不是 LCMS 知识库备份，已拒绝。")
        files = manifest.get("files") or []
        if len(files) != 1 or files[0].get("name") != "database.sqlite":
            raise BackupError("备份清单与内容不一致，已拒绝。")
        payload = archive.read("database.sqlite")
        expected = files[0].get("sha256")
        actual = sha256_bytes(payload)
        if expected != actual or files[0].get("size") != len(payload):
            raise BackupError("备份哈希或大小不符，已拒绝，没有写入当前数据库。")
        if not payload.startswith(b"SQLite format 3\x00"):
            raise BackupError("备份里的数据库文件头不正确，已拒绝。")
    return manifest


def restore_backup(db: Database, path: Path, *, confirm: bool) -> Path:
    """恢复。必须 confirm=True。成功前先把当前库另存为 pre-restore 备份。

    返回恢复前那份自动备份的路径。当前库只在校验通过后被替换。
    """
    if not confirm:
        raise BackupError("恢复必须明确确认。未确认时不会改动当前数据库。")
    inspect_backup(path)
    try:
        pre = create_backup(db, db.path.parent / "backups")
        # 改名，避免和普通备份混在一起
        marked = pre.with_name(f"pre-restore-{_now_stamp()}.zip")
        pre.rename(marked)
        pre = marked
    except Exception as exc:
        raise BackupError(f"恢复前备份失败，已中止，当前数据库未替换：{exc}") from exc
    try:
        with zipfile.ZipFile(path, "r") as archive:
            payload = archive.read("database.sqlite")
        tmp = db.path.with_suffix(".sqlite.restore")
        tmp.write_bytes(payload)
        check = sqlite3.connect(tmp)
        try:
            row = check.execute("PRAGMA integrity_check").fetchone()
            if not row or row[0] != "ok":
                raise BackupError("备份数据库完整性检查未通过，已拒绝。")
            tables = {item[0] for item in check.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "datasets" not in tables or "conclusions" not in tables:
                raise BackupError("备份数据库缺少必要的表，已拒绝。")
        finally:
            check.close()
        db.conn.close()
        tmp.replace(db.path)
        # 清掉旧的 wal，避免把替换前的日志又写回去。
        for suffix in ("-wal", "-shm"):
            leftover = Path(str(db.path) + suffix)
            if leftover.exists():
                leftover.unlink()
        db.conn = sqlite3.connect(db.path)
        db.conn.row_factory = sqlite3.Row
        db.conn.execute("PRAGMA foreign_keys = ON")
        db.conn.execute("PRAGMA journal_mode = WAL")
    except BackupError:
        _reopen_if_needed(db)
        raise
    except Exception as exc:
        _reopen_if_needed(db)
        raise BackupError(f"恢复失败，当前库若已被替换可从 {pre} 再恢复：{exc}") from exc
    return pre


def _reopen_if_needed(db: Database) -> None:
    try:
        db.conn.execute("SELECT 1")
    except sqlite3.ProgrammingError:
        db.conn = sqlite3.connect(db.path)
        db.conn.row_factory = sqlite3.Row
        db.conn.execute("PRAGMA foreign_keys = ON")


def verify_backup_file(path: Path) -> dict:
    """供界面调用的校验。不恢复。"""
    manifest = inspect_backup(path)
    # 再读一次文件哈希，确认 zip 本身可读。
    sha256_file(path)
    return manifest
