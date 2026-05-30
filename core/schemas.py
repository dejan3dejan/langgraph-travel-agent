from typing import Literal

from pydantic import BaseModel, Field


class UserPreferences(BaseModel):
    destination: str = Field(description="Primary city or region for the trip")
    destinations: list[str] = Field(
        default_factory=list,
        description="All destinations in order (e.g. ['Paris', 'Rome']). Empty means single-destination trip.",
    )
    start_location: str = Field(default="the user's current location", description="Where the user is starting from")
    duration: str = Field(description="Total length of stay (e.g. 7 days)")
    budget: str = Field(default="Medium", description="Budget level (Low, Medium, High)")
    interests: str = Field(default="General Sightseeing", description="Comma-separated interests")
    num_travelers: int = Field(default=1, description="Number of people traveling")
    age_range: str = Field(
        default="adults",
        description="Age group: kids, young_adults, adults, seniors, or mixed",
    )
    trip_type: str | None = Field(
        default=None,
        description="Trip style: romantic, family, adventure, business, workation, relaxation, cultural, or None",
    )
    travel_dates: str | None = Field(default=None, description="Specific dates if mentioned (e.g. 'March 13-17, 2026')")
    season_preference: str = Field(
        default="flexible",
        description="Timing preference: peak, off_season, shoulder, flexible",
    )
    constraints: str | None = Field(
        default=None,
        description="Specific constraints (e.g., 'pet friendly', 'wheelchair accessible', 'no car')",
    )
    focus: list[Literal["food", "activities", "hotels"]] = Field(default_factory=list)


class LogisticsBase(BaseModel):
    """Base class for all items that need geocoding."""

    lat: float | None = Field(None, description="Latitude coordinate")
    lon: float | None = Field(None, description="Longitude coordinate")
    geocoding_status: Literal["exact", "neighborhood", "failed"] | None = Field(
        None, description="Precision of geocoding"
    )
    zone: str | None = Field(None, description="Logistical zone (e.g., 'Near Hotel', 'Remote', 'Cluster A')")


class Restaurant(LogisticsBase):
    name: str = Field(description="Name of the restaurant")
    address: str = Field(description="Full street address and city. Essential for logistics.")
    neighborhood: str | None = Field(None, description="Neighborhood or district name")
    website: str | None = Field(None, description="Official website URL")
    cuisine: str = Field(description="Type of cuisine")
    price_level: str = Field(description="Price level ($ to $$$$)")
    rating: float = Field(description="Google rating")
    reason: str = Field(description="Why it fits the user's request")


class RestaurantList(BaseModel):
    items: list[Restaurant]


class Activity(LogisticsBase):
    name: str = Field(description="Name of the activity")
    address: str = Field(description="Full street address and city. Essential for logistics.")
    neighborhood: str | None = Field(None, description="Neighborhood or district name")
    website: str | None = Field(None, description="Official website URL")
    type: str = Field(description="Type of activity (e.g., museum, park, tour)")
    price_level: str = Field(description="Price level ($ to $$$$)")
    rating: float = Field(description="Google rating")
    reason: str = Field(description="Why it fits the user's request")


class ActivityList(BaseModel):
    items: list[Activity]


class Hotel(LogisticsBase):
    name: str = Field(description="Name of the hotel")
    address: str = Field(description="Full street address and city. Essential for logistics.")
    neighborhood: str | None = Field(None, description="Neighborhood or district name")
    website: str | None = Field(None, description="Official website URL")
    price_level: str = Field(description="Price level ($ to $$$$)")
    rating: float = Field(description="Google rating")
    amenities: list[str] = Field(default_factory=list, description="List of amenities (e.g., wifi, pool)")
    reason: str = Field(description="Why it fits the user's request")


class HotelList(BaseModel):
    items: list[Hotel]


class ItineraryCritique(BaseModel):
    approved: bool = Field(description="Whether the itinerary is approved")
    feedback: str = Field(description="Detailed feedback on the itinerary")
    score: int = Field(description="Score from 1-10")
    missing_data: list[Literal["food", "activities", "hotels"]] = Field(default_factory=list)
