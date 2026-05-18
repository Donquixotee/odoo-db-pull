from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field


EntryStatus = Literal["assigned", "in_progress", "sent", "accepted"]


class TimeEntryCreate(BaseModel):
    work_date: date
    task: str = Field(min_length=1, max_length=160)
    notes: str = ""
    hours: float = Field(gt=0, le=24)
    hourly_rate: float = Field(default=7.5, gt=0, le=500)
    status: EntryStatus = "sent"
    paid: bool = False


class TimeEntryUpdate(BaseModel):
    work_date: Optional[date] = None
    task: Optional[str] = Field(default=None, min_length=1, max_length=160)
    notes: Optional[str] = None
    hours: Optional[float] = Field(default=None, gt=0, le=24)
    hourly_rate: Optional[float] = Field(default=None, gt=0, le=500)
    status: Optional[EntryStatus] = None
    paid: Optional[bool] = None


class TimeTrackerSettingsUpdate(BaseModel):
    eur_to_dzd_rate: float = Field(gt=0, le=10000)
