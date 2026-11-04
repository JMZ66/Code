from __future__ import annotations


def align_peak_tables(groups: list[list[dict]], rt_tol: float) -> list[dict]:
    """按保留时间把多张峰表对齐。每个样品在同一行最多出现一个峰。"""
    events = []
    for group_index, peaks in enumerate(groups):
        for peak in peaks:
            events.append((float(peak["rt"]), group_index, peak))
    events.sort(key=lambda item: item[0])
    clusters: list[dict] = []
    for rt, group_index, peak in events:
        if clusters and rt - clusters[-1]["rt_anchor"] <= rt_tol and group_index not in clusters[-1]["by_sample"]:
            clusters[-1]["by_sample"][group_index] = peak
        else:
            clusters.append({"rt_anchor": rt, "by_sample": {group_index: peak}})
    return clusters
