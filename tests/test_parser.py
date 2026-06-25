import pathlib
import pytest

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "sample.stf"


@pytest.fixture
def base_state():
    return {
        "input_file_path": str(FIXTURE),
        "target_language": "fr",
        "segments": [],
        "stf_lines": [],
        "translation_col": -1,
        "glossary_context": "[]",
        "translated_segments": [],
        "glossary_violations": [],
        "failed_segment_ids": [],
        "loop_count": 0,
        "validation_issues": [],
        "output_stf": None,
        "extracted_glossary_count": 0,
        "errors": [],
    }


@pytest.mark.asyncio
async def test_parser_extracts_all_segments(base_state, monkeypatch):
    monkeypatch.setattr("app.nodes.parser._fetch_relevant_glossary", _stub_glossary)
    from app.nodes.parser import parser_node

    result = await parser_node(base_state)

    assert result["errors"] == []
    segs = result["segments"]
    keys = [s["component_key"] for s in segs]

    assert len(segs) == 6
    assert "ButtonOrLink.Account.SendContract" in keys
    assert "CustomLabel.SaveButton" in keys
    assert "CustomLabel.WelcomeMessage" in keys
    assert "CustomLabel.DeleteConfirm" in keys
    assert "CustomField.Account.Industry.FieldLabel" in keys
    assert "CustomField.Account.Industry.HelpText" in keys


@pytest.mark.asyncio
async def test_parser_includes_translated_rows(base_state, monkeypatch):
    """All rows are included — both already-translated and untranslated."""
    monkeypatch.setattr("app.nodes.parser._fetch_relevant_glossary", _stub_glossary)
    from app.nodes.parser import parser_node

    result = await parser_node(base_state)
    ids = {s["id"] for s in result["segments"]}

    assert "ButtonOrLink.Account.SendContract" in ids
    assert "CustomLabel.SaveButton" in ids


@pytest.mark.asyncio
async def test_parser_extracts_merge_fields(base_state, monkeypatch):
    monkeypatch.setattr("app.nodes.parser._fetch_relevant_glossary", _stub_glossary)
    from app.nodes.parser import parser_node

    result = await parser_node(base_state)
    segs = {s["component_key"]: s for s in result["segments"]}

    welcome = segs["CustomLabel.WelcomeMessage"]
    assert "{!User.FirstName}" in welcome["merge_fields"]
    assert "{!User.UnreadCount}" in welcome["merge_fields"]


@pytest.mark.asyncio
async def test_parser_extracts_component_type_from_key(base_state, monkeypatch):
    monkeypatch.setattr("app.nodes.parser._fetch_relevant_glossary", _stub_glossary)
    from app.nodes.parser import parser_node

    result = await parser_node(base_state)
    segs = {s["component_key"]: s for s in result["segments"]}

    assert segs["CustomLabel.SaveButton"]["component_type"] == "CustomLabel"
    assert segs["ButtonOrLink.Account.SendContract"]["component_type"] == "ButtonOrLink"
    assert segs["CustomField.Account.Industry.FieldLabel"]["component_type"] == "CustomField"


@pytest.mark.asyncio
async def test_parser_char_limits(base_state, monkeypatch):
    monkeypatch.setattr("app.nodes.parser._fetch_relevant_glossary", _stub_glossary)
    from app.nodes.parser import parser_node

    result = await parser_node(base_state)
    segs = {s["component_key"]: s for s in result["segments"]}

    assert segs["CustomLabel.SaveButton"]["char_limit"] == 1000
    assert segs["CustomField.Account.Industry.FieldLabel"]["char_limit"] == 255


@pytest.mark.asyncio
async def test_parser_missing_file(base_state, monkeypatch):
    monkeypatch.setattr("app.nodes.parser._fetch_relevant_glossary", _stub_glossary)
    from app.nodes.parser import parser_node

    base_state["input_file_path"] = "/nonexistent/path/file.stf"
    result = await parser_node(base_state)

    assert result["segments"] == []
    assert any("File read error" in e for e in result["errors"])


@pytest.mark.asyncio
async def test_parser_detects_translation_col(base_state, monkeypatch):
    monkeypatch.setattr("app.nodes.parser._fetch_relevant_glossary", _stub_glossary)
    from app.nodes.parser import parser_node

    result = await parser_node(base_state)

    assert result["translation_col"] == 2


@pytest.mark.asyncio
async def test_parser_preserves_all_lines(base_state, monkeypatch):
    monkeypatch.setattr("app.nodes.parser._fetch_relevant_glossary", _stub_glossary)
    from app.nodes.parser import parser_node

    result = await parser_node(base_state)

    stf_lines = result["stf_lines"]
    assert len(stf_lines) > 0
    assert any("TRANSLATED" in l for l in stf_lines)
    assert any("UNTRANSLATED" in l for l in stf_lines)


@pytest.mark.asyncio
async def test_parser_line_index_points_to_correct_line(base_state, monkeypatch):
    monkeypatch.setattr("app.nodes.parser._fetch_relevant_glossary", _stub_glossary)
    from app.nodes.parser import parser_node

    result = await parser_node(base_state)

    for seg in result["segments"]:
        line = result["stf_lines"][seg["line_index"]]
        assert seg["source_text"] in line


@pytest.mark.asyncio
async def test_parser_auto_detects_language(base_state, monkeypatch):
    monkeypatch.setattr("app.nodes.parser._fetch_relevant_glossary", _stub_glossary)
    from app.nodes.parser import parser_node

    base_state["target_language"] = ""
    result = await parser_node(base_state)

    assert result["target_language"] == "fr"
    assert result["errors"] == []
    assert len(result["segments"]) > 0


async def _stub_glossary(target_language, segments):
    return "[]"
