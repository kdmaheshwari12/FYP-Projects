# app/schemas/trip_schema.py
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict
from typing import List, Optional
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
    budget: float = Field(..., gt=0, description="Trip budget in PKR")
    travel_style: TravelStyle = Field(..., description="Travel style (e.g. adventure, luxury)")
    itinerary_id: Optional[str] = Field(None, description="Optional ID of an existing itinerary to reuse")
    trip_type: Optional[str] = Field("ai", description="Type of trip (ai, broker, ai_self, ai_broker)")
    broker_id: Optional[str] = Field(None, description="Optional broker ID if applicable")

    @field_validator("trip_type")
    @classmethod
    def validate_trip_type(cls, v: str) -> str:
        allowed = ["ai", "broker", "ai_self", "ai_broker"]
        if v.lower() not in allowed:
            raise ValueError(f"Trip type must be one of: {', '.join(allowed)}")
        return v.lower()

    @field_validator("destination", "departure_location", mode="before")
    @classmethod
    def validate_not_empty(cls, v: object) -> str:
        if v is None or (isinstance(v, str) and not v.strip()):
            raise ValueError("Field cannot be empty")
        return str(v).strip()

    @model_validator(mode="after")
    def validate_trip_dates(self) -> "TripCreate":
        if self.end_date <= self.start_date:
            raise ValueError("End date must be after start date")
        return self

    @model_validator(mode="after")
    def validate_destination_departure(self) -> "TripCreate":
        if self.destination.lower() == self.departure_location.lower():
            raise ValueError("Destination and departure location cannot be the same")
        return self
