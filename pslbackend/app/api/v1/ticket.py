from fastapi import APIRouter, Depends, HTTPException, status, Form, UploadFile, File, Query, Request
from datetime import datetime
import time
from typing import Any, Dict, List, Optional
from app.core.security import get_current_user, get_current_user_optional
from app.db.database import get_artwork_collection, get_db
from app.db.schemas import ArtworkSchema
from services.web3_service import web3_service
import logging
from PIL import Image
import io
import hashlib
import imagehash
from motor.motor_asyncio import AsyncIOMotorGridFSBucket
from app.db.database import get_user_collection, get_transaction_collection, get_license_collection
from bson import ObjectId
import tempfile
import base64
import aiohttp
import asyncio
import re
import json
from web3 import Web3
from functools import lru_cache
from collections import defaultdict
# Add with other imports (after line 41)
from services.redis_cache_service import (
    cache,
    get_artworks_cache,
    set_artworks_cache,
    invalidate_artworks_cache
)

from app.db.models import (
    ArtworkCreate, ArtworkUpdate, ArtworkBase as Ticket, ArtworkInDB,
    ArtworkPublic, ArtworkListResponse, User, SaleConfirmation,
    TransactionCreate, TransactionType, TransactionStatus, ContractCallRequest, ContractCallResponse,
    ImageMetadata, DuplicateCheckResult, AIClassificationResult, SaleConfirmationRequest, SaleTransactionRequest
)
from app.core.config import settings
from app.utils.ticket import resolve_artwork_identifier

AI_DETECTION_ENABLED = False

try:
    from services.user_history_service import UserHistoryService
except ModuleNotFoundError:
    class UserHistoryService:
        @staticmethod
        async def log_user_action(*args, **kwargs):
            return False

try:
    from services.paypal_service import get_paypal_service, paypal_service
except ModuleNotFoundError:
    class _DisabledPayPalService:
        async def register_artwork_with_paypal(self, *args, **kwargs):
            return {"success": False, "error": "PayPal integration is disabled in this build"}

        async def capture_payment(self, *args, **kwargs):
            return {"success": False, "error": "PayPal integration is disabled in this build"}

        async def payout_to_seller(self, *args, **kwargs):
            return {"success": False, "error": "PayPal integration is disabled in this build"}

        async def create_artwork_sale_order(self, *args, **kwargs):
            return {"success": False, "error": "PayPal integration is disabled in this build"}

        async def create_license_purchase_order(self, *args, **kwargs):
            return {"success": False, "error": "PayPal integration is disabled in this build"}

    _paypal_fallback = _DisabledPayPalService()

    def get_paypal_service():
        return _paypal_fallback

    paypal_service = _paypal_fallback

router = APIRouter(prefix="/tickets", tags=["tickets"])

# ✅ OPTIMIZATION: Simple in-memory cache for ticket counts (TTL: 30 seconds)
_artwork_counts_cache = {}
_counts_cache_ttl = 30  # seconds

def get_cached_counts():
    """Get cached ticket counts if still valid"""
    if _artwork_counts_cache:
        cached_time, cached_data = _artwork_counts_cache.get("data", (0, None))
        if time.time() - cached_time < _counts_cache_ttl:
            return cached_data
    return None

def set_cached_counts(data):
    """Cache ticket counts"""
    _artwork_counts_cache["data"] = (time.time(), data)

def clear_counts_cache():
    """Clear ticket counts cache (call when tickets are added/removed/modified)"""
    _artwork_counts_cache.clear()
    logger.debug("🗑️ Cleared ticket counts cache")

# async def get_current_registration_fee():
#     """Get the current registration platform fee percentage from admin settings"""
#     db = get_db()
#     settings = await db.system_settings.find_one({"_id": "global_settings"})
    
#     if settings:
#         # Check for registration_platform_fee_percentage first
#         fee = settings.get("registration_platform_fee_percentage")
#         if fee is None:
#             # Fallback to default_platform_fee_percentage if registration fee not set
#             fee = settings.get("default_platform_fee_percentage", 2)
#             logger.info(f"💰 Registration fee not set, using purchasing fee: {fee}%")
#         else:
#             logger.info(f"💰 Retrieved registration platform fee from database: {fee}%")
#         return float(fee) if fee is not None else 2
#     else:
#         logger.warning(f"⚠️ No global settings found, using default registration fee: 2%")
#         return 2
@router.get("/settings/platform-fee")
async def get_platform_fee():
    db = get_db()
    # Fetch from the same collection the Admin panel updates
    settings = await db.system_settings.find_one({"_id": "global_settings"})
    
    # Return default 2.5% if not set
    if not settings:
        return {"platform_fee": 2.5}
        
    return {"platform_fee": settings.get("platform_fee", 2.5)}
logger = logging.getLogger(__name__)


def _ensure_wirefluid_network(network_name: Optional[str]) -> str:
    normalized = (network_name or "wirefluid").strip().lower()
    if normalized != "wirefluid":
        raise HTTPException(
            status_code=400,
            detail="Only WireFluid network is supported."
        )
    return "wirefluid"


def _resolve_wirefluid_contract_address() -> Optional[str]:
    """Resolve contract address from initialized Web3 service first, then env fallbacks."""
    service_contract = getattr(web3_service, "contract", None)
    service_contract_address = getattr(service_contract, "address", None) if service_contract else None
    if service_contract_address:
        return service_contract_address

    return (
        getattr(settings, "WIREFLUID_CONTRACT_ADDRESS", None)
        or getattr(settings, "CONTRACT_ADDRESS", None)
    )

# ✅ License ID Generation System with Numeric Prefixes (similar to token_id)
LICENSE_ID_PREFIXES = {
    "paypal": {"numeric": 1, "display": "p"},      # PayPal: 1000001, 1000002... (display: p_1, p_2...)
    "stripe": {"numeric": 2, "display": "s"},      # Stripe: 2000001, 2000002... (display: s_1, s_2...)
    "credit_card": {"numeric": 3, "display": "c"},  # Credit Card: 3000001, 3000002... (display: c_1, c_2...)
    "on-chain": {"numeric": 0, "display": None},    # On-chain: Uses blockchain license_id directly (0, 1, 2...)
}

async def generate_license_id(
    payment_method: str,
    licenses_collection
) -> int:
    """
    Generate license_id with numeric prefix for off-chain licenses.
    
    Args:
        payment_method: 'paypal', 'stripe', 'credit_card', etc. (or 'crypto' for on-chain)
        licenses_collection: MongoDB collection for licenses
    
    Returns:
        int: license_id with prefix (e.g., 1000001 for PayPal)
    """
    # On-chain licenses use blockchain ID directly (no generation needed)
    if payment_method == "crypto" or payment_method == "on-chain":
        return None  # On-chain licenses get ID from blockchain
    
    # Determine the actual method
    if payment_method == "off-chain":
        method_key = "paypal"  # Default to PayPal
    else:
        method_key = payment_method.lower()
    
    # Get prefix configuration
    prefix_config = LICENSE_ID_PREFIXES.get(method_key)
    if not prefix_config:
        # Default to PayPal if method not found
        logger.warning(f"⚠️ Unknown payment method '{payment_method}', defaulting to PayPal")
        prefix_config = LICENSE_ID_PREFIXES["paypal"]
        method_key = "paypal"
    
    numeric_prefix = prefix_config["numeric"]
    
    # Find the highest license_id for this payment method
    # Query for licenses with license_id in the range for this method
    # e.g., for PayPal (prefix 1): 1000000 <= license_id < 2000000
    min_license_id = numeric_prefix * 1000000
    max_license_id = (numeric_prefix + 1) * 1000000  # Exclusive upper bound
    
    # Find the highest existing license_id in this range
    pipeline = [
        {
            "$match": {
                "license_id": {"$gte": min_license_id, "$lt": max_license_id},
                "payment_method": {"$ne": "crypto"}  # Exclude on-chain licenses
            }
        },
        {
            "$sort": {"license_id": -1}
        },
        {
            "$limit": 1
        },
        {
            "$project": {"license_id": 1}
        }
    ]
    
    cursor = licenses_collection.aggregate(pipeline)
    result = await cursor.to_list(length=1)
    
    if result and result[0].get("license_id"):
        # Get next sequential number
        last_license_id = result[0]["license_id"]
        sequence = last_license_id - min_license_id + 1
    else:
        # First license for this payment method
        sequence = 1
    
    # Generate license_id with prefix
    license_id = min_license_id + sequence
    
    logger.info(f"✅ Generated license_id: {license_id} for payment method: {method_key}")
    
    return license_id

# ✅ Token ID Generation System with Numeric Prefixes
# Maps registration methods to numeric prefixes and display prefixes
REGISTRATION_METHOD_PREFIXES = {
    "paypal": {"numeric": 1, "display": "p"},      # PayPal: 1000001, 1000002... (display: p_1, p_2...)
    "stripe": {"numeric": 2, "display": "s"},      # Stripe: 2000001, 2000002... (display: s_1, s_2...)
    "credit_card": {"numeric": 3, "display": "c"},  # Credit Card: 3000001, 3000002... (display: c_1, c_2...)
    "on-chain": {"numeric": 0, "display": None},    # On-chain: 0, 1, 2... (no display_id, uses blockchain token_id)
}

async def generate_token_id_and_display_id(
    registration_method: str,
    artworks_collection
) -> tuple[int, Optional[str]]:
    """
    Generate token_id with numeric prefix and display_id for off-chain tickets.
    
    Args:
        registration_method: 'on-chain', 'off-chain', 'paypal', 'stripe', etc.
        artworks_collection: MongoDB collection for tickets
    
    Returns:
        tuple: (token_id: int, display_id: Optional[str])
        - For on-chain: token_id comes from blockchain, display_id is None
        - For off-chain: token_id has numeric prefix (e.g., 1000001), display_id is string (e.g., 'p_1')
    """
    # Determine the actual method (handle 'off-chain' -> 'paypal' for now)
    if registration_method == "off-chain":
        # Default to PayPal for off-chain (can be extended later)
        method_key = "paypal"
    elif registration_method == "on-chain":
        # On-chain tickets get token_id from blockchain, not generated here
        return None, None
    else:
        method_key = registration_method.lower()
    
    # Get prefix configuration
    prefix_config = REGISTRATION_METHOD_PREFIXES.get(method_key)
    if not prefix_config:
        # Default to PayPal if method not found
        logger.warning(f"Unknown registration method '{registration_method}', defaulting to PayPal")
        prefix_config = REGISTRATION_METHOD_PREFIXES["paypal"]
        method_key = "paypal"
    
    numeric_prefix = prefix_config["numeric"]
    display_prefix = prefix_config["display"]
    
    # Find the highest token_id for this method
    # Query for tickets with token_id in the range for this method
    # e.g., for PayPal (prefix 1): 1000000 <= token_id < 2000000
    min_token_id = numeric_prefix * 1000000
    max_token_id = (numeric_prefix + 1) * 1000000  # Exclusive upper bound
    
    # Find the highest existing token_id in this range
    pipeline = [
        {
            "$match": {
                "token_id": {"$gte": min_token_id, "$lt": max_token_id}
            }
        },
        {
            "$sort": {"token_id": -1}
        },
        {
            "$limit": 1
        },
        {
            "$project": {"token_id": 1}
        }
    ]
    
    cursor = artworks_collection.aggregate(pipeline)
    result = await cursor.to_list(length=1)
    
    if result and result[0].get("token_id"):
        # Get next sequential number
        last_token_id = result[0]["token_id"]
        sequence = last_token_id - min_token_id + 1
    else:
        # First ticket for this method
        sequence = 1
    
    # Generate token_id with prefix
    token_id = min_token_id + sequence
    
    # Generate display_id (only for off-chain methods)
    display_id = f"{display_prefix}_{sequence}" if display_prefix else None
    
    logger.info(f"✅ Generated token_id: {token_id}, display_id: {display_id} for method: {method_key}")
    
    return token_id, display_id


async def get_current_global_fee():
    """Get the current global platform fee percentage from admin settings"""
    db = get_db()
    settings = await db.system_settings.find_one({"_id": "global_settings"})
    
    if settings:
        # Admin saves to 'platform_fee', but we might have 'default_platform_fee_percentage' from older versions
        fee = settings.get("platform_fee")
        if fee is None:
            fee = settings.get("default_platform_fee_percentage", 2.5)
            
        return float(fee)
    else:
        logger.warning(f"⚠️ No global settings found, using default platform fee: 2.5%")
        return 2.5

async def is_paypal_enabled() -> bool:
    """PayPal support has been removed from this deployment."""
    return False

# Initialize GridFS for binary image storage
def get_gridfs():
    """Get GridFS bucket for image storage"""
    from app.db.database import get_db
    db = get_db()
    return AsyncIOMotorGridFSBucket(db, bucket_name="artwork_images")

# ✅ Enhanced Image Processing Class with Duplicate Detection
class ImageProcessor:
    @staticmethod
    async def process_image(image_data: bytes, max_size: int = 5 * 1024 * 1024) -> bytes:
        try:
            img = Image.open(io.BytesIO(image_data))

            if img.mode in ('RGBA', 'LA'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[-1])
                img = background

            max_dimension = 2000
            if max(img.size) > max_dimension:
                ratio = max_dimension / max(img.size)
                new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
                img = img.resize(new_size, Image.Resampling.LANCZOS)

            output = io.BytesIO()
            img.save(output, format='JPEG', quality=85, optimize=True)
            processed_data = output.getvalue()

            return processed_data
        except Exception as e:
            logger.error(f"Image processing failed: {str(e)}")
            raise HTTPException(status_code=400, detail=f"Image processing failed: {str(e)}")

    @staticmethod
    def get_perceptual_hash(file_bytes: bytes) -> str:
        """Generate perceptual hash for similar image detection"""
        try:
            image = Image.open(io.BytesIO(file_bytes))
            # FIXED: Use consistent hash size and algorithm
            phash = imagehash.phash(image, hash_size=8)  # Explicit hash size
            hash_str = str(phash)
            logger.debug(f"Generated perceptual hash: {hash_str}")
            return hash_str
        except Exception as e:
            logger.error(f"Error generating perceptual hash: {e}")
            return ""

    @staticmethod
    def get_file_hash(file_bytes: bytes) -> str:
        """Generate SHA256 hash for exact duplicate detection"""
        try:
            hash_obj = hashlib.sha256(file_bytes)
            hash_str = hash_obj.hexdigest()
            logger.debug(f"Generated file hash: {hash_str[:16]}...")
            return hash_str
        except Exception as e:
            logger.error(f"Error generating file hash: {e}")
            return ""

    @staticmethod
    async def check_duplicates(image_data: bytes) -> DuplicateCheckResult:
        """Check for duplicate images using multiple methods"""
        try:
            artworks_collection = get_artwork_collection()
            logger.info("=== DUPLICATE CHECK DEBUG START ===")
            
            # Count total tickets in database
            total_count = await artworks_collection.count_documents({})
            logger.info(f"Total tickets in database: {total_count}")
            
            # 1. Exact hash check
            file_hash = ImageProcessor.get_file_hash(image_data)
            logger.info(f"Generated file hash: {file_hash[:20]}...")
            
            # Debug: Check what hashes exist in database
            existing_hashes = await artworks_collection.find(
                {"image_metadata.file_hash": {"$exists": True}}, 
                {"image_metadata.file_hash": 1, "title": 1}
            ).to_list(length=10)
            
            logger.info(f"Found {len(existing_hashes)} tickets with file hashes:")
            for ticket in existing_hashes:
                stored_hash = ticket.get("image_metadata", {}).get("file_hash", "None")
                title = ticket.get("title", "Untitled")
                logger.info(f"  - {title}: {stored_hash[:20]}...")
            
            existing = await artworks_collection.find_one({"image_metadata.file_hash": file_hash})
            if existing:
                logger.warning(f"EXACT DUPLICATE FOUND: {existing.get('title', 'Untitled')}")
                return DuplicateCheckResult(
                    is_duplicate=True,
                    duplicate_type="exact",
                    similarity_score=1.0,
                    existing_artwork_id=str(existing["_id"]),
                    message="Exact duplicate found"
                )

            # 2. Perceptual hash check
            perceptual_hash = ImageProcessor.get_perceptual_hash(image_data)
            logger.info(f"Generated perceptual hash: {perceptual_hash}")
            
            # Debug: Check what perceptual hashes exist (limited for logging)
            existing_phashes_debug = await artworks_collection.find(
                {"image_metadata.perceptual_hash": {"$exists": True, "$ne": None}}, 
                {"image_metadata.perceptual_hash": 1, "title": 1}
            ).to_list(length=10)
            
            logger.info(f"Found {len(existing_phashes_debug)} tickets with perceptual hashes (showing first 10):")
            for ticket in existing_phashes_debug:
                stored_phash = ticket.get("image_metadata", {}).get("perceptual_hash", "None")
                title = ticket.get("title", "Untitled")
                logger.info(f"  - {title}: {stored_phash}")
            
            # Get ALL tickets with perceptual hashes for actual comparison
            existing_phashes = await artworks_collection.find(
                {"image_metadata.perceptual_hash": {"$exists": True, "$ne": None}}, 
                {"image_metadata.perceptual_hash": 1, "title": 1}
            ).to_list(length=None)  # No limit - fetch all
            
            logger.info(f"Comparing with {len(existing_phashes)} total tickets for perceptual hash similarity")
            
            # Test perceptual hash comparison
            for doc in existing_phashes:
                if "image_metadata" in doc and "perceptual_hash" in doc["image_metadata"]:
                    try:
                        stored_phash_str = doc["image_metadata"]["perceptual_hash"]
                        
                        if isinstance(stored_phash_str, str) and len(stored_phash_str) == len(perceptual_hash):
                            current_phash = imagehash.hex_to_hash(perceptual_hash)
                            stored_phash = imagehash.hex_to_hash(stored_phash_str)
                            distance = current_phash - stored_phash
                            
                            logger.info(f"Comparing with {doc.get('title', 'Untitled')}: distance = {distance}")
                            
                            if distance <= 8:
                                logger.warning(f"PERCEPTUAL DUPLICATE FOUND: {doc.get('title', 'Untitled')}, distance: {distance}")
                                return DuplicateCheckResult(
                                    is_duplicate=True,
                                    duplicate_type="perceptual",
                                    similarity_score=1.0 - (distance / 64.0),
                                    existing_artwork_id=str(doc["_id"]),
                                    message=f"Perceptually similar image found (distance: {distance})"
                                )
                    except Exception as e:
                        logger.error(f"Error comparing perceptual hash with {doc.get('title', 'Untitled')}: {e}")
                        continue

            logger.info("AI embedding duplicate check is disabled")

            logger.info("=== NO DUPLICATES FOUND ===")
            return DuplicateCheckResult(
                is_duplicate=False,
                message="No duplicates found"
            )

        except Exception as e:
            logger.error(f"Duplicate check failed: {str(e)}", exc_info=True)
            return DuplicateCheckResult(
                is_duplicate=False,
                message=f"Duplicate check failed: {str(e)}"
            )

    @staticmethod
    async def classify_ai_content(image_data: bytes, model_choice: str = "gemini-2.5-flash") -> AIClassificationResult:
        """AI classification is disabled for this deployment."""
        return AIClassificationResult(
            is_ai_generated=False,
            confidence=0.0,
            description="AI classification is disabled for this deployment",
            model_used=model_choice,
            generated_description=""
        )
    @staticmethod
    def process_classification_result(result):
        """Consistently process AI classification results from all providers"""
        try:
            provider = result.get('provider')
            classification_data = result.get('result')
            
            # Handle different response formats consistently
            if isinstance(classification_data, tuple):
                # Tuple format: (label, details, description)
                if len(classification_data) >= 3:
                    label = classification_data[0]
                    details = classification_data[1]
                    description = classification_data[2]
                    
                    # FIXED: Handle the case where details is a JSON string
                    if isinstance(details, str) and details.strip().startswith('{'):
                        try:
                            # Try to parse the JSON string
                            json_data = json.loads(details)
                            label = json_data.get("label", label)
                            details = json_data.get("details", details)
                            description = json_data.get("description", description)
                            logger.info(f"Parsed JSON from details: label={label}")
                        except json.JSONDecodeError:
                            # If JSON parsing fails, keep original values
                            logger.warning("Failed to parse JSON from details field")
                            pass
                else:
                    # Handle incomplete tuple
                    label = classification_data[0] if len(classification_data) > 0 else None
                    details = classification_data[1] if len(classification_data) > 1 else ""
                    description = classification_data[2] if len(classification_data) > 2 else ""
            else:
                # Handle other formats (string, dict, etc.)
                label = None
                details = ""
                description = str(classification_data) if classification_data else ""

            # FIXED: Better logging to see what we're working with
            logger.info(f"Processing classification - label: {label}, details: {details[:100]}...")
            
            # Consistent AI detection logic
            is_ai_generated = False
            confidence = 0.0
            
            # Check if label indicates AI
            if label and label.upper() == "AI":
                is_ai_generated = True
                confidence = 0.85  # High confidence when explicitly labeled AI
            elif label and label.upper() == "REAL":
                is_ai_generated = False
                confidence = 0.85
            elif label and label.upper() == "HUMAN":
                is_ai_generated = False
                confidence = 0.85
            else:
                # Fallback: analyze description for AI indicators
                ai_indicators = ["AI", "artificial intelligence", "generated", "digital ticket", "algorithm", "neural network", "synthetic"]
                human_indicators = ["hand", "painted", "drawn", "brush", "canvas", "physical", "traditional", "human"]
                
                description_lower = description.lower() if description else ""
                details_lower = details.lower() if details else ""
                combined_text = f"{description_lower} {details_lower}"
                
                ai_indicator_count = sum(1 for indicator in ai_indicators if indicator in combined_text)
                human_indicator_count = sum(1 for indicator in human_indicators if indicator in combined_text)
                
                if ai_indicator_count > human_indicator_count:
                    is_ai_generated = True
                    confidence = min(0.7, ai_indicator_count * 0.15)
                else:
                    is_ai_generated = False
                    confidence = min(0.7, human_indicator_count * 0.15)
            
            logger.info(f"Final decision - is_ai_generated: {is_ai_generated}, confidence: {confidence}")
            
            return {
                "is_ai_generated": is_ai_generated,
                "confidence": confidence,
                "label": label,
                "description": description,
                "details": details,
                "provider": provider
            }
            
        except Exception as e:
            logger.error(f"Error processing classification result: {str(e)}")
            return {
                "is_ai_generated": False,
                "confidence": 0.0,
                "label": "ERROR",
                "description": f"Classification error: {str(e)}",
                "details": "",
                "provider": "error"
            }

    @staticmethod
    async def store_image_binary(image_data: bytes, filename: str, content_type: str) -> str:
        """Store image binary data in GridFS and return string ID"""
        try:
            fs = get_gridfs()
            # Add debug logging
            logger.info(f"Storing image in GridFS: {filename}, size: {len(image_data)} bytes")
            
            gridfs_id = await fs.upload_from_stream(filename, image_data, metadata={
                "content_type": content_type,
                "uploaded_at": datetime.utcnow()
            })
            
            # Convert ObjectId to string for storage
            gridfs_id_str = str(gridfs_id)
            logger.info(f"Image stored successfully with ID: {gridfs_id_str}")
            
            return gridfs_id_str
        except Exception as e:
            logger.error(f"Binary image storage failed: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to store image: {str(e)}")
        
# ✅ IPFS Upload Service (unchanged)
class IPFSService:
    """Service class to handle IPFS uploads with multiple providers"""
    
    @staticmethod
    async def upload_to_pinata(file_data: bytes, filename: str) -> str:
        """Upload to Pinata.cloud with proper error handling"""
        try:
            pinata_api_key = settings.PINATA_API_KEY
            pinata_secret_api_key = settings.PINATA_SECRET_API_KEY
            
            if not pinata_api_key or not pinata_secret_api_key:
                raise Exception("Pinata API credentials not configured")
            
            form_data = aiohttp.FormData()
            form_data.add_field('file', file_data, filename=filename)
            
            headers = {
                'pinata_api_key': pinata_api_key,
                'pinata_secret_api_key': pinata_secret_api_key,
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    'https://api.pinata.cloud/pinning/pinFileToIPFS',
                    headers=headers,
                    data=form_data
                ) as response:
                    content_type = response.headers.get('Content-Type', '')
                    response_text = await response.text()
                    
                    if 'application/json' in content_type:
                        result = await response.json()
                        if response.status == 200:
                            return f"ipfs://{result['IpfsHash']}"
                        else:
                            error_msg = result.get('error', {}).get('message', 'Unknown error')
                            raise Exception(f"Pinata error: {error_msg}")
                    else:
                        if response.status == 401:
                            raise Exception("Pinata authentication failed - check API keys")
                        elif response.status == 403:
                            raise Exception("Pinata access denied - check API permissions")
                        elif response.status == 413:
                            raise Exception("Pinata file too large - try smaller image")
                        else:
                            raise Exception(f"Pinata error: HTTP {response.status} - {response_text[:200]}")
                        
        except Exception as e:
            logger.error(f"Pinata upload failed: {str(e)}")
            raise

    @staticmethod
    async def upload_to_ipfs(file_data: bytes, filename: str, max_retries: int = 2) -> str:
        """Main upload method that tries multiple providers with retries"""
        providers = []
        
        if settings.PINATA_API_KEY and settings.PINATA_SECRET_API_KEY:
            providers.append(("Pinata", IPFSService.upload_to_pinata))
        
        if not providers:
            raise Exception("No IPFS providers configured. Please set up at least one IPFS service.")
        
        errors = []
        
        for provider_name, provider_func in providers:
            for attempt in range(max_retries):
                try:
                    logger.info(f"Trying {provider_name} (attempt {attempt + 1})...")
                    result = await provider_func(file_data, filename)
                    logger.info(f"Successfully uploaded to IPFS using {provider_name}: {result}")
                    return result
                except Exception as e:
                    error_msg = f"{provider_name} attempt {attempt + 1} failed: {str(e)}"
                    errors.append(error_msg)
                    logger.warning(error_msg)
                    
                    if attempt < max_retries - 1:
                        await asyncio.sleep(1)
        
        detailed_error = "All IPFS providers failed:\n" + "\n".join(errors)
        logger.error(detailed_error)
        raise Exception("All IPFS providers failed. Check API keys and network connectivity.")

# Add these imports at the top
from app.db.models import ArtworkCategory, ArtworkCategoryCreate

# Add this function to get database collections
def get_categories_collection():
    db = get_db()
    return db.artwork_categories

# Add these endpoints before your existing ticket endpoints
@router.post("/categories", response_model=dict)
async def create_category(
    category: ArtworkCategoryCreate,
    current_user: dict = Depends(get_current_user)
):
    """Create a new ticket category (admin only)"""
    try:
        # Check if user is admin (you'll need to implement this check based on your user model)
        # if not current_user.get("is_admin", False):
        #     raise HTTPException(status_code=403, detail="Only admins can create categories")
        
        categories_collection = get_categories_collection()
        
        # Check if category already exists
        existing = await categories_collection.find_one({
            "name": category.name,
            "type": category.type
        })
        
        if existing:
            raise HTTPException(status_code=400, detail="Category already exists")
        
        category_doc = ArtworkCategory(**category.model_dump())
        result = await categories_collection.insert_one(category_doc.model_dump(by_alias=True))
        
        return {
            "success": True,
            "category_id": str(result.inserted_id),
            "message": "Category created successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Category creation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create category: {str(e)}")

@router.get("/categories", response_model=List[ArtworkCategory])
async def get_categories(
    type: Optional[str] = Query(None, description="Filter by category type: medium, style, or subject"),
    include_inactive: bool = Query(False, description="Include inactive categories")
):
    """Get all ticket categories, optionally filtered by type"""
    try:
        categories_collection = get_categories_collection()
        
        filter_query = {}
        if type:
            filter_query["type"] = type
        if not include_inactive:
            filter_query["is_active"] = True
        
        cursor = categories_collection.find(filter_query).sort("name", 1)
        categories_data = await cursor.to_list(length=100)
        
        categories = []
        for doc in categories_data:
            if '_id' in doc and isinstance(doc['_id'], ObjectId):
                doc['_id'] = str(doc['_id'])
            categories.append(ArtworkCategory(**doc))
        
        return categories
    except Exception as e:
        logger.error(f"Error getting categories: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get categories")

