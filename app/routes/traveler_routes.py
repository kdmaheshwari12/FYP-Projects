# app/routes/traveler_routes.py
from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer
from app.db.mongodb import (
    users_collection,
    itineraries_collection,
    preferences_collection,
    messages_collection
)
from app.core.security import decode_access_token
from app.middleware.auth_middleware import get_current_active_user
from bson import ObjectId
import datetime
import random
import hashlib
import json , re
import os
import uuid
from dotenv import load_dotenv
from app.LLM.main import generate_itinerary_llm
from app.core.validation import validate_string, ValidationError
from app.schemas.itinerary_schema import ItineraryRequest
import logging

logger = logging.getLogger(__name__)
load_dotenv()

router = APIRouter(prefix="/traveler", tags=["Traveler"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="users/login")

from groq import Groq
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# Pakistan cities for validation
PAKISTAN_CITIES = [
    "islamabad", "rawalpindi", "lahore", "karachi", "quetta",
    "peshawar", "skardu", "hunza", "gilgit", "kashmir",
    "swat", "murree", "multan", "bahawalpur", "gwadar",
    "chitral", "hyderabad", "faisalabad", "sialkot"
]

# --------------------------
# HYBRID CITY DETECTION (B4)
# --------------------------
async def detect_city_hybrid(message: str):
    msg = message.lower()

    # STEP 1: REGEX TOKENIZE
    words = re.findall(r"[a-zA-Z]+", msg)

    # STEP 2: DIRECT MATCH AGAINST PAKISTAN CITIES
    for w in words:
        if w in PAKISTAN_CITIES:
            print("DEBUG: Regex detected city =", w)
            return w

    # STEP 3: LLM FALLBACK
    print("DEBUG: Regex failed. Using LLM city extraction...")

    llm_prompt = f"""
    Extract ONLY the Pakistan city mentioned in this message.
    If the city is outside Pakistan or none exists, reply: none

    Message: "{message}"
    """

    res = groq_client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": llm_prompt}]
    )

    city = res.choices[0].message.content.strip().lower()
    print("DEBUG: LLM extracted city =", city)

    if city in PAKISTAN_CITIES:
        return city

    return None


# -------------------------------------------
# 🔵 LOGGING FUNCTION (Message saving)
# -------------------------------------------
async def log_message(
    conversationId: str,
    senderId,
    receiverId,
    senderType: str,
    receiverType: str,
    text: str,
    meta=None
):
    await messages_collection.insert_one({
        "conversationId": conversationId,
        "senderId": senderId,
        "receiverId": receiverId,
        "senderType": senderType,
        "receiverType": receiverType,
        "message": text,
        "timestamp": datetime.datetime.now(datetime.timezone.utc),
        "meta": meta or []
    })


