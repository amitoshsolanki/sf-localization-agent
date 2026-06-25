import json
import pytest


def _make_state(segments, translated_segments, glossary_terms):
    return {
        "input_file_path": "test.stf",
        "target_language": "fr",
        "segments": segments,
        "stf_lines": [],
        "translation_col": -1,
        "glossary_context": json.dumps(glossary_terms),
        "translated_segments": translated_segments,
        "glossary_violations": [],
        "failed_segment_ids": [],
        "loop_count": 1,
        "validation_issues": [],
        "output_stf": None,
        "extracted_glossary_count": 0,
        "errors": [],
    }


@pytest.mark.asyncio
async def test_auditor_no_violations_when_glossary_used():
    from app.nodes.auditor import auditor_node

    segments = [
        {"id": "Lbl", "source_text": "Save the record", "component_type": "CustomLabel",
         "component_key": "Lbl", "merge_fields": [], "char_limit": 1000, "line_index": 0},
    ]
    translated = [{"id": "Lbl", "translated_text": "Enregistrer le dossier"}]
    glossary = [{"source": "Save", "translation": "Enregistrer", "context": "Button"}]

    result = await auditor_node(_make_state(segments, translated, glossary))
    assert result["glossary_violations"] == []


@pytest.mark.asyncio
async def test_auditor_detects_violation():
    from app.nodes.auditor import auditor_node

    segments = [
        {"id": "Lbl", "source_text": "Save the record", "component_type": "CustomLabel",
         "component_key": "Lbl", "merge_fields": [], "char_limit": 1000, "line_index": 0},
    ]
    translated = [{"id": "Lbl", "translated_text": "Sauvegarder le dossier"}]
    glossary = [{"source": "Save", "translation": "Enregistrer", "context": "Button"}]

    result = await auditor_node(_make_state(segments, translated, glossary))
    assert len(result["glossary_violations"]) == 1
    assert result["glossary_violations"][0]["segment_id"] == "Lbl"
    assert result["glossary_violations"][0]["approved_translation"] == "Enregistrer"


@pytest.mark.asyncio
async def test_auditor_case_insensitive():
    from app.nodes.auditor import auditor_node

    segments = [
        {"id": "Lbl", "source_text": "SAVE the record", "component_type": "CustomLabel",
         "component_key": "Lbl", "merge_fields": [], "char_limit": 1000, "line_index": 0},
    ]
    translated = [{"id": "Lbl", "translated_text": "enregistrer le dossier"}]
    glossary = [{"source": "Save", "translation": "Enregistrer", "context": "Button"}]

    result = await auditor_node(_make_state(segments, translated, glossary))
    assert result["glossary_violations"] == []


@pytest.mark.asyncio
async def test_auditor_skips_irrelevant_terms():
    from app.nodes.auditor import auditor_node

    segments = [
        {"id": "Lbl", "source_text": "Delete the record", "component_type": "CustomLabel",
         "component_key": "Lbl", "merge_fields": [], "char_limit": 1000, "line_index": 0},
    ]
    translated = [{"id": "Lbl", "translated_text": "Supprimer le dossier"}]
    glossary = [{"source": "Save", "translation": "Enregistrer", "context": "Button"}]

    result = await auditor_node(_make_state(segments, translated, glossary))
    assert result["glossary_violations"] == []


@pytest.mark.asyncio
async def test_auditor_empty_glossary():
    from app.nodes.auditor import auditor_node

    segments = [
        {"id": "Lbl", "source_text": "Save", "component_type": "CustomLabel",
         "component_key": "Lbl", "merge_fields": [], "char_limit": 1000, "line_index": 0},
    ]
    translated = [{"id": "Lbl", "translated_text": "Anything"}]

    result = await auditor_node(_make_state(segments, translated, []))
    assert result["glossary_violations"] == []
