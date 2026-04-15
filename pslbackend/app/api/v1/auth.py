from fastapi import APIRouter, Depends, HTTPException, status, Body
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from fastapi.responses import RedirectResponse  # ✅ ADD THIS
from fastapi import Body
from pydantic import BaseModel
from datetime import datetime, timedelta    
from app.db.models import ForgotPasswordRequest, UserEmailRequest, UserCreate, UserOut, Token,WalletConnectRequest  ,OAuthCallbackRequest  # ✅ ADD THIS
from app.core.security import (
    create_access_token, 
    get_password_hash, 
    verify_password,
    decode_token,
    get_current_user
)
from app.core.config import settings
from app.db.database import get_user_collection, connect_to_mongo, get_db
from .email import send_email
from services.oauth_service import oauth_service  # ✅ ADD THIS
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.db.database import db as database_singleton

import logging
import base64
import secrets
from bson import ObjectId
import random
import time
from typing import Optional, List  # ✅ ADD THIS
from io import BytesIO
import pyotp
import qrcode
# # from app.core.dependencies import get_current_user, get_db
# ✅ REMOVED: from app.core.dependencies import get_db - This was causing conflict!
# ✅ Using get_db from app.db.database (Motor async) instead of app.core.dependencies (synchronous)
# from app.core.dependencies import get_db
from app.db.database import get_db
from app.core.security import get_password_hash, verify_password
router = APIRouter(
    tags=["Auth"],
    prefix="/auth"
)

logger = logging.getLogger(__name__)


class _TwoFactorService:
    """Local 2FA helpers to avoid hard dependency on an external service module."""

    @staticmethod
    def generate_secret() -> str:
        return pyotp.random_base32()

    @staticmethod
    def generate_qr_code(email: str, secret: str, issuer_name: str = "DRM Platform") -> str:
        totp = pyotp.TOTP(secret)
        provisioning_uri = totp.provisioning_uri(name=email, issuer_name=issuer_name)

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=8,
            border=4,
        )
        qr.add_data(provisioning_uri)
        qr.make(fit=True)

        image = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
        return f"data:image/png;base64,{encoded}"

    @staticmethod
    def verify_totp(secret: str, otp_code: str, valid_window: int = 1) -> bool:
        if not secret or not otp_code:
            return False
        try:
            return bool(pyotp.TOTP(secret).verify(str(otp_code).strip(), valid_window=valid_window))
        except Exception:
            return False

    @staticmethod
    def generate_backup_codes(count: int = 10, length: int = 10) -> List[str]:
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        return [
            "".join(secrets.choice(alphabet) for _ in range(length))
            for _ in range(count)
        ]


two_factor_service = _TwoFactorService()


otp_store = {}  # In-memory OTP store
oauth_state_store = {}  # ✅ ADD THIS - Store OAuth states for CSRF protection

# OAuth2 scheme for token authentication
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


# ✅ ADD: Login request model
class LoginRequest(BaseModel):
    username: str  # email
    password: str
    otp_code: Optional[str] = None  # 2FA code

@router.post("/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends(), username: str = Body(...),
    password: str = Body(...),
    otp_code: Optional[str] = Body(None)):
    """
    Login with email, password, and optional 2FA code
    Maintains backward compatibility with existing login flow
    """
    try:
        logger.info(f"🔐 Login attempt for: {form_data.username}")
        
        # Check database is initialized
        if database_singleton.db is None:
            logger.error("❌ Database not initialized")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database not available"
            )
        
        # Find user by email (form_data.username contains the email)
        user = await database_singleton.db.users.find_one({
            "email": form_data.username  # ✅ Using form_data.username (string)
        })
        
        if not user:
            logger.warning(f"❌ User not found: {form_data.username}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # Verify password
        if not verify_password(form_data.password, user.get("hashed_password", "")):
            logger.warning(f"❌ Invalid password for: {form_data.username}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
                # ✅ NEW: Check if 2FA is enabled for this user
        if user.get("two_factor_enabled", False):
            logger.info(f"🔐 2FA is enabled for user: {username}")
            
            # Check if OTP code was provided
            if not otp_code:
                logger.warning(f"⚠️ 2FA required but no OTP code provided")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="2FA code required",
                    headers={
                        "X-2FA-Required": "true"
                    }
                )
            
            # Verify OTP code
            logger.info(f"🔍 Verifying 2FA code for: {username}")
            is_valid = two_factor_service.verify_totp(
                user["two_factor_secret"],
                otp_code
            )
            
            if not is_valid:
                logger.warning(f"❌ Invalid 2FA code for: {username}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid 2FA code"
                )
            
            logger.info(f"✅ 2FA verification successful for: {username}")
        
        # Create access token
        access_token_data = {
            "sub": user["email"],
            "user_id": str(user["_id"]),
            "role": user.get("role", "user")
        }
        
        access_token = create_access_token(data=access_token_data)
        
        logger.info(f"✅ Login successful for: {user['email']}")
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user_id": str(user["_id"]),
            "email": user["email"],
            "role": user.get("role", "user"),
            "username": user.get("username"),
            "wallet_address": user.get("wallet_address"),
            "two_factor_enabled": user.get("two_factor_enabled", False)  # ✅ NEW
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Authentication error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication failed"
        )
    

