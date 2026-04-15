import os
import logging
from datetime import datetime
from pymongo import MongoClient

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("migration")

# MongoDB Configuration
# Using the URI from the .env file found earlier
MONGODB_URI = "mongodb+srv://aiprojects789:IP1NwVwaBM0TosQI@drm.cmnzpag.mongodb.net/art_drm?retryWrites=true&w=majority&tls=true"
DB_NAME = "art_drm_local"

# Mapping from old types to new Phase 2 types
TYPE_MAPPING = {
    "LINK_ONLY": "PERSONAL_USE",
    "ACCESS_WITH_WM": "NON_COMMERCIAL",
    "FULL_ACCESS": "COMMERCIAL"
}

def migrate_licenses():
    """Migrate existing licenses to new Phase 2 types"""
    try:
        client = MongoClient(MONGODB_URI)
        db = client[DB_NAME]
        license_collection = db.licenses
        artwork_collection = db.artworks
        
        logger.info(f"🚀 Starting Phase 2 License Migration on DB: {DB_NAME}...")
        
        # 1. Update existing licenses
        total_migrated = 0
        for old_type, new_type in TYPE_MAPPING.items():
            result = license_collection.update_many(
                {"license_type": old_type},
                {"$set": {"license_type": new_type, "updated_at": datetime.utcnow()}}
            )
            total_migrated += result.modified_count
            logger.info(f"✅ Migrated {result.modified_count} licenses from {old_type} to {new_type}")
        
        # 2. Update all artworks to have the default 8 license types
        default_types = [
            "PERSONAL_USE", "NON_COMMERCIAL", "COMMERCIAL", "EXTENDED_COMMERCIAL",
            "EXCLUSIVE", "RESPONSIBLE_USE", "ARTWORK_OWNERSHIP", "CUSTOM"
        ]
        
        artworks_result = artwork_collection.update_many(
            {"available_license_types": {"$exists": False}},
            {"$set": {
                "available_license_types": default_types,
                "responsible_use_addon": {
                    "enabled": True,
                    "price_percentage": 500 # 5% default
                },
                "updated_at": datetime.utcnow()
            }}
        )
        logger.info(f"✅ Updated {artworks_result.modified_count} artworks with default Phase 2 license types")
        
        # 3. Handle old artworks that might have limited available types (if any)
        cursor = artwork_collection.find({"available_license_types": {"$in": list(TYPE_MAPPING.keys())}})
        count = 0
        for artwork in cursor:
            old_types = artwork.get("available_license_types", [])
            new_types = []
            for t in old_types:
                if t in TYPE_MAPPING:
                    new_types.append(TYPE_MAPPING[t])
                elif t in default_types:
                    new_types.append(t)
            
            # Ensure we always have the 8 standard ones if it was being updated
            if not new_types:
                new_types = default_types
                
            artwork_collection.update_one(
                {"_id": artwork["_id"]},
                {"$set": {"available_license_types": new_types}}
            )
            count += 1
        
        logger.info(f"✅ Refined {count} artworks with mapped license types")
        logger.info("🏁 Phase 2 Migration Complete!")
        client.close()
    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")

if __name__ == "__main__":
    migrate_licenses()
