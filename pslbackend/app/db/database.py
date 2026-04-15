from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.core.config import settings
from typing import Optional
import logging

logger = logging.getLogger(__name__)

class Database:
    client: Optional[AsyncIOMotorClient] = None
    db: Optional[AsyncIOMotorDatabase] = None
    _initialized: bool = False  # Track initialization status

db = Database()

# Optional global access (if needed)
client: Optional[AsyncIOMotorClient] = None
database: Optional[AsyncIOMotorDatabase] = None

import asyncio

async def connect_to_mongo():
    """Reconnect to MongoDB if event loop was closed or db is None"""
    global client, database  # allow global access if needed

    try:
        if db.client is None or db.db is None:
            db.client = AsyncIOMotorClient(
                settings.MONGODB_URI,
                maxPoolSize=50,
                socketTimeoutMS=30000,
                connectTimeoutMS=30000,
                serverSelectionTimeoutMS=5000
            )
            await db.client.admin.command('ping')
            db.db = db.client[settings.DB_NAME]

            # Update global accessors
            client = db.client
            database = db.db
            db._initialized = True  # Mark as initialized

            logger.info("✅ Connected to MongoDB")
        else:
            # check if current loop is still valid
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: None)
    except RuntimeError as e:
        if "closed" in str(e):
            logger.warning("⚠️ Event loop was closed. Reinitializing MongoDB client.")
            db.client = None
            db.db = None
            db._initialized = False
            await connect_to_mongo()
        else:
            logger.error(f"MongoDB error: {e}")
            raise
    except Exception as e:
        logger.error(f"MongoDB connection failed: {e}")
        raise RuntimeError("Database connection failed") from e


async def close_mongo_connection():
    """Close MongoDB connection gracefully"""
    if db.client:
        db.client.close()
        logger.info("MongoDB connection closed")
        db.client = None
        db.db = None
        db._initialized = False

def get_db() -> AsyncIOMotorDatabase:
    """Get database instance - raises RuntimeError if not initialized"""
    if db.db is None or not db._initialized:
        raise RuntimeError("MongoDB not initialized - call connect_to_mongo() first")
    return db.db

def get_user_collection():
    """Get users collection with validation"""
    return get_db().users

def get_artwork_collection():
    """Get tickets collection with validation"""
    return get_db()["tickets"]

def get_wallet_collection():
    """Get wallets collection with validation"""
    return get_db().wallets

def get_license_collection():
    """Get licenses collection with validation"""
    return get_db().licenses

def get_transaction_collection():
    """Get transactions collection with validation"""
    return get_db().transactions

def get_categories_collection():
    db = get_db()
    return db.artwork_categories

def get_user_history_collection():
    """Get user history collection"""
    db = get_db()
    return db.user_history

def is_mongo_initialized() -> bool:
    """Check if MongoDB is initialized"""
    return db._initialized and db.db is not None