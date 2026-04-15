import asyncio
import os
import sys
from datetime import datetime

# Add the project root to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

async def init_license_config():
    """Initialize default license configuration with both fixed fees and percentages"""
    try:
        from app.db.database import connect_to_mongo, get_db
        from app.db.models import LicenseConfig
        
        # Initialize MongoDB connection
        await connect_to_mongo()
        print("✅ MongoDB connected successfully")
        
        db = get_db()
        config_collection = db.license_configs
        
        # Check if default config already exists
        existing = await config_collection.find_one({"name": "Default Configuration"})
        if existing:
            print("✅ Default license configuration already exists")
            return
        
        # Create default configuration with BOTH fixed fees and percentages
        default_config = LicenseConfig(
            name="Default Configuration",
            # Fixed fees (as you specified)
            link_only_fee_eth=0.01196,
            watermark_fee_eth=0.02392,
            full_access_fee_eth=0.03588,
            # Percentages (for percentage-based calculation)
            link_only_percentage=20.0,  # 20% of artwork price
            watermark_percentage=70.0,  # 70% of artwork price  
            full_access_percentage=90.0,  # 90% of artwork price
            pricing_mode="fixed",  # Default to fixed fees
            license_duration_days=30,
            description="License configuration with both fixed fees (0.01196/0.02392/0.03588 ETH) and percentage options (20%/70%/90%)"
        )
        
        result = await config_collection.insert_one(default_config.model_dump(by_alias=True))
        default_config.id = str(result.inserted_id)
        
        print("✅ Default license configuration created successfully")
        print(f"📊 Fixed Fee Details:")
        print(f"   - Link Only: {default_config.link_only_fee_eth} ETH")
        print(f"   - Watermark Access: {default_config.watermark_fee_eth} ETH")
        print(f"   - Full Access: {default_config.full_access_fee_eth} ETH")
        print(f"📊 Percentage Details:")
        print(f"   - Link Only: {default_config.link_only_percentage}% of artwork price")
        print(f"   - Watermark Access: {default_config.watermark_percentage}% of artwork price")
        print(f"   - Full Access: {default_config.full_access_percentage}% of artwork price")
        print(f"⚙️  Pricing Mode: {default_config.pricing_mode}")
        print(f"⏰ Duration: {default_config.license_duration_days} days")
        
    except Exception as e:
        print(f"❌ Error creating license configuration: {e}")
        raise

if __name__ == "__main__":
    print("🚀 Starting license configuration initialization...")
    asyncio.run(init_license_config())