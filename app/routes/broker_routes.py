# app/routes/broker_routes.py
from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId
from datetime import datetime
from app.db.mongodb import (
    users_collection,
    broker_itineraries_collection,
    broker_collection,
    trips_collection,
    broker_reviews_collection,
)
from app.routes.auth_routes import get_current_user_obj
from app.core.validation import (
    validate_email,
    validate_pakistan_phone,
    validate_cnic,
    validate_name,
    validate_string,
    validate_integer,
    validate_choice,
    ValidationError,
    ValidationErrorResponse,
)
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/broker", tags=["Broker"])

from typing import List

@router.post("/verify")
async def broker_verification(data: dict):
    """
    Broker verification endpoint with comprehensive validation.
    
    Required Fields:
    {
      "email": "broker@example.com",
      "org_name": "Travel Company Name",
      "phone": "0300-1234567",
      "cnic": "35201-1234567-1",
      "license_number": "LIC123456",
      "tagline": "Best travel experiences",
      "years_of_experience": 5,
      "specialized_areas": ["Adventure and Nature Tourism"]
    }
    
    Returns:
        Confirmation message
        
    Raises:
        422: Validation errors
        404: User not found
        403: User is not a broker
    """
    errors = []
    
    # ========== EMAIL VALIDATION ==========
    try:
        validated_email = validate_email(data.get("email"), "email")
    except ValidationError as e:
        errors.append(e)
    
    # ========== ORGANIZATION NAME VALIDATION ==========
    try:
        validated_org_name = validate_string(
            data.get("org_name"), 
            "org_name",
            allow_empty=False,
            min_length=2,
            max_length=100
        )
    except ValidationError as e:
        errors.append(e)
    
    # ========== PHONE VALIDATION ==========
    try:
        validated_phone = validate_pakistan_phone(data.get("phone"), "phone")
    except ValidationError as e:
        errors.append(e)
    
    # ========== CNIC VALIDATION ==========
    try:
        validated_cnic = validate_cnic(data.get("cnic"), "cnic")
    except ValidationError as e:
        errors.append(e)
    
    # ========== LICENSE NUMBER VALIDATION ==========
    try:
        validated_license = validate_string(
            data.get("license_number"),
            "license_number",
            allow_empty=False,
            min_length=5,
            max_length=50
        )
    except ValidationError as e:
        errors.append(e)
    
    # ========== TAGLINE VALIDATION ==========
    try:
        validated_tagline = validate_string(
            data.get("tagline"),
            "tagline",
            allow_empty=False,
            min_length=10,
            max_length=200
        )
    except ValidationError as e:
        errors.append(e)
    
    # ========== YEARS OF EXPERIENCE VALIDATION ==========
    try:
        validated_experience = validate_integer(
            data.get("years_of_experience"),
            "years_of_experience",
            min_value=0,
            max_value=70
        )
    except ValidationError as e:
        errors.append(e)
    
    # ========== SPECIALIZED AREAS VALIDATION ==========
    try:
        specialized_areas = data.get("specialized_areas")
        if not specialized_areas or not isinstance(specialized_areas, list):
            raise ValidationError(
                "specialized_areas",
                "Specialized areas must be a non-empty list",
                code="INVALID_SPECIALIZED_AREAS"
            )
        if len(specialized_areas) == 0:
            raise ValidationError(
                "specialized_areas",
                "At least one specialized area is required",
                code="EMPTY_SPECIALIZED_AREAS"
            )
        # Validate each area is a non-empty string
        validated_areas = []
        for i, area in enumerate(specialized_areas):
            if not isinstance(area, str) or not area.strip():
                raise ValidationError(
                    "specialized_areas",
                    f"Area {i+1} must be a non-empty string",
                    code="INVALID_AREA_FORMAT"
                )
            validated_areas.append(area.strip())
    except ValidationError as e:
        errors.append(e)
    
    # ========== RETURN VALIDATION ERRORS ==========
    if errors:
        logger.warning(f"Broker verification validation failed: {len(errors)} error(s)")
        raise HTTPException(
            status_code=422,
            detail=ValidationErrorResponse.from_errors(errors).dict()
        )
    
    # ========== USER EXISTENCE & ROLE CHECK ==========
    try:
        logger.info(f"Looking up broker by email: {validated_email}")
        user = await users_collection.find_one({"email": validated_email})
        
        if not user:
            logger.warning(f"Broker not found: {validated_email}")
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )
        
        if user.get("role") != "broker":
            logger.warning(f"User is not a broker: {validated_email}")
            raise HTTPException(
                status_code=403,
                detail="User is not a broker"
            )
        
        # ========== UPDATE USER WITH VERIFIED DATA ==========
        await users_collection.update_one(
            {"email": validated_email},
            {"$set": {
                "org_name": validated_org_name,
                "tagline": validated_tagline,
                "years_of_experience": validated_experience,
                "specialized_areas": validated_areas,
                "verification_details": {
                    "phone": validated_phone,
                    "cnic": validated_cnic,
                    "license_number": validated_license,
                },
                "can_login": True,
                "is_verified": False,
                "updated_at": datetime.utcnow()
            }}
        )
        
        logger.info(f"Broker verification submitted successfully: {validated_email}")
        
        return {
            "status": "success",
            "message": "Verification submitted successfully",
            "email": validated_email
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating broker verification: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to submit verification. Please try again."
        )

