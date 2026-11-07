"""Safe measurement-model expressions.

The user string is parsed with the Python AST and then walked by this module.
It is never passed to eval or exec. Only arithmetic and a fixed function list
are accepted, so a spreadsheet formula cannot become arbitrary code.
"""

from __future__ import annotations

import ast
import math

from labuv.errors import LabError

_MAX_NODES = 200
_FUNCS = {"sqrt", "exp", "log", "ln", "log10", "abs", "sin", "cos", "tan"}
_CONST = {"pi": math.pi, "e": math.e}


class Dual:
    __slots__ = ("v", "g")

    def __init__(self, value: float, gradient: dict[str, float] | None = None):
        self.v = float(value)
        self.g = dict(gradient or {})
        if not math.isfinite(self.v) or any(not math.isfinite(x) for x in self.g.values()):
            raise LabError("表达式出现非有限结果（NaN 或无穷大），已停止计算。", code="nonfinite")


def compile_expression(source: str):
    text = (source or "").strip()
    if not text:
        raise LabError("测量模型表达式为空。", code="empty_expression")
    if len(text) > 2000:
        raise LabError("表达式过长。", code="expression_length")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise LabError(f"表达式语法错误：{exc.msg}", code="syntax") from exc
    if sum(1 for _ in ast.walk(tree)) > _MAX_NODES:
        raise LabError("表达式过于复杂。", code="expression_length")
    names = []
    seen = set()
    literals = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id not in _CONST and node.id not in _FUNCS:
            if node.id not in seen:
                seen.add(node.id)
                names.append(node.id)
        elif isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            if float(node.value) not in (0.0, 1.0, -1.0):
                literals.append(float(node.value))
        elif isinstance(node, (ast.Attribute, ast.Subscript, ast.Lambda, ast.ListComp, ast.Dict,
                               ast.List, ast.Tuple, ast.Set, ast.Compare, ast.BoolOp, ast.IfExp,
                               ast.JoinedStr, ast.NamedExpr)):
            raise LabError("表达式只允许算术运算和列出的函数，不能调用代码或访问属性。", code="forbidden_syntax")
    return CompiledExpression(tree, names, literals, text)


class CompiledExpression:
    def __init__(self, tree, names, literals, source: str):
        self.tree = tree
        self.names = names
        self.literals = literals
        self.source = source

    def evaluate(self, values: dict[str, float]) -> float:
        return self._eval(self.tree.body, values, dual=False).v

    def value_and_gradient(self, values: dict[str, float]) -> tuple[float, dict[str, float]]:
        result = self._eval(self.tree.body, values, dual=True)
        gradient = {name: result.g.get(name, 0.0) for name in self.names}
        return result.v, gradient

    def _eval(self, node, values, dual: bool):
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise LabError("表达式含有非数字常量。", code="forbidden_syntax")
            return Dual(float(node.value), {})
        if isinstance(node, ast.Name):
            if node.id in _CONST:
                return Dual(_CONST[node.id], {})
            if node.id not in values:
                raise LabError(f"表达式中的量“{node.id}”没有输入值。", code="missing_input")
            gradient = {node.id: 1.0} if dual else {}
            return Dual(float(values[node.id]), gradient)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            inner = self._eval(node.operand, values, dual)
            if isinstance(node.op, ast.UAdd):
                return inner
            return Dual(-inner.v, {k: -g for k, g in inner.g.items()})
        if isinstance(node, ast.BinOp):
            left = self._eval(node.left, values, dual)
            right = self._eval(node.right, values, dual)
            return _binop(node.op, left, right)
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
                raise LabError("只允许函数 sqrt、exp、log、ln、log10、abs、sin、cos、tan。", code="forbidden_syntax")
            if node.keywords or len(node.args) != 1:
                raise LabError(f"函数 {node.func.id} 只接受一个参数。", code="forbidden_syntax")
            arg = self._eval(node.args[0], values, dual)
            return _apply(node.func.id, arg)
        raise LabError("表达式含有不支持的语法。", code="forbidden_syntax")


