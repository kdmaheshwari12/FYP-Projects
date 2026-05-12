from fastapi import APIRouter, Depends, HTTPException
import requests
import os
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
    request_id = f"CHAT-{id(current_user)}"
    user_id = str(current_user["_id"])
    name = current_user.get("full_name") or current_user.get("name", "User")

    logger.info(f"[{request_id}] 💬 Chat token requested for user: {user_id}")

    try:
        # 1️⃣ Ensure CURRENT user exists in CometChat
        ensure_cometchat_user(user_id, name)

        # 2️⃣ Resolve trip (by id or most-recent)
        trip_id: Optional[str] = body.get("trip_id") if body else None

        if trip_id:
            # --- caller supplied a specific trip ---
            try:
                trip_obj_id = ObjectId(trip_id)
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid trip_id format")

            trip = await trips_collection.find_one({"_id": trip_obj_id})

            if not trip:
                raise HTTPException(status_code=404, detail="Trip not found")

            # Access control: caller must be traveler OR broker of this trip
            is_traveler = trip["user_id"] == ObjectId(user_id)
            is_broker = trip.get("broker_id") and trip["broker_id"] == ObjectId(user_id)

            if not is_traveler and not is_broker:
                raise HTTPException(status_code=403, detail="You are not part of this trip")

        else:
            # --- no trip_id supplied: best-effort lookup, never block token generation ---
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
            # trip may be None — that is fine, token is still generated below

        # 3️⃣ Determine PEER user (only when a trip is available)
        peer_id: Optional[str] = None
        peer_name: str = "User"

        if trip:
            if trip["user_id"] == ObjectId(user_id):
                # Caller is the traveler → peer is the broker
                if trip.get("broker_id"):
                    peer_id = str(trip["broker_id"])
                    peer_doc = await users_collection.find_one({"_id": trip["broker_id"]})
                    peer_name = (
                        peer_doc.get("org_name")
                        or peer_doc.get("name")
                        or "Broker"
                    ) if peer_doc else "Broker"
            else:
                # Caller is the broker → peer is the traveler
                peer_id = str(trip["user_id"])
                peer_doc = await users_collection.find_one({"_id": trip["user_id"]})
                peer_name = (
                    peer_doc.get("full_name")
                    or peer_doc.get("name")
                    or "Traveler"
                ) if peer_doc else "Traveler"

        # 4️⃣ Register peer in CometChat (idempotent – safe to call every time)
        if peer_id:
            ensure_cometchat_user(peer_id, peer_name)

        # 5️⃣ Generate CometChat AUTH TOKEN for the current user
        url = (
            f"https://{COMETCHAT_APP_ID}.api-{COMETCHAT_REGION}.cometchat.io"
            f"/v3/users/{user_id}/auth_tokens"
        )

        headers = {
            "Content-Type": "application/json",
            "apiKey": COMETCHAT_API_KEY,
            "appId": COMETCHAT_APP_ID,
        }

        res = requests.post(url, headers=headers)

        if res.status_code != 200:
            logger.error(f"[{request_id}] ❌ CometChat API Error: {res.text}")
            raise HTTPException(status_code=500, detail="Failed to communicate with chat service")

        auth_token = res.json()["data"]["authToken"]
        logger.info(f"[{request_id}] ✅ Chat token generated successfully")

        return {
            "success": True,
            "token": auth_token,       # matches frontend expectation
            "uid": user_id,
            "authToken": auth_token,   # kept for backwards-compat
            "peerUid": peer_id,
            "tripId": str(trip["_id"]) if trip else None,
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(
            f"[{request_id}] 💥 Unexpected error in get_chat_token: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")