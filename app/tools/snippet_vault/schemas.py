from typing import Literal, Optional

from pydantic import BaseModel, Field


NoteType = Literal["ssh", "database", "command", "credential", "query", "other"]


class SnippetCreate(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    content: str = Field(min_length=1)
    type: NoteType = "other"
    tags: list[str] = []


class SnippetUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=180)
    content: Optional[str] = Field(default=None, min_length=1)
    type: Optional[NoteType] = None
    tags: Optional[list[str]] = None
