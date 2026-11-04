from __future__ import annotations

import numpy as np

from gcms_kb.constants import LAYER_ALGORITHM, LAYER_CANDIDATE, LAYER_CONFIRMED, LAYER_RAW
from gcms_kb.db import Database
from gcms_kb.repository import list_components, list_confirmations, list_library, list_peaks, list_unknowns


def _contains_ions(mz, intensity, targets: list[float], tolerance: float, min_rel: float) -> bool:
    mz = np.asarray(mz, dtype=float)
    intensity = np.asarray(intensity, dtype=float)
    if mz.size == 0 or not targets:
        return not targets
    base = float(np.max(intensity)) if intensity.size else 0.0
    for target in targets:
        mask = np.abs(mz - float(target)) <= tolerance
        if not np.any(mask):
            return False
        if min_rel > 0 and base > 0 and float(np.max(intensity[mask])) < min_rel * base:
            return False
    return True


def _in_window(value, low, high) -> bool:
    if value is None:
        return False
    if low is not None and float(value) < float(low):
        return False
    if high is not None and float(value) > float(high):
        return False
    return True


def search_records(
    db: Database,
    *,
    ions: list[float] | None = None,
    ion_tolerance: float = 0.5,
    min_rel: float = 0.0,
    name: str = "",
    cas: str = "",
    sample_code: str = "",
    rt_min: float | None = None,
    rt_max: float | None = None,
    ri_min: float | None = None,
    ri_max: float | None = None,
) -> dict[str, list[dict]]:
    """按层返回检索结果。谱库条目和确认结论分开放，不会互相升级。"""
    ions = [float(ion) for ion in (ions or [])]
    name = name.strip()
    cas = cas.strip()
    sample_code = sample_code.strip()
    use_rt = rt_min is not None or rt_max is not None
    use_ri = ri_min is not None or ri_max is not None
    results = {
        LAYER_RAW: [],
        LAYER_ALGORITHM: [],
        "谱库条目": [],
        LAYER_CANDIDATE: [],
        LAYER_CONFIRMED: [],
        "未知峰": [],
    }
    with db.connect() as conn:
        samples = [dict(row) for row in conn.execute("SELECT * FROM samples").fetchall()]
        sample_by_id = {row["id"]: row for row in samples}
        if sample_code:
            matched = [
                row
                for row in samples
                if sample_code.lower() in str(row["sample_code"]).lower()
            ]
            results[LAYER_RAW] = [
                {
                    "layer": LAYER_RAW,
                    "sample_id": row["id"],
                    "sample_code": row["sample_code"],
                    "detail": row.get("file_hint") or row.get("notes") or "",
                    "is_synthetic": row["is_synthetic"],
                }
                for row in matched
            ]
            allowed = {row["id"] for row in matched}
        else:
            allowed = set(sample_by_id)
        if not sample_code:
            results[LAYER_RAW] = []

        def sample_ok(sample_id: int) -> bool:
            return sample_id in allowed

        peaks = []
        components = []
        if ions or use_rt or use_ri or sample_code:
            for sample_id in allowed:
                for peak in list_peaks(db, sample_id):
                    if not sample_ok(sample_id):
                        continue
                    if ions and not _contains_ions(peak["mz"], peak["intensity"], ions, ion_tolerance, min_rel):
                        continue
                    if use_rt and not _in_window(peak["rt"], rt_min, rt_max):
                        continue
                    if use_ri and not _in_window(peak["ri"], ri_min, ri_max):
                        continue
                    peaks.append(peak)
                for component in list_components(db, sample_id):
                    if ions and not _contains_ions(component["mz"], component["intensity"], ions, ion_tolerance, min_rel):
                        continue
                    if use_rt and not _in_window(component["rt"], rt_min, rt_max):
                        continue
                    if use_ri and not _in_window(component["ri"], ri_min, ri_max):
                        continue
                    components.append(component)
        for peak in peaks:
            sample = sample_by_id.get(peak["sample_id"], {})
            results[LAYER_ALGORITHM].append(
                {
                    "layer": LAYER_ALGORITHM,
                    "kind": "峰",
                    "sample_id": peak["sample_id"],
                    "sample_code": sample.get("sample_code"),
                    "record_id": peak["id"],
                    "rt": peak["rt"],
                    "ri": peak["ri"],
                    "detail": f"面积 {peak['area']:.4g}，高度 {peak['height']:.4g}",
                }
            )
        for component in components:
            sample = sample_by_id.get(component["sample_id"], {})
            results[LAYER_ALGORITHM].append(
                {
                    "layer": LAYER_ALGORITHM,
                    "kind": "解卷积组分",
                    "sample_id": component["sample_id"],
                    "sample_code": sample.get("sample_code"),
                    "record_id": component["id"],
                    "rt": component["rt"],
                    "ri": component["ri"],
                    "detail": f"模型面积 {component['area']:.4g}",
                }
            )

        for entry in list_library(db):
            if name and name.lower() not in str(entry["name"]).lower():
                continue
            if cas and cas.lower() not in str(entry.get("cas") or "").lower():
                continue
            if ions and not _contains_ions(entry["mz"], entry["intensity"], ions, ion_tolerance, min_rel):
                continue
            if use_rt and not _in_window(entry.get("rt"), rt_min, rt_max):
                continue
            if use_ri and not _in_window(entry.get("ri"), ri_min, ri_max):
                continue
            if not any([name, cas, ions, use_rt, use_ri]):
                continue
            results["谱库条目"].append(
                {
                    "layer": "谱库条目",
                    "record_id": entry["id"],
                    "name": entry["name"],
                    "cas": entry.get("cas"),
                    "ri": entry.get("ri"),
                    "rt": entry.get("rt"),
                    "is_synthetic": entry.get("is_synthetic"),
                    "detail": "自建谱库参考谱，不是样品结论",
                }
            )

        hit_sql = """
        SELECT h.*, e.name AS library_name, e.cas AS library_cas, s.sample_code
        FROM library_hits h
        JOIN library_entries e ON e.id = h.library_entry_id
        JOIN samples s ON s.id = h.sample_id
        WHERE h.superseded=0
        """
        hits = [dict(row) for row in conn.execute(hit_sql).fetchall()]
        for hit in hits:
            if hit["sample_id"] not in allowed:
                continue
            if name and name.lower() not in str(hit["library_name"]).lower():
                continue
            if cas and cas.lower() not in str(hit.get("library_cas") or "").lower():
                continue
            if use_rt and not _in_window(hit.get("query_rt"), rt_min, rt_max):
                continue
            if use_ri and not _in_window(hit.get("ri_query"), ri_min, ri_max):
                continue
            if ions:
                continue
            if not any([name, cas, use_rt, use_ri, sample_code]):
                continue
            results[LAYER_CANDIDATE].append(
                {
                    "layer": LAYER_CANDIDATE,
                    "label": hit["label"],
                    "sample_id": hit["sample_id"],
                    "sample_code": hit["sample_code"],
                    "name": hit["library_name"],
                    "cas": hit.get("library_cas"),
                    "score": hit["score"],
                    "rt": hit.get("query_rt"),
                    "ri": hit.get("ri_query"),
                    "detail": "谱库候选（未确认）",
                }
            )

        for row in list_confirmations(db):
            if row["sample_id"] not in allowed:
                continue
            if name and name.lower() not in str(row["compound_name"]).lower():
                continue
            if cas and cas.lower() not in str(row.get("cas") or "").lower():
                continue
            if use_rt and not _in_window(row.get("rt_observed"), rt_min, rt_max):
                continue
            if use_ri and not _in_window(row.get("ri_observed"), ri_min, ri_max):
                continue
            if ions:
                continue
            if not any([name, cas, use_rt, use_ri, sample_code]):
                continue
            sample = sample_by_id.get(row["sample_id"], {})
            results[LAYER_CONFIRMED].append(
                {
                    "layer": LAYER_CONFIRMED,
                    "sample_id": row["sample_id"],
                    "sample_code": sample.get("sample_code"),
                    "name": row["compound_name"],
                    "cas": row.get("cas"),
                    "rt": row.get("rt_observed"),
                    "ri": row.get("ri_observed"),
                    "user_name": row["user_name"],
                    "decided_at": row["decided_at"],
                    "decision": row["decision"],
                    "detail": row["evidence"],
                }
            )
        for row in list_unknowns(db):
            if row["sample_id"] not in allowed:
                continue
            if use_rt and not _in_window(row.get("rt"), rt_min, rt_max):
                continue
            if use_ri and not _in_window(row.get("ri"), ri_min, ri_max):
                continue
            if name or cas or ions:
                text = f"{row.get('note') or ''} {row.get('evidence') or ''}"
                if name and name.lower() not in text.lower():
                    continue
                if cas and cas.lower() not in text.lower():
                    continue
                if ions:
                    continue
            if not any([name, cas, use_rt, use_ri, sample_code]):
                continue
            sample = sample_by_id.get(row["sample_id"], {})
            results["未知峰"].append(
                {
                    "layer": "未知峰",
                    "sample_id": row["sample_id"],
                    "sample_code": sample.get("sample_code"),
                    "rt": row["rt"],
                    "ri": row.get("ri"),
                    "user_name": row["user_name"],
                    "logged_at": row["logged_at"],
                    "detail": row["note"],
                }
            )
    return results
