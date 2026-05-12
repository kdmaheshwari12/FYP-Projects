from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import JSONResponse
import requests
import os
import uuid
from bson import ObjectId
import logging
from typing import Optional

from app.routes.auth_routes import get_current_user_obj
from app.services.cometchat_services import ensure_cometchat_user
from app.db.mongodb import trips_collection, users_collection

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["Chat"])

COMETCHAT_APP_ID = os.getenv("COMETCHAT_APP_ID")
COMETCHAT_REGION = os.getenv("COMETCHAT_REGION")
COMETCHAT_API_KEY = os.getenv("COMETCHAT_API_KEY")
COMETCHAT_AUTH_KEY = os.getenv("COMETCHAT_AUTH_KEY")


@router.post("/token")
async def get_chat_token(
    body: dict = {},
    current_user: dict = Depends(get_current_user_obj)
):
    """
    Generates a CometChat Auth Token for the logged-in user.

    Optional body:
        { "trip_id": "<mongo_trip_id>" }

    If trip_id is supplied the peer is resolved from that specific trip.
    If omitted the token is still issued (peer fields will be null).
    """
    request_id = f"CHAT-{uuid.uuid4().hex[:6]}"
    user_id = str(current_user["_id"])
    name = current_user.get("full_name") or current_user.get("name", "User")

    logger.info(f"[{request_id}] 🚀 START GET_CHAT_TOKEN | user: {user_id} | name: {name}")

    try:
        # 1️⃣ Ensure CURRENT user exists in CometChat
        logger.info(f"[{request_id}] 👤 Ensuring user exists in CometChat: {user_id}")
        ensure_cometchat_user(user_id, name)

        # 2️⃣ Resolve trip (by id or most-recent)
        trip_id: Optional[str] = body.get("trip_id") if body else None
        logger.info(f"[{request_id}] 🔍 Resolving trip context (trip_id parameter: {trip_id})")

        if trip_id:
            # --- caller supplied a specific trip ---
            try:
                trip_obj_id = ObjectId(trip_id)
            except Exception as e:
                logger.warning(f"[{request_id}] ❌ Invalid trip_id format: {trip_id}")
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "message": "Invalid trip_id format"}
                )

            logger.info(f"[{request_id}] 🔍 Fetching specific trip: {trip_id}")
            trip = await trips_collection.find_one({"_id": trip_obj_id})

            if not trip:
                logger.warning(f"[{request_id}] ❌ Trip not found: {trip_id}")
                return JSONResponse(
                    status_code=404,
                    content={"success": False, "message": "Trip not found"}
                )

            # Access control: caller must be traveler OR broker of this trip
            is_traveler = str(trip["user_id"]) == user_id
            is_broker = trip.get("broker_id") and str(trip["broker_id"]) == user_id

            if not is_traveler and not is_broker:
                logger.warning(f"[{request_id}] ❌ Access denied for user {user_id} on trip {trip_id}")
                return JSONResponse(
                    status_code=403,
                    content={"success": False, "message": "You are not part of this trip"}
                )

        else:
            # --- no trip_id supplied: best-effort lookup ---
            logger.info(f"[{request_id}] 🔍 No trip_id supplied. Finding most recent active trip for user...")
            trip = await trips_collection.find_one(
                {
                    "$or": [
                        {"user_id": ObjectId(user_id)},
                        {"broker_id": ObjectId(user_id)},
                    ],
                    "status": {"$in": ["chatting", "active", "completion_pending", "completed"]},
                },
                sort=[("updated_at", -1)],
            )
            if trip:
                logger.info(f"[{request_id}] ✅ Found recent trip: {trip['_id']}")
            else:
                logger.info(f"[{request_id}] ℹ️ No active trips found for user.")

        # 3️⃣ Determine PEER user (only when a trip is available)
        peer_id: Optional[str] = None
        peer_name: str = "User"

        if trip:
            trip_id_str = str(trip["_id"])
            logger.info(f"[{request_id}] 👥 Resolving peer for trip: {trip_id_str}")
            
            try:
                if str(trip["user_id"]) == user_id:
                    # Caller is the traveler → peer is the broker
                    if trip.get("broker_id"):
                        peer_id = str(trip["broker_id"])
                        logger.info(f"[{request_id}] 👤 Caller is Traveler, peer is Broker: {peer_id}")
                        peer_doc = await users_collection.find_one({"_id": ObjectId(peer_id)})
                        if peer_doc:
                            peer_name = (
                                peer_doc.get("org_name")
                                or peer_doc.get("full_name")
                                or peer_doc.get("name")
                                or "Broker"
                            )
                            logger.info(f"[{request_id}] ✅ Found broker peer: {peer_name}")
                        else:
                            logger.warning(f"[{request_id}] ⚠️ Broker document not found for ID: {peer_id}")
                    else:
                        logger.info(f"[{request_id}] ℹ️ Trip has no broker assigned yet.")
                else:
                    # Caller is the broker → peer is the traveler
                    peer_id = str(trip["user_id"])
                    logger.info(f"[{request_id}] 👤 Caller is Broker, peer is Traveler: {peer_id}")
                    peer_doc = await users_collection.find_one({"_id": ObjectId(peer_id)})
                    if peer_doc:
                        peer_name = (
                            peer_doc.get("full_name")
                            or peer_doc.get("name")
                            or "Traveler"
                        )
                        logger.info(f"[{request_id}] ✅ Found traveler peer: {peer_name}")
                    else:
                        logger.warning(f"[{request_id}] ⚠️ Traveler document not found for ID: {peer_id}")
            except Exception as e:
                logger.error(f"[{request_id}] ❌ Error during peer resolution: {str(e)}")

        # 4️⃣ Register peer in CometChat (idempotent)
        if peer_id:
            logger.info(f"[{request_id}] 🔄 Ensuring CometChat user exists for peer: {peer_id} ({peer_name})")
            ensure_cometchat_user(peer_id, peer_name)

        # 5️⃣ Generate CometChat AUTH TOKEN for the current user
        if not COMETCHAT_APP_ID or not COMETCHAT_API_KEY:
             logger.error(f"[{request_id}] ❌ CometChat configuration missing in env!")
             return JSONResponse(
                 status_code=500,
                 content={"success": False, "message": "Chat service configuration error"}
             )

        url = (
            f"https://{COMETCHAT_APP_ID}.api-{COMETCHAT_REGION}.cometchat.io"
            f"/v3/users/{user_id}/auth_tokens"
        )

        headers = {
            "Content-Type": "application/json",
            "apiKey": COMETCHAT_API_KEY,
            "appId": COMETCHAT_APP_ID,
        }

        logger.info(f"[{request_id}] 🚀 Requesting auth token from CometChat API...")
        res = requests.post(url, headers=headers, timeout=10)

        if res.status_code != 200:
            logger.error(f"[{request_id}] ❌ CometChat API Error: {res.status_code} - {res.text}")
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": f"CometChat API error: {res.text}"}
            )

        auth_token = res.json()["data"]["authToken"]
        logger.info(f"[{request_id}] ✨ SUCCESS: Chat token generated")

        return {
            "success": True,
            "token": auth_token,
            "uid": user_id,
            "authToken": auth_token,
            "peerUid": peer_id,
            "tripId": str(trip["_id"]) if trip else None,
        }

    except Exception as e:
        logger.error(
            f"[{request_id}] 💥 FATAL EXCEPTION in get_chat_token: {str(e)}",
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "Internal server error during chat initialization",
                "debug_info": f"{type(e).__name__}: {str(e)}"
            }
        )