# ✅ ADD: Alternative OAuth2 compatible endpoint (for backward compatibility)
@router.post("/token")
async def token_login(form_data: OAuth2PasswordRequestForm = Depends()):
    """
    OAuth2 compatible token endpoint (backward compatibility)
    Does NOT support 2FA - use /login endpoint for 2FA
    """
    try:
        logger.info(f"🔐 OAuth2 token request for: {form_data.username}")
        
        if database_singleton.db is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database not available"
            )
        
        user = await database_singleton.db.users.find_one({
            "email": form_data.username
        })
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        if not verify_password(form_data.password, user.get("hashed_password", "")):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # Check if 2FA is enabled - if so, reject OAuth2 login
        if user.get("two_factor_enabled", False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="2FA enabled - use /login endpoint instead"
            )
        
        access_token_data = {
            "sub": user["email"],
            "user_id": str(user["_id"]),
            "role": user.get("role", "user")
        }
        
        access_token = create_access_token(data=access_token_data)
        
        return {
            "access_token": access_token,
            "token_type": "bearer"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ OAuth2 authentication error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication failed"
        )
    

@router.post("/connect-paypal")
async def connect_paypal_disabled(current_user: dict = Depends(get_current_user)):
    raise HTTPException(status_code=410, detail="PayPal support has been removed from this deployment.")


@router.post("/disconnect-paypal")
async def disconnect_paypal_disabled(current_user: dict = Depends(get_current_user)):
    raise HTTPException(status_code=410, detail="PayPal support has been removed from this deployment.")

@router.post("/connect-wallet", response_model=Token)
async def connect_wallet(payload: WalletConnectRequest, current_user: dict = Depends(get_current_user)):
    wallet_address = payload.wallet_address
    if not wallet_address:
        raise HTTPException(status_code=400, detail="Wallet address is required")
    
    # Safely get user's email
    user_email = current_user.get("email") or current_user.get("sub")
    if not user_email:
        raise HTTPException(status_code=400, detail="Cannot identify user email")

    await connect_to_mongo()
    user_collection = get_user_collection()
    
    # Check if wallet is already connected to another account
    existing_wallet_user = await user_collection.find_one({"wallet_address": wallet_address})
    if existing_wallet_user and existing_wallet_user["email"] != user_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This wallet is already connected to another account"
        )
    
    # Update wallet address in MongoDB
    result = await user_collection.update_one(
        {"email": user_email},
        {"$set": {"wallet_address": wallet_address, "updated_at": datetime.utcnow()}}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")

    # Get updated user data
    updated_user = await user_collection.find_one({"email": user_email})
    
    # Create a new JWT with updated wallet info
    access_token_expires = timedelta(hours=24)
    access_token = create_access_token(
        data={
            "sub": user_email,
            "user_id": str(updated_user.get("_id", "")),
            "wallet_address": wallet_address,
            "role": updated_user.get("role", "user")
        },
        expires_delta=access_token_expires
    )

    logger.info(f"Wallet {wallet_address} connected to user: {user_email}")

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": str(updated_user.get("_id", "")),
            "email": user_email,
            "username": updated_user.get("username", ""),
            "wallet_address": wallet_address,
            "is_verified": updated_user.get("is_verified", False),
            "profile_image": updated_user.get("profile_image", ""),
            "bio": updated_user.get("bio", ""),
            "role": updated_user.get("role", "user"),
            "created_at": updated_user.get("created_at"),
            "updated_at": datetime.utcnow()
        }
    }