# ------------------------------------------------------
# 1️⃣ CREATE ITINERARY
# ------------------------------------------------------
from app.middleware.auth_middleware import require_broker

@router.post("/itineraries")
async def create_itinerary(
    data: dict, 
    current_user: dict = Depends(require_broker)
):
    """
    Create a new itinerary with comprehensive validation.
    """
    errors = []
    
    # ========== TITLE VALIDATION ==========
    try:
        validated_title = validate_string(
            data.get("title"),
            "title",
            allow_empty=False,
            min_length=5,
            max_length=200
        )
    except ValidationError as e:
        errors.append(e)
    
    # ========== LOCATION VALIDATION ==========
    try:
        validated_departure = validate_string(
            data.get("departure_location"),
            "departure_location",
            allow_empty=False,
            min_length=2,
            max_length=100
        )
    except ValidationError as e:
        errors.append(e)
    
    try:
        validated_arrival = validate_string(
            data.get("arrival_location"),
            "arrival_location",
            allow_empty=False,
            min_length=2,
            max_length=100
        )
    except ValidationError as e:
        errors.append(e)
    
    # ========== DESCRIPTION VALIDATION ==========
    try:
        validated_description = validate_string(
            data.get("description"),
            "description",
            allow_empty=False,
            min_length=10,
            max_length=5000
        )
    except ValidationError as e:
        errors.append(e)
    
    # ========== DURATION VALIDATION ==========
    try:
        validated_duration = validate_integer(
            data.get("duration_days"),
            "duration_days",
            min_value=1,
            max_value=365
        )
    except ValidationError as e:
        errors.append(e)
    
    # ========== PRICE VALIDATION ==========
    try:
        validated_price = validate_integer(
            data.get("price_per_person"),
            "price_per_person",
            min_value=1,
            max_value=10000000  # 10 million PKR max
        )
    except ValidationError as e:
        errors.append(e)
    
    # ========== CONTACT INFO VALIDATION ==========
    # Phone (optional but if provided, must be valid)
    validated_phone = None
    if data.get("phone"):
        try:
            validated_phone = validate_pakistan_phone(data.get("phone"), "phone")
        except ValidationError as e:
            errors.append(e)
    
    # Email (optional but if provided, must be valid)
    validated_email = None
    if data.get("email"):
        try:
            validated_email = validate_email(data.get("email"), "contact_email")
        except ValidationError as e:
            errors.append(e)
    
    # WhatsApp (optional but if provided, must be valid phone)
    validated_whatsapp = None
    if data.get("whatsapp"):
        try:
            validated_whatsapp = validate_pakistan_phone(data.get("whatsapp"), "whatsapp")
        except ValidationError as e:
            errors.append(e)
    
    # ========== RETURN VALIDATION ERRORS ==========
    if errors:
        logger.warning(f"Itinerary creation validation failed: {len(errors)} error(s)")
        raise HTTPException(
            status_code=422,
            detail=ValidationErrorResponse.from_errors(errors).dict()
        )
    
    try:
        # ========== CREATE ITINERARY ==========
        itinerary = {
            "brokerId": ObjectId(current_user["_id"]),
            "title": validated_title,
            "departure_location": validated_departure,
            "arrival_location": validated_arrival,
            "trip_locations": data.get("trip_locations", []),
            "duration_days": validated_duration,
            "price_per_person": validated_price,
            "description": validated_description,
            "days": data.get("days", []),
            "cover_image": data.get("cover_image", ""),
            "contact_info": {
                "phone": validated_phone or "",
                "whatsapp": validated_whatsapp or "",
                "email": validated_email or ""
            },
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "is_published": True,
        }
        
        result = await broker_itineraries_collection.insert_one(itinerary)
        
        logger.info(f"Itinerary created successfully: {result.inserted_id}")
        
        return {
            "status": "success",
            "message": "Itinerary created successfully",
            "id": str(result.inserted_id)
        }
        
    except Exception as e:
        logger.error(f"Error creating itinerary: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to create itinerary. Please try again."
        )

