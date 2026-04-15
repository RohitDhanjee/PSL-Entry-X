import asyncio
import os
import sys
from pathlib import Path

# Add the current directory to the Python path
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

async def init_categories():
    try:
        print("🔧 Initializing artwork categories...")
        
        # Import motor
        from motor.motor_asyncio import AsyncIOMotorClient
        
        # Your MongoDB connection details - UPDATE THESE WITH YOUR ACTUAL VALUES
        MONGODB_URL = "mongodb+srv://aiprojects789:IP1NwVwaBM0TosQI@drm.cmnzpag.mongodb.net/art_drm?retryWrites=true&w=majority&tls=true"  # Update if different
        DATABASE_NAME = "art_drm_local"  # Update with your actual database name
        
        print(f"📡 Connecting to MongoDB: {MONGODB_URL}")
        print(f"🗄️ Database: {DATABASE_NAME}")
        
        # Connect to MongoDB
        client = AsyncIOMotorClient(MONGODB_URL)
        db = client[DATABASE_NAME]
        categories_collection = db.artwork_categories
        
        # Predefined categories
        CATEGORIES = [
            # 🎨 By Medium / Technique
            {"name": "Painting", "type": "medium", "description": "Oil, acrylic, watercolor, gouache, tempera, digital, spray, etc.", "is_active": True},
            {"name": "Drawing", "type": "medium", "description": "Pencil, charcoal, ink, pastel, marker, etc.", "is_active": True},
            {"name": "Sculpture", "type": "medium", "description": "Stone, wood, metal, clay, ceramic, mixed media", "is_active": True},
            {"name": "Printmaking", "type": "medium", "description": "Etching, lithography, screen printing, woodcut, etc.", "is_active": True},
            {"name": "Photography", "type": "medium", "description": "Digital, film, black & white, color, experimental", "is_active": True},
            {"name": "Digital Art", "type": "medium", "description": "AI art, 3D modeling, vector, animation", "is_active": True},
            {"name": "Mixed Media / Collage", "type": "medium", "description": "Combination of different artistic mediums", "is_active": True},
            {"name": "Textile & Fiber Art", "type": "medium", "description": "Weaving, embroidery, fashion, tapestry", "is_active": True},
            {"name": "Calligraphy / Typography", "type": "medium", "description": "Artistic writing and lettering", "is_active": True},
            {"name": "Installation Art", "type": "medium", "description": "Large-scale, immersive artworks", "is_active": True},
            {"name": "Performance Art", "type": "medium", "description": "Live artistic performance", "is_active": True},
            {"name": "Other Medium", "type": "medium", "description": "Other artistic medium not listed", "is_active": True},
            
            # 🖼 By Style / Movement
            {"name": "Abstract", "type": "style", "description": "Non-representational art", "is_active": True},
            {"name": "Realism / Hyperrealism", "type": "style", "description": "Art that resembles reality", "is_active": True},
            {"name": "Impressionism", "type": "style", "description": "Emphasis on light and movement", "is_active": True},
            {"name": "Expressionism", "type": "style", "description": "Emotional experience over physical reality", "is_active": True},
            {"name": "Surrealism", "type": "style", "description": "Dream-like, unconscious mind", "is_active": True},
            {"name": "Cubism", "type": "style", "description": "Geometric forms and multiple perspectives", "is_active": True},
            {"name": "Minimalism", "type": "style", "description": "Extreme simplicity of form", "is_active": True},
            {"name": "Pop Art", "type": "style", "description": "Popular culture influences", "is_active": True},
            {"name": "Conceptual Art", "type": "style", "description": "Idea or concept over aesthetic", "is_active": True},
            {"name": "Street Art / Graffiti", "type": "style", "description": "Public space art", "is_active": True},
            {"name": "Contemporary / Modern", "type": "style", "description": "Current artistic trends", "is_active": True},
            {"name": "Traditional / Folk / Indigenous", "type": "style", "description": "Cultural and traditional art forms", "is_active": True},
            {"name": "Other Style", "type": "style", "description": "Other artistic style not listed", "is_active": True},
            
            # 🌍 By Subject Matter
            {"name": "Portraits", "type": "subject", "description": "Art focused on people's faces or figures", "is_active": True},
            {"name": "Landscapes", "type": "subject", "description": "Natural scenery and environments", "is_active": True},
            {"name": "Still Life", "type": "subject", "description": "Arrangements of inanimate objects", "is_active": True},
            {"name": "Figurative Art", "type": "subject", "description": "Human body, gestures, and forms", "is_active": True},
            {"name": "Animals & Wildlife", "type": "subject", "description": "Animal subjects and wildlife", "is_active": True},
            {"name": "Architecture & Urban Scenes", "type": "subject", "description": "Buildings and cityscapes", "is_active": True},
            {"name": "Fantasy & Mythological", "type": "subject", "description": "Imaginary and mythical subjects", "is_active": True},
            {"name": "Religious & Spiritual", "type": "subject", "description": "Religious and spiritual themes", "is_active": True},
            {"name": "Political / Social Commentary", "type": "subject", "description": "Social and political themes", "is_active": True},
            {"name": "Nature & Environment", "type": "subject", "description": "Natural world and environmental themes", "is_active": True},
            {"name": "Abstract Concepts", "type": "subject", "description": "Non-representational ideas and concepts", "is_active": True},
            {"name": "Other Subject", "type": "subject", "description": "Other subject matter not listed", "is_active": True},
        ]

        # Clear existing categories
        print("🗑️ Clearing existing categories...")
        await categories_collection.delete_many({})
        
        # Insert new categories
        print("📝 Inserting new categories...")
        result = await categories_collection.insert_many(CATEGORIES)
        
        print(f"✅ Successfully inserted {len(result.inserted_ids)} categories into the database")
        
        # Verify the insertion
        count = await categories_collection.count_documents({})
        print(f"📊 Total categories in database: {count}")
        
        # Show categories by type
        medium_count = await categories_collection.count_documents({"type": "medium"})
        style_count = await categories_collection.count_documents({"type": "style"})
        subject_count = await categories_collection.count_documents({"type": "subject"})
        
        print(f"🎨 Medium categories: {medium_count}")
        print(f"🖼 Style categories: {style_count}")
        print(f"🌍 Subject categories: {subject_count}")
        
        print("\n🎉 Category initialization completed successfully!")
        
    except Exception as e:
        print(f"❌ Error initializing categories: {e}")
        import traceback
        traceback.print_exc()
        print("\n💡 Make sure:")
        print("1. MongoDB is running")
        print("2. The database name is correct")
        print("3. The connection string is correct")

if __name__ == "__main__":
    # Run the async function
    asyncio.run(init_categories())