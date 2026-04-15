import asyncio
import os
from motor.motor_asyncio import AsyncIOMotorClient

# Manual load of .env
env_vars = {}
with open(".env", "r") as f:
    for line in f:
        if "=" in line and not line.startswith("#"):
            key, value = line.strip().split("=", 1)
            env_vars[key] = value

async def check():
    uri = env_vars.get("MONGODB_URI")
    if not uri:
        print("MONGODB_URI not found in .env")
        return

    print(f"🔗 Checking Atlas Cluster databases...")
    client = AsyncIOMotorClient(uri)
    
    dbs = await client.list_database_names()
    print(f"All Databases: {dbs}")
    
    for db_name in dbs:
        if db_name in ["admin", "local", "config"]: continue
        db = client[db_name]
        col_list = await db.list_collection_names()
        if "artworks" in col_list:
            count = await db["artworks"].count_documents({})
            print(f"   Database '{db_name}' has 'artworks' collection with {count} documents")
            if count > 0:
                print(f"      PSL Tickets in {db_name}.artworks: {await db['artworks'].count_documents({'is_psl_ticket': True})}")

if __name__ == "__main__":
    asyncio.run(check())
