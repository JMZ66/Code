from __future__ import annotations

import base64
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from pyteomics import mzml

from gcms_kb.chromatogram import tic_bpc
from gcms_kb.errors import EmptyRun

_CV = None


def _offline_cv():
    """读取随程序打包的 PSI-MS 词表，避免 pyteomics 去联网，也不依赖 psims 安装目录里的数据文件。"""
    global _CV
    if _CV is None:
        import gzip

        from psims.controlled_vocabulary.controlled_vocabulary import ControlledVocabulary

        from gcms_kb.paths import resource_path

        with gzip.open(resource_path("obo", "psi-ms.obo.gz"), "rb") as handle:
            _CV = ControlledVocabulary.from_obo(handle)
    return _CV


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


@dataclass
class RunData:
    rt: np.ndarray
    tic: np.ndarray
    bpc: np.ndarray
    offsets: np.ndarray
    mz: np.ndarray
    intensity: np.ndarray
    file_hint: str
    instrument: str
    is_synthetic: bool
    n_scans: int

    def scan(self, index: int) -> tuple[np.ndarray, np.ndarray]:
        start = int(self.offsets[index])
        stop = int(self.offsets[index + 1])
        return self.mz[start:stop], self.intensity[start:stop]

    def scans(self) -> tuple[list[np.ndarray], list[np.ndarray]]:
        mz_list = []
        int_list = []
        for index in range(self.n_scans):
            mz, inten = self.scan(index)
            mz_list.append(mz)
            int_list.append(inten)
        return mz_list, int_list

    @classmethod
    def from_scans(
        cls,
        rt,
        scans_mz: list[np.ndarray],
        scans_i: list[np.ndarray],
        *,
        file_hint: str = "",
        instrument: str = "",
        is_synthetic: bool = False,
    ) -> "RunData":
        rt_arr = np.asarray(rt, dtype=float)
        order = np.argsort(rt_arr, kind="mergesort")
        rt_arr = rt_arr[order]
        ordered_mz = [np.asarray(scans_mz[int(i)], dtype=float) for i in order]
        ordered_i = [np.asarray(scans_i[int(i)], dtype=float) for i in order]
        tic, bpc = tic_bpc(ordered_i)
        offsets = np.zeros(len(rt_arr) + 1, dtype=np.int64)
        flat_mz = []
        flat_i = []
        for index, (mz, inten) in enumerate(zip(ordered_mz, ordered_i)):
            if mz.size:
                mask = np.isfinite(mz) & np.isfinite(inten) & (mz > 0)
                mz = mz[mask]
                inten = np.clip(inten[mask], 0, None)
                sort = np.argsort(mz)
                mz = np.ascontiguousarray(mz[sort], dtype=np.float64)
                inten = np.ascontiguousarray(inten[sort], dtype=np.float64)
            else:
                mz = np.array([], dtype=np.float64)
                inten = np.array([], dtype=np.float64)
            flat_mz.append(mz)
            flat_i.append(inten)
            offsets[index + 1] = offsets[index] + mz.size
        return cls(
            rt=rt_arr,
            tic=tic,
            bpc=bpc,
            offsets=offsets,
            mz=np.concatenate(flat_mz) if flat_mz else np.array([], dtype=np.float64),
            intensity=np.concatenate(flat_i) if flat_i else np.array([], dtype=np.float64),
            file_hint=file_hint,
            instrument=instrument,
            is_synthetic=is_synthetic,
            n_scans=int(len(rt_arr)),
        )


def time_unit(path: Path) -> str:
    """读取第一个 scan start time 的单位。UO:0000010 为秒，其余按分钟。"""
    for _event, elem in ET.iterparse(path, events=("end",)):
        if elem.tag.endswith("cvParam") and elem.get("accession") == "MS:1000016":
            accession = (elem.get("unitAccession") or "").upper()
            name = (elem.get("unitName") or "").lower()
            if accession == "UO:0000010" or name.startswith("sec"):
                return "second"
            return "minute"
        elem.clear()
    return "minute"