def _binop(op, left: Dual, right: Dual) -> Dual:
    keys = set(left.g) | set(right.g)
    if isinstance(op, ast.Add):
        return Dual(left.v + right.v, {k: left.g.get(k, 0.0) + right.g.get(k, 0.0) for k in keys})
    if isinstance(op, ast.Sub):
        return Dual(left.v - right.v, {k: left.g.get(k, 0.0) - right.g.get(k, 0.0) for k in keys})
    if isinstance(op, ast.Mult):
        grad = {k: left.g.get(k, 0.0) * right.v + left.v * right.g.get(k, 0.0) for k in keys}
        return Dual(left.v * right.v, grad)
    if isinstance(op, ast.Div):
        if right.v == 0.0:
            raise LabError("表达式出现除以零。", code="division_by_zero")
        grad = {
            k: (left.g.get(k, 0.0) * right.v - left.v * right.g.get(k, 0.0)) / (right.v ** 2)
            for k in keys
        }
        return Dual(left.v / right.v, grad)
    if isinstance(op, ast.Pow):
        return _power(left, right)
    raise LabError("只允许 + - * / 和乘方。", code="forbidden_syntax")


def _power(base: Dual, exp: Dual) -> Dual:
    integer_exp = not exp.g and float(exp.v).is_integer()
    if base.v < 0.0:
        if not integer_exp:
            raise LabError("负数不能做非整数次乘方。", code="domain")
        power = int(exp.v)
        value = base.v ** power
        if power == 0:
            factor = 0.0
        else:
            factor = power * (base.v ** (power - 1))
        return Dual(value, {k: factor * g for k, g in base.g.items()})
    if base.v == 0.0:
        if integer_exp and exp.v > 0:
            power = int(exp.v)
            value = 0.0 ** power
            factor = 0.0 if power > 1 else (1.0 if power == 1 else math.nan)
            if power == 0:
                raise LabError("0 的 0 次方没有定义。", code="domain")
            return Dual(value, {k: factor * g for k, g in base.g.items()})
        raise LabError("0 不能做非正数次乘方或实数对数。", code="domain")
    logged = _apply("ln", base)
    return _apply("exp", _binop(ast.Mult(), exp, logged))


def _apply(name: str, arg: Dual) -> Dual:
    x = arg.v
    if name == "sqrt":
        if x < 0.0:
            raise LabError("平方根的自变量不能为负。", code="domain")
        if x == 0.0:
            raise LabError("在 0 处平方根的灵敏系数无定义，请改写模型或不要把该点当作可微工作点。", code="domain")
        value = math.sqrt(x)
        factor = 0.5 / value
    elif name in ("log", "ln"):
        if x <= 0.0:
            raise LabError("对数的自变量必须为正。", code="domain")
        value = math.log(x)
        factor = 1.0 / x
    elif name == "log10":
        if x <= 0.0:
            raise LabError("对数的自变量必须为正。", code="domain")
        value = math.log10(x)
        factor = 1.0 / (x * math.log(10.0))
    elif name == "exp":
        value = math.exp(x)
        factor = value
    elif name == "abs":
        if x == 0.0:
            raise LabError("绝对值在 0 处不可导，灵敏系数无定义。", code="domain")
        value = abs(x)
        factor = 1.0 if x > 0.0 else -1.0
    elif name == "sin":
        value = math.sin(x)
        factor = math.cos(x)
    elif name == "cos":
        value = math.cos(x)
        factor = -math.sin(x)
    elif name == "tan":
        c = math.cos(x)
        if c == 0.0:
            raise LabError("正切在该点无定义。", code="domain")
        value = math.tan(x)
        factor = 1.0 / (c * c)
    else:
        raise LabError(f"未知函数 {name}。", code="forbidden_syntax")
    return Dual(value, {k: factor * g for k, g in arg.g.items()})


def second_derivative_diagnostic(compiled: CompiledExpression, values: dict[str, float]) -> dict:
    """Numerical Hessian, used only as a nonlinearity warning, not as uc.

    JCGM 100:2008 clause 5.1.2 says higher-order terms are required when
    nonlinearity is significant. The 2026 amendment text was not obtained, so
    this diagnostic is not presented as that amendment's formula.
    """
    names = compiled.names
    base = dict(values)
    _, gradient = compiled.value_and_gradient(base)
    hessian = {}
    for j, name_j in enumerate(names):
        step = 1e-6 * max(1.0, abs(base[name_j]))
        plus = dict(base)
        minus = dict(base)
        plus[name_j] = base[name_j] + step
        minus[name_j] = base[name_j] - step
        try:
            _, g_plus = compiled.value_and_gradient(plus)
            _, g_minus = compiled.value_and_gradient(minus)
        except LabError as exc:
            return {"available": False, "reason": str(exc), "shift": None}
        for name_i in names[j:]:
            hessian[(name_i, name_j)] = (g_plus[name_i] - g_minus[name_i]) / (2.0 * step)
            if name_i != name_j:
                hessian[(name_j, name_i)] = hessian[(name_i, name_j)]
    return {"available": True, "gradient": gradient, "hessian": hessian, "reason": ""}
