from fastapi import APIRouter, Depends, HTTPException 
import requests
import os
from bson import ObjectId
import logging

from app.routes.auth_routes import get_current_user_obj
from app.services.cometchat_services import ensure_cometchat_user
from app.db.mongodb import trips_collection, users_collection

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["Chat"])

COMETCHAT_APP_ID = os.getenv("COMETCHAT_APP_ID")
COMETCHAT_REGION = os.getenv("COMETCHAT_REGION")
COMETCHAT_AUTH_KEY = os.getenv("COMETCHAT_AUTH_KEY")


@router.post("/token")
async def get_chat_token(current_user: dict = Depends(get_current_user_obj)):
    """
    Generates a CometChat Auth Token for the logged-in user.
    """
    request_id = f"CHAT-{id(current_user)}"
    user_id = str(current_user["_id"])
    name = current_user.get("full_name") or current_user.get("name", "User")

    logger.info(f"[{request_id}] 💬 Chat token requested for user: {user_id}")

    try:
        # 1️⃣ Ensure CURRENT user exists in CometChat
        ensure_cometchat_user(user_id, name)

        # 2️⃣ Find active trip for this user (chatting/active/complete)
        trip = await trips_collection.find_one({
            "$or": [
                {"user_id": ObjectId(user_id)},
                {"broker_id": ObjectId(user_id)}
            ],
            "status": {"$in": ["chatting", "active" , "complete"]}
        })

        if not trip:
            logger.warning(f"[{request_id}] ⚠️ No active trip found for user: {user_id}")
            raise HTTPException(status_code=400, detail="No active trip found")

        # 3️⃣ Determine PEER user
        if trip["user_id"] == ObjectId(user_id):
            peer_id = str(trip["broker_id"])
            peer_name = "Broker"
        else:
            peer_id = str(trip["user_id"])
            peer_name = "Traveler"

        # 4️⃣ Ensure PEER exists in CometChat (idempotent)
        ensure_cometchat_user(peer_id, peer_name)

        # 5️⃣ Generate CometChat AUTH TOKEN
        url = f"https://{COMETCHAT_APP_ID}.api-{COMETCHAT_REGION}.cometchat.io/v3/users/{user_id}/auth_tokens"

        headers = {
            "Content-Type": "application/json",
            "apiKey": COMETCHAT_AUTH_KEY,
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
            "uid": user_id,
            "authToken": auth_token
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"[{request_id}] 💥 Unexpected error in get_chat_token: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")