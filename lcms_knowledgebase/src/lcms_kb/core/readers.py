"""读取 mzML 和 mzXML。解码交给 pyteomics，原始文件只读。

扫描模式优先采用 PSI-MS 受控词。词表里没有、只能靠隔离窗口宽度判断时，
``scan_mode_basis`` 会写成 heuristic，界面显示为“推断”。
"""

from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np
from pyteomics import mzml, mzxml

from lcms_kb.core.models import RunHeader, Scan
from lcms_kb.errors import UnsupportedFormat
from lcms_kb.offline import enforce_offline_ontology

# 隔离窗口宽于该值（Da）且没有 DIA 词条时，记为推断的 DIA。
DIA_WIDTH_HEURISTIC_DA = 8.0
AIF_WIDTH_HEURISTIC_DA = 50.0

DIA_TERMS = {
    "data-independent acquisition",
    "data independent acquisition from dissociation of sequential mass ranges",
    "data independent acquisition from dissociation of sequential mass ranges after ion mobility separation",
    "dissociation of sequential mass ranges",
    "dissociation of scanning quadrupole across a specified mass range",
}
AIF_TERMS = {
    "dissociation of full mass range",
    "data independent acquisition from dissociation of full mass range",
    "data independent acquisition from dissociation of full mass range after ion mobility separation",
}
DDA_TERMS = {"data-dependent acquisition"}

ACTIVATION_TERMS = (
    "collision-induced dissociation",
    "beam-type collision-induced dissociation",
    "higher energy beam-type collision-induced dissociation",
    "electron transfer dissociation",
    "pulsed q dissociation",
    "electron capture dissociation",
    "in-source collision-induced dissociation",
)

VENDOR_KEYS = (
    ("Thermo", ("thermo", "xcalibur", "orbitrap", "q exactive", "exactive", "exploris", "orbitrap fusion", "lumos", "ltq", "finnigan")),
    ("Waters", ("waters", "masslynx", "xevo", "synapt", "acquity")),
    ("SCIEX", ("sciex", "ab sciex", "tripletof", "qtrap", "analyst")),
    ("Agilent", ("agilent", "masshunter")),
    ("Bruker", ("bruker", "micrtof", "maxis", "timstof", "amazon series", "compass")),
)

_SCAN_NUMBER = re.compile(r"scan=(\d+)", re.IGNORECASE)


def read_run(path: Path | str) -> tuple[RunHeader, list[Scan]]:
    """一次读完头部和全部扫描。文件以只读方式打开。"""
    path = Path(path)
    header = read_header(path)
    scans = list(iter_scans(path, header))
    return header, scans


def read_header(path: Path | str) -> RunHeader:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".mzml":
        return _mzml_header(path)
    if suffix == ".mzxml":
        return _mzxml_header(path)
    raise UnsupportedFormat(f"不能直接读取 {suffix or '无扩展名'} 文件。开放格式只接受 mzML 和 mzXML。")


def iter_scans(path: Path | str, header: RunHeader | None = None):
    path = Path(path)
    header = header or read_header(path)
    suffix = path.suffix.lower()
    if suffix == ".mzml":
        yield from _iter_mzml(path, header)
    elif suffix == ".mzxml":
        yield from _iter_mzxml(path, header)
    else:
        raise UnsupportedFormat(f"不能直接读取 {suffix or '无扩展名'} 文件。")


def read_scan_at(path: Path | str, index_in_file: int) -> Scan:
    """按文件中的顺序随机读取一张谱。"""
    path = Path(path)
    enforce_offline_ontology()
    header = read_header(path)
    suffix = path.suffix.lower()
    if suffix == ".mzml":
        reader = mzml.MzML(str(path), read_schema=False, use_index=True)
        try:
            spec = reader.get_by_index(index_in_file)
        finally:
            reader.close()
        return _scan_from_mzml(spec, header)
    if suffix == ".mzxml":
        reader = mzxml.MzXML(str(path), use_index=True)
        try:
            spec = reader[index_in_file] if not hasattr(reader, "get_by_index") else reader.get_by_index(str(index_in_file + 1))
            # mzXML 的索引键通常是 scan num。按顺序回退。
            if spec is None:
                for offset, item in enumerate(reader):
                    if offset == index_in_file:
                        spec = item
                        break
        finally:
            reader.close()
        return _scan_from_mzxml(spec, header, index_in_file)
    raise UnsupportedFormat(path.suffix)


