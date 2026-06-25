from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class GlossaryTerm(SQLModel, table=True):
    __tablename__ = "glossary_terms"

    id: Optional[int] = Field(default=None, primary_key=True)
    source_term: str = Field(index=True)
    target_language: str = Field(index=True)  # ISO 639-1 code, e.g. "fr", "de", "ja"
    approved_translation: str
    context: Optional[str] = Field(default=None)  # UI context hint for disambiguation
    approved: bool = Field(default=True)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class TranslationMemory(SQLModel, table=True):
    __tablename__ = "translation_memory"

    id: Optional[int] = Field(default=None, primary_key=True)
    source_text: str
    target_language: str = Field(index=True)
    translated_text: str
    model_used: str
    glossary_violations: int = Field(default=0)
    loop_count: int = Field(default=0)
    sf_file_path: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=_now)
