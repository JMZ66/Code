"""Independent numerical checks. Expected values are literals, not calls back into the engine."""

import math
import shutil
from pathlib import Path

import pytest
from scipy import stats

from labuv.errors import LabError
from labuv.examples import load_example
from labuv.expression import compile_expression
from labuv.importers import import_table
from labuv.lod import lod_loq
from labuv.montecarlo import coverage_interval, numerical_tolerance
from labuv.paths import examples_dir
from labuv.precision import analyze_precision
from labuv.regression import fit_line
from labuv.topdown import evaluate_topdown
from labuv.trueness import crm_bias, spike_recovery
from labuv.uncertainty import evaluate_bottom_up
from labuv.validation_summary import summarize


def test_statistics_and_welch_satterthwaite_literals():
    result = evaluate_bottom_up(
        {
            "expression": "x1 + x2",
            "inputs": [
                {"name": "x1", "kind": "A", "role": "mean", "unit": "1", "raw": [10, 10.2, 9.8, 10.1, 9.9], "source": "手算"},
                {"name": "x2", "estimate": 5, "unit": "1", "kind": "B", "distribution": "normal", "u_mode": "standard", "u": 0.1, "source": "手算"},
            ],
            "coverage": {"mode": "probability", "p": 0.95},
        }
    )
    # s^2 = 0.10/4 = 0.025; u(mean)=sqrt(0.025/5)=sqrt(0.005); uc=sqrt(0.005+0.01)=sqrt(0.015)
    assert result["y"] == pytest.approx(15)
    assert result["uc"] == pytest.approx(math.sqrt(0.015))
    assert result["veff"] == pytest.approx(36)
    assert result["coverage"]["k"] == pytest.approx(stats.t.ppf(0.975, 36))
    assert result["coverage"]["k"] == pytest.approx(2.0280940009804502)


def test_correlated_product_and_refusal_of_effective_degrees_of_freedom():
    result = evaluate_bottom_up(
        {
            "expression": "x1 * x2",
            "inputs": [
                {"name": "x1", "estimate": 10, "unit": "1", "kind": "B", "distribution": "normal", "u_mode": "standard", "u": 0.1, "source": "手算"},
                {"name": "x2", "estimate": 2, "unit": "1", "kind": "B", "distribution": "normal", "u_mode": "standard", "u": 0.02, "source": "手算"},
            ],
            "correlation": [[1, 0.5], [0.5, 1]],
            "correlation_names": ["x1", "x2"],
            "coverage": {"mode": "k", "k": 2},
        }
    )
    # u^2 = 0.04 + 0.04 + 2*2*10*0.5*0.1*0.02 = 0.12
    assert result["uc"] == pytest.approx(math.sqrt(0.12))
    assert result["veff_applicable"] is False
    with pytest.raises(LabError, match="相关"):
        evaluate_bottom_up(
            {
                "expression": "x1 * x2",
                "inputs": [
                    {"name": "x1", "estimate": 10, "unit": "1", "kind": "B", "distribution": "normal", "u_mode": "standard", "u": 0.1, "source": "手算"},
                    {"name": "x2", "estimate": 2, "unit": "1", "kind": "B", "distribution": "rectangular", "u_mode": "half_width", "half_width": 0.02 * math.sqrt(3), "source": "手算"},
                ],
                "correlation": [[1, 0.2], [0.2, 1]],
                "coverage": {"mode": "k", "k": 2},
                "monte_carlo": {"enabled": True, "seed": 1, "n": 2000, "p": 0.95},
            }
        )


def test_illegal_correlation_matrices_are_rejected():
    base = {
        "expression": "x1 + x2",
        "inputs": [
            {"name": "x1", "estimate": 1, "unit": "1", "kind": "B", "distribution": "normal", "u_mode": "standard", "u": 0.1, "source": "s"},
            {"name": "x2", "estimate": 1, "unit": "1", "kind": "B", "distribution": "normal", "u_mode": "standard", "u": 0.1, "source": "s"},
        ],
        "coverage": {"mode": "k", "k": 2},
    }
    for matrix in ([[1, 0.2], [0.1, 1]], [[1, 1.2], [1.2, 1]], [[0.9, 0], [0, 1]], [[1, 0.9], [0.9, 0.2]]):
        with pytest.raises(LabError):
            evaluate_bottom_up({**base, "correlation": matrix})


