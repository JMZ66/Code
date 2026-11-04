import numpy as np

from gcms_kb.chromatogram import eic, tic_bpc
from gcms_kb.peaks import detect_peaks
from gcms_kb.ri import AlkanePoint, parse_alkane_csv, retention_index
from gcms_kb.spectrum_math import nominal_subtract


def test_tic_bpc_eic_known_values():
    mz = [np.array([50.0, 100.0]), np.array([50.0, 100.0])]
    intensity = [np.array([10.0, 30.0]), np.array([5.0, 1.0])]
    tic, bpc = tic_bpc(intensity)
    assert tic.tolist() == [40.0, 6.0]
    assert bpc.tolist() == [30.0, 5.0]
    assert eic(mz, intensity, 100.0, 0.1).tolist() == [30.0, 1.0]
    assert eic(mz, intensity, 80.0, 0.1).tolist() == [0.0, 0.0]


def test_gaussian_peak_area_matches_analytical():
    rt = np.arange(4.0, 6.0, 0.002)
    height = 1000.0
    sigma = 0.05
    intensity = height * np.exp(-0.5 * ((rt - 5.0) / sigma) ** 2)
    expected = height * sigma * np.sqrt(2 * np.pi)
    peaks = detect_peaks(rt, intensity)
    assert len(peaks) == 1
    assert abs(peaks[0].rt - 5.0) < 0.004
    assert abs(peaks[0].area - expected) / expected < 0.03


def test_two_separated_peaks_keep_their_areas():
    rt = np.arange(0.0, 10.0, 0.01)
    sigma = 0.08
    y = 500 * np.exp(-0.5 * ((rt - 3.0) / sigma) ** 2)
    y += 800 * np.exp(-0.5 * ((rt - 7.0) / sigma) ** 2)
    peaks = detect_peaks(rt, y)
    assert len(peaks) == 2
    expected = [500 * sigma * np.sqrt(2 * np.pi), 800 * sigma * np.sqrt(2 * np.pi)]
    got = sorted(peak.area for peak in peaks)
    for left, right in zip(got, expected):
        assert abs(left - right) / right < 0.03


def test_van_den_dool_kratz_and_extrapolation():
    points = [
        AlkanePoint(10, 4.0, "C10"),
        AlkanePoint(11, 5.0, "C11"),
        AlkanePoint(12, 6.5, "C12"),
    ]
    mid = retention_index(4.5, points)
    assert mid.extrapolated is False
    assert mid.ri == 1050
    later = retention_index(5.75, points)
    assert later.ri == 1150
    early = retention_index(3.0, points)
    assert early.extrapolated is True
    assert early.ri == 900
    gapped = retention_index(5.0, [AlkanePoint(10, 4.0), AlkanePoint(12, 6.0)])
    assert gapped.ri == 1100


def test_alkane_csv_roundtrip_text():
    points = parse_alkane_csv("carbon_number,rt_min,name\n10,4.0,n-decane\n11,5.2,n-undecane\n")
    assert points[0].carbon_number == 10
    assert points[1].rt == 5.2


def test_background_subtraction_removes_shared_nominal_ion():
    mz, inten = nominal_subtract([91, 92], [100, 20], [91], [40])
    assert list(mz) == [91, 92]
    assert list(inten) == [60, 20]
