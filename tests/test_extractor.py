import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.nodes.extractor import (
    _GlossaryEntry,
    _GlossaryExtractionResponse,
)


def _make_state(segments, translated_segments, output_stf="translated content"):
    return {
        "input_file_path": "test.stf",
        "target_language": "fr",
        "segments": segments,
        "stf_lines": [],
        "translation_col": 2,
        "glossary_context": "[]",
        "translated_segments": translated_segments,
        "glossary_violations": [],
        "failed_segment_ids": [],
        "loop_count": 1,
        "validation_issues": [],
        "output_stf": output_stf,
        "extracted_glossary_count": 0,
        "errors": [],
    }


def _mock_llm_response(terms):
    response = _GlossaryExtractionResponse(
        terms=[_GlossaryEntry(**t) for t in terms]
    )
    llm = AsyncMock()
    llm.ainvoke = AsyncMock(return_value=response)
    return llm


@pytest.mark.asyncio
async def test_extracts_new_terms():
    from app.nodes.extractor import extractor_node

    segments = [
        {"id": "CustomField.Account.Industry.FieldLabel", "source_text": "Industry",
         "component_type": "CustomField", "component_key": "CustomField.Account.Industry.FieldLabel",
         "merge_fields": [], "char_limit": 255, "line_index": 5},
    ]
    translated = [{"id": "CustomField.Account.Industry.FieldLabel", "translated_text": "Industrie"}]

    mock_llm = _mock_llm_response([
        {"source_term": "Industry", "translated_term": "Industrie"},
    ])

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.nodes.extractor._get_llm", return_value=mock_llm), \
         patch("app.nodes.extractor.AsyncSessionLocal", return_value=mock_ctx):
        result = await extractor_node(_make_state(segments, translated))

    assert result["extracted_glossary_count"] == 1
    mock_session.add.assert_called_once()
    added_term = mock_session.add.call_args[0][0]
    assert added_term.source_term == "Industry"
    assert added_term.approved_translation == "Industrie"
    assert added_term.approved is False


@pytest.mark.asyncio
async def test_skips_existing_approved_terms():
    from app.nodes.extractor import extractor_node

    segments = [
        {"id": "CustomLabel.Save", "source_text": "Save",
         "component_type": "CustomLabel", "component_key": "CustomLabel.Save",
         "merge_fields": [], "char_limit": 1000, "line_index": 5},
    ]
    translated = [{"id": "CustomLabel.Save", "translated_text": "Enregistrer"}]

    mock_llm = _mock_llm_response([
        {"source_term": "Save", "translated_term": "Enregistrer"},
    ])

    existing_term = MagicMock()
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = existing_term
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.nodes.extractor._get_llm", return_value=mock_llm), \
         patch("app.nodes.extractor.AsyncSessionLocal", return_value=mock_ctx):
        result = await extractor_node(_make_state(segments, translated))

    assert result["extracted_glossary_count"] == 0
    mock_session.add.assert_not_called()


@pytest.mark.asyncio
async def test_noop_when_no_output():
    from app.nodes.extractor import extractor_node

    result = await extractor_node(_make_state([], [], output_stf=None))

    assert result["extracted_glossary_count"] == 0


@pytest.mark.asyncio
async def test_filters_terms_longer_than_two_words():
    """Only 1- and 2-word source terms are inserted; longer phrases are dropped."""
    from app.nodes.extractor import extractor_node

    segments = [
        {"id": "s1", "source_text": "Send Contract", "component_type": "ButtonOrLink",
         "component_key": "s1", "merge_fields": [], "char_limit": 255, "line_index": 5},
    ]
    translated = [{"id": "s1", "translated_text": "Envoyer le contrat"}]

    mock_llm = _mock_llm_response([
        {"source_term": "Industry", "translated_term": "Industrie"},
        {"source_term": "Send Contract", "translated_term": "Envoyer le contrat"},
        {"source_term": "Please enter a valid value", "translated_term": "Veuillez saisir une valeur valide"},
    ])

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.nodes.extractor._get_llm", return_value=mock_llm), \
         patch("app.nodes.extractor.AsyncSessionLocal", return_value=mock_ctx):
        result = await extractor_node(_make_state(segments, translated))

    assert result["extracted_glossary_count"] == 2
    added_sources = [call.args[0].source_term for call in mock_session.add.call_args_list]
    assert added_sources == ["Industry", "Send Contract"]


@pytest.mark.asyncio
async def test_returns_correct_count_with_mixed():
    """Some terms are new, some already exist — count reflects only new inserts."""
    from app.nodes.extractor import extractor_node

    segments = [
        {"id": "s1", "source_text": "Industry", "component_type": "CustomField",
         "component_key": "s1", "merge_fields": [], "char_limit": 255, "line_index": 5},
        {"id": "s2", "source_text": "Save", "component_type": "CustomLabel",
         "component_key": "s2", "merge_fields": [], "char_limit": 1000, "line_index": 6},
    ]
    translated = [
        {"id": "s1", "translated_text": "Industrie"},
        {"id": "s2", "translated_text": "Enregistrer"},
    ]

    mock_llm = _mock_llm_response([
        {"source_term": "Industry", "translated_term": "Industrie"},
        {"source_term": "Save", "translated_term": "Enregistrer"},
    ])

    existing_term = MagicMock()
    call_count = 0

    async def mock_execute(query):
        nonlocal call_count
        call_count += 1
        mock_result = MagicMock()
        if call_count == 1:
            mock_result.scalars.return_value.first.return_value = None
        else:
            mock_result.scalars.return_value.first.return_value = existing_term
        return mock_result

    mock_session = AsyncMock()
    mock_session.execute = mock_execute
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.nodes.extractor._get_llm", return_value=mock_llm), \
         patch("app.nodes.extractor.AsyncSessionLocal", return_value=mock_ctx):
        result = await extractor_node(_make_state(segments, translated))

    assert result["extracted_glossary_count"] == 1
    assert mock_session.add.call_count == 1
