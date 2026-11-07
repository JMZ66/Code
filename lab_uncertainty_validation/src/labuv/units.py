"""Unit parsing and coherent evaluation.

Numbers entered by the user stay in the unit written next to them. Percent is
the one declared scaling: 99.5 % is calculated as 0.995 and the raw 99.5 is
kept. Offset units such as degree Celsius are refused rather than guessed.
"""

from __future__ import annotations

from pint import UnitRegistry

from labuv.errors import LabError
from labuv.expression import compile_expression

ureg = UnitRegistry(autoconvert_offset_to_baseunit=True)

_ALIASES = {
    "无量纲": "dimensionless",
    "1": "dimensionless",
    "—": "dimensionless",
    "-": "dimensionless",
    "%": "percent",
    "％": "percent",
    "百分比": "percent",
    "毫克每升": "mg/L",
    "微克每升": "ug/L",
    "毫克每千克": "mg/kg",
    "毫克每平方分米": "mg/dm**2",
    "平方分米": "dm**2",
    "毫升": "mL",
    "升": "L",
    "克": "g",
    "毫克": "mg",
    "微克": "ug",
    "千克": "kg",
}


def parse_unit(text: str):
    raw = "" if text is None else str(text).strip()
    if raw == "":
        raise LabError("单位为空。单位不能只作为标签省略。", code="unit")
    token = _ALIASES.get(raw, raw)
    try:
        unit = ureg(token).units
    except Exception as exc:
        raise LabError(f"无法识别单位“{raw}”。", code="unit") from exc
    probe = ureg.Quantity(1, unit)
    if not probe._is_multiplicative:
        raise LabError(
            f"单位“{raw}”带有零点偏移（例如 °C）。不确定度传播不自动处理这类单位，请改用 K 或其他比例单位。",
            code="offset_unit",
        )
    return unit


def is_percent(unit) -> bool:
    return unit == ureg.percent


def calculation_magnitude(estimate: float, unit) -> tuple[float, object]:
    """Return the magnitude used in the quantity equation and its unit.

    99.5 % becomes 0.995 dimensionless. Other units keep the entered number.
    """
    if is_percent(unit):
        return estimate / 100.0, ureg.dimensionless
    return float(estimate), unit


def to_base_scale(unit) -> float:
    return float(ureg.Quantity(1, unit).to_base_units().magnitude)


def unit_text(unit) -> str:
    try:
        return f"{unit:~P}"
    except Exception:
        return str(unit)


def evaluate_quantity(source: str, magnitudes: dict[str, float], units: dict):
    """Evaluate the expression with pint quantities. Returns a Quantity."""
    compiled = compile_expression(source)
    quantities = {}
    for name in compiled.names:
        quantities[name] = ureg.Quantity(magnitudes[name], units[name])
    try:
        return _quantity_eval(compiled.tree.body, quantities)
    except LabError:
        raise
    except Exception as exc:
        raise LabError(f"单位不一致或表达式不能按这些单位计算：{exc}", code="unit") from exc


def _quantity_eval(node, quantities):
    import ast
    import math

    if isinstance(node, ast.Constant):
        return ureg.Quantity(float(node.value), ureg.dimensionless)
    if isinstance(node, ast.Name):
        if node.id == "pi":
            return ureg.Quantity(math.pi, ureg.dimensionless)
        if node.id == "e":
            return ureg.Quantity(math.e, ureg.dimensionless)
        return quantities[node.id]
    if isinstance(node, ast.UnaryOp):
        value = _quantity_eval(node.operand, quantities)
        if isinstance(node.op, ast.USub):
            return -value
        return value
    if isinstance(node, ast.BinOp):
        left = _quantity_eval(node.left, quantities)
        right = _quantity_eval(node.right, quantities)
        if isinstance(node.op, ast.Add):
            _require_compatible(left, right, "相加")
            return left + right
        if isinstance(node.op, ast.Sub):
            _require_compatible(left, right, "相减")
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            if right.magnitude == 0:
                raise LabError("表达式出现除以零。", code="division_by_zero")
            return left / right
        if isinstance(node.op, ast.Pow):
            if right.dimensionality != {}:
                raise LabError("乘方的指数必须是无量纲数。", code="unit")
            return left ** right.magnitude
        raise LabError("不支持的运算。", code="forbidden_syntax")
    if isinstance(node, ast.Call):
        arg = _quantity_eval(node.args[0], quantities)
        name = node.func.id
        if name in ("sin", "cos", "tan", "exp", "log", "ln", "log10"):
            if arg.dimensionality != {}:
                raise LabError(f"{name} 的自变量必须无量纲。", code="unit")
            func = {"ln": math.log, "log": math.log}.get(name, getattr(math, name))
            return ureg.Quantity(func(arg.magnitude), ureg.dimensionless)
        if name == "sqrt":
            return arg ** 0.5
        if name == "abs":
            return abs(arg)
    raise LabError("表达式含有不支持的语法。", code="forbidden_syntax")


def _require_compatible(left, right, action: str):
    if not left.is_compatible_with(right):
        raise LabError(
            f"不能把单位“{unit_text(left.units)}”与“{unit_text(right.units)}”{action}。",
            code="unit",
        )


def compatible(actual, expected_text: str | None) -> bool:
    if not expected_text:
        return True
    expected = parse_unit(expected_text)
    return ureg.Quantity(1, actual).is_compatible_with(ureg.Quantity(1, expected))


def conversion_factor(actual_unit, report_unit) -> float:
    return float(ureg.Quantity(1, actual_unit).to(report_unit).magnitude)


def assert_same_number(left: float, right: float, what: str):
    scale = max(1.0, abs(left), abs(right))
    if not (math_isfinite(left) and math_isfinite(right)) or abs(left - right) > 1e-8 * scale:
        raise LabError(f"{what}不一致（{left} 与 {right}），已拒绝给出结果。", code="unit")


def math_isfinite(value: float) -> bool:
    import math
    return math.isfinite(value)


def base_magnitudes(magnitudes: dict[str, float], units: dict) -> tuple[dict[str, float], dict[str, float]]:
    bases = {}
    scales = {}
    for name, magnitude in magnitudes.items():
        scale = to_base_scale(units[name])
        scales[name] = scale
        bases[name] = magnitude * scale
    return bases, scales
