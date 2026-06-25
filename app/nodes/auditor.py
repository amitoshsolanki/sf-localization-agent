import json
from typing import Any

from app.state import AgentState, GlossaryViolation


async def auditor_node(state: AgentState) -> dict[str, Any]:
    glossary_context = state.get("glossary_context", "[]")
    glossary = json.loads(glossary_context)

    segments = {s["id"]: s for s in state["segments"]}
    translated = {t["id"]: t["translated_text"] for t in state.get("translated_segments", [])}

    violations: list[GlossaryViolation] = []

    for term in glossary:
        source_lower = term["source"].lower()
        approved_lower = term["translation"].lower()

        for seg_id, segment in segments.items():
            if source_lower not in segment["source_text"].lower():
                continue
            translated_text = translated.get(seg_id, "")
            if approved_lower not in translated_text.lower():
                violations.append({
                    "segment_id": seg_id,
                    "source_term": term["source"],
                    "approved_translation": term["translation"],
                    "found_in_translation": translated_text,
                })

    return {"glossary_violations": violations}
