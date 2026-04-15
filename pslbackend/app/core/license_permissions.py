from typing import Dict, List, Optional
from enum import Enum
from pydantic import BaseModel

class LicenseType(str, Enum):
    PERSONAL_USE = "PERSONAL_USE"
    NON_COMMERCIAL = "NON_COMMERCIAL"
    COMMERCIAL = "COMMERCIAL"
    EXTENDED_COMMERCIAL = "EXTENDED_COMMERCIAL"
    EXCLUSIVE = "EXCLUSIVE"
    RESPONSIBLE_USE = "RESPONSIBLE_USE"  # Note: Can be an add-on or a standalone restrictive license
    ARTWORK_OWNERSHIP = "ARTWORK_OWNERSHIP"
    CUSTOM = "CUSTOM"

class LicensePermissions(BaseModel):
    """Permissions matrix for each license type"""
    license_type: LicenseType
    display_name: str
    description: str
    
    # Commercial Rights
    commercial_use_allowed: bool = False
    revenue_generation_allowed: bool = False
    use_in_advertising: bool = False
    use_on_products: bool = False
    
    # Usage Rights
    public_display_allowed: bool = True
    modification_allowed: bool = False
    attribution_required: bool = True
    
    # Access & File Rights
    access_to_original: bool = False
    watermarked_preview_only: bool = True
    download_allowed: bool = False
    
    # Distribution Rights
    can_transfer: bool = False
    can_resale_file: bool = False
    max_buyers: int = -1  # -1 for unlimited, 1 for exclusive
    
    # Extra
    ethical_restrictions: bool = False
    territory: str = "Worldwide"
    duration_type: str = "Perpetual"  # Perpetual or Limited
    
    # Enforcement
    violation_consequence: str = "Immediate revocation and legal enforcement"

# Central Permissions Matrix
PERMISSIONS_MATRIX: Dict[LicenseType, LicensePermissions] = {
    LicenseType.PERSONAL_USE: LicensePermissions(
        license_type=LicenseType.PERSONAL_USE,
        display_name="Personal Use",
        description="For personal, non-promotional use only. No commercial rights.",
        commercial_use_allowed=False,
        revenue_generation_allowed=False,
        access_to_original=False,
        watermarked_preview_only=True,
        download_allowed=True, # Allow download of watermarked version
        max_buyers=-1
    ),
    LicenseType.NON_COMMERCIAL: LicensePermissions(
        license_type=LicenseType.NON_COMMERCIAL,
        display_name="Non-Commercial",
        description="For educational or non-profit use. No revenue generation allowed.",
        commercial_use_allowed=False,
        revenue_generation_allowed=False,
        access_to_original=True, # Grant original for educational/non-profit
        watermarked_preview_only=False,
        download_allowed=True,
        max_buyers=-1
    ),
    LicenseType.COMMERCIAL: LicensePermissions(
        license_type=LicenseType.COMMERCIAL,
        display_name="Commercial",
        description="Standard commercial use for small scale marketing or business.",
        commercial_use_allowed=True,
        revenue_generation_allowed=True,
        use_in_advertising=True,
        access_to_original=True,
        watermarked_preview_only=False,
        download_allowed=True,
        max_buyers=-1
    ),
    LicenseType.EXTENDED_COMMERCIAL: LicensePermissions(
        license_type=LicenseType.EXTENDED_COMMERCIAL,
        display_name="Extended Commercial",
        description="High-volume commercial use, products for resale, and large scale distribution.",
        commercial_use_allowed=True,
        revenue_generation_allowed=True,
        use_in_advertising=True,
        use_on_products=True,
        modification_allowed=True,
        access_to_original=True,
        watermarked_preview_only=False,
        download_allowed=True,
        max_buyers=-1
    ),
    LicenseType.EXCLUSIVE: LicensePermissions(
        license_type=LicenseType.EXCLUSIVE,
        display_name="Exclusive",
        description="Full commercial rights. Once purchased, no one else can buy a license for this ticket.",
        commercial_use_allowed=True,
        revenue_generation_allowed=True,
        use_in_advertising=True,
        use_on_products=True,
        modification_allowed=True,
        access_to_original=True,
        watermarked_preview_only=False,
        download_allowed=True,
        max_buyers=1,
        can_transfer=True
    ),
    LicenseType.RESPONSIBLE_USE: LicensePermissions(
        license_type=LicenseType.RESPONSIBLE_USE,
        display_name="Responsible Use",
        description="Includes ethical restrictions (e.g., no AI training, no harmful content).",
        ethical_restrictions=True,
        access_to_original=True,
        watermarked_preview_only=False,
        download_allowed=True,
        max_buyers=-1
    ),
    LicenseType.ARTWORK_OWNERSHIP: LicensePermissions(
        license_type=LicenseType.ARTWORK_OWNERSHIP,
        display_name="Ticket Ownership",
        description="Transfer of full ownership and copyright. Single buyer only.",
        commercial_use_allowed=True,
        revenue_generation_allowed=True,
        use_on_products=True,
        modification_allowed=True,
        access_to_original=True,
        watermarked_preview_only=False,
        download_allowed=True,
        max_buyers=1,
        can_transfer=True,
        can_resale_file=True
    ),
    LicenseType.CUSTOM: LicensePermissions(
        license_type=LicenseType.CUSTOM,
        display_name="Custom",
        description="Bespoke license terms agreed between creator and buyer.",
        max_buyers=-1 # Logic varies
    ),
}

def get_permissions(license_type: LicenseType) -> LicensePermissions:
    """Helper to get permissions for a license type"""
    return PERMISSIONS_MATRIX.get(license_type, PERMISSIONS_MATRIX[LicenseType.PERSONAL_USE])