def _local(tag: str) -> str:
    if tag.startswith("{"):
        return tag.rpartition("}")[2]
    return tag


def _cv_terms(element: ET.Element) -> list[tuple[str, str, str]]:
    found = []
    for child in element.iter():
        if _local(child.tag) != "cvParam":
            continue
        found.append((
            child.attrib.get("accession", ""),
            child.attrib.get("name", ""),
            child.attrib.get("value", ""),
        ))
    return found


def _text_blob(terms: list[tuple[str, str, str]], extra: list[str] | None = None) -> str:
    parts = [name.lower() for _acc, name, value in terms]
    parts.extend(value.lower() for _acc, _name, value in terms if value)
    if extra:
        parts.extend(item.lower() for item in extra)
    return " ".join(parts)


def infer_vendors(blob: str) -> list[str]:
    """从仪器和软件词条的文字推断厂商。推断结果不是仪器鉴定。"""
    found = []
    haystack = blob.lower()
    for vendor, keys in VENDOR_KEYS:
        if any(key in haystack for key in keys):
            found.append(vendor)
    return found


def _mzml_header(path: Path) -> RunHeader:
    # 只解析到 spectrumList 之前，避免把整份谱图载入内存。
    terms: list[tuple[str, str, str]] = []
    declared = None
    synthetic = False
    for event, elem in ET.iterparse(path, events=("start", "end")):
        name = _local(elem.tag)
        if event == "start" and name == "spectrumList":
            raw = elem.attrib.get("count")
            if raw and str(raw).isdigit():
                declared = int(raw)
            continue
        if event != "end":
            continue
        if name == "spectrum":
            break
        if name in {"referenceableParamGroup", "instrumentConfiguration", "software",
                    "sourceFile", "fileContent", "dataProcessing"}:
            terms.extend(_cv_terms(elem))
        if name == "userParam" and "TEST ONLY SYNTHETIC" in (elem.attrib.get("value", "") + elem.attrib.get("name", "")):
            synthetic = True
        if name in {"fileDescription", "softwareList", "instrumentConfigurationList", "dataProcessingList"}:
            elem.clear()
    names = [item[1] for item in terms if item[1]]
    acquisition = [name for name in names if name.lower() in {t.lower() for t in (DIA_TERMS | AIF_TERMS | DDA_TERMS)}]
    blob = _text_blob(terms)
    return RunHeader(
        format_name="mzML",
        spectrum_count_declared=declared,
        instrument_terms=names,
        software_terms=[name for name in names if name in {"Xcalibur", "MassLynx", "ProteoWizard", "ProteoWizard software", "Analyst"}],
        source_file_terms=names,
        file_content_terms=names,
        acquisition_terms=acquisition,
        vendors_inferred=infer_vendors(blob),
        test_only_synthetic=synthetic,
    )


def _mzxml_header(path: Path) -> RunHeader:
    tree_terms: list[str] = []
    synthetic = False
    declared = None
    # mzXML 的 msRun 属性里有 scanCount，仪器名在 msInstrument。
    for _event, elem in ET.iterparse(path, events=("end",)):
        name = _local(elem.tag)
        if name == "msInstrument":
            for child in elem:
                local = _local(child.tag)
                value = child.attrib.get("value") or child.attrib.get("name") or ""
                if value:
                    tree_terms.append(f"{local}:{value}")
                else:
                    tree_terms.append(local)
        if name == "msRun":
            raw = elem.attrib.get("scanCount")
            if raw and str(raw).isdigit():
                declared = int(raw)
        if name == "dataProcessing":
            software = elem.attrib.get("softwareType") or ""
            if software:
                tree_terms.append(software)
        if name == "note" and elem.text and "TEST ONLY SYNTHETIC" in elem.text:
            synthetic = True
        if name == "scan":
            break
        if name in {"msInstrument", "parentFile", "dataProcessing"}:
            elem.clear()
    return RunHeader(
        format_name="mzXML",
        spectrum_count_declared=declared,
        instrument_terms=tree_terms,
        vendors_inferred=infer_vendors(" ".join(tree_terms)),
        test_only_synthetic=synthetic or any("TEST ONLY SYNTHETIC" in item for item in tree_terms),
    )


