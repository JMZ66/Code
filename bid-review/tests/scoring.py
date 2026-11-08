"""Score a review against the labelled synthetic package."""

from __future__ import annotations


def _triggered(negative: dict, findings: list) -> bool:
    rules = set(negative.get("rules") or [])
    rule_id = negative.get("rule_id")
    for finding in findings:
        if rules and finding.rule_id not in rules:
            continue
        if rule_id and finding.rule_id != rule_id:
            continue
        subject = (finding.details or {}).get("subject") or ""
        if "subject" in negative and subject != negative["subject"]:
            continue
        if "subject_contains" in negative and negative["subject_contains"] not in subject:
            continue
        if "value_exact" in negative:
            values = (finding.details or {}).get("values") or []
            if negative["value_exact"] not in values:
                continue
        if "text" in negative and negative["text"] not in finding.blob():
            continue
        return True
    return False


def score(findings: list, expected: list[dict], negatives: list[dict]) -> dict:
    by_key: dict[str, list] = {}
    for finding in findings:
        by_key.setdefault(finding.key, []).append(finding)
    missed: list[str] = []
    for item in expected:
        group = by_key.get(item["key"]) or []
        if not group:
            missed.append(item["key"])
            continue
        finding = group[0]
        ok = finding.category == item["category"]
        blob = "\n".join(one.blob() for one in group)
        values = []
        for one in group:
            values.extend((one.details or {}).get("values") or [])
        for needle in item.get("contains") or []:
            if needle not in blob and needle not in " ".join(str(value) for value in values):
                ok = False
        if "pdf_page" in item and item["pdf_page"] not in set().union(*(set(one.pdf_pages) for one in group)):
            ok = False
        if "values" in item and not set(item["values"]).issubset(set(values)):
            ok = False
        if not ok:
            missed.append(item["key"])
    expected_keys = {item["key"] for item in expected}
    extras = sorted({finding.key for finding in findings if finding.key not in expected_keys})
    triggered = [item["id"] for item in negatives if _triggered(item, findings)]
    positives = len(expected)
    negative_count = len(negatives)
    miss_count = len(missed)
    false_count = len(triggered)
    return {
        "positives": positives,
        "missed": missed,
        "miss_count": miss_count,
        "miss_rate": miss_count / positives if positives else 0.0,
        "negatives": negative_count,
        "false_positives": triggered,
        "false_positive_count": false_count,
        "false_positive_rate": false_count / negative_count if negative_count else 0.0,
        "extras": extras,
        "extra_count": len(extras),
        "finding_count": len(findings),
    }
