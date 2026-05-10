from fastapi import APIRouter, HTTPException, Query
import httpx
import os
from datetime import datetime, timedelta
from bson import ObjectId
from app.db.mongodb import weather_collection, itineraries_collection
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/weather", tags=["Weather"])

# ====================================================
# 1. CITY NORMALIZATION
# ====================================================
CITY_MAPPINGS = {
    "Hunza": "Karimabad,PK",
    "Hunza Valley": "Karimabad,PK",
    "Skardu": "Skardu,PK",
    "Fairy Meadows": "Gilgit,PK",
    "Kashmir": "Muzaffarabad,PK",
    "Swat": "Mingora,PK",
    "Naran": "Naran,PK",
    "Kaghan": "Kaghan,PK",
    "Neelum Valley": "Muzaffarabad,PK",
    "Gilgit Baltistan": "Gilgit,PK",
    "Naltar": "Gilgit,PK",
    "Deosai": "Skardu,PK",
}

def normalize_city(city: str) -> str:
    if not city:
        return ""
    stripped = city.strip().title()
    return CITY_MAPPINGS.get(stripped, f"{stripped},PK")

# ====================================================
# 2. DIAGNOSTIC ENDPOINT — /weather/debug
# Run this first to confirm API key + connectivity
# ====================================================
@router.get("/debug")
async def debug_weather():
    """
    Diagnostic endpoint.
    Checks: API key presence, OpenWeather connectivity, test city fetch.
    Hit GET /weather/debug to diagnose any weather issues.
    """
    api_key = settings.OPENWEATHER_API_KEY
    key_present = bool(api_key)
    key_preview = (api_key[:6] + "...") if api_key else "MISSING"

    print(f"[DEBUG] OPENWEATHER_API_KEY present: {key_present}, preview: {key_preview}")

    if not api_key:
        return {
            "step": "api_key_check",
            "ok": False,
            "error": "OPENWEATHER_API_KEY is not set in environment variables",
            "fix": "Set OPENWEATHER_API_KEY in Railway environment variables"
        }

    # Test with a well-known city
    test_url = f"https://api.openweathermap.org/data/2.5/weather?q=Karachi,PK&appid={api_key}&units=metric"
    print(f"[DEBUG] Testing URL: {test_url}")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(test_url)

        print(f"[DEBUG] Test status: {resp.status_code}")
        print(f"[DEBUG] Test body: {resp.text[:300]}")

        if resp.status_code == 200:
            data = resp.json()
            return {
                "step": "api_connectivity",
                "ok": True,
                "key_preview": key_preview,
                "test_city": "Karachi,PK",
                "temperature": data["main"]["temp"],
                "condition": data["weather"][0]["description"],
                "message": "Weather API is working correctly ✅"
            }
        elif resp.status_code == 401:
            return {
                "step": "api_key_validation",
                "ok": False,
                "status": 401,
                "error": "API key is invalid or unauthorized",
                "fix": "Verify OPENWEATHER_API_KEY value in Railway env vars"
            }
        else:
            return {
                "step": "api_connectivity",
                "ok": False,
                "status": resp.status_code,
                "error": resp.text[:200]
            }
    except Exception as e:
        return {
            "step": "network",
            "ok": False,
            "error": str(e),
            "fix": "Check Railway outbound network connectivity"
        }