# -------------------------------------------
# 🔵 CHATBOT ROUTE (UPDATED WITH VALIDATION)
# -------------------------------------------
@router.post("/chat")
async def travel_chatbot(message: dict, current_user: dict = Depends(get_current_active_user)):
    """
    Chat endpoint with message validation and sanitization.
    
    Body:
    {
      "message": "I want to visit Hunza Valley"
    }
    """
    email = current_user["email"]
    
    # ========== MESSAGE VALIDATION & SANITIZATION ==========
    user_msg_raw = message.get("message")
    if user_msg_raw is None:
        logger.warning(f"Chat request missing 'message' key. Received keys: {list(message.keys())}")
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "message": "Required field 'message' is missing in request body."
            }
        )

    try:
        user_msg = validate_string(
            user_msg_raw,
            "message",
            allow_empty=False,
            min_length=1,
            max_length=5000
        )
    except ValidationError as e:
        logger.warning(f"Chat message validation failed: {e.message}")
        raise HTTPException(
            status_code=422,
            detail={"error": e.message, "field": "message", "code": e.code}
        )
    
    msg_lower = user_msg.lower()

    # Fetch user to get userID
    try:
        user = await users_collection.find_one({"email": email})
        if not user:
            logger.warning(f"Chat attempt by non-existent user: {email}")
            return JSONResponse(
                status_code=404,
                content={"success": False, "message": "User profile not found"}
            )

        user_id = user["_id"]
        conversationId = f"conv-{user_id}"   # persistent conversation ID

        # -------------------------------------------
        # 🔵 Log USER MESSAGE (sanitized)
        # -------------------------------------------
        await log_message(
            conversationId=conversationId,
            senderId=user_id,
            receiverId=None,
            senderType="traveler",
            receiverType="ai",
            text=user_msg
        )
    except Exception as e:
        logger.error(f"Error initializing chat for {email}: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "Could not initialize chat session"}
        )

    try:
        # 0️⃣ GREETINGS
        greetings = ["hi", "hello", "hey", "salam", "assalamualaikum",
                     "good morning", "good evening"]

        if msg_lower in greetings or any(msg_lower.startswith(g) for g in greetings):
            bot_reply = "Hello! 👋 How can I help you with your travel planning today?"
            # Log bot reply
            await log_message(
                conversationId=conversationId,
                senderId=None,
                receiverId=user_id,
                senderType="ai",
                receiverType="traveler",
                text=bot_reply
            )
            logger.info(f"[{conversationId}] ✅ AI reply generated (Greeting)")
            return {
                "success": True,
                "reply": bot_reply
            }

        # If not a greeting, proceed to AI logic...
        # 1️⃣ FETCH USER'S STORED ITINERARIES
        itineraries = await itineraries_collection.find({"user_email": email}).to_list(None)
        known_cities = [it["destination"].lower() for it in itineraries]

        # 2️⃣ DETECT IF USER WANTS MODIFICATION
        modification_keywords = [
            "shorten", "modify", "fix", "adjust", "update",
            "change", "edit", "remove", "replace", "add",
            "revise", "rearrange"
        ]
        is_modification = any(kw in msg_lower for kw in modification_keywords)

        # 3️⃣ HYBRID CITY DETECTION
        detected_city = await detect_city_hybrid(user_msg)

        # --------------------------
        # MODE 1 — GENERAL TRAVEL INFO
        # --------------------------
        if not is_modification:

            system_prompt = """
You are a Pakistan-specific travel assistant.

RULES:
1. Only answer travel-related questions about Pakistan.
2. If the city is outside Pakistan, reply:
   "Sorry, I can only provide travel information for places inside Pakistan."
3. Do NOT mention itineraries in this mode.
4. Respond naturally and keep answers short.
"""

            response = groq_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg}
                ]
            )

            bot_reply = response.choices[0].message.content
            logger.info(f"[{conversationId}] ✅ AI General Reply generated")

            # Log bot reply
            await log_message(
                conversationId=conversationId,
                senderId=None,
                receiverId=user_id,
                senderType="ai",
                receiverType="traveler",
                text=bot_reply
            )

            return {
                "success": True,
                "reply": bot_reply
            }

        # --------------------------
        # MODE 2 — ITINERARY MODIFICATION
        # --------------------------
        if not detected_city:
            bot_reply = "Please specify a Pakistan city for the itinerary you want to modify."

            await log_message(
                conversationId=conversationId,
                senderId=None,
                receiverId=user_id,
                senderType="ai",
                receiverType="traveler",
                text=bot_reply
            )
            return {
                "success": True,
                "reply": bot_reply
            }

        # Check if itinerary exists
        itinerary = next((it for it in itineraries if it["destination"].lower() == detected_city), None)

        if not itinerary:
            bot_reply = f"You do not have an itinerary for {detected_city.capitalize()}. Please generate one first."

            await log_message(conversationId, None, user_id, "ai", "traveler", bot_reply)

            return {
                "success": True,
                "reply": bot_reply
            }

        itinerary_days = itinerary["itinerary_days"]
        itinerary_json = json.dumps(itinerary_days)

        # LLM Prompt
        system_prompt = f"""
You are an itinerary editor for {detected_city.capitalize()}.

RULES:
- Only modify activities inside existing days.
- Do NOT add or remove days.
- No empty fields.
- No duplicates.
- Return ONLY valid JSON.
"""

        user_prompt = f"""
Existing itinerary:
{itinerary_json}

User request:
"{user_msg}"
"""

        res = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )

        ai_raw = res.choices[0].message.content

        try:
            ai_json = json.loads(ai_raw)
        except:
            bot_reply = "Sorry, I couldn't process that request. Please try again."

            await log_message(conversationId, None, user_id, "ai", "traveler", bot_reply)

            return {
                "success": True,
                "reply": bot_reply
            }

        # Fallback responses
        if ai_json.get("operation") == "chat":
            bot_reply = ai_json["reply"]

            await log_message(conversationId, None, user_id, "ai", "traveler", bot_reply)

            return {
                "success": True,
                "reply": bot_reply
            }

        # Apply modification
        updated = ai_json.get("updated_itinerary", [])

        # Validation
        if len(updated) != len(itinerary_days):
            bot_reply = "Error: Number of days cannot be changed."

            await log_message(conversationId, None, user_id, "ai", "traveler", bot_reply)

            return {
                "success": True,
                "reply": bot_reply
            }

        for day in updated:
            seen = set()
            for item in day["schedule"]:
                if not item.get("time") or not item.get("activity"):
                    bot_reply = "Error: Time and activity must not be empty."

                    await log_message(conversationId, None, user_id, "ai", "traveler", bot_reply)

                    return {
                "success": True,
                "reply": bot_reply
            }

                if item["activity"] in seen:
                    bot_reply = "Error: Duplicate activities found."

                    await log_message(conversationId, None, user_id, "ai", "traveler", bot_reply)

                    return {
                "success": True,
                "reply": bot_reply
            }

                seen.add(item["activity"])

        # Save updated itinerary
        await itineraries_collection.update_one(
            {"_id": itinerary["_id"]},
            {"$set": {"itinerary_days": updated}}
        )

        bot_reply = f"Your {detected_city.capitalize()} itinerary has been updated! 🎉"

        # Log success message
        await log_message(conversationId, None, user_id, "ai", "traveler", bot_reply, meta=updated)

        return {
            "success": True,
            "reply": bot_reply,
            "updated_itinerary": updated
        }
    except Exception as e:
        logger.error(f"[{conversationId}] 💥 Error in chatbot: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "AI service encountered an error. Please try again."
            }
        )