# ------------------------------------------------------
# 2️⃣ UPDATE ITINERARY
# ------------------------------------------------------
# ------------------------------------------------------
# UPDATE ITINERARY (FINAL VERSION)
# ------------------------------------------------------
@router.put("/update-itineraries/{itinerary_id}")
async def update_itinerary(
    itinerary_id: str,
    updates: dict,
    current_user: dict = Depends(get_current_user_obj)
):

    # Check role
    if current_user["role"] != "broker":
        raise HTTPException(status_code=403, detail="Only brokers allowed")

    # Fetch itinerary
    itinerary = await broker_itineraries_collection.find_one(
        {"_id": ObjectId(itinerary_id)}
    )

    if not itinerary:
        raise HTTPException(status_code=404, detail="Itinerary not found")

    # Ownership validation
    if str(itinerary["brokerId"]) != current_user["_id"]:
        raise HTTPException(status_code=403, detail="Not authorized to edit this")

    # Auto-update timestamp
    updates["updated_at"] = datetime.utcnow()

    # Apply update
    await broker_itineraries_collection.update_one(
        {"_id": ObjectId(itinerary_id)},
        {"$set": updates}
    )

    # Fetch updated itinerary
    updated_itinerary = await broker_itineraries_collection.find_one(
        {"_id": ObjectId(itinerary_id)}
    )

    # Convert ObjectIds → strings
    updated_itinerary["_id"] = str(updated_itinerary["_id"])
    updated_itinerary["brokerId"] = str(updated_itinerary["brokerId"])

    return {
        "message": "Itinerary updated successfully",
        "itinerary": updated_itinerary
    }

# ------------------------------------------------------
# 3️⃣ DELETE ITINERARY
# ------------------------------------------------------
@router.delete("/delete-itineraries/{itinerary_id}")
async def delete_itinerary(itinerary_id: str, current_user: dict = Depends(get_current_user_obj)):

    if current_user["role"] != "broker":
        raise HTTPException(status_code=403, detail="Only brokers allowed")

    itinerary = await broker_itineraries_collection.find_one({"_id": ObjectId(itinerary_id)})

    if not itinerary:
        raise HTTPException(status_code=404, detail="Itinerary not found")

    if str(itinerary["brokerId"]) != current_user["_id"]:
        raise HTTPException(status_code=403, detail="Not allowed")

    await broker_itineraries_collection.delete_one({"_id": ObjectId(itinerary_id)})

    return {"message": "Itinerary deleted successfully"}