# ====================================================
# 3. LIVE WEATHER — /weather/live?city=...
# ====================================================
@router.get("/live")
async def get_live_weather(city: str = Query(..., min_length=2)):
    """
    Get live weather with city normalization and caching.
    """
    search_city = normalize_city(city)
    api_key = settings.OPENWEATHER_API_KEY

    print(f"[WEATHER/LIVE] city='{city}' → normalized='{search_city}'")

    # Guard: missing API key
    if not api_key:
        logger.error("[WEATHER/LIVE] OPENWEATHER_API_KEY is missing!")
        print("[WEATHER/LIVE] ❌ OPENWEATHER_API_KEY not set in environment")
        return {
            "success": False,
            "message": "Weather service not configured (missing API key)",
            "data": None
        }

    # 1. Check Cache (15 min)
    try:
        cached = await weather_collection.find_one({
            "city": search_city,
            "type": "live",
            "timestamp": {"$gte": datetime.utcnow() - timedelta(minutes=15)}
        })
        if cached and "raw_data" in cached:
            print(f"[WEATHER/LIVE] ✅ Cache hit for '{search_city}'")
            return {"success": True, "source": "cache", "data": cached["raw_data"]}
    except Exception as e:
        logger.error(f"[WEATHER/LIVE] Cache error: {e}")

    # 2. Fetch from OpenWeather
    url = (
        f"https://api.openweathermap.org/data/2.5/weather"
        f"?q={search_city}&appid={api_key}&units=metric"
    )
    print(f"[WEATHER/LIVE] Fetching: {url}")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url)

        print(f"[WEATHER/LIVE] Status: {response.status_code}")
        print(f"[WEATHER/LIVE] Body: {response.text[:300]}")

        if response.status_code == 401:
            logger.error("[WEATHER/LIVE] API key rejected (401)")
            return {
                "success": False,
                "message": "Weather API key invalid — contact admin",
                "data": None
            }

        if response.status_code == 404:
            # Try without country code as fallback
            fallback_city = city.strip().title()
            fallback_url = (
                f"https://api.openweathermap.org/data/2.5/weather"
                f"?q={fallback_city}&appid={api_key}&units=metric"
            )
            print(f"[WEATHER/LIVE] 404 — retrying without ,PK: {fallback_url}")
            async with httpx.AsyncClient(timeout=10) as client:
                fallback_resp = await client.get(fallback_url)
            print(f"[WEATHER/LIVE] Fallback status: {fallback_resp.status_code}")

            if fallback_resp.status_code == 200:
                data = fallback_resp.json()
                await _cache_weather(search_city, data)
                return {"success": True, "data": data}

            return {
                "success": False,
                "message": f"Location '{city}' not found. Try a nearby major city.",
                "data": None
            }

        if response.status_code != 200:
            logger.error(f"[WEATHER/LIVE] Unexpected status {response.status_code}: {response.text[:200]}")
            return {
                "success": False,
                "message": f"Weather service error (HTTP {response.status_code})",
                "data": None
            }

        data = response.json()
        await _cache_weather(search_city, data)

        print(f"[WEATHER/LIVE] ✅ Success: {data.get('name')} {data['main']['temp']}°C")
        return {"success": True, "data": data}

    except httpx.TimeoutException:
        logger.error("[WEATHER/LIVE] Request timed out")
        return {"success": False, "message": "Weather service timed out", "data": None}
    except Exception as e:
        logger.error(f"[WEATHER/LIVE] Exception: {e}", exc_info=True)
        return {"success": False, "message": "Unexpected weather error", "data": None}


async def _cache_weather(city_key: str, data: dict):
    """Helper to upsert weather data into MongoDB cache."""
    try:
        await weather_collection.update_one(
            {"city": city_key, "type": "live"},
            {"$set": {"raw_data": data, "timestamp": datetime.utcnow()}},
            upsert=True
        )
    except Exception as e:
        logger.error(f"[WEATHER/LIVE] Cache write failed: {e}")


# ====================================================
# 4. FORECAST — /weather/forecast?city=...
# ====================================================
@router.get("/forecast")
async def get_forecast(city: str = Query(..., min_length=2)):
    """
    5-day forecast with normalization and safe error handling.
    """
    search_city = normalize_city(city)
    api_key = settings.OPENWEATHER_API_KEY

    print(f"[WEATHER/FORECAST] city='{city}' → normalized='{search_city}'")

    if not api_key:
        print("[WEATHER/FORECAST] ❌ OPENWEATHER_API_KEY not set")
        return {"success": False, "message": "Weather service not configured", "data": None}

    url = (
        f"https://api.openweathermap.org/data/2.5/forecast"
        f"?q={search_city}&appid={api_key}&units=metric"
    )
    print(f"[WEATHER/FORECAST] Fetching: {url}")

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url)

        print(f"[WEATHER/FORECAST] Status: {response.status_code}")

        if response.status_code == 401:
            return {"success": False, "message": "Weather API key invalid", "data": None}

        if response.status_code == 404:
            return {
                "success": False,
                "message": f"Forecast not available for '{city}'",
                "data": None
            }

        if response.status_code != 200:
            return {
                "success": False,
                "message": f"Forecast service error (HTTP {response.status_code})",
                "data": None
            }

        data = response.json()
        return {"success": True, "forecast": data}

    except httpx.TimeoutException:
        return {"success": False, "message": "Forecast service timed out", "data": None}
    except Exception as e:
        logger.error(f"[WEATHER/FORECAST] Exception: {e}", exc_info=True)
        return {"success": False, "message": "Unexpected forecast error", "data": None}


