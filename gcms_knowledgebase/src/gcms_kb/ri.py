from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AlkanePoint:
    carbon_number: int
    rt: float
    name: str = ""


@dataclass(frozen=True)
class RiResult:
    ri: float
    extrapolated: bool
    carbon_low: int
    carbon_high: int


def retention_index(rt: float, points: list[AlkanePoint]) -> RiResult:
    """程序升温保留指数（van den Dool–Kratz）。

    相邻正构烷烃时：RI = 100 * (n + (t - t_n) / (t_{n+1} - t_n))。
    若两个校正点的碳数差不是 1，按碳数差线性缩放，避免漏掉一个烷烃时把刻度压缩。
    超出校正范围时用最近一段外推，并标记 extrapolated。
    """
    if len(points) < 2:
        raise ValueError("烷烃校正至少需要两个点")
    ordered = sorted(points, key=lambda item: (item.rt, item.carbon_number))
    for left, right in zip(ordered, ordered[1:]):
        if right.rt <= left.rt:
            raise ValueError("烷烃保留时间必须严格递增")
        if right.carbon_number <= left.carbon_number:
            raise ValueError("烷烃碳数必须随保留时间增加")
    rt = float(rt)
    if rt < ordered[0].rt:
        left, right = ordered[0], ordered[1]
        extrapolated = True
    elif rt > ordered[-1].rt:
        left, right = ordered[-2], ordered[-1]
        extrapolated = True
    else:
        left, right = ordered[0], ordered[1]
        extrapolated = False
        for candidate_left, candidate_right in zip(ordered, ordered[1:]):
            if candidate_left.rt <= rt <= candidate_right.rt:
                left, right = candidate_left, candidate_right
                break
    span = right.rt - left.rt
    fraction = (rt - left.rt) / span
    carbon_span = right.carbon_number - left.carbon_number
    ri = 100.0 * (left.carbon_number + carbon_span * fraction)
    return RiResult(
        ri=float(ri),
        extrapolated=extrapolated,
        carbon_low=int(left.carbon_number),
        carbon_high=int(right.carbon_number),
    )


def parse_alkane_csv(text: str) -> list[AlkanePoint]:
    """读取 UTF-8 CSV。表头：carbon_number,rt_min,name。name 可省略。"""
    lines = [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]
    if not lines:
        raise ValueError("校正文件是空的")
    header = [part.strip().lower() for part in lines[0].split(",")]
    start = 1 if "carbon_number" in header or "rt_min" in header else 0
    points: list[AlkanePoint] = []
    for line in lines[start:]:
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 2:
            raise ValueError(f"无法解析这一行：{line}")
        points.append(
            AlkanePoint(
                carbon_number=int(float(parts[0])),
                rt=float(parts[1]),
                name=parts[2] if len(parts) > 2 else "",
            )
        )
    if len(points) < 2:
        raise ValueError("至少需要两个烷烃点")
    return points
