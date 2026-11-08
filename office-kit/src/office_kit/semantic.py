"""Pluggable inference hook. Nothing here calls a model or the network."""

from __future__ import annotations

from typing import Protocol

from office_kit.models import Document, Evidence, Finding


class SemanticProvider(Protocol):
    def infer(self, request: dict) -> list[dict]:
        """Return candidate findings. The engine relabels them as inference."""


class DisabledSemanticProvider:
    """Default provider. ``infer`` returns no findings and performs no I/O."""

    name = "disabled"

    def infer(self, request: dict) -> list[dict]:
        return []


def excerpts(documents: list[Document], limit: int = 30) -> list[dict]:
    rows = []
    for document in documents:
        if document.word is None:
            continue
        for paragraph in document.word.paragraphs:
            if not paragraph.text_accepted.strip():
                continue
            rows.append(
                {
                    "path": document.source.path,
                    "sha256": document.source.sha256,
                    "anchor": paragraph.anchor,
                    "quote": paragraph.text_accepted[:240],
                }
            )
            if len(rows) >= limit:
                return rows
    return rows


def normalize_inference(provider, documents: list[Document], report) -> None:
    if provider is None or isinstance(provider, DisabledSemanticProvider):
        return
    try:
        raw = provider.infer({"excerpts": excerpts(documents), "note": "这些摘录是源文。你的输出只能作为推断。"})
    except Exception as exc:
        report.warnings.append({"code": "semantic_failed", "message": f"推断接口失败，已忽略：{exc}"})
        return
    for item in raw or []:
        evidence_rows = item.get("evidence") or []
        if not evidence_rows:
            report.warnings.append({"code": "inference_dropped", "message": "一条推断没有证据位置，已丢弃。"})
            continue
        evidence = []
        for row in evidence_rows:
            anchor = row.get("anchor") or ""
            quote = row.get("quote") or ""
            if not anchor or not quote:
                evidence = []
                break
            evidence.append(
                Evidence(
                    source_path=row.get("source_path") or "",
                    sha256=row.get("sha256") or "",
                    anchor=anchor,
                    quote=quote[:240],
                    part=row.get("part") or anchor.split("#", 1)[0],
                )
            )
        if not evidence:
            report.warnings.append({"code": "inference_dropped", "message": "一条推断的证据缺少锚点或引文，已丢弃。"})
            continue
        message = str(item.get("message") or "")
        if not message.startswith("【推断】"):
            message = "【推断】" + message
        report.findings.append(
            Finding(
                id="",
                rule_id=str(item.get("rule_id") or "semantic.inference"),
                severity="info",
                origin="inference",
                category="需要人工判断",
                message=message,
                evidence=evidence,
                details={"provider": getattr(provider, "name", provider.__class__.__name__)},
            )
        )
