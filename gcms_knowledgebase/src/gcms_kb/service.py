from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from gcms_kb.archive import load_run, save_run
from gcms_kb.chromatogram import eic_from_flat
from gcms_kb.compare import align_peak_tables
from gcms_kb.confirmation import validate_confirmation, validate_unknown
from gcms_kb.constants import (
    CANDIDATE_LABEL,
    DECONV_ALGO,
    DECONV_ALGO_VERSION,
    PEAK_ALGO,
    PEAK_ALGO_VERSION,
    SIM_ALGO,
)
from gcms_kb.convert import convert_raw_to_mzml
from gcms_kb.db import Database
from gcms_kb.deconvolution import deconvolve
from gcms_kb.errors import GCMSError, UnsafePath
from gcms_kb.hashing import assert_unchanged, file_size, sha256_file
from gcms_kb.msp_io import read_msp, write_msp
from gcms_kb.mzml_io import read_mzml
from gcms_kb.paths import assert_under
from gcms_kb.peaks import detect_peaks
from gcms_kb import repository as repo
from gcms_kb.ri import AlkanePoint, retention_index
from gcms_kb.search import search_records
from gcms_kb.settings import Settings
from gcms_kb.similarity import cosine_scores
from gcms_kb.spectrum_math import spectrum_at


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class KnowledgeBase:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        for name in ("mzml", "cache", "converted", "safety_backups", "logs", "exports", "external"):
            (self.data_dir / name).mkdir(exist_ok=True)
        self.db = Database(self.data_dir)
        self.settings_path = self.data_dir / "settings.json"
        self.settings = Settings.load(self.settings_path)
        if not self.settings.user_name:
            self.settings.user_name = os.environ.get("USERNAME") or os.environ.get("USER") or ""

    def save_settings(self) -> None:
        self.settings.save(self.settings_path)

    def _rel(self, path: Path) -> str:
        return str(path.resolve().relative_to(self.data_dir.resolve()).as_posix())

    def import_paths(self, paths: list[Path], user_name: str, **common) -> list[dict]:
        results = []
        for path in paths:
            path = Path(path)
            try:
                if path.suffix.lower() == ".raw":
                    result = self.import_raw(path, user_name, **common)
                else:
                    result = self.import_mzml(path, user_name, **common)
                result["ok"] = True
                results.append(result)
            except Exception as exc:
                results.append({"ok": False, "path": str(path), "error": str(exc)})
        return results

    def import_mzml(self, path: Path, user_name: str, **common) -> dict:
        path = Path(path).resolve()
        digest = sha256_file(path)
        size = file_size(path)
        stored = self.data_dir / "mzml" / f"{digest}.mzML"
        if path != stored.resolve():
            if not stored.exists():
                shutil.copyfile(path, stored)
        assert_unchanged(path, digest, size)
        run = read_mzml(stored)
        assert_unchanged(path, digest, size)
        archive = self.data_dir / "cache" / f"{digest}.npz"
        save_run(archive, run)
        assert_unchanged(path, digest, size)
        return self._register_sample(
            original=path,
            digest=digest,
            size=size,
            source_format="mzml",
            mzml_path=stored,
            archive_path=archive,
            run=run,
            user_name=user_name,
            **common,
        )

    def import_raw(self, path: Path, user_name: str, **common) -> dict:
        path = Path(path).resolve()
        digest = sha256_file(path)
        size = file_size(path)
        out_dir = self.data_dir / "converted"
        produced = convert_raw_to_mzml(path, out_dir, self.settings, self.data_dir)
        assert_unchanged(path, digest, size)
        run = read_mzml(produced)
        assert_unchanged(path, digest, size)
        archive = self.data_dir / "cache" / f"{digest}.npz"
        save_run(archive, run)
        assert_unchanged(path, digest, size)
        return self._register_sample(
            original=path,
            digest=digest,
            size=size,
            source_format="raw",
            mzml_path=produced,
            archive_path=archive,
            run=run,
            user_name=user_name,
            **common,
        )

    def _register_sample(
        self,
        *,
        original: Path,
        digest: str,
        size: int,
        source_format: str,
        mzml_path: Path,
        archive_path: Path,
        run,
        user_name: str,
        sample_code: str | None = None,
        instrument: str = "",
        method_name: str = "",
        notes: str = "",
        acquired_at: str = "",
    ) -> dict:
        notes = notes or ""
        if run.is_synthetic and "合成" not in notes:
            notes = (notes + "\n" if notes else "") + "文件标记为合成数据（gcms_kb_synthetic），不是仪器采集。"
        if run.file_hint and "ESI" in run.file_hint.upper() and "不是 GC-MS" not in notes:
            notes = (notes + "\n" if notes else "") + f"采集提示：{run.file_hint}。这不是 EI GC-MS 的滤镜字符串。"
        record = {
            "sample_code": sample_code or original.stem,
            "original_path": str(original),
            "original_sha256": digest,
            "original_size": size,
            "source_format": source_format,
            "mzml_relpath": self._rel(mzml_path),
            "archive_relpath": self._rel(archive_path),
            "instrument": instrument or run.instrument,
            "method_name": method_name,
            "acquired_at": acquired_at or None,
            "imported_at": now_iso(),
            "imported_by": user_name or self.settings.user_name or "未填写",
            "notes": notes,
            "file_hint": run.file_hint,
            "is_synthetic": 1 if run.is_synthetic else 0,
            "n_scans": run.n_scans,
            "rt_min": float(run.rt[0]) if run.n_scans else None,
            "rt_max": float(run.rt[-1]) if run.n_scans else None,
        }
        sample_id = repo.insert_sample(self.db, record)
        self.db.audit(now_iso(), record["imported_by"], "import", f"{source_format} {original} -> {sample_id}")
        record["id"] = sample_id
        record["path"] = str(original)
        return record

    def list_samples(self, text: str = "") -> list[dict]:
        return repo.list_samples(self.db, text)

    def load_sample_run(self, sample_id: int):
        sample = repo.get_sample(self.db, sample_id)
        if sample is None:
            raise GCMSError("样品不存在")
        archive = assert_under(self.data_dir, self.data_dir / sample["archive_relpath"])
        return sample, load_run(archive)

    def chromatogram(self, sample_id: int, kind: str, mz: float | None = None, tolerance: float | None = None):
        _sample, run = self.load_sample_run(sample_id)
        kind = kind.lower()
        if kind == "tic":
            return run.rt, run.tic
        if kind == "bpc":
            return run.rt, run.bpc
        if kind == "eic":
            if mz is None:
                raise GCMSError("提取离子色谱需要 m/z。")
            tol = self.settings.mz_tolerance if tolerance is None else tolerance
            return run.rt, eic_from_flat(run.mz, run.intensity, run.offsets, float(mz), float(tol))
        raise GCMSError("色谱类型只能是 TIC、BPC 或 EIC。")

    def spectrum_at_rt(self, sample_id: int, rt: float, background: bool | None = None):
        _sample, run = self.load_sample_run(sample_id)
        use_bg = self.settings.background_subtract if background is None else background
        return spectrum_at(run, rt, background=use_bg)

    def detect_peaks_for(self, sample_id: int, user_name: str | None = None) -> list[dict]:
        _sample, run = self.load_sample_run(sample_id)
        found = detect_peaks(run.rt, run.tic)
        repo.supersede_peaks(self.db, sample_id)
        created = now_iso()
        for peak in found:
            mz, inten, index, subtracted = spectrum_at(
                run, peak.rt, background=self.settings.background_subtract
            )
            repo.insert_peak(
                self.db,
                {
                    "sample_id": sample_id,
                    "algorithm": PEAK_ALGO,
                    "algorithm_version": PEAK_ALGO_VERSION,
                    "rt": peak.rt,
                    "rt_start": peak.rt_start,
                    "rt_end": peak.rt_end,
                    "height": peak.height,
                    "area": peak.area,
                    "apex_scan": index,
                    "baseline_start": peak.baseline_start,
                    "baseline_end": peak.baseline_end,
                    "background_subtracted": subtracted,
                    "mz": mz,
                    "intensity": inten,
                    "created_at": created,
                },
            )
        self.db.audit(created, user_name or self.settings.user_name, "detect_peaks", str(sample_id))
        return repo.list_peaks(self.db, sample_id)

    def deconvolve_sample(self, sample_id: int, user_name: str | None = None) -> tuple[list[dict], str]:
        _sample, run = self.load_sample_run(sample_id)
        scans_mz, scans_i = run.scans()
        components, note = deconvolve(
            run.rt,
            scans_mz,
            scans_i,
            apex_tol=float(self.settings.deconv_apex_tol),
            mz_bin=float(self.settings.deconv_mz_bin),
        )
        repo.supersede_components(self.db, sample_id)
        created = now_iso()
        for component in components:
            repo.insert_component(
                self.db,
                {
                    "sample_id": sample_id,
                    "algorithm": DECONV_ALGO,
                    "algorithm_version": DECONV_ALGO_VERSION,
                    "rt": component.rt,
                    "rt_start": component.rt_start,
                    "rt_end": component.rt_end,
                    "height": component.height,
                    "area": component.area,
                    "mz": component.mz,
                    "intensity": component.intensity,
                    "created_at": created,
                },
            )
        self.db.audit(created, user_name or self.settings.user_name, "deconvolve", note or str(sample_id))
        return repo.list_components(self.db, sample_id), note

    def add_library_spectrum(self, record: dict) -> int:
        record = dict(record)
        record.setdefault("added_at", now_iso())
        record.setdefault("added_by", self.settings.user_name or "未填写")
        record.setdefault("source", "sample")
        if not str(record.get("name") or "").strip():
            raise GCMSError("谱库条目需要名称。加入谱库不会把样品峰鉴定为该化合物。")
        entry_id = repo.insert_library(self.db, record)
        self.db.audit(record["added_at"], record["added_by"], "library_add", record["name"])
        return entry_id

    def import_msp(self, path: Path, user_name: str) -> int:
        count = 0
        for record in read_msp(Path(path)):
            text = f"{record['name']} {record.get('comment') or ''}"
            self.add_library_spectrum(
                {
                    "name": record["name"],
                    "cas": record.get("cas"),
                    "formula": record.get("formula"),
                    "ri": record.get("ri"),
                    "rt": record.get("rt"),
                    "source": "msp",
                    "added_by": user_name or self.settings.user_name or "未填写",
                    "notes": record.get("comment") or "",
                    "is_synthetic": "合成" in text,
                    "mz": record["mz"],
                    "intensity": record["intensity"],
                }
            )
            count += 1
        return count

    def export_msp(self, path: Path, entries: list[dict] | None = None) -> int:
        rows = entries if entries is not None else repo.list_library(self.db)
        payload = []
        for row in rows:
            payload.append(
                {
                    "name": row["name"],
                    "cas": row.get("cas"),
                    "formula": row.get("formula"),
                    "ri": row.get("ri"),
                    "rt": row.get("rt"),
                    "comment": row.get("notes") or "自建谱库参考谱，不是鉴定结论",
                    "mz": row["mz"],
                    "intensity": row["intensity"],
                }
            )
        write_msp(Path(path), payload)
        return len(payload)

    def search_library(self, sample_id: int, query_kind: str, query_id: int) -> list[dict]:
        if query_kind == "peak":
            rows = repo.list_peaks(self.db, sample_id)
        elif query_kind == "component":
            rows = repo.list_components(self.db, sample_id)
        else:
            raise GCMSError("只能对算法峰或解卷积组分做谱库检索。")
        target = next((row for row in rows if row["id"] == query_id), None)
        if target is None:
            raise GCMSError("找不到要检索的算法记录。")
        repo.supersede_hits(self.db, sample_id, query_kind, query_id)
        scored = []
        for entry in repo.list_library(self.db):
            ri_query = target.get("ri")
            ri_library = entry.get("ri")
            ri_pass = None
            ri_delta = None
            if ri_query is not None and ri_library is not None:
                ri_delta = float(ri_query) - float(ri_library)
                ri_pass = abs(ri_delta) <= float(self.settings.ri_tolerance)
                if not ri_pass:
                    continue
            score, matched, reverse = cosine_scores(
                target["mz"],
                target["intensity"],
                entry["mz"],
                entry["intensity"],
                tolerance=float(self.settings.cosine_tolerance),
                mz_power=float(self.settings.mz_power),
                intensity_power=float(self.settings.intensity_power),
            )
            if score < float(self.settings.similarity_min):
                continue
            scored.append((score, reverse, matched, entry, ri_query, ri_library, ri_delta, ri_pass))
        scored.sort(key=lambda item: item[0], reverse=True)
        created = now_iso()
        algo = (
            f"{SIM_ALGO} mz_power={self.settings.mz_power} "
            f"intensity_power={self.settings.intensity_power} tolerance={self.settings.cosine_tolerance}"
        )
        for rank, (score, reverse, matched, entry, ri_query, ri_library, ri_delta, ri_pass) in enumerate(
            scored[: int(self.settings.similarity_top_k)], start=1
        ):
            repo.insert_hit(
                self.db,
                {
                    "sample_id": sample_id,
                    "query_kind": query_kind,
                    "query_id": query_id,
                    "query_rt": target["rt"],
                    "library_entry_id": entry["id"],
                    "rank": rank,
                    "score": score,
                    "reverse_score": reverse,
                    "matched_peaks": matched,
                    "ri_query": ri_query,
                    "ri_library": ri_library,
                    "ri_delta": ri_delta,
                    "ri_pass": None if ri_pass is None else int(bool(ri_pass)),
                    "algorithm": algo,
                    "created_at": created,
                    "label": CANDIDATE_LABEL,
                },
            )
        self.db.audit(created, self.settings.user_name, "library_search", f"{query_kind}:{query_id}")
        return [hit for hit in repo.list_hits(self.db, sample_id) if hit["query_kind"] == query_kind and hit["query_id"] == query_id]

    def save_calibration(self, name: str, points: list[dict], user_name: str, notes: str = "") -> int:
        if len(points) < 2:
            raise GCMSError("烷烃校正至少需要两个点。")
        return repo.insert_calibration(self.db, name, user_name or self.settings.user_name, now_iso(), notes, points)

    def apply_retention_index(self, sample_id: int, calibration_id: int) -> int:
        points = [
            AlkanePoint(int(item["carbon_number"]), float(item["rt"]), item.get("name") or "")
            for item in repo.calibration_points(self.db, calibration_id)
        ]
        count = 0
        for peak in repo.list_peaks(self.db, sample_id):
            result = retention_index(peak["rt"], points)
            repo.update_peak_ri(self.db, peak["id"], result.ri, result.extrapolated)
            count += 1
        for component in repo.list_components(self.db, sample_id):
            result = retention_index(component["rt"], points)
            repo.update_component_ri(self.db, component["id"], result.ri, result.extrapolated)
            count += 1
        return count

    def confirm(self, record: dict) -> int:
        validate_confirmation(record)
        record = dict(record)
        record["decided_at"] = record.get("decided_at") or now_iso()
        record["user_name"] = str(record["user_name"]).strip()
        record["evidence"] = str(record["evidence"]).strip()
        record["basis_detail"] = str(record["basis_detail"]).strip()
        record["compound_name"] = str(record["compound_name"]).strip()
        confirmation_id = repo.insert_confirmation(self.db, record)
        self.db.audit(record["decided_at"], record["user_name"], "confirm", record["compound_name"])
        return confirmation_id

    def log_unknown(self, record: dict) -> int:
        validate_unknown(record)
        record = dict(record)
        record["logged_at"] = record.get("logged_at") or now_iso()
        record["user_name"] = str(record["user_name"]).strip()
        record["note"] = str(record["note"]).strip()
        unknown_id = repo.insert_unknown(self.db, record)
        self.db.audit(record["logged_at"], record["user_name"], "unknown", record["note"])
        return unknown_id

    def search(self, **kwargs) -> dict[str, list[dict]]:
        return search_records(self.db, **kwargs)

    def report(self, sample_id: int) -> dict:
        sample = repo.get_sample(self.db, sample_id)
        if sample is None:
            raise GCMSError("样品不存在")
        confirmations = []
        for row in repo.list_confirmations(self.db, sample_id):
            row = dict(row)
            if row["target_kind"] == "peak" and row.get("target_id"):
                superseded = repo.peak_is_superseded(self.db, int(row["target_id"]))
                if superseded:
                    row["link_note"] = "关联的算法峰已有更新版本，本结论仍是当时的人工记录。"
            confirmations.append(row)
        return {
            "sample": sample,
            "peaks": repo.list_peaks(self.db, sample_id),
            "components": repo.list_components(self.db, sample_id),
            "hits": repo.list_hits(self.db, sample_id),
            "confirmations": confirmations,
            "unknowns": repo.list_unknowns(self.db, sample_id),
        }

    def export_excel(self, sample_id: int, path: Path) -> None:
        from gcms_kb.reports import write_excel

        write_excel(self.report(sample_id), Path(path))

    def export_pdf(self, sample_id: int, path: Path) -> None:
        from gcms_kb.reports import write_pdf

        write_pdf(self.report(sample_id), Path(path))

    def backup(self, path: Path) -> Path:
        from gcms_kb.backup import create_backup

        return create_backup(self.db, Path(path))

    def restore(self, path: Path) -> Path:
        from gcms_kb.backup import restore_backup

        safety = restore_backup(self.db, Path(path))
        self.settings = Settings.load(self.settings_path)
        return safety

    def verify_original(self, sample_id: int) -> dict:
        sample = repo.get_sample(self.db, sample_id)
        if sample is None:
            raise GCMSError("样品不存在")
        path = Path(sample["original_path"])
        if not path.is_file():
            return {"exists": False, "unchanged": False, "path": str(path)}
        digest = sha256_file(path)
        return {
            "exists": True,
            "unchanged": digest == sample["original_sha256"] and file_size(path) == sample["original_size"],
            "path": str(path),
            "sha256": digest,
        }

    def delete_sample(self, sample_id: int) -> None:
        sample = repo.get_sample(self.db, sample_id)
        if sample is None:
            return
        original = Path(sample["original_path"])
        digest = sha256_file(original) if original.is_file() else None
        size = file_size(original) if original.is_file() else None
        repo.delete_sample(self.db, sample_id)
        remaining = repo.list_samples(self.db, limit=100000)
        used = set()
        for other in remaining:
            used.add(other.get("archive_relpath"))
            used.add(other.get("mzml_relpath"))
        for relative in (sample.get("archive_relpath"), sample.get("mzml_relpath")):
            if not relative or relative in used:
                continue
            target = self.data_dir / relative
            try:
                target = assert_under(self.data_dir, target)
            except UnsafePath:
                continue
            if target.is_file() and target.resolve() != original.resolve():
                target.unlink()
        if original.is_file() and digest is not None:
            assert_unchanged(original, digest, size)

    def compare_samples(self, sample_ids: list[int], rt_tol: float | None = None) -> dict:
        tol = float(self.settings.rt_tolerance if rt_tol is None else rt_tol)
        groups = []
        chromatograms = []
        samples = []
        for sample_id in sample_ids:
            sample, run = self.load_sample_run(sample_id)
            samples.append(sample)
            groups.append(repo.list_peaks(self.db, sample_id))
            chromatograms.append({"sample_id": sample_id, "sample_code": sample["sample_code"], "rt": run.rt, "tic": run.tic})
        return {
            "samples": samples,
            "chromatograms": chromatograms,
            "aligned": align_peak_tables(groups, tol),
            "rt_tol": tol,
        }

    def run_external_msdial(self, sample_id: int) -> dict:
        executable = self.settings.msdial_console_path.strip()
        if not executable:
            raise GCMSError(
                "未配置 MS-DIAL。官方程序需自行安装，本软件不附带，也不会把未验证的外部结果写入算法层。"
            )
        sample = repo.get_sample(self.db, sample_id)
        if sample is None:
            raise GCMSError("样品不存在")
        mzml = assert_under(self.data_dir, self.data_dir / sample["mzml_relpath"])
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        out = self.data_dir / "external" / f"msdial_{sample_id}_{stamp}"
        indir = out / "input"
        indir.mkdir(parents=True)
        shutil.copyfile(mzml, indir / mzml.name)
        param = out / "Msdial-GCMS-Param.txt"
        param.write_text(_msdial_param(), encoding="utf-8")
        command = [executable, "gcms", "-i", str(indir), "-o", str(out), "-m", str(param)]
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=3600)
        (out / "command.txt").write_text(" ".join(command), encoding="utf-8")
        (out / "stdout.txt").write_text(completed.stdout or "", encoding="utf-8")
        (out / "stderr.txt").write_text(completed.stderr or "", encoding="utf-8")
        return {
            "output_dir": str(out),
            "returncode": completed.returncode,
            "imported": False,
            "message": "MS-DIAL 已按控制台方式调用。输出留在数据目录，没有导入算法层。",
        }


def _msdial_param() -> str:
    return "\n".join(
        [
            "Data type: Centroid",
            "Ion mode: Positive",
            "Accuracy type: IsNominal",
            "Retention time begin: 0",
            "Retention time end: 100",
            "Mass range begin: 30",
            "Mass range end: 600",
            "Smoothing method: LinearWeightedMovingAverage",
            "Smoothing level: 3",
            "Average peak width: 20",
            "Minimum peak height: 1000",
            "Mass slice width: 0.5",
            "Mass accuracy: 0.5",
            "Sigma window value: 0.5",
            "Amplitude cut off: 10",
            "Retention type: RT",
            "EI similarity tolerance for identification: 70",
            "Identification score cut off: 70",
            "Alignment index type: RT",
            "Retention time tolerance for alignment: 0.075",
            "EI similarity tolerance: 70",
            "Retention time factor: 0.5",
            "EI similarity factor: 0.5",
            "Peak count filter: 0",
            "QC at least filter: False",
            "",
        ]
    )