@router.post("/signup", response_model=UserOut)
async def signup(user: UserCreate):
    """User registration endpoint"""
    try:
        await connect_to_mongo()
        user_collection = get_user_collection()

        # Check if email already exists
        if await user_collection.find_one({"email": user.email}):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )

        # Prepare user data
        user_data = {
            "_id": str(ObjectId()),
            "email": user.email,
            "username": user.username,
            "full_name": user.full_name if hasattr(user, "full_name") else "",
            "role": "user",  # default role
            "is_active": True,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "wallet_address": None  # Not sent from UI
        }

        # Hash password separately
        hashed_password = get_password_hash(user.password)
        user_data["hashed_password"] = hashed_password

        # Insert into MongoDB
        await user_collection.insert_one(user_data)

        # Remove hashed_password before returning
        user_data.pop("hashed_password", None)

        return UserOut(**user_data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Signup error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Registration failed"
        )

# Authentication function remains unchanged
async def authenticate_user(email: str, password: str):
    """Authenticate user credentials"""
    try:
        user_collection = get_user_collection()
        user = await user_collection.find_one({"email": email})
        
        if not user or not verify_password(password, user.get("hashed_password", "")):
            return None
            
        return user
    except Exception as e:
        logger.error(f"Authentication error: {str(e)}")
        return None



# Dependency to get current admin user
async def get_current_admin_user(current_user: dict = Depends(get_current_user)):
    """Dependency that ensures the current user is an admin"""
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. Admin privileges required.",
        )
    return current_user


# Create User
@router.post("/users", response_model=UserOut)
async def create_user(user: UserCreate, current_admin: dict = Depends(get_current_admin_user)):
    users = get_user_collection()
    user_dict = user.dict()
    now = datetime.utcnow()
    user_dict.update({
        "created_at": now,
        "updated_at": now,
        "is_active": True  # <- ensure the field exists
        })
    result = await users.insert_one(user_dict)
    user_dict["_id"] = str(result.inserted_id)
    return user_dict


# Admin-only route to get all users
@router.get("/admin/users")
async def get_all_users(current_admin: dict = Depends(get_current_admin_user)):
    """Get all users - Admin only"""
    try:
        await connect_to_mongo()
        user_collection = get_user_collection()
        
        users = []
        async for user in user_collection.find({}):
            user["_id"] = str(user["_id"])
            # Don't return password hashes
            user.pop("hashed_password", None)
            users.append(user)
        
        logger.info(f"Admin {current_admin['email']} retrieved all users")
        return {"users": users, "total": len(users)}
    
    except Exception as e:
        logger.error(f"Error getting all users: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve users"
        )
    
# ============================================
# GOOGLE OAUTH ENDPOINTS
# ============================================

class GoogleTokenVerify(BaseModel):
    id_token: str

class GoogleLinkRequest(BaseModel):
    id_token: str

@router.get("/google/login")
async def google_login():
    """
    Initiate Google OAuth login flow
    Redirects user to Google consent screen
    """
    try:
        # Generate state for CSRF protection
        state = oauth_service.generate_state()
        
        # Store state with timestamp (expire after 10 minutes)
        oauth_state_store[state] = {
            "timestamp": datetime.utcnow(),
            "used": False
        }
        
        # Clean up old states (older than 10 minutes)
        current_time = datetime.utcnow()
        expired_states = [
            s for s, data in oauth_state_store.items()
            if (current_time - data["timestamp"]).seconds > 600
        ]
        for expired_state in expired_states:
            del oauth_state_store[expired_state]
        
        # Generate Google authorization URL
        redirect_uri = settings.GOOGLE_REDIRECT_URI
        auth_url = oauth_service.get_google_auth_url(redirect_uri, state)
        
        logger.info(f"Initiating Google OAuth with state: {state}")
        
        # Return the auth URL for frontend to redirect
        return {
            "auth_url": auth_url,
            "state": state
        }
        
    except Exception as e:
        logger.error(f"Error initiating Google OAuth: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to initiate Google login"
        )