def test_rectangular_triangular_and_units():
    rectangular = evaluate_bottom_up(
        {
            "expression": "x",
            "inputs": [{"name": "x", "estimate": 10, "unit": "mg", "kind": "B", "distribution": "rectangular", "u_mode": "half_width", "half_width": 3, "source": "s"}],
            "coverage": {"mode": "k", "k": 2},
        }
    )
    assert rectangular["uc"] == pytest.approx(3 / math.sqrt(3))
    triangular = evaluate_bottom_up(
        {
            "expression": "x",
            "inputs": [{"name": "x", "estimate": 10, "unit": "mg", "kind": "B", "distribution": "triangular", "u_mode": "half_width", "half_width": 3, "source": "s"}],
            "coverage": {"mode": "k", "k": 2},
        }
    )
    assert triangular["uc"] == pytest.approx(3 / math.sqrt(6))
    with pytest.raises(LabError, match="单位"):
        evaluate_bottom_up(
            {
                "expression": "a + b",
                "inputs": [
                    {"name": "a", "estimate": 1, "unit": "mg", "kind": "B", "distribution": "normal", "u_mode": "standard", "u": 0.1, "source": "s"},
                    {"name": "b", "estimate": 1, "unit": "s", "kind": "B", "distribution": "normal", "u_mode": "standard", "u": 0.1, "source": "s"},
                ],
                "coverage": {"mode": "k", "k": 2},
            }
        )


def test_percent_purity_and_standard_solution_literal():
    result = evaluate_bottom_up(load_example("standard_solution.json"))
    # c = 100*0.995*1/(100*100) = 0.00995 mg/mL
    # uP = (0.5 percentage point)/sqrt(3) = 0.005/sqrt(3) as a fraction
    purity_fraction = 0.995
    u_purity = 0.005 / math.sqrt(3)
    relative = math.sqrt((0.1 / 100) ** 2 + (u_purity / purity_fraction) ** 2 + (0.08 / 100) ** 2 + (0.01 / 1) ** 2 + (0.08 / 100) ** 2)
    assert result["y"] == pytest.approx(0.00995)
    assert result["uc"] == pytest.approx(0.00995 * relative)
    assert result["uc"] == pytest.approx(0.00010468671851449608)


def test_migration_does_not_confuse_area_and_volume():
    result = evaluate_bottom_up(load_example("migration.json"))
    assert result["y"] == pytest.approx(0.9)
    assert result["uc"] == pytest.approx(0.049246827308974936)
    assert "mg" in result["unit"]
    doubled = load_example("migration.json")
    doubled["expression"] = "(c_meas - c_blank) * D * V * V / A"
    with pytest.raises(LabError, match="量纲"):
        evaluate_bottom_up(doubled)


def test_icp_bottom_up_literal_and_separate_topdown_model():
    bottom = evaluate_bottom_up(load_example("icp_bottom.json"))
    assert bottom["y"] == pytest.approx(0.02)
    assert bottom["uc"] == pytest.approx(0.00054)
    top = evaluate_topdown(load_example("icp_topdown.json"))
    expected = 0.02 * math.sqrt(0.03 ** 2 + 0.02 ** 2)
    assert top["uc"] == pytest.approx(expected)
    blocked = load_example("icp_topdown.json")
    blocked["precision_includes_recovery"] = True
    with pytest.raises(LabError, match="已经包含"):
        evaluate_topdown(blocked)


def test_published_phosphate_recovery_matches_equation_9():
    result = evaluate_topdown(load_example("phosphate_recovery.json"))
    items = [(2.31, 2.24, 0.11, 12, 0.05), (1.032, 1.0, 0.09, 10, 0.025), (1.70, 1.77, 0.14, 1, 0.115)]
    recoveries = []
    variances = []
    for mean, reference, standard, count, u_reference in items:
        recovery = mean / reference
        variances.append(recovery ** 2 * ((standard / (mean * math.sqrt(count))) ** 2 + (u_reference / reference) ** 2))
        recoveries.append(recovery)
    assert result["mean_recovery"] == pytest.approx(sum(recoveries) / 3)
    assert result["u_recovery"] == pytest.approx(math.sqrt(sum(variances)) / 3)
    assert result["mean_recovery"] == pytest.approx(1.0079006591337099, rel=1e-9)
    assert result["u_recovery"] == pytest.approx(0.037053560676501986, rel=1e-9)