# ------------------------------------------------------
# 6️⃣ GET DETAILED ITINERARY
# ------------------------------------------------------
@router.get("/itineraries/{itinerary_id}")
async def get_itinerary_detail(itinerary_id: str):
    try:
        obj_id = ObjectId(itinerary_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid itinerary id")

    itinerary = await broker_itineraries_collection.find_one({"_id": obj_id})
    if not itinerary:
        raise HTTPException(status_code=404, detail="Itinerary not found")

    # Convert ObjectIds
    itinerary["_id"] = str(itinerary["_id"])
    broker_id = itinerary.get("brokerId")

    if broker_id:
        itinerary["brokerId"] = str(broker_id)

        # 🔹 Fetch broker org name + contact info
        broker = await users_collection.find_one(
            {"_id": broker_id},
            {"org_name": 1}
        )

        broker_contact = await broker_collection.find_one(
            {"brokerId": broker_id},
            {"_id": 0, "phone": 1, "whatsapp": 1, "email": 1}
        )

        itinerary["broker_org_name"] = broker.get("org_name", "Independent Broker") if broker else "Independent Broker"
    else:
        broker_contact = None
        itinerary["broker_org_name"] = "Independent Broker"

    itinerary["contact_info"] = broker_contact or {
        "phone": "",
        "whatsapp": "",
        "email": ""
    }

    itinerary.setdefault("departure_location", "")
    itinerary.setdefault("arrival_location", "")
    itinerary.setdefault("trip_locations", [])

    return {"itinerary": itinerary}

# ------------------------------------------------------
# 4️⃣ GET ALL ITINERARIES OF LOGGED-IN BROKER
# ------------------------------------------------------
@router.get("/show-itineraries")
async def get_broker_itineraries(current_user: dict = Depends(get_current_user_obj)):

    if current_user["role"] != "broker":
        raise HTTPException(status_code=403, detail="Only brokers allowed")

    itineraries = await broker_itineraries_collection.find(
        {"brokerId": ObjectId(current_user["_id"])}
    ).to_list(length=None)

    for i in itineraries:
        i["_id"] = str(i["_id"])
        i["brokerId"] = str(i["brokerId"])

    return itineraries

# ------------------------------------------------------
# GLOBAL CONTACT INFO ROUTE (Create/Update)
# ------------------------------------------------------
@router.put("/contact-info")
async def update_broker_contact_info(
    data: dict,
    current_user: dict = Depends(get_current_user_obj)
):

    if current_user["role"] != "broker":
        raise HTTPException(status_code=403, detail="Only brokers allowed")

    broker_id = ObjectId(current_user["_id"])

    contact_info = {
        "phone": data.get("phone", ""),
        "whatsapp": data.get("whatsapp", ""),
        "email": data.get("email", ""),
        "updated_at": datetime.utcnow()
    }

    # Check if record exists
    existing = await broker_collection.find_one(
        {"brokerId": broker_id}
    )

    if existing:
        # Update existing contact info
        await broker_collection.update_one(
            {"brokerId": broker_id},
            {"$set": contact_info}
        )
    else:
        # Create new contact info record
        await broker_collection.insert_one(
            { "brokerId": broker_id, **contact_info }
        )

    # ALSO update all itineraries with new contact info
    await broker_itineraries_collection.update_many(
        {"brokerId": broker_id},
        {"$set": {"contact_info": contact_info}}
    )

    return {"message": "Contact info updated for broker and all itineraries"}
# ------------------------------------------------------
# GET BROKER CONTACT INFO
# ------------------------------------------------------
@router.get("/contact-info")
async def get_broker_contact_info(
    current_user: dict = Depends(get_current_user_obj)
):

    if current_user["role"] != "broker":
        raise HTTPException(status_code=403, detail="Only brokers allowed")

    broker_id = ObjectId(current_user["_id"])

    info = await broker_collection.find_one(
        {"brokerId": broker_id}
    )

    if not info:
        return {
            "phone": "",
            "whatsapp": "",
            "email": "",
        }

    info["_id"] = str(info["_id"])
    info["brokerId"] = str(info["brokerId"])

    return info
from typing import Optional
from bson import ObjectId
from app.db.mongodb import (
    broker_itineraries_collection,
    broker_reviews_collection
)

@router.get("/public/itineraries")
async def get_all_published_itineraries(
    city: Optional[str] = None,
    min_price: Optional[int] = None,
    max_price: Optional[int] = None,
    min_rating: Optional[float] = None,
):
    filters = []

    # ✅ Published OR legacy docs
    filters.append({
        "$or": [
            {"is_published": True},
            {"is_published": {"$exists": False}}
        ]
    })

    # ✅ City filter
    if city:
        filters.append({
            "$or": [
                {"arrival_location": {"$regex": city, "$options": "i"}},
                {
                    "trip_locations": {
                        "$elemMatch": {
                            "$regex": city,
                            "$options": "i"
                        }
                    }
                }
            ]
        })

    # ✅ Budget filter
    if min_price is not None or max_price is not None:
        price_query = {}
        if min_price is not None:
            price_query["$gte"] = min_price
        if max_price is not None:
            price_query["$lte"] = max_price

        filters.append({"price_per_person": price_query})

    query = {"$and": filters} if filters else {}

    itineraries = await broker_itineraries_collection.find(query).to_list(None)

    enriched = []

    for it in itineraries:
        itinerary_id = it["_id"]

        # ⭐ Aggregate reviews
        pipeline = [
            {"$match": {"itineraryId": itinerary_id}},
            {
                "$group": {
                    "_id": "$itineraryId",
                    "avgRating": {"$avg": "$rating"},
                    "reviewCount": {"$sum": 1}
                }
            }
        ]

        rating_data = await broker_reviews_collection.aggregate(pipeline).to_list(1)

        avg_rating = round(rating_data[0]["avgRating"], 1) if rating_data else 0
        review_count = rating_data[0]["reviewCount"] if rating_data else 0

        # ⭐ Rating filter
        if min_rating is not None and avg_rating < min_rating:
            continue

        # 🔹 Fetch broker org name
        broker = await users_collection.find_one(
            {"_id": it["brokerId"]},
            {"org_name": 1}
        )

        it["_id"] = str(it["_id"])
        it["brokerId"] = str(it["brokerId"])
        it["avgRating"] = avg_rating
        it["reviewCount"] = review_count
        it["broker_org_name"] = broker.get("org_name", "Independent Broker") if broker else "Independent Broker"

        enriched.append(it)

    return enriched

# ------------------------------------------------------
# 📥 BROKER INCOMING REQUESTS (CHAT INBOX)
# ------------------------------------------------------

@router.get("/incoming-requests")
async def get_broker_incoming_requests(
    current_user: dict = Depends(get_current_user_obj)
):
    # 🔐 Only brokers allowed
    if current_user["role"] != "broker":
        raise HTTPException(status_code=403, detail="Only brokers allowed")

    broker_id = ObjectId(current_user["_id"])

    # 🔎 Fetch trips assigned to this broker
    trips_cursor = trips_collection.find(
        {
            "broker_id": broker_id,
            "status": {"$in": ["chatting", "active", "completion_pending"]}
        }
    ).sort("updated_at", -1)

    trips = await trips_cursor.to_list(length=None)

    response = []

    for trip in trips:
        # 👤 Fetch traveler info
        traveler = await users_collection.find_one(
            {"_id": trip["user_id"]},
            {"full_name": 1}
        )

        response.append({
            "tripId": str(trip["_id"]),
            "travelerName": traveler.get("full_name", "Traveler") if traveler else "Traveler",
            "destination": trip.get("destination", ""),
            "budget": trip.get("budget", 0),
            "status": trip.get("status"),
            "tripType": trip.get("trip_type"),
            "lastMessage": trip.get("last_message"),  # may be None
            "updatedAt": trip.get("updated_at")
        })

    return response

@router.get("/marketplace")
async def broker_marketplace():

    brokers = await users_collection.find(
        {
            "role": "broker",
            "can_login": True
        }
    ).to_list(None)

    result = []

    for broker in brokers:

        broker_id = broker["_id"]  # ObjectId

        # ✅ Count itineraries
        total_itineraries = await broker_itineraries_collection.count_documents({
            "brokerId": broker_id
        })

        # ✅ Get reviews
        reviews = await broker_reviews_collection.find({
            "brokerId": broker_id
        }).to_list(None)

        review_count = len(reviews)

        if review_count > 0:
            avg_rating = sum(r.get("rating", 0) for r in reviews) / review_count
        else:
            avg_rating = 0

        result.append({
            "broker_id": str(broker_id),
            "org_name": broker.get("org_name", "Unnamed Broker"),
            "tagline": broker.get("tagline", ""),
            "years_of_experience": broker.get("years_of_experience", 0),
            "specialized_areas": broker.get("specialized_areas", []),
            "rating": round(avg_rating, 1),
            "review_count": review_count,
            "total_itineraries": total_itineraries,
        })

    # 🔥 Sort by rating (descending)
    result.sort(key=lambda x: x["rating"], reverse=True)

    return result