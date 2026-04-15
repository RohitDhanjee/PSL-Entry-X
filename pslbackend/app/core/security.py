from fastapi import HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from app.core.config import settings
from datetime import datetime, timedelta
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Authentication scheme
http_bearer = HTTPBearer(auto_error=True)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hashed version"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Generate password hash"""
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT token with expiration"""
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    
    # Ensure required fields
    if "user_id" not in to_encode:
        to_encode["user_id"] = to_encode.get("sub")  # Fallback to sub if user_id not provided
    
    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow()
    })

    # ✅ FIXED: Use JWT_SECRET_KEY instead of SECRET_KEY to match decode_token
    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY, 
        algorithm=settings.JWT_ALGORITHM
    )
    
    return encoded_jwt

def decode_token(token: str) -> Optional[dict]:
    """Decode JWT token and return payload if valid"""
    try:
        # Check token format first
        token_parts = token.split('.')
        logger.debug(f"Received token has {len(token_parts)} parts")
        # ... logging ...
        
        if len(token_parts) != 3:
            logger.error(f"Invalid token format: expected 3 parts, got {len(token_parts)}")
            return None
            
        # Debug the settings being used
        # logger.debug(f"Decoding with JWT_SECRET_KEY: {settings.JWT_SECRET_KEY[:10]}...")
        # logger.debug(f"Decoding with JWT_ALGORITHM: {settings.JWT_ALGORITHM}")
            
        # ✅ VERIFY: This was already using JWT_SECRET_KEY, so now they match
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY, 
            algorithms=[settings.JWT_ALGORITHM]
        )
        
        logger.debug(f"Successfully decoded token payload: {payload}")
        return payload
        
    except jwt.ExpiredSignatureError:
        logger.error("Token has expired")
        return None
    except JWTError as e:
        logger.error(f"JWT decode error: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error decoding token: {e}")
        return None


async def get_current_user(token: HTTPAuthorizationCredentials = Depends(http_bearer)):
    """Dependency to extract current user from JWT"""
    if token is None:
        logger.error("Authorization header missing")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authorization header missing"
        )

    logger.debug(f"Processing token: {token.credentials[:20]}...")
    
    payload = decode_token(token.credentials)
    if payload is None:
        logger.error("Token decode failed")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid token"
        )

    # Debug info
    logger.debug(f"Token payload: {payload}")

    # Verify required claims
    required_claims = ["sub", "user_id", "exp"]
    for claim in required_claims:
        if claim not in payload:
            logger.error(f"Missing required claim: {claim} in payload: {payload}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required claim: {claim}"
            )

    logger.debug(f"Authentication successful for user: {payload['sub']}")
    
    # Return consistent dictionary structure
    user_dict = {
        "id": payload["user_id"],  # Add 'id' field for compatibility
        "user_id": payload["user_id"],
        "email": payload["sub"],
        "sub": payload["sub"],
        "wallet_address": payload.get("wallet_address", ""),
        "role": payload.get("role", "user"),
        "username": payload.get("username", payload["sub"].split("@")[0])  # Add username
    }
    
    logger.debug(f"Returning user dict: {user_dict}")
    return user_dict


async def get_current_admin_user(current_user: dict = Depends(get_current_user)):
    """Dependency that ensures the current user is an admin"""
    if current_user.get("role") != "admin":
        logger.warning(f"Non-admin user {current_user.get('email')} attempted admin access")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. Admin privileges required."
        )
    return current_user

async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(http_bearer)
) -> Optional[dict]:
    """
    Optional dependency - returns user if authenticated, None otherwise.
    """
    try:
        if credentials:
            return await get_current_user(credentials)
        return None
    except HTTPException:
        return None
    except Exception as e:
        logger.warning(f"Optional auth failed: {e}")
        return None


# ============================================
# SINGLE-USE IMAGE ACCESS TOKEN UTILITIES
# ============================================

import uuid

from typing import Optional, Union

def create_image_token(token_id: Union[int, str], expires_minutes: int = 5) -> str:
    """
    Create a SINGLE-USE JWT token for image access.
    These tokens allow viewing medium-resolution images on the website.
    Each token can only be used ONCE - after use, it becomes invalid.
    
    Args:
        token_id: The ticket token ID
        expires_minutes: Token validity in minutes (default 5)
    
    Returns:
        JWT token string with unique nonce for single-use tracking
    """
    expire = datetime.utcnow() + timedelta(minutes=expires_minutes)
    
    # Generate unique nonce for single-use tracking
    nonce = str(uuid.uuid4())
    
    payload = {
        "type": "image_access",
        "token_id": token_id,
        "nonce": nonce,  # Unique ID for single-use tracking
        "exp": expire,
        "iat": datetime.utcnow()
    }
    
    encoded = jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM
    )
    
    logger.debug(f"Created single-use image token for ticket {token_id}, nonce: {nonce[:8]}...")
    return encoded


def verify_image_token(token: str, expected_token_id: Union[int, str]) -> bool:
    """
    Verify a SINGLE-USE image access token.
    After successful verification, the token is marked as used in Redis.
    Subsequent attempts to use the same token will fail.
    
    Args:
        token: The JWT token to verify
        expected_token_id: The ticket token ID that should match
    
    Returns:
        True if token is valid, unused, and matches the token_id, False otherwise
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )
        
        # Verify token type and token_id match
        if payload.get("type") != "image_access":
            logger.warning(f"Invalid token type: {payload.get('type')}")
            return False
            
        if payload.get("token_id") != expected_token_id:
            logger.warning(f"Token ID mismatch: expected {expected_token_id}, got {payload.get('token_id')}")
            return False
        
        # Get nonce for single-use check
        nonce = payload.get("nonce")
        if not nonce:
            logger.warning("Token missing nonce - invalid token")
            return False
        
        # Check if token has already been used (via Redis)
        try:
            from services.redis_cache_service import cache as redis_cache
            
            used_key = f"image_token_used:{nonce}"
            
            # Check if already used
            if redis_cache.redis.exists(used_key):
                logger.warning(f"🚫 Token already used! nonce: {nonce[:8]}... - REJECTING")
                return False
            
            # Mark as used with 10 minute TTL (cleanup old entries)
            redis_cache.redis.setex(used_key, 600, "1")
            logger.info(f"✅ Token verified and marked as USED - nonce: {nonce[:8]}...")
            
        except Exception as redis_err:
            # If Redis fails, fall back to allowing the token (fail-open for user experience)
            logger.warning(f"Redis check failed, allowing token: {redis_err}")
        
        return True
        
    except jwt.ExpiredSignatureError:
        logger.debug(f"Image token expired for ticket {expected_token_id}")
        return False
    except JWTError as e:
        logger.warning(f"Image token verification failed: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error verifying image token: {e}")
        return False