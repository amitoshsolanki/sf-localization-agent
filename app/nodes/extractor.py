import json
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select

from app.db.models import GlossaryTerm
from app.db.session import AsyncSessionLocal
from app.llm import get_chat_model
from app.state import AgentState
from app.utils.prompts import GLOSSARY_EXTRACT_SYSTEM, build_glossary_extract_prompt


MAX_TERM_WORDS = 2


class _GlossaryEntry(BaseModel):
    source_term: str
    translated_term: str


class _GlossaryExtractionResponse(BaseModel):
    terms: list[_GlossaryEntry]


def _get_llm() -> Any:
    return get_chat_model("extractor").with_structured_output(_GlossaryExtractionResponse, method="json_mode")


async def extractor_node(state: AgentState) -> dict[str, Any]:
    if not state.get("output_stf"):
        return {"extracted_glossary_count": 0}

    translated = {t["id"]: t["translated_text"] for t in state.get("translated_segments", [])}
    segments = state["segments"]
    target_lang = state["target_language"]

    segment_data = [
        {
            "id": s["id"],
            "source_text": s["source_text"],
            "translated_text": translated[s["id"]],
        }
        for s in segments
        if s["id"] in translated
    ]

    if not segment_data:
        return {"extracted_glossary_count": 0}

    segments_json = json.dumps(segment_data, ensure_ascii=False, indent=2)
    user_prompt = build_glossary_extract_prompt(target_lang, segments_json)

    structured_llm = _get_llm()
    response: _GlossaryExtractionResponse = await structured_llm.ainvoke([
        ("system", GLOSSARY_EXTRACT_SYSTEM),
        ("human", user_prompt),
    ])

    count = 0
    async with AsyncSessionLocal() as session:
        for entry in response.terms:
            source = entry.source_term.strip()
            translated_term = entry.translated_term.strip()
            if not source or not translated_term:
                continue
            # Glossary terms must be single concepts; the source is the lookup key
            if len(source.split()) > MAX_TERM_WORDS:
                continue

            existing = await session.execute(
                select(GlossaryTerm).where(
                    GlossaryTerm.source_term == source,
                    GlossaryTerm.target_language == target_lang,
                    GlossaryTerm.approved == True,
                )
            )
            if existing.scalars().first():
                continue

            session.add(GlossaryTerm(
                source_term=source,
                target_language=target_lang,
                approved_translation=translated_term,
                context="auto-extracted",
                approved=False,
            ))
            count += 1

        await session.commit()

    return {"extracted_glossary_count": count}