# ====================================================
# 1. CITY NORMALIZATION
# ====================================================
CITY_MAPPINGS = {
    "Hunza": "Karimabad,PK",
    "Hunza Valley": "Karimabad,PK",
    "Skardu": "Skardu,PK",
    "Fairy Meadows": "Gilgit,PK",
    "Kashmir": "Muzaffarabad,PK",
    "Swat": "Mingora,PK",
    "Naran": "Naran,PK",
    "Kaghan": "Kaghan,PK"
}

def normalize_city(city: str) -> str:
    if not city:
        return ""
    stripped = city.strip().title()
    return CITY_MAPPINGS.get(stripped, f"{stripped},PK")

# ====================================================
# 2. ENDPOINTS
# ====================================================

@router.get("/live")
async def get_live_weather(city: str = Query(..., min_length=2)):
    """
    Get live weather with normalization and safe error handling.
    """
    search_city = normalize_city(city)
    api_key = settings.OPENWEATHER_API_KEY
    
    # 1. Check Cache (15 min)
    try:
        cached = await weather_collection.find_one({
            "city": search_city,
            "type": "live",
            "timestamp": {"$gte": datetime.utcnow() - timedelta(minutes=15)}
        })
        if cached:
            return {
                "success": True,
                "source": "cache",
                "data": cached["raw_data"]
            }
    except Exception as e:
        logger.error(f"Cache error: {e}")

    # 2. Fetch from OpenWeather
    url = f"https://api.openweathermap.org/data/2.5/weather?q={search_city}&appid={api_key}&units=metric"
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url)
            
        if response.status_code == 404:
            return {
                "success": False,
                "message": f"Location '{city}' not recognized by weather service",
                "data": None
            }
            
        if response.status_code != 200:
            logger.error(f"Weather API Error {response.status_code}: {response.text}")
            return {
                "success": False,
                "message": "Weather service currently unavailable",
                "data": None
            }

        data = response.json()
        
        # 3. Update Cache
        await weather_collection.update_one(
            {"city": search_city, "type": "live"},
            {"$set": {"raw_data": data, "timestamp": datetime.utcnow()}},
            upsert=True
        )

        return {
            "success": True,
            "data": data
        }

    except Exception as e:
        logger.error(f"Weather fetch exception: {e}")
        return {
            "success": False,
            "message": "Failed to connect to weather service",
            "data": None
        }

@router.get("/forecast")
async def get_forecast(city: str = Query(..., min_length=2)):
    """
    Get 5-day forecast with normalization and safe error handling.
    """
    search_city = normalize_city(city)
    api_key = settings.OPENWEATHER_API_KEY

    url = f"https://api.openweathermap.org/data/2.5/forecast?q={search_city}&appid={api_key}&units=metric"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url)

        if response.status_code == 404:
            return {
                "success": False,
                "message": f"Forecast unavailable for '{city}'",
                "data": None
            }

        if response.status_code != 200:
            return {
                "success": False,
                "message": "Forecast service currently unavailable",
                "data": None
            }

        data = response.json()
        return {
            "success": True,
            "forecast": data
        }

    except Exception as e:
        logger.error(f"Forecast fetch exception: {e}")
        return {
            "success": False,
            "message": "Failed to connect to forecast service",
            "data": None
        }