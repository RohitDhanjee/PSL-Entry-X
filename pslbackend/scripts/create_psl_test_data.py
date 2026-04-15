"""
PSL Test Data Script
====================
Creates a test PSL ticket and license for testing the Smart-Ticketing feature.

Usage: python scripts/create_psl_test_data.py
"""

import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime, timedelta
from bson import ObjectId
import os
from dotenv import load_dotenv

load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI")
DB_NAME = os.getenv("DB_NAME")

async def create_test_psl_ticket():
    """Create a test PSL ticket and license"""
    
    # Connect to MongoDB
    client = AsyncIOMotorClient(MONGODB_URI)
    db = client[DB_NAME]
    
    print("🔗 Connected to MongoDB")
    
    # Find specific user
    TARGET_EMAIL = "rohitdhanjee25@gmail.com"
    
    user = await db.users.find_one({"email": TARGET_EMAIL})
    if not user:
        print(f"❌ User not found: {TARGET_EMAIL}")
        return
    
    user_email = user.get("email")
    wallet_address = user.get("wallet_address", "")
    print(f"👤 Using user: {user_email}")
    
    # Create PSL Ticket (Artwork)
    ticket_id = ObjectId()
    ticket = {
        "_id": ticket_id,
        "title": "PSL 2024: Peshawar Zalmi vs Quetta Gladiators",
        "description": "VIP Entry Pass - Match 15",
        "category": "PSL_SMART_TICKET",
        "tags": ["psl", "ticket", "PSL", "cricket"],
        "is_psl_ticket": True,
        "price": 100,
        "image_url": "https://placehold.co/600x400/10b981/ffffff?text=PSL+TICKET",
        "creator_email": user_email,
        "owner_email": user_email,
        "seat_number": "A-45",
        "stand": "VIP Enclosure",
        "match_datetime": (datetime.utcnow() + timedelta(days=7)).isoformat(),
        "is_redeemed": False,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "metadata": {
            "seat_number": "A-45",
            "stand": "VIP Enclosure",
            "match_datetime": (datetime.utcnow() + timedelta(days=7)).isoformat(),
            "venue": "National Stadium, Karachi"
        }
    }
    
    await db.artworks.insert_one(ticket)
    print(f"✅ Created PSL ticket: {ticket_id}")
    
    # Create License for this ticket
    license_id = ObjectId()
    license_doc = {
        "_id": license_id,
        "artwork_id": str(ticket_id),
        "licensee_email": user_email,
        "licensee_wallet": wallet_address,
        "license_type": "PSL_SMART_TICKET",
        "is_active": True,
        "start_date": datetime.utcnow(),
        "end_date": datetime.utcnow() + timedelta(days=30),
        "created_at": datetime.utcnow(),
        "fee_paid": 100,
        "payment_method": "demo",
        "tx_hash": "demo_tx_" + str(license_id)
    }
    
    await db.licenses.insert_one(license_doc)
    print(f"✅ Created license: {license_id}")
    
    print("\n" + "="*50)
    print("🎫 PSL TEST DATA CREATED SUCCESSFULLY!")
    print("="*50)
    print(f"Ticket ID: {ticket_id}")
    print(f"License ID: {license_id}")
    print(f"User: {user_email}")
    print(f"Match: Peshawar Zalmi vs Quetta Gladiators")
    print(f"Seat: A-45 (VIP Enclosure)")
    print("\n👉 Now go to Dashboard > PSL Tickets to test!")
    
    client.close()

if __name__ == "__main__":
    asyncio.run(create_test_psl_ticket())