# Simple global cache for suggested itineraries
SUGGESTED_CACHE = {"data": [], "timestamp": datetime.datetime.min}
CACHE_TTL = datetime.timedelta(minutes=10)

# Helper to safely serialize any MongoDB document
def _serialize_doc(doc: dict) -> dict:
    """Convert all ObjectId fields in a document to strings."""
    for key, value in doc.items():
        if isinstance(value, ObjectId):
            doc[key] = str(value)
        elif isinstance(value, list):
            doc[key] = [
                _serialize_doc(item) if isinstance(item, dict) else
                str(item) if isinstance(item, ObjectId) else item
                for item in value
            ]
        elif isinstance(value, dict):
            doc[key] = _serialize_doc(value)
    return doc


# 1️⃣ Traveler Dashboard
@router.get("/dashboard")
async def get_dashboard(current_user: dict = Depends(get_current_active_user)):
    """Get traveler dashboard data (My Trips + Suggested Itineraries)"""
    global SUGGESTED_CACHE
    email = current_user["email"]

    try:
        # Fetch My Trips
        my_trips = await itineraries_collection.find({"user_email": email}).to_list(None)
        for trip in my_trips:
            _serialize_doc(trip)

        # Fetch/Cache suggested itineraries
        now = datetime.datetime.utcnow()
        if not SUGGESTED_CACHE["data"] or (now - SUGGESTED_CACHE["timestamp"]) > CACHE_TTL:
            try:
                suggested = await itineraries_collection.aggregate([{"$sample": {"size": 3}}]).to_list(None)
                for s in suggested:
                    _serialize_doc(s)
                SUGGESTED_CACHE = {"data": suggested, "timestamp": now}
                logger.info("🆕 Dashboard suggested trips cache REFRESHED")
            except Exception as agg_err:
                logger.warning(f"⚠️ $sample aggregation failed (empty collection?): {agg_err}")
                SUGGESTED_CACHE = {"data": [], "timestamp": now}
        else:
            logger.debug("⚡ Dashboard suggested trips cache HIT")

        return {
            "message": "Traveler dashboard loaded successfully",
            "my_trips": my_trips,
            "suggested_trips": SUGGESTED_CACHE["data"],
        }
    except Exception as e:
        logger.error(f"💥 Dashboard error: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"Dashboard loading failed: {str(e)}"}
        )


