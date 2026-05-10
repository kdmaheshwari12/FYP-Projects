from fastapi import APIRouter, HTTPException
import httpx
import os
from datetime import datetime
from bson import ObjectId
from app.db.mongodb import weather_collection, itineraries_collection
from app.core.validation import validate_string, ValidationError
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/weather", tags=["Weather"])

from app.core.config import settings

@router.get("/live")
async def get_live_weather(city: str):
    """
    Get live weather for a city with validation and caching.
    """
    # 1️⃣ Validate City
    try:
        validated_city = validate_string(city, "city", allow_empty=False, min_length=2).title()
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=f"Invalid city name: {e.message}")

    # 2️⃣ Check Cache (last 15 minutes)
    try:
        cached = await weather_collection.find_one({
            "city": validated_city,
            "timestamp": {"$gte": datetime.utcnow() - timedelta(minutes=15)}
        })
        if cached and "weather_summary" in cached:
            logger.info(f"Weather cache hit for {validated_city}")
            return cached["weather_summary"]
    except Exception as e:
        logger.error(f"Cache lookup failed: {e}")

    # 3️⃣ Fetch from OpenWeather
    api_key = settings.OPENWEATHER_API_KEY
    if not api_key:
        logger.error("OPENWEATHER_API_KEY is missing in settings")
        raise HTTPException(status_code=500, detail="Weather service configuration error")

    url = f"https://api.openweathermap.org/data/2.5/weather?q={validated_city}&appid={api_key}&units=metric"
    
    logger.debug(f"Fetching weather from: {url}")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url)
            
        logger.debug(f"Weather API status: {response.status_code}")
        logger.debug(f"Weather API body: {response.text}")

        if response.status_code == 401:
            logger.error("Invalid OpenWeather API Key")
            raise HTTPException(status_code=503, detail="Weather service unavailable (auth error)")
        
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail=f"City '{validated_city}' not found")

        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Weather API error")

        data = response.json()
        
        # 4️⃣ Format Response
        summary = {
            "city": data.get("name", validated_city),
            "temperature": round(data["main"]["temp"]),
            "humidity": data["main"]["humidity"],
            "condition": data["weather"][0]["description"]
        }

        # 5️⃣ Update Cache
        try:
            await weather_collection.insert_one({
                "city": validated_city,
                "weather_summary": summary,
                "raw_response": data,
                "timestamp": datetime.utcnow()
            })
        except Exception as e:
            logger.error(f"Failed to cache weather: {e}")

        return summary

    except httpx.TimeoutException:
        logger.error("Weather API timeout")
        raise HTTPException(status_code=504, detail="Weather service timed out")
    except httpx.RequestError as e:
        logger.error(f"Weather API connection error: {e}")
        raise HTTPException(status_code=503, detail="Weather service unreachable")
    except Exception as e:
        if isinstance(e, HTTPException): raise e
        logger.error(f"Unexpected weather error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal weather service error")

def serialize_mongo_doc(doc: dict):
    """
    Converts ObjectId → string so FastAPI can return the document safely.
    """
    for key, value in doc.items():
        if isinstance(value, ObjectId):
            doc[key] = str(value)
        # also check nested fields
        if isinstance(value, dict):
            doc[key] = serialize_mongo_doc(value)
        if isinstance(value, list):
            doc[key] = [serialize_mongo_doc(v) if isinstance(v, dict) else v for v in value]
    return doc


async def fetch_openweather(url: str):
    """
    Helper to fetch weather data from OpenWeather API
    """
    async with httpx.AsyncClient() as client:
        res = await client.get(url)
        data = res.json()

    if res.status_code != 200:
        raise HTTPException(400, detail=data)

    return data


# -------- 2) GET WEATHER HISTORY -------- #
@router.get("/history/{city}")
async def get_weather_history(city: str):

    records = (
        await weather_collection.find({"city": city})
        .sort("timestamp", -1)
        .to_list(None)
    )

    # Convert each MongoDB document
    records = [serialize_mongo_doc(r) for r in records]

    return {
        "city": city,
        "count": len(records),
        "history": records,
    }

# -------- 3) FETCH WEATHER FOR ITINERARY -------- #
@router.post("/itinerary/{itinerary_id}")
async def fetch_itinerary_weather(itinerary_id: str):

    try:
        itinerary = await itineraries_collection.find_one({"_id": ObjectId(itinerary_id)})

        if not itinerary:
            raise HTTPException(404, "Itinerary not found")

        city = itinerary.get("destination")
        if not city:
            raise HTTPException(400, "Itinerary has no destination field")

        # Fetch live weather for itinerary city
        url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={settings.OPENWEATHER_API_KEY}&units=metric"

        async with httpx.AsyncClient() as client:
            res = await client.get(url)
            data = res.json()

        if res.status_code != 200:
            raise HTTPException(400, data)

        # Save inside itinerary document
        await itineraries_collection.update_one(
            {"_id": itinerary["_id"]},
            {"$set": {"latestWeather": data, "weatherUpdatedAt": datetime.utcnow()}}
        )

        return {
            "status": "success",
            "destination": city,
            "message": "Weather updated for itinerary",
            "weather": data
        }

    except Exception as e:
        raise HTTPException(500, f"Weather update error: {str(e)}")
    
@router.get("/forecast")
async def get_forecast(city: str):
    try:
        url = f"https://api.openweathermap.org/data/2.5/forecast?q={city}&appid={settings.OPENWEATHER_API_KEY}&units=metric"

        async with httpx.AsyncClient() as client:
            res = await client.get(url)
            data = res.json()

        if res.status_code != 200:
            raise HTTPException(400, data)

        # Store forecast snapshot
        record = {
            "city": city,
            "type": "forecast",
            "data": data,
            "timestamp": datetime.utcnow()
        }
        await weather_collection.insert_one(record)

        return {
            "status": "success",
            "message": "5-day forecast fetched & stored",
            "forecast": data
        }

    except Exception as e:
        raise HTTPException(500, f"Forecast fetch error: {str(e)}")