# Update the register_artwork_with_image endpoint to include categories and price
@router.post("/register-with-image")
async def register_artwork_with_image(
    title: str = Form(...),
    description: Optional[str] = Form(None),
    royalty_percentage: int = Form(...),
    price: float = Form(...),
    medium_category: str = Form(...),
    style_category: str = Form(...),
    subject_category: str = Form(...),
    other_medium: Optional[str] = Form(None),
    other_style: Optional[str] = Form(None),
    other_subject: Optional[str] = Form(None),
    ai_model: str = Form("gemini-1.5-flash"),
    registration_method: str = Form("on-chain"),  # NEW: "on-chain" or "off-chain" (replaces payment_method)
    responsible_use_addon: bool = Form(False),    # ✅ ADDED
    # PSL Smart-Ticket fields (Hackathon Demo)
    is_psl_ticket: Optional[str] = Form(None),    # "true" or None
    psl_seat_number: Optional[str] = Form(None),
    psl_stand: Optional[str] = Form(None),
    psl_venue: Optional[str] = Form(None),
    psl_match_date: Optional[str] = Form(None),
    psl_match_time: Optional[str] = Form(None),
    image: UploadFile = File(...),
    network: str = Form("wirefluid"),
    current_user: dict = Depends(get_current_user)
):
    try:
        network = (network or "wirefluid").strip().lower()
        if network != "wirefluid":
            raise HTTPException(
                status_code=400,
                detail="Only WireFluid network is supported."
            )

        current_fee = await get_current_global_fee()
        is_psl_ticket_flag = str(is_psl_ticket).lower() == "true"

        # ✅ Check for PSL ticket authorization
        if is_psl_ticket_flag:
            user_email = current_user.get("email", "").lower()
            authorized_issuers = [email.strip().lower() for email in settings.AUTHORIZED_PSL_ISSUERS if email.strip()]
            
            if user_email not in authorized_issuers:
                logger.warning(f"🚫 Unauthorized PSL ticket attempt: {user_email}")
                raise HTTPException(
                    status_code=403, 
                    detail="Unauthorized to issue PSL Smart-Tickets. Only authorized PCB accounts can perform this action."
                )
            logger.info(f"✅ Authorized PSL issuer detected: {user_email}")

            if registration_method != "on-chain":
                raise HTTPException(
                    status_code=400,
                    detail="PSL Smart-Tickets can only be registered on-chain."
                )

            missing_psl_fields = []
            if not (psl_seat_number or "").strip():
                missing_psl_fields.append("psl_seat_number")
            if not (psl_stand or "").strip():
                missing_psl_fields.append("psl_stand")
            if not (psl_venue or "").strip():
                missing_psl_fields.append("psl_venue")
            if not (psl_match_date or "").strip():
                missing_psl_fields.append("psl_match_date")
            if not (psl_match_time or "").strip():
                missing_psl_fields.append("psl_match_time")

            if missing_psl_fields:
                raise HTTPException(
                    status_code=400,
                    detail=f"Missing required PSL ticket fields: {', '.join(missing_psl_fields)}"
                )

        if not 0 <= royalty_percentage <= 2000:
            raise HTTPException(status_code=400, detail="Royalty must be between 0-2000 basis points")
        
        if price < 0:
            raise HTTPException(status_code=400, detail="Price cannot be negative")

        image_data = await image.read()
        if len(image_data) > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Image file too large (max 10MB)")

        # Direct upload mode: skip duplicate and AI rejection checks.
        duplicate_result = DuplicateCheckResult(
            is_duplicate=False,
            duplicate_type=None,
            similarity_score=None,
            existing_artwork_id=None,
            message="Duplicate check disabled"
        )
        ai_result = AIClassificationResult(
            is_ai_generated=False,
            confidence=0.0,
            description="AI classification disabled",
            model_used=ai_model,
            generated_description=""
        )

        # Step 3: Process and store image
        logger.info("Processing image...")
        processed_image_data = await ImageProcessor.process_image(image_data)
        
        # Step 4: Store binary image in GridFS
        logger.info("Storing image binary...")
        gridfs_id = await ImageProcessor.store_image_binary(
            processed_image_data, 
            image.filename, 
            image.content_type
        )
        
        # Extract responsible_use_addon (already processed by FastAPI from Form)
        # We use the value directly from parameter
        
        # Step 5: Upload to IPFS (attempt, but don't fail if it doesn't work)
        image_ipfs_uri = None
        try:
            logger.info("Uploading to IPFS...")
            image_ipfs_uri = await IPFSService.upload_to_ipfs(processed_image_data, image.filename)
        except Exception as e:
            logger.warning(f"IPFS upload failed, continuing with binary storage: {str(e)}")

        # Step 6: Create image metadata - FIXED: Ensure all hashes are stored properly
        image_metadata = {
            "filename": image.filename,
            "file_hash": ImageProcessor.get_file_hash(processed_image_data),
            "perceptual_hash": ImageProcessor.get_perceptual_hash(processed_image_data),
            "embedding": None,
            "gridfs_id": gridfs_id,
            "content_type": image.content_type or "image/jpeg",
            "file_size": len(processed_image_data),
            "uploaded_at": datetime.utcnow()
        }

        # FIXED: Add validation logging
        logger.info(f"Image metadata created:")
        logger.info(f"  - File hash: {image_metadata['file_hash'][:16]}...")
        logger.info(f"  - Perceptual hash: {image_metadata['perceptual_hash']}")
        logger.info("  - Embedding: disabled")

        if registration_method != "on-chain":
            raise HTTPException(
                status_code=400,
                detail="Off-chain/PayPal registration is no longer supported. Use on-chain registration only."
            )

        if registration_method == "off-chain":
            logger.info("Using off-chain registration (PayPal) - Checking seller onboarding...")
            
            # ✅ MANDATORY: Check if creator is onboarded before registration
            user_id = str(current_user.get('id') or current_user.get('user_id') or current_user.get('_id') or '')
            user_email = current_user.get('email')
            
            logger.info(f"🔍 Checking onboarding for user_id: {user_id}, email: {user_email}")
            
            # ✅ Check both sellers collection AND users collection for onboarding status
            db = get_db()
            sellers_collection = db.sellers
            users_collection = db.users
            
            # Method 1: Check sellers collection by user_id
            seller = await sellers_collection.find_one({"user_id": user_id})
            
            # Method 2: If not found, try by email
            if not seller and user_email:
                seller = await sellers_collection.find_one({"email": user_email})
            
            # Method 3: Check users collection for paypal_onboarded status
            user_doc = None
            if ObjectId.is_valid(user_id):
                user_doc = await users_collection.find_one({"_id": ObjectId(user_id)})
            if not user_doc:
                user_doc = await users_collection.find_one({"user_id": user_id})
            if not user_doc and user_email:
                user_doc = await users_collection.find_one({"email": user_email})
            
            # ✅ MANDATORY: Creator MUST be onboarded - Find LATEST onboarded seller record
            is_onboarded = False
            merchant_id = None
            
            # ✅ Strategy 1: Find LATEST seller record with onboarded=true AND merchant_id
            all_onboarded_sellers = await sellers_collection.find(
                {
                    "user_id": user_id,
                    "onboarded": True,  # ✅ MUST be onboarded
                    "merchant_id": {"$ne": None, "$exists": True}  # ✅ MUST have merchant_id
                }
            ).sort("updated_at", -1).limit(1).to_list(length=1)
            
            if all_onboarded_sellers and len(all_onboarded_sellers) > 0:
                latest_onboarded_seller = all_onboarded_sellers[0]
                merchant_id = latest_onboarded_seller.get('merchant_id')
                is_onboarded = True
                logger.info(f"✅✅✅ Found LATEST onboarded seller: merchant_id={merchant_id}, updated_at={latest_onboarded_seller.get('updated_at')}")
            
            # ✅ Strategy 2: Check user collection for paypal_onboarded (fallback)
            if not merchant_id and user_doc:
                user_onboarded = user_doc.get('paypal_onboarded', False)
                user_merchant_id = user_doc.get('paypal_merchant_id')
                if user_onboarded and user_merchant_id:
                    is_onboarded = True
                    merchant_id = user_merchant_id
                    logger.info(f"👤 Found user record: paypal_onboarded={user_onboarded}, merchant_id={user_merchant_id}")
            
            # ✅ MANDATORY CHECK: Creator MUST be onboarded to register ticket
            if not is_onboarded or not merchant_id:
                logger.warning(f"❌ User {user_id} not onboarded - Registration BLOCKED")
                logger.warning(f"   Seller record: {seller is not None}, User record: {user_doc is not None}")
                logger.warning(f"   Seller onboarded: {seller.get('onboarded') if seller else None}")
                logger.warning(f"   User paypal_onboarded: {user_doc.get('paypal_onboarded') if user_doc else None}")
                logger.warning(f"   Merchant ID found: {merchant_id}")
                raise HTTPException(
                    status_code=400,
                    detail="PayPal seller onboarding is REQUIRED. Please complete PayPal onboarding before registering tickets. This ensures we can send payments to your PayPal account when your ticket is sold."
                )
            
            logger.info(f"✅✅✅ User {user_id} is onboarded with merchant ID: {merchant_id}")
            
            # ✅ Create metadata JSON and upload to IPFS (same as crypto flow)
            metadata = {
                "name": title,
                "description": description,
                "image": image_ipfs_uri or f"data:image/binary;id={str(image_metadata.get('gridfs_id'))}",
                "attributes": {
                    "royalty_percentage": royalty_percentage,
                    "price": price,
                    "medium_category": medium_category,
                    "style_category": style_category,
                    "subject_category": subject_category,
                    "other_medium": other_medium,
                    "other_style": other_style,
                    "other_subject": other_subject,
                    "creator": current_user.get("email"),  # Use email for PayPal users
                    "created_at": datetime.utcnow().isoformat(),
                    "has_fallback_image": True,
                    "payment_method": "paypal"
                }
            }
            
            metadata_bytes = json.dumps(metadata).encode('utf-8')
            metadata_uri = await IPFSService.upload_to_ipfs(metadata_bytes, "metadata.json")
            logger.info(f"✅ Metadata uploaded to IPFS: {metadata_uri}")
            
            # ✅ Prepare COMPLETE ticket data for PayPal registration
            artwork_data = {
                "title": title,
                "description": description,
                "royalty_percentage": royalty_percentage,
                "price": price,
                "medium_category": medium_category,
                "style_category": style_category,
                "subject_category": subject_category,
                "other_medium": other_medium,
                "other_style": other_style,
                "other_subject": other_subject,
                "metadata_uri": metadata_uri,  # ✅ IPFS metadata URI
                "image_ipfs_uri": image_ipfs_uri,  # ✅ IPFS image URI
                "creator_id": str(current_user.get('id')),  # ✅ Creator ID
                "owner_id": str(current_user.get('id'))     # ✅ Owner ID
            }
            
            # ✅ Check if PayPal is enabled by admin
            if not await is_paypal_enabled():
                raise HTTPException(
                    status_code=403,
                    detail="PayPal payments are currently disabled by the administrator. Please use on-chain registration instead."
                )
            
            # ✅ PayPal registration - no seller onboarding required
            paypal_result = await paypal_service.register_artwork_with_paypal(
                artwork_data=artwork_data,
                image_metadata=image_metadata,
                current_user=current_user
            )
            
            if not paypal_result['success']:
                raise HTTPException(status_code=400, detail=paypal_result.get('error'))
            
            return {
                "status": "success",
                "registration_method": "off-chain",  # NEW: Use registration_method
                "payment_method": "paypal",  # OLD: Keep for backward compatibility
                "order_data": {
                    "order_id": paypal_result['order_id'],
                    "approval_url": paypal_result['approval_url'],
                    # ✅ REMOVED: virtual_token_id - will be generated from MongoDB _id when ticket is created
                    "registration_fee": paypal_result['registration_fee']
                },
                "metadata_uri": metadata_uri,  # ✅ Return actual metadata URI
                "image_uri": image_ipfs_uri,
                "image_metadata": image_metadata,
                "royalty_percentage": royalty_percentage,
                "price": price,
                "categories": {
                    "medium": medium_category,
                    "style": style_category,
                    "subject": subject_category,
                    "other_medium": other_medium,
                    "other_style": other_style,
                    "other_subject": other_subject
                },
                "duplicate_check": duplicate_result.dict(),
                "ai_classification": ai_result.dict()
            }
        
        else:
            # KEEP ALL YOUR EXISTING METAMASK CODE HERE
            # Check if wallet address exists for on-chain registration
            wallet_addr = current_user.get('wallet_address')
            if not wallet_addr:
                raise HTTPException(
                    status_code=400, 
                    detail="Wallet address is required for on-chain registration. Please connect your MetaMask wallet."
                )
                
            # PSL Smart-Ticket metadata (Hackathon Demo)
            psl_data = None
            if is_psl_ticket_flag:
                psl_data = {
                    "is_psl_ticket": True,
                    "seat_number": psl_seat_number,
                    "stand": psl_stand,
                    "venue": psl_venue,
                    "match_date": psl_match_date,
                    "match_time": psl_match_time
                }
                logger.info(f"🎫 PSL Ticket detected: {psl_data}")
            
            metadata = {
                "name": title,
                "description": description,
                "image": image_ipfs_uri or f"data:image/binary;id={str(gridfs_id)}",
                "attributes": {
                    "royalty_percentage": royalty_percentage,
                    "price": price,
                    "medium_category": medium_category,
                    "style_category": style_category,
                    "subject_category": subject_category,
                    "other_medium": other_medium,
                    "other_style": other_style,
                    "other_subject": other_subject,
                    "responsible_use_addon": responsible_use_addon,
                    "creator": current_user.get("wallet_address"),
                    "created_at": datetime.utcnow().isoformat(),
                    "has_fallback_image": True,
                    "ai_classified": ai_result.dict(),
                    # PSL metadata (Hackathon Demo)
                    "psl_ticket": psl_data
                }
            }

            metadata_bytes = json.dumps(metadata).encode('utf-8')
            metadata_uri = await IPFSService.upload_to_ipfs(metadata_bytes, "metadata.json")

            # ✅ Use the correct network's pre-initialized service to prepare the transaction.
            # This ensures the right contract address and chain ID are used for the selected network.
            active_web3_service = web3_service.get_service(network)
            tx_data = await active_web3_service.prepare_register_transaction(
                metadata_uri,
                royalty_percentage,
                from_address=current_user.get('wallet_address'),
                is_conversion=False,
                artwork_price_eth=price
            )

            return {
                "status": "success",
                "registration_method": "on-chain",  # NEW: Use registration_method
                "payment_method": "crypto",  # OLD: Keep for backward compatibility
                "transaction_data": tx_data,
                "metadata_uri": metadata_uri,
                "image_uri": image_ipfs_uri,
                "image_metadata": image_metadata,
                "royalty_percentage": royalty_percentage,
                "price": price,
                "responsible_use_addon": responsible_use_addon,
                "is_psl_ticket": is_psl_ticket_flag,
                "psl_metadata": psl_data,
                "categories": {
                    "medium": medium_category,
                    "style": style_category,
                    "subject": subject_category,
                    "other_medium": other_medium,
                    "other_style": other_style,
                    "other_subject": other_subject
                },
                "duplicate_check": duplicate_result.dict(),
                "ai_classification": ai_result.dict()
            }
        
    except Exception as e:
        logger.error(f"Registration with image failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")

# Update the confirm_registration endpoint to include categories and price
@router.post("/confirm-registration")
async def confirm_registration(confirmation_data: dict, current_user: dict = Depends(get_current_user)):
    try:
        artworks_collection = get_artwork_collection()
        
        # ✅ DYNAMIC: Get network from confirmation data or fallback to ACTIVE_NETWORK
        network = _ensure_wirefluid_network(
            confirmation_data.get("network") or getattr(settings, "ACTIVE_NETWORK", "wirefluid")
        )
        logger.info(f"🌐 Registration network: {network}")

        # Use latest admin-configured platform fee for persisted ticket record.
        try:
            current_fee = await get_current_global_fee()
        except Exception as fee_error:
            logger.warning(f"⚠️ Failed to fetch current global fee, using default 2.5%: {fee_error}")
            current_fee = 2.5

        token_id = None
        asa_id = confirmation_data.get("algorand_asa_id")
        confirmed_asa_id = None
        algorand_app_id = None

        if network == "algorand":
            raw_app_id = (
                confirmation_data.get("algorand_app_id")
                or confirmation_data.get("app_id")
                or getattr(settings, "ALGORAND_APP_ID", 0)
            )
            try:
                parsed_app_id = int(raw_app_id or 0)
                if parsed_app_id > 0:
                    algorand_app_id = parsed_app_id
            except Exception:
                logger.warning(f"⚠️ Invalid Algorand app id received during registration: {raw_app_id}")

        if network == "algorand":
            from services.algorand_service import AlgorandService
            from algosdk import encoding as algo_encoding
            algorand_service = AlgorandService()
            verification = await algorand_service.verify_registration(
                tx_hash=confirmation_data["tx_hash"],
                asa_id=asa_id
            )
            if not verification["success"]:
                raise HTTPException(status_code=400, detail=f"Algorand verification failed: {verification.get('error')}")

            verified_asa = verification.get("asa_id") or verification.get("token_id") or asa_id
            if not verified_asa:
                raise HTTPException(status_code=400, detail="Could not determine Algorand ASA ID from registration transaction")

            try:
                confirmed_asa_id = int(verified_asa)
            except Exception:
                raise HTTPException(status_code=400, detail=f"Invalid Algorand ASA ID resolved from transaction: {verified_asa}")

            # For Algorand, token_id and ASA ID are equivalent in this project.
            token_id = confirmed_asa_id

            payer_address = (confirmation_data.get("from_address") or "").strip()
            if not payer_address or not algo_encoding.is_valid_address(payer_address):
                raise HTTPException(status_code=400, detail="Missing or invalid Algorand payer address for registration confirmation")

            platform_address = (algorand_service.platform_address or "").strip()
            provided_fee = confirmation_data.get("registration_fee_microalgos")
            provided_fee_microalgos = 0
            if provided_fee is not None:
                try:
                    provided_fee_microalgos = max(0, int(str(provided_fee)))
                except Exception:
                    raise HTTPException(status_code=400, detail="Invalid registration_fee_microalgos in confirmation payload")

            price_for_fee_algo = 0.0
            try:
                price_for_fee_algo = float(confirmation_data.get("price") or 0)
            except Exception:
                price_for_fee_algo = 0.0

            calculated_fee_microalgos = 0
            if price_for_fee_algo > 0:
                price_microalgos = int(round(price_for_fee_algo * 1_000_000))
                platform_fee_basis = max(0, int(round(float(current_fee) * 100)))
                calculated_fee_microalgos = (price_microalgos * platform_fee_basis) // 10000

            expected_fee_microalgos = max(provided_fee_microalgos, calculated_fee_microalgos)
            if expected_fee_microalgos > 0:
                if not platform_address or not algo_encoding.is_valid_address(platform_address):
                    raise HTTPException(
                        status_code=500,
                        detail="ALGORAND_PLATFORM_ADDRESS is missing or invalid while registration platform fee is enabled",
                    )

                await _verify_algorand_registration_fee_payment(
                    tx_hash=confirmation_data["tx_hash"],
                    payer_address=payer_address,
                    platform_address=platform_address,
                    expected_amount_microalgos=expected_fee_microalgos,
                    algorand_service=algorand_service,
                )
        else:
            # ✅ Use pre-initialized network-specific service from the global proxy.
            # Both Sepolia and WireFluid are already connected at server startup —
            # just pick the right one. No initialization overhead per request.
            network_web3_service = web3_service.get_service(network)
            
            tx_receipt = await network_web3_service.get_transaction_receipt(confirmation_data["tx_hash"])
            if not tx_receipt or tx_receipt.get("status") != 1:
                raise HTTPException(status_code=400, detail="Blockchain transaction failed")

            token_id = await network_web3_service.get_token_id_from_tx(confirmation_data["tx_hash"])
            if token_id is None:
                raise HTTPException(status_code=400, detail="Could not determine token ID from transaction")

        attributes = confirmation_data.get("attributes") or {}
        image_metadata = confirmation_data.get("image_metadata", {})
        
        categories_data = confirmation_data.get("categories", {})
        medium_category = categories_data.get("medium", "Other Medium")
        style_category = categories_data.get("style", "Other Style")
        subject_category = categories_data.get("subject", "Other Subject")
        other_medium = categories_data.get("other_medium")
        other_style = categories_data.get("other_style")
        other_subject = categories_data.get("other_subject")

        # GET REGISTRATION METHOD FROM CONFIRMATION DATA (NEW)
        registration_method = confirmation_data.get("registration_method", "on-chain")
        # Keep old field for backward compatibility
        payment_method = confirmation_data.get("payment_method", "crypto")
        
        # Determine is_on_chain based on registration_method
        is_on_chain = (registration_method == "on-chain")
        
        # ✅ DYNAMIC: Get network from confirmation data or fallback to ACTIVE_NETWORK
        network = _ensure_wirefluid_network(
            confirmation_data.get("network") or getattr(settings, "ACTIVE_NETWORK", "wirefluid")
        )
        logger.info(f"🌐 Registration network: {network}")
        
        # ✅ NEW: Check if ticket already exists (for off-chain to on-chain conversion)
        # If registration_method is "on-chain" and we're converting an existing off-chain ticket
        metadata_uri = confirmation_data["metadata_uri"]
        existing_artwork = None
        
        if registration_method == "on-chain":
            # Try to find existing off-chain ticket by metadata_uri and owner
            user_id = str(current_user.get('_id') or current_user.get('id'))
            
            # ✅ More flexible query: Check for off-chain tickets (handles backward compatibility)
            # Try multiple queries to find the ticket (MongoDB $or needs to be structured correctly)
            
            # Query 1: Try finding by metadata_uri and owner_id, then check if it's off-chain
            existing_artwork = await artworks_collection.find_one({
                "metadata_uri": metadata_uri,
                "owner_id": user_id
            })
            
            # ✅ If found, verify it's actually off-chain (not already on-chain)
            if existing_artwork:
                is_on_chain_value = existing_artwork.get("is_on_chain")
                is_virtual_token = existing_artwork.get("is_virtual_token", False)
                payment_method = existing_artwork.get("payment_method", "crypto")
                
                # Determine if ticket is off-chain (backward compatibility)
                is_actually_off_chain = False
                if is_on_chain_value is False:
                    is_actually_off_chain = True
                elif is_on_chain_value is None or is_on_chain_value is True:
                    # Check old fields for backward compatibility
                    if is_virtual_token or payment_method == "paypal":
                        is_actually_off_chain = True
                
                # If ticket is already on-chain, don't update it
                if not is_actually_off_chain:
                    logger.info(f"ℹ️ Ticket {existing_artwork.get('_id')} is already on-chain, skipping update")
                    existing_artwork = None
                else:
                    logger.info(f"✅ Found existing off-chain ticket to convert: {existing_artwork.get('_id')}, is_on_chain: {is_on_chain_value}, is_virtual_token: {is_virtual_token}, payment_method: {payment_method}")
            else:
                logger.info(f"ℹ️ No existing ticket found for metadata_uri: {metadata_uri}, owner_id: {user_id} - will create new ticket")
        
        if existing_artwork:
            # ✅ UPDATE existing ticket (off-chain to on-chain conversion)
            logger.info(f"✅ Updating existing off-chain ticket {existing_artwork.get('_id')} to on-chain")
            
            update_data = {
                "token_id": token_id,  # ✅ New blockchain token_id
                "is_on_chain": True,  # ✅ Mark as on-chain
                "registration_method": "on-chain",  # ✅ Update registration method
                "network": network,  # ✅ DYNAMIC: Set network
                "creator_address": current_user.get('wallet_address'),  # ✅ Set creator address
                "owner_address": current_user.get('wallet_address'),  # ✅ Set owner address
                "tx_hash": confirmation_data.get("tx_hash"),  # ✅ Store transaction hash
                "display_id": None,  # ✅ Clear display_id (on-chain tickets don't use display_id)
                "updated_at": datetime.utcnow(),
                # Update old fields for backward compatibility
                "payment_method": "crypto",
                "is_virtual_token": False,
                # Update fields if provided
                "title": confirmation_data.get("title") or existing_artwork.get("title"),
                "description": confirmation_data.get("description") or existing_artwork.get("description"),
                "price": confirmation_data.get("price") or existing_artwork.get("price"),
                "royalty_percentage": confirmation_data.get("royalty_percentage") or existing_artwork.get("royalty_percentage"),
                "medium_category": medium_category or existing_artwork.get("medium_category"),
                "style_category": style_category or existing_artwork.get("style_category"),
                "subject_category": subject_category or existing_artwork.get("subject_category"),
                "other_medium": other_medium or existing_artwork.get("other_medium"),
                "other_style": other_style or existing_artwork.get("other_style"),
                "other_subject": other_subject or existing_artwork.get("other_subject"),
                "responsible_use_addon": confirmation_data.get("responsible_use_addon", existing_artwork.get("responsible_use_addon", False))
            }

            if network == "algorand":
                update_data["algorand_asa_id"] = confirmed_asa_id
                update_data["algorand_app_id"] = algorand_app_id
                update_data["creator_algorand_address"] = confirmation_data.get("from_address")
                update_data["owner_algorand_address"] = confirmation_data.get("from_address")
            
            # Update image fields if provided
            if confirmation_data.get("image_uri"):
                update_data["image_ipfs_uri"] = confirmation_data.get("image_uri")
            if image_metadata:
                update_data["image_metadata"] = image_metadata
                if image_metadata.get("gridfs_id"):
                    update_data["image_metadata_id"] = image_metadata.get("gridfs_id")
            
            # ✅ Ensure _id is ObjectId for update query
            artwork_object_id = existing_artwork.get("_id")
            if not isinstance(artwork_object_id, ObjectId):
                artwork_object_id = ObjectId(artwork_object_id)
            
            result = await artworks_collection.update_one(
                {"_id": artwork_object_id},
                {"$set": update_data}
            )
            
            artwork_id = str(artwork_object_id)
            is_update = True
            
            # ✅ Log update result for debugging
            if result.modified_count > 0:
                logger.info(f"✅ Successfully updated ticket {artwork_id} to on-chain. Modified count: {result.modified_count}")
            else:
                logger.warning(f"⚠️ Update query executed but no documents were modified for ticket {artwork_id}")
        else:
            # ✅ CREATE new ticket (normal registration flow)
            ticket = ArtworkInDB(
                token_id=token_id,
                creator_id=str(current_user.get('_id') or current_user.get('id')),  # ADD THIS - user ID
                owner_id=str(current_user.get('_id') or current_user.get('id')),    # ADD THIS - user ID
                creator_address=current_user.get('wallet_address'),  # Keep for crypto
                owner_address=current_user.get('wallet_address'),    # Keep for crypto
                metadata_uri=metadata_uri,
                royalty_percentage=confirmation_data["royalty_percentage"],
                price=confirmation_data["price"],
                title=confirmation_data.get("title"),
                description=confirmation_data.get("description"),
                medium_category=medium_category,
                style_category=style_category,
                subject_category=subject_category,
                other_medium=other_medium,
                other_style=other_style,
                other_subject=other_subject,
                responsible_use_addon=confirmation_data.get("responsible_use_addon", False),
                attributes=attributes,
                # NEW FIELDS
                registration_method=registration_method,
                is_on_chain=is_on_chain,
                network=network,  # ✅ DYNAMIC: Set network
                display_id=None,  # ✅ On-chain tickets don't use display_id (token_id comes from blockchain)
                # OLD FIELDS (kept for backward compatibility)
                payment_method=payment_method,
                is_virtual_token=not is_on_chain,  # Keep old field for backward compatibility
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                tx_hash=confirmation_data.get("tx_hash"),
                paypal_order_id=confirmation_data.get("paypal_order_id"),  # For PayPal
                platform_fee_percentage=current_fee,
            
                # Image storage fields
                image_metadata=image_metadata,
                image_metadata_id=image_metadata.get("gridfs_id"),
                image_ipfs_uri=confirmation_data.get("image_uri"),
                has_fallback_image=True,
                
                # Algorand Specific Fields
                algorand_asa_id=confirmed_asa_id if network == "algorand" else None,
                algorand_app_id=algorand_app_id if network == "algorand" else None,
                creator_algorand_address=confirmation_data.get("from_address") if network == "algorand" else None,
                owner_algorand_address=confirmation_data.get("from_address") if network == "algorand" else None,

                # PSL Smart-Ticket fields (Hackathon Demo)
                is_psl_ticket=confirmation_data.get("is_psl_ticket", False),
                psl_metadata=confirmation_data.get("psl_metadata")
            )

            result = await artworks_collection.insert_one(ticket.model_dump(by_alias=True))
            artwork_id = str(result.inserted_id)
            is_update = False

        await UserHistoryService.log_user_action(
            user_id=str(current_user['id']),
            action="register_on_chain" if is_update else "upload",
            artwork_id=artwork_id,
            artwork_token_id=token_id,
            metadata={
                "title": confirmation_data.get("title"),
                "price": confirmation_data.get("price"),
                "categories": confirmation_data.get("categories", {}),
                "payment_method": payment_method,  # ADD THIS
                "is_update": is_update  # NEW: Indicate if this was an update
            }
        )

        # ✅ Add ticket to FFAISS index for recommendations
        try:
            from app.api.v1.advance_search import add_artwork_to_faiss
            await add_artwork_to_faiss(artwork_id, ticket.model_dump(by_alias=True))
        except Exception as e:
            logger.warning(f"⚠️ Failed to add ticket {artwork_id} to FFAISS index: {e}")
            # Don't fail the registration if indexing fails

        # ✅ REDIS CACHE: Invalidate ticket cache after registration
        try:
            invalidate_artworks_cache()
            
            logger.info("🗑️ Ticket cache invalidated after registration")
        except Exception as cache_error:
            logger.warning(f"⚠️ Failed to invalidate cache: {cache_error}")

        return {
            "success": True, 
            "artwork_id": artwork_id, 
            "token_id": token_id,
            "algorand_asa_id": confirmed_asa_id if network == "algorand" else None,
            "is_update": is_update  # NEW: Indicate if ticket was updated or created
        }
    except Exception as e:
        logger.error(f"Ticket confirmation failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to confirm ticket registration: {str(e)}")
    