def _instrument_name(path: Path) -> str:
    try:
        text = path.read_bytes()[:500_000].decode("utf-8", errors="ignore")
    except OSError:
        return ""
    marker = 'accession="MS:1000031"'
    position = text.find(marker)
    if position >= 0:
        window = text[position : position + 300]
        name_at = window.find('name="')
        if name_at >= 0:
            rest = window[name_at + 6 :]
            return rest.split('"', 1)[0]
    return ""


def _looks_synthetic(path: Path, file_hint: str) -> bool:
    if "gcms_kb_synthetic" in file_hint.lower():
        return True
    try:
        head = path.read_bytes()[:300_000].decode("utf-8", errors="ignore").lower()
    except OSError:
        return False
    return "gcms_kb_synthetic" in head


def read_mzml(path: Path) -> RunData:
    """用 pyteomics 读取 mzML。只汇总 MS1。TIC/BPC 由谱图重新计算。"""
    path = Path(path)
    unit = time_unit(path)
    rt_values: list[float] = []
    mz_list: list[np.ndarray] = []
    int_list: list[np.ndarray] = []
    file_hint = ""
    with mzml.MzML(str(path), read_schema=False, huge_tree=True, cv=_offline_cv()) as reader:
        for spectrum in reader:
            level = spectrum.get("ms level")
            try:
                level = int(level)
            except (TypeError, ValueError):
                level = 1
            if level != 1:
                continue
            scans = _as_list(spectrum.get("scanList", {}).get("scan"))
            if not scans:
                continue
            scan = scans[0]
            rt = scan.get("scan start time")
            if rt is None:
                continue
            rt = float(rt)
            if unit == "second":
                rt = rt / 60.0
            if not file_hint:
                file_hint = str(scan.get("filter string") or "")
            mz = spectrum.get("m/z array")
            inten = spectrum.get("intensity array")
            mz_arr = np.array([], dtype=float) if mz is None else np.asarray(mz, dtype=float)
            in_arr = np.array([], dtype=float) if inten is None else np.asarray(inten, dtype=float)
            rt_values.append(rt)
            mz_list.append(mz_arr)
            int_list.append(in_arr)
    if not rt_values:
        raise EmptyRun(f"文件中没有可用的 MS1 扫描：{path.name}")
    instrument = _instrument_name(path)
    return RunData.from_scans(
        rt_values,
        mz_list,
        int_list,
        file_hint=file_hint,
        instrument=instrument,
        is_synthetic=_looks_synthetic(path, file_hint),
    )


def _encode(values: np.ndarray) -> tuple[str, int, int]:
    raw = np.ascontiguousarray(values, dtype="<f8").tobytes()
    text = base64.b64encode(raw).decode("ascii")
    return text, len(text), int(np.asarray(values).size)


