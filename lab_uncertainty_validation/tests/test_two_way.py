from labuv.precision import analyze_precision


def test_balanced_two_way_with_no_dispersion_is_zero():
    rows = []
    for factor_a in ("甲", "乙"):
        for factor_b in ("早", "晚"):
            rows.append({"value": 5, "factor1": factor_a, "factor2": factor_b})
            rows.append({"value": 5, "factor1": factor_a, "factor2": factor_b})
    result = analyze_precision({"design": "two_way_balanced", "rows": rows})
    assert result["repeatability_sd"] == 0
    assert result["intermediate_sd"] == 0