@router.get("/google/callback")
async def google_callback(code: str, state: str):
    """
    Handle Google OAuth callback
    This endpoint receives the authorization code from Google
    """
    try:
        # Verify state to prevent CSRF attacks
        if state not in oauth_state_store:
            logger.warning(f"Invalid OAuth state received: {state}")
            error_url = f"{settings.FRONTEND_URL}/auth?error=Invalid+state"
            return RedirectResponse(url=error_url)
        
        # Check if state was already used
        if oauth_state_store[state].get("used"):
            logger.warning(f"OAuth state already used: {state}")
            error_url = f"{settings.FRONTEND_URL}/auth?error=State+already+used"
            return RedirectResponse(url=error_url)
        
        # Mark state as used
        oauth_state_store[state]["used"] = True
        
        # Exchange code for token
        logger.info("Exchanging authorization code for access token")
        tokens = await oauth_service.exchange_code_for_token(code)

        # Verify ID token and get user info
        logger.info("Verifying ID token")
        google_user = await oauth_service.verify_google_id_token(tokens.get("id_token"))
        
        if not google_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Google token"
            )
        
        # Create or update user in database
        await connect_to_mongo()
        user_collection = get_user_collection()
        
        existing_user = await user_collection.find_one({"email": google_user["email"]})
        
        if not existing_user:
            new_user = {
                "_id": str(ObjectId()),
                "email": google_user["email"],
                "username": google_user.get("name", google_user["email"].split("@")[0]),
                "full_name": google_user.get("name", ""),
                "hashed_password": None,
                "role": "user",
                "is_active": True,
                "oauth_provider": "google",
                "oauth_id": google_user.get("sub"),
                "profile_picture": google_user.get("picture"),
                "email_verified": google_user.get("email_verified", False),
                "wallet_address": None,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            
            await user_collection.insert_one(new_user)
            existing_user = new_user
        # Create JWT token for our application
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={
                "sub": existing_user["email"],
                "user_id": str(existing_user["_id"]),
                "wallet_address": existing_user.get("wallet_address", ""),
                "paypal_merchant_id": existing_user.get("paypal_merchant_id", ""),
                "role": existing_user.get("role", "user")
            },
            expires_delta=access_token_expires
        )
        
        logger.info(f"✅ Google OAuth successful for user: {existing_user['email']}")
        
        
        # Redirect to frontend with token
        frontend_url = f"{settings.FRONTEND_URL}/auth/callback?token={access_token}&provider=google"
        return RedirectResponse(url=frontend_url)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Google OAuth callback error: {e}")
        import traceback
        traceback.print_exc()

        # Redirect to frontend with error
        error_url = f"{settings.FRONTEND_URL}/auth/error?message=OAuth+failed"
        return RedirectResponse(url=error_url)


@router.post("/google/verify", response_model=Token)
async def verify_google_token(payload: GoogleTokenVerify): 
    """
    Verify Google ID token (for frontend direct Google Sign-In)
    Alternative to OAuth flow for frontend Google Sign-In button
    """
    try:
        # Verify the token
        logger.info("🔄 Verifying Google ID token...")
        google_user = await oauth_service.verify_google_id_token(payload.id_token)
        
        if not google_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Google token"
            )
        
        logger.info(f"✅ Google token verified for: {google_user.get('email')}")
        
        # Get database
        await connect_to_mongo()
        user_collection = get_user_collection()

        # Check if user exists
        existing_user = await user_collection.find_one({"email": google_user["email"]})


        if existing_user:
            # Update OAuth info if needed
            if not existing_user.get("oauth_provider"):
                await user_collection.update_one(
                    {"_id": existing_user["_id"]},
                    {
                        "$set": {
                            "oauth_provider": "google",
                            "oauth_id": google_user.get("sub"),
                            "profile_picture": google_user.get("picture"),
                            "email_verified": google_user.get("email_verified", False),
                            "updated_at": datetime.utcnow()
                        }
                    }
                )
            logger.info(f"✅ Existing user logged in: {google_user['email']}")
        else:
            # Create new user
            new_user = {
                "_id": str(ObjectId()),
                "email": google_user["email"],
                "username": google_user.get("name", google_user["email"].split("@")[0]),
                "full_name": google_user.get("name", ""),
                "hashed_password": None,  # OAuth users don't have passwords
                "role": "user",
                "is_active": True,
                "oauth_provider": "google",
                "oauth_id": google_user.get("sub"),
                "profile_picture": google_user.get("picture"),
                "email_verified": google_user.get("email_verified", False),
                "wallet_address": None,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            
            await user_collection.insert_one(new_user)
            existing_user = new_user
            
            logger.info(f"✅ New Google user created: {google_user['email']}")
        
        # Create JWT for our application
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={
                "sub": existing_user["email"],
                "user_id": str(existing_user["_id"]),
                "wallet_address": existing_user.get("wallet_address", ""),
                "paypal_merchant_id": existing_user.get("paypal_merchant_id", ""),
                "role": existing_user.get("role", "user")
            },
            expires_delta=access_token_expires
        )
        
        logger.info(f"✅ JWT token created for user: {existing_user['email']}")
        
        return {
             "access_token": access_token,
            "token_type": "bearer",
            "user_id": str(existing_user["_id"]),
            "email": existing_user["email"],
            "role": existing_user.get("role", "user"),
            "wallet_address": existing_user.get("wallet_address", ""),
            "profile_picture": existing_user.get("profile_picture", ""),
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Google token verification error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token verification failed"
        )


