"""Data schema for the Uttarakhand knowledge graph.

Every fact carries provenance (`source`) and a `confidence` so that the planner, the
Critic agent and the evals can tell sourced facts from unverified ones.
"""
import re
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field


class EntityType(StrEnum):
    DESTINATION = "Destination"
    ATTRACTION = "Attraction"
    ACTIVITY = "Activity"
    EATERY = "Eatery"
    STAY = "Stay"
    DISH = "Dish"
    GATEWAY = "Gateway"


class Tier(StrEnum):
    BUDGET = "budget"
    MID = "mid"
    PREMIUM = "premium"


class Confidence(StrEnum):
    SOURCED = "sourced"  # taken from a cited source, fetched automatically
    CURATED_UNVERIFIED = "curated_unverified"  # hand-entered, still needs checking
    VERIFIED = "verified"  # a human checked it against an official source


class Source(BaseModel):
    name: str
    url: str
    license: str = ""
    fetched_at: date | None = None


class Connection(BaseModel):
    relation: str  # IN_DESTINATION, NEAR, FAMOUS_FOR, ...
    target: str  # entity id
    distance_km: float | None = None


class Entity(BaseModel):
    id: str
    type: EntityType
    name: str
    destination_id: str | None = None
    description: str = ""
    semantic_text: str = ""
    lat: float | None = None
    lon: float | None = None
    elevation_m: float | None = None
    coord_source: str = ""  # "wikivoyage" | "osm" | "nominatim" | "google" | "" (none)
    google_place_id: str = ""  # safe to store; coordinates from Google are time-limited
    tags: list[str] = Field(default_factory=list)
    tier: Tier | None = None
    price_text: str = ""
    hours: str = ""
    address: str = ""
    phone: str = ""
    url: str = ""
    region: str = ""  # Garhwal / Kumaon
    source: Source
    confidence: Confidence = Confidence.SOURCED
    last_verified: date | None = None
    connections: list[Connection] = Field(default_factory=list)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def make_id(etype: EntityType, destination: str, name: str) -> str:
    return f"{etype.value.lower()}_{slugify(destination)}_{slugify(name)}"


# Rough bounding box of Uttarakhand, used only to flag suspicious coordinates.
UK_BBOX = (28.7, 31.5, 77.5, 81.1)  # lat_min, lat_max, lon_min, lon_max


def in_uttarakhand(lat: float, lon: float) -> bool:
    return UK_BBOX[0] <= lat <= UK_BBOX[1] and UK_BBOX[2] <= lon <= UK_BBOX[3]
