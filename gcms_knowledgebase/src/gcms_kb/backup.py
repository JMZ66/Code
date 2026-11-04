from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path

from gcms_kb.db import Database
from gcms_kb.errors import CorruptBackup

FORMAT = "gcms-kb-backup-1"
EXCLUDE_DIRS = {"safety_backups", "logs", "exports"}
EXCLUDE_SUFFIXES = ("-wal", "-shm")


def now_stamp() -> str:
    return datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")


def _iter_files(data_dir: Path) -> list[Path]:
    files = []
    for path in data_dir.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(data_dir)
        if relative.parts and relative.parts[0] in EXCLUDE_DIRS:
            continue
        if path.name.endswith(EXCLUDE_SUFFIXES):
            continue
        files.append(path)
    return sorted(files)


def _safe_relative(name: str) -> str:
    pure = Path(name)
    if pure.is_absolute() or ".." in pure.parts or name.startswith("/") or name.startswith("\\"):
        raise CorruptBackup(f"备份里有不安全路径：{name}")
    return pure.as_posix()


def create_backup(db: Database, dest: Path) -> Path:
    """把数据库和缓存打成带 SHA-256 清单的 zip。不包含更早的安全备份，避免循环膨胀。"""
    db.checkpoint()
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    files = _iter_files(db.data_dir)
    manifest_files = []
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            relative = path.relative_to(db.data_dir).as_posix()
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            archive.writestr(relative, data)
            manifest_files.append({"path": relative, "sha256": digest, "size": len(data)})
        manifest = {
            "format": FORMAT,
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "files": manifest_files,
        }
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return dest


def verify_backup(zip_path: Path) -> dict:
    zip_path = Path(zip_path)
    if not zipfile.is_zipfile(zip_path):
        raise CorruptBackup("这不是有效的 zip 备份。")
    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            names = archive.namelist()
            if "manifest.json" not in names:
                raise CorruptBackup("备份缺少 manifest.json。")
            for name in names:
                _safe_relative(name)
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            if manifest.get("format") != FORMAT:
                raise CorruptBackup("备份格式不受支持。")
            listed = manifest.get("files")
            if not isinstance(listed, list):
                raise CorruptBackup("清单损坏。")
            listed_names = []
            for item in listed:
                relative = _safe_relative(str(item.get("path", "")))
                expected = str(item.get("sha256", ""))
                size = int(item.get("size", -1))
                try:
                    payload = archive.read(relative)
                except KeyError as exc:
                    raise CorruptBackup(f"清单中的文件不在压缩包内：{relative}") from exc
                digest = hashlib.sha256(payload).hexdigest()
                if digest != expected or len(payload) != size:
                    raise CorruptBackup(f"文件校验失败：{relative}")
                listed_names.append(relative)
            extras = [name for name in names if name != "manifest.json" and name not in listed_names]
            if extras:
                raise CorruptBackup("压缩包含有清单之外的文件。")
            if "gcms.sqlite3" not in listed_names:
                raise CorruptBackup("备份里没有数据库。")
    except CorruptBackup:
        raise
    except (zipfile.BadZipFile, json.JSONDecodeError, OSError, ValueError) as exc:
        raise CorruptBackup(f"无法读取备份：{exc}") from exc
    return manifest


def _integrity(path: Path) -> bool:
    conn = sqlite3.connect(path)
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
    finally:
        conn.close()
    return row is not None and row[0] == "ok"


def restore_backup(db: Database, zip_path: Path) -> Path:
    """先校验，再把当前数据做成安全备份，然后才替换。校验失败时不改动当前数据。"""
    manifest = verify_backup(zip_path)
    safety_dir = db.data_dir / "safety_backups"
    safety_dir.mkdir(parents=True, exist_ok=True)
    safety = safety_dir / f"pre_restore_{now_stamp()}.zip"
    create_backup(db, safety)
    staging = db.data_dir / "safety_backups" / f"_staging_{now_stamp()}"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            for item in manifest["files"]:
                relative = _safe_relative(item["path"])
                target = staging / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(relative))
        staged_db = staging / "gcms.sqlite3"
        if not _integrity(staged_db):
            raise CorruptBackup("备份里的数据库没有通过完整性检查。")
        removed: list[Path] = []
        for path in _iter_files(db.data_dir):
            path.unlink()
            removed.append(path)
        for path in list(db.data_dir.rglob("*")):
            if path.is_dir() and path.relative_to(db.data_dir).parts[:1] != ("safety_backups",):
                if path.name not in EXCLUDE_DIRS and not any(path.iterdir()):
                    path.rmdir()
        for item in manifest["files"]:
            relative = item["path"]
            source = staging / relative
            target = db.data_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        if not _integrity(db.path):
            raise CorruptBackup("恢复后的数据库没有通过完整性检查。")
    except Exception:
        if safety.is_file():
            try:
                _rollback_from_safety(db, safety)
            except Exception:
                pass
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    return safety


def _rollback_from_safety(db: Database, safety: Path) -> None:
    manifest = verify_backup(safety)
    for path in _iter_files(db.data_dir):
        path.unlink()
    with zipfile.ZipFile(safety, "r") as archive:
        for item in manifest["files"]:
            relative = item["path"]
            target = db.data_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(relative))