def _iter_mzml(path: Path, header: RunHeader):
    enforce_offline_ontology()
    reader = mzml.MzML(str(path), read_schema=False)
    try:
        for spec in reader:
            yield _scan_from_mzml(spec, header)
    finally:
        reader.close()


def _iter_mzxml(path: Path, header: RunHeader):
    reader = mzxml.MzXML(str(path))
    try:
        for index, spec in enumerate(reader):
            yield _scan_from_mzxml(spec, header, index)
    finally:
        reader.close()


def _as_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _unit(value) -> str | None:
    return getattr(value, "unit_info", None)


def _rt_minutes(value) -> tuple[float | None, str | None]:
    if value is None:
        return None, None
    unit = _unit(value)
    number = _as_float(value)
    if number is None:
        return None, unit
    if unit and "second" in unit.lower():
        return number / 60.0, unit
    return number, unit or "minute"


def _first(value):
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _term_names(spec: dict) -> list[str]:
    names = []
    for key, val in spec.items():
        if isinstance(val, np.ndarray):
            continue
        if isinstance(val, (str, int, float)):
            names.append(str(key))
    return names


def _activation_name(activation: dict | None) -> str | None:
    if not isinstance(activation, dict):
        return None
    for term in ACTIVATION_TERMS:
        if term in activation:
            return term
    for key in activation:
        if key in {"collision energy", "collision energy ramp start", "collision energy ramp end"}:
            continue
        if isinstance(activation[key], str):
            return str(key)
    return None


def _collision_energy(activation: dict | None) -> float | None:
    if not isinstance(activation, dict):
        return None
    if "collision energy" in activation:
        return _as_float(activation.get("collision energy"))
    start = _as_float(activation.get("collision energy ramp start"))
    end = _as_float(activation.get("collision energy ramp end"))
    if start is not None and end is not None:
        return (start + end) / 2.0
    return start if start is not None else end


def classify_scan_mode(*, ms_level: int | None, term_names: list[str],
                       file_terms: list[str], isolation_width: float | None,
                       precursor_mz: float | None) -> tuple[str, str]:
    """返回 (scan_mode, basis)。basis 以 cv 或 heuristic 开头。"""
    names = {item.lower() for item in term_names}
    file_names = {item.lower() for item in file_terms}
    if "srm spectrum" in names or "selected reaction monitoring" in names:
        return "srm", "cv:MS:1000583"
    if "sim spectrum" in names or "selected ion monitoring" in names:
        return "sim", "cv:MS:1000582"
    if names & {item.lower() for item in AIF_TERMS} or file_names & {item.lower() for item in AIF_TERMS}:
        if ms_level and ms_level >= 2:
            return "dia_aif", "cv:dia-full-range"
    if names & {item.lower() for item in DIA_TERMS} or file_names & {item.lower() for item in DIA_TERMS}:
        if ms_level and ms_level >= 2:
            return "dia", "cv:MS:1003215"
    if (names | file_names) & {item.lower() for item in DDA_TERMS}:
        if ms_level and ms_level >= 2:
            return "dda", "cv:MS:1003221"
        if ms_level == 1:
            return "full_scan", "cv:ms-level+dda-run"
    if ms_level and ms_level >= 2:
        if isolation_width is not None and isolation_width >= AIF_WIDTH_HEURISTIC_DA:
            return "dia_aif", f"heuristic:isolation_width={isolation_width:g}>={AIF_WIDTH_HEURISTIC_DA:g}"
        if isolation_width is not None and isolation_width >= DIA_WIDTH_HEURISTIC_DA:
            return "dia", f"heuristic:isolation_width={isolation_width:g}>={DIA_WIDTH_HEURISTIC_DA:g}"
        if precursor_mz is not None:
            return "dda", "heuristic:precursor-present"
        return "unknown", "heuristic:msn-without-precursor"
    if ms_level == 1:
        return "full_scan", "cv:ms-level-1"
    return "unknown", "cv:missing"


