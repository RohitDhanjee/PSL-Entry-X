"""
License Access Service

Service for managing license-based access control for artwork images.
Handles license verification, expiry checking, and access level determination.
"""

from typing import Optional, Dict, Any, Tuple, Union
from datetime import datetime, timedelta
import logging
from bson import ObjectId

from app.db.database import get_license_collection, get_artwork_collection, get_user_collection
from app.utils.artwork import resolve_artwork_identifier

logger = logging.getLogger(__name__)

# Access level constants
ACCESS_OWNER = "OWNER"
ACCESS_FULL = "FULL_ACCESS"
ACCESS_WATERMARK = "ACCESS_WITH_WM"
ACCESS_LINK_ONLY = "LINK_ONLY"
ACCESS_NONE = "NO_ACCESS"
ACCESS_EXPIRED = "EXPIRED"

# Watermark text
WATERMARK_TEXT = "PSL Entry X protected"


from app.core.license_permissions import PERMISSIONS_MATRIX, LicenseType, get_permissions

class LicenseAccessService:
    """Service for checking license-based access to artworks"""
    
    @staticmethod
    async def get_user_license_for_artwork(
        user_id: str, 
        artwork_identifier: Union[int, str],
        wallet_address: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get the best active license for a user on a specific artwork.
        Returns the highest-tier license if multiple exist.
        """
        try:
            db_licenses = get_license_collection()
            
            or_conditions = []
            if user_id:
                or_conditions.append({"buyer_id": user_id})
                if ObjectId.is_valid(user_id):
                    or_conditions.append({"buyer_id": str(ObjectId(user_id))})
            
            if wallet_address:
                or_conditions.append({"buyer_address": wallet_address.lower()})
            
            if not or_conditions:
                return None
            
            # Resolve artwork to get both token_id and _id if available
            artwork = await resolve_artwork_identifier(artwork_identifier)
            if not artwork:
                return None
            
            token_id = artwork.get("token_id")
            artwork_id = str(artwork.get("_id"))
            
            query = {
                "$or": [
                    {"token_id": token_id},
                    {"artwork_id": artwork_id}
                ],
                "$and": [{"$or": or_conditions}]
            }
            
            licenses = await db_licenses.find(query).to_list(length=100)
            if not licenses:
                return None
            
            # Filter and Sort by Priority
            # Priority: Based on permissions (access_to_original > watermarked > link)
            def get_priority(lic):
                lt_str = lic.get("license_type", "PERSONAL_USE")
                try:
                    lt = LicenseType(lt_str)
                    perms = get_permissions(lt)
                    score = 0
                    if perms.access_to_original: score += 10
                    if not perms.watermarked_preview_only: score += 5
                    if perms.commercial_use_allowed: score += 20
                    return score
                except ValueError:
                    return 0

            valid_licenses = []
            for lic in licenses:
                if lic.get("is_active", False):
                    if not LicenseAccessService.is_license_expired(lic):
                        valid_licenses.append(lic)
            
            if not valid_licenses:
                for lic in licenses:
                    if LicenseAccessService.is_license_expired(lic):
                        lic["_is_expired"] = True
                        return lic
                return None
            
            valid_licenses.sort(key=get_priority, reverse=True)
            return valid_licenses[0]
            
        except Exception as e:
            logger.error(f"Error getting user license for artwork: {e}", exc_info=True)
            return None
    
    @staticmethod
    def is_license_expired(license_doc: Dict[str, Any]) -> bool:
        """Check if a license has expired."""
        try:
            end_date = license_doc.get("end_date")
            if end_date:
                if isinstance(end_date, str):
                    end_date = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                return datetime.utcnow() > end_date
            
            start = license_doc.get("purchase_time") or license_doc.get("start_date") or license_doc.get("created_at")
            duration = license_doc.get("duration_days", 30)
            
            if start:
                if isinstance(start, str):
                    start = datetime.fromisoformat(start.replace('Z', '+00:00'))
                elif isinstance(start, datetime):
                    pass
                else:
                    return False
                end_date = start + timedelta(days=duration)
                return datetime.utcnow() > end_date
            
            return False
        except Exception as e:
            logger.error(f"Error checking license expiry: {e}")
            return False
    
    @staticmethod
    async def is_artwork_owner(
        user_id: str,
        artwork_identifier: Union[int, str],
        wallet_address: Optional[str] = None
    ) -> bool:
        """Check if user is the owner or original creator of the artwork."""
        try:
            artwork = await resolve_artwork_identifier(artwork_identifier)
            if not artwork:
                return False
            
            # ID match
            if user_id:
                u_id = str(user_id)
                if str(artwork.get("owner_id")) == u_id or str(artwork.get("creator_id")) == u_id:
                    return True
            
            # Wallet match
            if wallet_address:
                w_addr = wallet_address.lower()
                if (artwork.get("owner_address") or "").lower() == w_addr:
                    return True
                if (artwork.get("creator_address") or "").lower() == w_addr:
                    return True
                    
            return False
        except Exception as e:
            logger.error(f"Error checking ownership: {e}")
            return False
    
    @staticmethod
    async def get_access_level(
        user_id: Optional[str],
        artwork_identifier: Union[int, str],
        wallet_address: Optional[str] = None
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        """
        Determine the effective access level.
        Returns Tuple of (effective_level, license_doc)
        effective_level is mapping back to constants: OWNER, FULL_ACCESS, ACCESS_WITH_WM, LINK_ONLY, NO_ACCESS, EXPIRED
        """
        try:
            if not user_id and not wallet_address:
                return ACCESS_NONE, None
            
            if await LicenseAccessService.is_artwork_owner(user_id, artwork_identifier, wallet_address):
                return ACCESS_OWNER, None
            
            license_doc = await LicenseAccessService.get_user_license_for_artwork(
                user_id, artwork_identifier, wallet_address
            )
            
            if not license_doc:
                return ACCESS_NONE, None
            
            if license_doc.get("_is_expired") or LicenseAccessService.is_license_expired(license_doc):
                return ACCESS_EXPIRED, license_doc
            
            # Map dynamic permissions to legacy access levels for backward compatibility in frontend/DRM
            lt_str = license_doc.get("license_type", "PERSONAL_USE")
            try:
                lt = LicenseType(lt_str)
                perms = get_permissions(lt)
                
                if perms.access_to_original and not perms.watermarked_preview_only:
                    return ACCESS_FULL, license_doc
                elif not perms.watermarked_preview_only:
                    return ACCESS_FULL, license_doc
                elif not perms.access_to_original and perms.watermarked_preview_only:
                    return ACCESS_WATERMARK, license_doc
                else:
                    return ACCESS_LINK_ONLY, license_doc
            except ValueError:
                return ACCESS_LINK_ONLY, license_doc
                
        except Exception as e:
            logger.error(f"Error getting access level: {e}")
            return ACCESS_NONE, None
    
    @staticmethod
    async def verify_license_access(
        user_id: str,
        artwork_identifier: Union[int, str],
        permission_key: str, # Replaced 'required_type' with 'permission_key' (optional refactor)
        wallet_address: Optional[str] = None
    ) -> bool:
        """
        Verify if user has a specific permission.
        Args:
            permission_key: e.g., 'commercial_use_allowed', 'access_to_original', 'download_allowed'
        """
        if await LicenseAccessService.is_artwork_owner(user_id, artwork_identifier, wallet_address):
            return True
            
        license_doc = await LicenseAccessService.get_user_license_for_artwork(user_id, artwork_identifier, wallet_address)
        if not license_doc or LicenseAccessService.is_license_expired(license_doc):
            return False
            
        lt_str = license_doc.get("license_type", "PERSONAL_USE")
        try:
            lt = LicenseType(lt_str)
            perms = get_permissions(lt)
            
            # Check attribute on LicensePermissions model
            val = getattr(perms, permission_key, False)
            return bool(val)
        except (ValueError, AttributeError):
            # Fallback to legacy check if permission_key is one of the old types
            access_level, _ = await LicenseAccessService.get_access_level(user_id, token_id, wallet_address)
            hierarchy = {ACCESS_FULL: 3, ACCESS_WATERMARK: 2, ACCESS_LINK_ONLY: 1, ACCESS_NONE: 0}
            return hierarchy.get(access_level, 0) >= hierarchy.get(permission_key, 0)

# Singleton instance
license_access_service = LicenseAccessService()



# Singleton instance
license_access_service = LicenseAccessService()
