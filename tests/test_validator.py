import pytest

_STF_LINES = [
    "# Test file",
    "------------------TRANSLATED-------------------",
    "",
    "# KEY\tLABEL\tTRANSLATION\tOUT OF DATE",
    "",
    "CustomLabel.Lbl\tSave\t\t-",
]


def _make_state(segments, translated_segments):
    return {
        "input_file_path": "test.stf",
        "target_language": "fr",
        "segments": segments,
        "stf_lines": _STF_LINES,
        "translation_col": 2,
        "glossary_context": "[]",
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
async def test_validator_passes_clean_translation():
    from app.nodes.validator import validator_node

    segments = [
        {"id": "CustomLabel.Lbl", "source_text": "Save", "component_type": "CustomLabel",
         "component_key": "CustomLabel.Lbl", "merge_fields": [], "char_limit": 1000, "line_index": 5},
    ]
    translated = [{"id": "CustomLabel.Lbl", "translated_text": "Sauvegarder"}]

    result = await validator_node(_make_state(segments, translated))
    assert result["validation_issues"] == []
    assert result["failed_segment_ids"] == []
    assert result["output_stf"] is not None


@pytest.mark.asyncio
async def test_validator_detects_missing_translation():
    from app.nodes.validator import validator_node

    segments = [
        {"id": "CustomLabel.Lbl", "source_text": "Save", "component_type": "CustomLabel",
         "component_key": "CustomLabel.Lbl", "merge_fields": [], "char_limit": 1000, "line_index": 5},
    ]
    result = await validator_node(_make_state(segments, []))

    assert len(result["validation_issues"]) == 1
    assert result["validation_issues"][0]["issue_type"] == "missing_translation"
    assert "CustomLabel.Lbl" in result["failed_segment_ids"]
    assert result["output_stf"] is None


@pytest.mark.asyncio
async def test_validator_detects_altered_merge_field():
    from app.nodes.validator import validator_node

    segments = [
        {"id": "W", "source_text": "Hi {!User.Name}!", "component_type": "CustomLabel",
         "component_key": "W", "merge_fields": ["{!User.Name}"], "char_limit": 1000, "line_index": 5},
    ]
    translated = [{"id": "W", "translated_text": "Bonjour User.Name!"}]

    result = await validator_node(_make_state(segments, translated))
    types = [i["issue_type"] for i in result["validation_issues"]]
    assert "merge_field_altered" in types
    assert "W" in result["failed_segment_ids"]
    assert result["output_stf"] is None


@pytest.mark.asyncio
async def test_validator_detects_char_limit_exceeded():
    from app.nodes.validator import validator_node

    segments = [
        {"id": "CustomLabel.Lbl", "source_text": "Short", "component_type": "CustomLabel",
         "component_key": "CustomLabel.Lbl", "merge_fields": [], "char_limit": 10, "line_index": 5},
    ]
    translated = [{"id": "CustomLabel.Lbl", "translated_text": "This is way too long for the limit"}]

    result = await validator_node(_make_state(segments, translated))
    types = [i["issue_type"] for i in result["validation_issues"]]
    assert "char_limit_exceeded" in types
    assert "CustomLabel.Lbl" in result["failed_segment_ids"]
    assert result["output_stf"] is None


@pytest.mark.asyncio
async def test_validator_aggregates_glossary_violations():
    from app.nodes.validator import validator_node

    segments = [
        {"id": "CustomLabel.Lbl", "source_text": "Save", "component_type": "CustomLabel",
         "component_key": "CustomLabel.Lbl", "merge_fields": [], "char_limit": 1000, "line_index": 5},
    ]
    translated = [{"id": "CustomLabel.Lbl", "translated_text": "Sauvegarder"}]

    state = _make_state(segments, translated)
    state["glossary_violations"] = [{
        "segment_id": "CustomLabel.Lbl",
        "source_term": "Save",
        "approved_translation": "Enregistrer",
        "found_in_translation": "Sauvegarder",
    }]

    result = await validator_node(state)
    assert "CustomLabel.Lbl" in result["failed_segment_ids"]
    assert result["output_stf"] is None


@pytest.mark.asyncio
async def test_validator_reconstructs_stf():
    from app.nodes.validator import validator_node

    stf_lines = [
        "# Test file",
        "------------------TRANSLATED-------------------",
        "",
        "# KEY\tLABEL\tTRANSLATION\tOUT OF DATE",
        "",
        "CustomLabel.Save\tSave\t\t-",
        "CustomLabel.Del\tDelete\t\t-",
    ]
    segments = [
        {"id": "CustomLabel.Save", "source_text": "Save", "component_type": "CustomLabel",
         "component_key": "CustomLabel.Save", "merge_fields": [], "char_limit": 1000, "line_index": 5},
        {"id": "CustomLabel.Del", "source_text": "Delete", "component_type": "CustomLabel",
         "component_key": "CustomLabel.Del", "merge_fields": [], "char_limit": 1000, "line_index": 6},
    ]
    translated = [
        {"id": "CustomLabel.Save", "translated_text": "Sauvegarder"},
        {"id": "CustomLabel.Del", "translated_text": "Supprimer"},
    ]

    state = {
        "input_file_path": "test.stf",
        "target_language": "fr",
        "segments": segments,
        "stf_lines": stf_lines,
        "translation_col": 2,
        "glossary_context": "[]",
        "translated_segments": translated,
        "glossary_violations": [],
        "failed_segment_ids": [],
        "loop_count": 1,
        "validation_issues": [],
        "output_stf": None,
        "extracted_glossary_count": 0,
        "errors": [],
    }

    result = await validator_node(state)
    assert result["output_stf"] is not None
    assert "Sauvegarder" in result["output_stf"]
    assert "Supprimer" in result["output_stf"]

    lines = result["output_stf"].strip().split("\n")
    last_data = lines[-1]
    cols = last_data.split("\t")
    assert cols[2] == "Supprimer"


@pytest.mark.asyncio
async def test_validator_reconstructs_untranslated_section():
    """Rows from the UNTRANSLATED section (2 cols) get translation appended."""
    from app.nodes.validator import validator_node

    stf_lines = [
        "# Test",
        "------------------OUTDATED AND UNTRANSLATED-----------------",
        "",
        "# KEY\tLABEL",
        "",
        "CustomLabel.Hello\tHello",
    ]
    segments = [
        {"id": "CustomLabel.Hello", "source_text": "Hello", "component_type": "CustomLabel",
         "component_key": "CustomLabel.Hello", "merge_fields": [], "char_limit": 1000, "line_index": 5},
    ]
    translated = [{"id": "CustomLabel.Hello", "translated_text": "Bonjour"}]

    state = {
        "input_file_path": "test.stf",
        "target_language": "fr",
        "segments": segments,
        "stf_lines": stf_lines,
        "translation_col": 2,
        "glossary_context": "[]",
        "translated_segments": translated,
        "glossary_violations": [],
        "failed_segment_ids": [],
        "loop_count": 1,
        "validation_issues": [],
        "output_stf": None,
        "extracted_glossary_count": 0,
        "errors": [],
    }

    result = await validator_node(state)
    assert result["output_stf"] is not None
    data_line = result["output_stf"].strip().split("\n")[-1]
    cols = data_line.split("\t")
    assert cols[0] == "CustomLabel.Hello"
    assert cols[1] == "Hello"
    assert cols[2] == "Bonjour"


@pytest.mark.asyncio
async def test_validator_detects_injected_merge_fields():
    from app.nodes.validator import validator_node

    segments = [
        {"id": "CustomLabel.Lbl", "source_text": "Hello world", "component_type": "CustomLabel",
         "component_key": "CustomLabel.Lbl", "merge_fields": [], "char_limit": 1000, "line_index": 5},
    ]
    translated = [{"id": "CustomLabel.Lbl", "translated_text": "Bonjour {!Injected.Field}"}]

    result = await validator_node(_make_state(segments, translated))
    types = [i["issue_type"] for i in result["validation_issues"]]
    assert "merge_field_altered" in types
    assert "CustomLabel.Lbl" in result["failed_segment_ids"]