def _polarity_from_terms(names: list[str]) -> str:
    lowered = {item.lower() for item in names}
    positive = "positive scan" in lowered
    negative = "negative scan" in lowered
    if positive and not negative:
        return "positive"
    if negative and not positive:
        return "negative"
    return "unknown"


def _arrays(spec: dict) -> tuple[np.ndarray, np.ndarray]:
    mz = np.asarray(spec.get("m/z array", np.array([], dtype=float)), dtype=float).ravel()
    intensity = np.asarray(spec.get("intensity array", np.array([], dtype=float)), dtype=float).ravel()
    if mz.shape != intensity.shape:
        limit = min(mz.size, intensity.size)
        mz = mz[:limit]
        intensity = intensity[:limit]
    return mz, intensity


def _tic_bpc(mz: np.ndarray, intensity: np.ndarray, reported_tic: float | None) -> tuple[float, float, float | None]:
    if intensity.size == 0:
        return 0.0, 0.0, None
    tic_value = float(intensity.sum())
    index = int(np.argmax(intensity))
    return tic_value, float(intensity[index]), float(mz[index])


def _scan_number_from_id(spectrum_id: str, index_in_file: int) -> int:
    match = _SCAN_NUMBER.search(spectrum_id or "")
    if match:
        return int(match.group(1))
    tail = re.search(r"(\d+)$", spectrum_id or "")
    if tail:
        return int(tail.group(1))
    return index_in_file + 1


def _scan_from_mzml(spec: dict, header: RunHeader) -> Scan:
    index_in_file = int(spec.get("index", 0))
    spectrum_id = str(spec.get("id", ""))
    ms_level = _as_int(spec.get("ms level"))
    names = _term_names(spec)
    scan_list = spec.get("scanList") or {}
    scan0 = _first(_as_list(scan_list.get("scan"))) or {}
    if isinstance(scan0, dict):
        names.extend(_term_names(scan0))
        rt_min, rt_unit = _rt_minutes(scan0.get("scan start time"))
        filter_string = scan0.get("filter string")
        filter_string = str(filter_string) if filter_string else None
    else:
        rt_min, rt_unit, filter_string = None, None, None
    polarity = _polarity_from_terms(names)
    precursors = _as_list((spec.get("precursorList") or {}).get("precursor"))
    precursor = precursors[0] if precursors else {}
    selected = None
    activation = None
    isolation = {}
    if isinstance(precursor, dict):
        selected_list = _as_list((precursor.get("selectedIonList") or {}).get("selectedIon"))
        selected = selected_list[0] if selected_list else None
        activation = precursor.get("activation")
        isolation = precursor.get("isolationWindow") or {}
    precursor_mz = None
    precursor_charge = None
    if isinstance(selected, dict):
        precursor_mz = _as_float(selected.get("selected ion m/z"))
        precursor_charge = _as_int(selected.get("charge state"))
    lower = _as_float(isolation.get("isolation window lower offset")) if isinstance(isolation, dict) else None
    upper = _as_float(isolation.get("isolation window upper offset")) if isinstance(isolation, dict) else None
    width = None
    if lower is not None or upper is not None:
        width = (lower or 0.0) + (upper or 0.0)
    elif isinstance(isolation, dict):
        low_limit = _as_float(isolation.get("isolation window lower limit"))
        high_limit = _as_float(isolation.get("isolation window upper limit"))
        if low_limit is not None and high_limit is not None:
            width = high_limit - low_limit
    mode, basis = classify_scan_mode(
        ms_level=ms_level,
        term_names=names,
        file_terms=header.acquisition_terms,
        isolation_width=width,
        precursor_mz=precursor_mz,
    )
    mz, intensity = _arrays(spec)
    reported = _as_float(spec.get("total ion current"))
    tic_value, bpc_value, bpc_mz = _tic_bpc(mz, intensity, reported)
    centroid = None
    if "centroid spectrum" in spec:
        centroid = True
    elif "profile spectrum" in spec:
        centroid = False
    return Scan(
        index_in_file=index_in_file,
        scan_number=_scan_number_from_id(spectrum_id, index_in_file),
        ms_level=ms_level,
        polarity=polarity,
        rt_min=rt_min,
        rt_unit=rt_unit,
        scan_mode=mode,
        scan_mode_basis=basis,
        precursor_mz=precursor_mz,
        precursor_charge=precursor_charge,
        isolation_lower_offset=lower,
        isolation_upper_offset=upper,
        isolation_width=width,
        collision_energy=_collision_energy(activation if isinstance(activation, dict) else None),
        activation=_activation_name(activation if isinstance(activation, dict) else None),
        tic=tic_value,
        bpc=bpc_value,
        bpc_mz=bpc_mz,
        reported_tic=reported,
        centroid=centroid,
        filter_string=filter_string,
        mz=mz,
        intensity=intensity,
        cv_terms=tuple(names),
    )


