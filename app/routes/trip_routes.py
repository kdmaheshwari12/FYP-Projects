from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from bson import ObjectId
from datetime import datetime, timedelta
import logging
import uuid
from app.core.config import settings
from app.db.mongodb import trips_collection, users_collection, itineraries_collection, broker_itineraries_collection
from app.routes.auth_routes import get_current_user_obj
from app.schemas.trip_schema import TripCreate
from app.core.validation import (
    ValidationErrorResponse,
)

router = APIRouter(prefix="/trips", tags=["Trips"])

logger = logging.getLogger(__name__)

# ============================================================
# 1️⃣ CREATE TRIP (REUSE SAFE)
# ============================================================
@router.post("/", status_code=201)
async def create_trip(
    trip_data: TripCreate,
    current_user: dict = Depends(get_current_user_obj)
):
    """
    Create or reuse a trip with validation.
    """
    request_id = f"TRIP-{uuid.uuid4().hex[:8]}"
    logger.info(f"[{request_id}] 🆕 CREATE_TRIP attempt | User: {current_user.get('email')}")
    
    try:
        # 2️⃣ Validate and convert IDs
        itinerary_obj_id = None
        if trip_data.itinerary_id:
            try:
                itinerary_obj_id = ObjectId(trip_data.itinerary_id)
            except Exception:
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "message": "Invalid itinerary_id format"}
                )

        broker_obj_id = None
        if trip_data.broker_id:
            try:
                broker_obj_id = ObjectId(trip_data.broker_id)
            except Exception:
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "message": "Invalid broker_id format"}
                )

        # 3️⃣ Check for trip re-use
        if itinerary_obj_id:
            existing_trip = await trips_collection.find_one({
                "user_id": ObjectId(current_user["_id"]),
                "itinerary_source_id": itinerary_obj_id,
                "trip_type": trip_data.trip_type,
            })

            if existing_trip:
                logger.info(f"[{request_id}] 🔁 Trip reused: {existing_trip['_id']}")
                
                if not existing_trip.get("broker_id") and broker_obj_id:
                    await trips_collection.update_one(
                        {"_id": existing_trip["_id"]},
                        {"$set": {
                            "broker_id": broker_obj_id,
                            "status": "chatting"
                        }}
                    )
                    existing_trip["status"] = "chatting"

                return {
                    "success": True,
                    "message": "Trip details retrieved",
                    "trip_id": str(existing_trip["_id"]),
                    "reused": True,
                    "status": existing_trip.get("status", "draft")
                }

        # 4️⃣ Create new trip document
        start_dt = datetime.combine(trip_data.start_date, datetime.min.time())
        end_dt = datetime.combine(trip_data.end_date, datetime.min.time())

        trip_doc = {
            "user_id": ObjectId(current_user["_id"]),
            "trip_type": trip_data.trip_type,
            "itinerary_source_id": itinerary_obj_id,
            "broker_id": broker_obj_id,
            "status": "chatting" if broker_obj_id else "draft",
            "destination": trip_data.destination,
            "departure_location": trip_data.departure_location,
            "start_date": start_dt,
            "end_date": end_dt,
            "budget": trip_data.budget,
            "travel_style": trip_data.travel_style.value,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }

        result = await trips_collection.insert_one(trip_doc)
        logger.info(f"[{request_id}] ✅ New trip created: {result.inserted_id}")

        return {
            "success": True,
            "message": "Trip created successfully",
            "trip_id": str(result.inserted_id),
            "reused": False,
            "status": trip_doc["status"]
        }

    except Exception as e:
        logger.error(f"[{request_id}] 💥 CRITICAL ERROR: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "A critical server error occurred while creating your trip.",
                "debug_info": str(e) if settings.DEBUG else None
            }
        )
    except Exception as e:
        logger.error(f"[{request_id}] 💥 CRITICAL ERROR: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "A critical server error occurred while creating your trip.",
                "debug_info": str(e) if settings.DEBUG else None
            }
        )