@router.post("/confirm-paypal-payment")
async def confirm_paypal_payment(
    confirmation_data: dict,
    current_user: dict = Depends(get_current_user)
):
    raise HTTPException(status_code=410, detail="PayPal support has been removed from this deployment.")

    try:
        # ✅ Check if PayPal is enabled by admin
        if not await is_paypal_enabled():
            raise HTTPException(
                status_code=403,
                detail="PayPal payments are currently disabled by the administrator."
            )

        from bson import ObjectId
        
        order_id = confirmation_data.get("order_id")
        transaction_type = confirmation_data.get("type")
        
        if not order_id or not transaction_type:
            raise HTTPException(status_code=400, detail="Missing required parameters")
        logger.info(f"📥 Confirming PayPal payment: {transaction_type} - Order: {order_id}")

        # Check if already processed
        paypal_orders_collection = get_db().paypal_orders
        existing_order = await paypal_orders_collection.find_one({
            "paypal_order_id": order_id
        })
        
        # ✅ Check if order is already completed and has artwork_id
        if existing_order and existing_order.get('status') == "COMPLETED":
            artwork_id = str(existing_order.get('artwork_id', ''))
            if artwork_id:
                logger.warning(f"Order {order_id} already processed with artwork_id: {artwork_id}")
                return {
                    "success": True,
                    "message": f"PayPal {transaction_type} already completed",
                    "order_id": order_id,
                    "artwork_id": artwork_id,
                    "transaction_type": transaction_type
                }
        
        paypal_service = get_paypal_service()
        
        # ✅ FIXED: For ticket purchases, skip capture here and let confirm_paypal_sale handle it
        # This prevents duplicate capture errors
        if transaction_type == "ticket":
            # Get token_id from order document (before capture)
            order_doc = await paypal_orders_collection.find_one({"paypal_order_id": order_id})
            if not order_doc:
                raise HTTPException(status_code=404, detail="Order not found")
            
            token_id = order_doc.get('token_id')
            if not token_id:
                raise HTTPException(status_code=400, detail="Token ID not found in order")
            
            # ✅ Call confirm_paypal_sale which will handle capture + seller + creator payouts
            sale_confirmation = {
                "order_id": order_id,
                "token_id": token_id,
                "payment_method": "paypal"
            }
            
            logger.info(f"🔄 Redirecting to confirm_paypal_sale for complete handling (capture + seller + creator payouts)")
            return await confirm_paypal_sale(sale_confirmation, current_user)
        
        # ✅ For registration/license types, capture payment here
        capture_result = await paypal_service.capture_payment(order_id)
        
        if not capture_result['success']:
            error_msg = capture_result.get('error', 'Unknown error')
            
            # ✅ Handle already captured orders - check if license/ticket is already processed
            if '422' in str(error_msg) or 'ORDER_ALREADY_CAPTURED' in str(error_msg) or 'Unprocessable Entity' in str(error_msg):
                logger.warning(f"⚠️ Order {order_id} may already be captured, checking status...")
                existing_order = await paypal_orders_collection.find_one({"paypal_order_id": order_id})
                
                if existing_order and existing_order.get('captured'):
                    logger.info(f"✅ Confirmed: Order {order_id} was already captured")
                    artwork_id = str(existing_order.get('artwork_id', ''))
                    
                    # ✅ For license transactions, also check if license is active
                    if transaction_type == "license":
                        from app.db.database import get_license_collection
                        licenses_collection = get_license_collection()
                        active_license = await licenses_collection.find_one({
                            "paypal_order_id": order_id,
                            "status": {"$in": ["CONFIRMED", "ACTIVE"]}
                        })
                        if active_license:
                            logger.info(f"✅ License already active for order {order_id}")
                            return {
                                "success": True,
                                "message": f"PayPal {transaction_type} already completed",
                                "order_id": order_id,
                                "artwork_id": artwork_id,
                                "transaction_type": transaction_type,
                                "license_id": active_license.get('license_id')
                            }
                    
                    return {
                        "success": True,
                        "message": f"PayPal {transaction_type} already completed",
                        "order_id": order_id,
                        "artwork_id": artwork_id,
                        "transaction_type": transaction_type
                    }
            
            raise HTTPException(status_code=400, detail=f"Payment capture failed: {error_msg}")

        order_data = capture_result['order']

        # ✅ INITIALIZE artwork_id
        artwork_id = None
                
        
        # Handle registration and license types...
        if transaction_type == "registration":
            # ✅ COMPLETE PAYPAL REGISTRATION FLOW
            logger.info(f"📝 Processing PayPal registration payment")
            
            # Get COMPLETE ticket data from order
            artwork_data = order_data.get('artwork_data', {})
            image_metadata = order_data.get('image_metadata', {})
            
            # ✅ DEBUG: Log artwork_data to see what we're getting
            logger.info(f"📦 Ticket data from order: {json.dumps(artwork_data, default=str)}")
            logger.info(f"📦 Royalty percentage from artwork_data: {artwork_data.get('royalty_percentage')}")
            
            if not artwork_data:
                raise HTTPException(status_code=400, detail="Ticket data not found in order")
            
            # Extract all required fields
            artworks_collection = get_artwork_collection()
            
            # ✅ Get royalty_percentage with proper fallback
            royalty_percentage = artwork_data.get('royalty_percentage')
            if royalty_percentage is None:
                logger.warning(f"⚠️ Royalty percentage is None in artwork_data, using default 0")
                royalty_percentage = 0
            else:
                try:
                    royalty_percentage = int(royalty_percentage)
                except (ValueError, TypeError):
                    logger.warning(f"⚠️ Invalid royalty_percentage value: {royalty_percentage}, using default 0")
                    royalty_percentage = 0
            
            # ✅ Get price with proper fallback
            price = artwork_data.get('price')
            if price is None:
                logger.warning(f"⚠️ Price is None in artwork_data, using default 0")
                price = 0.0
            else:
                try:
                    price = float(price)
                except (ValueError, TypeError):
                    logger.warning(f"⚠️ Invalid price value: {price}, using default 0")
                    price = 0.0
            
            logger.info(f"✅ Using royalty_percentage: {royalty_percentage}, price: {price}")
            
            # ✅ Check if ticket already exists (prevent duplicates)
            from bson import ObjectId
            user_id = str(current_user.get('id') or current_user.get('_id'))
            metadata_uri = artwork_data.get('metadata_uri')
            
            # Check 1: Check if ticket with same paypal_order_id already exists (most reliable)
            existing_artwork = await artworks_collection.find_one({
                "paypal_order_id": order_id
            })
            
            if existing_artwork:
                # Ticket already exists for this order - return existing ticket ID
                artwork_id = str(existing_artwork.get('_id'))
                logger.info(f"✅ Ticket already exists for order {order_id} with ID: {artwork_id}, returning existing ticket")
                
                # Update order with artwork_id if not set
                await paypal_orders_collection.update_one(
                    {"paypal_order_id": order_id},
                    {"$set": {"artwork_id": artwork_id, "captured": True, "status": "COMPLETED"}}
                )
                
                return {
                    "success": True,
                    "message": "Ticket already registered for this order",
                    "artwork_id": artwork_id,
                    "order_id": order_id,
                    "transaction_type": transaction_type
                }
            
            # Check 2: Check if ticket with same metadata_uri and owner_id already exists (fallback)
            existing_artwork = await artworks_collection.find_one({
                "metadata_uri": metadata_uri,
                "owner_id": user_id,
                "is_on_chain": False  # Only check off-chain tickets
            })
            
            if existing_artwork:
                # Ticket already exists - return existing ticket ID and update paypal_order_id
                artwork_id = str(existing_artwork.get('_id'))
                logger.info(f"✅ Ticket already exists with ID: {artwork_id} (same metadata_uri), updating paypal_order_id and returning existing ticket")
                
                # Update ticket with paypal_order_id if not set
                await artworks_collection.update_one(
                    {"_id": ObjectId(artwork_id)},
                    {"$set": {"paypal_order_id": order_id}}
                )
                
                # Update order with artwork_id
                await paypal_orders_collection.update_one(
                    {"paypal_order_id": order_id},
                    {"$set": {"artwork_id": artwork_id, "captured": True, "status": "COMPLETED"}}
                )
                
                return {
                    "success": True,
                    "message": "Ticket already registered",
                    "artwork_id": artwork_id,
                    "order_id": order_id,
                    "transaction_type": transaction_type
                }
            
            # ✅ Create ticket data as dict (to allow token_id generation after insertion)
            artwork_dict = {
                "creator_id": artwork_data.get('creator_id') or str(current_user.get('id')),
                "owner_id": artwork_data.get('owner_id') or str(current_user.get('id')),
                "creator_address": None,  # ✅ Optional for PayPal - no wallet needed
                "owner_address": None,    # ✅ Optional for PayPal - no wallet needed
                "metadata_uri": artwork_data.get('metadata_uri'),  # ✅ Required - from IPFS
                "royalty_percentage": royalty_percentage,  # ✅ Properly validated
                "price": price,  # ✅ Properly validated
                "title": artwork_data.get('title'),
                "description": artwork_data.get('description'),
                "medium_category": artwork_data.get('medium_category'),
                "style_category": artwork_data.get('style_category'),
                "subject_category": artwork_data.get('subject_category'),
                "other_medium": artwork_data.get('other_medium'),
                "other_style": artwork_data.get('other_style'),
                "other_subject": artwork_data.get('other_subject'),
                # NEW FIELDS
                "registration_method": "off-chain",  # ✅ Off-chain registration
                "is_on_chain": False,  # ✅ Not on blockchain
                # OLD FIELDS (kept for backward compatibility)
                "payment_method": "paypal",  # ✅ PayPal payment
                "is_virtual_token": True,  # ✅ Virtual token (not on blockchain)
                "paypal_order_id": order_id,  # ✅ PayPal order ID
                "is_licensed": False,
                "image_metadata": image_metadata,  # ✅ Complete image metadata
                "image_metadata_id": image_metadata.get("gridfs_id"),  # ✅ GridFS ID
                "image_ipfs_uri": artwork_data.get('image_ipfs_uri'),  # ✅ IPFS image URI
                "has_fallback_image": True,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            
            # ✅ Generate token_id with numeric prefix and display_id for PayPal
            generated_token_id, display_id = await generate_token_id_and_display_id(
                registration_method="paypal",
                artworks_collection=artworks_collection
            )
            
            # Add token_id and display_id to artwork_dict
            artwork_dict["token_id"] = generated_token_id
            artwork_dict["display_id"] = display_id
            
            # Insert ticket with token_id and display_id
            result = await artworks_collection.insert_one(artwork_dict)
            artwork_id = str(result.inserted_id)
            
            logger.info(f"✅ PayPal ticket registered with ID: {artwork_id}, Token ID: {generated_token_id}, Display ID: {display_id}")
            
            # ✅ Add ticket to FFAISS index for recommendations
            try:
                from app.api.v1.advance_search import add_artwork_to_faiss
                await add_artwork_to_faiss(artwork_id, artwork_dict)
            except Exception as e:
                logger.warning(f"⚠️ Failed to add ticket {artwork_id} to FFAISS index: {e}")
                # Don't fail the registration if indexing fails
        elif transaction_type == "license":
            # ✅ COMPLETE LICENSE FLOW
            logger.info(f"📜 Processing PayPal license payment")
            
            # Get license data from order
            license_data = order_data.get('metadata', {})
            token_id = order_data.get('token_id') or license_data.get('token_id')
            license_type = order_data.get('license_type') or license_data.get('license_type')
            artwork_id = order_data.get('artwork_id') or license_data.get('artwork_id')
            
            if not token_id or not license_type:
                raise HTTPException(status_code=400, detail="Missing license data in order")
            
            # Get license and ticket collections
            from app.db.database import get_license_collection
            licenses_collection = get_license_collection()
            artworks_collection = get_artwork_collection()
            
            # ✅ Find pending license by paypal_order_id (primary) or by token_id + buyer_id (fallback)
            pending_license = await licenses_collection.find_one({
                "paypal_order_id": order_id,
                "status": "PENDING"
            })
            
            # ✅ Fallback: If not found by order_id, try to find by token_id and buyer_id
            if not pending_license:
                buyer_id = str(current_user.get('id', '') or current_user.get('_id', ''))
                if buyer_id and token_id:
                    pending_license = await licenses_collection.find_one({
                        "token_id": token_id,
                        "buyer_id": buyer_id,
                        "status": "PENDING",
                        "payment_method": "paypal"
                    })
                    if pending_license:
                        logger.info(f"✅ Found pending license by token_id + buyer_id fallback")
            
            # ✅ Payment confirmed - Now create license (not before payment)
            if pending_license:
                # Update existing pending license (if somehow exists)
                license_id = pending_license.get('license_id')
                logger.info(f"✅ Found pending license {license_id}, activating...")
                
                # ✅ Check if already confirmed
                if pending_license.get("status") == "CONFIRMED" and pending_license.get("is_active"):
                    logger.warning(f"⚠️ License {license_id} is already confirmed. Duplicate payment callback.")
                    return {
                        "success": True,
                        "message": "License already confirmed",
                        "license_id": license_id,
                        "already_processed": True
                    }

                buyer_email = current_user.get('email')  # ✅ Get buyer email
                
                # Update to confirmed
                await licenses_collection.update_one(
                    {"license_id": license_id},
                    {
                        "$set": {
                            "is_active": True,
                            "status": "CONFIRMED",
                            "buyer_email": buyer_email,
                            "purchase_time": datetime.utcnow(),
                            "updated_at": datetime.utcnow()
                        }
                    }
                )
                
                logger.info(f"✅ License {license_id} activated successfully")
            else:
                # ✅ Create license ONLY after payment confirmation
                # Check if already exists (duplicate callback)
                existing_confirmed = await licenses_collection.find_one({
                    "paypal_order_id": order_id,
                    "status": "CONFIRMED",
                    "is_active": True
                })
                
                if existing_confirmed:
                    logger.warning(f"⚠️ License already exists and is confirmed for order {order_id}")
                    return {
                        "success": True,
                        "message": "License already confirmed",
                        "license_id": existing_confirmed.get("license_id"),
                        "already_processed": True
                    }
                
                # ✅ Check for duplicate active license
                buyer_id = str(current_user.get('id', '') or current_user.get('_id', ''))
                existing_active = await licenses_collection.find_one({
                    "token_id": token_id,
                    "buyer_id": buyer_id,
                    "payment_method": "paypal",
                    "status": "CONFIRMED",
                    "is_active": True
                })
                
                if existing_active:
                    logger.warning(f"⚠️ User {buyer_id} already has an active license (#{existing_active.get('license_id')}) for token {token_id}")
                    return {
                        "success": True,
                        "message": "License already exists for this ticket",
                        "license_id": existing_active.get("license_id"),
                        "already_processed": True
                    }
                
                # ✅ CREATE LICENSE AFTER PAYMENT CONFIRMATION
                logger.info(f"✅ Payment confirmed for order {order_id}, creating license...")
                
                # Get ticket info
                artwork_doc = await artworks_collection.find_one({"token_id": token_id}, sort=[("_id", -1)])
                if not artwork_doc:
                    raise HTTPException(status_code=404, detail="Ticket not found")
                
                artwork_id = str(artwork_doc.get('_id', ''))
                owner_id = artwork_doc.get('owner_id')
                buyer_id = str(current_user.get('id', '') or current_user.get('_id', ''))
                artwork_price = artwork_doc.get("price", 0.0)
                
                # # Calculate license count
                # license_count = await licenses_collection.count_documents({}) + 1
                
                # Get amount from order
                amount_usd = order_data.get('amount', 0.0)
                if isinstance(amount_usd, str):
                    amount_usd = float(amount_usd)
                
                # Calculate license fees for display
                from services.license_config_service import LicenseConfigService
                config = await LicenseConfigService.get_active_config()
                fee_calculation = await LicenseConfigService.calculate_license_fees(
                    license_type, 
                    artwork_price, 
                    config,
                    responsible_use_addon=artwork_doc.get("responsible_use_addon")
                )

                # ✅ Generate license_id with prefix (off-chain only)
                license_id = await generate_license_id("paypal", licenses_collection)
                
                if not license_id:
                    raise HTTPException(
                        status_code=500,
                        detail="Failed to generate license ID"
                    )
                
                buyer_email = current_user.get('email')
                buyer_email = current_user.get('email')
                # ✅ CREATE LICENSE WITH CONFIRMED STATUS
                license_dict = {
                    "license_id": license_id,
                    "token_id": token_id,
                    "buyer_id": buyer_id,
                    "buyer_email": buyer_email,
                    "owner_id": str(owner_id),
                    "buyer_address": None,
                    "owner_address": None,
                    "license_type": license_type,
                    "total_amount_eth": fee_calculation.total_amount_eth,
                    "total_amount_wei": fee_calculation.total_amount_wei,
                    "total_amount_usd": amount_usd,
                    "is_active": True,  # ✅ Active immediately after payment confirmation
                    "purchase_time": datetime.utcnow(),
                    "status": "CONFIRMED",  # ✅ Confirmed status
                    "payment_method": "paypal",
                    "paypal_order_id": order_id,
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow()
                }
                
                result = await licenses_collection.insert_one(license_dict)
                logger.info(f"✅✅✅ Created CONFIRMED license {license_id} for token {token_id} after payment confirmation")
            
            # Update ticket license status
            await artworks_collection.update_one(
                {"_id": artwork_doc.get("_id")},
                {"$set": {"is_licensed": True, "updated_at": datetime.utcnow()}}
            )
            
            # ✅ Handle seller payout - Owner receives License Fee only (not total minus platform fee)
            seller_user_id = order_data.get('seller_user_id') or license_data.get('seller_user_id')
            
            # ✅ Get amount_usd from order_data (needed for payout calculation)
            amount_usd = order_data.get('amount', 0.0)
            if isinstance(amount_usd, str):
                amount_usd = float(amount_usd)
            
            logger.info(f"💰 License Payout Check:")
            logger.info(f"   seller_user_id from order_data: {order_data.get('seller_user_id')}")
            logger.info(f"   seller_user_id from license_data: {license_data.get('seller_user_id') if license_data else 'N/A'}")
            logger.info(f"   Final seller_user_id: {seller_user_id}")
            logger.info(f"   amount_usd: ${amount_usd:.2f} USD")
            logger.info(f"   license_fee_usd in order_data: {order_data.get('license_fee_usd')}")
            logger.info(f"   platform_fee_usd in order_data: {order_data.get('platform_fee_usd')}")
            
            if seller_user_id:
                try:
                    # Get seller info for payout
                    from app.db.database import get_user_collection
                    from bson import ObjectId
                    users_collection = get_user_collection()
                    
                    # ✅ Try multiple lookup methods for seller user
                    seller_user = None
                    seller_user_id_str = str(seller_user_id)
                    
                    if ObjectId.is_valid(seller_user_id_str):
                        seller_user = await users_collection.find_one({"_id": ObjectId(seller_user_id_str)})
                    if not seller_user:
                        seller_user = await users_collection.find_one({"user_id": seller_user_id_str})
                    if not seller_user:
                        seller_user = await users_collection.find_one({"_id": seller_user_id_str})
                    if not seller_user:
                        seller_user = await users_collection.find_one({"id": seller_user_id_str})
                    
                    logger.info(f"🔍 Seller lookup - seller_user_id: {seller_user_id_str}, found: {seller_user is not None}")
                    
                    if seller_user:
                        seller_email = seller_user.get('email')
                        seller_merchant_id = seller_user.get('paypal_merchant_id')
                        seller_paypal_onboarded = seller_user.get('paypal_onboarded', False)
                        
                        logger.info(f"✅ Seller user found:")
                        logger.info(f"   Email: {seller_email}")
                        logger.info(f"   Merchant ID: {seller_merchant_id}")
                        logger.info(f"   PayPal Onboarded: {seller_paypal_onboarded}")
                        
                        # ✅ Get license fee breakdown from order data (stored during order creation)
                        # On-chain style: License Fee - Seller Platform Fee = Owner Receives
                        license_fee_usd = order_data.get('license_fee_usd')
                        buyer_platform_fee_usd = order_data.get('buyer_platform_fee_usd')
                        seller_platform_fee_usd = order_data.get('seller_platform_fee_usd')
                        platform_fee_usd = order_data.get('platform_fee_usd')
                        owner_receives_usd = order_data.get('owner_receives_usd')  # ✅ Pre-calculated
                        
                        # ✅ If license fee breakdown not in order data, calculate it (fallback)
                        if license_fee_usd is None or license_fee_usd <= 0:
                            # Fallback: Calculate from ticket price and license percentage
                            artwork_doc = await artworks_collection.find_one({"token_id": token_id}, sort=[("_id", -1)])
                            if artwork_doc:
                                artwork_price_eth = artwork_doc.get('price', 0.0)
                                if artwork_price_eth and artwork_price_eth > 0:
                                    from services.license_config_service import LicenseConfigService
                                    from app.api.v1.ticket import get_current_global_fee
                                    
                                    config = await LicenseConfigService.get_active_config()
                                    platform_fee_percentage = await get_current_global_fee()
                                    PLATFORM_FEE_RATE = platform_fee_percentage / 100
                                    
                                    license_percentages = {
                                        "LINK_ONLY": config.link_only_percentage,
                                        "ACCESS_WITH_WM": config.watermark_percentage,
                                        "FULL_ACCESS": config.full_access_percentage
                                    }
                                    license_percentage = license_percentages.get(license_type, 20.0)
                                    
                                    eth_to_usd_rate = 2700.0
                                    artwork_price_usd = float(artwork_price_eth) * eth_to_usd_rate
                                    
                                    # ✅ On-chain style calculation
                                    license_fee_usd = round((artwork_price_usd * license_percentage) / 100, 2)
                                    buyer_platform_fee_usd = round(artwork_price_usd * PLATFORM_FEE_RATE, 2)
                                    seller_platform_fee_usd = round(artwork_price_usd * PLATFORM_FEE_RATE, 2)
                                    platform_fee_usd = buyer_platform_fee_usd + seller_platform_fee_usd
                                    owner_receives_usd = round(license_fee_usd - seller_platform_fee_usd, 2)
                                    
                                    logger.info(f"💰 Calculated license fee breakdown (fallback - on-chain style):")
                                    logger.info(f"   License Fee: ${license_fee_usd:.2f} USD")
                                    logger.info(f"   Buyer Platform Fee: ${buyer_platform_fee_usd:.2f} USD")
                                    logger.info(f"   Seller Platform Fee: ${seller_platform_fee_usd:.2f} USD")
                                    logger.info(f"   Owner Receives: ${owner_receives_usd:.2f} USD")
                                    logger.info(f"   Platform Receives: ${platform_fee_usd:.2f} USD")
                                else:
                                    logger.warning(f"⚠️ Ticket price not available, cannot calculate license fee")
                                    license_fee_usd = 0.0
                                    owner_receives_usd = 0.0
                            else:
                                logger.warning(f"⚠️ Ticket not found, cannot calculate license fee")
                                license_fee_usd = 0.0
                                owner_receives_usd = 0.0
                        
                        # ✅ Owner receives: License Fee - Seller Platform Fee (same as on-chain)
                        if owner_receives_usd is None or owner_receives_usd <= 0:
                            # Fallback: Calculate from license_fee and seller_platform_fee
                            if seller_platform_fee_usd is not None and seller_platform_fee_usd > 0:
                                owner_receives_usd = round(license_fee_usd - seller_platform_fee_usd, 2)
                            else:
                                # Last resort: Use license_fee (backward compatibility)
                                owner_receives_usd = license_fee_usd
                        
                        owner_payout_amount = max(0.0, owner_receives_usd)  # Ensure non-negative
                        
                        logger.info(f"💰 License Payout Calculation (On-chain style):")
                        logger.info(f"   Total Payment (buyer pays): ${amount_usd:.2f} USD")
                        logger.info(f"   License Fee: ${license_fee_usd:.2f} USD")
                        logger.info(f"   Buyer Platform Fee: ${buyer_platform_fee_usd:.2f} USD")
                        logger.info(f"   Seller Platform Fee: ${seller_platform_fee_usd:.2f} USD")
                        logger.info(f"   Owner Receives (License Fee - Seller Platform Fee): ${owner_payout_amount:.2f} USD")
                        logger.info(f"   Platform Receives (Buyer + Seller Platform Fee): ${platform_fee_usd:.2f} USD")
                        
                        if owner_payout_amount > 0:
                            if seller_merchant_id and seller_paypal_onboarded:
                                # Payout to owner: License Fee - Seller Platform Fee
                                logger.info(f"💸 Initiating owner payout: ${owner_payout_amount:.2f} USD to {seller_email} (merchant_id: {seller_merchant_id})")
                                payout_result = await paypal_service.payout_to_seller(
                                    order_id=order_id,
                                    seller_email=seller_email,
                                    amount=owner_payout_amount,  # ✅ License Fee - Seller Platform Fee
                                    seller_merchant_id=seller_merchant_id,
                                    currency='USD'
                                )
                                
                                if payout_result.get('success'):
                                    logger.info(f"✅✅✅ OWNER PAYOUT SUCCESSFUL: ${owner_payout_amount:.2f} USD to {seller_email}")
                                    logger.info(f"   Payout Batch ID: {payout_result.get('payout_batch_id', 'N/A')}")
                                else:
                                    logger.error(f"❌❌❌ OWNER PAYOUT FAILED: {payout_result.get('error', 'Unknown error')}")
                                    logger.error(f"   Seller: {seller_email}, Amount: ${owner_payout_amount:.2f} USD")
                            else:
                                logger.warning(f"⚠️⚠️⚠️ OWNER NOT ONBOARDED - PAYOUT SKIPPED")
                                logger.warning(f"   Seller: {seller_email}")
                                logger.warning(f"   Merchant ID: {seller_merchant_id} (REQUIRED)")
                                logger.warning(f"   PayPal Onboarded: {seller_paypal_onboarded} (REQUIRED)")
                                logger.warning(f"   Amount ${owner_payout_amount:.2f} USD will be held by platform until owner completes PayPal onboarding.")
                        else:
                            logger.warning(f"⚠️ Owner payout amount is 0 or invalid, skipping payout")
                    else:
                        logger.error(f"❌ Seller user NOT FOUND for seller_user_id: {seller_user_id_str}")
                        logger.error(f"   Cannot process payout - seller user lookup failed")
                except Exception as e:
                    logger.warning(f"⚠️ Error processing owner payout: {e}", exc_info=True)
            
            logger.info(f"✅ PayPal license purchase completed for token {token_id}")

        await UserHistoryService.log_user_action(
            user_id=str(current_user['id']),
            action=transaction_type,
            artwork_id=artwork_id,
            artwork_token_id=order_data.get('token_id'),
            metadata={
                "payment_method": "paypal",
                "order_id": order_id,
                "amount": order_data['amount'],
                "type": transaction_type
            }
        )

        # ✅ REDIS CACHE: Invalidate ticket cache after PayPal payment
        try:
            invalidate_artworks_cache()
            logger.info("🗑️ Ticket cache invalidated after PayPal payment")
        except Exception as cache_error:
            logger.warning(f"⚠️ Failed to invalidate cache: {cache_error}")

        return {
            "success": True,
            "message": f"PayPal {transaction_type} completed successfully",
            "order_id": order_id,
            "artwork_id": artwork_id,
            "transaction_type": transaction_type
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"PayPal confirmation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to complete PayPal transaction: {str(e)}")

# ✅ NEW: Blockchain Registration Endpoints for Off-Chain Tickets
@router.post("/{artwork_id}/register-on-chain")
async def register_artwork_on_chain(
    artwork_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Prepare blockchain registration transaction for an existing off-chain ticket.
    User must be the owner and have a wallet address.
    """
    try:
        from bson import ObjectId
        
        artworks_collection = get_artwork_collection()
        
        # ✅ Try multiple lookup methods to find ticket
        artwork_doc = None
        
        # Method 1: Try as MongoDB ObjectId
        if ObjectId.is_valid(artwork_id):
            artwork_doc = await artworks_collection.find_one({"_id": ObjectId(artwork_id)})
            if artwork_doc:
                logger.info(f"✅ Found ticket by MongoDB _id: {artwork_id}")
        
        # Method 2: Try as string _id (if Method 1 failed)
        if not artwork_doc:
            artwork_doc = await artworks_collection.find_one({"_id": artwork_id})
            if artwork_doc:
                logger.info(f"✅ Found ticket by string _id: {artwork_id}")
        
        # Method 3: Try by token_id as fallback (if artwork_id is actually a token_id)
        if not artwork_doc:
            try:
                token_id_int = int(artwork_id)
                artwork_doc = await artworks_collection.find_one({"token_id": token_id_int}, sort=[("_id", -1)])
                if artwork_doc:
                    logger.info(f"✅ Found ticket by token_id: {token_id_int}")
            except (ValueError, TypeError):
                pass
        
        if not artwork_doc:
            logger.error(f"❌ Ticket not found with ID: {artwork_id} (tried _id as ObjectId, _id as string, and token_id)")
            raise HTTPException(status_code=404, detail=f"Ticket not found with ID: {artwork_id}")
        
        # ✅ Validate: Ticket must be off-chain
        is_on_chain = artwork_doc.get("is_on_chain")
        if is_on_chain is None:
            # Backward compatibility: check old fields
            payment_method = artwork_doc.get("payment_method", "crypto")
            is_virtual_token = artwork_doc.get("is_virtual_token", False)
            if payment_method == "paypal" or is_virtual_token:
                is_on_chain = False
            else:
                is_on_chain = True
        
        if is_on_chain:
            raise HTTPException(
                status_code=400,
                detail="This ticket is already registered on blockchain. Cannot register again."
            )
        
        # ✅ Validate: User must be the owner
        user_id = str(current_user.get('id') or current_user.get('_id') or current_user.get('user_id') or '')
        owner_id = str(artwork_doc.get('owner_id', ''))
        
        if user_id != owner_id:
            raise HTTPException(
                status_code=403,
                detail="Only the ticket owner can register it on blockchain"
            )
        
        # ✅ Validate: User must have wallet address
        wallet_address = current_user.get('wallet_address')
        if not wallet_address:
            raise HTTPException(
                status_code=400,
                detail="Wallet address required. Please connect your wallet to register ticket on blockchain."
            )
        
        # Get ticket data
        metadata_uri = artwork_doc.get('metadata_uri')
        if not metadata_uri:
            raise HTTPException(
                status_code=400,
                detail="Ticket metadata URI not found. Cannot register on blockchain."
            )
        
        royalty_percentage = artwork_doc.get('royalty_percentage', 0)
        
        # Prepare blockchain transaction
        tx_data = await web3_service.prepare_register_transaction(
            metadata_uri,
            royalty_percentage,
            from_address=wallet_address,
            is_conversion=True,
            artwork_price_eth=None
        )
        
        logger.info(f"✅ Prepared blockchain registration for ticket {artwork_id}")
        
        return {
            "status": "success",
            "registration_method": "on-chain",
            "transaction_data": tx_data,
            "metadata_uri": metadata_uri,
            "artwork_id": artwork_id,
            "message": "Blockchain registration transaction prepared. Please confirm via MetaMask."
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to prepare blockchain registration: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to prepare blockchain registration: {str(e)}")

@router.post("/{artwork_id}/confirm-on-chain-registration")
async def confirm_on_chain_registration(
    artwork_id: str,
    confirmation_data: dict,
    current_user: dict = Depends(get_current_user)
):
    """
    Confirm blockchain registration for an off-chain ticket.
    Updates ticket to on-chain status with new blockchain token_id.
    """
    try:
        from bson import ObjectId
        
        logger.info(f"🔄 confirm_on_chain_registration called for artwork_id: {artwork_id}")
        logger.info(f"📦 confirmation_data: {confirmation_data}")
        logger.info(f"👤 current_user id: {current_user.get('id') or current_user.get('_id')}")
        
        artworks_collection = get_artwork_collection()
        
        # ✅ Try multiple lookup methods to find ticket (same as register-on-chain endpoint)
        artwork_doc = None
        
        # Method 1: Try as MongoDB ObjectId
        if ObjectId.is_valid(artwork_id):
            artwork_doc = await artworks_collection.find_one({"_id": ObjectId(artwork_id)})
            if artwork_doc:
                logger.info(f"✅ Found ticket by MongoDB _id: {artwork_id}")
        
        # Method 2: Try as string _id (if Method 1 failed)
        if not artwork_doc:
            artwork_doc = await artworks_collection.find_one({"_id": artwork_id})
            if artwork_doc:
                logger.info(f"✅ Found ticket by string _id: {artwork_id}")
        
        # Method 3: Try by token_id as fallback (if artwork_id is actually a token_id)
        if not artwork_doc:
            try:
                token_id_int = int(artwork_id)
                artwork_doc = await artworks_collection.find_one({"token_id": token_id_int}, sort=[("_id", -1)])
                if artwork_doc:
                    logger.info(f"✅ Found ticket by token_id: {token_id_int}")
            except (ValueError, TypeError):
                pass
        
        if not artwork_doc:
            logger.error(f"❌ Ticket not found with ID: {artwork_id} (tried _id as ObjectId, _id as string, and token_id)")
            raise HTTPException(status_code=404, detail=f"Ticket not found with ID: {artwork_id}")
        
        # ✅ Validate: Ticket must be off-chain
        is_on_chain = artwork_doc.get("is_on_chain")
        if is_on_chain is None:
            # Backward compatibility
            payment_method = artwork_doc.get("payment_method", "crypto")
            is_virtual_token = artwork_doc.get("is_virtual_token", False)
            if payment_method == "paypal" or is_virtual_token:
                is_on_chain = False
            else:
                is_on_chain = True
        
        if is_on_chain:
            raise HTTPException(
                status_code=400,
                detail="This ticket is already registered on blockchain"
            )
        
        # ✅ Validate: User must be the owner
        user_id = str(current_user.get('id') or current_user.get('_id') or current_user.get('user_id') or '')
        owner_id = str(artwork_doc.get('owner_id', ''))
        
        if user_id != owner_id:
            raise HTTPException(
                status_code=403,
                detail="Only the ticket owner can confirm blockchain registration"
            )
        
        # ✅ Validate: User must have wallet address
        wallet_address = current_user.get('wallet_address')
        if not wallet_address:
            raise HTTPException(
                status_code=400,
                detail="Wallet address required"
            )
        
        # Verify blockchain transaction
        tx_hash = confirmation_data.get("tx_hash")
        if not tx_hash:
            logger.error(f"❌ Transaction hash missing in confirmation_data for artwork_id: {artwork_id}")
            raise HTTPException(status_code=400, detail="Transaction hash required")
        
        logger.info(f"🔍 Verifying blockchain transaction: {tx_hash}")
        try:
            tx_receipt = await web3_service.get_transaction_receipt(tx_hash)
            if not tx_receipt:
                logger.error(f"❌ Transaction receipt not found for tx_hash: {tx_hash}")
                raise HTTPException(status_code=400, detail="Transaction not found on blockchain")
            if tx_receipt.get("status") != 1:
                logger.error(f"❌ Transaction failed on blockchain. tx_hash: {tx_hash}, status: {tx_receipt.get('status')}")
                raise HTTPException(status_code=400, detail="Blockchain transaction failed")
            logger.info(f"✅ Transaction verified successfully: {tx_hash}")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"❌ Error verifying transaction {tx_hash}: {str(e)}", exc_info=True)
            raise HTTPException(status_code=400, detail=f"Error verifying blockchain transaction: {str(e)}")
        
        # Get new blockchain token_id from transaction
        logger.info(f"🔍 Extracting token_id from transaction: {tx_hash}")
        try:
            new_token_id = await web3_service.get_token_id_from_tx(tx_hash)
            if not new_token_id:
                logger.error(f"❌ Could not extract token_id from transaction: {tx_hash}")
                raise HTTPException(status_code=400, detail="Could not determine token ID from transaction")
            logger.info(f"✅ Extracted token_id: {new_token_id} from transaction: {tx_hash}")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"❌ Error extracting token_id from transaction {tx_hash}: {str(e)}", exc_info=True)
            raise HTTPException(status_code=400, detail=f"Error extracting token ID: {str(e)}")
        
        # ✅ Update ticket: Convert to on-chain
        network = _ensure_wirefluid_network(
            confirmation_data.get("network") or getattr(settings, "ACTIVE_NETWORK", "wirefluid")
        )
        logger.info(f"🌐 Registration network: {network}")

        update_data = {
            "token_id": new_token_id,  # ✅ New blockchain token_id (replaces virtual token_id)
            "is_on_chain": True,  # ✅ Mark as on-chain
            "registration_method": "on-chain",  # ✅ Update registration method
            "network": network,  # ✅ DYNAMIC: Update network
            "creator_address": wallet_address,  # ✅ Set creator address
            "owner_address": wallet_address,  # ✅ Set owner address
            "tx_hash": tx_hash,  # ✅ Store transaction hash
            "updated_at": datetime.utcnow(),
            # Keep old fields for backward compatibility
            "payment_method": "crypto",  # Update old field
            "is_virtual_token": False,  # Update old field
            # ✅ Keep all existing data (history, licenses, etc.)
            # ✅ Keep paypal_order_id for historical tracking
        }
        
        # ✅ Use the ticket's _id directly from the found document
        # MongoDB always returns _id as ObjectId, so use it directly
        artwork_object_id = artwork_doc.get("_id")
        if not artwork_object_id:
            logger.error(f"❌ Ticket document has no _id field: {artwork_id}")
            raise HTTPException(status_code=500, detail="Ticket document missing _id field")
        
        # Log the _id type and current ticket state for debugging
        logger.info(f"🔍 Ticket _id from document - type: {type(artwork_object_id).__name__}, value: {artwork_object_id}, repr: {repr(artwork_object_id)}")
        logger.info(f"📋 Current ticket state BEFORE update:")
        logger.info(f"   token_id: {artwork_doc.get('token_id')} (type: {type(artwork_doc.get('token_id')).__name__})")
        logger.info(f"   is_on_chain: {artwork_doc.get('is_on_chain')} (type: {type(artwork_doc.get('is_on_chain')).__name__})")
        logger.info(f"   registration_method: {artwork_doc.get('registration_method')}")
        logger.info(f"📝 Update data to apply:")
        logger.info(f"   token_id: {update_data.get('token_id')} (type: {type(update_data.get('token_id')).__name__})")
        logger.info(f"   is_on_chain: {update_data.get('is_on_chain')} (type: {type(update_data.get('is_on_chain')).__name__})")
        logger.info(f"   registration_method: {update_data.get('registration_method')}")
        
        # ✅ Use the _id directly from the document (it's already the correct type from MongoDB)
        # Don't try to convert it - MongoDB returns it as ObjectId
        logger.info(f"🔄 Executing update_one with _id: {artwork_object_id} (type: {type(artwork_object_id).__name__})")
        result = await artworks_collection.update_one(
            {"_id": artwork_object_id},
            {"$set": update_data}
        )
        
        logger.info(f"📊 Update result - matched_count: {result.matched_count}, modified_count: {result.modified_count}, upserted_id: {result.upserted_id}")
        
        if result.matched_count == 0:
            logger.error(f"❌ No ticket found with _id: {artwork_object_id} (type: {type(artwork_object_id).__name__})")
            # Try to find it again to see what's wrong
            retry_find = await artworks_collection.find_one({"_id": artwork_object_id})
            logger.error(f"🔍 Retry find with same _id returned: {retry_find is not None}")
            if retry_find:
                logger.error(f"🔍 Retry find _id type: {type(retry_find.get('_id')).__name__}, value: {retry_find.get('_id')}")
            raise HTTPException(status_code=404, detail=f"Ticket not found with _id: {artwork_object_id}")
        
        if result.modified_count == 0:
            # Check if the update data is actually different from current state
            logger.warning(f"⚠️ Update operation returned modified_count=0 - checking if ticket already has these values")
            # Re-fetch to check current state
            current_artwork = await artworks_collection.find_one({"_id": artwork_object_id})
            if current_artwork:
                current_token_id = current_artwork.get('token_id')
                current_is_on_chain = current_artwork.get('is_on_chain')
                current_reg_method = current_artwork.get('registration_method')
                logger.info(f"📋 Current ticket state AFTER update attempt:")
                logger.info(f"   token_id: {current_token_id} (type: {type(current_token_id).__name__})")
                logger.info(f"   is_on_chain: {current_is_on_chain} (type: {type(current_is_on_chain).__name__})")
                logger.info(f"   registration_method: {current_reg_method}")
                
                # If the ticket already has the correct values, that's okay - don't fail
                if (current_token_id == new_token_id and 
                    current_is_on_chain == True and
                    current_reg_method == 'on-chain'):
                    logger.info(f"✅ Ticket already has correct values - treating as success")
                else:
                    logger.error(f"❌ Ticket values don't match expected!")
                    logger.error(f"   Expected: token_id={new_token_id}, is_on_chain=True, registration_method=on-chain")
                    logger.error(f"   Current:  token_id={current_token_id}, is_on_chain={current_is_on_chain}, registration_method={current_reg_method}")
                    raise HTTPException(status_code=500, detail="Failed to update ticket (no documents modified)")
            else:
                logger.error(f"❌ Could not re-fetch ticket after update attempt")
                raise HTTPException(status_code=500, detail="Failed to update ticket (no documents modified)")
        
        logger.info(f"✅ Ticket {artwork_id} successfully registered on blockchain with token_id {new_token_id}")
        
        # Log user action (non-blocking - don't fail if this fails)
        try:
            await UserHistoryService.log_user_action(
                user_id=user_id,
                action="register_on_chain",
                artwork_id=artwork_id,
                artwork_token_id=new_token_id,
                metadata={
                    "old_token_id": artwork_doc.get("token_id"),
                    "new_token_id": new_token_id,
                    "tx_hash": tx_hash
                }
            )
            logger.info(f"✅ User action logged for ticket {artwork_id}")
        except Exception as log_error:
            # Don't fail the whole operation if logging fails
            logger.warning(f"⚠️ Failed to log user action for ticket {artwork_id}: {str(log_error)}")
        # ✅ REDIS CACHE: Invalidate ticket cache after on-chain registration
        try:
            invalidate_artworks_cache()
            invalidate_artwork_cache(new_token_id)
            invalidate_blockchain_cache(new_token_id)
            logger.info("🗑️ Ticket cache invalidated after on-chain registration")
        except Exception as cache_error:
            logger.warning(f"⚠️ Failed to invalidate cache: {cache_error}")
        return {
            "success": True,
            "artwork_id": artwork_id,
            "token_id": new_token_id,
            "tx_hash": tx_hash,
            "message": "Ticket successfully registered on blockchain"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to confirm blockchain registration: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to confirm blockchain registration: {str(e)}")

# ============================================
# IMAGE PROTECTION UTILITIES
# ============================================

def resize_image_to_resolution(image_data: bytes, max_dimension: int, content_type: str = "image/jpeg") -> bytes:
    """Resize image to specified maximum dimension while maintaining aspect ratio."""
    from io import BytesIO
    
    img = Image.open(BytesIO(image_data))
    width, height = img.size
    
    if width <= max_dimension and height <= max_dimension:
        return image_data
    
    if width > height:
        new_width = max_dimension
        new_height = int(height * (max_dimension / width))
    else:
        new_height = max_dimension
        new_width = int(width * (max_dimension / height))
    
    img_resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
    
    output = BytesIO()
    if content_type == "image/png":
        img_resized.save(output, format="PNG", optimize=True)
    else:
        if img_resized.mode in ('RGBA', 'P'):
            img_resized = img_resized.convert('RGB')
        img_resized.save(output, format="JPEG", quality=85, optimize=True)
    
    output.seek(0)
    return output.read()

# Image resolution constants
IMAGE_RES_LOW = 400      # Low resolution for direct/unauthorized access
IMAGE_RES_MEDIUM = 800   # Medium resolution for website display with token
IMAGE_RES_FULL = 2048    # Full resolution for owners/FULL_ACCESS licenses

# Watermark text constant
WATERMARK_TEXT = "PSL Entry X protected"

# ✅ CONFIGURABLE: Watermark opacity (0-255)
# 0 = fully transparent, 255 = fully opaque
# Recommended values:
#   100 = ~39% - very subtle, barely visible
#   150 = ~59% - moderate visibility
#   180 = ~70% - clearly visible but not overwhelming (DEFAULT)
#   200 = ~78% - very prominent
#   230 = ~90% - extremely visible
WATERMARK_OPACITY = 180

# Cache for pre-rendered watermark tiles (key: font_size_opacity_text)
_watermark_tile_cache = {}


def apply_watermark(image_data: bytes, watermark_text: str = WATERMARK_TEXT, content_type: str = "image/jpeg") -> bytes:
    """
    Apply a semi-transparent watermark to an image.
    OPTIMIZED: Creates single rotated tile and tiles it across image.
    
    Args:
        image_data: Original image bytes
        watermark_text: Text to use as watermark (default: "PSL Entry X protected")
        content_type: Image MIME type
        
    Returns:
        Watermarked image bytes
    """
    from io import BytesIO
    from PIL import ImageDraw, ImageFont
    
    try:
        img = Image.open(BytesIO(image_data))
        width, height = img.size
        
        # Convert to RGBA for transparency support
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
        
        # Calculate font size based on image dimensions
        font_size = max(16, min(width, height) // 20)
        
        # Get or create cached watermark tile (includes opacity in key for live updates)
        cache_key = f"{font_size}_{WATERMARK_OPACITY}_{watermark_text}"
        if cache_key not in _watermark_tile_cache:
            # Create the rotated text tile once
            try:
                font = ImageFont.truetype("arial.ttf", font_size)
            except:
                try:
                    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", font_size)
                except:
                    font = ImageFont.load_default()
            
            # Create text image
            dummy_draw = ImageDraw.Draw(Image.new('RGBA', (1, 1)))
            bbox = dummy_draw.textbbox((0, 0), watermark_text, font=font)
            text_width = bbox[2] - bbox[0] + 10
            text_height = bbox[3] - bbox[1] + 10
            
            txt_img = Image.new('RGBA', (text_width, text_height), (255, 255, 255, 0))
            txt_draw = ImageDraw.Draw(txt_img)
            txt_draw.text((5, 5), watermark_text, font=font, fill=(255, 255, 255, WATERMARK_OPACITY))
            
            # Rotate once
            rotated_tile = txt_img.rotate(30, expand=True, resample=Image.Resampling.BILINEAR)
            _watermark_tile_cache[cache_key] = rotated_tile
        
        tile = _watermark_tile_cache[cache_key]
        tile_w, tile_h = tile.size
        
        # Create overlay by tiling the pre-rotated watermark
        overlay = Image.new('RGBA', (width, height), (255, 255, 255, 0))
        
        # Tile spacing
        spacing_x = tile_w + 60
        spacing_y = tile_h + 40
        
        # Simple tiling with offset for alternating rows
        y = 0
        row = 0
        while y < height + tile_h:
            x = -tile_w if row % 2 == 0 else -tile_w // 2
            while x < width + tile_w:
                overlay.paste(tile, (int(x), int(y)), tile)
                x += spacing_x
            y += spacing_y
            row += 1
        
        # Composite the watermark onto the original image
        img = Image.alpha_composite(img, overlay)
        
        # Convert back to RGB for JPEG output
        output = BytesIO()
        if content_type == "image/png":
            img.save(output, format="PNG", optimize=True)
        else:
            img = img.convert('RGB')
            img.save(output, format="JPEG", quality=85, optimize=True)
        
        output.seek(0)
        return output.read()
        
    except Exception as e:
        logger.error(f"Error applying watermark: {e}", exc_info=True)
        # Return original image if watermarking fails
        return image_data



# ✅ NEW: Get image access token
@router.get("/{artwork_identifier}/image-token")
async def get_image_token(artwork_identifier: str):
    """Generate a short-lived token for image access (5 min expiry)."""
    from app.core.security import create_image_token
    from app.utils.ticket import resolve_artwork_identifier
    
    try:
        ticket = await resolve_artwork_identifier(artwork_identifier)
        if not ticket:
            raise HTTPException(status_code=404, detail="Ticket not found")
        
        real_token_id = ticket.get("token_id")
        artwork_db_id = str(ticket.get("_id"))
        
        # Use token_id if available, fallback to DB _id
        token = create_image_token(real_token_id or artwork_db_id, expires_minutes=5)
        
        return {
            "token": token,
            "expires_in": 300,
            "image_url": f"/api/v1/tickets/{artwork_identifier}/image?token={token}"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating image token: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate image token")


# ✅ MODIFIED: Get ticket image with multi-resolution protection
@router.get("/{artwork_identifier}/image")
async def get_artwork_image(artwork_identifier: str, token: Optional[str] = None):
    """
    Get ticket image with resolution based on access method:
    - With valid token: 800px medium resolution (for website display)
    - Without token/invalid: 400px low resolution (for direct URL access)
    """
    from app.core.security import verify_image_token
    from app.utils.ticket import resolve_artwork_identifier
    
    try:
        # Get ticket info
        artwork_doc = await resolve_artwork_identifier(artwork_identifier)
        if not artwork_doc:
            raise HTTPException(status_code=404, detail="Ticket not found for image")
        
        real_token_id = artwork_doc.get("token_id")
        artwork_db_id = str(artwork_doc.get("_id"))

        # Determine resolution and watermark based on token validity
        # Verify token against either token_id or Mongo ID
        if token and verify_image_token(token, real_token_id or artwork_db_id):
            target_resolution = IMAGE_RES_MEDIUM  # 800px for valid token
            apply_wm = False  # ✅ NO watermark for website display
            logger.info(f"🖼️ Image request for token_id: {real_token_id} - VALID TOKEN - serving {IMAGE_RES_MEDIUM}px (no watermark)")
        else:
            target_resolution = IMAGE_RES_LOW  # 400px for no/invalid token
            apply_wm = True  # ✅ Watermark for bypass attempts
            logger.info(f"🖼️ Image request for ticket: {artwork_identifier} - NO/INVALID TOKEN - serving {IMAGE_RES_LOW}px (with watermark)")
        
        artworks_collection = get_artwork_collection()
        
        # ✅ FIX: Use resolved ticket doc for all logic
        if artwork_doc:
            payment_method = artwork_doc.get("payment_method", "crypto")
            is_virtual_token = artwork_doc.get("is_virtual_token", False)
            
            # Use cached or metadata from doc instead of re-querying blockchain
            # This is safer and faster during migration
            logger.info(f"✅ Using resolved artwork_doc: {artwork_db_id}")
        else:
            logger.warning(f"❌ Ticket not found for identifier: {artwork_identifier}")
            raise HTTPException(status_code=404, detail="Ticket not found")
        
        # Check if fallback image exists and has GridFS ID
        has_fallback = artwork_doc.get("has_fallback_image")
        
        logger.info(f"✅ Ticket found for token_id: {real_token_id}, _id: {artwork_doc.get('_id')}")
        
        # Check if fallback image exists and has GridFS ID
        has_fallback = artwork_doc.get("has_fallback_image")
        image_metadata_id = artwork_doc.get("image_metadata_id")
        
        logger.info(f"📸 Image metadata check - has_fallback_image: {has_fallback}, image_metadata_id: {image_metadata_id}")
        
        if not has_fallback or not image_metadata_id:
            logger.warning(f"❌ No fallback image available for ticket: {artwork_identifier} - has_fallback_image: {has_fallback}, image_metadata_id: {image_metadata_id}")
            raise HTTPException(status_code=404, detail="No fallback image available")
        
        fs = get_gridfs()
        gridfs_id = artwork_doc["image_metadata_id"]
        
        logger.info(f"📦 Attempting to retrieve GridFS file with ID: {gridfs_id}")
        
        try:
            # Convert string ID back to ObjectId for GridFS
            from bson import ObjectId
            
            # Add validation for ObjectId format
            if not ObjectId.is_valid(gridfs_id):
                logger.error(f"❌ Invalid ObjectId format: {gridfs_id}")
                raise HTTPException(status_code=500, detail="Invalid image storage ID format")
                
            gridfs_object_id = ObjectId(gridfs_id)
            logger.info(f"✅ Valid ObjectId, attempting to open GridFS stream...")
            
            grid_out = await fs.open_download_stream(gridfs_object_id)
            image_data = await grid_out.read()
            content_type = grid_out.metadata.get("content_type", "image/jpeg")
            
            logger.info(f"✅ Successfully retrieved image from GridFS - size: {len(image_data)} bytes, content_type: {content_type}")
            
            # ✅ NEW: Resize image based on access level
            original_size = len(image_data)
            image_data = resize_image_to_resolution(image_data, target_resolution, content_type)
            logger.info(f"🔄 Image resized to {target_resolution}px - original: {original_size} bytes, resized: {len(image_data)} bytes")
            
            # ✅ Apply watermark ONLY for bypass attempts (no valid token)
            if apply_wm:
                image_data = apply_watermark(image_data, WATERMARK_TEXT, content_type)
                logger.info(f"🔒 Watermark applied to image (bypass protection)")
            else:
                logger.info(f"✅ Clean image served (valid token)")
            
            from fastapi.responses import Response
            return Response(
                content=image_data,
                media_type=content_type,
                headers={
                    "Cache-Control": "private, max-age=300" if target_resolution == IMAGE_RES_MEDIUM else "public, max-age=3600",
                    "Content-Disposition": f"inline; filename=artwork_{real_token_id or artwork_db_id}.jpg",
                    "Vary": "Origin",
                    "X-Image-Resolution": f"{target_resolution}px",
                    "X-Watermarked": "true" if apply_wm else "false"
                }
            )
        except Exception as e:
            logger.error(f"❌ Failed to retrieve image for ticket {artwork_identifier} from GridFS: {str(e)}", exc_info=True)
            raise HTTPException(status_code=404, detail=f"Image not found in storage: {str(e)}")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting ticket image {artwork_identifier}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get ticket image")


# ✅ NEW: Licensed image endpoint - serves image based on user's license
@router.get("/{token_id}/licensed-image")
async def get_licensed_artwork_image(
    token_id: int,
    request: Request,
    auth: Optional[str] = None
):
    """
    Get ticket image based on user's license level.
    
    Access levels:
    - OWNER: Full quality, no watermark
    - FULL_ACCESS: Full quality, no watermark
    - ACCESS_WITH_WM: Medium quality (800px) with watermark
    - LINK_ONLY: Medium quality (800px) with watermark
    - EXPIRED: Returns 403 with "License Expired" message
    - NO_ACCESS: Returns 403
    
    Supports auth query parameter OR Authorization Bearer header.
    """
    from services.license_access_service import LicenseAccessService, ACCESS_OWNER, ACCESS_FULL, ACCESS_WATERMARK, ACCESS_LINK_ONLY, ACCESS_NONE, ACCESS_EXPIRED
    from jose import jwt, JWTError
    from app.core.config import settings
    
    try:
        user = None
        token_to_decode = None
        
        # Try auth query parameter first (for direct browser access)
        if auth:
            token_to_decode = auth
            logger.info("Using auth query parameter")
        else:
            # Try Authorization header
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token_to_decode = auth_header.replace("Bearer ", "")
                logger.info("Using Authorization header")
        
        if token_to_decode:
            try:
                payload = jwt.decode(token_to_decode, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
                # JWT contains all the info we need - no database lookup required
                user_id_from_token = payload.get("user_id")
                if user_id_from_token:
                    user = {
                        "id": user_id_from_token,
                        "_id": user_id_from_token,
                        "wallet_address": payload.get("wallet_address"),
                        "email": payload.get("sub")
                    }
                    logger.info(f"✅ Auth successful for user: {user_id_from_token}")
            except jwt.ExpiredSignatureError:
                logger.warning("Auth token expired")
                raise HTTPException(status_code=401, detail="Token expired")
            except JWTError as e:
                logger.warning(f"Invalid auth token: {e}")
                raise HTTPException(status_code=401, detail="Invalid token")
            except Exception as e:
                logger.error(f"Failed to decode auth token: {e}", exc_info=True)
                raise HTTPException(status_code=401, detail="Authentication failed")
        
        if not user:
            raise HTTPException(status_code=401, detail="Not authenticated")
        
        user_id = str(user.get('id') or user.get('_id') or user.get('user_id') or '')
        wallet_address = user.get('wallet_address')
        
        # Get access level for this user on this ticket
        access_level, license_doc = await LicenseAccessService.get_access_level(
            user_id, token_id, wallet_address
        )
        
        logger.info(f"🔑 Licensed image access for token_id: {token_id}, user: {user_id}, level: {access_level}")
        
        # Handle expired license - block access
        if access_level == ACCESS_EXPIRED:
            raise HTTPException(
                status_code=403, 
                detail="License expired. Please renew your license to access this ticket."
            )
        
        # Handle no access
        if access_level == ACCESS_NONE:
            raise HTTPException(
                status_code=403, 
                detail="No valid license found. Please purchase a license to access this ticket."
            )
        
        # Determine resolution and watermark based on access level
        if access_level in [ACCESS_OWNER, ACCESS_FULL]:
            target_resolution = IMAGE_RES_FULL
            apply_wm = False
            logger.info(f"📸 Access level: {access_level} - FULL quality, NO watermark")
        elif access_level in [ACCESS_WATERMARK, ACCESS_LINK_ONLY]:
            target_resolution = IMAGE_RES_MEDIUM
            apply_wm = True
            logger.info(f"📸 Access level: {access_level} - MEDIUM quality, WITH watermark")
        else:
            target_resolution = IMAGE_RES_LOW
            apply_wm = True
            logger.info(f"📸 Access level: {access_level} - LOW quality, WITH watermark")
        
        # Get ticket from database
        artworks_collection = get_artwork_collection()
        artwork_doc = await artworks_collection.find_one(
            {"token_id": token_id},
            sort=[("created_at", -1)]
        )
        
        if not artwork_doc:
            raise HTTPException(status_code=404, detail="Ticket not found")
        
        # Check for fallback image
        has_fallback = artwork_doc.get("has_fallback_image")
        image_metadata_id = artwork_doc.get("image_metadata_id")
        
        if not has_fallback or not image_metadata_id:
            raise HTTPException(status_code=404, detail="No image available for this ticket")
        
        # Get image from GridFS
        fs = get_gridfs()
        
        from bson import ObjectId
        if not ObjectId.is_valid(image_metadata_id):
            raise HTTPException(status_code=500, detail="Invalid image storage ID")
        
        grid_out = await fs.open_download_stream(ObjectId(image_metadata_id))
        image_data = await grid_out.read()
        content_type = grid_out.metadata.get("content_type", "image/jpeg")
        
        original_size = len(image_data)
        logger.info(f"📸 Original image size: {original_size} bytes")
        
        # Resize image
        image_data = resize_image_to_resolution(image_data, target_resolution, content_type)
        logger.info(f"📸 After resize: {len(image_data)} bytes, resolution: {target_resolution}px")
        
        # Apply watermark if needed
        if apply_wm:
            logger.info(f"🔖 Applying watermark: {WATERMARK_TEXT}")
            image_data = apply_watermark(image_data, WATERMARK_TEXT, content_type)
            logger.info(f"🔖 After watermark: {len(image_data)} bytes")
        
        from fastapi.responses import Response
        return Response(
            content=image_data,
            media_type=content_type,
            headers={
                "Cache-Control": "private, max-age=300",
                "Content-Disposition": f"inline; filename=artwork_{token_id}.jpg",
                "X-Image-Resolution": f"{target_resolution}px",
                "X-Access-Level": access_level,
                "X-Watermarked": "true" if apply_wm else "false"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting licensed ticket image {token_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get ticket image")


# ✅ NEW: Licensed download endpoint - allows full download for FULL_ACCESS licenses
@router.get("/{token_id}/licensed-download")
async def download_licensed_artwork(
    token_id: int,
    current_user: dict = Depends(get_current_user)
):
    """
    Download original ticket file (for OWNER or FULL_ACCESS license holders only).
    """
    from services.license_access_service import LicenseAccessService, ACCESS_OWNER, ACCESS_FULL, ACCESS_EXPIRED
    
    try:
        user_id = str(current_user.get('id') or current_user.get('_id') or current_user.get('user_id') or '')
        wallet_address = current_user.get('wallet_address')
        
        # Get access level
        access_level, license_doc = await LicenseAccessService.get_access_level(
            user_id, token_id, wallet_address
        )
        
        logger.info(f"⬇️ Download request for token_id: {token_id}, user: {user_id}, level: {access_level}")
        
        # Only allow download for OWNER or FULL_ACCESS
        if access_level == ACCESS_EXPIRED:
            raise HTTPException(
                status_code=403,
                detail="License expired. Please renew your license to download this ticket."
            )
        
        if access_level not in [ACCESS_OWNER, ACCESS_FULL]:
            raise HTTPException(
                status_code=403,
                detail="Download requires Full Access license. Please upgrade your license to download."
            )
        
        # Get ticket
        artworks_collection = get_artwork_collection()
        artwork_doc = await artworks_collection.find_one(
            {"token_id": token_id},
            sort=[("created_at", -1)]
        )
        
        if not artwork_doc:
            raise HTTPException(status_code=404, detail="Ticket not found")
        
        image_metadata_id = artwork_doc.get("image_metadata_id")
        if not image_metadata_id:
            raise HTTPException(status_code=404, detail="No image available for download")
        
        # Get original image from GridFS
        fs = get_gridfs()
        
        from bson import ObjectId
        grid_out = await fs.open_download_stream(ObjectId(image_metadata_id))
        image_data = await grid_out.read()
        content_type = grid_out.metadata.get("content_type", "image/jpeg")
        
        # Get ticket title for filename
        title = artwork_doc.get("title", f"artwork_{token_id}")
        # Sanitize filename
        import re
        safe_title = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '_')
        extension = "png" if content_type == "image/png" else "jpg"
        
        from fastapi.responses import Response
        return Response(
            content=image_data,
            media_type=content_type,
            headers={
                "Content-Disposition": f"attachment; filename={safe_title}.{extension}",
                "X-Access-Level": access_level
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading ticket {token_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to download ticket")
    
# ✅ Enhanced List tickets (unchanged core logic, but enhanced public model)
@router.get("/", response_model=ArtworkListResponse)
async def list_artworks(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    creator_address: Optional[str] = None,
    owner_address: Optional[str] = None,
    payment_method: Optional[str] = Query(None, description="DEPRECATED: Filter by payment method: 'crypto' or 'paypal'. Use is_on_chain instead."),
    is_on_chain: Optional[bool] = Query(None, description="Filter by on-chain status: true for on-chain, false for off-chain"),
    is_psl_ticket: Optional[bool] = Query(None, description="Filter by PSL Smart-Ticket status: true for tickets only"),
):
    try:
        # ✅ REDIS CACHE: Step 1 - Generate cache key from request parameters
        cache_filters = {
            "cache_version": "artwork_list_v2_psl_from_artworks",
            "page": page,
            "size": size,
            "creator": creator_address,
            "owner": owner_address,
            "payment": payment_method,
            "chain": is_on_chain,
            "is_psl_ticket": is_psl_ticket
        }
        
        # ✅ REDIS CACHE: Step 2 - Try to get from cache first
        cached_response = get_artworks_cache(cache_filters)
        if cached_response:
            logger.info(f"⚡ REDIS CACHE HIT - Returning cached tickets (page {page})")
            return ArtworkListResponse(**cached_response)
        
        logger.info(f"💨 REDIS CACHE MISS - Fetching from database (page {page})")
        
        artworks_collection = get_artwork_collection()

        # Base filter for standard tickets - EXCLUDES PSL unless PSL filter is requested
        filter_query = {
            "token_id": {"$ne": None, "$exists": True},
            "$or": [
                {"is_for_sale": True},
                {"is_for_sale": {"$exists": False}}
            ]
        }

        if is_psl_ticket:
            # PSL filter must fetch from tickets collection and return PSL-only records.
            filter_query["is_psl_ticket"] = True
            logger.info("🎫 Explorer using tickets collection with is_psl_ticket=true")
        else:
            filter_query["is_psl_ticket"] = {"$ne": True}
        
        users_collection = get_user_collection()
        
        # ✅ Filter by on-chain status (NEW - preferred method)
        if is_on_chain is not None and not is_psl_ticket:
            if is_on_chain:
                # On-chain tickets: must be on blockchain
                filter_query["$and"] = filter_query.get("$and", []) + [
                    {
                        "$nor": [
                            {"is_on_chain": False},
                            {"registration_method": "off-chain"},
                            {"payment_method": "paypal"}
                        ]
                    },
                    {
                        "$or": [
                            {"is_on_chain": True},
                            {"registration_method": "on-chain"},
                            {"payment_method": "crypto", "creator_address": {"$ne": None, "$exists": True}},
                            {"payment_method": {"$exists": False}, "creator_address": {"$ne": None, "$exists": True}}
                        ]
                    }
                ]
                logger.info("🔍 Appended on-chain filter to query")
            else:
                # Off-chain tickets: not on blockchain
                filter_query["$and"] = filter_query.get("$and", []) + [
                    {
                        "$or": [
                            {"is_on_chain": False},
                            {"registration_method": "off-chain"},
                            {"payment_method": "paypal"}
                        ]
                    },
                    {
                        "$nor": [
                            {"is_on_chain": True},
                            {"registration_method": "on-chain"}
                        ]
                    }
                ]
                logger.info("🔍 Appended off-chain filter to query")
        
        # ✅ Backward compatibility: Support old payment_method filter
        elif payment_method and not is_psl_ticket:
            if payment_method == "crypto":
                filter_query["payment_method"] = "crypto"
                filter_query["creator_address"] = {"$ne": None, "$exists": True}
            elif payment_method == "paypal":
                filter_query["payment_method"] = "paypal"
        
        if creator_address:
            filter_query["creator_address"] = creator_address.lower()
        if owner_address:
            filter_query["owner_address"] = owner_address.lower()
            
        # ✅ Add PSL Ticket filter (Hackathon Demo)
        if is_psl_ticket:
            logger.info("🎫 Filtering PSL tickets from tickets collection")

        total = await artworks_collection.count_documents(filter_query)
        has_next = (page * size) < total
        skip = (page - 1) * size

        cursor = artworks_collection.find(filter_query).skip(skip).limit(size).sort("created_at", -1)
        artworks_data = await cursor.to_list(length=size)

        # ✅ OPTIMIZATION: Batch fetch all user IDs first (fixes N+1 query problem)
        creator_ids = set()
        owner_ids = set()
        valid_artworks_docs = []
        
        skipped_count = 0
        filtered_out_count = 0
        
        for doc in artworks_data:
            # ✅ Skip tickets with null or missing token_id (except PSL tickets which might be unminted)
            if not is_psl_ticket and (not doc.get("token_id") or doc.get("token_id") is None):
                logger.warning(f"Skipping ticket with null token_id: {doc.get('_id')}")
                skipped_count += 1
                continue
            
            # ✅ Additional validation: Double-check filter criteria (safety check)
            if is_on_chain is not None and not is_psl_ticket:
                doc_is_on_chain = doc.get("is_on_chain")
                doc_registration_method = doc.get("registration_method")
                doc_payment_method = doc.get("payment_method")
                doc_creator_address = doc.get("creator_address")
                
                # Determine if ticket is actually on-chain or off-chain
                is_actually_on_chain = None
                if doc_is_on_chain is not None:
                    is_actually_on_chain = doc_is_on_chain
                elif doc_registration_method:
                    is_actually_on_chain = (doc_registration_method == "on-chain")
                elif doc_payment_method == "crypto" or (not doc_payment_method and doc_creator_address):
                    is_actually_on_chain = True
                elif doc_payment_method == "paypal":
                    is_actually_on_chain = False
                else:
                    is_actually_on_chain = bool(doc_creator_address)
                
                # Filter out tickets that don't match the requested filter
                if is_on_chain and not is_actually_on_chain:
                    logger.warning(f"🚫 Filtered out off-chain ticket from on-chain results: {doc.get('_id')} (token_id: {doc.get('token_id')}) - is_on_chain: {doc_is_on_chain}, registration_method: {doc_registration_method}, payment_method: {doc_payment_method}")
                    filtered_out_count += 1
                    continue
                elif not is_on_chain and is_actually_on_chain:
                    logger.warning(f"🚫 Filtered out on-chain ticket from off-chain results: {doc.get('_id')} (token_id: {doc.get('token_id')}) - is_on_chain: {doc_is_on_chain}, registration_method: {doc_registration_method}, payment_method: {doc_payment_method}")
                    filtered_out_count += 1
                    continue
            
            try:
                # UPDATED: Use validate_document method to handle missing fields
                artwork_db_model = ArtworkInDB.validate_document(doc)
                
                # ✅ Collect user IDs for batch lookup
                if artwork_db_model.creator_id:
                    creator_ids.add(str(artwork_db_model.creator_id))
                if artwork_db_model.owner_id:
                    owner_ids.add(str(artwork_db_model.owner_id))
                
                valid_artworks_docs.append((doc, artwork_db_model))
            except Exception as e:
                logger.error(f"Failed to validate ticket {doc.get('_id', 'unknown')} (token_id: {doc.get('token_id')}): {e}", exc_info=True)
                skipped_count += 1
                continue
        
        # ✅ OPTIMIZATION: Batch fetch all users at once (single query instead of N queries)
        user_cache = {}
        all_user_ids = creator_ids | owner_ids
        
        if all_user_ids:
            # Build queries for different ID formats
            object_id_queries = []
            string_id_queries = []
            user_id_queries = []
            
            for user_id_str in all_user_ids:
                if ObjectId.is_valid(user_id_str):
                    object_id_queries.append(ObjectId(user_id_str))
                string_id_queries.append(user_id_str)
                user_id_queries.append(user_id_str)
            
            # Execute batch queries in parallel
            user_fetch_tasks = []
            if object_id_queries:
                user_fetch_tasks.append(users_collection.find({"_id": {"$in": object_id_queries}}).to_list(length=len(object_id_queries)))
            if string_id_queries:
                user_fetch_tasks.append(users_collection.find({"_id": {"$in": string_id_queries}}).to_list(length=len(string_id_queries)))
            if user_id_queries:
                user_fetch_tasks.append(users_collection.find({"user_id": {"$in": user_id_queries}}).to_list(length=len(user_id_queries)))
            
            if user_fetch_tasks:
                user_results = await asyncio.gather(*user_fetch_tasks)
                # Combine all results and build cache
                for user_list in user_results:
                    for user in user_list:
                        user_id_key = str(user.get("_id"))
                        if user_id_key not in user_cache:
                            user_cache[user_id_key] = user
                        # Also cache by user_id field
                        if user.get("user_id"):
                            user_cache[str(user.get("user_id"))] = user
        
        # ✅ Process tickets with cached user data
        tickets = []
        for doc, artwork_db_model in valid_artworks_docs:
            try:
                artwork_public = ArtworkPublic.from_db_model(artwork_db_model)
                artwork_dict = artwork_public.model_dump()
                
                # ✅ Use cached user data instead of individual queries
                if artwork_db_model.creator_id:
                    creator_id_str = str(artwork_db_model.creator_id)
                    creator_user = user_cache.get(creator_id_str)
                    if creator_user:
                        artwork_dict["creator_name"] = creator_user.get('full_name') or creator_user.get('username') or "Unknown"
                        artwork_dict["creator_email"] = creator_user.get('email') or None
                
                if artwork_db_model.owner_id:
                    owner_id_str = str(artwork_db_model.owner_id)
                    owner_user = user_cache.get(owner_id_str)
                    if owner_user:
                        artwork_dict["owner_name"] = owner_user.get('full_name') or owner_user.get('username') or "Unknown"
                        artwork_dict["owner_email"] = owner_user.get('email') or None
                
                tickets.append(ArtworkPublic(**artwork_dict))
            except Exception as e:
                logger.error(f"Failed to process ticket {doc.get('_id', 'unknown')} (token_id: {doc.get('token_id')}): {e}", exc_info=True)
                skipped_count += 1
                continue
        
        # ✅ Log skipped tickets for debugging
        if skipped_count > 0:
            logger.warning(f"⚠️ Skipped {skipped_count} ticket(s) due to validation errors or null token_id. Expected: {len(artworks_data)}, Got: {len(tickets)}")
        if filtered_out_count > 0:
            logger.warning(f"🚫 Filtered out {filtered_out_count} ticket(s) that didn't match filter criteria (is_on_chain={is_on_chain})")

        # ✅ REDIS CACHE: Step 3 - Build response
        response = ArtworkListResponse(
            tickets=tickets,
            total=total,
            page=page,
            size=size,
            has_next=has_next
        )
        
        # ✅ REDIS CACHE: Step 4 - Cache the response for 5 minutes (300 seconds)
        try:
            set_artworks_cache(cache_filters, response.model_dump(), ttl=300)
            logger.info(f"💾 Cached response for page {page} (TTL: 5 min)")
        except Exception as cache_error:
            # Don't fail if caching fails - just log it
            logger.warning(f"⚠️ Failed to cache response: {cache_error}")
        
        return response
    except Exception as e:
        logger.error(f"Error listing tickets: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list tickets"
        )

# ✅ OPTIMIZED: Get ticket counts by on-chain status (only listed for sale)
@router.get("/counts")
async def get_artwork_counts():
    """Get count of tickets by on-chain status - only counts tickets listed for sale"""
    try:
        # ✅ OPTIMIZATION: Check cache first
        cached_counts = get_cached_counts()
        if cached_counts:
            logger.debug("📊 Returning cached ticket counts")
            return cached_counts
        
        artworks_collection = get_artwork_collection()
        
        # ✅ Base filter: Only tickets listed for sale (same as list_artworks endpoint)
        base_sale_filter = {
            "$or": [
                {"is_for_sale": True},  # Explicitly listed for sale
                {"is_for_sale": {"$exists": False}}  # Legacy tickets (never listed, show by default)
            ]
        }
        
        base_filter = {
            "$and": [
                {"token_id": {"$ne": None, "$exists": True}},
                base_sale_filter
            ]
        }
        
        # ✅ OPTIMIZATION: Use aggregation pipeline for all counts in parallel (much faster)
        pipeline = [
            {"$match": base_filter},
            {
                "$facet": {
                    "total": [{"$count": "count"}],
                    "on_chain": [
                        {"$match": {"is_on_chain": True}},
                        {"$count": "count"}
                    ],
                    "off_chain": [
                        {"$match": {"is_on_chain": False}},
                        {"$count": "count"}
                    ],
                    "crypto": [
                        {
                            "$match": {
                                "$and": [
                                    {
                                        "$or": [
                                            {"payment_method": "crypto", "creator_address": {"$ne": None, "$exists": True}},
                                            {"payment_method": {"$exists": False}, "creator_address": {"$ne": None, "$exists": True}}
                                        ]
                                    },
                                    {"payment_method": {"$ne": "paypal"}}
                                ]
                            }
                        },
                        {"$count": "count"}
                    ],
                    "paypal": [
                        {"$match": {"payment_method": "paypal"}},
                        {"$count": "count"}
                    ],
                    "psl": [
                        {"$match": {"is_psl_ticket": True}},
                        {"$count": "count"}
                    ]
                }
            }
        ]
        
        # Execute aggregation pipeline (single query instead of 5 separate queries)
        result = await artworks_collection.aggregate(pipeline).to_list(length=1)
        
        if result and len(result) > 0:
            facets = result[0]
            total_count = facets["total"][0]["count"] if facets["total"] else 0
            on_chain_count = facets["on_chain"][0]["count"] if facets["on_chain"] else 0
            off_chain_count = facets["off_chain"][0]["count"] if facets["off_chain"] else 0
            crypto_count = facets["crypto"][0]["count"] if facets["crypto"] else 0
            paypal_count = facets["paypal"][0]["count"] if facets["paypal"] else 0
            psl_count = facets["psl"][0]["count"] if facets["psl"] else 0
        else:
            # Fallback to individual counts if aggregation fails
            total_count = await artworks_collection.count_documents(base_filter)
            on_chain_count = await artworks_collection.count_documents({
                "$and": [base_filter, {"is_on_chain": True}]
            })
            off_chain_count = await artworks_collection.count_documents({
                "$and": [base_filter, {"is_on_chain": False}]
            })
            crypto_count = await artworks_collection.count_documents({
                "$and": [
                    base_filter,
                    {
                        "$or": [
                            {"payment_method": "crypto", "creator_address": {"$ne": None, "$exists": True}},
                            {"payment_method": {"$exists": False}, "creator_address": {"$ne": None, "$exists": True}}
                        ]
                    },
                    {"payment_method": {"$ne": "paypal"}}
                ]
            })
            paypal_count = await artworks_collection.count_documents({
                "$and": [base_filter, {"payment_method": "paypal"}]
            })
            psl_count = await artworks_collection.count_documents({
                "$and": [base_filter, {"is_psl_ticket": True}]
            })

        # PSL count now comes from tickets collection only.
        psl_count = await artworks_collection.count_documents({
            "$and": [base_filter, {"is_psl_ticket": True}]
        })
        
        counts = {
            "total": total_count,
            "on_chain": on_chain_count,  # NEW: Preferred field
            "off_chain": off_chain_count,  # NEW: Preferred field
            "crypto": crypto_count,  # OLD: Backward compatibility
            "paypal": paypal_count,  # OLD: Backward compatibility
            "psl": psl_count
        }
        
        # ✅ Cache the results
        set_cached_counts(counts)
        
        # ✅ Debug: Log counts for troubleshooting
        logger.info(f"📊 Ticket counts - Total: {total_count}, On-chain: {on_chain_count}, Off-chain: {off_chain_count}, Crypto (old): {crypto_count}, PayPal (old): {paypal_count}")
        
        # ✅ If there's a mismatch, log tickets that don't match either category
        if total_count != (on_chain_count + off_chain_count):
            logger.warning(f"⚠️ Count mismatch detected! Total ({total_count}) != On-chain ({on_chain_count}) + Off-chain ({off_chain_count}) = {on_chain_count + off_chain_count}")
        
        return counts
    except Exception as e:
        logger.error(f"Error getting ticket counts: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get ticket counts"
        )

# ✅ Enhanced Get single ticket
def get_artwork_cache(token_id: int) -> Optional[Dict]:
    """Get cached ticket details"""
    key = cache.cache_key("artwork_detail", token_id=token_id)
    return cache.get(key)

def set_artwork_cache(token_id: int, data: Dict, ttl: int = 300):
    """Cache ticket details"""
    key = cache.cache_key("artwork_detail", token_id=token_id)
    return cache.set(key, data, ttl)

def invalidate_artwork_cache(token_id: int):
    """Invalidate ticket cache when updated"""
    key = cache.cache_key("artwork_detail", token_id=token_id)
    return cache.delete(key)

# Line 2783 - Update the get_artwork endpoint:
@router.get("/{artwork_identifier}", response_model=ArtworkPublic)
async def get_artwork(artwork_identifier: str):
    try:
        # Get ticket info
        artwork_doc = await resolve_artwork_identifier(artwork_identifier)
        if not artwork_doc:
            raise HTTPException(status_code=404, detail="Ticket not found")
            
        token_id = artwork_doc.get("token_id")
        artwork_id = str(artwork_doc.get("_id"))

        # ✅ REDIS CACHE: Step 1 - Try to get from cache using artwork_id (string)
        cached_response = get_artwork_cache(artwork_id)
        if cached_response:
            logger.info(f"⚡ REDIS CACHE HIT - Returning cached ticket {artwork_id}")
            return ArtworkPublic(**cached_response)
        
        logger.info(f"💨 REDIS CACHE MISS - Fetching ticket {artwork_id} from database")
        
        users_collection = get_user_collection()
        artworks_collection = get_artwork_collection()
        blockchain_data = None
        
        # ✅ Use resolved ticket doc
        if artwork_doc:
            payment_method = artwork_doc.get("payment_method", "crypto")
            is_virtual_token = artwork_doc.get("is_virtual_token", False)
            network_name = (artwork_doc.get("network") or "").lower()
            is_algorand_artwork = network_name == "algorand"
            
            logger.info(f"✅ Found ticket {artwork_id} with payment_method: {payment_method}")
            
            # Only query EVM blockchain for EVM crypto tickets.
            if payment_method != "paypal" and not is_virtual_token and not is_algorand_artwork:
                try:
                    owner = await web3_service.get_artwork_owner(token_id)
                    artwork_info = await web3_service.get_artwork_info(token_id)
                    
                    if owner and artwork_info:
                        blockchain_data = {
                            "creator": artwork_info.get("creator"),
                            "owner": owner,
                            "metadata_uri": artwork_info.get("metadata_uri")
                        }
                        logger.info(f"✅ Retrieved blockchain data for token {token_id} to match correct ticket")
                except Exception as e:
                    logger.debug(f"Could not fetch blockchain data for token {token_id}: {e}")
            elif is_algorand_artwork:
                logger.info(f"ℹ️ Ticket {token_id} is on Algorand; skipping EVM contract lookup")
        else:
            raise HTTPException(status_code=404, detail="Ticket not found")
        
        # ✅ If we have blockchain data, try to match by creator_address and metadata_uri
        if blockchain_data:
            creator_address = blockchain_data.get("creator", "").lower() if blockchain_data.get("creator") else None
            metadata_uri = blockchain_data.get("metadata_uri")
            
            if creator_address or metadata_uri:
                query = {"token_id": token_id}
                if creator_address:
                    query["creator_address"] = {"$regex": f"^{creator_address}$", "$options": "i"}
                if metadata_uri:
                    query["metadata_uri"] = metadata_uri
                
                artwork_doc = await artworks_collection.find_one(query)
                if artwork_doc:
                    logger.info(f"✅ Matched ticket {token_id} using blockchain data")
                else:
                    # Fallback: try with just creator_address
                    if creator_address:
                        artwork_doc = await artworks_collection.find_one({
                            "token_id": token_id,
                            "creator_address": {"$regex": f"^{creator_address}$", "$options": "i"}
                        })
                    if not artwork_doc:
                        logger.warning(f"⚠️ Could not match ticket {token_id} with blockchain data, using most recent")
        else:
            artwork_doc = None
        
        # ✅ If no match found, get the most recent ticket with this token_id
        if not artwork_doc:
            artwork_doc = await artworks_collection.find_one(
                {"token_id": token_id},
                sort=[("created_at", -1)]  # Most recent first
            )
            if artwork_doc:
                logger.info(f"✅ Using most recent ticket for token {token_id}")
        
        if not artwork_doc:
            raise HTTPException(status_code=404, detail="Ticket not found")

        # UPDATED: Use validate_document to handle missing fields
        ticket = ArtworkInDB.validate_document(artwork_doc)
        artwork_public = ArtworkPublic.from_db_model(ticket)
        
        # ✅ Fetch creator and owner user information for PayPal tickets
        artwork_dict = artwork_public.model_dump()
        
        logger.info(f"📦 Ticket data from database for token {token_id}: token_id={artwork_dict.get('token_id')}, title={artwork_dict.get('title')}, price={artwork_dict.get('price')}, owner_address={artwork_dict.get('owner_address')}, owner_id={artwork_dict.get('owner_id')}, creator_address={artwork_dict.get('creator_address')}, creator_id={artwork_dict.get('creator_id')}, payment_method={artwork_dict.get('payment_method')}, is_for_sale={artwork_dict.get('is_for_sale')}")
        
        # Fetch creator user info
        if ticket.creator_id:
            creator_user = None
            creator_id_str = str(ticket.creator_id)
            
            # Try multiple lookup methods
            if ObjectId.is_valid(creator_id_str):
                creator_user = await users_collection.find_one({"_id": ObjectId(creator_id_str)})
            if not creator_user:
                creator_user = await users_collection.find_one({"_id": creator_id_str})
            if not creator_user:
                creator_user = await users_collection.find_one({"user_id": creator_id_str})
            
            if creator_user:
                artwork_dict["creator_name"] = creator_user.get('full_name') or creator_user.get('username') or "Unknown"
                artwork_dict["creator_email"] = creator_user.get('email') or None
                logger.info(f"✅ Found creator user info for token {token_id}: {artwork_dict.get('creator_name')}")
            else:
                logger.warning(f"⚠️ Creator user not found for creator_id: {creator_id_str}")
        
        # Fetch owner user info
        if ticket.owner_id:
            owner_user = None
            owner_id_str = str(ticket.owner_id)
            
            # Try multiple lookup methods
            if ObjectId.is_valid(owner_id_str):
                owner_user = await users_collection.find_one({"_id": ObjectId(owner_id_str)})
            if not owner_user:
                owner_user = await users_collection.find_one({"_id": owner_id_str})
            if not owner_user:
                owner_user = await users_collection.find_one({"user_id": owner_id_str})
            
            if owner_user:
                artwork_dict["owner_name"] = owner_user.get('full_name') or owner_user.get('username') or "Unknown"
                artwork_dict["owner_email"] = owner_user.get('email') or None
                logger.info(f"✅ Found owner user info for token {token_id}: {artwork_dict.get('owner_name')}")
            else:
                logger.warning(f"⚠️ Owner user not found for owner_id: {owner_id_str}")
        
        result = ArtworkPublic(**artwork_dict)
        
        # ✅ REDIS CACHE: Step 2 - Cache the response for 5 minutes (300 seconds)
        try:
            set_artwork_cache(token_id, result.model_dump(), ttl=300)
            logger.info(f"💾 Cached ticket {token_id} (TTL: 5 min)")
        except Exception as cache_error:
            # Don't fail if caching fails - just log it
            logger.warning(f"⚠️ Failed to cache ticket {token_id}: {cache_error}")
        
        logger.info(f"✅ Returning ticket data for token {token_id}")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting ticket {token_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get ticket")

# ✅ List and Delist endpoints (placed before generic {token_id} route to avoid conflicts)
from pydantic import BaseModel

class ListForSaleRequest(BaseModel):
    price: float

@router.post("/{artwork_identifier}/list-for-sale")
async def list_artwork_for_sale(
    artwork_identifier: str,
    request: ListForSaleRequest,
    current_user: dict = Depends(get_current_user)
):
    """List an owned ticket for resale"""
    try:
        from app.utils.ticket import resolve_artwork_identifier
        artworks_collection = get_artwork_collection()
        
        # 1. Verify Ownership
        ticket = await resolve_artwork_identifier(artwork_identifier)
        if not ticket:
            raise HTTPException(status_code=404, detail="Ticket not found")
            
        # ✅ Check wallet address match (handle None values)
        owner_address = ticket.get("owner_address") or ""
        user_wallet = current_user.get("wallet_address") or ""
        
        is_owner_wallet = (
            owner_address and user_wallet and
            str(owner_address).lower() == str(user_wallet).lower()
        )
        
        # ✅ Check user ID match (fallback for PayPal users)
        current_user_id = str(current_user.get("id") or current_user.get("_id") or "")
        artwork_owner_id = str(ticket.get("owner_id", ""))
        is_owner_id = artwork_owner_id and current_user_id and artwork_owner_id == current_user_id
        
        if not (is_owner_wallet or is_owner_id):
            logger.warning(f"❌ Ownership check failed - User: {current_user_id}, Ticket owner_id: {artwork_owner_id}, Ticket owner_address: {owner_address}, User wallet: {user_wallet}")
            raise HTTPException(status_code=403, detail="Only the owner can list this ticket")

        # ✅ NEW: Check if ticket is off-chain (PayPal) - if yes, require onboarding
        is_on_chain = ticket.get("is_on_chain")
        if is_on_chain is None:
            payment_met = ticket.get("payment_method", "crypto")
            is_virtual_token = ticket.get("is_virtual_token", False)
            is_on_chain = not (payment_met == "paypal" or is_virtual_token)
        
        if not is_on_chain:
            from bson import ObjectId
            db = get_db()
            sellers_collection = db.sellers
            users_collection = get_user_collection()
            
            owner_is_onboarded = False
            owner_merchant_id = None
            
            owner_seller = await sellers_collection.find_one(
                {
                    "user_id": current_user_id,
                    "onboarded": True,
                    "merchant_id": {"$ne": None, "$exists": True}
                },
                sort=[("updated_at", -1)]
            )
            
            if owner_seller:
                owner_merchant_id = owner_seller.get('merchant_id')
                owner_is_onboarded = True
            else:
                lookup_queries = []
                if ObjectId.is_valid(current_user_id):
                    lookup_queries.append({"_id": ObjectId(current_user_id)})
                lookup_queries.extend([{"_id": current_user_id}, {"user_id": current_user_id}, {"id": current_user_id}])
                
                for query in lookup_queries:
                    try:
                        owner_user = await users_collection.find_one(query)
                        if owner_user:
                            owner_merchant_id = owner_user.get('paypal_merchant_id')
                            owner_is_onboarded = owner_user.get('paypal_onboarded', False)
                            if owner_is_onboarded and owner_merchant_id:
                                break
                    except: continue
            
            if not owner_is_onboarded or not owner_merchant_id:
                raise HTTPException(
                    status_code=400,
                    detail="PayPal onboarding is required to list ticket for sale."
                )

        # 2. Update Database
        if request.price <= 0:
             raise HTTPException(status_code=400, detail="Price must be greater than 0")

        await artworks_collection.update_one(
            {"_id": ticket["_id"]},
            {
                "$set": {
                    "is_for_sale": True,
                    "price": request.price,
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        logger.info(f"Ticket {ticket.get('token_id', artwork_identifier)} listed for sale at {request.price} by {current_user_id}")
        
        try:
            invalidate_artworks_cache()
            if ticket.get("token_id") is not None:
                invalidate_artwork_cache(ticket["token_id"])
                invalidate_blockchain_cache(ticket["token_id"])
        except: pass

        return {"success": True, "message": "Ticket listed for sale successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list ticket: {e}")
        raise HTTPException(status_code=500, detail="Failed to list ticket")
        
# Add this endpoint to handle de-listing tickets
@router.post("/{artwork_identifier}/delist")
async def delist_artwork(
    artwork_identifier: str,
    current_user: dict = Depends(get_current_user)
):
    """Remove an ticket from sale"""
    try:
        from app.utils.ticket import resolve_artwork_identifier
        artworks_collection = get_artwork_collection()
        
        # 1. Verify Ownership
        ticket = await resolve_artwork_identifier(artwork_identifier)
        if not ticket:
            raise HTTPException(status_code=404, detail="Ticket not found")
            
        # ✅ Check wallet address match or user ID match
        owner_address = ticket.get("owner_address") or ""
        user_wallet = current_user.get("wallet_address") or ""
        
        is_owner_wallet = (
            owner_address and user_wallet and
            str(owner_address).lower() == str(user_wallet).lower()
        )
        
        current_user_id = str(current_user.get("id") or current_user.get("_id") or "")
        artwork_owner_id = str(ticket.get("owner_id", ""))
        is_owner_id = artwork_owner_id and current_user_id and artwork_owner_id == current_user_id
        
        if not (is_owner_wallet or is_owner_id):
            raise HTTPException(status_code=403, detail="Only the owner can de-list this ticket")

        # 2. Update Database
        await artworks_collection.update_one(
            {"_id": ticket["_id"]},
            {
                "$set": {
                    "is_for_sale": False,
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        logger.info(f"Ticket {ticket.get('token_id', artwork_identifier)} de-listed by {current_user_id}")
        
        try:
            invalidate_artworks_cache()
            if ticket.get("token_id") is not None:
                invalidate_artwork_cache(ticket["token_id"])
                invalidate_blockchain_cache(ticket["token_id"])
        except: pass
        
        return {"success": True, "message": "Ticket removed from sale"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delist ticket: {e}")
        raise HTTPException(status_code=500, detail="Failed to delist ticket")

from pydantic import BaseModel

class ListForSaleRequest(BaseModel):
    price: float

@router.post("/{artwork_identifier}/list-for-sale-legacy")
async def list_artwork_for_sale_redundant(
    artwork_identifier: str,
    request: ListForSaleRequest,
    current_user: dict = Depends(get_current_user)
):
    """List an owned ticket for resale (Redundant implementation)"""
    try:
        from app.utils.ticket import resolve_artwork_identifier
        artworks_collection = get_artwork_collection()
        
        # 1. Verify Ownership
        ticket = await resolve_artwork_identifier(artwork_identifier)
        if not ticket:
            raise HTTPException(status_code=404, detail="Ticket not found")
            
        # Check wallet address match
        is_owner_wallet = (
            ticket.get("owner_address", "").lower() == 
            current_user.get("wallet_address", "").lower()
        )
        
        # Check user ID match (fallback for PayPal users)
        current_user_id = str(current_user.get("id") or current_user.get("_id") or "")
        is_owner_id = str(ticket.get("owner_id", "")) == current_user_id
        
        if not (is_owner_wallet or is_owner_id):
            raise HTTPException(status_code=403, detail="Only the owner can list this ticket")

        # 2. Update Database
        if request.price <= 0:
             raise HTTPException(status_code=400, detail="Price must be greater than 0")

        await artworks_collection.update_one(
            {"_id": ticket["_id"]},
            {
                "$set": {
                    "is_for_sale": True,
                    "price": request.price,
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        logger.info(f"Ticket {ticket.get('token_id', artwork_identifier)} listed for sale by {current_user_id}")
        
        return {"success": True, "message": "Ticket listed for sale successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list ticket: {e}")
        raise HTTPException(status_code=500, detail="Failed to list ticket")
        
# Add this endpoint to handle de-listing tickets
@router.post("/{artwork_identifier}/delist-legacy")
async def delist_artwork_redundant(
    artwork_identifier: str,
    current_user: dict = Depends(get_current_user)
):
    """Remove an ticket from sale (Redundant implementation)"""
    try:
        from app.utils.ticket import resolve_artwork_identifier
        artworks_collection = get_artwork_collection()
        
        # 1. Verify Ownership
        ticket = await resolve_artwork_identifier(artwork_identifier)
        if not ticket:
            raise HTTPException(status_code=404, detail="Ticket not found")
            
        # Check wallet address match or user ID match
        is_owner_wallet = (
            ticket.get("owner_address", "").lower() == 
            current_user.get("wallet_address", "").lower()
        )
        current_user_id = str(current_user.get("id") or current_user.get("_id") or "")
        is_owner_id = str(ticket.get("owner_id", "")) == current_user_id
        
        if not (is_owner_wallet or is_owner_id):
            raise HTTPException(status_code=403, detail="Only the owner can de-list this ticket")

        # 2. Update Database
        await artworks_collection.update_one(
            {"_id": ticket["_id"]},
            {
                "$set": {
                    "is_for_sale": False,
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        logger.info(f"Ticket {ticket.get('token_id', artwork_identifier)} de-listed by {current_user_id}")
        
        return {"success": True, "message": "Ticket removed from sale"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delist ticket: {e}")
        raise HTTPException(status_code=500, detail="Failed to delist ticket")

@router.post("/classify-ai")
async def classify_image_ai(
    image: UploadFile = File(...),
    model: str = Form("gemini-2.5-flash"),
    current_user: dict = Depends(get_current_user)
):
    """AI classification endpoint is disabled for this deployment."""
    raise HTTPException(status_code=410, detail="AI detection is disabled for this deployment")
    
@router.post("/check-duplicates")
async def check_image_duplicates(
    image: UploadFile = File(...),
    current_user: dict = Depends(get_current_user)
):
    """Check if an image is a duplicate before upload with timeout handling"""
    try:
        if not image.filename:
            raise HTTPException(status_code=400, detail="No image file provided")
            
        image_data = await image.read()
        if len(image_data) == 0:
            raise HTTPException(status_code=400, detail="Empty image file")
            
        if len(image_data) > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Image file too large (max 10MB)")

        logger.info(f"Starting duplicate check for image: {image.filename}, size: {len(image_data)} bytes")
        
        import asyncio
        
        try:
            duplicate_result = await asyncio.wait_for(
                ImageProcessor.check_duplicates(image_data),
                timeout=30.0  # 30 seconds timeout for duplicate check
            )
        except asyncio.TimeoutError:
            logger.error("Duplicate check timed out after 30 seconds")
            return DuplicateCheckResult(
                is_duplicate=False,
                message="Duplicate check timed out - proceeding with caution"
            )
        
        logger.info(f"Duplicate check completed: {duplicate_result.is_duplicate}")
        return duplicate_result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Duplicate check failed: {str(e)}", exc_info=True)
        return DuplicateCheckResult(
            is_duplicate=False,
            message=f"Duplicate check failed: {str(e)[:100]}..."
        )

# Fix 3: Add similar timeout handling to duplicate check
@staticmethod
async def check_duplicates(image_data: bytes) -> DuplicateCheckResult:
    """Check for duplicate images using multiple methods"""
    try:
        artworks_collection = get_artwork_collection()
        
        # 1. Exact hash check
        file_hash = ImageProcessor.get_file_hash(image_data)
        logger.info(f"Checking for exact duplicates with hash: {file_hash[:10]}...")
        
        existing = await artworks_collection.find_one({"image_metadata.file_hash": file_hash})
        if existing:
            logger.warning(f"Exact duplicate found: ticket {existing.get('_id')}")
            return DuplicateCheckResult(
                is_duplicate=True,
                duplicate_type="exact",
                similarity_score=1.0,
                existing_artwork_id=str(existing["_id"]),
                message="Exact duplicate found"
            )

        # 2. Perceptual hash check - FIXED: Use consistent hash format
        perceptual_hash = ImageProcessor.get_perceptual_hash(image_data)
        logger.info(f"Checking for perceptual duplicates with hash: {perceptual_hash[:10]}...")
        
        # Get all tickets with perceptual hashes
        cursor = artworks_collection.find({
            "image_metadata.perceptual_hash": {"$exists": True, "$ne": None}
        })
        
        # FIXED: Convert to list to avoid cursor issues
        existing_artworks = await cursor.to_list(length=1000)  # Limit for performance
        
        for doc in existing_artworks:
            if "image_metadata" in doc and "perceptual_hash" in doc["image_metadata"]:
                try:
                    stored_phash_str = doc["image_metadata"]["perceptual_hash"]
                    
                    # FIXED: Handle both string and hash object formats
                    if isinstance(stored_phash_str, str) and len(stored_phash_str) == len(perceptual_hash):
                        current_phash = imagehash.hex_to_hash(perceptual_hash)
                        stored_phash = imagehash.hex_to_hash(stored_phash_str)
                        distance = current_phash - stored_phash
                        
                        # FIXED: More lenient threshold for better detection
                        if distance <= 8:  # Increased from 5 to 8
                            logger.warning(f"Perceptual duplicate found: ticket {doc.get('_id')}, distance: {distance}")
                            return DuplicateCheckResult(
                                is_duplicate=True,
                                duplicate_type="perceptual",
                                similarity_score=1.0 - (distance / 64.0),
                                existing_artwork_id=str(doc["_id"]),
                                message=f"Perceptually similar image found (distance: {distance})"
                            )
                except Exception as e:
                    logger.warning(f"Error comparing perceptual hash: {e}")
                    continue

        logger.info("AI embedding duplicate check is disabled")

        logger.info("No duplicates found")
        return DuplicateCheckResult(
            is_duplicate=False,
            message="No duplicates found"
        )

    except Exception as e:
        logger.error(f"Duplicate check failed: {str(e)}", exc_info=True)
        # FIXED: Don't fail silently - return error but allow upload
        return DuplicateCheckResult(
            is_duplicate=False,
            message=f"Duplicate check failed: {str(e)} - Upload allowed with warning"
        )
    
@router.post("/{artwork_identifier}/view")
async def track_artwork_view(
    artwork_identifier: str,
    current_user: dict = Depends(get_current_user_optional)
):
    """Track when a user views an ticket details page"""
    try:
        ticket = await resolve_artwork_identifier(artwork_identifier)
        if not ticket:
            raise HTTPException(status_code=404, detail="Ticket not found")
        
        # Log view action
        user_id = str(current_user.get('id') or current_user.get('_id') or 'anonymous')
        artwork_id = str(ticket.get('_id'))
        
        await UserHistoryService.log_user_action(
            user_id=user_id,
            action="view",
            artwork_id=artwork_id,
            artwork_token_id=ticket.get("token_id"),
            metadata={
                "view_timestamp": datetime.utcnow().isoformat(),
                "artwork_title": ticket.get("title")
            }
        )
        
        return {"success": True, "message": "View tracked"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to track ticket view: {str(e)}")
        # Don't raise error for tracking failures
        return {"success": False, "message": "View tracking failed"}

def get_blockchain_cache(artwork_identifier: Any) -> Optional[Dict]:
    """Get cached blockchain info"""
    key = cache.cache_key("artwork_blockchain", identifier=str(artwork_identifier))
    return cache.get(key)

def set_blockchain_cache(artwork_identifier: Any, data: Dict, ttl: int = 180):
    """Cache blockchain info (shorter TTL since it changes more frequently)"""
    key = cache.cache_key("artwork_blockchain", identifier=str(artwork_identifier))
    return cache.set(key, data, ttl)

def invalidate_blockchain_cache(artwork_identifier: Any):
    """Invalidate blockchain cache when updated"""
    key = cache.cache_key("artwork_blockchain", identifier=str(artwork_identifier))
    return cache.delete(key)

# Line 3410 - Update the get_artwork_blockchain_info endpoint:
@router.get("/{artwork_identifier}/blockchain", response_model=dict)
async def get_artwork_blockchain_info(artwork_identifier: str):
    """Get blockchain info with graceful fallbacks"""
    try:
        # ✅ REDIS CACHE: Step 1 - Try to get from cache first
        cached_response = get_blockchain_cache(artwork_identifier)
        if cached_response:
            logger.info(f"⚡ REDIS CACHE HIT - Returning cached blockchain info for {artwork_identifier}")
            return cached_response
        
        logger.info(f"💨 REDIS CACHE MISS - Fetching blockchain info for {artwork_identifier}")
        
        # Resolve ticket from database
        artwork_doc = await resolve_artwork_identifier(artwork_identifier)
        
        if not artwork_doc:
            logger.warning(f"Ticket {artwork_identifier} not found in database")
            raise HTTPException(status_code=404, detail="Ticket not found in database")
            
        token_id = artwork_doc.get("token_id")
        artwork_id = str(artwork_doc.get("_id"))

        # ✅ CHECK: If ticket is PayPal-registered, skip blockchain queries
        payment_method = artwork_doc.get("payment_method", "crypto")
        is_virtual_token = artwork_doc.get("is_virtual_token", False)
        
        network_name = (artwork_doc.get("network") or "").lower()
        is_algorand_artwork = network_name == "algorand"

        if payment_method == "paypal" or is_virtual_token:
            logger.info(f"✅ Ticket {token_id} is PayPal-registered (virtual token), returning database data only")
            # For PayPal tickets, return database data directly (no blockchain)
            response_data = {
                "token_id": token_id,
                "creator": artwork_doc.get("creator_address") or artwork_doc.get("creator_id", "Unknown"),
                "owner": artwork_doc.get("owner_address") or artwork_doc.get("owner_id", "Unknown"),
                "metadata_uri": artwork_doc.get("metadata_uri", ""),
                "royalty_percentage": artwork_doc.get("royalty_percentage", 0),
                "is_licensed": artwork_doc.get("is_licensed", False),
                "blockchain_status": "not_applicable",  # ✅ PayPal tickets don't use blockchain
                "source": "database",
                "payment_method": "paypal",
                "is_virtual_token": True
            }
            
            # ✅ REDIS CACHE: Cache PayPal ticket response (longer TTL since it doesn't change)
            try:
                set_blockchain_cache(artwork_identifier, response_data, ttl=600)  # 10 minutes for PayPal
                logger.info(f"💾 Cached blockchain info for PayPal ticket {artwork_identifier} (TTL: 10 min)")
            except Exception as cache_error:
                logger.warning(f"⚠️ Failed to cache blockchain info: {cache_error}")
            
            return response_data

        if is_algorand_artwork:
            logger.info(f"✅ Ticket {token_id} is Algorand-registered, fetching live Algorand chain data")

            asa_id = artwork_doc.get("algorand_asa_id") or token_id
            db_creator = artwork_doc.get("creator_algorand_address") or artwork_doc.get("creator_address") or "Unknown"
            db_owner = artwork_doc.get("owner_algorand_address") or artwork_doc.get("owner_address") or "Unknown"
            db_metadata_uri = artwork_doc.get("metadata_uri", "")

            chain_info = None
            chain_error = None
            try:
                from services.algorand_service import algorand_service
                chain_info = await algorand_service.get_asset_blockchain_info(asa_id)
                if not chain_info.get("success"):
                    chain_error = chain_info.get("error")
            except Exception as e:
                chain_error = str(e)
                logger.warning(f"⚠️ Failed to fetch live Algorand data for ASA {asa_id}: {e}")

            creator_value = chain_info.get("creator") if chain_info and chain_info.get("success") else None
            owner_value = chain_info.get("owner") if chain_info and chain_info.get("success") else None
            metadata_value = chain_info.get("metadata_uri") if chain_info and chain_info.get("success") else None

            response_data = {
                "token_id": token_id,
                "creator": creator_value or db_creator,
                "owner": owner_value or db_owner,
                "metadata_uri": metadata_value or db_metadata_uri,
                "royalty_percentage": artwork_doc.get("royalty_percentage", 0),
                "is_licensed": artwork_doc.get("is_licensed", False),
                "blockchain_status": "algorand",
                "source": "algorand_blockchain" if chain_info and chain_info.get("success") else "database",
                "network": "algorand",
                "algorand_asa_id": asa_id,
            }

            if chain_error:
                response_data["chain_warning"] = chain_error

            try:
                set_blockchain_cache(artwork_identifier, response_data, ttl=300)
                logger.info(f"💾 Cached blockchain info for Algorand ticket {artwork_identifier} (TTL: 5 min)")
            except Exception as cache_error:
                logger.warning(f"⚠️ Failed to cache blockchain info: {cache_error}")

            return response_data

        # ✅ Only query blockchain for crypto tickets
        logger.info(f"Ticket {token_id} is crypto-registered, querying blockchain...")

        # Try to get blockchain data with fallbacks
        artwork_info = None
        owner = None
        
        # Get owner first (this seems to work)
        try:
            owner = await web3_service.get_artwork_owner(token_id)
        except Exception as e:
            logger.warning(f"Failed to get owner for {token_id}: {e}")
        
        # Try to get ticket info (this is failing)
        try:
            artwork_info = await web3_service.get_artwork_info(token_id)
        except Exception as e:
            logger.warning(f"Failed to get ticket info for {token_id}: {e}")
        
        # If both calls failed, check if we have cached data in database
        if not artwork_info and not owner:
            logger.warning(f"All blockchain calls failed for token {token_id}")
            
            # Return database data as fallback
            response_data = {
                "token_id": token_id,
                "creator": artwork_doc.get("creator_address", "Unknown"),
                "owner": artwork_doc.get("owner_address", "Unknown"),
                "metadata_uri": artwork_doc.get("metadata_uri", ""),
                "royalty_percentage": artwork_doc.get("royalty_percentage", 0),
                "is_licensed": artwork_doc.get("is_licensed", False),
                "blockchain_status": "unavailable",
                "source": "database_fallback"
            }
            
            # ✅ REDIS CACHE: Cache fallback response (shorter TTL)
            try:
                set_blockchain_cache(artwork_identifier, response_data, ttl=60)  # 1 minute for fallback
                logger.info(f"💾 Cached fallback blockchain info for {artwork_identifier} (TTL: 1 min)")
            except Exception as cache_error:
                logger.warning(f"⚠️ Failed to cache blockchain info: {cache_error}")
            
            return response_data
        
        # If we have partial data, merge with database data
        creator = artwork_info.get("creator") if artwork_info else artwork_doc.get("creator_address", "Unknown")
        metadata_uri = artwork_info.get("metadata_uri") if artwork_info else artwork_doc.get("metadata_uri", "")
        royalty_percentage = artwork_info.get("royalty_percentage") if artwork_info else artwork_doc.get("royalty_percentage", 0)
        is_licensed = artwork_info.get("is_licensed") if artwork_info else artwork_doc.get("is_licensed", False)
        
        # Use the owner from blockchain if available, otherwise from database
        final_owner = owner if owner else artwork_doc.get("owner_address", "Unknown")
        
        response_data = {
            "token_id": token_id,
            "creator": creator,
            "owner": final_owner,
            "metadata_uri": metadata_uri,
            "royalty_percentage": royalty_percentage,
            "is_licensed": is_licensed,
            "blockchain_status": "partial" if not artwork_info or not owner else "full",
            "source": "mixed" if not artwork_info or not owner else "blockchain"
        }
        
        # ✅ REDIS CACHE: Step 2 - Cache the response for 3 minutes (180 seconds)
        try:
            set_blockchain_cache(artwork_identifier, response_data, ttl=180)
            logger.info(f"💾 Cached blockchain info for {artwork_identifier} (TTL: 3 min)")
        except Exception as cache_error:
            logger.warning(f"⚠️ Failed to cache blockchain info: {cache_error}")
        
        logger.info(f"Returning blockchain info for token {token_id}: {response_data}")
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting blockchain info for ticket {token_id}: {e}", exc_info=True)
        
        # Ultimate fallback - return minimal data
        return {
            "token_id": token_id,
            "creator": "Unknown",
            "owner": "Unknown",
            "metadata_uri": "",
            "royalty_percentage": 0,
            "is_licensed": False,
            "blockchain_status": "error",
            "source": "error_fallback"
        }

@router.put("/{artwork_identifier}")
async def update_artwork(
    artwork_identifier: str,
    artwork_update: ArtworkUpdate,
    current_user: dict = Depends(get_current_user)
):
    try:
        artwork_doc = await resolve_artwork_identifier(artwork_identifier)
        if not artwork_doc:
            raise HTTPException(status_code=404, detail="Ticket not found")
        
        token_id = artwork_doc.get("token_id")
        artwork_id = str(artwork_doc.get("_id"))
        artworks_collection = get_artwork_collection()

        # ✅ Validate and sanitize document (handles ObjectId to string conversion)
        ArtworkInDB.validate_document(artwork_doc)
        
        ticket = ArtworkInDB.model_validate(artwork_doc)
        
        # ✅ Broaden ownership check to support both crypto (wallet) and PayPal (owner_id)
        user_id = str(current_user.get('user_id') or current_user.get('id') or "")
        wallet_address = current_user.get('wallet_address', '').lower()
        
        artwork_owner_id = str(ticket.owner_id) if ticket.owner_id else ""
        artwork_owner_address = ticket.owner_address.lower() if ticket.owner_address else ""
        
        is_owner = (
            (artwork_owner_address and artwork_owner_address == wallet_address) or
            (artwork_owner_id and artwork_owner_id == user_id)
        )
        
        if not is_owner:
            logger.warning(f"🚫 Ownership mismatch for ticket {artwork_identifier}: ticket(addr={artwork_owner_address}, id={artwork_owner_id}) vs user(addr={wallet_address}, id={user_id})")
            raise HTTPException(status_code=403, detail="Only owner can update ticket settings")

        update_data = artwork_update.model_dump(exclude_unset=True)
        update_data["updated_at"] = datetime.utcnow()

        # ✅ CRITICAL EXCLUSIVITY CHECK: Block listing for sale if an EXCLUSIVE license exists
        if update_data.get("is_for_sale") is True:
            db = get_db()
            licenses_collection = db.licenses
            exclusive_license = await licenses_collection.find_one({
                "$or": [{"token_id": token_id}, {"artwork_id": artwork_id}],
                "license_type": {"$in": ["EXCLUSIVE", "ARTWORK_OWNERSHIP"]},
                "status": {"$in": ["CONFIRMED", "PENDING"]},
                "is_active": True
            })
            if exclusive_license:
                logger.warning(f"🚫 Blocked relisting of ticket {token_id}: Active EXCLUSIVE license exists.")
                raise HTTPException(
                    status_code=400, 
                    detail="Cannot list for sale: This ticket is already exclusively licensed to a buyer."
                )

        # ✅ PSL TICKET CHECK: Block resale for non-creators (Hackathon Demo restriction)
        if update_data.get("is_for_sale") is True and ticket.is_psl_ticket:
            artwork_creator_id = str(ticket.creator_id) if ticket.creator_id else ""
            artwork_creator_address = ticket.creator_address.lower() if ticket.creator_address else ""
            
            is_creator = (
                (artwork_creator_address and artwork_creator_address == wallet_address) or
                (artwork_creator_id and artwork_creator_id == user_id)
            )
            
            if not is_creator:
                 logger.warning(f"🚫 Blocked resale of PSL ticket {token_id} by non-creator user {user_id}")
                 raise HTTPException(
                     status_code=400, 
                     detail="PSL Smart-Tickets cannot be resold. Only the original creator can list them for sale."
                 )

        await artworks_collection.update_one({"_id": ObjectId(artwork_id)}, {"$set": update_data})
        updated_doc = await artworks_collection.find_one({"_id": ObjectId(artwork_id)})
        # ✅ Validate and sanitize updated document
        ArtworkInDB.validate_document(updated_doc)
        
        updated_artwork = ArtworkInDB.model_validate(updated_doc)
        
        # ✅ REDIS CACHE: Invalidate ticket cache after update
        try:
            invalidate_artworks_cache()
            invalidate_artwork_cache(artwork_identifier)
            invalidate_blockchain_cache(artwork_identifier)
            logger.info("🗑️ Ticket cache invalidated after update")
        except Exception as cache_error:
            logger.warning(f"⚠️ Failed to invalidate cache: {cache_error}")
        
        return ArtworkPublic.from_db_model(updated_artwork)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating ticket {token_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update ticket")


# --- Test Contract Endpoint ---
@router.post("/test-contract", response_model=ContractCallResponse)
async def test_contract(request: ContractCallRequest):
    try:
        # ✅ Simulate contract call (replace with real Web3 logic later)
        result = {
            "function": request.function_name,
            "params": request.parameters,
            "from": request.from_address,
            "value": request.value
        }

        return ContractCallResponse(
            success=True,
            result=result,
            tx_hash="0x" + "abc123".ljust(64, "0")  # dummy tx hash
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/owner/{owner_identifier}", response_model=ArtworkListResponse)
async def get_artworks_by_owner(
    owner_identifier: str,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100)
):
    """
    Get tickets by owner - supports both user ID and wallet address
    ⚡ OPTIMIZED: Batch user lookups, exact match queries, database indexes
    """
    try:
        artworks_collection = get_artwork_collection()
        users_collection = get_user_collection()

        # ⚡ OPTIMIZED: Determine if identifier is a wallet address or user ID
        is_wallet_address = (
            owner_identifier.startswith('0x') and 
            len(owner_identifier) == 42
        )

        filter_query = {}
        
        if is_wallet_address:
            # ⚡ OPTIMIZED: Use exact match instead of regex for better index usage
            filter_query = {
                "owner_address": owner_identifier.lower(),  # Exact match, case-insensitive storage
                "token_id": {"$ne": None, "$exists": True}
            }
            logger.info(f"Searching by wallet address: {owner_identifier}")
        else:
            # ⚡ OPTIMIZED: Simplified query structure for better index usage
            filter_query = {
                "$and": [
                    {
                        "$or": [
                            {"owner_id": owner_identifier},  # Exact match for user ID
                            {"owner_address": owner_identifier.lower()}  # Exact match for wallet (fallback)
                        ]
                    },
                    {"token_id": {"$ne": None, "$exists": True}}
                ]
            }
        logger.info(f"Searching by owner_id (PayPal) OR owner_address (crypto): {owner_identifier}")

        # ⚡ OPTIMIZED: Get total count and tickets in parallel
        total_task = artworks_collection.count_documents(filter_query)
        
        skip = (page - 1) * size
        artworks_task = artworks_collection.find(
            filter_query
        ).skip(skip).limit(size).sort("created_at", -1).to_list(length=size)
        
        # Execute both queries in parallel
        total, artworks_data = await asyncio.gather(total_task, artworks_task)
        
        has_next = (page * size) < total

        # ⚡ OPTIMIZED: Deduplicate using set (faster than list iteration)
        seen_ids = set()
        unique_artworks_data = []
        for doc in artworks_data:
            doc_id = str(doc.get("_id"))
            if doc_id not in seen_ids:
                seen_ids.add(doc_id)
                unique_artworks_data.append(doc)
        
        if len(artworks_data) != len(unique_artworks_data):
            logger.info(f"✅ Deduplicated tickets: {len(artworks_data)} -> {len(unique_artworks_data)}")

        # ⚡ OPTIMIZED: Collect all unique creator_id and owner_id for batch lookup
        creator_ids = set()
        owner_ids = set()
        valid_artworks = []
        
        for doc in unique_artworks_data:
            if not doc.get("token_id") or doc.get("token_id") is None:
                continue
            
            try:
                db_model = ArtworkInDB.validate_document(doc)
                if db_model.creator_id:
                    creator_ids.add(str(db_model.creator_id))
                if db_model.owner_id:
                    owner_ids.add(str(db_model.owner_id))
                valid_artworks.append((doc, db_model))
            except Exception as e:
                logger.warning(f"Skipping invalid ticket document: {e}")
                continue

        # ⚡ OPTIMIZED: Batch fetch all users at once (fixes N+1 problem)
        user_cache = {}
        all_user_ids = creator_ids | owner_ids
        
        if all_user_ids:
            # Build ObjectId queries
            object_id_queries = []
            string_id_queries = []
            
            for user_id in all_user_ids:
                if ObjectId.is_valid(user_id):
                    object_id_queries.append(ObjectId(user_id))
                else:
                    string_id_queries.append(user_id)
            
            # Batch fetch by ObjectId _id
            if object_id_queries:
                object_id_cursor = users_collection.find({"_id": {"$in": object_id_queries}})
                async for user in object_id_cursor:
                    user_cache[str(user["_id"])] = user
            
            # Batch fetch by string _id for remaining IDs
            remaining_by_string = set(string_id_queries) - set(user_cache.keys())
            if remaining_by_string:
                string_cursor = users_collection.find({"_id": {"$in": list(remaining_by_string)}})
                async for user in string_cursor:
                    user_cache[str(user["_id"])] = user
            
            # Batch fetch by user_id field for any still missing
            still_missing = all_user_ids - set(user_cache.keys())
            if still_missing:
                user_id_cursor = users_collection.find({"user_id": {"$in": list(still_missing)}})
                async for user in user_id_cursor:
                    if user.get("user_id"):
                        user_cache[user["user_id"]] = user

        # ⚡ OPTIMIZED: Build tickets list using cached user data
        tickets = []
        for doc, db_model in valid_artworks:
            try:
                artwork_public = ArtworkPublic.from_db_model(db_model)
                artwork_dict = artwork_public.model_dump()
                
                # Get user data from cache (no additional queries)
                if db_model.creator_id:
                    creator_user = user_cache.get(str(db_model.creator_id))
                    if creator_user:
                        artwork_dict["creator_name"] = creator_user.get('full_name') or creator_user.get('username') or "Unknown"
                        artwork_dict["creator_email"] = creator_user.get('email') or None
                
                if db_model.owner_id:
                    owner_user = user_cache.get(str(db_model.owner_id))
                    if owner_user:
                        artwork_dict["owner_name"] = owner_user.get('full_name') or owner_user.get('username') or "Unknown"
                        artwork_dict["owner_email"] = owner_user.get('email') or None
                
                tickets.append(ArtworkPublic(**artwork_dict))
            except Exception as e:
                logger.warning(f"Skipping invalid ticket document: {e}")
                continue

        return ArtworkListResponse(
            tickets=tickets,
            total=total,
            page=page,
            size=size,
            has_next=has_next
        )
    except Exception as e:
        logger.error(f"Error getting tickets by owner {owner_identifier}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get tickets")


@router.get("/creator/{creator_identifier}", response_model=ArtworkListResponse)
async def get_artworks_by_creator(
    creator_identifier: str,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100)
):
    """
    Get tickets by creator - supports both user ID and wallet address
    """
    try:
        artworks_collection = get_artwork_collection()
        users_collection = get_user_collection()

        # Determine if identifier is a wallet address or user ID
        is_wallet_address = (
            creator_identifier.startswith('0x') and 
            len(creator_identifier) == 42
        )

        filter_query = {}
        
        if is_wallet_address:
            # Search by wallet address (crypto users)
            filter_query = {
                "creator_address": {
                    "$regex": f"^{re.escape(creator_identifier.lower())}$",
                    "$options": "i"
                }
            }
            logger.info(f"Searching creator by wallet address: {creator_identifier}")
        else:
            # Search by user ID (PayPal users or internal lookup)
            # ✅ Try multiple lookup methods for user (similar to license endpoints)
            user = None
            if ObjectId.is_valid(creator_identifier):
                user = await users_collection.find_one({"_id": ObjectId(creator_identifier)})
            if not user:
                user = await users_collection.find_one({"user_id": creator_identifier})
            if not user:
                user = await users_collection.find_one({"_id": creator_identifier})
            if not user:
                user = await users_collection.find_one({"id": creator_identifier})
            
            if user:
                # ✅ Get all possible user ID formats that might be stored as creator_id
                possible_creator_ids = set()
                if user.get('user_id'):
                    possible_creator_ids.add(str(user.get('user_id')))
                if user.get('id'):
                    possible_creator_ids.add(str(user.get('id')))
                if user.get('_id'):
                    possible_creator_ids.add(str(user.get('_id')))
                possible_creator_ids.add(creator_identifier)
                
                # ✅ Search with all possible creator_id formats
                creator_id_conditions = [{"creator_id": cid} for cid in possible_creator_ids]
                
                # Also include wallet address if user has one (for crypto tickets)
                wallet_address = user.get('wallet_address')
                if wallet_address:
                    creator_id_conditions.append({
                        "creator_address": {
                            "$regex": f"^{re.escape(wallet_address.lower())}$",
                            "$options": "i"
                        }
                    })
                
                if len(creator_id_conditions) > 1:
                    filter_query = {"$or": creator_id_conditions}
                else:
                    filter_query = creator_id_conditions[0]
                
                logger.info(f"Searching creator by user ID: {creator_identifier}, possible IDs: {possible_creator_ids}")
            else:
                # Try as wallet address anyway
                filter_query = {
                    "creator_address": {
                        "$regex": f"^{re.escape(creator_identifier.lower())}$",
                        "$options": "i"
                    }
                }
                logger.info(f"Creator user not found, searching as wallet address: {creator_identifier}")

        total = await artworks_collection.count_documents(filter_query)
        has_next = (page * size) < total
        skip = (page - 1) * size

        cursor = artworks_collection.find(filter_query).skip(skip).limit(size).sort("created_at", -1)
        artworks_data = await cursor.to_list(length=size)

        tickets = []
        for doc in artworks_data:
            try:
                db_model = ArtworkInDB.validate_document(doc)
                tickets.append(ArtworkPublic.from_db_model(db_model))
            except Exception as e:
                logger.warning(f"Skipping invalid ticket document: {e}")
                continue

        return ArtworkListResponse(
            tickets=tickets,
            total=total,
            page=page,
            size=size,
            has_next=has_next
        )
    except Exception as e:
        logger.error(f"Error getting tickets by creator {creator_identifier}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get tickets")
    
def is_valid_wallet_address(address: str) -> bool:
    """Check if a string is a valid Ethereum wallet address"""
    if not address.startswith('0x') or len(address) != 42:
        return False
    try:
        # Check if all characters after 0x are valid hex
        return all(c in '0123456789abcdefABCDEF' for c in address[2:])
    except:
        return False


def _normalize_royalty_basis_points(raw_value: Any) -> int:
    """Normalize royalty config to basis points (0..10000)."""
    if raw_value is None:
        return 0

    try:
        value = float(raw_value)
    except Exception:
        return 0

    if value <= 0:
        return 0

    # Accept fractional (0.1), percentage (10), or basis points (1000).
    if value <= 1:
        basis_points = int(round(value * 10000))
    elif value <= 100:
        basis_points = int(round(value * 100))
    else:
        basis_points = int(round(value))

    return max(0, min(10000, basis_points))


def _merge_algorand_payment_legs(payment_legs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge legs with the same receiver so frontend signs fewer payment txns."""
    merged: Dict[str, Dict[str, Any]] = {}

    for leg in payment_legs:
        receiver = (leg.get("to") or "").strip()
        amount = int(leg.get("amount") or 0)
        purpose = (leg.get("purpose") or "payment").strip()

        if not receiver or amount <= 0:
            continue

        if receiver not in merged:
            merged[receiver] = {
                "to": receiver,
                "amount": amount,
                "purposes": [purpose],
            }
            continue

        merged[receiver]["amount"] += amount
        if purpose and purpose not in merged[receiver]["purposes"]:
            merged[receiver]["purposes"].append(purpose)

    return [
        {
            "to": receiver,
            "amount": data["amount"],
            "purpose": "+".join(data["purposes"]),
        }
        for receiver, data in merged.items()
    ]


def _extract_group_id_from_indexer_tx(indexer_tx: Dict[str, Any]) -> Optional[str]:
    """Return Algorand group id string from indexer transaction payload if available."""
    group_id = indexer_tx.get("group")
    if isinstance(group_id, str) and group_id.strip():
        return group_id.strip()

    nested = (((indexer_tx.get("txn") or {}).get("txn") or {}).get("grp"))
    if isinstance(nested, str) and nested.strip():
        return nested.strip()

    return None


def _to_indexer_group_id_bytes(group_id: Optional[str]) -> Optional[bytes]:
    """Convert indexer group id text to raw bytes expected by algosdk indexer client."""
    if not group_id:
        return None

    candidate = group_id.strip()
    if not candidate:
        return None

    try:
        return base64.b64decode(candidate, validate=True)
    except Exception:
        # Some payloads may omit padding; retry with normalized padding.
        try:
            padded = candidate + ("=" * (-len(candidate) % 4))
            return base64.b64decode(padded)
        except Exception:
            logger.warning("⚠️ Could not decode Algorand group id '%s' to bytes", candidate)
            return None


async def _verify_algorand_registration_fee_payment(
    tx_hash: str,
    payer_address: str,
    platform_address: str,
    expected_amount_microalgos: int,
    algorand_service,
) -> Dict[str, Any]:
    """Ensure Algorand registration group includes exact platform fee payment."""
    expected_amount = int(expected_amount_microalgos or 0)
    if expected_amount <= 0:
        return {"success": True, "actual_amount_microalgos": 0, "expected_amount_microalgos": 0}

    payer_normalized = (payer_address or "").strip().lower()
    platform_normalized = (platform_address or "").strip().lower()

    search_resp = algorand_service.indexer_client.search_transactions(txid=tx_hash, limit=1)
    txns = search_resp.get("transactions", []) if isinstance(search_resp, dict) else []
    if not txns:
        raise HTTPException(status_code=400, detail="Algorand registration transaction not found in indexer")

    anchor_tx = txns[0]
    confirmed_round = int(anchor_tx.get("confirmed-round") or 0)
    if confirmed_round <= 0:
        raise HTTPException(status_code=400, detail="Algorand registration transaction is not confirmed yet")

    group_id = _extract_group_id_from_indexer_tx(anchor_tx)
    group_id_bytes = _to_indexer_group_id_bytes(group_id)
    grouped_transactions = [anchor_tx]

    if group_id_bytes:
        grouped_resp = algorand_service.indexer_client.search_transactions(
            group_id=group_id_bytes,
            min_round=confirmed_round,
            max_round=confirmed_round,
            limit=50,
        )
        grouped_transactions = grouped_resp.get("transactions", []) if isinstance(grouped_resp, dict) else [anchor_tx]

    actual_amount = 0
    for txn in grouped_transactions:
        if txn.get("tx-type") != "pay":
            continue

        sender = (txn.get("sender") or "").strip().lower()
        if sender != payer_normalized:
            continue

        payment_txn = txn.get("payment-transaction", {}) if isinstance(txn, dict) else {}
        receiver = (payment_txn.get("receiver") or "").strip().lower()
        if receiver != platform_normalized:
            continue

        actual_amount += int(payment_txn.get("amount") or 0)

    if actual_amount != expected_amount:
        raise HTTPException(
            status_code=400,
            detail=(
                "Algorand registration fee payment verification failed: "
                f"expected {expected_amount} microalgos to platform, got {actual_amount} microalgos"
            ),
        )

    return {
        "success": True,
        "group_id": group_id,
        "expected_amount_microalgos": expected_amount,
        "actual_amount_microalgos": actual_amount,
    }


async def _build_algorand_sale_breakdown(
    artwork_doc: Dict[str, Any],
    sale_price_microalgos: int,
    seller_address: str,
    platform_address: str,
) -> Dict[str, Any]:
    """Compute Algorand sale economics with buyer/seller platform fees and optional royalty."""
    from algosdk import encoding as algo_encoding

    sale_price_microalgos = int(sale_price_microalgos)
    if sale_price_microalgos <= 0:
        raise HTTPException(status_code=400, detail="Sale amount must be greater than zero")

    seller_address = (seller_address or "").strip()
    if not seller_address or not algo_encoding.is_valid_address(seller_address):
        raise HTTPException(status_code=400, detail="Invalid Algorand seller address")

    platform_fee_percentage = await get_current_global_fee()
    platform_fee_basis = max(0, int(round(float(platform_fee_percentage) * 100)))

    buyer_platform_fee_microalgos = (sale_price_microalgos * platform_fee_basis) // 10000
    seller_platform_fee_microalgos = (sale_price_microalgos * platform_fee_basis) // 10000

    creator_address = (
        artwork_doc.get("creator_algorand_address")
        or artwork_doc.get("creator_address")
        or ""
    ).strip()

    if creator_address and not algo_encoding.is_valid_address(creator_address):
        creator_address = ""

    is_primary_sale = bool(creator_address and creator_address.lower() == seller_address.lower())
    royalty_basis = _normalize_royalty_basis_points(artwork_doc.get("royalty_percentage", 0))
    royalty_microalgos = 0 if is_primary_sale else (sale_price_microalgos * royalty_basis) // 10000

    if royalty_microalgos > 0 and not creator_address:
        raise HTTPException(
            status_code=400,
            detail="Royalty is configured but creator Algorand address is missing or invalid",
        )

    seller_receives_microalgos = (
        sale_price_microalgos - seller_platform_fee_microalgos - royalty_microalgos
    )
    if seller_receives_microalgos <= 0:
        raise HTTPException(
            status_code=400,
            detail="Sale split is invalid: seller net amount must be greater than zero",
        )

    platform_receives_microalgos = buyer_platform_fee_microalgos + seller_platform_fee_microalgos
    platform_address = (platform_address or "").strip()
    if platform_receives_microalgos > 0:
        if not platform_address or not algo_encoding.is_valid_address(platform_address):
            raise HTTPException(
                status_code=500,
                detail="ALGORAND_PLATFORM_ADDRESS is missing or invalid while platform fee is enabled",
            )

    payment_legs: List[Dict[str, Any]] = [
        {
            "to": seller_address,
            "amount": seller_receives_microalgos,
            "purpose": "seller_net",
        }
    ]

    if platform_receives_microalgos > 0:
        payment_legs.append(
            {
                "to": platform_address,
                "amount": platform_receives_microalgos,
                "purpose": "platform_fee",
            }
        )

    if royalty_microalgos > 0:
        payment_legs.append(
            {
                "to": creator_address,
                "amount": royalty_microalgos,
                "purpose": "creator_royalty",
            }
        )

    merged_legs = _merge_algorand_payment_legs(payment_legs)
    buyer_total_microalgos = sum(int(leg["amount"]) for leg in merged_legs)

    return {
        "sale_price_microalgos": sale_price_microalgos,
        "buyer_platform_fee_microalgos": buyer_platform_fee_microalgos,
        "seller_platform_fee_microalgos": seller_platform_fee_microalgos,
        "royalty_microalgos": royalty_microalgos,
        "royalty_basis_points": royalty_basis,
        "platform_fee_basis_points": platform_fee_basis,
        "seller_receives_microalgos": seller_receives_microalgos,
        "platform_receives_microalgos": platform_receives_microalgos,
        "buyer_total_microalgos": buyer_total_microalgos,
        "creator_algorand_address": creator_address or None,
        "seller_algorand_address": seller_address,
        "platform_algorand_address": platform_address or None,
        "is_primary_sale": is_primary_sale,
        "payment_legs": merged_legs,
    }


async def _verify_algorand_sale_payments(
    tx_hash: str,
    buyer_wallet: str,
    expected_breakdown: Dict[str, Any],
    algorand_service,
) -> Dict[str, Any]:
    """Verify that buyer sent exact expected payment legs inside the transaction group."""
    buyer_wallet = (buyer_wallet or "").strip().lower()

    expected_by_receiver: Dict[str, int] = defaultdict(int)
    for leg in expected_breakdown.get("payment_legs", []):
        receiver = (leg.get("to") or "").strip()
        amount = int(leg.get("amount") or 0)
        if receiver and amount > 0:
            expected_by_receiver[receiver] += amount

    if not expected_by_receiver:
        raise HTTPException(status_code=400, detail="No expected Algorand payment legs available for verification")

    search_resp = algorand_service.indexer_client.search_transactions(txid=tx_hash, limit=1)
    txns = search_resp.get("transactions", []) if isinstance(search_resp, dict) else []
    if not txns:
        raise HTTPException(status_code=400, detail="Algorand transaction not found in indexer")

    anchor_tx = txns[0]
    confirmed_round = int(anchor_tx.get("confirmed-round") or 0)
    if confirmed_round <= 0:
        raise HTTPException(status_code=400, detail="Algorand transaction is not confirmed yet")

    group_id = _extract_group_id_from_indexer_tx(anchor_tx)
    group_id_bytes = _to_indexer_group_id_bytes(group_id)
    grouped_transactions = [anchor_tx]

    if group_id_bytes:
        grouped_resp = algorand_service.indexer_client.search_transactions(
            group_id=group_id_bytes,
            min_round=confirmed_round,
            max_round=confirmed_round,
            limit=50,
        )
        grouped_transactions = grouped_resp.get("transactions", []) if isinstance(grouped_resp, dict) else [anchor_tx]

    actual_by_receiver: Dict[str, int] = defaultdict(int)
    for txn in grouped_transactions:
        if txn.get("tx-type") != "pay":
            continue

        sender = (txn.get("sender") or "").strip().lower()
        if sender != buyer_wallet:
            continue

        payment_info = txn.get("payment-transaction", {}) if isinstance(txn, dict) else {}
        receiver = (payment_info.get("receiver") or "").strip()
        amount = int(payment_info.get("amount") or 0)
        if receiver and amount > 0:
            actual_by_receiver[receiver] += amount

    mismatches: List[str] = []
    for receiver, expected_amount in expected_by_receiver.items():
        actual_amount = actual_by_receiver.get(receiver, 0)
        if actual_amount != expected_amount:
            mismatches.append(f"{receiver}: expected {expected_amount}, got {actual_amount}")

    extras = [
        f"{receiver}: {amount}"
        for receiver, amount in actual_by_receiver.items()
        if receiver not in expected_by_receiver
    ]

    if mismatches or extras:
        detail_chunks = []
        if mismatches:
            detail_chunks.append("amount mismatch -> " + "; ".join(mismatches))
        if extras:
            detail_chunks.append("unexpected payment legs -> " + "; ".join(extras))
        raise HTTPException(
            status_code=400,
            detail="Algorand payment split verification failed: " + " | ".join(detail_chunks),
        )

    expected_total = int(expected_breakdown.get("buyer_total_microalgos") or 0)
    actual_total = sum(actual_by_receiver.values())
    if expected_total != actual_total:
        raise HTTPException(
            status_code=400,
            detail=(
                "Algorand payment total mismatch: "
                f"expected {expected_total} microalgos, got {actual_total} microalgos"
            ),
        )

    return {
        "group_id": group_id,
        "confirmed_round": confirmed_round,
        "actual_total_microalgos": actual_total,
        "expected_total_microalgos": expected_total,
    }
    

# # --- Sale transaction preparation ---
@router.post("/prepare-sale-transaction", response_model=Dict[str, Any])
async def prepare_sale_transaction(
    request: SaleTransactionRequest,  # Use request body instead of query params
    current_user: dict = Depends(get_current_user)
) -> Dict[str, Any]:
    """Prepare a sale transaction with proper address validation - REAL MODE ONLY"""
    try:
        # ✅ ADD LOGGING
        logger.info(f"Received sale transaction request: {request}")
        logger.info(f"Payment method: {request.payment_method}")
        # Extract parameters from request body
        # current_user = {"email": "test@test.com"}  # ✅ ADD DUMMY USER
        artwork_identifier = request.artwork_id
        buyer_address = request.buyer_address
        seller_address = request.seller_address
        sale_price_wei = request.sale_price_wei
        
        logger.info(f"Preparing sale - buyer: {buyer_address}, payment_method from request: {getattr(request, 'payment_method', 'not provided')}")
        # ✅ Check if request has payment_method field
        payment_method = (getattr(request, 'payment_method', None) or "crypto").lower()
        if payment_method == "paypal":
            raise HTTPException(
                status_code=400,
                detail="PayPal payment method is no longer supported. Use crypto payment."
            )

        # ✅ Get ticket to check its payment method (Support cross-collection fallback)
        artwork_doc = await resolve_artwork_identifier(artwork_identifier)
        if not artwork_doc and request.token_id:
            artwork_doc = await resolve_artwork_identifier(str(request.token_id))
            
        logger.info(f"Ticket found: {artwork_doc is not None}")
        
        # Keep numeric token_id for blockchain operations
        token_id = artwork_doc.get("token_id") if artwork_doc else request.token_id
        
        if not artwork_doc:
            raise HTTPException(status_code=404, detail="Ticket not found")

        network = _ensure_wirefluid_network(
            artwork_doc.get("network") or getattr(settings, "ACTIVE_NETWORK", "wirefluid") or "wirefluid"
        )
        is_algorand_sale = network == "algorand"
        
        # ✅ VALIDATION: Check payment method restrictions
        # Get ticket registration status (NEW - preferred method)
        is_on_chain = artwork_doc.get("is_on_chain")
        # Backward compatibility: derive from old fields if new fields don't exist
        if is_on_chain is None:
            artwork_payment_method = artwork_doc.get("payment_method", "crypto")
            is_virtual_token = artwork_doc.get("is_virtual_token", False)
            if artwork_payment_method == "paypal" or is_virtual_token:
                is_on_chain = False
            else:
                is_on_chain = True
        
        # ✅ RESTRICTION: On-chain tickets MUST use crypto (blockchain requirement)
        if is_on_chain and payment_method != "crypto":
            raise HTTPException(
                status_code=400,
                detail="This ticket is registered on blockchain. Only crypto payment is available for on-chain tickets."
            )
        
        # ✅ NO RESTRICTION: Off-chain tickets can use any payment method (PayPal, crypto, or future methods)
        # Off-chain tickets are flexible and can accept any payment method
        
        # Explicitly block removed payment method.
        if payment_method == "paypal":
            raise HTTPException(
                status_code=400,
                detail="PayPal payment method is no longer supported. Use crypto payment."
            )
        
        
        # ✅ Otherwise use crypto flow (existing code)
        logger.info("Using crypto flow for purchase")

        if is_algorand_sale:
            try:
                from algosdk import encoding as algo_encoding
                from algosdk.logic import get_application_address
                from services.algorand_service import algorand_service
            except Exception as algo_import_error:
                logger.error(f"❌ Algorand SDK import failed: {algo_import_error}")
                raise HTTPException(status_code=500, detail="Algorand SDK is not available on backend")

            try:
                algorand_service.algod_client.status()
            except Exception as algo_health_error:
                logger.error(f"❌ Algorand connection issue during sale preparation: {algo_health_error}")
                raise HTTPException(status_code=503, detail=f"Algorand service unavailable: {str(algo_health_error)}")

            buyer_address = (buyer_address or "").strip()
            seller_address = (seller_address or "").strip()

            if not algo_encoding.is_valid_address(buyer_address):
                raise HTTPException(status_code=400, detail="Invalid Algorand buyer address")

            owner_address = (
                artwork_doc.get("owner_algorand_address")
                or artwork_doc.get("creator_algorand_address")
                or artwork_doc.get("owner_address")
                or artwork_doc.get("creator_address")
            )

            asa_id = (
                artwork_doc.get("algorand_asa_id")
                or artwork_doc.get("nft_token_id")
                or artwork_doc.get("token_id")
                or request.token_id
            )
            if asa_id:
                try:
                    asa_id_int = int(asa_id)
                    chain_info = await algorand_service.get_asset_blockchain_info(asa_id_int)
                    if chain_info.get("success") and chain_info.get("owner"):
                        owner_address = chain_info.get("owner")
                    # Backfill missing ASA ID so future confirms do not fail.
                    if not artwork_doc.get("algorand_asa_id"):
                        try:
                            await get_artwork_collection().update_one(
                                {"_id": artwork_doc["_id"]},
                                {"$set": {"algorand_asa_id": asa_id_int, "updated_at": datetime.utcnow()}},
                            )
                        except Exception as backfill_error:
                            logger.warning(f"⚠️ Failed to backfill algorand_asa_id for token {token_id}: {backfill_error}")
                except Exception as owner_fetch_error:
                    logger.warning(f"⚠️ Failed to fetch live Algorand owner for sale token {token_id}: {owner_fetch_error}")

            buyer_opted_in = True
            asa_id_int = None
            if asa_id:
                try:
                    asa_id_int = int(asa_id)
                except Exception:
                    raise HTTPException(status_code=500, detail="Ticket has invalid Algorand ASA ID")

                try:
                    buyer_account_info = algorand_service.algod_client.account_info(buyer_address)
                    buyer_assets = buyer_account_info.get("assets", []) if isinstance(buyer_account_info, dict) else []
                    buyer_opted_in = any(int(asset.get("asset-id", 0)) == asa_id_int for asset in buyer_assets)
                except Exception as optin_check_error:
                    logger.error(f"❌ Failed to verify Algorand opt-in for {buyer_address}, ASA {asa_id_int}: {optin_check_error}")
                    raise HTTPException(status_code=503, detail="Unable to verify Algorand opt-in status")

            effective_seller = seller_address or owner_address
            if not effective_seller or not algo_encoding.is_valid_address(effective_seller):
                raise HTTPException(status_code=400, detail="Invalid Algorand seller address")

            if buyer_address == effective_seller:
                raise HTTPException(status_code=400, detail="Cannot purchase your own ticket")

            # Keep backward-compatible field name but value is in microalgos for Algorand.
            if sale_price_wei is not None:
                try:
                    sale_price_microalgos = int(sale_price_wei)
                except Exception:
                    raise HTTPException(status_code=400, detail="Invalid Algorand amount")
            else:
                artwork_price = float(artwork_doc.get("price") or 0)
                sale_price_microalgos = int(round(artwork_price * 1_000_000))

            if sale_price_microalgos <= 0:
                raise HTTPException(status_code=400, detail="Sale amount must be greater than zero")

            sale_breakdown = await _build_algorand_sale_breakdown(
                artwork_doc=artwork_doc,
                sale_price_microalgos=sale_price_microalgos,
                seller_address=effective_seller,
                platform_address=algorand_service.platform_address,
            )

            if token_id is None:
                raise HTTPException(status_code=400, detail="Ticket token ID is required for Algorand sale")

            app_id = artwork_doc.get("algorand_app_id") or getattr(settings, "ALGORAND_APP_ID", 0)
            app_id = int(app_id or 0)

            primary_leg = sale_breakdown["payment_legs"][0]

            # Fallback mode: if app is not configured, proceed with payment-only transaction.
            if app_id <= 0:
                logger.warning(
                    "⚠️ Algorand app ID is not configured for ticket %s. Using payment-only sale fallback.",
                    token_id,
                )
                return {
                    "to": primary_leg["to"],
                    "value": primary_leg["amount"],
                    "asaId": asa_id_int,
                    "buyerOptedIn": buyer_opted_in,
                    "requiresOptIn": bool(asa_id_int and not buyer_opted_in),
                    "payment_legs": sale_breakdown["payment_legs"],
                    "sale_breakdown": sale_breakdown,
                    "mode": "REAL",
                    "requires_blockchain": True,
                    "payment_method": "crypto",
                    "network": "algorand",
                    "algorand_payment_only": True,
                }

            return {
                # Legacy top-level fields are preserved, but payment_legs drives the actual split.
                "to": primary_leg["to"],
                "value": primary_leg["amount"],
                "asaId": asa_id_int,
                "buyerOptedIn": buyer_opted_in,
                "requiresOptIn": bool(asa_id_int and not buyer_opted_in),
                "payment_legs": sale_breakdown["payment_legs"],
                "sale_breakdown": sale_breakdown,
                "appId": app_id,
                "appArgs": [
                    "purchase_artwork",
                    int(token_id),
                    sale_price_microalgos
                ],
                "mode": "REAL",
                "requires_blockchain": True,
                "payment_method": "crypto",
                "network": "algorand"
            }
        
        # Buyer address must be a valid wallet for crypto flow.
        if not is_algorand_sale and not is_valid_wallet_address(buyer_address):
            raise HTTPException(
                status_code=400,
                detail="Invalid buyer wallet address for crypto purchase."
            )

        # ✅ CRITICAL: Check if we're in demo mode
        if web3_service.demo_mode:
            raise HTTPException(status_code=400, detail="Web3 service is in demo mode. Real transactions are disabled.")
        
        if not web3_service.w3 or not web3_service.w3.is_connected():
            raise HTTPException(status_code=500, detail="Web3 not connected")
        
        # Validate and convert addresses to checksum format
        try:
            buyer_address_checksum = Web3.to_checksum_address(buyer_address)
            seller_address_checksum = Web3.to_checksum_address(seller_address)
        except ValueError as e:
            logger.error(f"Invalid Ethereum address: {e}")
            raise HTTPException(status_code=400, detail=f"Invalid Ethereum address: {e}")
        
        # Get optimized gas prices
        gas_prices = await web3_service.get_current_gas_price()
        
        # Check buyer balance
        balance = web3_service.w3.eth.get_balance(buyer_address_checksum)
        
        # Estimate gas properly for the transaction
        try:
            gas_estimate = web3_service.w3.eth.estimate_gas({
                'from': buyer_address_checksum,
                'to': seller_address_checksum,
                'value': sale_price_wei,
                'data': f'0x{token_id:064x}'
            })
            estimated_gas = int(gas_estimate * 1.2)  # Add 20% buffer
        except Exception as gas_error:
            logger.warning(f"Gas estimation failed, using safe default: {gas_error}")
            estimated_gas = 50000
        
        # Calculate required balance
        if 'maxFeePerGas' in gas_prices:
            required_balance = sale_price_wei + (gas_prices['maxFeePerGas'] * estimated_gas)
        else:
            required_balance = sale_price_wei + (gas_prices['gasPrice'] * estimated_gas)
        
        if balance < required_balance:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Insufficient funds. Need {Web3.from_wei(required_balance, 'ether')} ETH, "
                    f"but only have {Web3.from_wei(balance, 'ether')} ETH"
                )
            )
        
        contract_address = _resolve_wirefluid_contract_address()
        if not contract_address:
            raise HTTPException(status_code=500, detail="Contract address not configured")
        
        contract_address_checksum = Web3.to_checksum_address(contract_address)

        # ✅ FIX: Prepare base params WITHOUT 'to' field (contract adds it automatically)
        platform_fee_percentage = await get_current_global_fee()  # Returns 20.0
        platform_fee_basis = int(platform_fee_percentage * 100)  # Convert to basis points (2000)

        buyer_platform_fee_wei = (sale_price_wei * platform_fee_basis) // 10000
        seller_platform_fee_wei = (sale_price_wei * platform_fee_basis) // 10000
        total_payment_wei = sale_price_wei + buyer_platform_fee_wei

        logger.info(f"💰 Sale payment calculation:")
        logger.info(f"   Sale Price: {Web3.from_wei(sale_price_wei, 'ether')} ETH")
        logger.info(f"   Buyer Platform Fee ({platform_fee_percentage}%): {Web3.from_wei(buyer_platform_fee_wei, 'ether')} ETH")
        logger.info(f"   Total Payment Required: {Web3.from_wei(total_payment_wei, 'ether')} ETH")

        # ✅ FIX: Prepare base params WITH buyer platform fee
        base_params = {
            'from': buyer_address_checksum,
            'value': total_payment_wei,  # ✅ Total payment (sale price + buyer platform fee)
            'nonce': web3_service.w3.eth.get_transaction_count(buyer_address_checksum),
        }
        
        # Add gas pricing to base params
        base_params.update(gas_prices)
        
        # Estimate gas first
        try:
            # Build temporary transaction for gas estimation
            temp_tx = web3_service.contract.functions.handleSale(
                token_id, 
                sale_price_wei,
                buyer_platform_fee_wei,  # ✅ Add this
                seller_platform_fee_wei  # ✅ Add this
            ).build_transaction({
                'from': buyer_address_checksum,
                'value': total_payment_wei,
                'nonce': web3_service.w3.eth.get_transaction_count(buyer_address_checksum),
            })
            # Estimate gas for contract call
            gas_estimate = web3_service.w3.eth.estimate_gas({
                'from': buyer_address_checksum,
                'to': contract_address_checksum,
                'value': total_payment_wei,
                'data': temp_tx['data']
            })
            estimated_gas = int(gas_estimate * 1.2)  # Add 20% buffer
            logger.info(f"✅ Gas estimated for handleSale: {estimated_gas}")
        except Exception as gas_error:
            logger.warning(f"Gas estimation failed, using safe default: {gas_error}")
            estimated_gas = 200000  # Higher gas for contract interaction
        
        # Add gas to base params
        base_params['gas'] = estimated_gas
        
        # Build final transaction (contract automatically adds 'to' field)
        tx = web3_service.contract.functions.handleSale(
            token_id, 
            sale_price_wei,
            buyer_platform_fee_wei,  # ✅ Pass calculated fee
            seller_platform_fee_wei  # ✅ Pass calculated fee
        ).build_transaction({
            **base_params,
            'value': total_payment_wei  # ✅ Transaction value: salePrice + buyerPlatformFee
        })
        
        # Return transaction data with properly formatted addresses
        result = {
            'to': tx['to'],  # ✅ Get from built transaction, not base_params
            'value': hex(tx['value']),  # ✅ Get from built transaction
            'gas': hex(tx['gas']),  # ✅ Get from built transaction
            'data': tx['data'],  # ✅ Get from built transaction (handleSale function call)
            'nonce': hex(tx['nonce']),  # ✅ Get from built transaction
            'mode': 'REAL',
            'requires_blockchain': True
        }
        
        # ✅ Calculate gas cost estimate in ETH
        if 'maxFeePerGas' in gas_prices:
            gas_cost_wei = gas_prices['maxFeePerGas'] * estimated_gas
        else:
            gas_cost_wei = gas_prices['gasPrice'] * estimated_gas

        gas_cost_eth = Web3.from_wei(gas_cost_wei, 'ether')

        # ✅ Add gas estimate to result
        result['gas_estimate_eth'] = float(gas_cost_eth)
        result['gas_limit'] = estimated_gas
        result['gas_cost_wei'] = str(gas_cost_wei)

        logger.info(f"✅ Prepared REAL sale transaction calling handleSale")
        logger.info(f"   Contract: {contract_address_checksum}")
        logger.info(f"   Token ID: {token_id}")
        logger.info(f"   Sale Price: {sale_price_wei} wei")
        logger.info(f"   Gas Estimate: {gas_cost_eth} ETH (limit: {estimated_gas})")
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Sale transaction preparation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Sale transaction preparation failed: {str(e)}")

