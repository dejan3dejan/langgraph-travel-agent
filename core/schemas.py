from typing import List, Optional, Literal
from pydantic import BaseModel, Field

class UserPreferences(BaseModel):
    destination: str = Field(description="City or region for the trip")
    start_location: str = Field(description="Where the user is starting from")
    duration: str = Field(description="Length of stay (e.g. 3 days)")
    budget: str = Field(description="Budget level (Low, Medium, High)")
    interests: str = Field(description="Comma-separated interests")
    constraints: Optional[str] = Field(description="Specific constraints (e.g., 'pet friendly', 'smoking allowed', 'no car', 'party friendly')")
    focus: List[Literal["food", "activities", "hotels"]] = Field(default_factory=list)

class LogisticsBase(BaseModel):
    """Base class for all items that need geocoding."""
    lat: Optional[float] = Field(None, description="Latitude coordinate")
    lon: Optional[float] = Field(None, description="Longitude coordinate")
    geocoding_status: Optional[Literal["exact", "neighborhood", "failed"]] = Field(None, description="Precision of geocoding")
    zone: Optional[str] = Field(None, description="Logistical zone (e.g., 'Near Hotel', 'Remote', 'Cluster A')")

class Restaurant(LogisticsBase):
    name: str = Field(description="Name of the restaurant")
    address: str = Field(description="Full street address and city. Essential for logistics.")
    neighborhood: Optional[str] = Field(None, description="Neighborhood or district name")
    website: Optional[str] = Field(None, description="Official website URL")
    cuisine: str = Field(description="Type of cuisine")
    price_level: str = Field(description="Price level ($ to $$$$)")
    rating: float = Field(description="Google rating")
    reason: str = Field(description="Why it fits the user's request")

class RestaurantList(BaseModel):
    items: List[Restaurant]

class Activity(LogisticsBase):
    name: str = Field(description="Name of the activity")
    address: str = Field(description="Full street address or specific location")
    neighborhood: Optional[str] = Field(None, description="Neighborhood or district name")
    website: Optional[str] = Field(None, description="Official website URL or booking link")
    type: str = Field(description="Type (Museum, Park, etc.)")
    duration: str = Field(description="Estimated time to spend")
    description: str = Field(description="Brief description")

class ActivityList(BaseModel):
    items: List[Activity]

class Hotel(LogisticsBase):
    name: str = Field(description="Name of the hotel")
    address: str = Field(description="Full street address. Essential for logistics.")
    neighborhood: str = Field(description="Neighborhood location")
    website: Optional[str] = Field(None, description="Official website URL or booking link")
    price_range: str = Field(description="Price estimate per night")
    pros: str = Field(description="Key advantages")

class HotelList(BaseModel):
    items: List[Hotel]

class ItineraryCritique(BaseModel):
    approved: bool = Field(description="Is the plan ready for the user?")
    score: int = Field(description="Quality score 1-10")
    feedback: str = Field(description="Specific issues to fix if not approved")
    missing_data: List[Literal["food", "activities", "hotels"]] = Field(
        default_factory=list, 
        description="List of categories that need more (or better) research data."
    )