# 2️⃣ Save Preferences
@router.post("/preferences")
async def save_preferences(preferences: dict, current_user: dict = Depends(get_current_active_user)):
    """Save user preferences temporarily before AI generation"""
    email = current_user["email"]

    # Remove previous preferences for this user
    await preferences_collection.delete_many({"user_email": email})

    preferences["user_email"] = email
    preferences["created_at"] = datetime.datetime.now(datetime.timezone.utc)

    result = await preferences_collection.insert_one(preferences)
    preferences["_id"] = str(result.inserted_id)

    return {"message": "Preferences saved successfully", "preferences": preferences}


# 3️⃣ Generate AI Itinerary
# Every generated itinerary is stored in the itineraries collection.
# Validation is handled entirely by the ItineraryRequest Pydantic schema
# BEFORE any AI/LLM code runs.
@router.post("/generate-itinerary")
async def generate_itinerary(
    preferences: ItineraryRequest,          # ← strict Pydantic schema
    current_user: dict = Depends(get_current_active_user)
):
    """
    Generate a personalized AI itinerary.

    Required fields (validated by Pydantic before this function runs):
      - destination        : non-empty string, 2–100 chars
      - departure_location : non-empty string, 2–100 chars
      - budget             : positive number > 0  (PKR)
      - duration_days      : integer 1–30
      - travel_style       : one of the TravelStyle enum values
      - interests          : optional list of strings

    Any missing / empty / invalid field returns HTTP 422 with a clear
    message BEFORE the LLM is called.
    """

    email = current_user["email"]
    request_id = f"GEN-{uuid.uuid4().hex[:8]}"
    logger.info(
        f"[{request_id}] 🤖 generate-itinerary | user={email} "
        f"dest='{preferences.destination}' days={preferences.duration_days} "
        f"budget={preferences.budget} style={preferences.travel_style}"
    )

    # ── Map budget (PKR number → low / moderate / high category) ─────────────
    raw_budget = preferences.budget
    if raw_budget < 20_000:
        budget_category = "low"
    elif raw_budget < 60_000:
        budget_category = "moderate"
    else:
        budget_category = "high"

    destination   = preferences.destination       # already stripped by schema
    duration      = preferences.duration_days
    interests     = preferences.resolved_interests
    travel_style  = preferences.travel_style.value

    # ── Duplicate prevention hash ─────────────────────────────────────────────
    hash_input = json.dumps({
        "user_email":   email,
        "destination":  destination.lower(),
        "duration":     duration,
        "budget":       budget_category,
        "interests":    sorted(interests),
        "travel_style": travel_style,
    }, sort_keys=True)
    unique_hash = hashlib.sha256(hash_input.encode()).hexdigest()

    existing = await itineraries_collection.find_one({"unique_hash": unique_hash})
    if existing:
        _serialize_doc(existing)
        logger.info(f"[{request_id}] 🔁 Returning cached itinerary")
        return {
            "success": True,
            "message": "Itinerary already existed — returning saved version.",
            "duplicate": True,
            "itinerary": existing,
        }

    # ── LLM call (runs in thread pool so async loop stays unblocked) ──────────
    import asyncio
    try:
        logger.info(f"[{request_id}] ⏳ Calling LLM for '{destination}' ({duration} days)...")
        llm_output = await asyncio.to_thread(
            generate_itinerary_llm,
            destination=destination,
            days=duration,
            budget=budget_category,
            interests=interests,
            departure_location=preferences.departure_location or "Not specified",
            travel_style=travel_style
        )
    except ValueError as e:
        # Catch specific ValueErrors (like NO_HOTELS)
        err_msg = str(e)
        if "NO_HOTELS" in err_msg:
            clean_msg = err_msg.split(":", 1)[1].strip() if ":" in err_msg else err_msg
            logger.warning(f"[{request_id}] ⚠️ {err_msg}")
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": clean_msg}
            )
        raise e # Let global handler take other ValueErrors

    except Exception as e:
        err_msg = str(e)
        logger.error(f"[{request_id}] 💥 LLM generation failed: {err_msg}", exc_info=True)
        
        # Decide status code based on error type
        status_code = 500
        clean_msg = "AI itinerary generation failed"
        
        if "EXTERNAL_SERVICE_UNAVAILABLE" in err_msg:
            status_code = 503
            clean_msg = "External travel service unavailable"
        elif "AI_GENERATION_FAILED" in err_msg:
            status_code = 500
            # Try to extract the actual reason if available
            if ":" in err_msg:
                clean_msg = err_msg.split(":", 1)[1].strip()
        else:
            clean_msg = f"Itinerary generation failed: {err_msg}"

        return JSONResponse(
            status_code=status_code,
            content={
                "success": False,
                "message": clean_msg,
            },
        )

    # ── Persist to MongoDB ─────────────────────────────────────────────────────
    itinerary_doc = {
        "user_email":         email,
        "destination":        destination,
        "departure_location": preferences.departure_location,
        "duration":           duration,
        "budget_pkr":         raw_budget,
        "budget":             budget_category,
        "interests":          interests,
        "travel_style":       travel_style,
        "itinerary_days":     llm_output,
        "created_at":         datetime.datetime.now(datetime.timezone.utc),
        "source":             "RAG AI Generator v2.0",
        "unique_hash":        unique_hash,
    }

    try:
        result = await itineraries_collection.insert_one(itinerary_doc)
        itinerary_doc["_id"] = str(result.inserted_id)
        _serialize_doc(itinerary_doc)
        logger.info(f"[{request_id}] ✅ Itinerary saved: {result.inserted_id}")
    except Exception as e:
        logger.error(f"[{request_id}] 💥 Failed to save itinerary: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "Failed to save itinerary"},
        )

    return {
        "success": True,
        "message": "AI itinerary generated successfully!",
        "duplicate": False,
        "itinerary": itinerary_doc,
    }