@router.post("/confirm-sale")
async def confirm_sale_transaction(
    confirmation_data: SaleConfirmationRequest,  # Use proper model
    current_user: dict = Depends(get_current_user)
):
    """Confirm sale transaction after blockchain confirmation"""
    try:
        tx_hash = confirmation_data.tx_hash
        artwork_identifier = confirmation_data.artwork_id
        
        if not tx_hash or (not artwork_identifier and not confirmation_data.token_id):
            raise HTTPException(status_code=400, detail="Missing transaction hash or ticket ID")

        logger.info(f"🔄 Confirming sale transaction - Ticket ID: {artwork_identifier}, Token: {confirmation_data.token_id}, TX: {tx_hash}")

        db_artworks = get_artwork_collection()
        db_transactions = get_transaction_collection()
        
        # Get the ticket (Support cross-collection fallback)
        artwork_doc = await resolve_artwork_identifier(artwork_identifier)
        if not artwork_doc and confirmation_data.token_id:
            artwork_doc = await resolve_artwork_identifier(str(confirmation_data.token_id))
            
        if not artwork_doc:
            raise HTTPException(status_code=404, detail="Ticket not found")
            
        token_id = artwork_doc.get("token_id")
        network = _ensure_wirefluid_network(
            artwork_doc.get("network") or getattr(settings, "ACTIVE_NETWORK", "wirefluid") or "wirefluid"
        )
        is_algorand_sale = network == "algorand"

        # ✅ Use buyer_address from confirmation data (more reliable than current_user session)
        buyer_wallet_raw = confirmation_data.buyer_address or current_user.get('wallet_address') or ""
        buyer_wallet = buyer_wallet_raw.strip() if is_algorand_sale else buyer_wallet_raw.lower()
        if not buyer_wallet:
            raise HTTPException(status_code=400, detail="Missing buyer wallet address in sale confirmation")

        payment_breakdown = None

        if is_algorand_sale:
            from services.algorand_service import algorand_service
            from algosdk import encoding as algo_encoding

            if not algo_encoding.is_valid_address(buyer_wallet):
                raise HTTPException(status_code=400, detail="Invalid Algorand buyer address")

            app_id = artwork_doc.get("algorand_app_id") or getattr(settings, "ALGORAND_APP_ID", 0)
            app_id = int(app_id or 0)

            if app_id > 0:
                verification = await algorand_service.verify_licensing(
                    tx_hash=tx_hash,
                    app_id=app_id
                )
                if not verification.get("success"):
                    raise HTTPException(status_code=400, detail=f"Algorand verification failed: {verification.get('error')}")
            else:
                pending_txn = algorand_service.algod_client.pending_transaction_info(tx_hash)
                if int(pending_txn.get("confirmed-round", 0)) <= 0:
                    raise HTTPException(status_code=400, detail="Algorand transaction not confirmed yet")

            asa_id = (
                artwork_doc.get("algorand_asa_id")
                or artwork_doc.get("nft_token_id")
                or artwork_doc.get("token_id")
                or confirmation_data.token_id
            )
            if not asa_id:
                raise HTTPException(status_code=400, detail="Ticket ASA ID is missing; cannot verify Algorand ownership transfer")

            transfer_tx_hash = None
            pre_transfer_owner = None

            try:
                asa_id_int = int(asa_id)
                if not artwork_doc.get("algorand_asa_id"):
                    try:
                        await db_artworks.update_one(
                            {"_id": artwork_doc["_id"]},
                            {"$set": {"algorand_asa_id": asa_id_int, "updated_at": datetime.utcnow()}},
                        )
                    except Exception as backfill_error:
                        logger.warning(f"⚠️ Failed to backfill algorand_asa_id during confirm for token {token_id}: {backfill_error}")
                chain_info = await algorand_service.get_asset_blockchain_info(asa_id_int)
                if not chain_info.get("success"):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Failed to fetch Algorand asset ownership: {chain_info.get('error') or 'Unknown error'}"
                    )

                pre_transfer_owner = (chain_info.get("owner") or "").strip()
                if not pre_transfer_owner:
                    raise HTTPException(status_code=400, detail="Could not determine current Algorand asset owner")

                try:
                    sale_price_microalgos = int(str(confirmation_data.sale_price_wei))
                except Exception:
                    raise HTTPException(status_code=400, detail="Invalid sale amount for Algorand confirmation")

                payment_breakdown = await _build_algorand_sale_breakdown(
                    artwork_doc=artwork_doc,
                    sale_price_microalgos=sale_price_microalgos,
                    seller_address=pre_transfer_owner,
                    platform_address=algorand_service.platform_address,
                )

                await _verify_algorand_sale_payments(
                    tx_hash=tx_hash,
                    buyer_wallet=buyer_wallet,
                    expected_breakdown=payment_breakdown,
                    algorand_service=algorand_service,
                )

                if pre_transfer_owner.lower() != buyer_wallet.lower():
                    transfer_result = await algorand_service.transfer_asset_with_clawback(
                        asa_id=asa_id_int,
                        current_owner=pre_transfer_owner,
                        new_owner=buyer_wallet,
                        amount=1,
                        note=f"sale:{token_id}:{tx_hash}",
                    )
                    if not transfer_result.get("success"):
                        raise HTTPException(
                            status_code=400,
                            detail=(
                                "Algorand payment succeeded but NFT transfer failed: "
                                f"{transfer_result.get('error') or 'Unknown transfer error'}"
                            ),
                        )
                    transfer_tx_hash = transfer_result.get("tx_hash")

                owner_check = await algorand_service.get_asset_blockchain_info(asa_id_int)
                if not owner_check.get("success"):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Failed to verify post-transfer owner: {owner_check.get('error') or 'Unknown error'}"
                    )
                live_owner = (owner_check.get("owner") or "").strip()
                if live_owner.lower() != buyer_wallet.lower():
                    raise HTTPException(
                        status_code=400,
                        detail=f"On-chain NFT transfer not detected yet. Current owner is {live_owner}."
                    )
            except HTTPException:
                raise
            except Exception as ownership_verify_error:
                logger.error(f"❌ Failed Algorand ownership verification for token {token_id}, tx {tx_hash}: {ownership_verify_error}")
                raise HTTPException(status_code=500, detail="Failed to verify Algorand NFT ownership transfer")
        else:
            # Verify transaction on blockchain (EVM)
            tx_receipt = await web3_service.get_transaction_receipt(tx_hash)
            if not tx_receipt:
                raise HTTPException(status_code=400, detail="Transaction not found on blockchain")

            if tx_receipt.get("status") != 1:
                raise HTTPException(status_code=400, detail="Transaction failed on blockchain")

        # Update ticket ownership in tickets collection (single source of truth)
        target_collection = db_artworks
        
        buyer_user_id = str(
            current_user.get('user_id')
            or current_user.get('id')
            or current_user.get('_id')
            or ""
        )
        update_fields = {
            "owner_address": buyer_wallet,
            "is_for_sale": False,
            "updated_at": datetime.utcnow(),
            "sold_at": datetime.utcnow(),
        }
        if is_algorand_sale:
            update_fields["owner_algorand_address"] = buyer_wallet
        if buyer_user_id:
            update_fields["owner_id"] = buyer_user_id

        update_result = await target_collection.update_one(
            {"_id": artwork_doc["_id"]},
            {"$set": update_fields}
        )

        if update_result.matched_count == 0:
            raise HTTPException(status_code=500, detail="Failed to update ticket ownership")
        if update_result.modified_count == 0:
            logger.warning(
                "⚠️ Sale confirm matched ticket but no fields changed (token=%s, tx=%s)",
                token_id,
                tx_hash,
            )
        # ✅ REDIS CACHE: Invalidate ticket cache after sale
        try:
            invalidate_artwork_cache(token_id)
            invalidate_blockchain_cache(token_id)
            invalidate_artworks_cache()
            logger.info(f"🗑️ Ticket cache invalidated after sale for token {token_id}")
        except Exception as cache_error:
            logger.warning(f"⚠️ Failed to invalidate cache: {cache_error}")
        # Create transaction record
        sale_transaction = {
            "tx_hash": tx_hash,
            "token_id": token_id,
            "from_address": buyer_wallet,
            "to_address": pre_transfer_owner if is_algorand_sale else artwork_doc.get("owner_address"),
            "from_user_id": str(current_user.get('id') or current_user.get('_id') or current_user.get('user_id')),
            "to_user_id": artwork_doc.get("owner_id"),
            "value": str(
                payment_breakdown.get("sale_price_algo") # Should be human readable ALGO
                if is_algorand_sale and payment_breakdown
                else confirmation_data.sale_price_eth
            ),
            "transaction_type": "SALE",
            "status": "CONFIRMED",
            "payment_method": confirmation_data.payment_method or "crypto",  # ADD THIS
            "currency": "ALGO" if is_algorand_sale else "ETH",
            "asset_transfer_tx_hash": transfer_tx_hash if is_algorand_sale else None,
            "sale_price_microalgos": payment_breakdown.get("sale_price_microalgos") if is_algorand_sale and payment_breakdown else None,
            "buyer_platform_fee_microalgos": payment_breakdown.get("buyer_platform_fee_microalgos") if is_algorand_sale and payment_breakdown else None,
            "seller_platform_fee_microalgos": payment_breakdown.get("seller_platform_fee_microalgos") if is_algorand_sale and payment_breakdown else None,
            "royalty_microalgos": payment_breakdown.get("royalty_microalgos") if is_algorand_sale and payment_breakdown else None,
            "platform_receives_microalgos": payment_breakdown.get("platform_receives_microalgos") if is_algorand_sale and payment_breakdown else None,
            "seller_receives_microalgos": payment_breakdown.get("seller_receives_microalgos") if is_algorand_sale and payment_breakdown else None,
            "buyer_total_microalgos": payment_breakdown.get("buyer_total_microalgos") if is_algorand_sale and payment_breakdown else None,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }

        await db_transactions.insert_one(sale_transaction)

        # Log user action
        await UserHistoryService.log_user_action(
            user_id=str(current_user.get('id', '')),
            action="artwork_purchase_confirmed",
            artwork_id=str(artwork_doc.get('_id', '')),
            artwork_token_id=token_id,
            metadata={
                "transaction_hash": tx_hash,
                "previous_owner": artwork_doc.get("owner_address"),
                "sale_price": confirmation_data.sale_price_eth
            }
        )

        logger.info(f"✅ Sale confirmed successfully for token {token_id}, transaction {tx_hash}")

        return {
            "success": True,
            "message": "Sale confirmed successfully",
            "token_id": token_id,
            "transaction_hash": tx_hash,
            "new_owner": buyer_wallet
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error confirming sale: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to confirm sale: {str(e)}")
    
@router.get("/health/blockchain")
async def blockchain_health():
    """Minimal blockchain health check"""
    try:
        # Just return basic status without complex nested data
        return {
            "success": True,
            "connected": web3_service.connected,
            "demo_mode": web3_service.demo_mode,
            "provider_configured": bool(
                getattr(settings, 'WIREFLUID_RPC_URL', None)
                or getattr(settings, 'WEB3_PROVIDER_URL', None)
            ),
            "contract_configured": bool(_resolve_wirefluid_contract_address()),
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "connected": False,
            "demo_mode": getattr(web3_service, 'demo_mode', True)
        }
    
# ADD THIS HELPER FUNCTION FOR PAYPAL SALES
async def prepare_paypal_sale_transaction(
    artwork_id: str,
    token_id: int,
    buyer_address: str,
    sale_price: float,
    current_owner: str,
    current_user: dict
) -> Dict[str, Any]:
    """Prepare PayPal sale transaction with proper user field handling"""
    try:
        from bson import ObjectId
        
        artworks_collection = get_artwork_collection()
        users_collection = get_user_collection()
        
        # Get ticket info
        if artwork_id and ObjectId.is_valid(artwork_id):
            artwork_doc = await artworks_collection.find_one({"_id": ObjectId(artwork_id)})
        else:
            artwork_doc = await artworks_collection.find_one({"token_id": token_id}, sort=[("_id", -1)])
            
        if not artwork_doc:
            logger.error(f"Ticket not found for ID: {artwork_id} or token_id: {token_id}")
            raise HTTPException(status_code=404, detail="Ticket not found")
        
        # Get artwork_id from document (to be certain)
        artwork_id = str(artwork_doc['_id'])
        logger.info(f"Found ticket with _id: {artwork_id}")
        
        # ✅ FIXED: Get seller user info - handle both crypto (wallet_address) and PayPal (owner_id/email)
        seller_user = None
        
        # ✅ Priority 1: For PayPal tickets, ALWAYS use owner_id from ticket document (ignore current_owner if it's a placeholder)
        if artwork_doc.get("payment_method") == "paypal":
            owner_id = artwork_doc.get("owner_id")
            if owner_id:
                owner_id_str = str(owner_id)
                logger.info(f"🔍 Looking up seller by ticket owner_id: {owner_id_str} (type: {type(owner_id)})")
                
                # Try multiple lookup methods
                lookup_queries = [
                    {"_id": ObjectId(owner_id_str)},  # Try as ObjectId _id first (most common)
                    {"user_id": owner_id_str},        # Try as user_id string
                    {"id": owner_id_str},             # Try as id field
                    {"_id": owner_id_str}             # Try as string _id
                ]
                
                for query in lookup_queries:
                    try:
                        seller_user = await users_collection.find_one(query)
                        if seller_user:
                            logger.info(f"✅ Found seller using query: {query}")
                            break
                    except Exception as e:
                        logger.debug(f"Query failed for {query}: {e}")
                        continue
                
                # Also try creator_id as fallback (for PayPal, creator is initially owner)
        if not seller_user:
                    creator_id = artwork_doc.get("creator_id")
                    if creator_id and str(creator_id) != owner_id_str:  # Only if different
                        creator_id_str = str(creator_id)
                        logger.info(f"🔍 Trying creator_id as fallback: {creator_id_str}")
                        
                        creator_lookup_queries = [
                            {"_id": ObjectId(creator_id_str)},
                            {"user_id": creator_id_str},
                            {"id": creator_id_str},
                            {"_id": creator_id_str}
                        ]
                        
                        for query in creator_lookup_queries:
                            try:
                                seller_user = await users_collection.find_one(query)
                                if seller_user:
                                    logger.info(f"✅ Found seller by creator_id using query: {query}")
                                    break
                            except Exception as e:
                                logger.debug(f"Creator query failed for {query}: {e}")
                                continue
        
        # ✅ Priority 2: Only try current_owner if it's NOT a placeholder and seller not found yet
        if not seller_user and current_owner and current_owner not in ['paypal_user', 'unknown', '']:
            # Try by email (if current_owner is an email)
            if "@" in str(current_owner):
                logger.info(f"🔍 Trying seller lookup by email: {current_owner}")
                seller_user = await users_collection.find_one({"email": str(current_owner).lower()})
            
            # Try by wallet_address (for crypto tickets)
            if not seller_user:
                logger.info(f"🔍 Trying seller lookup by wallet_address: {current_owner}")
                seller_user = await users_collection.find_one({"wallet_address": str(current_owner).lower()})
            
            # Try by user_id (if current_owner is a user ID)
            if not seller_user:
                logger.info(f"🔍 Trying seller lookup by user_id: {current_owner}")
                seller_user = await users_collection.find_one({"user_id": str(current_owner)})
        
        if not seller_user:
            # ✅ Last resort: Try to find ANY user to verify database connection
            test_user = await users_collection.find_one({})
            logger.error(f"❌ Seller user not found")
            logger.error(f"   current_owner parameter: {current_owner}")
            logger.error(f"   Ticket payment_method: {artwork_doc.get('payment_method')}")
            logger.error(f"   Ticket owner_id: {artwork_doc.get('owner_id')} (type: {type(artwork_doc.get('owner_id'))})")
            logger.error(f"   Ticket creator_id: {artwork_doc.get('creator_id')} (type: {type(artwork_doc.get('creator_id'))})")
            if test_user:
                logger.error(f"   Database connection OK. Sample user fields: {list(test_user.keys())[:10]}")
            else:
                logger.error(f"   Database connection issue - no users found at all")
            
            # ✅ Try one more time with $or query to catch all possible field names
            if owner_id:
                owner_id_str = str(owner_id)
                final_queries = []
                
                # Try as ObjectId _id
                if ObjectId.is_valid(owner_id_str):
                    final_queries.append({"_id": ObjectId(owner_id_str)})
                
                # Try as string _id
                final_queries.append({"_id": owner_id_str})
                
                # Try as user_id string
                final_queries.append({"user_id": owner_id_str})
                
                # Try as id field
                final_queries.append({"id": owner_id_str})
                
                if final_queries:
                    final_query = {"$or": final_queries}
                    try:
                        logger.info(f"🔍 Final attempt with $or query: {len(final_queries)} variations")
                        seller_user = await users_collection.find_one(final_query)
                        if seller_user:
                            logger.info(f"✅ Found seller using final $or query!")
                        else:
                            logger.error(f"❌ Final $or query returned no results")
                    except Exception as e:
                        logger.error(f"Final $or query failed: {e}")
            
            if not seller_user:
                raise HTTPException(status_code=404, detail=f"Seller user not found. Owner ID: {artwork_doc.get('owner_id')}")
        
        logger.info(f"✅ Found seller user: {seller_user.get('email')} (ID: {seller_user.get('_id')}, user_id: {seller_user.get('user_id')})")
        
        # ✅ FIXED: Get buyer user info - Try multiple methods
        buyer_user_id = current_user.get("user_id") or current_user.get("id")
        buyer_email = current_user.get("email")
        
        if not buyer_user_id:
            logger.error(f"Buyer user ID not found in token")
            raise HTTPException(status_code=404, detail="Buyer user ID not found")
        
        # Try to find buyer by ID
        if ObjectId.is_valid(buyer_user_id):
            buyer_user = await users_collection.find_one({"_id": ObjectId(buyer_user_id)})
        else:
            buyer_user = await users_collection.find_one({"user_id": buyer_user_id})
        
        # Fallback: try by email
        if not buyer_user and buyer_email:
            buyer_user = await users_collection.find_one({"email": buyer_email})
        
        # Fallback: try by wallet address (if provided)
        if not buyer_user and buyer_address:
            buyer_user = await users_collection.find_one({"wallet_address": buyer_address.lower()})
        
        if not buyer_user:
            logger.error(f"Buyer user not found for ID: {buyer_user_id}, Email: {buyer_email}")
            raise HTTPException(status_code=404, detail="Buyer user not found")
        
        logger.info(f"✅ Found buyer user: {buyer_user.get('email')}")
        
        # ✅ MANDATORY: Check if buyer has tickets listed for sale - if yes, must be onboarded
        buyer_user_id_final = str(buyer_user.get('_id') or buyer_user.get('user_id') or buyer_user.get('id'))
        
        # Check if buyer has any tickets listed for sale
        buyer_artworks_for_sale = await artworks_collection.count_documents({
            "owner_id": buyer_user_id_final,
            "is_for_sale": True,
            "payment_method": "paypal"
        })
        
        if buyer_artworks_for_sale > 0:
            logger.info(f"🔍 Buyer has {buyer_artworks_for_sale} PayPal ticket(s) listed for sale - Checking onboarding...")
            
            # ✅ MANDATORY: Buyer MUST be onboarded if they have tickets for sale - Find LATEST onboarded record
            db = get_db()
            sellers_collection = db.sellers
            
            buyer_merchant_id = None
            buyer_is_onboarded = False
            
            # ✅ Strategy 1: Find LATEST seller record with onboarded=true AND merchant_id
            all_buyer_sellers = await sellers_collection.find(
                {
                    "user_id": buyer_user_id_final,
                    "onboarded": True,  # ✅ MUST be onboarded
                    "merchant_id": {"$ne": None, "$exists": True}  # ✅ MUST have merchant_id
                }
            ).sort("updated_at", -1).limit(1).to_list(length=1)
            
            if all_buyer_sellers and len(all_buyer_sellers) > 0:
                latest_buyer_seller = all_buyer_sellers[0]
                buyer_merchant_id = latest_buyer_seller.get('merchant_id')
                buyer_is_onboarded = True
                logger.info(f"✅✅✅ Found LATEST onboarded buyer: merchant_id={buyer_merchant_id}, updated_at={latest_buyer_seller.get('updated_at')}")
            
            # ✅ Strategy 2: Check user collection for paypal_onboarded (fallback)
            if not buyer_merchant_id:
                buyer_paypal_onboarded = buyer_user.get('paypal_onboarded', False)
                buyer_paypal_merchant_id = buyer_user.get('paypal_merchant_id')
                if buyer_paypal_onboarded and buyer_paypal_merchant_id:
                    buyer_merchant_id = buyer_paypal_merchant_id
                    buyer_is_onboarded = True
                    logger.info(f"👤 Buyer onboarded via user collection: merchant_id={buyer_merchant_id}")
            
            # ✅ MANDATORY CHECK: Buyer MUST be onboarded if they have tickets for sale
            if not buyer_is_onboarded or not buyer_merchant_id:
                logger.warning(f"❌ Buyer {buyer_user_id_final} has {buyer_artworks_for_sale} ticket(s) for sale but is NOT onboarded")
                logger.warning(f"   Purchase BLOCKED - Buyer must complete PayPal onboarding first")
                raise HTTPException(
                    status_code=400,
                    detail=f"You have {buyer_artworks_for_sale} ticket(s) listed for sale. PayPal onboarding is REQUIRED before you can purchase tickets. Please complete PayPal onboarding first to ensure you can receive payments when your tickets are sold."
                )
            
            logger.info(f"✅✅✅ Buyer is onboarded with merchant_id: {buyer_merchant_id}")
        
        # ✅ FIXED: Get user IDs properly
        seller_user_id = str(seller_user.get('_id') or seller_user.get('user_id') or seller_user.get('id'))
        
        logger.info(f"Seller user_id: {seller_user_id}, Buyer user_id: {buyer_user_id_final}")
        
        if not seller_user_id:
            logger.error(f"Seller user ID not found in user document: {seller_user.keys()}")
            raise HTTPException(status_code=400, detail="Seller user ID not found")
        
        if not buyer_user_id_final:
            logger.error(f"Buyer user ID not found in user document: {buyer_user.keys()}")
            raise HTTPException(status_code=400, detail="Buyer user ID not found")
        
        # Get emails
        seller_email = seller_user.get('email') or f"seller_{seller_user_id}@artplatform.com"
        buyer_email_final = buyer_user.get('email') or buyer_email or f"buyer_{buyer_user_id_final}@artplatform.com"
        
        logger.info(f"Creating PayPal sale order...")
        paypal_service = get_paypal_service()
        
        # Create PayPal sale order
        paypal_result = await paypal_service.create_artwork_sale_order(
            artwork_id=str(artwork_doc['_id']),
            token_id=token_id,
            buyer_id=buyer_user_id_final,
            buyer_email=buyer_email_final,
            seller_user_id=seller_user_id,
            amount=sale_price
        )
        
        logger.info(f"PayPal order result: {paypal_result}")
        
        if not paypal_result['success']:
            raise HTTPException(status_code=400, detail=paypal_result.get('error'))
        
        return {
            "transaction_data": {
                "type": "paypal",
                "order_id": paypal_result['order_id'],
                "approval_url": paypal_result['approval_url']
            },
            "sale_details": {
                "token_id": token_id,
                "sale_price_eth": sale_price,
                "current_owner": current_owner,
                "buyer_address": buyer_address,
                "payment_method": "paypal",
                "paypal_order_id": paypal_result['order_id']
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"PayPal sale preparation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"PayPal sale preparation failed: {str(e)}")

# --- Confirm sale ---
@router.post("/confirm-sale", response_model=dict)
async def confirm_sale(
    sale_confirmation: dict,  # CHANGE: Use dict instead of SaleConfirmation to handle both types
    current_user: dict = Depends(get_current_user)  # CHANGE: Use dict
):
    try:
        payment_method = sale_confirmation.get("payment_method", "crypto")
        
        # PayPal flow removed.
        if payment_method == "paypal":
            raise HTTPException(
                status_code=400,
                detail="PayPal payment method is no longer supported."
            )
        
        # Existing crypto sale confirmation logic
        artworks_collection = get_artwork_collection()
        transactions_collection = get_transaction_collection()
        users_collection = get_user_collection()  # ADD THIS

        tx_hash = sale_confirmation.get("tx_hash")
        token_id = sale_confirmation.get("token_id")
        buyer_address = sale_confirmation.get("buyer_address")
        seller_address = sale_confirmation.get("seller_address")
        sale_price = sale_confirmation.get("sale_price")

        if not all([tx_hash, token_id, buyer_address, seller_address, sale_price]):
            raise HTTPException(status_code=400, detail="Missing required sale parameters")

        # Verify transaction
        tx_receipt = await web3_service.get_transaction_receipt(tx_hash)
        if not tx_receipt or tx_receipt.get("status") != 1:
            raise HTTPException(status_code=400, detail="Sale transaction failed or not found")

        # Get the ticket document
        artwork_doc = await artworks_collection.find_one({"token_id": token_id}, sort=[("_id", -1)])
        if not artwork_doc:
            raise HTTPException(status_code=404, detail="Ticket not found")

        artwork_id = str(artwork_doc.get('_id', ''))

        # ✅ LOG: Log incoming data
        logger.info(f"🔄 Confirming sale - Token: {token_id}, TX: {tx_hash}")
        logger.info(f"   buyer_address: {buyer_address}")
        logger.info(f"   seller_address: {seller_address}")
        logger.info(f"   current_user: {current_user.get('wallet_address') if current_user else 'None'}")
        
        # GET BUYER AND SELLER USER INFO - ADD THIS
        buyer_user = await users_collection.find_one({"wallet_address": buyer_address.lower()})
        seller_user = await users_collection.find_one({"wallet_address": seller_address.lower()})


        logger.info(f"   buyer_user found: {buyer_user is not None}")
        logger.info(f"   seller_user found: {seller_user is not None}")

        # Update ticket ownership - ADD USER ID SUPPORT
        update_data = {
            "owner_address": buyer_address.lower(),
            "is_for_sale": False,  # ✅ Disable for sale after purchase
            "updated_at": datetime.utcnow()
        }
        
        # ✅ FIX: Get user ID from multiple possible fields
        if buyer_user:
            # Try different field names (user_id, _id, id)
            buyer_user_id = (
                buyer_user.get('user_id') or 
                buyer_user.get('_id') or 
                buyer_user.get('id')
            )
            if buyer_user_id:
                update_data["owner_id"] = str(buyer_user_id)
                logger.info(f"   buyer_user_id: {buyer_user_id}")
            else:
                logger.warning(f"⚠️ Buyer user found but no ID field: {buyer_user}")
        else:
            # ✅ FALLBACK: Use current_user if buyer_user not found
            current_user_id = current_user.get('id') or current_user.get('_id')
            if current_user_id:
                update_data["owner_id"] = str(current_user_id)
                logger.info(f"   Using current_user_id: {current_user_id}")
            else:
                logger.warning(f"⚠️ No buyer user found and current_user has no ID")

        # ✅ LOG: Verify what we're updating
        logger.info(f"✅ Updating ticket ownership - Token: {token_id}")
        logger.info(f"   owner_address: {update_data.get('owner_address')}")
        logger.info(f"   owner_id: {update_data.get('owner_id')}")

        update_filter = {"_id": artwork_doc.get("_id")} if artwork_doc.get("_id") is not None else {"token_id": token_id}
        update_result = await artworks_collection.update_one(
            update_filter,
            {"$set": update_data}
        )

        # ✅ LOG: Verify update result
        logger.info(f"✅ Update result - Modified: {update_result.modified_count}, Matched: {update_result.matched_count}")

        if update_result.modified_count == 0 and update_result.matched_count == 0:
            logger.error(f"❌ Ticket not found for token_id: {token_id}")
        elif update_result.modified_count == 0:
            logger.warning(f"⚠️ Ticket found but no changes made (already updated?)")
        # ✅ REDIS CACHE: Invalidate ticket cache after sale
        try:
            invalidate_artwork_cache(token_id)
            invalidate_blockchain_cache(token_id)
            invalidate_artworks_cache()
            logger.info(f"🗑️ Ticket cache invalidated after sale for token {token_id}")
        except Exception as cache_error:
            logger.warning(f"⚠️ Failed to invalidate cache: {cache_error}")
        # Create transaction record
        sale_transaction = TransactionCreate(
            tx_hash=tx_hash,
            from_address=seller_address,
            to_address=buyer_address,
            value=str(sale_price),
            transaction_type=TransactionType.SALE,
            status=TransactionStatus.CONFIRMED,
            metadata={
                "token_id": token_id, 
                "artwork_id": artwork_id,
                "payment_method": "crypto",  # ADD THIS
                "buyer_user_id": str(buyer_user.get('user_id') or buyer_user.get('_id') or buyer_user.get('id')) if buyer_user else (str(current_user.get('id') or current_user.get('_id')) if current_user else None),
                "seller_user_id": str(seller_user.get('user_id') or seller_user.get('_id') or seller_user.get('id')) if seller_user else None
            }
        )

        await transactions_collection.insert_one(sale_transaction.model_dump(by_alias=True))

        # GET BUYER USER ID - ADD THIS
        buyer_user_id = str(current_user.get('id', ''))
        if not buyer_user_id and buyer_user:
            buyer_user_id = str(buyer_user.get('_id', ''))

        # Log user action with the correct artwork_id
        await UserHistoryService.log_user_action(
            user_id=buyer_user_id,  # FIXED: Use proper buyer user ID
            action="purchase",
            artwork_id=artwork_id,
            artwork_token_id=token_id,
            metadata={
                "sale_price": sale_price,
                "seller_address": seller_address,
                "buyer_address": buyer_address,
                "tx_hash": tx_hash,
                "artwork_title": artwork_doc.get("title", "Untitled"),
                "payment_method": "crypto"  # ADD THIS
            }
        )

        # Also log the seller's action if needed
        seller_user_id = None
        if seller_user:
            seller_user_id = str(seller_user.get('_id', ''))
        elif seller_address.lower() != current_user.get('wallet_address', '').lower():
            # Find seller user by wallet address
            seller_user = await users_collection.find_one({"wallet_address": seller_address.lower()})
            if seller_user:
                seller_user_id = str(seller_user.get('_id', ''))

        if seller_user_id:
            await UserHistoryService.log_user_action(
                user_id=seller_user_id,
                action="sale",
                artwork_id=artwork_id,
                artwork_token_id=token_id,
                metadata={
                    "sale_price": sale_price,
                    "buyer_address": buyer_address,
                    "tx_hash": tx_hash,
                    "artwork_title": artwork_doc.get("title", "Untitled"),
                    "payment_method": "crypto"  # ADD THIS
                }
            )

        return {
            "success": True,
            "message": "Sale confirmed successfully",
            "new_owner": buyer_address,
            "token_id": token_id,
            "artwork_id": artwork_id,
            "payment_method": "crypto"  # ADD THIS
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Sale confirmation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to confirm sale: {str(e)}")


# ADD THIS HELPER FUNCTION FOR PAYPAL SALE CONFIRMATION
async def confirm_paypal_sale(sale_confirmation: dict, current_user: dict) -> Dict[str, Any]:
    """Confirm PayPal sale with proper user field handling"""
    try:

        artworks_collection = get_artwork_collection()
        users_collection = get_user_collection()
        
        order_id = sale_confirmation.get("order_id")
        token_id = sale_confirmation.get("token_id")
        
        if not order_id or not token_id:
            raise HTTPException(status_code=400, detail="Missing PayPal order ID or token ID")

        paypal_service = get_paypal_service()
        
        # ✅ FIXED: Get order document FIRST to get buyer/seller IDs
        from app.db.database import get_db
        db = get_db()
        paypal_orders_collection = db.paypal_orders
        
        order_doc = await paypal_orders_collection.find_one({"paypal_order_id": order_id})
        if not order_doc:
            raise HTTPException(status_code=404, detail="Order document not found")
        
        # ✅ FIXED: Use current_user for buyer (buyer is making the request)
        # Get seller ID from order document
        seller_user_id = order_doc.get('seller_user_id')
        
        if not seller_user_id:
            raise HTTPException(status_code=400, detail="Missing seller user ID in order document")
        
        # ✅ Get buyer from current_user (the one making the request)
        buyer_user_id_from_token = current_user.get("user_id") or current_user.get("id")
        buyer_email = current_user.get("email")
        
        # Capture PayPal payment
        capture_result = await paypal_service.capture_payment(order_id)
        if not capture_result['success']:
            raise HTTPException(status_code=400, detail="PayPal payment capture failed")

        order_data = capture_result['order']
        
        # Get ticket info
        artwork_doc = await artworks_collection.find_one({"token_id": token_id}, sort=[("_id", -1)])
        if not artwork_doc:
            raise HTTPException(status_code=404, detail="Ticket not found")

        artwork_id = str(artwork_doc.get('_id', ''))
        
        # ✅ Find buyer user - try multiple methods
        buyer_user = None
        if buyer_user_id_from_token:
            lookup_queries = []
            if ObjectId.is_valid(buyer_user_id_from_token):
                lookup_queries.append({"_id": ObjectId(buyer_user_id_from_token)})
            lookup_queries.append({"_id": buyer_user_id_from_token})
            lookup_queries.append({"user_id": buyer_user_id_from_token})
            lookup_queries.append({"id": buyer_user_id_from_token})
            
            for query in lookup_queries:
                try:
                    buyer_user = await users_collection.find_one(query)
                    if buyer_user:
                        break
                except:
                    continue
        
        # If still not found, try by email
        if not buyer_user and buyer_email:
            buyer_user = await users_collection.find_one({"email": buyer_email})
        
        if not buyer_user:
            logger.error(f"Buyer user not found. ID from token: {buyer_user_id_from_token}, Email: {buyer_email}")
            raise HTTPException(status_code=404, detail="Buyer user not found")
        
        # ✅ Find seller user - try multiple methods
        seller_user = None
        seller_user_id_str = str(seller_user_id)
        lookup_queries = []
        if ObjectId.is_valid(seller_user_id_str):
            lookup_queries.append({"_id": ObjectId(seller_user_id_str)})
        lookup_queries.append({"_id": seller_user_id_str})
        lookup_queries.append({"user_id": seller_user_id_str})
        lookup_queries.append({"id": seller_user_id_str})
        
        for query in lookup_queries:
            try:
                seller_user = await users_collection.find_one(query)
                if seller_user:
                    break
            except:
                continue
        
        if not seller_user:
            logger.error(f"Seller user not found with ID: {seller_user_id}")
            raise HTTPException(status_code=404, detail="Seller user not found")

        # ✅ FIXED: For PayPal tickets, only set owner_address if buyer has a wallet
        # PayPal tickets should use owner_id, not wallet_address
        buyer_wallet = buyer_user.get('wallet_address') or ""
        buyer_user_id = str(buyer_user.get('_id') or buyer_user.get('user_id') or buyer_user.get('id'))
        seller_wallet = seller_user.get('wallet_address') or ""

        # Update ticket ownership - only set owner_address if buyer has wallet
        update_data = {
            "owner_id": buyer_user_id,
            "is_for_sale": False,  # ✅ Disable for sale after purchase
            "updated_at": datetime.utcnow(),
            "payment_method": "paypal",
            "paypal_order_id": order_id
        }
        
        # Only set owner_address if buyer has a wallet (for mixed users)
        if buyer_wallet:
            update_data["owner_address"] = buyer_wallet.lower()
        else:
            # For PayPal-only users, set owner_address to None
            update_data["owner_address"] = None
        
        update_filter = {"_id": artwork_doc.get("_id")} if artwork_doc.get("_id") is not None else {"token_id": token_id}
        await artworks_collection.update_one(
            update_filter,
            {"$set": update_data}
        )
        # ✅ REDIS CACHE: Invalidate ticket cache after PayPal sale
        try:
            invalidate_artwork_cache(token_id)
            invalidate_blockchain_cache(token_id)
            invalidate_artworks_cache()
            logger.info(f"🗑️ Ticket cache invalidated after PayPal sale for token {token_id}")
        except Exception as cache_error:
            logger.warning(f"⚠️ Failed to invalidate cache: {cache_error}")

        # Log user actions
        buyer_user_log_id = str(buyer_user.get('_id') or buyer_user.get('user_id') or buyer_user.get('id'))
        seller_user_log_id = str(seller_user.get('_id') or seller_user.get('user_id') or seller_user.get('id'))
        
        # Log buyer action
        await UserHistoryService.log_user_action(
            user_id=buyer_user_log_id,
            action="purchase",
            artwork_id=artwork_id,
            artwork_token_id=token_id,
            metadata={
                "sale_price": order_data.get('amount'),
                "seller_address": seller_wallet,
                "buyer_address": buyer_wallet,
                "order_id": order_id,
                "artwork_title": artwork_doc.get("title", "Untitled"),
                "payment_method": "paypal"
            }
        )

        # Log seller action
        await UserHistoryService.log_user_action(
            user_id=seller_user_log_id,
            action="sale",
            artwork_id=artwork_id,
            artwork_token_id=token_id,
            metadata={
                "sale_price": order_data.get('amount'),
                "buyer_address": buyer_wallet,
                "order_id": order_id,
                "artwork_title": artwork_doc.get("title", "Untitled"),
                "payment_method": "paypal"
            }
        )

        # ✅ TRIGGER SELLER PAYOUT - Use order document already fetched above
        logger.info(f"🔍 Using order document with order_id: {order_id}")
        
        if not order_doc:
            logger.error(f"❌ CRITICAL: Order document not found for order_id: {order_id}")
            logger.error(f"   Payment was captured but seller payout cannot be triggered!")
            logger.error(f"   This is a critical issue - seller will not receive payment.")
        else:
            logger.info(f"✅ Order document found")
            logger.info(f"   Order type: {order_doc.get('type')}")
            logger.info(f"   Payment flow: {order_doc.get('payment_flow')}")
            logger.info(f"   Seller user ID: {order_doc.get('seller_user_id')}")
            # ✅ DEBUG: Log all creator-related fields from order_doc
            logger.info(f"🔍 Creator fields in order_doc:")
            logger.info(f"   - creator_royalty_amount: {order_doc.get('creator_royalty_amount')}")
            logger.info(f"   - creator_merchant_id: {order_doc.get('creator_merchant_id')}")
            logger.info(f"   - creator_email: {order_doc.get('creator_email')}")
            logger.info(f"   - creator_user_id: {order_doc.get('creator_user_id')}")
            logger.info(f"   - is_primary_sale: {order_doc.get('is_primary_sale')}")
            
            if order_doc.get('payment_flow') == 'platform_managed':
                # ✅ SELLER PAYOUT
                seller_email = order_doc.get('seller_email')
                seller_merchant_id = order_doc.get('seller_merchant_id')
                seller_payout_amount = order_doc.get('seller_payout_amount')
                
                logger.info(f"💰 Seller Payout Info:")
                logger.info(f"   - Merchant ID: {seller_merchant_id}")
                logger.info(f"   - Amount: ${seller_payout_amount}")
                logger.info(f"   - Email: {seller_email}")
                
                if seller_merchant_id and seller_payout_amount:
                    logger.info(f"💸 Initiating seller payout: ${seller_payout_amount} to merchant {seller_merchant_id}")
                    
                    try:
                        # ✅ Trigger payout to seller
                        payout_result = await paypal_service.payout_to_seller(
                            order_id=order_id,
                            seller_email=seller_email,
                            seller_merchant_id=seller_merchant_id,
                            amount=seller_payout_amount
                        )
                        
                        if payout_result['success']:
                            logger.info(f"✅✅✅ SELLER PAYOUT SUCCESSFUL!")
                            logger.info(f"   Payout Batch ID: {payout_result.get('payout_batch_id')}")
                            logger.info(f"   Amount: ${payout_result.get('amount')}")
                            logger.info(f"   Method: {payout_result.get('method')}")
                        else:
                            logger.error(f"❌❌❌ SELLER PAYOUT FAILED!")
                            logger.error(f"   Error: {payout_result.get('error')}")
                            logger.error(f"   Seller will NOT receive payment automatically.")
                    except Exception as payout_error:
                        logger.error(f"❌❌❌ EXCEPTION during seller payout: {payout_error}", exc_info=True)
                        logger.error(f"   Seller will NOT receive payment automatically.")
                else:
                    logger.warning(f"⚠️⚠️⚠️ MISSING SELLER PAYOUT INFO:")
                    logger.warning(f"   - Merchant ID: {seller_merchant_id} (REQUIRED)")
                    logger.warning(f"   - Amount: {seller_payout_amount} (REQUIRED)")
                    logger.warning(f"   - Email: {seller_email}")
                    if not seller_merchant_id:
                        logger.warning(f"   ⚠️ Seller must complete PayPal onboarding to receive payouts!")
                
                # ✅ CREATOR ROYALTY PAYOUT (for secondary sales only)
                creator_royalty_amount = order_doc.get('creator_royalty_amount', 0)
                creator_merchant_id = order_doc.get('creator_merchant_id')
                creator_email = order_doc.get('creator_email')
                is_primary_sale = order_doc.get('is_primary_sale', False)
                
                # ✅ DEBUG: Log creator info from order_doc
                logger.info(f"🔍 Creator Royalty Check:")
                logger.info(f"   - creator_royalty_amount: {creator_royalty_amount}")
                logger.info(f"   - creator_merchant_id: {creator_merchant_id}")
                logger.info(f"   - creator_email: {creator_email}")
                logger.info(f"   - is_primary_sale: {is_primary_sale}")
                logger.info(f"   - Condition check: creator_royalty_amount > 0 ({creator_royalty_amount > 0}) AND not is_primary_sale ({not is_primary_sale}) = {creator_royalty_amount > 0 and not is_primary_sale}")
                
                if creator_royalty_amount > 0 and not is_primary_sale:
                    logger.info(f"🎨 Creator Royalty Payout Info:")
                    logger.info(f"   - Merchant ID: {creator_merchant_id}")
                    logger.info(f"   - Amount: ${creator_royalty_amount}")
                    logger.info(f"   - Email: {creator_email}")
                    
                    if creator_merchant_id and creator_royalty_amount:
                        logger.info(f"💸 Initiating creator royalty payout: ${creator_royalty_amount} to merchant {creator_merchant_id}")
                        
                        try:
                            # ✅ Trigger payout to creator
                            creator_payout_result = await paypal_service.payout_to_seller(
                                order_id=f"{order_id}_creator_royalty",
                                seller_email=creator_email,
                                seller_merchant_id=creator_merchant_id,
                                amount=creator_royalty_amount
                            )
                            
                            if creator_payout_result['success']:
                                logger.info(f"✅✅✅ CREATOR ROYALTY PAYOUT SUCCESSFUL!")
                                logger.info(f"   Payout Batch ID: {creator_payout_result.get('payout_batch_id')}")
                                logger.info(f"   Amount: ${creator_payout_result.get('amount')}")
                                logger.info(f"   Method: {creator_payout_result.get('method')}")
                                
                                # Update order document
                                await paypal_orders_collection.update_one(
                                    {"paypal_order_id": order_id},
                                    {"$set": {
                                        "creator_payout_status": "completed",
                                        "creator_payout_batch_id": creator_payout_result.get('payout_batch_id'),
                                        "updated_at": datetime.utcnow()
                                    }}
                                )
                            else:
                                logger.error(f"❌❌❌ CREATOR ROYALTY PAYOUT FAILED!")
                                logger.error(f"   Error: {creator_payout_result.get('error')}")
                                logger.error(f"   Creator will NOT receive royalty automatically.")
                                
                                # Update order document
                                await paypal_orders_collection.update_one(
                                    {"paypal_order_id": order_id},
                                    {"$set": {
                                        "creator_payout_status": "failed",
                                        "creator_payout_error": creator_payout_result.get('error'),
                                        "updated_at": datetime.utcnow()
                                    }}
                                )
                        except Exception as creator_payout_error:
                            logger.error(f"❌❌❌ EXCEPTION during creator royalty payout: {creator_payout_error}", exc_info=True)
                            logger.error(f"   Creator will NOT receive royalty automatically.")
                    else:
                        logger.warning(f"⚠️⚠️⚠️ MISSING CREATOR ROYALTY PAYOUT INFO:")
                        logger.warning(f"   - Merchant ID: {creator_merchant_id} (REQUIRED)")
                        logger.warning(f"   - Amount: {creator_royalty_amount} (REQUIRED)")
                        logger.warning(f"   - Email: {creator_email}")
                        if not creator_merchant_id:
                            logger.warning(f"   ⚠️ Creator must complete PayPal onboarding to receive royalties!")
                elif is_primary_sale:
                    logger.info(f"💰 Primary sale - No creator royalty (seller is creator)")
                else:
                    logger.info(f"💰 No creator royalty for this sale")
            else:
                logger.warning(f"⚠️ Order payment_flow is not 'platform_managed': {order_doc.get('payment_flow')}")
                logger.warning(f"   Payout will not be triggered for this order type.")

        # ✅ LOG TRANSACTION for artist earnings dashboard (PayPal Sale)
        try:
            db_transactions = get_transaction_collection()
            
            sale_transaction = {
                "transaction_hash": order_id,
                "token_id": token_id,
                "artwork_id": artwork_id,
                "from_user_id": buyer_user_id,
                "from_address": buyer_wallet,
                "to_user_id": seller_user_id,
                "to_address": seller_wallet,
                "transaction_type": TransactionType.SALE.value,
                "status": TransactionStatus.CONFIRMED.value,
                "value": str(order_data.get('amount') or "0"), # Sale price
                "currency": "USD",
                "created_at": datetime.utcnow(),
                "payment_method": "paypal",
                "network": artwork_doc.get("network")
            }
            await db_transactions.insert_one(sale_transaction)
            logger.info(f"✅ SALE (PayPal) transaction logged for ticket {token_id}")
        except Exception as log_error:
            logger.error(f"⚠️ Failed to log PayPal sale transaction: {log_error}")

        return {
            "success": True,
            "message": "PayPal sale confirmed successfully",
            "new_owner": buyer_wallet,
            "token_id": token_id,
            "artwork_id": artwork_id,
            "order_id": order_id,
            "payment_method": "paypal"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"PayPal sale confirmation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"PayPal sale confirmation failed: {str(e)}")
    
@router.post("/migrate/missing-fields")
async def migrate_missing_fields():
    """Migration endpoint to add missing creator_id and owner_id to existing tickets - NO AUTH REQUIRED"""
    try:
        artworks_collection = get_artwork_collection()
        users_collection = get_user_collection()
        
        # Find tickets missing creator_id or owner_id
        artworks_to_migrate = await artworks_collection.find({
            "$or": [
                {"creator_id": {"$exists": False}},
                {"owner_id": {"$exists": False}}
            ]
        }).to_list(length=None)
        
        migrated_count = 0
        
        for ticket in artworks_to_migrate:
            try:
                update_data = {}
                
                # Try to find creator user by wallet address
                if "creator_id" not in ticket and ticket.get("creator_address"):
                    creator_user = await users_collection.find_one({
                        "wallet_address": ticket["creator_address"].lower()
                    })
                    if creator_user:
                        update_data["creator_id"] = str(creator_user.get("_id", ""))
                
                # Try to find owner user by wallet address  
                if "owner_id" not in ticket and ticket.get("owner_address"):
                    owner_user = await users_collection.find_one({
                        "wallet_address": ticket["owner_address"].lower()
                    })
                    if owner_user:
                        update_data["owner_id"] = str(owner_user.get("_id", ""))
                
                # If we found any updates, apply them
                if update_data:
                    await artworks_collection.update_one(
                        {"_id": ticket["_id"]},
                        {"$set": update_data}
                    )
                    migrated_count += 1
                    logger.info(f"Migrated ticket {ticket.get('token_id')}: {update_data}")
                    
            except Exception as e:
                logger.error(f"Failed to migrate ticket {ticket.get('_id')}: {e}")
                continue
        
        return {
            "success": True,
            "message": f"Migration completed. Updated {migrated_count} tickets.",
            "migrated_count": migrated_count,
            "total_processed": len(artworks_to_migrate)
        }
        
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise HTTPException(status_code=500, detail=f"Migration failed: {str(e)}")


#✅ 1. GET ALL GLOBAL SETTINGS
@router.get("/settings/global")
async def get_global_settings():
    """Get all global configuration settings (Fee, Payment Methods)"""
    try:
        db = get_db()
        settings = await db.system_settings.find_one({"_id": "global_settings"})
        
        # Default values if database is empty
        if not settings:
            return {
                "platform_fee": 2.5,
                "enable_crypto": True,
                "enable_paypal": True
            }
            
        return {
            "platform_fee": settings.get("default_platform_fee_percentage", 2.5),
            "enable_crypto": settings.get("enable_crypto", True),
            "enable_paypal": settings.get("enable_paypal", True)
        }
    except Exception as e:
        logger.error(f"Error fetching global settings: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch settings")

# ✅ 2. UPDATE GLOBAL SETTINGS
@router.post("/settings/global")
async def update_global_settings(
    settings_data: dict, 
    current_user: dict = Depends(get_current_user)
):
    """Update global settings (Admin only)"""
    # Security: Ensure only admins can access this
    # if current_user.get("role") != "admin": raise HTTPException(403, detail="Admin access required")
    
    try:
        db = get_db()
        update_fields = {}
        
        # Handle Platform Fee
        if "platform_fee" in settings_data:
            update_fields["default_platform_fee_percentage"] = float(settings_data["platform_fee"])
            
        # Handle Payment Method Toggles
        if "enable_crypto" in settings_data:
            update_fields["enable_crypto"] = bool(settings_data["enable_crypto"])
            
        if "enable_paypal" in settings_data:
            update_fields["enable_paypal"] = bool(settings_data["enable_paypal"])
            
        if not update_fields:
            raise HTTPException(status_code=400, detail="No valid settings provided")
            
        # Update database (upsert=True creates it if missing)
        await db.system_settings.update_one(
            {"_id": "global_settings"},
            {"$set": update_fields},
            upsert=True
        )
        
        return {"status": "success", "message": "Settings updated successfully", "updates": update_fields}
        
    except Exception as e:
        logger.error(f"Error updating global settings: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update settings: {str(e)}")

@router.post("/admin/pause")
async def pause_contract(current_user: dict = Depends(get_current_user)):
    """Pause contract (admin only)"""
    try:
        # Check if user is admin/owner
        if not current_user.get('is_admin'):
            raise HTTPException(status_code=403, detail="Admin access required")
        
        result = await web3_service.pause_contract()
        return result
    except Exception as e:
        logger.error(f"Failed to pause contract: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/admin/unpause")
async def unpause_contract(current_user: dict = Depends(get_current_user)):
    """Unpause contract (admin only)"""
    try:
        # Check if user is admin/owner
        if not current_user.get('is_admin'):
            raise HTTPException(status_code=403, detail="Admin access required")
        
        result = await web3_service.unpause_contract()
        return result
    except Exception as e:
        logger.error(f"Failed to unpause contract: {e}")
        raise HTTPException(status_code=500, detail=str(e))