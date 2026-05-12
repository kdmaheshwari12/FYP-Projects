# app/schemas/trip_schema.py
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict
from typing import List, Optional, Union
from datetime import date
from enum import Enum
from app.schemas.itinerary_schema import TravelStyle

class TripCreate(BaseModel):
    """
    Schema for creating a new trip.
    itinerary_id is optional to allow creating trips from scratch.
    """
    model_config = ConfigDict(str_strip_whitespace=True)

    destination: str = Field(..., min_length=1, description="Destination city")
    departure_location: str = Field(..., min_length=1, description="Departure city")
    start_date: date = Field(..., description="Trip start date")
    end_date: date = Field(..., description="Trip end date")
    budget: Union[float, str] = Field(..., description="Trip budget in PKR or category (low, moderate, high)")
    travel_style: Optional[TravelStyle] = Field(default=TravelStyle.adventure, description="Travel style (e.g. adventure, luxury)")
    itinerary_id: Optional[str] = Field(None, description="Optional ID of an existing itinerary to reuse")
    trip_type: Optional[str] = Field("ai", description="Type of trip (ai, broker, ai_self, ai_broker)")
    broker_id: Optional[str] = Field(None, description="Optional broker ID if applicable")

    @model_validator(mode="before")
    @classmethod
    def handle_budget_mapping(cls, data: any) -> any:
        if not isinstance(data, dict):
            return data
        
        budget_val = data.get("budget")
        if isinstance(budget_val, str):
            mapping = {"low": 20000, "moderate": 50000, "high": 150000}
            
            # Clean numeric strings (remove commas, currency symbols, whitespace)
            clean_val = "".join(c for c in budget_val if c.isdigit() or c == ".")
            
            try:
                if clean_val:
                    data["budget"] = float(clean_val)
                else:
                    # Not a numeric string, check category mapping
                    data["budget"] = mapping.get(budget_val.lower().strip(), 50000)
            except (ValueError, TypeError):
                data["budget"] = mapping.get(budget_val.lower().strip(), 50000)
        return data

    @field_validator("trip_type")
    @classmethod
    def validate_trip_type(cls, v: str) -> str:
        allowed = ["ai", "broker", "ai_self", "ai_broker"]
        if v.lower() not in allowed:
            raise ValueError(f"Trip type must be one of: {', '.join(allowed)}")
        return v.lower()

    @field_validator("destination", "departure_location", "travel_style", mode="before")
    @classmethod
    def validate_and_clean(cls, v: any, info: any) -> str:
        if v is None:
            if info.field_name == "travel_style":
                return "adventure"
            raise ValueError(f"{info.field_name} cannot be None")
        
        if isinstance(v, str):
            v = v.strip().lower()
            if not v:
                raise ValueError(f"{info.field_name} cannot be empty")
            return v
        return v

    @model_validator(mode="after")
    def validate_trip_dates(self) -> "TripCreate":
        if self.end_date <= self.start_date:
            raise ValueError("End date must be after start date")
        return self
