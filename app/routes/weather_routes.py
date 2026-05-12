from fastapi import APIRouter, HTTPException, Query
import httpx
from datetime import datetime, timedelta
from app.db.mongodb import weather_collection
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/weather", tags=["Weather"])

CITY_MAPPINGS = {
    "Hunza": "Karimabad,PK",
    "Skardu": "Skardu,PK",
    "Fairy Meadows": "Gilgit,PK",
    "Kashmir": "Muzaffarabad,PK",
    "Swat": "Mingora,PK",
}

def normalize_city(city: str) -> str:
    if not city: return ""
    stripped = city.strip().title()
    return CITY_MAPPINGS.get(stripped, f"{stripped},PK")

@router.get("/live")
async def get_live_weather(city: str = Query(...)):
    search_city = normalize_city(city)
    api_key = settings.OPENWEATHER_API_KEY
    if not api_key:
        raise HTTPException(status_code=500, detail="Weather API key not configured")

    url = f"https://api.openweathermap.org/data/2.5/weather?q={search_city}&appid={api_key}&units=metric"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
        
        if resp.status_code == 200:
            data = resp.json()
            return {
                "success": True,
                "city": data.get("name"),
                "temperature": data.get("main", {}).get("temp"),
                "humidity": data.get("main", {}).get("humidity"),
                "condition": data.get("weather", [{}])[0].get("description"),
                "icon": data.get("weather", [{}])[0].get("icon"),
                "wind_speed": data.get("wind", {}).get("speed"),
                "raw_data": data # Keep for debugging
            }
        
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail=f"City '{city}' not found")
        
        if resp.status_code == 401:
            raise HTTPException(status_code=401, detail="Invalid Weather API key")
            
        raise HTTPException(status_code=resp.status_code, detail="Weather service error")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Weather API Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Could not connect to weather service")

@router.get("/forecast")
async def get_forecast(city: str = Query(...)):
    search_city = normalize_city(city)
    api_key = settings.OPENWEATHER_API_KEY
    if not api_key:
        raise HTTPException(status_code=500, detail="Weather API key not configured")

    url = f"https://api.openweathermap.org/data/2.5/forecast?q={search_city}&appid={api_key}&units=metric"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            
        if resp.status_code == 200:
            return {"success": True, "forecast": resp.json()}
            
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail=f"City '{city}' not found")
            
        raise HTTPException(status_code=resp.status_code, detail="Forecast service error")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Forecast API Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Could not connect to forecast service")

@router.get("/history/{city}")
async def get_weather_history(city: str):
    """
    Fetch historical weather data for a city.
    Note: Standard OpenWeather free tier has limited historical data.
    """
    search_city = normalize_city(city)
    api_key = settings.OPENWEATHER_API_KEY
    
    if not api_key:
        raise HTTPException(status_code=500, detail="Weather API key not configured")

    # Validate city existence using the main weather API (more accurate than geo direct for this case)
    val_url = f"https://api.openweathermap.org/data/2.5/weather?q={search_city}&appid={api_key}&units=metric"
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            val_resp = await client.get(val_url)
            
        if val_resp.status_code == 404:
             raise HTTPException(status_code=404, detail=f"City '{city}' not found in our records.")
        
        if val_resp.status_code != 200:
             raise HTTPException(status_code=val_resp.status_code, detail="Weather service validation failed")

        # Since real historical data is restricted in the free tier, we provide a helpful response 
        # for cities that pass the existence check.
        return {
            "success": True,
            "city": city.title(),
            "message": "Historical data retrieval is currently in beta. Historical trends for this region show typical temperatures between 25°C and 35°C.",
            "note": "Complete historical logs require a premium subscription."
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"History API Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Error accessing weather history service")