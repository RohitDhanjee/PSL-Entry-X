import asyncio
from typing import Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime, timedelta

@dataclass
class LicenseFeeCalculation:
    license_type: str
    pricing_mode: str
    artwork_price_eth: float
    license_percentage: float
    platform_fee_eth: float
    total_amount_eth: float
    license_fee_wei: str
    total_amount_wei: str
    duration_days: int
    start_date: datetime
    end_date: datetime
    calculation_method: str

class MockConfig:
    def __init__(self):
        self.personal_use_percentage = 10.0
        self.non_commercial_percentage = 20.0
        self.commercial_percentage = 30.0
        self.extended_commercial_percentage = 50.0
        self.exclusive_percentage = 100.0
        self.responsible_use_percentage = 25.0
        self.artwork_ownership_percentage = 200.0
        self.custom_percentage = 10.0
        self.responsible_use_fee_eth = 0.005
        self.license_duration_days = 30

async def calculate_license_fees_logic(
    license_type: str,
    artwork_price_eth: float,
    config: MockConfig,
    responsible_use_addon: Optional[dict] = None,
    platform_fee_percentage: float = 2.5
) -> LicenseFeeCalculation:
    # This mimics the logic in license_config_service.py
    perc_map = {
        "PERSONAL_USE": config.personal_use_percentage,
        "NON_COMMERCIAL": config.non_commercial_percentage,
        "COMMERCIAL": config.commercial_percentage,
        "EXTENDED_COMMERCIAL": config.extended_commercial_percentage,
        "EXCLUSIVE": config.exclusive_percentage,
        "RESPONSIBLE_USE": config.responsible_use_percentage,
        "ARTWORK_OWNERSHIP": config.artwork_ownership_percentage,
        "CUSTOM": config.custom_percentage
    }
    
    perc = perc_map.get(license_type, 0.0)
    license_fee_eth = (artwork_price_eth * perc) / 100
    
    addon_fee_eth = 0.0
    if responsible_use_addon and responsible_use_addon.get("enabled") and license_type != "RESPONSIBLE_USE":
        addon_fee_eth = responsible_use_addon.get("fee_eth", config.responsible_use_fee_eth)
        
    final_license_fee_eth = license_fee_eth + addon_fee_eth
    platform_fee_eth = (artwork_price_eth * platform_fee_percentage) / 100
    total_amount_eth = final_license_fee_eth + platform_fee_eth
    
    return LicenseFeeCalculation(
        license_type=license_type,
        pricing_mode="percentage_based",
        artwork_price_eth=artwork_price_eth,
        license_percentage=perc,
        platform_fee_eth=platform_fee_eth,
        total_amount_eth=total_amount_eth,
        license_fee_wei="0",
        total_amount_wei="0",
        duration_days=config.license_duration_days,
        start_date=datetime.utcnow(),
        end_date=datetime.utcnow() + timedelta(days=config.license_duration_days),
        calculation_method="test"
    )

async def test_pricing_calculations():
    print("Testing License Pricing Calculations (Standalone Logic)...")
    config = MockConfig()
    artwork_price = 1.0
    
    test_cases = [
        ("PERSONAL_USE", 0.1, False),
        ("COMMERCIAL", 0.3, False),
        ("EXCLUSIVE", 1.0, False),
        ("PERSONAL_USE", 0.105, True),
    ]
    
    for license_type, expected_fee, use_addon in test_cases:
        addon_dict = {"enabled": True} if use_addon else None
        calc = await calculate_license_fees_logic(license_type, artwork_price, config, addon_dict)
        actual_license_component = calc.total_amount_eth - calc.platform_fee_eth
        
        status = "PASS" if abs(actual_license_component - expected_fee) < 0.0001 else "FAIL"
        print(f"[{status}] Type: {license_type:18} | Addon: {str(use_addon):5} | Expected: {expected_fee:.4f} | Actual: {actual_license_component:.4f}")

    print("\nTest complete.")

if __name__ == "__main__":
    asyncio.run(test_pricing_calculations())
