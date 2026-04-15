from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from app.core.config import settings
from app.db.database import get_db
from motor.motor_asyncio import AsyncIOMotorDatabase
from typing import Optional
import logging

logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login")

async def get_db() -> AsyncIOMotorDatabase:
    """Dependency to get database instance"""
    try:
        db = get_db()
        if db is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database not available"
            )
        return db
    except RuntimeError as e:
        logger.error(f"Database error: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection not initialized"
        )


async def get_current_user(token: str = Depends(oauth2_scheme)):
    """Get current authenticated user from JWT token"""
    logger.info(f"🔍 Validating token: {token[:20]}...")
    
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # ✅ FIXED: Use JWT_SECRET_KEY and JWT_ALGORITHM to match token creation
        SECRET_KEY = settings.JWT_SECRET_KEY
        ALGORITHM = settings.JWT_ALGORITHM
        
        logger.info(f"🔑 Using JWT_SECRET_KEY: {SECRET_KEY[:10]}...")
        
        # Decode JWT token
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        user_id: str = payload.get("user_id")
        
        logger.info(f"✅ Token valid for user: {email}")
        logger.info(f"📧 Exact email from token: '{email}' (length: {len(email) if email else 0})")
        
        if email is None:
            logger.error("❌ No email in token payload")
            raise credentials_exception
        
        # ✅ Return the full payload for more robust authorization
        return {
            "email": email.strip(),
            "user_id": user_id,
            "wallet_address": payload.get("wallet_address", ""),
            "role": payload.get("role", "user"),
            "paypal_merchant_id": payload.get("paypal_merchant_id", "")
        }
        
    except JWTError as error:
        logger.error(f"❌ JWT Error: {error}")
        raise credentials_exception


async def get_current_admin(current_user: dict = Depends(get_current_user)):
    """Verify user is an admin"""
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admins only"
        )
    return current_user


async def get_current_normal_user(current_user: dict = Depends(get_current_user)):
    """Verify user is a normal user"""
    if current_user.get("role") != "user":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Users only"
        )
    return current_user