#------------------------------------------------------------
#Route for showing detailed itinerary in broker modal whether it's AI or BROKER
#------------------------------------------------------------
@router.get("/{trip_id}/itinerary-context")
async def get_trip_itinerary_context(
    trip_id: str,
    current_user: dict = Depends(get_current_user_obj)
):
    # 1️⃣ Validate trip_id
    try:
        trip_obj_id = ObjectId(trip_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid trip_id format")

    # 2️⃣ Fetch trip
    trip = await trips_collection.find_one({"_id": trip_obj_id})

    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    # 2️⃣ Access control (traveler OR broker)
    user_id = str(trip["user_id"])
    broker_id = str(trip.get("broker_id")) if trip.get("broker_id") else None

    if current_user["_id"] not in [user_id, broker_id]:
        raise HTTPException(status_code=403, detail="Not allowed")

    trip_type = trip.get("trip_type")
    source_id = trip.get("itinerary_source_id")

    if not source_id:
        raise HTTPException(status_code=400, detail="Trip has no itinerary source")

    # 3️⃣ Fetch itinerary based on trip type
    if trip_type in ["ai_self", "ai_broker"]:
        itinerary = await itineraries_collection.find_one(
            {"_id": ObjectId(source_id)}
        )
        source = "ai"

    elif trip_type == "broker":
        itinerary = await broker_itineraries_collection.find_one(
            {"_id": ObjectId(source_id)}
        )
        source = "broker"

    else:
        raise HTTPException(status_code=400, detail="Invalid trip type")

    if not itinerary:
        raise HTTPException(status_code=404, detail="Itinerary not found")

    # 4️⃣ Normalize ObjectIds
    itinerary["_id"] = str(itinerary["_id"])

    if itinerary.get("brokerId"):
        itinerary["brokerId"] = str(itinerary["brokerId"])

    return {
        "source": source,              # "ai" or "broker"
        "tripType": trip_type,
        "itinerary": itinerary
    }

# ============================================================
# 2️⃣ GET MY TRIPS (USER DASHBOARD)
# ============================================================
@router.get("/my")
async def get_my_trips(
    current_user: dict = Depends(get_current_user_obj)
):
    """
    Fetch all trips created by the logged-in user.
    Used for:
    - Active Trips
    - Past Trips
    """

    trips = await trips_collection.find(
        {"user_id": ObjectId(current_user["_id"])}
    ).sort("created_at", -1).to_list(None)

    response = []

    for t in trips:
        response.append({
            "trip_id": str(t["_id"]),
            "trip_type": t.get("trip_type"),
            "status": t.get("status"),
            "destination": t.get("destination"),
            "budget": t.get("budget"),
            "broker_id": str(t["broker_id"]) if t.get("broker_id") else None,
            "created_at": t.get("created_at")
        })

    return {
        "count": len(response),
        "trips": response
    }


# ============================================================
# 3️⃣ GET TRIP BY ID
# ============================================================
@router.get("/{trip_id}")
async def get_trip_by_id(
    trip_id: str,
    current_user: dict = Depends(get_current_user_obj)
):
    """
    Fetch a single trip.
    Used for:
    - Chat screen
    - Trip details
    - Weather alerts
    """

    try:
        trip_obj_id = ObjectId(trip_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid trip_id")

    trip = await trips_collection.find_one(
        {
            "_id": trip_obj_id,
            "user_id": ObjectId(current_user["_id"])
        }
    )

    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    return {
        "trip_id": str(trip["_id"]),
        "trip_type": trip.get("trip_type"),
        "status": trip.get("status"),
        "destination": trip.get("destination"),
        "budget": trip.get("budget"),
        "itinerary_source_id": str(trip["itinerary_source_id"]),
        "broker_id": str(trip["broker_id"]) if trip.get("broker_id") else None,
        "chat_id": trip.get("chat_id"),
        "created_at": trip.get("created_at"),
        "updated_at": trip.get("updated_at")
    }

#=================================================================
#route for chat access - traveler and broker used by chat screen
#=================================================================
@router.get("/{trip_id}/chat-context")
async def get_trip_for_chat(
    trip_id: str,
    current_user: dict = Depends(get_current_user_obj)
):
    trip = await trips_collection.find_one(
        {"_id": ObjectId(trip_id)}
    )

    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    user_id = str(trip["user_id"])
    broker_id = str(trip.get("broker_id"))

    if (
        current_user["_id"] != user_id and
        current_user["_id"] != broker_id
    ):
        raise HTTPException(status_code=403, detail="Not allowed")

    trip["_id"] = str(trip["_id"])
    trip["user_id"] = str(trip["user_id"])
    if trip.get("broker_id"):
        trip["broker_id"] = str(trip["broker_id"])
    
    if trip.get("itinerary_source_id") and isinstance(trip["itinerary_source_id"], ObjectId):
        trip["itinerary_source_id"] = str(trip["itinerary_source_id"])

    if trip.get("chat_id") and isinstance(trip["chat_id"], ObjectId):
        trip["chat_id"] = str(trip["chat_id"])
    return trip


@router.get("/{trip_id}/chat-peer")
async def get_trip_chat_peer(
    trip_id: str,
    current_user: dict = Depends(get_current_user_obj)
):
    """
    Returns the OTHER user's CometChat UID for this trip
    """
    request_id = f"PEER-{uuid.uuid4().hex[:6]}"
    logger.info(f"[{request_id}] 🚀 START GET_CHAT_PEER | trip_id: {trip_id}")

    try:
        # 1️⃣ Validate trip_id
        try:
            logger.info(f"[{request_id}] 🔍 Validating trip_id: {trip_id}")
            trip_obj_id = ObjectId(trip_id)
        except Exception as e:
            logger.warning(f"[{request_id}] ❌ Invalid trip_id format: {trip_id}. Error: {str(e)}")
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Invalid trip_id format"}
            )

        # 2️⃣ Fetch trip
        logger.info(f"[{request_id}] 🔍 Fetching trip from MongoDB...")
        trip = await trips_collection.find_one({"_id": trip_obj_id})
        if not trip:
            logger.warning(f"[{request_id}] ❌ Trip not found in DB: {trip_id}")
            return JSONResponse(
                status_code=404,
                content={"success": False, "message": "Trip not found"}
            )

        current_user_id_raw = current_user["_id"]
        trip_user_id_raw = trip["user_id"]
        trip_broker_id_raw = trip.get("broker_id")

        logger.info(f"[{request_id}] 🎫 Trip Details: user_id={trip_user_id_raw} ({type(trip_user_id_raw)}), broker_id={trip_broker_id_raw} ({type(trip_broker_id_raw)})")
        logger.info(f"[{request_id}] 👤 Current User: {current_user_id_raw} ({type(current_user_id_raw)})")

        # Normalize to strings for comparison
        current_user_id = str(current_user_id_raw)
        trip_user_id = str(trip_user_id_raw)
        trip_broker_id = str(trip_broker_id_raw) if trip_broker_id_raw else None

        # 3️⃣ Determine peer
        if trip_user_id == current_user_id:
            logger.info(f"[{request_id}] 👤 Caller is Traveler")
            if not trip_broker_id:
                logger.warning(f"[{request_id}] ❌ No broker assigned to trip {trip_id}")
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "message": "This trip does not have an assigned broker yet."}
                )
            peer_id = trip_broker_id
            peer_role = "broker"
        elif trip_broker_id == current_user_id:
            logger.info(f"[{request_id}] 👤 Caller is Broker")
            peer_id = trip_user_id
            peer_role = "traveler"
        else:
            logger.warning(f"[{request_id}] ❌ User {current_user_id} is not part of trip {trip_id} (user_id={trip_user_id}, broker_id={trip_broker_id})")
            return JSONResponse(
                status_code=403,
                content={"success": False, "message": "You are not authorized to access chat for this trip"}
            )

        # 4️⃣ Fetch peer details
        logger.info(f"[{request_id}] 🔍 Fetching peer user details from MongoDB (ID: {peer_id})...")
        try:
            peer_user = await users_collection.find_one(
                {"_id": ObjectId(peer_id)},
                {"full_name": 1, "name": 1, "org_name": 1}
            )
        except Exception as db_err:
            logger.error(f"[{request_id}] ❌ DB Error fetching peer: {str(db_err)}")
            raise db_err

        if peer_user:
            peer_name = (
                peer_user.get("full_name") 
                or peer_user.get("org_name") 
                or peer_user.get("name") 
                or "User"
            )
            logger.info(f"[{request_id}] ✅ Found peer: {peer_name}")
        else:
            peer_name = "User"
            logger.warning(f"[{request_id}] ⚠️ Peer user {peer_id} not found in database")

        logger.info(f"[{request_id}] ✨ SUCCESS: peerUid={peer_id}, peerRole={peer_role}")
        return {
            "success": True,
            "peerUid": str(peer_id),
            "peerRole": peer_role,
            "peerName": peer_name
        }

    except Exception as e:
        logger.error(f"[{request_id}] 💥 FATAL EXCEPTION in get_trip_chat_peer: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False, 
                "message": "Internal server error fetching chat participant",
                "debug_info": f"{type(e).__name__}: {str(e)}"
            }
        )

