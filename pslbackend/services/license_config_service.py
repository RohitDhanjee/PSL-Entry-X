from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from web3 import Web3
import logging
from app.db.database import get_db
from app.db.models import LicenseConfig, LicenseFeeCalculation
from bson import ObjectId

logger = logging.getLogger(__name__)


class LicenseConfigService:
    """Service for managing license configurations and fee calculations"""
    
    @staticmethod
    async def get_active_config():
        """Get the active license configuration"""
        db = get_db()
        config_collection = db.license_configs
        
        config_doc = await config_collection.find_one({"is_active": True})
        if not config_doc:
            return await LicenseConfigService.create_default_config()
            
        if "_id" in config_doc:
            config_doc["_id"] = str(config_doc["_id"])
            
        return LicenseConfig(**config_doc)
    
    @staticmethod
    async def create_default_config():
        """Create default license configuration with all 8 types"""
        db = get_db()
        config_collection = db.license_configs
        
        default_config = LicenseConfig(
            name="Default Configuration",
            # Fixed fees (Legacy values mapped to new tiers where applicable)
            personal_use_fee_eth=0.01196,
            non_commercial_fee_eth=0.015,
            commercial_fee_eth=0.02392,
            extended_commercial_fee_eth=0.03588,
            exclusive_fee_eth=0.05,
            responsible_use_fee_eth=0.01,
            artwork_ownership_fee_eth=0.1,
            custom_fee_eth=0.0,
            
            # Percentages
            personal_use_percentage=20.0,
            non_commercial_percentage=30.0,
            commercial_percentage=70.0,
            extended_commercial_percentage=90.0,
            exclusive_percentage=150.0, 
            responsible_use_percentage=10.0, 
            artwork_ownership_percentage=200.0, 
            custom_percentage=0.0,
            
            pricing_mode="fixed",
            license_duration_days=36500,
            description="Default Phase 2 configuration with 8 license tiers"
        )
        
        # Check if default already exists
        existing = await config_collection.find_one({"name": "Default Configuration"})
        if existing:
            return LicenseConfig(**existing)
        
        result = await config_collection.insert_one(default_config.model_dump(by_alias=True))
        default_config.id = str(result.inserted_id)
        
        logger.info("Created default Phase 2 license configuration")
        return default_config

    @staticmethod
    async def get_license_prices_for_artwork(artwork_price_eth: float, responsible_use_addon: Optional[dict] = None) -> Dict[str, Any]:
        """Get license prices for all active types using consolidated logic"""
        try:
            config = await LicenseConfigService.get_active_config()
            
            from app.api.v1.ticket import get_current_global_fee
            platform_fee_percentage = await get_current_global_fee()
            
            license_types = [
                "PERSONAL_USE", "NON_COMMERCIAL", "COMMERCIAL", "EXTENDED_COMMERCIAL",
                "EXCLUSIVE", "ARTWORK_OWNERSHIP", "CUSTOM"
            ]
            
            prices = {}
            for lt in license_types:
                # Use the same consolidated calculation logic
                calc = await LicenseConfigService.calculate_license_fees(
                    lt, artwork_price_eth, config, responsible_use_addon
                )
                prices[lt] = calc.model_dump()
            
            return {
                "success": True,
                "prices": prices,
                "duration_days": config.license_duration_days,
                "platform_fee_percentage": platform_fee_percentage,
                "config_name": config.name,
                "pricing_mode": "percentage_based",
                "responsible_use_addon_active": bool(responsible_use_addon and responsible_use_addon.get("enabled"))
            }
            
        except Exception as e:
            logger.error(f"Error calculating license prices: {e}")
            raise
    
    @staticmethod
    async def calculate_license_fees(
        license_type: str,
        artwork_price_eth: Optional[float] = None,
        config: Optional[LicenseConfig] = None,
        responsible_use_addon: Optional[dict] = None
    ) -> LicenseFeeCalculation:
        """Calculate fees for a specific license type, including optional add-ons"""
        if not config:
            config = await LicenseConfigService.get_active_config()
        
        if artwork_price_eth is None or artwork_price_eth <= 0:
            artwork_price_eth = 0.0
        
        from app.api.v1.ticket import get_current_global_fee
        platform_fee_percentage = await get_current_global_fee()
        
        perc_map = {
            "PERSONAL_USE": config.personal_use_percentage,
            "NON_COMMERCIAL": config.non_commercial_percentage,
            "COMMERCIAL": config.commercial_percentage,
            "EXTENDED_COMMERCIAL": config.extended_commercial_percentage,
            "EXCLUSIVE": config.exclusive_percentage,
            "ARTWORK_OWNERSHIP": config.artwork_ownership_percentage,
            "CUSTOM": config.custom_percentage
        }
        
        perc = perc_map.get(license_type, 0.0)
        license_fee_eth = (artwork_price_eth * perc) / 100
        
        addon_fee_eth = 0.0
        if responsible_use_addon and responsible_use_addon.get("enabled"):
            if config.pricing_mode == "percentage":
                addon_fee_eth = (artwork_price_eth * config.responsible_use_percentage) / 100
            else:
                addon_fee_eth = config.responsible_use_fee_eth
            
        final_license_fee_eth = license_fee_eth + addon_fee_eth
        platform_fee_eth = (artwork_price_eth * platform_fee_percentage) / 100
        total_amount_eth = final_license_fee_eth + platform_fee_eth
        
        return LicenseFeeCalculation(
            license_type=license_type,
            pricing_mode="percentage_based",
            artwork_price_eth=artwork_price_eth,
            license_percentage=perc,
            platform_fee_eth=platform_fee_eth,
            license_fee_eth=license_fee_eth, 
            addon_fee_eth=addon_fee_eth, # ✅ Explicitly pass the addon surcharge
            total_amount_eth=total_amount_eth,
            license_fee_wei=str(Web3.to_wei(final_license_fee_eth, 'ether')),
            total_amount_wei=str(Web3.to_wei(total_amount_eth, 'ether')),
            duration_days=36500, # Perpetual override
            start_date=datetime.utcnow(),
            end_date=datetime.utcnow() + timedelta(days=config.license_duration_days),
            calculation_method=f"{perc}% of artwork price + {addon_fee_eth} ETH addon, Platform fee: {platform_fee_percentage}%"
        )
    
    @staticmethod
    async def get_all_license_prices(
        artwork_price_eth: Optional[float] = None,
        responsible_use_addon: Optional[dict] = None
    ) -> Dict[str, Any]:
        """Helper to get prices for all types"""
        config = await LicenseConfigService.get_active_config()
        license_types = [
            "PERSONAL_USE", "NON_COMMERCIAL", "COMMERCIAL", "EXTENDED_COMMERCIAL",
            "EXCLUSIVE", "ARTWORK_OWNERSHIP", "CUSTOM"
        ]
        
        prices = {}
        for lt in license_types:
            calc = await LicenseConfigService.calculate_license_fees(
                lt, artwork_price_eth, config, responsible_use_addon
            )
            prices[lt] = calc.model_dump()
            
        from app.api.v1.ticket import get_current_global_fee
        platform_fee_percentage = await get_current_global_fee()

        return {
            "success": True,
            "prices": prices,
            "duration_days": config.license_duration_days,
            "platform_fee_percentage": platform_fee_percentage,
            "config_name": config.name,
            "responsible_use_addon_active": bool(responsible_use_addon and responsible_use_addon.get("enabled"))
        }

    @staticmethod
    async def save_config(config_data: LicenseConfig) -> LicenseConfig:
        """Save a new license configuration and make it active"""
        db = get_db()
        config_collection = db.license_configs
        
        # Deactivate all existing configs if this one is active
        if config_data.is_active:
            await config_collection.update_many(
                {"is_active": True},
                {"$set": {"is_active": False, "updated_at": datetime.utcnow()}}
            )
            
        config_data.updated_at = datetime.utcnow()
        if not config_data.created_at:
            config_data.created_at = datetime.utcnow()
            
        # Prepare data for MongoDB
        data = config_data.model_dump(by_alias=True)
        # Remove ID from data to avoid immutable field error during update
        if "id" in data: del data["id"]
        if "_id" in data: del data["_id"]
        
        # If it has an ID, update it, otherwise insert
        if config_data.id:
            config_id = config_data.id
            await config_collection.update_one(
                {"_id": ObjectId(config_id) if isinstance(config_id, str) and len(config_id) == 24 else config_id},
                {"$set": data}
            )
        else:
            result = await config_collection.insert_one(data)
            config_data.id = str(result.inserted_id)
            
        logger.info(f"Saved license configuration: {config_data.name}")
        return config_data