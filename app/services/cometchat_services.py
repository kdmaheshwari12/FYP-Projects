import requests
import os
import logging

logger = logging.getLogger(__name__)

COMETCHAT_APP_ID = os.getenv("COMETCHAT_APP_ID")
COMETCHAT_REGION = os.getenv("COMETCHAT_REGION")
COMETCHAT_REST_API_KEY = os.getenv("COMETCHAT_API_KEY")

BASE_URL = f"https://{COMETCHAT_APP_ID}.api-{COMETCHAT_REGION}.cometchat.io/v3"

HEADERS = {
    "Content-Type": "application/json",
    "apiKey": COMETCHAT_REST_API_KEY,
    "appId": COMETCHAT_APP_ID,
}

def ensure_cometchat_user(user_id: str, name: str):
    if not COMETCHAT_APP_ID or not COMETCHAT_REST_API_KEY:
        logger.error("❌ CometChat configuration missing! Check COMETCHAT_APP_ID and COMETCHAT_API_KEY")
        return

    logger.info(f"🔄 [CometChat] Ensuring user exists: {user_id} ({name})")
    
    try:
        # 1️⃣ Check if user exists
        res = requests.get(
            f"{BASE_URL}/users/{user_id}",
            headers=HEADERS,
            timeout=10
        )

        if res.status_code == 200:
            logger.info(f"✅ [CometChat] User {user_id} already exists.")
            return

        if res.status_code == 404:
            # 2️⃣ Create user
            logger.info(f"➕ [CometChat] User {user_id} not found. Creating...")
            payload = {
                "uid": user_id,
                "name": name
            }

            create_res = requests.post(
                f"{BASE_URL}/users",
                json=payload,
                headers=HEADERS,
                timeout=10
            )

            if create_res.status_code in [200, 201]:
                logger.info(f"✅ [CometChat] User {user_id} created successfully.")
            else:
                logger.error(f"❌ [CometChat] Failed to create user: {create_res.text}")
                create_res.raise_for_status()
        else:
            logger.error(f"❌ [CometChat] Unexpected error checking user: {res.text}")
            res.raise_for_status()

    except Exception as e:
        logger.error(f"💥 [CometChat] Exception in ensure_cometchat_user: {str(e)}", exc_info=True)
        raise e