@router.post("/link-google")
async def link_google_account(
    payload: GoogleLinkRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Link Google account to existing user
    For users who signed up with email/password
    """
    try:
        # Verify Google token
        google_user = await oauth_service.verify_google_id_token(payload.id_token)
        
        if not google_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Google token"
            )
        
        # Check if Google account is already linked to another user
        await connect_to_mongo()
        user_collection = get_user_collection()
        
        existing_google_user = await user_collection.find_one({
            "oauth_id": google_user.get("sub"),
            "oauth_provider": "google"
        })
        
        if existing_google_user:
            if str(existing_google_user["_id"]) != current_user["user_id"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="This Google account is already linked to another user"
                )
            else:
                return {"message": "Google account already linked to your account"}
        
        # Link Google account
        await user_collection.update_one(
            {"_id": current_user["user_id"]},
            {
                "$set": {
                    "oauth_provider": "google",
                    "oauth_id": google_user.get("sub"),
                    "profile_picture": google_user.get("picture"),
                    "email_verified": google_user.get("email_verified", False),
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        logger.info(f"✅ Google account linked to user: {current_user.get('email')}")
        
        return {
            "message": "Google account linked successfully",
            "profile_picture": google_user.get("picture")
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Google account linking error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to link Google account"
        )


@router.post("/unlink-google")
async def unlink_google_account(current_user: dict = Depends(get_current_user)):
    """
    Unlink Google account from user
    """
    try:
        await connect_to_mongo()
        user_collection = get_user_collection()
        
        # Check if user has password (can't unlink if OAuth-only account)
        user = await user_collection.find_one({"_id": current_user["user_id"]})
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        if not user.get("hashed_password"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot unlink Google account. Please set a password first."
            )
        
        # Unlink Google
        result = await user_collection.update_one(
            {"_id": current_user["user_id"]},
            {"$unset": {
                "oauth_provider": "",
                "oauth_id": "",
                "profile_picture": ""
            }, "$set": {
                "updated_at": datetime.utcnow()
            }}
        )
        
        if result.matched_count == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        logger.info(f"Google account unlinked from user: {current_user['email']}")
        
        return {"message": "Google account unlinked successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Google account unlinking error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to unlink Google account"
        )
    
@router.post("/logout")
async def logout(current_user: dict = Depends(get_current_user)):
    email = current_user.get("email") or current_user.get("sub")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )
    return {"message": f"User {email} logged out successfully"}

# Admin-only route to delete a user
@router.delete("/admin/users/{user_id}")
async def delete_user(user_id: str, current_admin: dict = Depends(get_current_admin_user)):
    """Delete a user - Admin only"""
    try:
        await connect_to_mongo()
        user_collection = get_user_collection()
        
        # Don't allow admin to delete themselves
        if user_id == current_admin["user_id"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete your own account"
            )
        
        result = await user_collection.delete_one({"_id": user_id})
        
        if result.deleted_count == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        logger.info(f"Admin {current_admin['email']} deleted user with ID: {user_id}")
        return {"message": "User deleted successfully"}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting user: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete user"
        )

# Admin-only route to update user role
@router.put("/admin/users/{user_id}/role")
async def update_user_role(
    user_id: str, 
    new_role: str = Body(..., embed=True),
    current_admin: dict = Depends(get_current_admin_user)
):
    """Update user role - Admin only"""
    if new_role not in ["user", "admin"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Role must be either 'user' or 'admin'"
        )
    
    try:
        await connect_to_mongo()
        user_collection = get_user_collection()
        
        result = await user_collection.update_one(
            {"_id": user_id},
            {"$set": {
                "role": new_role,
                "updated_at": datetime.utcnow()
            }}
        )
        
        if result.matched_count == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        logger.info(f"Admin {current_admin['email']} updated user {user_id} role to {new_role}")
        return {"message": f"User role updated to {new_role}"}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating user role: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update user role"
        )

@router.post("/update-password")
async def update_password(
    current_password: str,
    new_password: str,
    current_user: dict = Depends(get_current_user)
):
    try:
        user_collection = get_user_collection()
        user = await user_collection.find_one({"email": current_user["email"]})

        if not user or not verify_password(current_password, user["hashed_password"]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is incorrect"
            )

        hashed_password = get_password_hash(new_password)
        await user_collection.update_one(
            {"email": current_user["email"]},
            {"$set": {
                "hashed_password": hashed_password,
                "updated_at": datetime.utcnow()
            }}
        )

        logger.info(f"Password updated for user: {current_user['email']}")
        return {"message": "Password updated successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Password update error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Password update failed"
        )

@router.post("/forgot-password")
async def forgot_password(payload: ForgotPasswordRequest):
    await connect_to_mongo()
    user_collection = get_user_collection()
    user = await user_collection.find_one({"email": payload.email})

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    otp = str(random.randint(100000, 999999))
    otp_store[payload.email] = {"otp": otp, "timestamp": time.time()}

    subject = "Your OTP for Password Reset"
    body = f"Your OTP is {otp}. It is valid for 5 minutes."

    try:
        send_email(subject, body, payload.email)
        return {"message": "OTP sent to your email"}
    except Exception as e:
        logger.error(f"Failed to send OTP email: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to send OTP")

@router.post("/verify-otp")
async def verify_otp(email: str = Body(...), otp: str = Body(...)):
    otp_data = otp_store.get(email)
    if not otp_data:
        raise HTTPException(status_code=404, detail="No OTP found")

    if time.time() - otp_data["timestamp"] > 300:
        del otp_store[email]
        raise HTTPException(status_code=400, detail="OTP expired")

    if otp_data["otp"] != otp:
        raise HTTPException(status_code=400, detail="Invalid OTP")

    return {"message": "OTP verified"}

@router.post("/reset-password")
async def reset_password(email: str = Body(...), otp: str = Body(...), new_password: str = Body(...)):
    otp_data = otp_store.get(email)
    if not otp_data or otp_data["otp"] != otp:
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")

    await connect_to_mongo()
    user_collection = get_user_collection()
    user = await user_collection.find_one({"email": email})

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    hashed_password = get_password_hash(new_password)
    await user_collection.update_one(
        {"email": email},
        {"$set": {
            "hashed_password": hashed_password,
            "updated_at": datetime.utcnow()
        }}
    )

    del otp_store[email]
    return {"message": "Password reset successfully"}

@router.post("/find-user")
async def find_user(payload: UserEmailRequest):
    await connect_to_mongo()
    user_collection = get_user_collection()
    user = await user_collection.find_one({"email": payload.email})

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {"message": f"User found with email {payload.email}"}

# Get current user profile
@router.get("/me")
async def get_current_user_profile(current_user: dict = Depends(get_current_user)):
    """Get current user's profile"""
    return {
        "email": current_user["email"],
        "role": current_user.get("role", "user"),
        "user_id": current_user.get("user_id"),
        "wallet_address": current_user.get("wallet_address"),
        "oauth_provider": current_user.get("oauth_provider"),
        "two_factor_enabled": current_user.get("two_factor_enabled", False),
        "hashed_password": bool(current_user.get("hashed_password")), # ✅ Add this
    }

# Admin dashboard stats
@router.get("/admin/stats")
async def get_admin_stats(current_admin: dict = Depends(get_current_admin_user)):
    """Get admin dashboard statistics"""
    try:
        await connect_to_mongo()
        user_collection = get_user_collection()
        
        total_users = await user_collection.count_documents({})
        total_admins = await user_collection.count_documents({"role": "admin"})
        total_regular_users = await user_collection.count_documents({"role": "user"})
        active_users = await user_collection.count_documents({"is_active": True})
        
        return {
            "total_users": total_users,
            "total_admins": total_admins,
            "total_regular_users": total_regular_users,
            "active_users": active_users
        }
    
    except Exception as e:
        logger.error(f"Error getting admin stats: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve statistics"
        )


@router.get("/2fa/status")
async def get_2fa_status(
    current_user: dict = Depends(get_current_user)
):
    """Get 2FA status for current user"""
    try:
        # ✅ Use database singleton directly
        if database_singleton.db is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database not initialized"
            )
        
        user = await database_singleton.db.users.find_one({"email": current_user["email"]})
        
        return {
            "enabled": user.get("two_factor_enabled", False) if user else False
        }
    except Exception as e:
        logger.error(f"Error checking 2FA status: {e}")
        return {"enabled": False}


