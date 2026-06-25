import asyncio
import json
import os
from typing import Any

from pydantic import BaseModel

from app.llm import get_chat_model
from app.state import AgentState, TranslatedSegment
from app.utils.prompts import TRANSLATE_SYSTEM, build_translate_prompt
_BATCH_SIZE = int(os.getenv("TRANSLATE_BATCH_SIZE", "50"))


class _TranslationItem(BaseModel):
    id: str
    translated_text: str


class _TranslationResponse(BaseModel):
    translations: list[_TranslationItem]


def _get_llm() -> Any:
    return get_chat_model("translator").with_structured_output(_TranslationResponse, method="json_mode")


def _build_violations_feedback(violations: list[dict], target_ids: set[str]) -> str:
    relevant = [v for v in violations if v["segment_id"] in target_ids]
    if not relevant:
        return ""
    lines = []
    for v in relevant:
        lines.append(
            f'  - Segment "{v["segment_id"]}": for "{v["source_term"]}", '
            f'use "{v["approved_translation"]}" (you wrote: "{v["found_in_translation"]}")'
        )
    return "\n".join(lines)


def _build_validation_feedback(issues: list[dict], target_ids: set[str]) -> str:
    relevant = [i for i in issues if i["segment_id"] in target_ids]
    if not relevant:
        return ""
    lines = []
    for issue in relevant:
        lines.append(f'  - [{issue["issue_type"]}] {issue["segment_id"]}: {issue["details"]}')
    return "\n".join(lines)


async def _translate_batch(
    batch: list[dict],
    target_lang: str,
    glossary_json: str,
    violations_feedback: str,
    validation_feedback: str,
    structured_llm: Any,
) -> list[TranslatedSegment]:
    segments_json = json.dumps(
        [
            {
                "id": s["id"],
                "source_text": s["source_text"],
                "char_limit": s["char_limit"],
                "merge_fields": s["merge_fields"],
            }
            for s in batch
        ],
        ensure_ascii=False,
        indent=2,
    )

    user_prompt = build_translate_prompt(
        target_language=target_lang,
        glossary_json=glossary_json,
        segments_json=segments_json,
        violations_feedback=violations_feedback,
        validation_feedback=validation_feedback,
    )

    response: _TranslationResponse = await structured_llm.ainvoke([
        ("system", TRANSLATE_SYSTEM),
        ("human", user_prompt),
    ])

    return [
        {"id": item.id, "translated_text": item.translated_text}
        for item in response.translations
    ]


async def translator_node(state: AgentState) -> dict[str, Any]:
    target_lang = state["target_language"]
    all_segments = state["segments"]
    glossary_json = state.get("glossary_context", "[]")
    failed_ids = set(state.get("failed_segment_ids", []))
    violations = state.get("glossary_violations", [])
    validation_issues = state.get("validation_issues", [])

    existing = {t["id"]: t for t in state.get("translated_segments", [])}

    if failed_ids:
        segments_to_translate = [s for s in all_segments if s["id"] in failed_ids]
    else:
        segments_to_translate = list(all_segments)

    if not segments_to_translate:
        return {"translated_segments": list(existing.values()), "loop_count": state.get("loop_count", 0) + 1}

    target_ids = {s["id"] for s in segments_to_translate}
    violations_feedback = _build_violations_feedback(violations, target_ids) if failed_ids else ""
    validation_feedback = _build_validation_feedback(validation_issues, target_ids) if failed_ids else ""

    structured_llm = _get_llm()

    batches = [
        segments_to_translate[i : i + _BATCH_SIZE]
        for i in range(0, len(segments_to_translate), _BATCH_SIZE)
    ]

    tasks = [
        _translate_batch(
            batch, target_lang, glossary_json,
            violations_feedback, validation_feedback, structured_llm,
        )
        for batch in batches
    ]
    batch_results = await asyncio.gather(*tasks)

    for result in batch_results:
        for item in result:
            existing[item["id"]] = item

    return {
        "translated_segments": list(existing.values()),
        "loop_count": state.get("loop_count", 0) + 1,
    }
