import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv

load_dotenv()

async def migrate_artworks():
    mongodb_uri = os.getenv("MONGODB_URI")
    db_name = os.getenv("DB_NAME")
    
    print(f"Connecting to MongoDB: {db_name}")
    client = AsyncIOMotorClient(mongodb_uri)
    db = client[db_name]
    artworks_collection = db.artworks
    
    # Find all artworks where responsible_use_addon is a dictionary
    cursor = artworks_collection.find({"responsible_use_addon": {"$type": "object"}})
    count = 0
    
    async for doc in cursor:
        old_val = doc.get("responsible_use_addon")
        new_val = False
        if isinstance(old_val, dict):
            new_val = old_val.get("enabled", False)
        
        print(f"Migrating artwork {doc.get('token_id')}: {old_val} -> {new_val}")
        await artworks_collection.update_one(
            {"_id": doc["_id"]},
            {"$set": {"responsible_use_addon": new_val}}
        )
        count += 1
    
    print(f"\nMigration complete! {count} artworks updated.")

if __name__ == "__main__":
    asyncio.run(migrate_artworks())
