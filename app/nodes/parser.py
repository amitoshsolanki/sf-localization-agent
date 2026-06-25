import json
import re
from typing import Any

from sqlalchemy import select

from app.db.models import GlossaryTerm
from app.db.session import AsyncSessionLocal
from app.state import AgentState, TranslationSegment

MERGE_FIELD_RE = re.compile(r"\{![^}]+\}")

CHAR_LIMITS: dict[str, int] = {
    "CustomLabel": 1000,
    "CustomField": 255,
    "CustomTab": 40,
    "ValidationRule": 255,
    "QuickAction": 765,
    "WebLink": 1000,
    "Flow": 255,
    "ReportType": 255,
    "CustomApplication": 255,
    "GlobalPicklistValue": 255,
    "RecordType": 255,
    "Layout": 80,
}
_DEFAULT_CHAR_LIMIT = 255

_SECTION_SEPARATOR_RE = re.compile(r"^-{5,}")
_LANGUAGE_CODE_RE = re.compile(r"^Language\s+code:\s*(\S+)", re.IGNORECASE)
_LABEL_HEADERS = {"label", "source", "value", "label/value"}
_TRANSLATION_HEADERS = {"translation", "translated value", "translated"}
_KEY_HEADERS = {"key", "fullname", "full name", "name", "setup component"}


def _is_section_separator(line: str) -> bool:
    return bool(_SECTION_SEPARATOR_RE.match(line.strip()))


def _parse_column_header(line: str) -> list[str]:
    """Extract column names from a #-prefixed header line like '# KEY\\tLABEL\\t...'."""
    text = line.lstrip("#").strip()
    return [c.strip().lower() for c in text.split("\t") if c.strip()]


def _detect_column(headers_lower: list[str], candidates: set[str]) -> int:
    for i, h in enumerate(headers_lower):
        if h in candidates:
            return i
    return -1


def _char_limit_for(component_type: str) -> int:
    return CHAR_LIMITS.get(component_type, _DEFAULT_CHAR_LIMIT)


def _error_result(errors: list[str], msg: str) -> dict[str, Any]:
    return {
        "errors": errors + [msg],
        "segments": [],
        "stf_lines": [],
        "translation_col": -1,
        "glossary_context": "[]",
    }


async def parser_node(state: AgentState) -> dict[str, Any]:
    file_path = state["input_file_path"]
    target_lang = state.get("target_language", "")
    errors: list[str] = list(state.get("errors", []))

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            raw_lines = f.read().splitlines()
    except Exception as exc:
        return _error_result(errors, f"File read error: {exc}")

    stf_lines: list[str] = list(raw_lines)

    translation_col = -1
    key_col = -1
    label_col = -1
    detected_language = ""
    section_header_pending = False
    in_data = False
    segments: list[TranslationSegment] = []
    seen_ids: set[str] = set()

    for line_idx, line in enumerate(stf_lines):
        stripped = line.strip()

        if not detected_language:
            m = _LANGUAGE_CODE_RE.match(stripped)
            if m:
                detected_language = m.group(1)

        if _is_section_separator(stripped):
            section_header_pending = True
            in_data = False
            continue

        if section_header_pending and stripped.startswith("#") and "\t" in line:
            headers = _parse_column_header(line)
            key_col = _detect_column(headers, _KEY_HEADERS)
            label_col = _detect_column(headers, _LABEL_HEADERS)
            t_col = _detect_column(headers, _TRANSLATION_HEADERS)
            if t_col != -1:
                translation_col = t_col
            elif translation_col == -1:
                translation_col = len(headers)
            section_header_pending = False
            in_data = True
            continue

        if section_header_pending and not stripped:
            continue

        if not in_data:
            continue

        if not stripped or stripped.startswith("#"):
            continue

        cols = line.split("\t")

        if key_col == -1 or label_col == -1:
            continue

        key_val = cols[key_col].strip() if key_col < len(cols) else ""
        source_text = cols[label_col].strip() if label_col < len(cols) else ""
        if not source_text:
            continue

        component_type = key_val.split(".")[0] if key_val else ""
        component_key = key_val

        seg_id = component_key if component_key else f"seg_{line_idx}"
        if seg_id in seen_ids:
            seg_id = f"{seg_id}_{line_idx}"
        seen_ids.add(seg_id)

        segments.append({
            "id": seg_id,
            "source_text": source_text,
            "component_type": component_type,
            "component_key": component_key,
            "merge_fields": MERGE_FIELD_RE.findall(source_text),
            "char_limit": _char_limit_for(component_type),
            "line_index": line_idx,
        })

    if not target_lang and detected_language:
        target_lang = detected_language

    if not target_lang:
        return _error_result(errors, "No target language: not found in file metadata and not provided via --target-language")

    if not segments:
        return _error_result(errors, "No translatable segments found in .stf file")

    if translation_col == -1:
        translation_col = 2

    glossary_context = await _fetch_relevant_glossary(target_lang, segments)

    return {
        "segments": segments,
        "stf_lines": stf_lines,
        "translation_col": translation_col,
        "target_language": target_lang,
        "glossary_context": glossary_context,
        "errors": errors,
    }


async def _fetch_relevant_glossary(
    target_language: str, segments: list[TranslationSegment]
) -> str:
    if not segments:
        return "[]"

    source_texts_lower = [s["source_text"].lower() for s in segments]

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(GlossaryTerm).where(
                GlossaryTerm.target_language == target_language,
                GlossaryTerm.approved == True,
            )
        )
        all_terms = result.scalars().all()

    relevant = [
        t for t in all_terms
        if any(t.source_term.lower() in st for st in source_texts_lower)
    ]

    return json.dumps(
        [
            {"source": t.source_term, "translation": t.approved_translation, "context": t.context}
            for t in relevant
        ],
        ensure_ascii=False,
        indent=2,
    )