def test_monte_carlo_matches_linear_normal_model_within_sampling_tolerance():
    result = evaluate_bottom_up(
        {
            "expression": "x1 * x2",
            "inputs": [
                {"name": "x1", "estimate": 10, "unit": "1", "kind": "B", "distribution": "normal", "u_mode": "standard", "u": 0.1, "source": "s"},
                {"name": "x2", "estimate": 2, "unit": "1", "kind": "B", "distribution": "normal", "u_mode": "standard", "u": 0.02, "source": "s"},
            ],
            "coverage": {"mode": "k", "k": 2},
            "monte_carlo": {"enabled": True, "seed": 7, "n": 80000, "p": 0.95, "interval": "symmetric"},
        }
    )
    analytical = math.sqrt((2 * 0.1) ** 2 + (10 * 0.02) ** 2)
    monte = result["monte_carlo"]
    assert monte["seed"] == 7
    assert monte["n"] == 80000
    assert monte["sd"] == pytest.approx(analytical, rel=0.015)
    assert monte["mean"] == pytest.approx(20, abs=0.01)
    assert monte["interval"] == "probabilistically_symmetric"
    assert "adaptive" in result["trace"] or "固定样本数" in result["trace"]


def test_coverage_interval_follows_jcgm_101_indexes():
    low, high = coverage_interval(list(range(1, 101)), 0.95, "symmetric")
    # M=100, pM=95, q=95, (M-q)/2=2.5, r=integer part of 6/2=3; y(3)=3, y(98)=98
    assert (low, high) == (3, 98)
    assert numerical_tolerance(0.00035, 2) == pytest.approx(0.000005)
    assert numerical_tolerance(2, 1) == pytest.approx(0.5)


def test_regression_literals_wls_and_zero_x_weight():
    ordinary = fit_line(
        {"weight_mode": "ols", "rows": [{"x": 1, "y": 2.1}, {"x": 2, "y": 3.9}, {"x": 3, "y": 6.2}, {"x": 4, "y": 7.8}]}
    )
    assert ordinary["slope"] == pytest.approx(1.94)
    assert ordinary["intercept"] == pytest.approx(0.15)
    assert ordinary["covariance"]["slope"] == pytest.approx(0.041 / 5)
    weighted = fit_line(
        {
            "weight_mode": "wls_absolute",
            "rows": [
                {"x": 1, "y": 2, "sigma": 1},
                {"x": 2, "y": 4, "sigma": 1},
                {"x": 3, "y": 7, "sigma": 2},
            ],
        }
    )
    assert weighted["slope"] == pytest.approx(7 / 3)
    assert weighted["intercept"] == pytest.approx(-4 / 9)
    assert weighted["covariance"]["slope"] == pytest.approx(1)
    assert weighted["absolute_variance_weights"] is True
    with pytest.raises(LabError, match="x=0"):
        fit_line({"weight_mode": "wls_inv_x", "rows": [{"x": 0, "y": 1}, {"x": 1, "y": 2}, {"x": 2, "y": 3}]})
    exact = fit_line({"weight_mode": "ols", "rows": [{"x": 0, "y": 1}, {"x": 1, "y": 3}, {"x": 2, "y": 5}], "inverse": {"y": 5}})
    assert exact["inverse"]["x"] == pytest.approx(2)
    assert exact["inverse"]["u"] == pytest.approx(0)


def test_lack_of_fit_does_not_divide_by_zero_pure_error():
    result = fit_line({"weight_mode": "ols", "rows": [{"x": 0, "y": 0}, {"x": 0, "y": 0}, {"x": 1, "y": 1}, {"x": 1, "y": 1}, {"x": 2, "y": 4}, {"x": 2, "y": 4}]})
    assert result["lack_of_fit"]["applicable"] is False
    assert "无定义" in result["lack_of_fit"]["reason"]


def test_precision_unbalanced_negative_rsd_and_crossed_design():
    result = analyze_precision(
        {
            "design": "one_way",
            "rows": [
                {"value": 1, "factor1": "A"},
                {"value": 2, "factor1": "A"},
                {"value": 3, "factor1": "B"},
                {"value": 4, "factor1": "B"},
                {"value": 5, "factor1": "B"},
            ],
        }
    )
    assert result["repeatability_variance"] == pytest.approx(5 / 6)
    assert result["between_variance_raw"] == pytest.approx(25 / 9)
    negative = analyze_precision(
        {"design": "one_way", "rows": [{"value": 0, "factor1": "A"}, {"value": 2, "factor1": "A"}, {"value": 0, "factor1": "B"}, {"value": 2, "factor1": "B"}]}
    )
    assert negative["between_variance_raw"] < 0
    assert negative["between_variance_reported"] == 0
    with pytest.raises(LabError, match="均值"):
        analyze_precision(
            {"design": "one_way", "include_rsd": True, "rows": [{"value": -1, "factor1": "A"}, {"value": 1, "factor1": "A"}, {"value": -1, "factor1": "B"}, {"value": 1, "factor1": "B"}]}
        )
    with pytest.raises(LabError, match="单因素"):
        analyze_precision(
            {
                "design": "one_way",
                "rows": [{"value": 1, "factor1": "A", "factor2": "X"}, {"value": 2, "factor1": "A", "factor2": "Y"}, {"value": 3, "factor1": "B", "factor2": "X"}],
            }
        )
    with pytest.raises(LabError, match="不平衡"):
        analyze_precision(
            {
                "design": "two_way_balanced",
                "rows": [
                    {"value": 1, "factor1": "A", "factor2": "X"},
                    {"value": 2, "factor1": "A", "factor2": "X"},
                    {"value": 3, "factor1": "B", "factor2": "Y"},
                    {"value": 4, "factor1": "B", "factor2": "Y"},
                ],
            }
        )