def _scan_from_mzxml(spec: dict, header: RunHeader, index_in_file: int) -> Scan:
    ms_level = _as_int(spec.get("msLevel"))
    polarity_raw = str(spec.get("polarity") or "")
    if polarity_raw == "+":
        polarity = "positive"
    elif polarity_raw == "-":
        polarity = "negative"
    else:
        polarity = "unknown"
    retention = spec.get("retentionTime")
    # pyteomics 通常把 PT 时间转成秒的浮点，并带 unit。未知时按分钟处理 mzXML 的常见秒值。
    rt_min, rt_unit = _rt_from_mzxml(retention)
    precursor_mz = _as_float(spec.get("precursorMz"))
    # 前体有时是 list of dict
    if precursor_mz is None and "precursorMz" in spec and isinstance(spec["precursorMz"], list):
        first = spec["precursorMz"][0]
        if isinstance(first, dict):
            precursor_mz = _as_float(first.get("precursorMz"))
    collision = _as_float(spec.get("collisionEnergy"))
    activation = spec.get("activationMethod")
    activation = str(activation) if activation else None
    filter_string = None
    names = []
    if ms_level == 1:
        names.append("MS1 spectrum")
    elif ms_level and ms_level >= 2:
        names.append("MSn spectrum")
    mode, basis = classify_scan_mode(
        ms_level=ms_level,
        term_names=names,
        file_terms=header.acquisition_terms,
        isolation_width=None,
        precursor_mz=precursor_mz,
    )
    mz, intensity = _arrays(spec)
    reported = _as_float(spec.get("totIonCurrent"))
    tic_value, bpc_value, bpc_mz = _tic_bpc(mz, intensity, reported)
    scan_number = _as_int(spec.get("num")) or _as_int(spec.get("id")) or (index_in_file + 1)
    centroid = None
    if str(spec.get("centroided")) in {"1", "true", "True"}:
        centroid = True
    return Scan(
        index_in_file=index_in_file,
        scan_number=int(scan_number),
        ms_level=ms_level,
        polarity=polarity,
        rt_min=rt_min,
        rt_unit=rt_unit,
        scan_mode=mode,
        scan_mode_basis=basis,
        precursor_mz=precursor_mz,
        precursor_charge=None,
        isolation_lower_offset=None,
        isolation_upper_offset=None,
        isolation_width=None,
        collision_energy=collision,
        activation=activation,
        tic=tic_value,
        bpc=bpc_value,
        bpc_mz=bpc_mz,
        reported_tic=reported,
        centroid=centroid,
        filter_string=filter_string,
        mz=mz,
        intensity=intensity,
        cv_terms=tuple(names),
    )


def _rt_from_mzxml(value) -> tuple[float | None, str | None]:
    if value is None:
        return None, None
    unit = _unit(value)
    number = _as_float(value)
    if number is None:
        return None, unit
    if unit and "minute" in unit.lower():
        return number, unit
    # mzXML 的 retentionTime 属性是 xs:duration，pyteomics 转成秒。
    if unit is None or "second" in unit.lower():
        return number / 60.0, unit or "second"
    return number, unit
