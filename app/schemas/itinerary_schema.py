# app/schemas/itinerary_schema.py
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict
from typing import List, Optional, Union
from enum import Enum

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

class ItineraryRequest(BaseModel):
    """
    Flexible input schema to support both old and new frontend formats.
    """
    model_config = ConfigDict(
        str_strip_whitespace=True,
        populate_by_name=True
    )

    destination: str
    departure_location: Optional[str] = Field(default=None)
    budget: Union[float, str]
    duration_days: Optional[int] = Field(default=None)
    travel_style: Optional[TravelStyle] = Field(default=TravelStyle.adventure)
    interests: Optional[List[str]] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def handle_aliases_and_types(cls, data: any) -> any:
        if not isinstance(data, dict):
            return data
        
        # Map old names to new names if needed
        if "departure" in data and not data.get("departure_location"):
            data["departure_location"] = data["departure"]
        if "duration" in data and not data.get("duration_days"):
            try:
                data["duration_days"] = int(data["duration"])
            except:
                data["duration_days"] = 3
        
        # Handle budget string categories
        budget_val = data.get("budget")
        if isinstance(budget_val, str):
            mapping = {"low": 20000, "moderate": 50000, "high": 150000}
            data["budget"] = mapping.get(budget_val.lower(), 50000)
            
        return data

    @property
    def resolved_interests(self) -> List[str]:
        return self.interests if self.interests else ["Culture", "Adventure"]
