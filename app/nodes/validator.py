import re
from typing import Any, Optional

from app.state import AgentState, TranslationSegment, ValidationIssue

MERGE_FIELD_RE = re.compile(r"\{![^}]+\}")


async def validator_node(state: AgentState) -> dict[str, Any]:
    segments = {s["id"]: s for s in state["segments"]}
    translated = {t["id"]: t["translated_text"] for t in state.get("translated_segments", [])}
    issues: list[ValidationIssue] = []

    for seg_id, segment in segments.items():
        text = translated.get(seg_id)
        if text is None:
            issues.append({
                "segment_id": seg_id,
                "issue_type": "missing_translation",
                "details": "No translation returned for this segment",
            })
            continue

        for mf in segment["merge_fields"]:
            if mf not in text:
                issues.append({
                    "segment_id": seg_id,
                    "issue_type": "merge_field_altered",
                    "details": f"Merge field '{mf}' missing or altered in translation",
                })

        unexpected = set(MERGE_FIELD_RE.findall(text)) - set(segment["merge_fields"])
        if unexpected:
            issues.append({
                "segment_id": seg_id,
                "issue_type": "merge_field_altered",
                "details": f"Unexpected merge fields injected: {sorted(unexpected)}",
            })

        char_count = len(text)
        limit = segment["char_limit"]
        if char_count > limit:
            issues.append({
                "segment_id": seg_id,
                "issue_type": "char_limit_exceeded",
                "details": f"Length {char_count} exceeds limit {limit}",
            })

    failed_ids: set[str] = set()
    for v in state.get("glossary_violations", []):
        failed_ids.add(v["segment_id"])
    for issue in issues:
        failed_ids.add(issue["segment_id"])

    output_stf: Optional[str] = None
    if not failed_ids:
        output_stf = _reconstruct_stf(
            state["stf_lines"],
            state["translation_col"],
            state["segments"],
            translated,
        )

    return {
        "validation_issues": issues,
        "failed_segment_ids": list(failed_ids),
        "output_stf": output_stf,
    }


def _reconstruct_stf(
    stf_lines: list[str],
    translation_col: int,
    segments: list[TranslationSegment],
    translated: dict[str, str],
) -> str:
    seg_by_line = {s["line_index"]: s["id"] for s in segments}

    output: list[str] = []
    for i, line in enumerate(stf_lines):
        seg_id = seg_by_line.get(i)
        if seg_id and seg_id in translated:
            cols = line.split("\t")
            while len(cols) <= translation_col:
                cols.append("")
            cols[translation_col] = translated[seg_id]
            output.append("\t".join(cols))
        else:
            output.append(line)

    return "\n".join(output) + "\n"
