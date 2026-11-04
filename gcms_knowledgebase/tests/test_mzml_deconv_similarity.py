from pathlib import Path

import numpy as np
from matchms.similarity import CosineGreedy
from pyteomics import mzml

from gcms_kb.deconvolution import deconvolve
from gcms_kb.msp_io import read_msp, write_msp
from gcms_kb.mzml_io import _offline_cv, read_mzml, time_unit, write_mzml
from gcms_kb.similarity import cosine_scores

PUBLIC_MZML = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "gcms_kb"
    / "resources"
    / "testdata"
    / "public"
    / "small.pwiz.1.1.mzML"
)


def _scans_for(rt, centers):
    scans = []
    for time in rt:
        mz = []
        inten = []
        for center, ions in centers:
            shape = np.exp(-0.5 * ((time - center) / 0.04) ** 2)
            for mass, height in ions:
                mz.append(mass)
                inten.append(height * shape)
        scans.append((np.array(mz, dtype=float), np.array(inten, dtype=float)))
    return scans


def test_synthetic_mzml_roundtrip_tic(tmp_path):
    rt = np.array([1.0, 2.0, 3.0])
    scans = [
        (np.array([50.0, 100.0]), np.array([10.0, 30.0])),
        (np.array([50.0, 100.0]), np.array([5.0, 1.0])),
        (np.array([91.0]), np.array([8.0])),
    ]
    path = tmp_path / "synthetic.mzML"
    write_mzml(path, rt, scans, synthetic=True)
    assert time_unit(path) == "minute"
    run = read_mzml(path)
    assert run.is_synthetic is True
    assert run.n_scans == 3
    assert run.tic.tolist() == [40.0, 6.0, 8.0]
    assert run.bpc.tolist() == [30.0, 5.0, 8.0]
    eic91 = [float(run.scan(i)[1][np.rint(run.scan(i)[0]) == 91].sum()) if run.scan(i)[0].size else 0 for i in range(3)]
    assert eic91 == [0.0, 0.0, 8.0]
    try:
        write_mzml(path, rt, scans, synthetic=False)
    except ValueError:
        pass
    else:
        raise AssertionError("合成写入器必须拒绝未标记的文件")


def test_public_thermo_mzml_tic_matches_pyteomics():
    assert PUBLIC_MZML.is_file()
    text = PUBLIC_MZML.read_text(encoding="utf-8", errors="ignore")
    assert "ESI" in text and "FTMS" in text
    assert "gcms_kb_synthetic" not in text
    unit = time_unit(PUBLIC_MZML)
    run = read_mzml(PUBLIC_MZML)
    pairs = []
    with mzml.MzML(str(PUBLIC_MZML), read_schema=False, huge_tree=True, cv=_offline_cv()) as reader:
        for spectrum in reader:
            level = int(spectrum.get("ms level") or 1)
            if level != 1:
                continue
            scans = spectrum.get("scanList", {}).get("scan") or []
            if isinstance(scans, dict):
                scans = [scans]
            if not scans or scans[0].get("scan start time") is None:
                continue
            rt = float(scans[0]["scan start time"])
            if unit == "second":
                rt /= 60.0
            inten = spectrum.get("intensity array")
            total = 0.0 if inten is None else float(np.nansum(np.asarray(inten, dtype=float)))
            pairs.append((rt, total))
    pairs.sort()
    assert len(pairs) == run.n_scans
    assert run.n_scans > 10
    np.testing.assert_allclose(run.tic, [item[1] for item in pairs], rtol=1e-5, atol=1e-2)
    assert "ESI" in (run.file_hint or text)


def test_deconvolution_splits_overlapping_components():
    rt = np.arange(4.6, 5.8, 0.01)
    scans = _scans_for(
        rt,
        [
            (5.0, [(91.0, 1000.0), (65.0, 400.0)]),
            (5.15, [(105.0, 1000.0), (65.0, 500.0)]),
        ],
    )
    components, _note = deconvolve(
        rt,
        [item[0] for item in scans],
        [item[1] for item in scans],
        apex_tol=0.05,
    )
    assert len(components) == 2
    first, second = components

    def at(component, mass):
        keys = np.rint(component.mz)
        found = np.where(keys == mass)[0]
        return 0.0 if found.size == 0 else float(component.intensity[found[0]])

    assert at(first, 91) > 5 * at(first, 105)
    assert at(second, 105) > 5 * at(second, 91)
    assert at(first, 65) > 0
    assert at(second, 65) > 0
    assert abs(first.rt - 5.0) < 0.03
    assert abs(second.rt - 5.15) < 0.03


def test_similarity_matches_matchms_and_reverse_ignores_extra_ion():
    ref_mz = np.array([65.0, 91.0, 92.0])
    ref_i = np.array([20.0, 100.0, 40.0])
    query_mz = np.array([65.0, 91.0, 92.0, 200.0])
    query_i = np.array([20.0, 100.0, 40.0, 80.0])
    forward, matched, reverse = cosine_scores(
        query_mz, query_i, ref_mz, ref_i, tolerance=0.1, mz_power=1.0, intensity_power=0.5
    )
    from gcms_kb.similarity import to_spectrum

    cosine = CosineGreedy(tolerance=0.1, mz_power=1.0, intensity_power=0.5)
    reference = to_spectrum(ref_mz, ref_i)
    query = to_spectrum(query_mz, query_i)
    expected = cosine.pair(reference, query)
    if isinstance(expected, np.ndarray):
        expected = expected.item()
    assert forward == float(expected[0])
    assert matched == int(expected[1])
    pure, _n, pure_reverse = cosine_scores(ref_mz, ref_i, ref_mz, ref_i, tolerance=0.1, mz_power=1.0, intensity_power=0.5)
    assert pure == 1
    assert reverse == pure_reverse == 1
    assert reverse > forward


def test_msp_roundtrip(tmp_path):
    path = tmp_path / "lib.msp"
    write_msp(
        path,
        [
            {
                "name": "甲苯",
                "cas": "108-88-3",
                "formula": "C7H8",
                "ri": 763,
                "comment": "合成示例，不是标准谱",
                "mz": [65, 91, 92],
                "intensity": [20, 100, 40],
            }
        ],
    )
    loaded = read_msp(path)
    assert loaded[0]["name"] == "甲苯"
    assert loaded[0]["cas"] == "108-88-3"
    assert loaded[0]["formula"] == "C7H8"
    assert loaded[0]["ri"] == 763
    assert loaded[0]["mz"].tolist() == [65, 91, 92]
    assert loaded[0]["intensity"].tolist() == [20, 100, 40]
    again = tmp_path / "again.msp"
    write_msp(again, loaded)
    reloaded = read_msp(again)
    assert reloaded[0]["name"] == "甲苯"
    assert reloaded[0]["mz"].tolist() == [65.0, 91.0, 92.0]
