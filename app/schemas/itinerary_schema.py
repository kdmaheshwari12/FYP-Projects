# app/schemas/itinerary_schema.py
"""
Pydantic v2 request schema for POST /traveler/generate-itinerary.

All validators run BEFORE the LLM is called.
Empty strings, whitespace-only values, zero/negative numbers → HTTP 422.
"""

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic import ConfigDict
from typing import List, Optional
from enum import Enum


# ---------------------------------------------------------------------------
# Allowed travel styles
# ---------------------------------------------------------------------------
class TravelStyle(str, Enum):
    adventure  = "adventure"
    cultural   = "cultural"
    relaxation = "relaxation"
    family     = "family"
    budget     = "budget"
    luxury     = "luxury"
    solo       = "solo"
    nature     = "nature"
    religious  = "religious"
    food       = "food"


# ---------------------------------------------------------------------------
# Request schema
# ---------------------------------------------------------------------------
class ItineraryRequest(BaseModel):
    """
    Strict input schema for AI itinerary generation.

    FastAPI feeds this BEFORE any route code runs.
    Any validation failure → HTTP 422 with a clear message.
    The LLM is NEVER called if validation fails.
    """

    model_config = ConfigDict(
        # Return the first validation error with a readable message
        # rather than the Pydantic internal representation
        str_strip_whitespace=True,   # auto-strip all str fields
    )

    destination: str = Field(
        ...,
        min_length=1,
        description="Travel destination inside Pakistan (e.g. 'Hunza Valley')",
    )
    departure_location: str = Field(
        ...,
        min_length=1,
        description="City the traveller departs from (e.g. 'Islamabad')",
    )
    budget: float = Field(
        ...,
        gt=0,
        description="Total trip budget in PKR — must be greater than 0",
    )
    duration_days: int = Field(
        ...,
        ge=1,
        le=30,
        description="Number of trip days (1–30)",
    )
    travel_style: TravelStyle = Field(
        ...,
        description="Travel style selection",
    )
    interests: Optional[List[str]] = Field(
        default=None,
        description="Optional list of interest tags",
    )

    # ── Field Validators ──────────────────────────────────────────────────────

    @field_validator("destination", "departure_location", mode="before")
    @classmethod
    def validate_not_empty(cls, v: object, info) -> str:
        field_name = info.field_name.replace("_", " ").title()
        if v is None or (isinstance(v, str) and not v.strip()):
            raise ValueError(f"{field_name} is required")
        if not isinstance(v, str):
            raise ValueError(f"{field_name} must be a string")
        return v.strip()

    @field_validator("duration_days")
    @classmethod
    def validate_duration_days(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Duration days must be greater than 0")
        if v > 30:
            raise ValueError("Duration days cannot exceed 30")
        return v

    @field_validator("budget")
    @classmethod
    def validate_budget(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Budget must be greater than 0")
        return v

    @field_validator("interests", mode="before")
    @classmethod
    def validate_interests(cls, v: object) -> List[str]:
        if v is None:
            return ["Culture", "Adventure"]
        if not isinstance(v, list):
            raise ValueError("Interests must be a list of strings")
        cleaned = [str(i).strip() for i in v if str(i).strip()]
        return cleaned if cleaned else ["Culture", "Adventure"]

    # ── Cross-field validation ────────────────────────────────────────────────

    @model_validator(mode="after")
    def destination_not_same_as_departure(self) -> "ItineraryRequest":
        if self.destination.lower() == self.departure_location.lower():
            raise ValueError(
                "Destination and departure location cannot be the same city"
            )
        return self

    # ── Convenience property ──────────────────────────────────────────────────

    @property
    def resolved_interests(self) -> List[str]:
        """Always returns a non-empty interests list."""
        return self.interests or ["Culture", "Adventure"]