@router.post("/2fa/enable")
async def enable_2fa(
    current_user: dict = Depends(get_current_user)
):
    """Enable 2FA - Generate QR code"""
    try:
        logger.info(f"🔄 Enabling 2FA for user: {current_user['email']}")
        
        # ✅ Check database is initialized
        if database_singleton.db is None:
            logger.error("❌ Database not initialized")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database not initialized"
            )
        
        # Check if user exists
        existing_user = await database_singleton.db.users.find_one({"email": current_user["email"]})
        logger.info(f"🔍 User lookup result: {existing_user is not None}")
        
        if not existing_user:
            logger.error(f"❌ No user found with email: {current_user['email']}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found in database"
            )
        
        logger.info(f"👤 Found user: {existing_user.get('email')} (ID: {existing_user.get('_id')})")
        
        # Generate secret
        secret = two_factor_service.generate_secret()
        logger.info(f"🔑 Generated secret: {secret}")
        
        # Generate QR code
        qr_code = two_factor_service.generate_qr_code(
            email=current_user["email"],
            secret=secret
        )
        
        logger.info(f"📱 Generated QR code")
        
        # Store secret in database
        result = await database_singleton.db.users.update_one(
            {"_id": existing_user["_id"]},
            {
                "$set": {
                    "two_factor_secret": secret,
                    "two_factor_enabled": False,
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        logger.info(f"✅ Database update result: matched={result.matched_count}, modified={result.modified_count}")
        
        if result.matched_count == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Failed to update user"
            )
        
        return {
            "success": True,
            "qr_code": qr_code,
            "secret": secret,
            "message": "Scan QR code with your authenticator app"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error enabling 2FA: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to enable 2FA: {str(e)}"
        )


@router.post("/2fa/verify-setup")
async def verify_2fa_setup(
    otp_code: str = Body(..., embed=True),
    current_user: dict = Depends(get_current_user)
):
    """Verify 2FA setup with OTP code"""
    try:
        logger.info(f"🔄 Verifying 2FA setup for user: {current_user['email']}")
        logger.info(f"🔢 OTP code received: {otp_code}")
        
        if database_singleton.db is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database not initialized"
            )
        
        user = await database_singleton.db.users.find_one({"email": current_user["email"]})
        
        if not user:
            logger.error(f"❌ User not found: {current_user['email']}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        logger.info(f"👤 User found: {user.get('email')}")
        logger.info(f"🔑 Stored secret exists: {bool(user.get('two_factor_secret'))}")
        
        if not user.get("two_factor_secret"):
            logger.error(f"❌ No secret stored for user")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="2FA setup not initiated"
            )
        
        # Verify OTP
        logger.info(f"🔍 Verifying OTP with secret...")
        is_valid = two_factor_service.verify_totp(
            user["two_factor_secret"],
            otp_code
        )
        
        logger.info(f"✅ OTP verification result: {is_valid}")
        
        if not is_valid:
            logger.error(f"❌ Invalid OTP code")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid verification code"
            )
        
        # Enable 2FA
        result = await database_singleton.db.users.update_one(
            {"email": current_user["email"]},
            {
                "$set": {
                    "two_factor_enabled": True,
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        logger.info(f"✅ 2FA enabled successfully")
        
        return {
            "success": True,
            "message": "2FA enabled successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error verifying 2FA: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
# ✅ ADD: Request model for 2FA disable
class Disable2FARequest(BaseModel):
    password: str

@router.post("/2fa/disable")
async def disable_2fa(
    request: Disable2FARequest,  # ✅ CHANGED: Use Pydantic model
    current_user: dict = Depends(get_current_user)
):
    """Disable 2FA for user account"""
    try:
        logger.info(f"🔄 Disabling 2FA for user: {current_user['email']}")
        if database_singleton.db is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database not initialized"
            )
        
        user = await database_singleton.db.users.find_one({"email": current_user["email"]})
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Verify password
        from app.core.security import verify_password
        
        if not verify_password(request.password, user.get("hashed_password", "")):
            logger.warning(f"❌ Invalid password for 2FA disable")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect password"
            )
        
        # Disable 2FA
        result = await database_singleton.db.users.update_one(
            {"email": current_user["email"]},
            {
                "$set": {
                    "two_factor_enabled": False,
                    "two_factor_secret": None,
                    "backup_codes": [],
                    "updated_at": datetime.utcnow()
                }
            }
        )
        logger.info(f"✅ 2FA disabled successfully for: {current_user['email']}")
        return {
            "success": True,
            "message": "2FA disabled successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error disabling 2FA: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/2fa/backup-codes")
async def generate_backup_codes(
    current_user: dict = Depends(get_current_user)
):
    """Generate backup codes for 2FA"""
    try:
        if database_singleton.db is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database not initialized"
            )
        
        user = await database_singleton.db.users.find_one({"email": current_user["email"]})
        
        if not user or not user.get("two_factor_enabled"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="2FA must be enabled first"
            )
        
        # Generate new backup codes
        backup_codes = two_factor_service.generate_backup_codes()
        
        # Store backup codes
        await database_singleton.db.users.update_one(
            {"email": current_user["email"]},
            {
                "$set": {
                    "backup_codes": backup_codes,
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        return {
            "success": True,
            "backup_codes": backup_codes
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating backup codes: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


# ============================================
# PASSWORD CHANGE ENDPOINT
# ============================================

@router.post("/change-password")
async def change_password(
    current_password: str = Body(...),
    new_password: str = Body(...),
    current_user: dict = Depends(get_current_user)
):
    """Change password for logged-in user"""
    try:
        if database_singleton.db is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database not initialized"
            )
        
        from app.core.security import verify_password, get_password_hash
        
        user = await database_singleton.db.users.find_one({"email": current_user["email"]})
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Verify current password
        if not verify_password(current_password, user["hashed_password"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Current password is incorrect"
            )
        
        # Validate new password strength
        if len(new_password) < 8:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must be at least 8 characters long"
            )
        
        # Hash new password
        new_hashed_password = get_password_hash(new_password)
        
        # Update password
        await database_singleton.db.users.update_one(
            {"email": current_user["email"]},
            {
                "$set": {
                    "hashed_password": new_hashed_password,
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        return {
            "success": True,
            "message": "Password changed successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error changing password: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@router.post("/set-password")
async def set_password(
    new_password: str = Body(..., embed=True),
    current_user: dict = Depends(get_current_user)
):
    """
    Set password for OAuth users who don't have one
    This enables email/password login as backup
    """
    try:
        logger.info(f"🔐 Setting password for user: {current_user['email']}")
        
        if database_singleton.db is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database not initialized"
            )
        
        user = await database_singleton.db.users.find_one({"email": current_user["email"]})
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # ✅ Check if user already has a password
        if user.get("hashed_password"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password already set. Use change-password endpoint instead."
            )
        
        # Validate new password strength
        if len(new_password) < 8:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must be at least 8 characters long"
            )
        
        from app.core.security import get_password_hash
        
        # Hash new password
        hashed_password = get_password_hash(new_password)
        
        # Set password
        await database_singleton.db.users.update_one(
            {"email": current_user["email"]},
            {
                "$set": {
                    "hashed_password": hashed_password,
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        logger.info(f"✅ Password set successfully for: {current_user['email']}")
        
        return {
            "success": True,
            "message": "Password set successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error setting password: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )