"""mzML / mzXML 元数据、色谱和原始文件哈希。"""

from pathlib import Path

import numpy as np
import pytest

from lcms_kb.core.chromatogram import bpc, eic, subtract_trace, tic
from lcms_kb.core.readers import read_run
from lcms_kb.hashing import sha256_file
from tests.synthetic_mzml import write_blank_mzml, write_synthetic_mzml, write_synthetic_mzxml

PUBLIC = Path(__file__).parent / "data" / "public"


def test_synthetic_metadata_polarity_level_ce_and_mode(tmp_path):
    path = write_synthetic_mzml(tmp_path / "synthetic.mzML")
    before = sha256_file(path)
    header, scans = read_run(path)
    assert sha256_file(path) == before
    assert header.test_only_synthetic
    assert header.spectrum_count_declared == 11
    assert len(scans) == 11

    by_scan = {scan.scan_number: scan for scan in scans}
    assert by_scan[1].polarity == "positive" and by_scan[1].ms_level == 1
    assert by_scan[1].scan_mode == "full_scan"
    assert by_scan[3].polarity == "negative" and by_scan[3].ms_level == 1
    assert by_scan[4].ms_level == 2
    assert by_scan[4].scan_mode == "dda"
    assert by_scan[4].collision_energy == pytest.approx(20)
    assert by_scan[4].activation == "collision-induced dissociation"
    assert by_scan[4].precursor_mz == pytest.approx(200)
    assert by_scan[5].collision_energy == pytest.approx(40)
    assert "beam-type" in by_scan[5].activation
    assert by_scan[6].polarity == "negative"
    assert by_scan[7].scan_mode == "dia"
    assert by_scan[7].scan_mode_basis.startswith("cv")
    assert by_scan[8].scan_mode == "sim"
    assert by_scan[9].scan_mode == "srm"
    assert by_scan[10].scan_mode == "dia" and by_scan[10].scan_mode_basis.startswith("heuristic")
    assert by_scan[11].scan_mode == "dia_aif"
    ms2 = [scan for scan in scans if scan.ms_level == 2]
    assert len(ms2) == 7


def test_tic_bpc_eic_do_not_mix_polarity(tmp_path):
    _header, scans = read_run(write_synthetic_mzml(tmp_path / "s.mzML"))
    positive = tic(scans, polarity="positive", ms_level=1, scan_modes={"full_scan"})
    assert list(positive.rt_min) == pytest.approx([1.0, 2.0])
    assert list(positive.intensity) == pytest.approx([45, 30])
    positive_bpc = bpc(scans, polarity="positive", ms_level=1, scan_modes={"full_scan"})
    assert list(positive_bpc.intensity) == pytest.approx([30, 20])
    assert list(positive_bpc.extra_mz) == pytest.approx([200, 100])
    extracted = eic(scans, 200.0, 10, "ppm", polarity="positive", ms_level=1, scan_modes={"full_scan"})
    # 10 ppm 在 m/z 200 处约 0.002 Da，只能吃到 200 这个峰：30 和 10。
    assert list(extracted.intensity) == pytest.approx([30, 10])
    # 不按扫描模式过滤时，SIM 会进入 MS1 曲线。这是显式选择，不是默默混合。
    with_sim = tic(scans, polarity="positive", ms_level=1)
    assert 100 in list(with_sim.intensity)
    negative = eic(scans, 200.0, 0.01, "da", polarity="negative", ms_level=1)
    assert list(negative.intensity) == pytest.approx([0])
    assert negative.polarity == "negative"
    assert positive.layer == "raw_signal"


def test_blank_subtraction_is_labeled_algorithm_result(tmp_path):
    sample = eic(read_run(write_synthetic_mzml(tmp_path / "s.mzML"))[1], 200, 0.01, "da",
                 polarity="positive", ms_level=1)
    # 空白文件只有两个时间点，和样品 EIC 时间轴不同，直接相减应拒绝。
    blank = eic(read_run(write_blank_mzml(tmp_path / "b.mzML"))[1], 200, 0.01, "da",
                polarity="positive", ms_level=1)
    with pytest.raises(ValueError):
        subtract_trace(sample, blank)
    # 同一时间轴上的扣减：用空白自身减去一条更低的曲线。
    derived = subtract_trace(blank, blank)
    assert derived.layer == "algorithm_result"
    assert np.all(derived.intensity == 0)


def test_mzxml_polarity_rt_and_precursor(tmp_path):
    header, scans = read_run(write_synthetic_mzxml(tmp_path / "s.mzXML"))
    assert header.test_only_synthetic
    assert scans[0].polarity == "positive"
    assert scans[0].rt_min == pytest.approx(1.5)
    assert scans[0].tic == pytest.approx(45)
    assert scans[1].polarity == "negative"
    assert scans[1].ms_level == 2
    assert scans[1].precursor_mz == pytest.approx(150)
    assert scans[1].collision_energy == pytest.approx(25)
    assert list(scans[1].mz) == pytest.approx([40, 70])


def test_public_thermo_and_waters_files_are_positive_ms1_only():
    thermo = PUBLIC / "pymzml_example_qexactive_pos.mzML"
    waters = PUBLIC / "arabidopsis_waters_pos_ms1.mzML"
    before = {thermo: sha256_file(thermo), waters: sha256_file(waters)}
    th, ts = read_run(thermo)
    wh, ws = read_run(waters)
    assert sha256_file(thermo) == before[thermo]
    assert sha256_file(waters) == before[waters]
    assert "Thermo" in th.vendors_inferred
    assert any("Q Exactive" in term for term in th.instrument_terms)
    assert len(ts) == 11
    assert all(scan.ms_level == 1 and scan.polarity == "positive" for scan in ts)
    assert all(scan.collision_energy is None for scan in ts)
    assert "Waters" in wh.vendors_inferred
    assert len(ws) == 800
    assert all(scan.ms_level == 1 and scan.polarity == "positive" for scan in ws)
    assert ws[0].rt_min == pytest.approx(0.0692333356, rel=1e-5)
    assert ws[-1].rt_min == pytest.approx(34.6226349, rel=1e-5)
    # 第一张谱的 TIC 等于峰强度之和，不靠文件里申报的总离子流硬凑。
    assert ts[0].tic == pytest.approx(float(np.sum(ts[0].intensity)))
    assert ws[0].tic == pytest.approx(float(np.sum(ws[0].intensity)))


def test_reader_does_not_need_network(tmp_path, monkeypatch):
    def blocked(*_args, **_kwargs):
        raise RuntimeError("network blocked")

    monkeypatch.setattr("urllib.request.urlopen", blocked)
    read_run(write_synthetic_mzml(tmp_path / "s.mzML"))
