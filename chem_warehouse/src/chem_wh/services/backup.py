from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from pathlib import Path

from chem_wh.db.database import Database
from chem_wh.services.audit import AuditService
from chem_wh.services.auth import AuthService, UserSession
from chem_wh.services.exceptions import ValidationError
from chem_wh.utils.integrity import sha256_file
from chem_wh.utils.timeutil import now_iso


class BackupService:
    """Full offline backup: DB + SDS + QR codes + manifest hashes."""

    def __init__(
        self,
        db: Database,
        auth: AuthService,
        audit: AuditService,
        data_dir: Path | None = None,
    ):
        self.db = db
        self.auth = auth
        self.audit = audit
        self.data_dir = Path(data_dir) if data_dir else Path(db.path).parent

    def _collect_files(self) -> list[tuple[str, Path]]:
        files: list[tuple[str, Path]] = [("database/chem_warehouse.db", Path(self.db.path))]
        for sub in ("sds", "qr_codes"):
            root = self.data_dir / sub
            if not root.exists():
                continue
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    rel = f"{sub}/{path.relative_to(root).as_posix()}"
                    files.append((rel, path))
        return files

    def backup(self, operator: UserSession, dest_dir: str | Path) -> Path:
        self.auth.require(operator, "backup")
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        self.db.conn.execute("PRAGMA wal_checkpoint(FULL)")
        stamp = now_iso().replace(":", "").replace("+", "_")
        target = dest / f"chem_warehouse_backup_{stamp}.zip"

        entries = self._collect_files()
        manifest = {
            "created_at": now_iso(),
            "app": "chem_warehouse",
            "version": "0.2.0",
            "files": {},
            "note": (
                "本备份含本地明文数据库。拥有文件系统权限的管理员可直接修改 SQLite；"
                "哈希校验仅能发现意外损坏或非授权篡改尝试，不能替代物理与管理制度。"
            ),
        }
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for arcname, path in entries:
                digest = sha256_file(path)
                manifest["files"][arcname] = {
                    "sha256": digest,
                    "size": path.stat().st_size,
                }
                zf.write(path, arcname)
            zf.writestr(
                "manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2),
            )
        self.audit.log(
            operator.id,
            "backup.create",
            "database",
            None,
            {"path": str(target), "file_count": len(manifest["files"])},
        )
        return target

    def verify_archive(self, backup_file: str | Path) -> dict:
        src = Path(backup_file)
        if not src.exists():
            raise ValidationError("备份文件不存在")
        with zipfile.ZipFile(src, "r") as zf:
            if "manifest.json" not in zf.namelist():
                raise ValidationError("备份缺少 manifest.json")
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            errors = []
            for arcname, meta in manifest.get("files", {}).items():
                if arcname not in zf.namelist():
                    errors.append(f"缺失文件: {arcname}")
                    continue
                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                    tmp.write(zf.read(arcname))
                    tmp_path = Path(tmp.name)
                try:
                    digest = sha256_file(tmp_path)
                finally:
                    tmp_path.unlink(missing_ok=True)
                if digest != meta.get("sha256"):
                    errors.append(f"哈希不一致: {arcname}")
            return {"ok": not errors, "errors": errors, "manifest": manifest}

    def restore(self, operator: UserSession, backup_file: str | Path) -> None:
        self.auth.require(operator, "backup")
        src = Path(backup_file)
        result = self.verify_archive(src)
        if not result["ok"]:
            raise ValidationError(f"备份校验失败: {result['errors']}")

        with zipfile.ZipFile(src, "r") as zf, tempfile.TemporaryDirectory() as tmp:
            zf.extractall(tmp)
            tmp_path = Path(tmp)
            db_src = tmp_path / "database" / "chem_warehouse.db"
            if not db_src.exists():
                raise ValidationError("备份中缺少数据库文件")
            self.db.conn.close()
            shutil.copy2(db_src, self.db.path)
            for sub in ("sds", "qr_codes"):
                src_dir = tmp_path / sub
                dest_dir = self.data_dir / sub
                if dest_dir.exists():
                    shutil.rmtree(dest_dir)
                if src_dir.exists():
                    shutil.copytree(src_dir, dest_dir)
            self.db.reopen()

        self.audit.log(
            operator.id, "backup.restore", "database", None, {"path": str(src)}
        )