def write_mzml(path: Path, rt_min, scans: list[tuple[np.ndarray, np.ndarray]], *, synthetic: bool) -> None:
    """写出本程序生成的 mzML。只允许 synthetic=True，避免把合成谱伪装成仪器文件。"""
    if synthetic is not True:
        raise ValueError("write_mzml 只允许写出明确标记为合成数据的文件")
    rt_min = np.asarray(rt_min, dtype=float)
    if len(rt_min) != len(scans):
        raise ValueError("扫描数与保留时间数量不一致")
    parts = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<mzML xmlns="http://psi.hupo.org/ms/mzml" version="1.1.0">',
        "  <cvList count=\"2\">",
        '    <cv id="MS" fullName="Proteomics Standards Initiative Mass Spectrometry Ontology" version="4.1.0" URI="https://purl.obolibrary.org/obo/ms.obo"/>',
        '    <cv id="UO" fullName="Unit Ontology" version="2023" URI="https://purl.obolibrary.org/obo/uo.obo"/>',
        "  </cvList>",
        "  <fileDescription>",
        "    <fileContent>",
        '      <cvParam cvRef="MS" accession="MS:1000579" name="MS1 spectrum" value=""/>',
        "    </fileContent>",
        "  </fileDescription>",
        '  <softwareList count="1">',
        '    <software id="gcms_kb_synthetic" version="1.0.0">',
        '      <cvParam cvRef="MS" accession="MS:1000799" name="custom unreleased software tool" value="synthetic GC-MS EI data generated by gcms_kb_synthetic; NOT a real instrument file"/>',
        "    </software>",
        "  </softwareList>",
        '  <instrumentConfigurationList count="1">',
        '    <instrumentConfiguration id="IC1">',
        '      <cvParam cvRef="MS" accession="MS:1000031" name="gcms_kb_synthetic" value=""/>',
        "    </instrumentConfiguration>",
        "  </instrumentConfigurationList>",
        '  <dataProcessingList count="1">',
        '    <dataProcessing id="dp1">',
        '      <processingMethod order="0" softwareRef="gcms_kb_synthetic">',
        '        <cvParam cvRef="MS" accession="MS:1000544" name="Conversion to mzML" value="synthetic"/>',
        "      </processingMethod>",
        "    </dataProcessing>",
        "  </dataProcessingList>",
        '  <run id="gcms_kb_synthetic" defaultInstrumentConfigurationRef="IC1">',
        f'    <spectrumList count="{len(scans)}" defaultDataProcessingRef="dp1">',
    ]
    for index, (rt, (mz, inten)) in enumerate(zip(rt_min, scans)):
        mz = np.asarray(mz, dtype=float)
        inten = np.asarray(inten, dtype=float)
        mz_text, mz_len, n_peaks = _encode(mz)
        in_text, in_len, _n = _encode(inten)
        parts.append(
            f'      <spectrum id="scan={index + 1}" index="{index}" defaultArrayLength="{n_peaks}">'
        )
        parts.append('        <cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="1"/>')
        parts.append('        <cvParam cvRef="MS" accession="MS:1000127" name="centroid spectrum" value=""/>')
        parts.append('        <scanList count="1">')
        parts.append("          <scan>")
        parts.append(
            f'            <cvParam cvRef="MS" accession="MS:1000016" name="scan start time" value="{float(rt):.8f}" unitCvRef="UO" unitAccession="UO:0000031" unitName="minute"/>'
        )
        parts.append(
            '            <cvParam cvRef="MS" accession="MS:1000512" name="filter string" value="SYNTHETIC GC-EI centroid gcms_kb_synthetic"/>'
        )
        parts.append("          </scan>")
        parts.append("        </scanList>")
        parts.append('        <binaryDataArrayList count="2">')
        parts.append(f'          <binaryDataArray encodedLength="{mz_len}">')
        parts.append('            <cvParam cvRef="MS" accession="MS:1000523" name="64-bit float" value=""/>')
        parts.append('            <cvParam cvRef="MS" accession="MS:1000576" name="no compression" value=""/>')
        parts.append('            <cvParam cvRef="MS" accession="MS:1000514" name="m/z array" value="" unitCvRef="MS" unitAccession="MS:1000040" unitName="m/z"/>')
        parts.append(f"            <binary>{mz_text}</binary>")
        parts.append("          </binaryDataArray>")
        parts.append(f'          <binaryDataArray encodedLength="{in_len}">')
        parts.append('            <cvParam cvRef="MS" accession="MS:1000523" name="64-bit float" value=""/>')
        parts.append('            <cvParam cvRef="MS" accession="MS:1000576" name="no compression" value=""/>')
        parts.append('            <cvParam cvRef="MS" accession="MS:1000515" name="intensity array" value="" unitCvRef="MS" unitAccession="MS:1000131" unitName="number of detector counts"/>')
        parts.append(f"            <binary>{in_text}</binary>")
        parts.append("          </binaryDataArray>")
        parts.append("        </binaryDataArrayList>")
        parts.append("      </spectrum>")
    parts.extend(
        [
            "    </spectrumList>",
            "  </run>",
            "</mzML>",
            "",
        ]
    )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts), encoding="utf-8")
