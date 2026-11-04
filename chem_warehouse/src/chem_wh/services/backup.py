from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from chem_wh import __version__
from chem_wh.constants import DISCLAIMER_SHORT
from chem_wh.db.database import Database, remove_sidecars
from chem_wh.services.audit import AuditService
from chem_wh.services.auth import AuthService, UserSession
from chem_wh.services.exceptions import ValidationError
from chem_wh.utils.integrity import sha256_file
from chem_wh.utils.timeutil import now_iso


def check_sqlite_file(path: Path) -> None:
    target = Path(path)
    uri = target.resolve().as_uri() + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.DatabaseError as exc:
        raise ValidationError(f"数据库无法打开: {exc}") from exc
    try:
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
        except sqlite3.DatabaseError as exc:
            raise ValidationError(f"数据库无法读取: {exc}") from exc
        if not row or row[0] != "ok":
            detail = row[0] if row else "无结果"
            raise ValidationError(f"数据库完整性检查未通过: {detail}")
        conn.execute("PRAGMA foreign_keys=ON")
        bad = conn.execute("PRAGMA foreign_key_check").fetchone()
        if bad:
            raise ValidationError(f"数据库外键不一致: {tuple(bad)}")
    finally:
        conn.close()


class BackupService:
    """Full offline backup: database + SDS + label images + manifest hashes."""

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
            "version": __version__,
            "files": {},
            "note": (
                "本备份含本地数据库。拥有本机文件权限的人员仍可直接修改 SQLite；"
                "哈希可以发现损坏或事后改动，不能代替单位的管理制度。"
                + DISCLAIMER_SHORT
            ),
        }
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for arcname, path in entries:
                digest = sha256_file(path)
                manifest["files"][arcname] = {"sha256": digest, "size": path.stat().st_size}
                zf.write(path, arcname)
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
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
        if not src.is_file():
            raise ValidationError("备份文件不存在")
        try:
            zf_ctx = zipfile.ZipFile(src, "r")
        except zipfile.BadZipFile as exc:
            raise ValidationError("备份不是有效的 ZIP 文件") from exc
        with zf_ctx as zf:
            self._reject_zip_slip(zf)
            if "manifest.json" not in zf.namelist():
                raise ValidationError("备份缺少 manifest.json")
            try:
                manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise ValidationError("备份清单无法读取") from exc
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

    @staticmethod
    def _reject_zip_slip(zf: zipfile.ZipFile) -> None:
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or ".." in Path(name).parts:
                raise ValidationError("备份包含非法路径")

    def _extract_checked(self, src: Path, dest: Path) -> None:
        with zipfile.ZipFile(src, "r") as zf:
            self._reject_zip_slip(zf)
            for info in zf.infolist():
                target = (dest / info.filename).resolve()
                try:
                    target.relative_to(dest.resolve())
                except ValueError as exc:
                    raise ValidationError("备份包含非法路径") from exc
            zf.extractall(dest)
        db_src = dest / "database" / "chem_warehouse.db"
        if not db_src.is_file():
            raise ValidationError("备份中缺少数据库文件")
        check_sqlite_file(db_src)

    def restore(self, operator: UserSession, backup_file: str | Path, *, confirmed: bool = False) -> Path:
        """Restore only after an explicit confirmation and a fresh backup of the live data."""
        self.auth.require(operator, "backup")
        if not confirmed:
            raise ValidationError(
                "恢复会覆盖当前数据。必须先确认，系统才会自动备份当前数据并继续。"
            )
        src = Path(backup_file)
        result = self.verify_archive(src)
        if not result["ok"]:
            raise ValidationError(f"备份校验失败，已拒绝恢复: {result['errors']}")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._extract_checked(src, tmp_path)
            pre_dir = self.data_dir / "backups"
            pre_backup = self.backup(operator, pre_dir)
            pre_check = self.verify_archive(pre_backup)
            if not pre_check["ok"]:
                raise ValidationError(
                    f"恢复前自动备份校验失败，已中止，当前数据未改动: {pre_check['errors']}"
                )
            try:
                self._replace_from_tree(tmp_path)
            except Exception as exc:
                try:
                    self._restore_tree_from_zip(pre_backup)
                except Exception as rollback_exc:
                    raise ValidationError(
                        f"恢复失败（{exc}），且回滚也失败（{rollback_exc}）。"
                        f"恢复前备份仍在 {pre_backup}"
                    ) from exc
                raise ValidationError(
                    f"恢复后的数据未通过完整性检查，已退回恢复前状态。备份文件: {pre_backup}"
                ) from exc
        self.audit.log(
            operator.id,
            "backup.restore",
            "database",
            None,
            {"path": str(src), "pre_backup": str(pre_backup)},
        )
        return pre_backup

    def _replace_from_tree(self, tree: Path) -> None:
        db_src = tree / "database" / "chem_warehouse.db"
        try:
            self.db.conn.close()
        except sqlite3.Error:
            pass
        remove_sidecars(self.db.path)
        shutil.copy2(db_src, self.db.path)
        for sub in ("sds", "qr_codes"):
            src_dir = tree / sub
            dest_dir = self.data_dir / sub
            if dest_dir.exists():
                shutil.rmtree(dest_dir)
            if src_dir.exists():
                shutil.copytree(src_dir, dest_dir)
            else:
                dest_dir.mkdir(parents=True, exist_ok=True)
        self.db.reopen()
        if self.db.integrity_check() != "ok":
            raise ValidationError("恢复后的数据库完整性检查未通过")
        violations = self.db.foreign_key_violations()
        if violations:
            raise ValidationError(f"恢复后的数据库外键不一致: {tuple(violations[0])}")

    def _restore_tree_from_zip(self, backup_file: Path) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._extract_checked(backup_file, tmp_path)
            self._replace_from_tree(tmp_path)
