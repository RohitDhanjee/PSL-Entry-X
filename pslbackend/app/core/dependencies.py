from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pymongo import MongoClient
from typing import Optional
import os

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login")

# MongoDB connection
MONGO_URL = os.getenv("MONGODB_URI")
client = MongoClient(MONGO_URL)
db_instance = client.get_database("art_drm_local")

def get_db():
    """Get database instance"""
    return db_instance


async def get_current_user(token: str = Depends(oauth2_scheme)):
    """
    Get current authenticated user from JWT token
    """
    print(f"🔍 Validating token: {token[:20]}...") # ✅ ADD DEBUG
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # Decode JWT token
        SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-here-change-this-in-production")
        ALGORITHM = "HS256"

        print(f"🔑 Using SECRET_KEY: {SECRET_KEY[:10]}...") # ✅ ADD DEBUG
        
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        
        print(f"✅ Token valid for user: {email}") # ✅ ADD DEBUG
        print(f"📧 Exact email from token: '{email}' (length: {len(email)})")  # ✅ ADD THIS
        if email is None:
            print("❌ No email in token payload")
            raise credentials_exception
            
        # ✅ ADD: Return the exact email with no modifications
        return {"email": email.strip()}  # Remove any whitespace
        
    except JWTError as error:
        print(f"❌ JWT Error: {error}") # ✅ ADD DEBUG
        raise credentials_exception