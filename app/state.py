from typing import Optional, TypedDict


class TranslationSegment(TypedDict):
    id: str
    source_text: str
    component_type: str  # e.g. "CustomField", "ButtonOrLink"
    component_key: str   # full KEY from .stf (e.g. "CustomField.Obj.Field.FieldLabel")
    merge_fields: list[str]
    char_limit: int
    line_index: int      # index into stf_lines for reconstruction


class TranslatedSegment(TypedDict):
    id: str
    translated_text: str


class GlossaryViolation(TypedDict):
    segment_id: str
    source_term: str
    approved_translation: str
    found_in_translation: str


class ValidationIssue(TypedDict):
    segment_id: str
    issue_type: str  # missing_translation | merge_field_altered | char_limit_exceeded
    details: str


class AgentState(TypedDict):
    # Inputs
    input_file_path: str
    target_language: str

    # Set by Parser
    segments: list[TranslationSegment]
    stf_lines: list[str]           # all raw lines preserved for reconstruction
    translation_col: int           # column index for the Translation field
    glossary_context: str          # proactively fetched glossary as JSON

    # Set by Translator / Auditor / Validator loop
    translated_segments: list[TranslatedSegment]
    glossary_violations: list[GlossaryViolation]
    failed_segment_ids: list[str]  # segments that need retry (set by validator)
    loop_count: int

    # Set by Validator
    validation_issues: list[ValidationIssue]

    # Final output
    output_stf: Optional[str]
    extracted_glossary_count: int
    errors: list[str]
