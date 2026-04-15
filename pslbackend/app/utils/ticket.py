from typing import Any, Dict, Optional, Union
from bson import ObjectId
from app.db.database import get_artwork_collection
import logging

logger = logging.getLogger(__name__)

async def resolve_artwork_identifier(artwork_identifier: Union[int, str]) -> Optional[Dict[str, Any]]:
    """
    Resolve ticket from database using either MongoDB _id or legacy token_id.
    """
    if not artwork_identifier:
        return None
        
    artworks_collection = get_artwork_collection()
    
    # Priority 1: MongoDB _id (most accurate)
    if isinstance(artwork_identifier, str) and ObjectId.is_valid(artwork_identifier):
        try:
            artwork_doc = await artworks_collection.find_one({"_id": ObjectId(artwork_identifier)})
            if artwork_doc:
                return artwork_doc
        except Exception as e:
            logger.debug(f"ObjectId lookup failed for {artwork_identifier}: {e}")
            
    # Priority 2: Numeric token_id (legacy)
    try:
        # Handle string input that's actually an integer token_id
        token_id_int = int(artwork_identifier)
        artwork_doc = await artworks_collection.find_one({"token_id": token_id_int}, sort=[("_id", -1)])
        if artwork_doc:
            return artwork_doc
    except (ValueError, TypeError):
        pass
        
    # Last resort: Try as string $or search
    try:
        artwork_doc = await artworks_collection.find_one({
            "$or": [
                {"token_id": artwork_identifier},
                {"_id": artwork_identifier} 
            ]
        })
        return artwork_doc
    except Exception as e:
        logger.error(f"Final identifier resolution fallback failed: {e}")
        return None
