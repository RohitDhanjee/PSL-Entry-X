import asyncio
import sys
import os
from unittest.mock import MagicMock, patch

# Add the current directory to sys.path to allow imports from app
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# IMPORTANT: we need to mock things that are imported during LicenseConfigService import
# Since LicenseConfigService imports from app.db.database and app.db.models

async def test_pricing_calculations():
    print("🧪 Testing License Pricing Calculations...")
    
    # We patch the functions used INSIDE the service
    with patch('app.db.database.get_db', return_value=MagicMock()), \
         patch('app.api.v1.artwork.get_current_global_fee', return_value=2.5):
        
        from services.license_config_service import LicenseConfigService
        from app.db.models import LicenseConfig
        
        # Mock config
        config = LicenseConfig(
            name="Test Config",
            personal_use_percentage=10.0,
            non_commercial_percentage=20.0,
            commercial_percentage=30.0,
            extended_commercial_percentage=50.0,
            exclusive_percentage=100.0,
            responsible_use_percentage=25.0,
            artwork_ownership_percentage=200.0,
            custom_percentage=10.0,
            responsible_use_fee_eth=0.005, # Fixed fallback fee
            license_duration_days=30
        )
        
        artwork_price = 1.0 # 1 ETH
        
        test_cases = [
            ("PERSONAL_USE", 0.1, False), # 10% of 1.0
            ("COMMERCIAL", 0.3, False),   # 30% of 1.0
            ("EXCLUSIVE", 1.0, False),    # 100% of 1.0
            ("PERSONAL_USE", 0.105, True), # 10% + 0.005 addon
        ]
        
        for license_type, expected_fee, use_addon in test_cases:
            addon_dict = {"enabled": True} if use_addon else None
            
            calc = await LicenseConfigService.calculate_license_fees(
                license_type=license_type,
                artwork_price_eth=artwork_price,
                config=config,
                responsible_use_addon=addon_dict
            )
            
            # total_amount_eth = (license_fee + addon_fee) + platform_fee
            actual_license_component = calc.total_amount_eth - calc.platform_fee_eth
            
            status = "✅ PASS" if abs(actual_license_component - expected_fee) < 0.0001 else "❌ FAIL"
            print(f"[{status}] Type: {license_type:18} | Addon: {str(use_addon):5} | Expected: {expected_fee:.4f} | Actual: {actual_license_component:.4f}")

    print("\n🏁 Test complete.")

if __name__ == "__main__":
    asyncio.run(test_pricing_calculations())