def test_crm_and_spike_are_distinct():
    crm = crm_bias(
        {
            "replicates": [10.1, 9.9, 10.2, 9.8, 10.0],
            "reference": 9.8,
            "certificate_uncertainty_applicable": True,
            "certificate_expanded": 0.2,
            "certificate_k": 2,
        }
    )
    assert crm["bias"] == pytest.approx(0.2)
    assert crm["u_bias"] == pytest.approx(math.sqrt(0.015))
    refused = crm_bias({"replicates": [10, 10], "reference": 9, "certificate_uncertainty_applicable": False})
    assert refused["u_bias"] is None
    spike = spike_recovery({"design": "replicates", "found": [11, 12, 10], "added": 10, "blank": 1})
    assert spike["recoveries"] == pytest.approx([1.0, 1.1, 0.9])
    assert spike["model_id"] != crm["model_id"]
    with pytest.raises(LabError, match="成对"):
        spike_recovery({"design": "paired_native", "before": [5, 5], "after": [8], "added": 3})


def test_lod_conditions_and_no_invented_pass():
    result = lod_loq(
        {
            "method": "blank_sd",
            "scope": "method",
            "values": [1, 2, 3],
            "k_lod": 3,
            "k_loq": 10,
            "source": "测试用出处，不是软件默认法定倍数",
            "blank_corrected": True,
            "n_averaged": 1,
            "n_blank": 1,
            "unit": "mg/kg",
        }
    )
    # values 1,2,3 have s0=1; blank-corrected n=nb=1 gives s'=sqrt(2)
    assert result["s0"] == pytest.approx(1)
    assert result["lod"] == pytest.approx(3 * math.sqrt(2))
    assert result["verified"] is False
    with pytest.raises(LabError, match="出处"):
        lod_loq({"method": "blank_sd", "scope": "method", "values": [1, 2, 3], "k_lod": 3, "k_loq": 10, "source": "", "unit": "mg/kg"})
    calibration = lod_loq(
        {
            "method": "calibration",
            "scope": "instrument",
            "k_lod": 3.3,
            "k_loq": 10,
            "source": "用户确认的 ICH 写法",
            "slope": 1.5,
            "residual_sd": 0.02,
            "residual_domain": "signal",
            "unit": "mg/L",
            "n": 6,
            "df": 4,
        }
    )
    assert calibration["lod"] == pytest.approx(3.3 * 0.02 / 1.5)
    assert calibration["scope"] == "仪器检出限"
    summary = summarize({"characteristics": [{"name": "回收率", "result": 0.98, "unit": "1"}], "working_range": {}})
    assert summary["characteristics"][0]["status"] == "未评价"


def test_expression_rejects_code_and_domain_errors():
    with pytest.raises(LabError):
        compile_expression("__import__('os').system('echo')")
    with pytest.raises(LabError, match="除以零"):
        compile_expression("1/x").evaluate({"x": 0})


def test_import_failure_chinese_path_and_original_bytes(tmp_path):
    folder = tmp_path / "实验 数据"
    folder.mkdir()
    target = folder / "坏表.csv"
    shutil.copyfile(examples_dir() / "bad_calibration.csv", target)
    table = import_table(target)
    before = target.read_bytes()
    with pytest.raises(LabError) as caught:
        fit_line({"rows": table["rows"], "weight_mode": "ols"})
    assert caught.value.row == 3
    assert caught.value.column == "y"
    assert target.read_bytes() == before
    good = import_table(examples_dir() / "calibration.csv")
    assert len(good["rows"]) == 4


def test_single_observation_is_not_replaced_by_the_mean():
    with pytest.raises(LabError, match="单次"):
        evaluate_bottom_up(
            {
                "expression": "x",
                "inputs": [{"name": "x", "kind": "A", "role": "single", "unit": "mg/L", "raw": [1, 2, 3], "source": "s"}],
                "coverage": {"mode": "k", "k": 2},
            }
        )
