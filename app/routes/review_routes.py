from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId
from datetime import datetime

from app.db.mongodb import (
    broker_reviews_collection,
    broker_itineraries_collection,
    itineraries_collection,
)
from app.routes.auth_routes import get_current_user_obj
from app.db.mongodb import broker_reviews_collection, users_collection
from app.core.validation import (
    validate_string,
    validate_integer,
    ValidationError,
    ValidationErrorResponse,
)
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reviews", tags=["Reviews"])

from pymongo.errors import DuplicateKeyError




@router.post("/")
async def submit_review(
    data: dict,
    current_user: dict = Depends(get_current_user_obj)
):
    """
    Submit a review for an itinerary with validation.
    
    Body:
    {
      "itineraryId": "...",
      "rating": 5,
      "comment": "Great experience!"
    }
    
    Returns:
        Success message
        
    Raises:
        422: Validation errors
        404: Itinerary not found
        400: Cannot review unpublished itinerary or duplicate review
        403: User cannot review their own itinerary
    """
    errors = []
    
    # ========== ITINERARY ID VALIDATION ==========
    itinerary_id = data.get("itineraryId")
    if not itinerary_id:
        raise HTTPException(
            status_code=400,
            detail="itineraryId is required"
        )
    
    try:
        itinerary_obj_id = ObjectId(itinerary_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid itineraryId format")
    
    # ========== RATING VALIDATION ==========
    try:
        validated_rating = validate_integer(
            data.get("rating"),
            "rating",
            min_value=1,
            max_value=5
        )
    except ValidationError as e:
        errors.append(e)
    
    # ========== COMMENT VALIDATION ==========
    comment = data.get("comment", "").strip()
    validated_comment = ""
    
    if comment:
        try:
            validated_comment = validate_string(
                comment,
                "comment",
                allow_empty=True,
                min_length=0,
                max_length=5000
            )
        except ValidationError as e:
            errors.append(e)
    
    # ========== RETURN VALIDATION ERRORS ==========
    if errors:
        logger.warning(f"Review submission validation failed: {len(errors)} error(s)")
        raise HTTPException(
            status_code=422,
            detail=ValidationErrorResponse.from_errors(errors).dict()
        )
    
    # ========== ITINERARY VALIDATION ==========
    itinerary = await broker_itineraries_collection.find_one(
        {"_id": itinerary_obj_id}
    )
    if not itinerary:
        itinerary = await itineraries_collection.find_one({"_id": itinerary_obj_id})
    
    if not itinerary:
        logger.warning(f"Itinerary not found: {itinerary_id}")
        raise HTTPException(status_code=404, detail="Itinerary not found")
    
    # ❌ Prevent reviewing unpublished itineraries
    if not itinerary.get("is_published", False):
        logger.warning(f"Cannot review unpublished itinerary: {itinerary_id}")
        raise HTTPException(
            status_code=400,
            detail="Cannot review an unpublished itinerary"
        )
    
    # ❌ Prevent broker reviewing their own itinerary
    if itinerary["brokerId"] == ObjectId(current_user["_id"]):
        logger.warning(f"User attempted to review their own itinerary: {current_user['_id']}")
        raise HTTPException(
            status_code=403,
            detail="You cannot review your own itinerary"
        )
    
    # ========== CREATE REVIEW ==========
    try:
        review_doc = {
            "itineraryId": itinerary_obj_id,
            "brokerId": itinerary.get("brokerId"),
            "userId": ObjectId(current_user["_id"]),
            "rating": validated_rating,
            "comment": validated_comment,
            "created_at": datetime.utcnow()
        }
        
        await broker_reviews_collection.insert_one(review_doc)
        
        logger.info(f"Review submitted successfully by user: {current_user['_id']}")
        
        return {
            "status": "success",
            "message": "Review submitted successfully"
        }
        
    except DuplicateKeyError:
        # Unique index (userId + itineraryId) violation
        logger.warning(f"Duplicate review attempt: user={current_user['_id']}, itinerary={itinerary_id}")
        raise HTTPException(
            status_code=400,
            detail="You have already reviewed this itinerary"
        )
    except Exception as e:
        logger.error(f"Error submitting review: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to submit review. Please try again."
        )

#fetch all reviews
@router.get("/itinerary/{itinerary_id}")
async def get_reviews_for_itinerary(itinerary_id: str):
    try:
        itinerary_obj_id = ObjectId(itinerary_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid itinerary id")

    reviews = await broker_reviews_collection.find(
        {"itineraryId": itinerary_obj_id}
    ).to_list(None)

    response = []

    for r in reviews:
        # fetch user name (optional but recommended)
        user = await users_collection.find_one(
            {"_id": r["userId"]},
            {"_id": 0, "full_name": 1, "email": 1}
        )

        response.append({
            "rating": r["rating"],
            "comment": r.get("comment", ""),
            "user": user.get("full_name") if user else "Anonymous",
            "created_at": r["created_at"]
        })

    return {
        "count": len(response),
        "reviews": response
    }

@router.get("/broker-reviews")
async def get_all_reviews_for_broker(
    current_user: dict = Depends(get_current_user_obj)
):
    try:
        broker_id = ObjectId(current_user["_id"])
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid broker ID")

    # ============================================================
    # ✅ Fetch ALL reviews directly using brokerId
    # ============================================================
    reviews = await broker_reviews_collection.find(
        {"brokerId": broker_id}
    ).sort("created_at", -1).to_list(None)

    response = []

    for r in reviews:
        user = await users_collection.find_one(
            {"_id": r["userId"]},
            {"_id": 0, "full_name": 1}
        )

        response.append({
            "rating": r["rating"],
            "comment": r.get("comment", ""),
            "user": user.get("full_name") if user else "Anonymous",
            "created_at": r["created_at"],
            "itinerary_id": str(r["itineraryId"])
        })

    return {
        "count": len(response),
        "reviews": response
    }