@router.patch("/{trip_id}/activate")
async def activate_trip(
    trip_id: str,
    current_user: dict = Depends(get_current_user_obj),
):
    # Generate a unique request ID for tracing
    request_id = f"TRIP-{uuid.uuid4().hex[:8]}"
    logger.info(f"[{request_id}] 🆕 ACTIVATE_TRIP attempt | Trip: {trip_id} | User: {current_user.get('email')}")

    # 1️⃣ Validate trip ID
    try:
        trip_obj_id = ObjectId(trip_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid trip_id")

    # 2️⃣ Fetch trip
    trip = await trips_collection.find_one({"_id": trip_obj_id})
    print("Fetched trip:", trip)

    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    # 3️⃣ Ensure caller is Traveler or Broker
    current_user_id = str(current_user.get("_id"))
    role = str(current_user.get("role", "")).lower()

    print(f"DEBUG: Current user role: {role}")
    print(f"DEBUG: Current user ID: {current_user_id}")
    print(f"DEBUG: Trip traveler ID: {str(trip.get('user_id'))}")
    print(f"DEBUG: Trip broker ID: {str(trip.get('broker_id'))}")

    # ROLE GATE
    if role not in ["traveler", "broker"]:
        raise HTTPException(
            status_code=403,
            detail="Only traveler or broker can activate the trip"
        )

    # OWNERSHIP GATE
    is_traveler = str(trip.get("user_id")) == current_user_id
    assigned_broker_id = trip.get("broker_id")
    is_assigned_broker = assigned_broker_id and str(assigned_broker_id) == current_user_id
    
    # Option 1 logic: Allow any broker if no broker is assigned yet
    can_pick_up = (role == "broker" and assigned_broker_id is None)

    if not (is_traveler or is_assigned_broker or can_pick_up):
        logger.warning(f"Unauthorized activation attempt: User {current_user_id} (role: {role}) for Trip {trip_id}")
        raise HTTPException(
            status_code=403,
            detail="You are not authorized to activate this trip"
        )

    # 4️⃣ Ensure correct state
    if trip["status"] not in ["chatting", "draft"]:
        raise HTTPException(
            status_code=400,
            detail=f"Trip cannot be activated from {trip['status']} state"
        )

    # ============================================================
    # 🔹 5️⃣ Get itinerary days (AI or Broker)
    # ============================================================
    if trip["trip_type"] in ["ai_self", "ai_broker"]:
        itinerary = await itineraries_collection.find_one(
            {"_id": trip["itinerary_source_id"]}
        )
    else:
        itinerary = await broker_itineraries_collection.find_one(
            {"_id": trip["itinerary_source_id"]}
        )

    if not itinerary:
        # Fallback if itinerary is missing (since we made it optional during trip creation)
        days = 3
    else:
        # supports both structures (AI: duration, Broker: days)
        days = itinerary.get("duration") or itinerary.get("duration_days") or 1

    # ============================================================
    # 🔹 6️⃣ Calculate dates
    # ============================================================
    start_date = datetime.utcnow()
    end_date = start_date + timedelta(days=days + 2)
    grace_end_date = end_date + timedelta(days=4)

    # ============================================================
    # 🔹 7️⃣ Update trip (FULL STATE INIT)
    # ============================================================
    update_data = {
        "status": "active",
        "start_date": start_date,
        "end_date": end_date,
        "grace_end_date": grace_end_date,

        # 🔥 Completion system fields
        "traveler_completed": False,
        "broker_completed": False,
        "completion_requested_at": None,
        "completed_at": None,

        "updated_at": datetime.utcnow()
    }

    # If a broker is taking an unassigned trip, assign them now
    if role == "broker" and assigned_broker_id is None:
        logger.info(f"[{request_id}] 🤝 Broker {current_user_id} picking up trip {trip_id}")
        update_data["broker_id"] = ObjectId(current_user_id)

    await trips_collection.update_one(
        {"_id": trip_obj_id},
        {"$set": update_data}
    )

    # 8️⃣ Fetch updated trip
    updated_trip = await trips_collection.find_one({"_id": trip_obj_id})

    # 🔹 Normalize ObjectIds
    updated_trip["_id"] = str(updated_trip["_id"])
    updated_trip["user_id"] = str(updated_trip["user_id"])

    if updated_trip.get("broker_id"):
        updated_trip["broker_id"] = str(updated_trip["broker_id"])

    if updated_trip.get("itinerary_source_id"):
        updated_trip["itinerary_source_id"] = str(updated_trip["itinerary_source_id"])

    print("✅ Trip activated successfully")

    return {
        "message": "Trip activated successfully",
        "trip": updated_trip
    }

@router.get("/active/current")
async def get_current_active_trip(
    current_user: dict = Depends(get_current_user_obj)
):
    try:
        user_id = current_user.get("_id")
        user_role = current_user.get("role")
        logger.info(f"🔍 Checking active trip for user: {user_id} (role: {user_role})")

        if user_role != "traveler":
            raise HTTPException(status_code=403, detail="Only travelers allowed")

        trip = await trips_collection.find_one(
            {
                "user_id": ObjectId(current_user["_id"]),
                "status": { "$in": ["active", "completion_pending"] }
            },
            sort=[
                ("start_date", -1),   # preferred
                ("created_at", -1)    # fallback
            ]
        )

        if not trip:
            return {"hasActiveTrip": False}

        return {
            "hasActiveTrip": True,
            "trip": {
                "trip_id": str(trip["_id"]),
                "trip_type": trip.get("trip_type"),
                "status": trip.get("status"),
                "destination": trip.get("destination"),
                "budget": trip.get("budget"),

                "start_date": trip.get("start_date") or trip.get("created_at"),

                "itinerary_source_id": (
                    str(trip["itinerary_source_id"])
                    if trip.get("itinerary_source_id")
                    else None
                ),

                "broker_id": (
                    str(trip["broker_id"])
                    if trip.get("broker_id")
                    else None
                ),

                "chat_id": (
                    str(trip["chat_id"])
                    if trip.get("chat_id")
                    else None
                ),

                "created_at": trip.get("created_at"),
                "updated_at": trip.get("updated_at"),
            }
        }
    except Exception as e:
        logger.error(f"💥 ERROR in get_current_active_trip: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")

@router.patch("/{trip_id}/complete")
async def complete_trip(
    trip_id: str,
    current_user: dict = Depends(get_current_user_obj)
):
    try:
        trip_obj_id = ObjectId(trip_id)
    except:
        raise HTTPException(status_code=400, detail="Invalid trip_id")

    trip = await trips_collection.find_one({"_id": trip_obj_id})

    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    user_id = ObjectId(current_user["_id"])

    # ❌ Only allow after trip ended
    if trip["status"] not in ["completion_pending", "active"]:
        raise HTTPException(
            status_code=400,
            detail="Trip not eligible for completion"
        )

    update_fields = {}

    # ============================================================
    # 🔹 CASE 1: AI SELF TRIP
    # ============================================================
    if trip["trip_type"] == "ai_self":

        if trip["user_id"] != user_id:
            raise HTTPException(status_code=403, detail="Not allowed")

        update_fields["status"] = "completed"
        update_fields["completed_at"] = datetime.utcnow()

        await trips_collection.update_one(
            {"_id": trip_obj_id},
            {"$set": update_fields}
        )

        return {"message": "Trip completed successfully"}

    # ============================================================
    # 🔹 CASE 2: BROKER TRIP (DUAL CONFIRMATION)
    # ============================================================

    if trip["user_id"] == user_id:
        # Traveler clicks
        update_fields["traveler_completed"] = True

    elif trip.get("broker_id") == user_id:
        # Broker clicks
        update_fields["broker_completed"] = True

    else:
        raise HTTPException(status_code=403, detail="Not part of trip")

    # Update current user's confirmation
    await trips_collection.update_one(
        {"_id": trip_obj_id},
        {"$set": update_fields}
    )

    # 🔄 Fetch updated trip
    updated_trip = await trips_collection.find_one({"_id": trip_obj_id})

    # ✅ Check both confirmations
    if updated_trip.get("traveler_completed") and updated_trip.get("broker_completed"):
        await trips_collection.update_one(
            {"_id": trip_obj_id},
            {"$set": {
                "status": "completed",
                "completed_at": datetime.utcnow()
            }}
        )

        return {"message": "Trip fully completed"}

    return {"message": "Completion recorded. Waiting for other party."}

@router.get("/completed/review-pending")
async def get_review_pending_trip(
    current_user: dict = Depends(get_current_user_obj)
):
    if current_user["role"] != "traveler":
        raise HTTPException(status_code=403, detail="Only travelers allowed")

    user_id = ObjectId(current_user["_id"])

    # 1️⃣ Get completed trips
    trips = await trips_collection.find(
        {
            "user_id": user_id,
            "status": "completed"
        }
    ).sort("updated_at", -1).to_list(None)

    if not trips:
        return {"hasReviewPending": False}

    # 2️⃣ Check if already reviewed
    from app.db.mongodb import broker_reviews_collection

    for trip in trips:
        itinerary_id = trip.get("itinerary_source_id")

        if not itinerary_id:
            continue

        existing_review = await broker_reviews_collection.find_one({
            "userId": user_id,
            "itineraryId": itinerary_id
        })

        if not existing_review:
            # 👇 FOUND trip needing review
            return {
                "hasReviewPending": True,
                "trip": {
                    "trip_id": str(trip["_id"]),
                    "destination": trip.get("destination"),
                    "itinerary_source_id": str(itinerary_id),
                    "updated_at": trip.get("updated_at"),
                }
            }

    return {"hasReviewPending": False}