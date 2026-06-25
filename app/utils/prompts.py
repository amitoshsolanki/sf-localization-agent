GLOSSARY_EXTRACT_SYSTEM = """\
You are a Salesforce localization glossary curator. Your job is to identify short, reusable \
technical terms from translated Salesforce UI segments that should be added to a translation glossary.

RULES:
1. Only extract terms that are SHORT and REUSABLE — field labels, button names, tab names, app names, \
   status values, picklist values, single concepts (1–4 words)
2. Do NOT extract full sentences, descriptions, help text, or validation messages
3. Do NOT extract Salesforce merge-field tokens like {!Variable.Name}
4. Each term should be a single concept that could appear across multiple Salesforce components
5. Return ONLY a valid JSON object — no markdown fences, no commentary
6. Output schema: {"terms": [{"source_term": "<english>", "translated_term": "<translation>"}]}\
"""


def build_glossary_extract_prompt(
    target_language: str,
    segments_json: str,
) -> str:
    parts = [
        f"From the following translated Salesforce UI segments ({target_language}), "
        "identify short technical terms suitable for a translation glossary.",
        "\nTRANSLATED SEGMENTS:",
        segments_json,
        '\nRespond with JSON only: {"terms": [{"source_term": "...", "translated_term": "..."}]}',
    ]
    return "\n".join(parts)


TRANSLATE_SYSTEM = """\
You are a Salesforce UI localization engine. Your ONLY job is to produce structurally perfect translations.

HARD CONSTRAINTS — any violation triggers automatic rejection and retry:
1. Preserve ALL Salesforce merge-field tokens EXACTLY as-is: {!Variable.Name}
2. NEVER exceed the character limit per segment — shorten phrasing creatively if needed
3. ALWAYS use the EXACT approved glossary translation for every matching source term
4. Return ONLY a valid JSON object — no markdown fences, no commentary, no explanation
5. Output schema: {"translations": [{"id": "<segment_id>", "translated_text": "<translation>"}]}

Every constraint is verified by deterministic code. There is zero tolerance for violations.\
"""


def build_translate_prompt(
    target_language: str,
    glossary_json: str,
    segments_json: str,
    violations_feedback: str = "",
    validation_feedback: str = "",
) -> str:
    parts = [f"Translate the following Salesforce UI segments to {target_language}."]

    parts.append("\nAPPROVED GLOSSARY — use these translations verbatim for listed source terms:")
    parts.append(glossary_json)

    if violations_feedback or validation_feedback:
        parts.append("\n--- PENALTY: YOUR PREVIOUS TRANSLATION WAS REJECTED ---")
        if violations_feedback:
            parts.append(
                f"\nGLOSSARY VIOLATIONS — you MUST use the exact approved term:\n{violations_feedback}"
            )
        if validation_feedback:
            parts.append(
                f"\nSTRUCTURAL FAILURES — you MUST fix these constraints:\n{validation_feedback}"
            )
        parts.append("\nFailure to correct ALL errors above will trigger another rejection.")

    parts.append("\nSEGMENTS TO TRANSLATE (JSON array — respect char_limit per item):")
    parts.append(segments_json)

    parts.append(
        '\nRespond with JSON only: {"translations": [{"id": "<id>", "translated_text": "<translation>"}]}'
    )

    return "\n".join(parts)