# 4️⃣ View Specific Itinerary
@router.get("/itinerary/{itinerary_id}")
async def get_itinerary(itinerary_id: str, current_user: dict = Depends(get_current_active_user)):
    """Fetch a specific itinerary by its ID"""
    email = current_user["email"]

    try:
        try:
            obj_id = ObjectId(itinerary_id)
        except:
            raise HTTPException(status_code=400, detail="Invalid itinerary ID format")

        itinerary = await itineraries_collection.find_one({"_id": obj_id})
        if not itinerary:
            raise HTTPException(status_code=404, detail="Itinerary not found")

        itinerary["_id"] = str(itinerary["_id"])
        return itinerary
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error fetching itinerary {itinerary_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


# 5️⃣ Update Itinerary
@router.put("/itinerary/{itinerary_id}/update")
async def update_itinerary(
    itinerary_id: str,
    updates: dict,
    current_user: dict = Depends(get_current_active_user)
):
    """Update an itinerary (e.g., after AI modifies it)."""
    try:
        obj_id = ObjectId(itinerary_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid itinerary ID format")

    result = await itineraries_collection.update_one(
        {"_id": obj_id}, {"$set": updates}
    )

    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Itinerary not found or nothing to update")

    return {"success": True, "message": "Itinerary updated successfully"}


# 6️⃣ Suggested Itineraries - suggest top5 itineraries on dashboard
@router.get("/suggested-itineraries")
async def get_suggested_itineraries():
    """
    Suggest itineraries from previously AI-generated trips.
    Picks a few random ones from the database (no hardcoding).
    """
    total_itineraries = await itineraries_collection.count_documents({})

    if total_itineraries == 0:
        return {"message": "No itineraries available yet. Generate one to get started!", "suggested_itineraries": []}

    # Randomly sample up to 5 itineraries from your DB
    sample_size = min(5, total_itineraries)
    suggested = await itineraries_collection.aggregate([{"$sample": {"size": sample_size}}]).to_list(None)
    
    for s in suggested:
        s["_id"] = str(s["_id"])

    return {"suggested_itineraries": suggested}