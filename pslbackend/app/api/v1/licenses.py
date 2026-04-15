from app.core.config import settings
from fastapi import APIRouter, Depends, HTTPException, status, Query, Form
from typing import Optional, List, Dict, Any
from services.redis_cache_service import cache
from datetime import datetime, timedelta
import json
import asyncio
import logging
import base64
import hashlib
from web3 import Web3
from bson import ObjectId
from collections import defaultdict

from app.db.database import get_license_collection, get_artwork_collection, get_db, get_user_collection, get_transaction_collection
from app.db.models import (
    LicenseCreate, License, LicenseInDB,
    LicenseListResponse, User, LicenseConfig,
    LicenseConfigCreate, LicenseConfigUpdate, LicenseFeeCalculation,
    TransactionType, TransactionStatus
)
from app.core.security import get_current_user
from app.utils.ticket import resolve_artwork_identifier
from services.web3_service import web3_service
from services.license_config_service import LicenseConfigService
from .ticket import IPFSService  

try:
    from services.paypal_service import get_paypal_service
except ModuleNotFoundError:
    class _DisabledPayPalService:
        async def create_license_purchase_order(self, *args, **kwargs):
            return {"success": False, "error": "PayPal integration is disabled in this build"}

    _paypal_fallback = _DisabledPayPalService()

    def get_paypal_service():
        return _paypal_fallback

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/licenses", tags=["licenses"])


def _ensure_wirefluid_network(network_name: Optional[str]) -> str:
    normalized = (network_name or "wirefluid").strip().lower()
    if normalized != "wirefluid":
        raise HTTPException(
            status_code=400,
            detail="Only WireFluid network is supported."
        )
    return "wirefluid"

# ==========================================
# AUTO-CLEANUP MECHANISM FOR PENDING LICENSES
# ==========================================

async def cleanup_old_pending_licenses(
    max_age_hours: int = 24,
    dry_run: bool = False
) -> dict:
    """
    Clean up old pending licenses that were never confirmed.
    
    Args:
        max_age_hours: Maximum age in hours for pending licenses (default: 24 hours)
        dry_run: If True, only count licenses without deleting (default: False)
    
    Returns:
        dict with cleanup statistics
    """
    try:
        db_licenses = get_license_collection()
        
        # Calculate cutoff time
        cutoff_time = datetime.utcnow() - timedelta(hours=max_age_hours)
        
        # Find old pending licenses
        query = {
            "status": "PENDING",
            "is_active": False,
            "created_at": {"$lt": cutoff_time}
        }
        
        # Count licenses to be cleaned
        count = await db_licenses.count_documents(query)
        
        if count == 0:
            logger.info(f"🧹 No old pending licenses found (older than {max_age_hours} hours)")
            return {
                "success": True,
                "cleaned_count": 0,
                "dry_run": dry_run,
                "max_age_hours": max_age_hours
            }
        
        if dry_run:
            logger.info(f"🧹 [DRY RUN] Would clean {count} old pending licenses (older than {max_age_hours} hours)")
            return {
                "success": True,
                "cleaned_count": count,
                "dry_run": True,
                "max_age_hours": max_age_hours
            }
        
        # Get license IDs for logging
        old_licenses = await db_licenses.find(query).to_list(length=count)
        license_ids = [lic.get("license_id") for lic in old_licenses]
        
        # Delete old pending licenses
        result = await db_licenses.delete_many(query)
        deleted_count = result.deleted_count
        
        logger.info(f"🧹 Cleaned up {deleted_count} old pending licenses (older than {max_age_hours} hours)")
        logger.info(f"   License IDs: {license_ids[:10]}{'...' if len(license_ids) > 10 else ''}")
        
        return {
            "success": True,
            "cleaned_count": deleted_count,
            "license_ids": license_ids,
            "dry_run": False,
            "max_age_hours": max_age_hours,
            "cutoff_time": cutoff_time.isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ Error cleaning up old pending licenses: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "cleaned_count": 0
        }


async def _get_current_platform_fee_percentage() -> float:
    """Fetch global platform fee percentage from system settings."""
    try:
        db = get_db()
        settings_doc = await db.system_settings.find_one({"_id": "global_settings"})
        if not settings_doc:
            return 2.5

        fee = settings_doc.get("platform_fee")
        if fee is None:
            fee = settings_doc.get("default_platform_fee_percentage", 2.5)

        return max(0.0, float(fee))
    except Exception as fee_error:
        logger.warning(f"⚠️ Failed to fetch platform fee, defaulting to 2.5%: {fee_error}")
        return 2.5


def _algorand_license_numeric_id(seed_text: str) -> int:
    """Build a JS-safe deterministic integer license id for Algorand flows."""
    seed = str(seed_text or "").strip()
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    # 48-bit bucket keeps value JS-safe while staying deterministic.
    suffix = int.from_bytes(digest[:6], byteorder="big", signed=False)
    return 8_000_000_000_000_000 + suffix


def _normalize_license_id(raw_license_id: Any) -> int:
    """Normalize mixed legacy license ids (int/string) to int for API models."""
    if isinstance(raw_license_id, int):
        return raw_license_id

    if raw_license_id is None:
        return 0

    text = str(raw_license_id).strip()
    if not text:
        return 0

    if text.isdigit():
        return int(text)

    # Legacy Algorand IDs were stored as ALGO-<tx-prefix>.
    if text.upper().startswith("ALGO-"):
        return _algorand_license_numeric_id(text.split("-", 1)[1])

    return _algorand_license_numeric_id(text)


def _merge_algorand_payment_legs(payment_legs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge legs with same receiver so frontend signs fewer payment txns."""
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
    group_id = indexer_tx.get("group")
    if isinstance(group_id, str) and group_id.strip():
        return group_id.strip()

    nested = (((indexer_tx.get("txn") or {}).get("txn") or {}).get("grp"))
    if isinstance(nested, str) and nested.strip():
        return nested.strip()

    return None


def _to_indexer_group_id_bytes(group_id: Optional[str]) -> Optional[bytes]:
    if not group_id:
        return None

    candidate = group_id.strip()
    if not candidate:
        return None

    try:
        return base64.b64decode(candidate, validate=True)
    except Exception:
        try:
            padded = candidate + ("=" * (-len(candidate) % 4))
            return base64.b64decode(padded)
        except Exception:
            logger.warning("⚠️ Could not decode Algorand group id '%s' to bytes", candidate)
            return None


def _decode_algorand_app_arg(arg_b64: Any) -> Any:
    """Decode base64 app-arg from indexer into text/int when possible."""
    if not isinstance(arg_b64, str) or not arg_b64:
        return None

    try:
        padded = arg_b64 + ("=" * (-len(arg_b64) % 4))
        raw = base64.b64decode(padded)
    except Exception:
        return None

    if not raw:
        return ""

    try:
        decoded_text = raw.decode("utf-8")
        if decoded_text and all(31 < ord(ch) < 127 for ch in decoded_text):
            return decoded_text
    except Exception:
        pass

    if len(raw) <= 8:
        return int.from_bytes(raw, byteorder="big", signed=False)

    return raw.hex()


async def _build_algorand_license_breakdown(
    artwork_price_algo: float,
    license_percentage: float,
    owner_address: str,
    algorand_service,
) -> Dict[str, Any]:
    """Compute Algorand license payment split with buyer/seller platform fees."""
    from algosdk import encoding as algo_encoding

    artwork_price_microalgos = int(round(float(artwork_price_algo or 0) * 1_000_000))
    if artwork_price_microalgos <= 0:
        raise HTTPException(status_code=400, detail="Ticket price is invalid for Algorand licensing")

    owner_address = (owner_address or "").strip()
    if not owner_address or not algo_encoding.is_valid_address(owner_address):
        raise HTTPException(status_code=400, detail="Invalid Algorand owner address")

    license_percentage = float(license_percentage or 0)
    license_fee_microalgos = int(round((artwork_price_microalgos * license_percentage) / 100.0))
    if license_fee_microalgos <= 0:
        raise HTTPException(status_code=400, detail="Calculated Algorand license fee is invalid")

    platform_fee_percentage = await _get_current_platform_fee_percentage()
    platform_fee_basis = max(0, int(round(platform_fee_percentage * 100)))

    buyer_platform_fee_microalgos = (artwork_price_microalgos * platform_fee_basis) // 10000
    seller_platform_fee_microalgos = (artwork_price_microalgos * platform_fee_basis) // 10000

    if seller_platform_fee_microalgos >= license_fee_microalgos:
        seller_platform_fee_microalgos = license_fee_microalgos // 2

    owner_receives_microalgos = license_fee_microalgos - seller_platform_fee_microalgos
    if owner_receives_microalgos <= 0:
        raise HTTPException(
            status_code=400,
            detail="License split is invalid: owner net amount must be greater than zero",
        )

    platform_receives_microalgos = buyer_platform_fee_microalgos + seller_platform_fee_microalgos
    platform_address = (getattr(algorand_service, "platform_address", "") or "").strip()
    if platform_receives_microalgos > 0:
        if not platform_address or not algo_encoding.is_valid_address(platform_address):
            raise HTTPException(
                status_code=500,
                detail="ALGORAND_PLATFORM_ADDRESS is missing or invalid while platform fee is enabled",
            )

    payment_legs: List[Dict[str, Any]] = [
        {
            "to": owner_address,
            "amount": owner_receives_microalgos,
            "purpose": "owner_license_net",
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

    merged_legs = _merge_algorand_payment_legs(payment_legs)
    buyer_total_microalgos = sum(int(leg["amount"]) for leg in merged_legs)

    return {
        "artwork_price_microalgos": artwork_price_microalgos,
        "license_percentage": license_percentage,
        "license_fee_microalgos": license_fee_microalgos,
        "buyer_platform_fee_microalgos": buyer_platform_fee_microalgos,
        "seller_platform_fee_microalgos": seller_platform_fee_microalgos,
        "owner_receives_microalgos": owner_receives_microalgos,
        "platform_receives_microalgos": platform_receives_microalgos,
        "buyer_total_microalgos": buyer_total_microalgos,
        "platform_fee_basis_points": platform_fee_basis,
        "owner_algorand_address": owner_address,
        "platform_algorand_address": platform_address or None,
        "payment_legs": merged_legs,
    }


async def _verify_algorand_license_group(
    tx_hash: str,
    buyer_wallet: str,
    expected_breakdown: Dict[str, Any],
    expected_app_id: int,
    expected_token_id: int,
    expected_license_type: str,
    algorand_service,
) -> Dict[str, Any]:
    """Strictly verify grouped Algorand payments + app call for license purchase."""
    buyer_wallet = (buyer_wallet or "").strip().lower()
    expected_license_type = (expected_license_type or "").strip().upper()

    expected_by_receiver: Dict[str, int] = defaultdict(int)
    for leg in expected_breakdown.get("payment_legs", []):
        receiver = (leg.get("to") or "").strip()
        amount = int(leg.get("amount") or 0)
        if receiver and amount > 0:
            expected_by_receiver[receiver] += amount

    if not expected_by_receiver:
        raise HTTPException(status_code=400, detail="No expected Algorand payment legs for license verification")

    search_resp = algorand_service.indexer_client.search_transactions(txid=tx_hash, limit=1)
    txns = search_resp.get("transactions", []) if isinstance(search_resp, dict) else []
    if not txns:
        raise HTTPException(status_code=400, detail="Algorand license transaction not found in indexer")

    anchor_tx = txns[0]
    confirmed_round = int(anchor_tx.get("confirmed-round") or 0)
    if confirmed_round <= 0:
        raise HTTPException(status_code=400, detail="Algorand license transaction is not confirmed yet")

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
            detail="Algorand license payment verification failed: " + " | ".join(detail_chunks),
        )

    expected_total = int(expected_breakdown.get("buyer_total_microalgos") or 0)
    actual_total = sum(actual_by_receiver.values())
    if expected_total != actual_total:
        raise HTTPException(
            status_code=400,
            detail=(
                "Algorand license payment total mismatch: "
                f"expected {expected_total} microalgos, got {actual_total} microalgos"
            ),
        )

    app_call_verified = False
    for txn in grouped_transactions:
        if txn.get("tx-type") != "appl":
            continue

        app_tx = txn.get("application-transaction", {}) if isinstance(txn, dict) else {}
        app_id = int(app_tx.get("application-id") or 0)
        if app_id != int(expected_app_id):
            continue

        app_args = app_tx.get("application-args") or []
        if not app_args:
            continue

        method_arg = _decode_algorand_app_arg(app_args[0])
        if str(method_arg) != "purchase_license":
            continue

        token_ok = True
        license_type_ok = True

        if len(app_args) > 1:
            token_arg = _decode_algorand_app_arg(app_args[1])
            try:
                token_ok = int(token_arg) == int(expected_token_id)
            except Exception:
                token_ok = False

        if len(app_args) > 2:
            license_type_arg = _decode_algorand_app_arg(app_args[2])
            license_type_ok = str(license_type_arg or "").upper() == expected_license_type

        if token_ok and license_type_ok:
            app_call_verified = True
            break

    if not app_call_verified:
        raise HTTPException(
            status_code=400,
            detail="Algorand app call verification failed: expected purchase_license call not found in transaction group",
        )

    return {
        "group_id": group_id,
        "confirmed_round": confirmed_round,
        "actual_total_microalgos": actual_total,
        "expected_total_microalgos": expected_total,
    }


class LicenseDocumentService:
    """Service to generate and upload license documents to IPFS"""

    @staticmethod
    def generate_license_document(
        artwork_title: str,
        artwork_token_id: int,
        licensor_address: str,
        licensee_address: str,
        license_type: str,
        duration_days: int,
        start_date: datetime
    ) -> dict:
        end_date = start_date + timedelta(days=duration_days)

        license_document = {
            "license_agreement": {
                "title": f"Ticket License Agreement - {artwork_title}",
                "ticket": {
                    "title": artwork_title,
                    "token_id": artwork_token_id,
                    "blockchain": "Ethereum Sepolia"
                },
                "parties": {
                    "licensor": {
                        "wallet_address": licensor_address,
                        "role": "Ticket Owner & Rights Grantor"
                    },
                    "licensee": {
                        "wallet_address": licensee_address,
                        "role": "License Holder"
                    }
                },
                "license_terms": {
                    "type": license_type,
                    "duration": {
                        "start_date": start_date.isoformat(),
                        "end_date": end_date.isoformat(),
                        "duration_days": duration_days
                    },
                    "permissions": LicenseDocumentService.get_permissions_by_type(license_type),
                    "restrictions": LicenseDocumentService.get_restrictions_by_type(license_type),
                    "attribution_required": license_type in ["NON_COMMERCIAL", "RESPONSIBLE_USE"] # Matches "Often" and "May be" in Table 1
                },
                "terms_and_conditions": {
                    "usage_rights": LicenseDocumentService.get_usage_rights(license_type),
                    "termination": "This license automatically expires on the end date or can be revoked by the licensor.",
                    "governing_law": "This agreement is governed by blockchain smart contract terms.",
                    "dispute_resolution": "Disputes will be resolved according to the platform's terms of service."
                },
                "technical_details": {
                    "blockchain": "Ethereum",
                    "network": "Sepolia Testnet",
                    "license_fee": "0.1 ETH",
                    "created_at": datetime.utcnow().isoformat(),
                    "document_version": "1.0"
                }
            }
        }
        return license_document

    @staticmethod
    def get_permissions_by_type(license_type: str) -> list:
        permissions = {
            "PERSONAL_USE": [
                "View and display the ticket for personal use",
                "Share the ticket in personal social media with attribution",
                "Use as desktop wallpaper or personal device backgrounds"
            ],
            "NON_COMMERCIAL": [
                "Use in educational, non-profit or news projects",
                "Public display in non-commercial settings",
                "Personal and educational usage rights"
            ],
            "COMMERCIAL": [
                "Use in commercial projects and marketing materials",
                "Include in commercial websites and applications",
                "Use for promotional purposes with proper attribution",
                "Standard commercial usage rights"
            ],
            "EXTENDED_COMMERCIAL": [
                "High-volume commercial use and distribution",
                "Use on products for resale (merchandise)",
                "Full commercial marketing and advertising rights",
                "Right to modify work for commercial applications"
            ],
            "EXCLUSIVE": [
                "Exclusive rights to all uses of the ticket",
                "Commercial and non-commercial usage rights",
                "Right to sublicense to third parties",
                "Exclusive access during the license period"
            ],
            "RESPONSIBLE_USE": [
                "Ethical usage only (no harmful content, no AI training)",
                "Includes standard usage rights with ethical restrictions",
                "Verification of intended use case required"
            ],
            "ARTWORK_OWNERSHIP": [
                "Transfer of full ownership and copyright",
                "Unlimited commercial and personal usage rights",
                "Right to modify, redistribute, and resell the digital file",
                "Complete IP transfer to the licensee"
            ],
            "CUSTOM": [
                "Individually negotiated rights and permissions",
                "Specific terms defined in the custom agreement"
            ]
        }
        return permissions.get(license_type, [])

    @staticmethod
    def get_restrictions_by_type(license_type: str) -> list:
        restrictions = {
            "PERSONAL_USE": [
                "No commercial use permitted",
                "Cannot republish or redistribute as own",
                "Cannot claim ownership of the original work"
            ],
            "NON_COMMERCIAL": [
                "No revenue generation allowed",
                "Cannot use for advertising or promotion of for-profit entities",
                "Must provide proper attribution to the creator"
            ],
            "COMMERCIAL": [
                "Must provide proper attribution",
                "Cannot claim ownership of the original work",
                "No use on products for resale without Extended License"
            ],
            "EXTENDED_COMMERCIAL": [
                "Cannot claim original authorship",
                "Cannot register trademarks using the ticket directly"
            ],
            "EXCLUSIVE": [
                "Other parties cannot use the ticket during license period",
                "Licensee is responsible for protecting exclusivity"
            ],
            "RESPONSIBLE_USE": [
                "No use in AI model training or data sets",
                "No use in political, religious, or sensitive campaigns",
                "No use in content promoting hate or discrimination"
            ],
            "ARTWORK_OWNERSHIP": [
                "Limited by previous non-exclusive licenses granted",
                "Subject to agreed digital transfer protocols"
            ],
            "CUSTOM": [
                "Restricted by the specific terms of the custom agreement"
            ]
        }
        return restrictions.get(license_type, [])

    @staticmethod
    def get_usage_rights(license_type: str) -> str:
        usage_descriptions = {
            "PERSONAL_USE": "This license grants personal, non-commercial usage rights only. The licensee may view, display, and share the ticket for personal purposes with proper attribution.",
            "NON_COMMERCIAL": "This license grants rights for educational or non-profit purposes. Commercial use or revenue generation is strictly prohibited.",
            "COMMERCIAL": "This license grants standard commercial usage rights including marketing, advertising, and business applications. Attribution to the original creator is required.",
            "EXTENDED_COMMERCIAL": "This license grants unlimited commercial rights, including high-volume distribution and the right to use the ticket on products for resale.",
            "EXCLUSIVE": "This license grants exclusive rights to the ticket. No other licenses will be granted, and the licensee has full commercial and non-commercial usage rights.",
            "RESPONSIBLE_USE": "This license is subject to ethical usage restrictions. It prohibits use in AI training, harmful content, or sensitive political/religious contexts.",
            "ARTWORK_OWNERSHIP": "This license represents a full transfer of copyright and digital ownership. The licensee gains all intellectual property rights to the ticket.",
            "CUSTOM": "Usage rights for this license are bespoke and defined in the individually negotiated agreement between creator and licensee."
        }
        return usage_descriptions.get(license_type, "Standard usage rights apply.")


# @router.post("/grant-with-document")
# async def grant_license_with_document(
#     token_id: int = Form(...),
#     licensee_address: str = Form(...),
#     duration_days: int = Form(...),
#     license_type: str = Form(...),
#     current_user: dict = Depends(get_current_user)
# ):
#     try:
#         db_licenses = get_license_collection()
#         db_artworks = get_artwork_collection()

#         if not 1 <= duration_days <= 365:
#             raise HTTPException(status_code=400, detail="Duration must be between 1 and 365 days")

#         if license_type not in ["PERSONAL", "COMMERCIAL", "EXCLUSIVE"]:
#             raise HTTPException(status_code=400, detail="Invalid license type")

#         try:
#             licensee_address = Web3.to_checksum_address(licensee_address)
#         except Exception:
#             raise HTTPException(status_code=400, detail="Invalid Ethereum address")

#         artwork_doc = await db_artworks.find_one({"token_id": token_id}, sort=[("_id", -1)])
#         if not artwork_doc:
#             raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

#         # FIX: Handle current_user as dict
#         user_wallet = current_user.get('wallet_address')
#         if not user_wallet:
#             logger.error(f"Invalid current_user structure: {current_user}")
#             raise HTTPException(status_code=500, detail="User authentication error")

#         if artwork_doc["owner_address"].lower() != user_wallet.lower():
#             raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only ticket owner can grant licenses")

#         start_date = datetime.utcnow()
#         license_document = LicenseDocumentService.generate_license_document(
#             artwork_title=artwork_doc.get("title", "Untitled"),
#             artwork_token_id=token_id,
#             licensor_address=user_wallet,
#             licensee_address=licensee_address,
#             license_type=license_type,
#             duration_days=duration_days,
#             start_date=start_date
#         )

#         document_json = json.dumps(license_document, indent=2)
#         document_bytes = document_json.encode('utf-8')

#         terms_hash = await IPFSService.upload_to_ipfs(
#             document_bytes,
#             f"license_agreement_{token_id}_{int(start_date.timestamp())}.json"
#         )

#         license_count = await db_licenses.count_documents({}) + 1

#         max_retries = 3
#         tx_data = None
#         for attempt in range(max_retries):
#             try:
#                 tx_data = await web3_service.prepare_license_transaction(
#                     token_id,
#                     licensee_address,
#                     duration_days,
#                     terms_hash,
#                     license_type,
#                     user_wallet
#                 )
#                 break
#             except Exception as e:
#                 if attempt == max_retries - 1:
#                     raise e
#                 logger.warning(f"Attempt {attempt + 1} failed, retrying: {e}")
#                 await asyncio.sleep(1)

#         if not tx_data:
#             raise HTTPException(status_code=500, detail="Failed to prepare transaction after multiple attempts")

#         end_date = start_date + timedelta(days=duration_days)
#         fee_eth = 0.1  # Fixed fee

#         license_dict = {
#             "license_id": license_count,
#             "token_id": token_id,
#             "licensee_address": licensee_address.lower(),
#             "licensor_address": user_wallet.lower(),
#             "start_date": start_date,
#             "end_date": end_date,
#             "terms_hash": terms_hash,
#             "license_type": license_type,
#             "is_active": True,
#             "fee_paid": fee_eth,
#             "created_at": datetime.utcnow(),
#             "updated_at": datetime.utcnow(),
#             "transaction_data": tx_data
#         }

#         license_doc = LicenseInDB.from_mongo(license_dict)
#         result = await db_licenses.insert_one(license_doc.model_dump(by_alias=True, exclude={"id"}))

#         logger.info(f"Created license document with ID: {result.inserted_id}")

#         await db_artworks.update_one(
#             {"token_id": token_id},
#             {"$set": {"is_licensed": True, "updated_at": datetime.utcnow()}}
#         )

#         return {
#             "success": True,
#             "license_id": license_count,
#             "transaction_data": tx_data,
#             "terms_hash": terms_hash,
#             "license_document_preview": license_document["license_agreement"],
#             "fee": fee_eth
#         }

#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error granting license with document: {e}", exc_info=True)
#         raise HTTPException(status_code=500, detail=f"Failed to grant license: {str(e)}")

# @router.post("/purchase")
# async def purchase_license(
#     token_id: int = Form(...),
#     license_type: str = Form(...),
#     current_user: dict = Depends(get_current_user)
# ):
#     """Purchase a license for an ticket using the new contract structure"""
#     try:
#         db_licenses = get_license_collection()
#         db_artworks = get_artwork_collection()

#         # Validate license type
#         if license_type not in ["LINK_ONLY", "ACCESS_WITH_WM", "FULL_ACCESS"]:
#             raise HTTPException(status_code=400, detail="Invalid license type")

#         try:
#             buyer_address = Web3.to_checksum_address(current_user.get("wallet_address"))
#         except Exception:
#             raise HTTPException(status_code=400, detail="Invalid buyer address")

#         # ✅ Get ticket info and price
#         artwork_doc = await db_artworks.find_one({"token_id": token_id}, sort=[("_id", -1)])
#         if not artwork_doc:
#             raise HTTPException(status_code=404, detail="Ticket not found")
        
#         # ✅ Get ticket price
#         artwork_price_eth = artwork_doc.get('price', 0.0)
#         if not artwork_price_eth or artwork_price_eth <= 0:
#             raise HTTPException(status_code=400, detail="Ticket price not set")

#         # Get ticket owner from blockchain
#         owner_address = await web3_service.get_artwork_owner(token_id)
#         if not owner_address:
#             raise HTTPException(status_code=404, detail="Could not determine ticket owner")

#         # Prevent self-purchase
#         if buyer_address.lower() == owner_address.lower():
#             raise HTTPException(status_code=400, detail="Cannot purchase license for your own ticket")

#         # ✅ Get license percentage from config
#         from services.license_config_service import LicenseConfigService
#         config = await LicenseConfigService.get_active_config()
        
#         license_percentages = {
#             "LINK_ONLY": config.link_only_percentage,  # 20%
#             "ACCESS_WITH_WM": config.watermark_percentage,  # 70%
#             "FULL_ACCESS": config.full_access_percentage  # 90%
#         }
#         license_percentage = license_percentages.get(license_type, 20.0)

#         # ✅ Calculate license fee from ticket price × license percentage
#         artwork_price_wei = Web3.to_wei(artwork_price_eth, 'ether')
#         license_fee_wei = (artwork_price_wei * int(license_percentage * 100)) // 10000

#         # ✅ Calculate platform fees from ticket price × platform fee percentage
#         from app.api.v1.ticket import get_current_global_fee
#         platform_fee_percentage = await get_current_global_fee()
#         platform_fee_basis = int(platform_fee_percentage * 100)
        
#         buyer_platform_fee_wei = (artwork_price_wei * platform_fee_basis) // 10000
#         seller_platform_fee_wei = (artwork_price_wei * platform_fee_basis) // 10000
#         total_required_wei = license_fee_wei + buyer_platform_fee_wei

#         logger.info(f"💰 License purchase calculation:")
#         logger.info(f"   Ticket Price: {artwork_price_eth} ETH")
#         logger.info(f"   License Type: {license_type} ({license_percentage}%)")
#         logger.info(f"   License Fee: {Web3.from_wei(license_fee_wei, 'ether')} ETH")
#         logger.info(f"   Buyer Platform Fee: {Web3.from_wei(buyer_platform_fee_wei, 'ether')} ETH")
#         logger.info(f"   Total Required: {Web3.from_wei(total_required_wei, 'ether')} ETH")

#         # ✅ Prepare blockchain transaction with ticket price and license percentage
#         duration_days = 30  # Default duration, or get from request
#         terms_hash = ""  # Generate or get from request
        
#         try:
#             tx_data = await web3_service.prepare_license_transaction(
#                 token_id=token_id,
#                 licensee_address=buyer_address,
#                 duration_days=duration_days,
#                 terms_hash=terms_hash,
#                 license_type=license_type,
#                 from_address=buyer_address,
#                 artwork_price_eth=artwork_price_eth,  # ✅ Add this parameter
#                 license_percentage=license_percentage  # ✅ Add this parameter
#             )
#         except Exception as e:
#             logger.error(f"Failed to prepare transaction: {e}")
#             raise HTTPException(status_code=500, detail=f"Failed to prepare blockchain transaction: {str(e)}")

#         # Store license record in database
#         license_count = await db_licenses.count_documents({}) + 1
        
#         license_dict = {
#             "license_id": license_count,
#             "token_id": token_id,
#             "buyer_address": buyer_address.lower(),
#             "owner_address": owner_address.lower(),
#             "license_type": license_type,
#             "license_fee_wei": str(license_fee_wei),
#             "buyer_platform_fee_wei": str(buyer_platform_fee_wei),
#             "seller_platform_fee_wei": str(seller_platform_fee_wei),
#             "total_amount_wei": str(total_required_wei),
#             "license_fee_eth": str(Web3.from_wei(license_fee_wei, 'ether')),
#             "buyer_platform_fee_eth": str(Web3.from_wei(buyer_platform_fee_wei, 'ether')),
#             "total_amount_eth": str(Web3.from_wei(total_required_wei, 'ether')),
#             "is_active": True,
#             "purchase_time": datetime.utcnow(),
#             "created_at": datetime.utcnow(),
#             "updated_at": datetime.utcnow(),
#             "transaction_data": tx_data,
#             "status": "PENDING"
#         }

#         result = await db_licenses.insert_one(license_dict)
#         logger.info(f"Created license document with ID: {result.inserted_id}")

#         return {
#             "success": True,
#             "license_id": license_count,
#             "transaction_data": tx_data,
#             "fee_breakdown": {
#                 "artwork_price": str(artwork_price_eth),
#                 "license_percentage": license_percentage,
#                 "license_fee": str(Web3.from_wei(license_fee_wei, 'ether')),
#                 "buyer_platform_fee": str(Web3.from_wei(buyer_platform_fee_wei, 'ether')),
#                 "total_amount": str(Web3.from_wei(total_required_wei, 'ether')),
#                 "license_type": license_type
#             },
#             "artwork_info": {
#                 "token_id": token_id,
#                 "title": artwork_doc.get("title", "Untitled"),
#                 "owner_address": owner_address
#             }
#         }

#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error purchasing license: {e}", exc_info=True)
#         raise HTTPException(status_code=500, detail=f"Failed to purchase license: {str(e)}")





@router.post("/confirm-purchase")
async def confirm_license_purchase(
    confirmation_data: dict,
    current_user: dict = Depends(get_current_user)
):
    """Confirm license purchase after blockchain transaction and create/update DB record."""
    try:
        tx_hash = str(confirmation_data.get("tx_hash") or "").strip()
        artwork_id = confirmation_data.get("artwork_id")
        token_id = confirmation_data.get("token_id")  # Legacy fallback
        license_type = str(confirmation_data.get("license_type") or "").strip().upper()

        artwork_identifier = artwork_id or token_id
        if not tx_hash or not artwork_identifier or not license_type:
            raise HTTPException(
                status_code=400,
                detail="Missing tx_hash, ticket identifier, or license_type",
            )

        artwork_doc = await resolve_artwork_identifier(artwork_identifier)
        if not artwork_doc:
            raise HTTPException(status_code=404, detail="Ticket not found")

        network = _ensure_wirefluid_network(
            artwork_doc.get("network") or getattr(settings, "ACTIVE_NETWORK", "wirefluid") or "wirefluid"
        )
        is_algorand_purchase = network == "algorand"

        db_licenses = get_license_collection()
        db_artworks = get_artwork_collection()

        user_id = str(
            current_user.get("id")
            or current_user.get("_id")
            or current_user.get("user_id")
            or ""
        ).strip()
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        buyer_wallet = str(current_user.get("wallet_address") or "").strip()
        if not buyer_wallet:
            raise HTTPException(status_code=400, detail="User wallet address not found")

        token_id = int(artwork_doc.get("token_id") or 0)
        if token_id <= 0:
            raise HTTPException(status_code=400, detail="Ticket token_id is missing or invalid")

        artwork_id = str(artwork_doc.get("_id"))
        artwork_price = float(artwork_doc.get("price") or 0)
        if artwork_price <= 0:
            raise HTTPException(status_code=400, detail="Ticket price not set or invalid")

        config = await LicenseConfigService.get_active_config()
        fee_calculation = await LicenseConfigService.calculate_license_fees(
            license_type,
            artwork_price,
            config,
            responsible_use_addon=artwork_doc.get("responsible_use_addon"),
        )

        verification_meta: Dict[str, Any] = {}
        owner_address = None

        if is_algorand_purchase:
            from algosdk import encoding as algo_encoding
            from services.algorand_service import algorand_service

            if not algo_encoding.is_valid_address(buyer_wallet):
                raise HTTPException(status_code=400, detail="Invalid Algorand buyer wallet address")

            owner_address = (
                artwork_doc.get("owner_algorand_address")
                or artwork_doc.get("creator_algorand_address")
                or artwork_doc.get("owner_address")
                or artwork_doc.get("creator_address")
                or ""
            ).strip()

            asa_id = artwork_doc.get("algorand_asa_id")
            if asa_id:
                try:
                    chain_info = await algorand_service.get_asset_blockchain_info(int(asa_id))
                    if chain_info.get("success") and chain_info.get("owner"):
                        owner_address = str(chain_info.get("owner")).strip()
                except Exception as owner_fetch_error:
                    logger.warning(
                        f"⚠️ Failed to fetch live Algorand owner for ASA {asa_id} during confirm: {owner_fetch_error}"
                    )

            app_id = int(artwork_doc.get("algorand_app_id") or getattr(settings, "ALGORAND_APP_ID", 0) or 0)
            if app_id <= 0:
                raise HTTPException(status_code=500, detail="Algorand app ID is not configured")

            expected_breakdown = await _build_algorand_license_breakdown(
                artwork_price_algo=artwork_price,
                license_percentage=float(fee_calculation.license_percentage),
                owner_address=owner_address,
                algorand_service=algorand_service,
            )

            verification_meta = await _verify_algorand_license_group(
                tx_hash=tx_hash,
                buyer_wallet=buyer_wallet,
                expected_breakdown=expected_breakdown,
                expected_app_id=app_id,
                expected_token_id=token_id,
                expected_license_type=license_type,
                algorand_service=algorand_service,
            )

            buyer_address = buyer_wallet
            blockchain_license_id = _algorand_license_numeric_id(tx_hash)
            algorand_license_reference = f"ALGO-{tx_hash[:10]}"
        else:
            buyer_address = Web3.to_checksum_address(buyer_wallet)

            owner_address = await web3_service.get_artwork_owner(token_id)
            if not owner_address:
                raise HTTPException(status_code=404, detail="Could not determine ticket owner from blockchain")

            tx_receipt = await web3_service.get_transaction_receipt(tx_hash)
            if not tx_receipt:
                raise HTTPException(status_code=400, detail="Transaction not found on blockchain")
            if tx_receipt.get("status") != 1:
                raise HTTPException(status_code=400, detail="Transaction failed on blockchain")

            blockchain_license_id = await web3_service.get_license_id_from_transaction(tx_hash)
            if blockchain_license_id is None:
                raise HTTPException(
                    status_code=500,
                    detail="Failed to extract license ID from blockchain transaction",
                )

        license_id = blockchain_license_id

        license_dict = {
            "license_id": license_id,
            "artwork_id": artwork_id,
            "token_id": token_id,
            "buyer_id": user_id,
            "buyer_address": str(buyer_address).lower() if buyer_address else None,
            "owner_address": str(owner_address).lower() if owner_address else None,
            "license_type": license_type,
            "total_amount_eth": fee_calculation.total_amount_eth,
            "total_amount_wei": fee_calculation.total_amount_wei,
            "payment_method": "crypto",
            "network": network,
            "is_active": True,
            "status": "CONFIRMED",
            "transaction_hash": tx_hash,
            "purchase_time": datetime.utcnow(),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }

        if is_algorand_purchase:
            license_dict.update(
                {
                    "algorand_license_reference": algorand_license_reference,
                    "algorand_group_id": verification_meta.get("group_id"),
                    "buyer_total_microalgos": verification_meta.get("expected_total_microalgos"),
                    "confirmed_round": verification_meta.get("confirmed_round"),
                }
            )

        existing_license = await db_licenses.find_one({"license_id": license_id})
        if existing_license:
            logger.warning(f"⚠️ License {license_id} already exists. Updating existing record.")
            await db_licenses.update_one({"license_id": license_id}, {"$set": license_dict})
        else:
            await db_licenses.insert_one(license_dict)

        try:
            await db_artworks.update_one(
                {"_id": ObjectId(artwork_id)},
                {"$set": {"is_licensed": True, "updated_at": datetime.utcnow()}},
            )
        except Exception as update_error:
            logger.warning(f"⚠️ Could not set ticket is_licensed flag for {artwork_id}: {update_error}")

        # ✅ LOG TRANSACTION for artist earnings dashboard
        try:
            db_transactions = get_transaction_collection()
            
            # Find owner user ID for to_user_id mapping
            owner_user = None
            if owner_address:
                owner_user = await get_user_collection().find_one({
                    "wallet_address": {"$regex": f"^{owner_address.lower()}$", "$options": "i"}
                })
            
            to_user_id = str(owner_user.get("_id") or owner_user.get("user_id") or owner_user.get("id")) if owner_user else None

            license_transaction = {
                "transaction_hash": tx_hash,
                "token_id": token_id,
                "artwork_id": artwork_id,
                "from_user_id": user_id,
                "from_address": str(buyer_address).lower() if buyer_address else None,
                "to_user_id": to_user_id,
                "to_address": str(owner_address).lower() if owner_address else None,
                "transaction_type": TransactionType.LICENSE_PAYMENT.value,
                "status": TransactionStatus.CONFIRMED.value,
                "value": str(fee_calculation.total_amount_eth),
                "currency": "ALGO" if is_algorand_purchase else "ETH",
                "created_at": datetime.utcnow(),
                "network": network,
                "payment_method": "crypto"
            }
            await db_transactions.insert_one(license_transaction)
            logger.info(f"✅ LICENSE_PAYMENT transaction logged for ticket {token_id}")
        except Exception as log_error:
            logger.error(f"⚠️ Failed to log license transaction: {log_error}")

        return {
            "success": True,
            "message": "License purchase confirmed successfully",
            "license_id": license_id,
            "transaction_hash": tx_hash,
            "license_status": "CONFIRMED",
            "network": network,
            "verification": verification_meta if is_algorand_purchase else {"success": True},
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error confirming license purchase: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to confirm license purchase: {str(e)}")


# ✅ NEW: License access check endpoint
@router.get("/access/{artwork_identifier}")
async def check_license_access(
    artwork_identifier: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Check user's license access level for a specific ticket.
    
    Returns:
        - access_level: OWNER, FULL_ACCESS, ACCESS_WITH_WM, LINK_ONLY, NO_ACCESS, or EXPIRED
        - license_info: License details if user has a license
        - content_url: URL to access content based on license type
    """
    from services.license_access_service import (
        LicenseAccessService, 
        ACCESS_OWNER, ACCESS_FULL, ACCESS_WATERMARK, ACCESS_LINK_ONLY, ACCESS_NONE, ACCESS_EXPIRED
    )
    
    try:
        user_id = str(current_user.get('id') or current_user.get('_id') or current_user.get('user_id') or '')
        wallet_address = current_user.get('wallet_address')

        artwork_doc = await resolve_artwork_identifier(artwork_identifier)
        resolved_token_id = artwork_doc.get("token_id") if artwork_doc else None
        
        # Get access level
        access_level, license_doc = await LicenseAccessService.get_access_level(
            user_id, artwork_identifier, wallet_address
        )
        
        logger.info(f"🔑 License access check for identifier: {artwork_identifier}, user: {user_id}, level: {access_level}")
        
        # Build response based on access level
        response = {
            "token_id": resolved_token_id,
            "access_level": access_level,
            "has_access": access_level not in [ACCESS_NONE, ACCESS_EXPIRED],
            "is_owner": access_level == ACCESS_OWNER,
            "is_expired": access_level == ACCESS_EXPIRED,
        }
        
        # Add content URLs based on access level
        image_url_id = artwork_identifier # Usually the MongoDB _id string from frontend
        
        if access_level == ACCESS_OWNER:
            response["content"] = {
                "type": "full_access",
                "can_download": True,
                "can_view": True,
                "image_url": f"/api/v1/ticket/{image_url_id}/licensed-image",
                "download_url": f"/api/v1/ticket/{image_url_id}/licensed-download"
            }
        elif access_level == ACCESS_FULL:
            response["content"] = {
                "type": "full_access",
                "can_download": True,
                "can_view": True,
                "image_url": f"/api/v1/ticket/{image_url_id}/licensed-image",
                "download_url": f"/api/v1/ticket/{image_url_id}/licensed-download"
            }
        elif access_level == ACCESS_WATERMARK:
            response["content"] = {
                "type": "watermarked",
                "can_download": False,
                "can_view": True,
                "image_url": f"/api/v1/ticket/{image_url_id}/licensed-image"
            }
        elif access_level == ACCESS_LINK_ONLY:
            response["content"] = {
                "type": "link_only",
                "can_download": False,
                "can_view": True,
                "share_url": f"/ticket/{image_url_id}",
                "image_url": f"/api/v1/ticket/{image_url_id}/licensed-image"
            }
        elif access_level == ACCESS_EXPIRED:
            response["content"] = {
                "type": "expired",
                "message": "License expired. Please renew to access this ticket.",
                "can_download": False,
                "can_view": False
            }
        else:
            response["content"] = {
                "type": "no_access",
                "message": "No license found. Please purchase a license to access.",
                "can_download": False,
                "can_view": False
            }
        
        # Add license info if available
        if license_doc:
            response["license_info"] = {
                "license_id": license_doc.get("license_id"),
                "license_type": license_doc.get("license_type"),
                "purchase_time": license_doc.get("purchase_time"),
                "end_date": license_doc.get("end_date"),
                "duration_days": license_doc.get("duration_days", 30),
                "is_active": license_doc.get("is_active", False),
                "payment_method": license_doc.get("payment_method", "crypto")
            }
        
        return response
        
    except Exception as e:
        logger.error(f"Error checking license access: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to check license access")

# Add license configuration endpoints
@router.get("/config/active", response_model=LicenseConfig)
async def get_active_license_config():
    """Get the active license configuration"""
    try:
        config = await LicenseConfigService.get_active_config()
        return config
    except Exception as e:
        logger.error(f"Error getting active license config: {e}")
        raise HTTPException(status_code=500, detail="Failed to get license configuration")

@router.post("/config", response_model=dict)
async def create_license_config(
    config_data: LicenseConfigCreate,
    current_user: dict = Depends(get_current_user)
):
    """Create a new license configuration (admin only)"""
    try:
        # TODO: Add admin check
        # if not current_user.get("is_admin", False):
        #     raise HTTPException(status_code=403, detail="Only admins can create configurations")
        
        db = get_db()
        config_collection = db.license_configs
        
        # Deactivate other configurations if this one is set to active
        if config_data.is_active:
            await config_collection.update_many(
                {"is_active": True},
                {"$set": {"is_active": False}}
            )
        
        config = LicenseConfig(**config_data.model_dump())
        result = await config_collection.insert_one(config.model_dump(by_alias=True))
        
        return {
            "success": True,
            "config_id": str(result.inserted_id),
            "message": "License configuration created successfully"
        }
    except Exception as e:
        logger.error(f"Error creating license config: {e}")
        raise HTTPException(status_code=500, detail="Failed to create license configuration")

@router.put("/config/{config_id}", response_model=dict)
async def update_license_config(
    config_id: str,
    config_update: LicenseConfigUpdate,
    current_user: dict = Depends(get_current_user)
):
    """Update a license configuration (admin only)"""
    try:
        # TODO: Add admin check
        db = get_db()
        config_collection = db.license_configs
        
        from bson import ObjectId
        if not ObjectId.is_valid(config_id):
            raise HTTPException(status_code=400, detail="Invalid configuration ID")
        
        update_data = config_update.model_dump(exclude_unset=True)
        update_data["updated_at"] = datetime.utcnow()
        
        # Handle activation/deactivation
        if config_update.is_active is True:
            await config_collection.update_many(
                {"is_active": True},
                {"$set": {"is_active": False}}
            )
        
        result = await config_collection.update_one(
            {"_id": ObjectId(config_id)},
            {"$set": update_data}
        )
        
        if result.modified_count == 0:
            raise HTTPException(status_code=404, detail="Configuration not found")
        
        return {
            "success": True,
            "message": "License configuration updated successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating license config: {e}")
        raise HTTPException(status_code=500, detail="Failed to update license configuration")

@router.get("/config", response_model=List[LicenseConfig])
async def list_license_configs(
    active_only: bool = Query(False, description="Only return active configurations")
):
    """List all license configurations"""
    try:
        db = get_db()
        config_collection = db.license_configs
        
        query = {}
        if active_only:
            query["is_active"] = True
        
        cursor = config_collection.find(query).sort("created_at", -1)
        configs_data = await cursor.to_list(length=100)
        
        configs = []
        for doc in configs_data:
            if '_id' in doc:
                doc['_id'] = str(doc['_id'])
            configs.append(LicenseConfig(**doc))
        
        return configs
    except Exception as e:
        logger.error(f"Error listing license configs: {e}")
        raise HTTPException(status_code=500, detail="Failed to list license configurations")

@router.get("/prices")
async def get_license_prices(
    artwork_price: Optional[float] = Query(None, description="Ticket price in ETH for percentage calculation"),
    artwork_id: Optional[str] = Query(None, description="Filter by ticket MongoDB _id"),
    token_id: Optional[int] = Query(None, description="Legacy: Filter by ticket token ID")
):
    """Get license prices (fixed or percentage-based)"""
    try:
        responsible_use_addon = None
        artwork_identifier = artwork_id or token_id
        
        if artwork_identifier:
            ticket = await resolve_artwork_identifier(artwork_identifier)
            if ticket:
                responsible_use_addon = ticket.get("responsible_use_addon")
                if artwork_price is None:
                    artwork_price = ticket.get("price", 0.0)

        prices = await LicenseConfigService.get_all_license_prices(artwork_price or 0.0, responsible_use_addon)
        return prices
    except Exception as e:
        logger.error(f"Error getting license prices: {e}")
        raise HTTPException(status_code=500, detail="Failed to get license prices")

@router.get("/prices/calculate")
async def calculate_license_price(
    license_type: str = Query(..., description="License type"),
    artwork_price: Optional[float] = Query(None, description="Ticket price in ETH for percentage calculation"),
    artwork_id: Optional[str] = Query(None),
    token_id: Optional[int] = Query(None)
):
    """Calculate license price for a given license type"""
    try:
        responsible_use_addon = None
        artwork_identifier = artwork_id or token_id
        
        if artwork_identifier:
            ticket = await resolve_artwork_identifier(artwork_identifier)
            if ticket:
                responsible_use_addon = ticket.get("responsible_use_addon")
                if artwork_price is None:
                    artwork_price = ticket.get("price", 0.0)

        valid_types = [
            "PERSONAL_USE", "NON_COMMERCIAL", "COMMERCIAL", "EXTENDED_COMMERCIAL",
            "EXCLUSIVE", "ARTWORK_OWNERSHIP", "CUSTOM"
        ]
        if license_type not in valid_types:
            raise HTTPException(status_code=400, detail=f"Invalid license type. Must be one of: {', '.join(valid_types)}")
        
        calculation = await LicenseConfigService.calculate_license_fees(
            license_type, 
            artwork_price,
            responsible_use_addon=responsible_use_addon
        )
        
        return {
            "success": True,
            "calculation": calculation.model_dump(),
            "license_type": license_type,
            "artwork_price_provided": artwork_price is not None
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error calculating license price: {e}")
        raise HTTPException(status_code=500, detail="Failed to calculate license price")

@router.post("/purchase-simple")
async def purchase_license_simple(
    artwork_id: Optional[str] = Form(None),
    token_id: Optional[int] = Form(None),
    license_type: str = Form(...),
    current_user: dict = Depends(get_current_user)
):
    """Purchase a license with blockchain transaction - FORCE REAL MODE"""
    try:
        # Resolve ticket (artwork_id is prioritized)
        artwork_identifier = artwork_id or token_id
        artwork_doc = await resolve_artwork_identifier(artwork_identifier)
        if not artwork_doc:
            raise HTTPException(status_code=404, detail="Ticket not found")

        network = _ensure_wirefluid_network(
            artwork_doc.get("network") or getattr(settings, "ACTIVE_NETWORK", "wirefluid") or "wirefluid"
        )
        is_algorand_purchase = network == "algorand"
        
        # Ensure we have both
        token_id = artwork_doc.get("token_id")
        artwork_id = str(artwork_doc.get("_id"))

        algorand_service = None

        if is_algorand_purchase:
            try:
                from services.algorand_service import algorand_service
                algorand_service.algod_client.status()
            except Exception as algo_health_error:
                logger.error(f"❌ Algorand connection issue: {algo_health_error}")
                raise HTTPException(
                    status_code=503,
                    detail=f"Algorand service unavailable: {str(algo_health_error)}"
                )
        else:
            # ✅ CRITICAL: Check if we're in demo mode and reject if so
            if web3_service.demo_mode:
                logger.error("❌ License purchase attempted in DEMO mode - rejecting")
                raise HTTPException(
                    status_code=503,
                    detail="Blockchain service is currently in demo mode. Real transactions are disabled. Please check Web3 configuration."
                )

            # Check Web3 connection health
            connection_status = await web3_service.check_connection_health()
            if connection_status.get("status") != "healthy":
                logger.error(f"❌ Web3 connection issue: {connection_status}")
                raise HTTPException(
                    status_code=503,
                    detail=f"Blockchain service unavailable: {connection_status.get('message', 'Unknown error')}"
                )
        
        db_licenses = get_license_collection()
        db_artworks = get_artwork_collection()
        users_collection = get_user_collection()

        # Validate inputs
        valid_types = [
            "PERSONAL_USE", "NON_COMMERCIAL", "COMMERCIAL", "EXTENDED_COMMERCIAL",
            "EXCLUSIVE", "RESPONSIBLE_USE", "ARTWORK_OWNERSHIP", "CUSTOM"
        ]
        if license_type not in valid_types:
            raise HTTPException(status_code=400, detail=f"Invalid license type. Must be one of: {', '.join(valid_types)}")

        # Get user wallet
        buyer_wallet = current_user.get('wallet_address')
        user_id = str(current_user.get('id', ''))
            
        if not buyer_wallet:
            raise HTTPException(status_code=400, detail="User wallet address not found")

        buyer_wallet = str(buyer_wallet).strip()
        if is_algorand_purchase:
            try:
                from algosdk import encoding as algo_encoding
                if not algo_encoding.is_valid_address(buyer_wallet):
                    raise HTTPException(status_code=400, detail="Invalid Algorand wallet address")
            except HTTPException:
                raise
            except Exception as algo_address_error:
                logger.error(f"❌ Failed to validate Algorand wallet address: {algo_address_error}")
                raise HTTPException(status_code=400, detail="Invalid Algorand wallet address")

            buyer_address = buyer_wallet
        else:
            buyer_address = Web3.to_checksum_address(buyer_wallet)
        
        # Get ticket info
        artwork_doc = await resolve_artwork_identifier(token_id)
        if not artwork_doc:
            raise HTTPException(status_code=404, detail="Ticket not found")
        
        token_id = artwork_doc.get("token_id")

        artwork_id = str(artwork_doc.get('_id', ''))
        artwork_price = artwork_doc.get("price", 0.0)
        
        if artwork_price <= 0:
            raise HTTPException(status_code=400, detail="Ticket price not set or invalid")
        
        # Check ownership with blockchain - network-aware
        if is_algorand_purchase:
            owner_address = (
                artwork_doc.get("owner_algorand_address")
                or artwork_doc.get("creator_algorand_address")
                or artwork_doc.get("owner_address")
                or artwork_doc.get("creator_address")
            )

            asa_id = artwork_doc.get("algorand_asa_id")
            if asa_id:
                try:
                    from services.algorand_service import algorand_service
                    chain_info = await algorand_service.get_asset_blockchain_info(int(asa_id))
                    if chain_info.get("success") and chain_info.get("owner"):
                        owner_address = chain_info.get("owner")
                except Exception as owner_fetch_error:
                    logger.warning(f"⚠️ Failed to fetch live Algorand owner for ASA {asa_id}: {owner_fetch_error}")

            if not owner_address:
                raise HTTPException(
                    status_code=404,
                    detail="Could not determine ticket owner on Algorand"
                )
        else:
            owner_address = await web3_service.get_artwork_owner(token_id)
            if not owner_address:
                raise HTTPException(
                    status_code=404,
                    detail="Could not determine ticket owner from blockchain"
                )
            
        if str(buyer_address).lower() == str(owner_address).lower():
            raise HTTPException(status_code=400, detail="Cannot purchase license for your own ticket")
        
         
        # ✅ Auto-cleanup old pending licenses before checking for duplicates
        try:
            cleanup_result = await cleanup_old_pending_licenses(max_age_hours=1, dry_run=False)
            if cleanup_result.get("cleaned_count", 0) > 0:
                logger.info(f"🧹 Auto-cleaned {cleanup_result['cleaned_count']} old pending licenses before purchase check")
        except Exception as cleanup_error:
            logger.warning(f"⚠️ Auto-cleanup failed (non-critical): {cleanup_error}")
            # Continue with purchase even if cleanup fails
         # ✅ Check for existing active or pending license for this ticket and buyer (CRYPTO)
        existing_license = await db_licenses.find_one({
            "artwork_id": artwork_id,
            "buyer_id": user_id,
            "payment_method": {"$ne": "paypal"},  # Crypto licenses (not PayPal)
            "$or": [
                {"status": "CONFIRMED", "is_active": True},
                {"status": "PENDING"}  # Pending blockchain transaction
            ]
        })
        
        if existing_license:
            existing_license_id = existing_license.get("license_id")
            existing_status = existing_license.get("status")
            if existing_status == "CONFIRMED" and existing_license.get("is_active"):
                raise HTTPException(
                    status_code=400,
                    detail=f"You already have an active license (#{existing_license_id}) for this ticket. Each ticket can only have one active license per buyer."
                )
            elif existing_status == "PENDING":
                existing_license_id = existing_license.get("license_id")
                transaction_hash = existing_license.get("transaction_hash")
                
                # ✅ If no transaction hash, user cancelled in MetaMask - allow new purchase
                if not transaction_hash:
                    logger.info(f"🧹 Pending license #{existing_license_id} has no transaction hash (cancelled) - cleaning up")
                    db_licenses = get_license_collection()
                    await db_licenses.delete_one({"license_id": existing_license_id})
                    logger.info(f"✅ Cleaned up cancelled license - allowing new purchase")
                    # Continue with purchase (don't raise exception)
                else:
                    if is_algorand_purchase:
                        logger.warning(
                            f"⚠️ User {user_id} already has a pending Algorand license (#{existing_license_id}) for token {token_id}"
                        )
                        raise HTTPException(
                            status_code=400,
                            detail=f"You already have a pending license purchase (#{existing_license_id}) for this ticket. Please wait for the transaction to confirm."
                        )
                    else:
                        # Transaction hash exists - check if transaction failed
                        try:
                            tx_receipt = await web3_service.get_transaction_receipt(transaction_hash)
                            if tx_receipt and tx_receipt.get("status") == 0:
                                # Transaction failed - clean up
                                logger.info(f"🧹 Pending license #{existing_license_id} transaction failed - cleaning up")
                                db_licenses = get_license_collection()
                                await db_licenses.delete_one({"license_id": existing_license_id})
                                logger.info(f"✅ Cleaned up failed transaction - allowing new purchase")
                                # Continue with purchase
                            else:
                                # Transaction pending or succeeded - block new purchase
                                logger.warning(f"⚠️ User {user_id} already has a pending license (#{existing_license_id}) for token {token_id}")
                                raise HTTPException(
                                    status_code=400,
                                    detail=f"You already have a pending license purchase (#{existing_license_id}) for this ticket. Please wait for the transaction to confirm."
                                )
                        except Exception as tx_error:
                            # Can't verify transaction - be conservative
                            logger.warning(f"⚠️ Could not verify transaction for license #{existing_license_id}: {tx_error}")
                            raise HTTPException(
                                status_code=400,
                                detail=f"You already have a pending license purchase (#{existing_license_id}) for this ticket. Please wait for the transaction to confirm or try again later."
                            )

        # ✅ NEW: Phase 2 Exclusivity Checks
        # 1. Check if ticket is ALREADY exclusively licensed
        # We check both confirmed and pending exclusive licenses
        exclusive_query = {
            "artwork_id": artwork_id,
            "license_type": {"$in": ["EXCLUSIVE", "ARTWORK_OWNERSHIP"]},
            "status": {"$in": ["CONFIRMED", "PENDING"]},
            "is_active": True
        }
        existing_exclusive = await db_licenses.find_one(exclusive_query)
        if existing_exclusive:
            raise HTTPException(
                status_code=400,
                detail="Ticket is already exclusively licensed. No further licenses can be purchased."
            )
        
        # 2. If buying EXCLUSIVE, check if ANY active licenses exist
        if license_type in ["EXCLUSIVE", "ARTWORK_OWNERSHIP"]:
            any_active_query = {
                "artwork_id": artwork_id,
                "status": {"$in": ["CONFIRMED", "PENDING"]},
                "is_active": True
            }
            if await db_licenses.count_documents(any_active_query) > 0:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot purchase exclusive license for ticket with existing active licenses."
                )

        # Calculate license fees
        config = await LicenseConfigService.get_active_config()
        fee_calculation = await LicenseConfigService.calculate_license_fees(
            license_type, 
            artwork_price, 
            config,
            responsible_use_addon=artwork_doc.get("responsible_use_addon")
        )
        license_percentage = fee_calculation.license_percentage
        # ✅ CRITICAL: Prepare REAL blockchain transaction (network-aware)
        logger.info(
            f"🔄 Preparing REAL blockchain transaction for license purchase - Token: {token_id}, Buyer: {buyer_address}, Network: {network}"
        )

        if is_algorand_purchase:
            app_id = artwork_doc.get("algorand_app_id") or getattr(settings, "ALGORAND_APP_ID", 0)
            app_id = int(app_id or 0)
            if app_id <= 0:
                raise HTTPException(status_code=500, detail="Algorand app ID is not configured")

            license_breakdown = await _build_algorand_license_breakdown(
                artwork_price_algo=float(artwork_price),
                license_percentage=float(license_percentage),
                owner_address=str(owner_address or "").strip(),
                algorand_service=algorand_service,
            )

            payment_legs = license_breakdown.get("payment_legs") or []
            if not payment_legs:
                raise HTTPException(status_code=500, detail="Algorand license payment legs are missing")

            primary_leg = payment_legs[0]

            tx_data = {
                # Keep legacy single-leg fields for compatibility; frontend prefers payment_legs.
                "to": primary_leg.get("to"),
                "value": int(primary_leg.get("amount") or 0),
                "payment_legs": payment_legs,
                "license_breakdown": license_breakdown,
                "appId": app_id,
                "appArgs": [
                    "purchase_license",
                    int(token_id),
                    license_type,
                    36500
                ],
            }

            required_fields = ["payment_legs", "appId", "appArgs"]
        else:
            # ✅ Use prepare_simple_license_purchase with ticket price and license percentage
            tx_data = await web3_service.prepare_simple_license_purchase(
                token_id=token_id,
                buyer_address=buyer_address,
                license_type=license_type,
                artwork_price_eth=artwork_price,
                license_percentage=license_percentage,
                duration_days=36500  # ✅ Default to Perpetual as per current business logic
            )
            required_fields = ['to', 'data', 'value']

        if not tx_data:
            raise HTTPException(status_code=500, detail="Failed to prepare blockchain transaction data")

        missing_fields = [field for field in required_fields if field not in tx_data]
        if missing_fields:
            logger.error(f"❌ Missing required transaction fields: {missing_fields}")
            raise HTTPException(
                status_code=500,
                detail=f"Incomplete transaction data: missing {', '.join(missing_fields)}"
            )

        # Store pending license in database (not active until blockchain confirmation)
        license_count = await db_licenses.count_documents({}) + 1
        
        # license_dict = {
        #     "license_id": license_count,
        #     "token_id": token_id,
        #     "buyer_id": user_id,
        #     "buyer_address": buyer_address.lower(),
        #     "owner_address": owner_address.lower(),
        #     "license_type": license_type,
        #     "total_amount_eth": fee_calculation.total_amount_eth,
        #     "total_amount_wei": fee_calculation.total_amount_wei,
        #     "is_active": False,  # Not active until blockchain confirmation
        #     "purchase_time": datetime.utcnow(),
        #     "status": "PENDING",  # Waiting for blockchain confirmation
        #     "transaction_data": tx_data,
        #     "created_at": datetime.utcnow(),
        #     "updated_at": datetime.utcnow(),
        #     "mode": "REAL"  # Track that this is a real blockchain transaction
        # }

        # result = await db_licenses.insert_one(license_dict)
        # logger.info(f"✅ Created pending license {license_count} for real blockchain transaction")

        # Return transaction data that WILL trigger MetaMask
        response_data = {
            "success": True,
            "license_id": license_count,
            "transaction_data": tx_data,
            "requires_blockchain": True,
            "mode": "REAL",
            "network": network,
            "fee_calculation": fee_calculation.model_dump(),
            "artwork_info": {
                "token_id": token_id,
                "artwork_id": artwork_id,
                "title": artwork_doc.get("title", "Untitled"),
                "price_eth": artwork_price
            },
            "license_breakdown": tx_data.get("license_breakdown") if is_algorand_purchase else None,
            "message": f"Please confirm the transaction in {'Pera Wallet' if is_algorand_purchase else 'MetaMask'} to complete your license purchase"
        }
        
        logger.info(f"✅ Returning REAL transaction data for {'Pera Wallet' if is_algorand_purchase else 'MetaMask'} signing: {response_data}")
        return response_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error in license purchase: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"License purchase failed: {str(e)}")

@router.post("/purchase-paypal")
async def purchase_license_paypal(
    artwork_identifier: str = Form(...),
    license_type: str = Form(...),
    current_user: dict = Depends(get_current_user)
):
    """Purchase a license for PayPal-registered ticket using PayPal payment"""
    raise HTTPException(status_code=410, detail="PayPal support has been removed from this deployment.")

    try:
        # ✅ Check if PayPal is enabled by admin
        from app.api.v1.ticket import is_paypal_enabled
        if not await is_paypal_enabled():
            raise HTTPException(
                status_code=403,
                detail="PayPal payments are currently disabled by the administrator."
            )
        
        db_licenses = get_license_collection()
        db_artworks = get_artwork_collection()
        users_collection = get_user_collection()
        paypal_service = get_paypal_service()

        # Validate inputs
        valid_types = [
            "PERSONAL_USE", "NON_COMMERCIAL", "COMMERCIAL", "EXTENDED_COMMERCIAL",
            "EXCLUSIVE", "ARTWORK_OWNERSHIP", "CUSTOM"
        ]
        if license_type not in valid_types:
            raise HTTPException(status_code=400, detail=f"Invalid license type. Must be one of: {', '.join(valid_types)}")

        # Get user info
        user_id = str(current_user.get('id', '') or current_user.get('_id', ''))
        buyer_email = current_user.get('email')
        
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")
        if not buyer_email:
            raise HTTPException(status_code=400, detail="User email not found")

        # Get ticket info
        artwork_doc = await resolve_artwork_identifier(artwork_identifier)
        if not artwork_doc:
            raise HTTPException(status_code=404, detail="Ticket not found")
        
        token_id = artwork_doc.get("token_id")
        artwork_id = str(artwork_doc.get("_id"))

        # ✅ Check if ticket is on-chain or off-chain
        is_on_chain = artwork_doc.get("is_on_chain")
        # Backward compatibility: derive from old fields if new fields don't exist
        if is_on_chain is None:
            payment_method = artwork_doc.get("payment_method", "crypto")
            is_virtual_token = artwork_doc.get("is_virtual_token", False)
            if payment_method == "paypal" or is_virtual_token:
                is_on_chain = False
            else:
                is_on_chain = True
        
        # ✅ RESTRICTION: On-chain tickets MUST use crypto for licenses (blockchain requirement)
        if is_on_chain:
            raise HTTPException(
                status_code=400, 
                detail="This ticket is registered on blockchain. Please use the crypto payment method for licenses."
            )
        
        # ✅ NO RESTRICTION: Off-chain tickets can use PayPal or any other payment method

        artwork_id = str(artwork_doc.get('_id', ''))
        artwork_price = artwork_doc.get("price", 0.0)
        
        if artwork_price <= 0:
            raise HTTPException(status_code=400, detail="Ticket price not set or invalid")

        # Get ticket owner (from database, not blockchain)
        owner_id = artwork_doc.get("owner_id")
        if not owner_id:
            raise HTTPException(status_code=404, detail="Could not determine ticket owner")
        
        # Prevent self-purchase
        if str(owner_id) == user_id:
            raise HTTPException(status_code=400, detail="Cannot purchase license for your own ticket")

        # ✅ Check for existing active or pending license for this ticket and buyer
        existing_license = await db_licenses.find_one({
            "artwork_id": artwork_id,
            "buyer_id": user_id,
            "payment_method": "paypal",
            "$or": [
                {"status": "CONFIRMED", "is_active": True},
                {"status": "PENDING"}  # Pending payment
            ]
        })
        
        if existing_license:
            existing_license_id = existing_license.get("license_id")
            existing_status = existing_license.get("status")
            if existing_status == "CONFIRMED" and existing_license.get("is_active"):
                raise HTTPException(
                    status_code=400,
                    detail=f"You already have an active license (#{existing_license_id}) for this ticket. Each ticket can only have one active license per buyer."
                )
            elif existing_status == "PENDING":
                # Return the existing pending license's PayPal order info
                existing_order_id = existing_license.get("paypal_order_id")
                logger.warning(f"⚠️ User {user_id} already has a pending license (#{existing_license_id}) for token {token_id}")
                raise HTTPException(
                    status_code=400,
                    detail=f"You already have a pending license purchase (#{existing_license_id}) for this ticket. Please complete or cancel the existing purchase first."
                )

        # ✅ NEW: Phase 2 Exclusivity Checks for PayPal
        exclusive_query = {
            "artwork_id": artwork_id,
            "license_type": {"$in": ["EXCLUSIVE", "ARTWORK_OWNERSHIP"]},
            "status": {"$in": ["CONFIRMED", "PENDING"]},
            "is_active": True
        }
        existing_exclusive = await db_licenses.find_one(exclusive_query)
        if existing_exclusive:
            raise HTTPException(
                status_code=400,
                detail="Ticket is already exclusively licensed via PayPal or Crypto."
            )
        
        if license_type in ["EXCLUSIVE", "ARTWORK_OWNERSHIP"]:
            any_active_query = {
                "artwork_id": artwork_id,
                "status": {"$in": ["CONFIRMED", "PENDING"]},
                "is_active": True
            }
            if await db_licenses.count_documents(any_active_query) > 0:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot purchase exclusive license via PayPal for ticket with existing active licenses."
                )

        # Get seller user info for payout
        seller_user_id = str(owner_id)
        seller_user = await users_collection.find_one({"user_id": seller_user_id})
        if not seller_user:
            # Try alternative lookups
            if ObjectId.is_valid(seller_user_id):
                seller_user = await users_collection.find_one({"_id": ObjectId(seller_user_id)})
            if not seller_user:
                seller_user = await users_collection.find_one({"_id": seller_user_id})
        
        if not seller_user:
            raise HTTPException(status_code=404, detail="Seller user not found")

        # Calculate license fees (same as blockchain)
        config = await LicenseConfigService.get_active_config()
        fee_calculation = await LicenseConfigService.calculate_license_fees(
            license_type, 
            artwork_price, 
            config,
            responsible_use_addon=artwork_doc.get("responsible_use_addon")
        )

        # Convert ETH amount to USD for PayPal
        # Use fixed rate (same as frontend) - can be updated to use API later
        eth_to_usd_rate = 2700.0  # Default rate, matches frontend CurrencyConverter
        amount_usd = float(fee_calculation.total_amount_eth) * eth_to_usd_rate

        logger.info(f"💰 PayPal License Purchase - Token: {token_id}, Type: {license_type}, Amount: ${amount_usd:.2f} USD")
        logger.info(f"📦 Ticket ID: {artwork_id}, Ticket Price: {artwork_price} ETH")

        # Create PayPal order
        paypal_result = await paypal_service.create_license_purchase_order(
            license_type=license_type,
            token_id=token_id,
            artwork_id=artwork_id,  # String version of ObjectId
            buyer_id=user_id,
            buyer_email=buyer_email,
            seller_user_id=seller_user_id,
            amount=amount_usd,
            currency='USD'
        )

        if not paypal_result.get('success'):
            error_msg = paypal_result.get('error', 'Unknown error')
            logger.error(f"❌ PayPal order creation failed: {error_msg}")
            raise HTTPException(status_code=500, detail=f"Failed to create PayPal order: {error_msg}")

        # # Store pending license in database
        # license_count = await db_licenses.count_documents({}) + 1
        
        # license_dict = {
        #     "license_id": license_count,
        #     "token_id": token_id,
        #     "buyer_id": user_id,
        #     "owner_id": seller_user_id,
        #     "buyer_address": None,  # PayPal users don't have wallet addresses
        #     "owner_address": None,  # PayPal tickets don't have owner addresses
        #     "license_type": license_type,
        #     "total_amount_eth": fee_calculation.total_amount_eth,
        #     "total_amount_wei": fee_calculation.total_amount_wei,
        #     "total_amount_usd": amount_usd,
        #     "is_active": False,  # Not active until PayPal payment confirmed
        #     "purchase_time": datetime.utcnow(),
        #     "status": "PENDING",  # Waiting for PayPal payment confirmation
        #     "payment_method": "paypal",
        #     "paypal_order_id": paypal_result.get('order_id'),
        #     "created_at": datetime.utcnow(),
        #     "updated_at": datetime.utcnow()
        # }

        # result = await db_licenses.insert_one(license_dict)
        # logger.info(f"✅ Created pending PayPal license {license_count} for token {token_id}")

        # Return PayPal approval URL
        response_data = {
            "success": True,
            # "license_id": license_count,
            "approval_url": paypal_result.get('approval_url'),
            "order_id": paypal_result.get('order_id'),
            "requires_paypal": True,
            "payment_method": "paypal",
            "fee_calculation": {
                "total_amount_eth": fee_calculation.total_amount_eth,
                "total_amount_usd": amount_usd,
                "eth_to_usd_rate": eth_to_usd_rate
            },
            "artwork_info": {
                "token_id": token_id,
                "artwork_id": artwork_id,
                "title": artwork_doc.get("title", "Untitled"),
                "price_eth": artwork_price
            },
            "message": "Please complete the PayPal payment to finish your license purchase"
        }
        
        logger.info(f"✅ Returning PayPal approval URL for license purchase: {response_data}")
        return response_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error in PayPal license purchase: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"PayPal license purchase failed: {str(e)}")
    
@router.get("/health/blockchain")
async def blockchain_health():
    """Check blockchain connection status"""
    try:
        status = await web3_service.check_connection_health()
        return {
            "success": True,
            "blockchain_status": status,
            "demo_mode": web3_service.demo_mode,
            "connected": web3_service.connected,
            "provider_url": getattr(settings, 'WEB3_PROVIDER_URL', 'Not set'),
            "contract_address": getattr(settings, 'CONTRACT_ADDRESS', 'Not set')
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "demo_mode": web3_service.demo_mode,
            "connected": False
        }
    
@router.get("/prices/ticket/{artwork_identifier}")
async def get_license_prices_for_artwork(artwork_identifier: str):
    """Get license prices for a specific ticket"""
    try:
        # Get ticket info
        artwork_doc = await resolve_artwork_identifier(artwork_identifier)
        if not artwork_doc:
            raise HTTPException(status_code=404, detail="Ticket not found")
        
        token_id = artwork_doc.get("token_id")
        artwork_id = str(artwork_doc.get("_id"))
        
        artwork_price = artwork_doc.get("price", 0.0)

        # ✅ Add detailed logging
        logger.info(f"💰 License price calculation for token {token_id}:")
        logger.info(f"   Ticket price from DB: {artwork_price} ETH")
        logger.info(f"   Ticket price type: {type(artwork_price)}")
        if artwork_price <= 0:
            raise HTTPException(status_code=400, detail="Ticket price not set or invalid")
        
        prices = await LicenseConfigService.get_all_license_prices(artwork_price, artwork_doc.get("responsible_use_addon"))
        logger.info(f"   Calculated prices: {prices.get('prices', {})}")
        # Add ticket information
        prices["artwork_info"] = {
            "token_id": token_id,
            "title": artwork_doc.get("title", "Untitled"),
            "price_eth": artwork_price,
            "owner_address": artwork_doc.get("owner_address")
        }
        
        return prices
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting license prices for ticket {token_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get license prices")
    
# Update other license endpoints to include duration information
@router.get("/{license_id}/status")
async def get_license_status(license_id: int):
    """Get detailed license status including expiration info"""
    try:
        db_licenses = get_license_collection()
        
        license_doc = await db_licenses.find_one({"license_id": license_id})
        if not license_doc:
            raise HTTPException(status_code=404, detail="License not found")
        
        current_time = datetime.utcnow()
        end_date = license_doc.get("end_date")
        is_active = license_doc.get("is_active", False)
        
        # Calculate time remaining
        time_remaining = None
        if end_date:
            if isinstance(end_date, str):
                end_date = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            time_remaining = end_date - current_time
        
        status_info = {
            "license_id": license_id,
            "is_active": is_active and (not time_remaining or time_remaining.total_seconds() > 0),
            "status": license_doc.get("status", "UNKNOWN"),
            "purchase_time": license_doc.get("purchase_time"),
            "start_date": license_doc.get("start_date"),
            "end_date": license_doc.get("end_date"),
            "duration_days": license_doc.get("duration_days", 30),
            "artwork_price_eth": license_doc.get("artwork_price_eth", 0),
            "time_remaining_days": time_remaining.days if time_remaining and time_remaining.total_seconds() > 0 else 0,
            "time_remaining_hours": (time_remaining.seconds // 3600) if time_remaining and time_remaining.total_seconds() > 0 else 0,
            "is_expired": time_remaining and time_remaining.total_seconds() <= 0,
            "revoked_at": license_doc.get("revoked_at"),
            "revoked_reason": license_doc.get("revoked_reason")
        }
        
        return {
            "success": True,
            "license_status": status_info
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting license status for {license_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/buyer/{buyer_identifier}")
async def get_buyer_licenses(
    buyer_identifier: str,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100)
):
    """Get licenses for a buyer - supports both user ID and wallet address"""
    try:
        db_licenses = get_license_collection()
        users_collection = get_user_collection()

        # Determine if identifier is a wallet address or user ID
        is_wallet_address = (
            buyer_identifier.startswith('0x') and 
            len(buyer_identifier) == 42
        )

        filter_query = {}
        
        if is_wallet_address:
            # Search by wallet address (crypto users)
            try:
                buyer_checksum = Web3.to_checksum_address(buyer_identifier)
                filter_query = {"buyer_address": buyer_checksum.lower()}
                logger.info(f"Searching licenses by buyer wallet address: {buyer_identifier}")
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid Ethereum address")
        else:
            # Search by user ID (PayPal users or internal lookup)
            # Try multiple lookup methods for user
            user = None
            if ObjectId.is_valid(buyer_identifier):
                user = await users_collection.find_one({"_id": ObjectId(buyer_identifier)})
            if not user:
                user = await users_collection.find_one({"user_id": buyer_identifier})
            if not user:
                user = await users_collection.find_one({"_id": buyer_identifier})
            if not user:
                user = await users_collection.find_one({"id": buyer_identifier})
            
            if user:
                # User found, search by buyer_id (for PayPal licenses)
                # ✅ Get all possible user ID formats that might be stored as buyer_id
                user_id_from_user_field = user.get('user_id')
                user_id_from_id_field = user.get('id')
                user_id_from_objectid = user.get('_id')
                
                # Convert all to strings (matching how they're stored in purchase-paypal)
                possible_buyer_ids = set()
                
                # Add user_id field
                if user_id_from_user_field:
                    possible_buyer_ids.add(str(user_id_from_user_field))
                
                # Add id field
                if user_id_from_id_field:
                    possible_buyer_ids.add(str(user_id_from_id_field))
                
                # Add _id (ObjectId) as string
                if user_id_from_objectid:
                    possible_buyer_ids.add(str(user_id_from_objectid))
                
                # Add original identifier
                possible_buyer_ids.add(buyer_identifier)
                
                # ✅ Search with all possible buyer_id formats
                or_conditions = [{"buyer_id": bid} for bid in possible_buyer_ids]
                
                filter_query = {"$or": or_conditions} if len(or_conditions) > 1 else {"buyer_id": list(possible_buyer_ids)[0]}
                
                logger.info(f"🔍 Searching licenses by buyer user ID - Query: {filter_query}")
                logger.info(f"   Possible buyer_ids: {possible_buyer_ids}")
                logger.info(f"   User found - user_id: {user_id_from_user_field}, _id: {user_id_from_objectid}, id: {user_id_from_id_field}")
                
                # Also include wallet address if user has one (for crypto licenses)
                wallet_address = user.get('wallet_address')
                if wallet_address:
                    filter_query = {
                        "$or": or_conditions + [{"buyer_address": wallet_address.lower()}]
                    }
                    logger.info(f"Including wallet address in search: {wallet_address}")
            else:
                # Try as wallet address anyway
                try:
                    buyer_checksum = Web3.to_checksum_address(buyer_identifier)
                    filter_query = {"buyer_address": buyer_checksum.lower()}
                    logger.info(f"Buyer user not found, searching as wallet address: {buyer_identifier}")
                except Exception:
                    raise HTTPException(status_code=400, detail="Invalid user ID or Ethereum address")

        # ⚡ OPTIMIZED: Get total count and licenses in parallel
        total_task = db_licenses.count_documents(filter_query)
        skip = (page - 1) * size
        licenses_task = db_licenses.find(filter_query).skip(skip).limit(size).sort("purchase_time", -1).to_list(length=size)
        
        # Execute both queries in parallel
        total, licenses_data = await asyncio.gather(total_task, licenses_task)
        has_next = (page * size) < total

        # Also try to get from blockchain for crypto users
        blockchain_licenses = []
        if is_wallet_address:
            try:
                blockchain_licenses = await web3_service.get_buyer_licenses(buyer_checksum)
            except Exception as e:
                logger.warning(f"Could not fetch blockchain licenses: {e}")

        # Combine and enrich licenses
        enriched_licenses = []
        
        # ⚡ OPTIMIZED: Batch fetch all user emails at once (fixes N+1 problem)
        user_email_cache = {}
        owner_ids = set()
        buyer_ids = set()
        paypal_licenses = []
        
        # Collect all unique user IDs that need email lookup
        for db_license in licenses_data:
            payment_method = db_license.get("payment_method", "crypto")
            if payment_method == "paypal":
                owner_id = db_license.get("owner_id")
                buyer_id = db_license.get("buyer_id")
                if owner_id:
                    owner_ids.add(str(owner_id))
                if buyer_id:
                    buyer_ids.add(str(buyer_id))
                paypal_licenses.append(db_license)
        
        # Batch fetch all users at once
        all_user_ids = owner_ids | buyer_ids
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
                    email = user.get("email")
                    # ⚡ OPTIMIZED: Cache email by all possible ID formats for lookup
                    user_email_cache[str(user["_id"])] = email
                    if user.get("user_id"):
                        user_email_cache[str(user["user_id"])] = email
                    if user.get("id"):
                        user_email_cache[str(user["id"])] = email
            
            # Batch fetch by string _id for remaining IDs
            remaining_by_string = set(string_id_queries) - {str(k) for k in user_email_cache.keys()}
            if remaining_by_string:
                string_cursor = users_collection.find({"_id": {"$in": list(remaining_by_string)}})
                async for user in string_cursor:
                    email = user.get("email")
                    user_email_cache[str(user["_id"])] = email
                    if user.get("user_id"):
                        user_email_cache[str(user["user_id"])] = email
                    if user.get("id"):
                        user_email_cache[str(user["id"])] = email
            
            # Batch fetch by user_id field for any still missing
            still_missing = all_user_ids - {str(k) for k in user_email_cache.keys()}
            if still_missing:
                user_id_cursor = users_collection.find({"user_id": {"$in": list(still_missing)}})
                async for user in user_id_cursor:
                    email = user.get("email")
                    if user.get("user_id"):
                        user_email_cache[str(user["user_id"])] = email
                        user_email_cache[str(user["_id"])] = email
                    if user.get("id"):
                        user_email_cache[str(user["id"])] = email
            
            # Batch fetch by id field for any still missing
            still_missing = all_user_ids - {str(k) for k in user_email_cache.keys()}
            if still_missing:
                id_cursor = users_collection.find({"id": {"$in": list(still_missing)}})
                async for user in id_cursor:
                    email = user.get("email")
                    if user.get("id"):
                        user_email_cache[str(user["id"])] = email
                        user_email_cache[str(user["_id"])] = email
                    if user.get("user_id"):
                        user_email_cache[str(user["user_id"])] = email

        # Add database licenses
        for db_license in licenses_data:
            try:
                # ✅ Convert None to empty string for Pydantic validation
                buyer_address = db_license.get("buyer_address") or ""
                owner_address = db_license.get("owner_address") or ""
                
                # ⚡ OPTIMIZED: Get emails from cache (no additional queries)
                owner_email = None
                buyer_email = None
                owner_id = db_license.get("owner_id")
                buyer_id = db_license.get("buyer_id")
                payment_method = db_license.get("payment_method", "crypto")
                
                if payment_method == "paypal":
                     # ✅ Priority 1: Get email directly from license document (if stored)
                    buyer_email = db_license.get("buyer_email")
                    owner_email = db_license.get("owner_email")
                    
                    # ✅ Priority 2: If not in document, try cache
                    if not buyer_email and buyer_id:
                        buyer_email = user_email_cache.get(str(buyer_id))
                    if not owner_email and owner_id:
                        owner_email = user_email_cache.get(str(owner_id))
                    
                    # ✅ Priority 3: If still not found, fetch directly (fallback)
                    if not buyer_email and buyer_id:
                        try:
                            buyer_user = None
                            if ObjectId.is_valid(str(buyer_id)):
                                buyer_user = await users_collection.find_one({"_id": ObjectId(buyer_id)})
                            if not buyer_user:
                                buyer_user = await users_collection.find_one({"_id": buyer_id})
                            if not buyer_user:
                                buyer_user = await users_collection.find_one({"user_id": buyer_id})
                            if not buyer_user:
                                buyer_user = await users_collection.find_one({"id": buyer_id})
                            
                            if buyer_user:
                                buyer_email = buyer_user.get("email")
                                # Cache it for future use
                                if buyer_email:
                                    user_email_cache[str(buyer_id)] = buyer_email
                        except Exception as e:
                            logger.warning(f"⚠️ Failed to fetch buyer email for {buyer_id}: {e}")
                    
                    if not owner_email and owner_id:
                        try:
                            owner_user = None
                            if ObjectId.is_valid(str(owner_id)):
                                owner_user = await users_collection.find_one({"_id": ObjectId(owner_id)})
                            if not owner_user:
                                owner_user = await users_collection.find_one({"_id": owner_id})
                            if not owner_user:
                                owner_user = await users_collection.find_one({"user_id": owner_id})
                            if not owner_user:
                                owner_user = await users_collection.find_one({"id": owner_id})
                            
                            if owner_user:
                                owner_email = owner_user.get("email")
                                # Cache it for future use
                                if owner_email:
                                    user_email_cache[str(owner_id)] = owner_email
                        except Exception as e:
                            logger.warning(f"⚠️ Failed to fetch owner email for {owner_id}: {e}")
                
                # ✅ Ensure total_amount_eth is always a string
                total_amount_eth = db_license.get("total_amount_eth", "0")
                if total_amount_eth is None:
                    total_amount_eth = "0"
                elif not isinstance(total_amount_eth, str):
                    total_amount_eth = str(total_amount_eth)
                
                # ✅ Ensure purchase_time is a string
                purchase_time = db_license.get("purchase_time")
                if purchase_time is None:
                    purchase_time = ""
                elif isinstance(purchase_time, datetime):
                    purchase_time = purchase_time.isoformat()
                else:
                    purchase_time = str(purchase_time)
                
                license_info = {
                    "license_id": _normalize_license_id(db_license.get("license_id")),
                    "token_id": db_license["token_id"],
                    "buyer_id": db_license.get("buyer_id"),
                    "owner_id": owner_id,
                    "buyer_address": buyer_address,  # ✅ Empty string if None
                    "owner_address": owner_address,  # ✅ Empty string if None
                    "owner_email": owner_email,  # ✅ Owner email for PayPal licenses
                    "buyer_email": buyer_email,  # ✅ Buyer email for PayPal licenses (for owner view)
                    "license_type": db_license["license_type"],
                    "actual_amount_wei": str(db_license.get("actual_amount_wei", "0") or "0"),
                    "license_fee_wei": str(db_license.get("license_fee_wei", "0") or "0"),
                    "total_amount_wei": str(db_license.get("total_amount_wei", "0") or "0"),
                    "actual_amount_eth": str(db_license.get("actual_amount_eth", "0") or "0"),
                    "license_fee_eth": str(db_license.get("license_fee_eth", "0") or "0"),
                    "total_amount_eth": total_amount_eth,  # ✅ Always a string
                    "total_amount_usd": db_license.get("total_amount_usd"),  # ✅ Add USD amount for PayPal licenses
                    "purchase_time": purchase_time,  # ✅ Always a string
                    "is_active": db_license.get("is_active", True),
                    # ✅ Preserve actual status from database (don't override PENDING_APPROVAL)
                    "status": db_license.get("status") or ("CONFIRMED" if db_license.get("is_active") else "PENDING"),
                    "payment_method": payment_method,
                    "transaction_hash": db_license.get("transaction_hash"),
                    "network": db_license.get("network"),
                    "algorand_group_id": db_license.get("algorand_group_id"),
                    "algorand_license_reference": db_license.get("algorand_license_reference"),
                    "source": "database"
                }
                enriched_licenses.append(license_info)
            except Exception as e:
                logger.warning(f"Skipping invalid license document: {e}")
                continue

        # Add blockchain licenses (avoid duplicates)
        for bc_license in blockchain_licenses:
            # Check if already in database results
            existing = any(l.get("license_id") == bc_license["license_id"] for l in enriched_licenses)
            if not existing:
                license_info = {
                    "license_id": _normalize_license_id(bc_license.get("license_id")),
                    "token_id": bc_license["token_id"],
                    "buyer_address": bc_license["buyer"],
                    "owner_address": bc_license["owner"],
                    "license_type": ["LINK_ONLY", "ACCESS_WITH_WM", "FULL_ACCESS"][bc_license["license_type"]],
                    "actual_amount_wei": str(bc_license["actual_amount"]),
                    "license_fee_wei": str(bc_license["license_fee"]),
                    "total_amount_wei": str(bc_license["total_amount"]),
                    "actual_amount_eth": str(Web3.from_wei(bc_license["actual_amount"], 'ether')),
                    "license_fee_eth": str(Web3.from_wei(bc_license["license_fee"], 'ether')),
                    "total_amount_eth": str(Web3.from_wei(bc_license["total_amount"], 'ether')),
                    "purchase_time": datetime.fromtimestamp(bc_license["purchase_time"]).isoformat(),
                    "is_active": bc_license["is_active"],
                    "source": "blockchain"
                }
                enriched_licenses.append(license_info)

        return {
            "success": True,
            "licenses": enriched_licenses,
            "total": len(enriched_licenses),
            "page": page,
            "size": size,
            "has_next": has_next,
            "buyer_identifier": buyer_identifier
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting buyer licenses: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/user/{wallet_address}", response_model=LicenseListResponse)
async def get_user_licenses(
    wallet_address: str,
    as_licensee: bool = Query(False, description="Get licenses where user is licensee (buyer)"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    """Get licenses for a specific user (as licensor or licensee) - supports both wallet address and user ID"""
    try:
        logger.info(f"Getting licenses for identifier: {wallet_address} as_licensee={as_licensee}")
        
        # ✅ Detect if identifier is wallet address or user ID
        is_wallet_address = (
            wallet_address.startswith('0x') and 
            len(wallet_address) == 42
        )
        
        if is_wallet_address:
            # Normalize wallet address
            normalized_identifier = wallet_address.lower()
            
            if as_licensee:
                # Get licenses where user is the licensee (buyer)
                result = await list_licenses(
                    page=page, 
                    size=size, 
                    licensee_address=normalized_identifier
                )
            else:
                # Get licenses where user is the licensor (owner/seller)
                result = await list_licenses(
                    page=page, 
                    size=size, 
                    licensor_address=normalized_identifier
                )
        else:
            # ✅ It's a user ID - use buyer endpoint logic for PayPal users
            if as_licensee:
                # Use the buyer endpoint which supports user IDs
                result_data = await get_buyer_licenses(
                    buyer_identifier=wallet_address,
                    page=page,
                    size=size
                )
                # Convert to LicenseListResponse format
                from app.db.models import License, LicenseListResponse
                licenses = []
                logger.info(f"🔄 Converting {len(result_data.get('licenses', []))} license dicts to License objects")
                
                for idx, license_dict in enumerate(result_data.get("licenses", [])):
                    license_dict["license_id"] = _normalize_license_id(license_dict.get("license_id"))

                    # ✅ Ensure None values are converted to empty strings for Pydantic validation
                    if license_dict.get("buyer_address") is None:
                        license_dict["buyer_address"] = ""
                    if license_dict.get("owner_address") is None:
                        license_dict["owner_address"] = ""
                    
                    # ✅ Log the license dict before conversion
                    logger.info(f"📋 License {idx+1} dict keys: {list(license_dict.keys())}")
                    logger.info(f"📋 License {idx+1} data: token_id={license_dict.get('token_id')}, status={license_dict.get('status')}, is_active={license_dict.get('is_active')}, payment_method={license_dict.get('payment_method')}, owner_email={license_dict.get('owner_email')}, buyer_email={license_dict.get('buyer_email')}")
                    
                    try:
                        license_obj = License(**license_dict)
                        licenses.append(license_obj)
                        logger.info(f"✅ Successfully converted license {idx+1} to License object")
                    except Exception as e:
                        logger.error(f"❌ Error converting license {idx+1} to License object: {e}")
                        logger.error(f"   License dict: {license_dict}")
                        logger.error(f"   Exception type: {type(e)}, details: {str(e)}", exc_info=True)
                        continue
                
                logger.info(f"✅ Successfully converted {len(licenses)}/{len(result_data.get('licenses', []))} licenses")
                
                result = LicenseListResponse(
                    licenses=licenses,
                    total=result_data.get("total", len(licenses)),
                    page=page,
                    size=size,
                    has_next=result_data.get("has_next", False)
                )
                
                logger.info(f"📤 Returning LicenseListResponse with {len(licenses)} licenses")
            else:
                # For licensor (seller), use list_licenses with licensee_id
                result = await list_licenses(
                    page=page, 
                    size=size, 
                    licensor_id=wallet_address
                )
            
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user licenses for {wallet_address}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get user licenses: {str(e)}")
    
@router.get("/{license_id}/info")
async def get_license_info_from_blockchain(license_id: int):
    """Get license info directly from blockchain"""
    try:
        # ✅ license_id IS the blockchain license ID (no separate field needed)
        db_licenses = get_license_collection()
        db_license = await db_licenses.find_one({"license_id": license_id})
        
        # ✅ Use license_id directly as blockchain license ID
        blockchain_license_id = license_id
        logger.info(f"🔍 Fetching blockchain license info for license_id: {license_id} (blockchain ID: {blockchain_license_id})")
        
        # Get from blockchain using the license_id (which is the blockchain license ID)
        bc_license = await web3_service.get_license_info(blockchain_license_id)
        if not bc_license:
            # Check if license exists in database but not on blockchain
            error_detail = f"License {license_id} not found on blockchain"
            if db_license:
                if db_license.get("status") == "PENDING":
                    error_detail += ". License transaction is still pending confirmation."
                elif db_license.get("transaction_hash"):
                    error_detail += f". Transaction hash: {db_license.get('transaction_hash')}. The transaction may have failed or the license was never created on blockchain."
                else:
                    error_detail += ". No blockchain transaction found for this license."
            else:
                error_detail += ". License not found in database either."
            
            raise HTTPException(status_code=404, detail=error_detail)

        # Format response
        license_info = {
            "success": True,
            "license_id": license_id,
            "token_id": bc_license["token_id"],
            "owner_address": bc_license["owner"],
            "buyer_address": bc_license["buyer"],
            "license_type": ["LINK_ONLY", "ACCESS_WITH_WM", "FULL_ACCESS"][bc_license["license_type"]],
            "actual_amount_wei": str(bc_license["actual_amount"]),
            "license_fee_wei": str(bc_license["license_fee"]),
            "total_amount_wei": str(bc_license["total_amount"]),
            "purchase_time": bc_license["purchase_time"],
            "is_active": bc_license["is_active"],
            "source": "blockchain",
            "license": {  # ✅ Wrap in license object for frontend compatibility
                "license_id": license_id,
                "token_id": bc_license["token_id"],
                "owner_address": bc_license["owner"],
                "buyer_address": bc_license["buyer"],
                "license_type": ["LINK_ONLY", "ACCESS_WITH_WM", "FULL_ACCESS"][bc_license["license_type"]],
                "actual_amount_wei": str(bc_license["actual_amount"]),
                "license_fee_wei": str(bc_license["license_fee"]),
                "total_amount_wei": str(bc_license["total_amount"]),
                "purchase_time": bc_license["purchase_time"],
                "is_active": bc_license["is_active"],
            }
        }
        
        # Add database info if available
        if db_license:
            license_info["database_info"] = {
                "status": db_license.get("status"),
                "created_at": db_license.get("created_at"),
                "payment_method": db_license.get("payment_method", "crypto"),
                "transaction_hash": db_license.get("transaction_hash")
            }
            license_info["license"]["database_info"] = license_info["database_info"]
            license_info["license"]["transaction_hash"] = db_license.get("transaction_hash")
            license_info["transaction_hash"] = db_license.get("transaction_hash")
        
        return license_info

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting license info: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# @router.post("/grant", response_model=dict)
# async def grant_license(
#     license_data: LicenseCreate,
#     current_user: dict = Depends(get_current_user)
# ):
#     try:
#         db_licenses = get_license_collection()
#         db_artworks = get_artwork_collection()

#         artwork_doc = await db_artworks.find_one({"token_id": license_data.token_id})
#         if not artwork_doc:
#             raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

#         if artwork_doc["owner_address"].lower() != current_user.get('wallet_address', '').lower():
#             raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only ticket owner can grant licenses")

#         license_count = await db_licenses.count_documents({}) + 1

#         max_retries = 3
#         tx_data = None
#         for attempt in range(max_retries):
#             try:
#                 tx_data = await web3_service.prepare_license_transaction(
#                     license_data.token_id,
#                     license_data.licensee_address,
#                     license_data.duration_days,
#                     license_data.terms_hash,
#                     license_data.license_type.value,
#                     current_user.get("wallet_address")
#                 )
#                 break
#             except Exception as e:
#                 if attempt == max_retries - 1:
#                     raise e
#                 logger.warning(f"Attempt {attempt + 1} failed, retrying: {e}")
#                 await asyncio.sleep(1)

#         if not tx_data:
#             raise HTTPException(status_code=500, detail="Failed to prepare transaction after multiple attempts")

#         start_date = datetime.utcnow()
#         end_date = start_date + timedelta(days=license_data.duration_days)
#         fee_eth = 0.1

#         license_dict = {
#             "license_id": license_count,
#             "token_id": license_data.token_id,
#             "licensee_address": license_data.licensee_address.lower(),
#             "licensor_address": current_user.get("wallet_address").lower(),
#             "start_date": start_date,
#             "end_date": end_date,
#             "terms_hash": license_data.terms_hash,
#             "license_type": license_data.license_type,
#             "is_active": True,
#             "fee_paid": fee_eth,
#             "created_at": datetime.utcnow(),
#             "updated_at": datetime.utcnow(),
#             "transaction_data": tx_data
#         }

#         license_doc = LicenseInDB.from_mongo(license_dict)
#         result = await db_licenses.insert_one(license_doc.model_dump(by_alias=True, exclude={"id"}))

#         logger.info(f"Created license document with ID: {result.inserted_id}")

#         return {
#             "success": True,
#             "license_id": license_count,
#             "transaction_data": tx_data,
#             "fee": fee_eth
#         }

#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error granting license: {e}", exc_info=True)
#         raise HTTPException(status_code=500, detail=f"Failed to grant license: {str(e)}")


@router.post("/{license_id}/revoke", response_model=dict)
async def revoke_license(
    license_id: int,
    current_user: dict = Depends(get_current_user)
):
    try:
        db_licenses = get_license_collection()
        db_artworks = get_artwork_collection()

        license_doc = await db_licenses.find_one({"license_id": license_id})
        if not license_doc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="License not found")
        
        # ✅ Check ownership: Support both crypto (address) and PayPal (user_id) licenses
        payment_method = license_doc.get("payment_method", "crypto")
        is_owner = False
        
        if payment_method == "paypal":
            # ✅ PayPal license: Check owner_id
            owner_id = license_doc.get("owner_id")
            if not owner_id:
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="License missing owner_id")
            
            # Get current user info
            current_user_id = current_user.get("user_id") or current_user.get("id") or current_user.get("_id")
            current_user_email = current_user.get("email")
            
            # Convert both to strings for comparison
            owner_id_str = str(owner_id)
            current_user_id_str = str(current_user_id) if current_user_id else None
            
            logger.info(f"🔍 PayPal license ownership check - License owner_id: {owner_id_str} (type: {type(owner_id)}), Current user_id: {current_user_id_str}, Current email: {current_user_email}")
            
            # Strategy 1: Direct string comparison
            if current_user_id_str:
                is_owner = owner_id_str == current_user_id_str
                if is_owner:
                    logger.info(f"✅ Direct string match: {owner_id_str} == {current_user_id_str}")
            
            # Strategy 2: Look up owner user document and compare all possible ID fields
            if not is_owner:
                users_collection = get_user_collection()
                from bson import ObjectId
                
                # Try to find owner user by owner_id
                owner_user = None
                try:
                    # Try owner_id as ObjectId
                    if ObjectId.is_valid(owner_id_str):
                        owner_user = await users_collection.find_one({"_id": ObjectId(owner_id_str)})
                    # Try owner_id as user_id field
                    if not owner_user:
                        owner_user = await users_collection.find_one({"user_id": owner_id_str})
                    # Try owner_id as string _id
                    if not owner_user:
                        owner_user = await users_collection.find_one({"_id": owner_id_str})
                except Exception as e:
                    logger.warning(f"Error looking up owner user by owner_id: {e}")
                
                if owner_user:
                    # Get all possible ID fields from owner user
                    owner_user_ids = {
                        str(owner_user.get("_id", "")),
                        str(owner_user.get("user_id", "")),
                        str(owner_user.get("id", ""))
                    }
                    # Remove empty strings
                    owner_user_ids = {id_val for id_val in owner_user_ids if id_val and id_val != "None"}
                    
                    # Get all possible ID fields from current user
                    current_user_ids = set()
                    if current_user_id_str:
                        current_user_ids.add(current_user_id_str)
                    if current_user_email:
                        # Also try to find current user by email and get their IDs
                        try:
                            current_user_doc = await users_collection.find_one({"email": current_user_email})
                            if current_user_doc:
                                current_user_ids.add(str(current_user_doc.get("_id", "")))
                                current_user_ids.add(str(current_user_doc.get("user_id", "")))
                                current_user_ids.add(str(current_user_doc.get("id", "")))
                        except Exception as e:
                            logger.warning(f"Error looking up current user by email: {e}")
                    
                    # Remove empty strings
                    current_user_ids = {id_val for id_val in current_user_ids if id_val and id_val != "None"}
                    
                    # Check if any IDs match
                    is_owner = bool(owner_user_ids & current_user_ids)
                    
                    # Strategy 3: If still not matched, try email comparison
                    if not is_owner and current_user_email:
                        owner_email = owner_user.get("email")
                        if owner_email and owner_email.lower() == current_user_email.lower():
                            is_owner = True
                            logger.info(f"✅ Email match: {owner_email} == {current_user_email}")
                    
                    logger.info(f"🔍 Owner user IDs: {owner_user_ids}, Current user IDs: {current_user_ids}, Match: {is_owner}")
                else:
                    logger.warning(f"⚠️ Could not find owner user document for owner_id: {owner_id_str}")
                    # Last resort: Try to find owner by email if we have current_user_email
                    if current_user_email:
                        try:
                            owner_user_by_email = await users_collection.find_one({"email": current_user_email})
                            if owner_user_by_email:
                                owner_user_by_email_id = str(owner_user_by_email.get("_id", ""))
                                owner_user_by_email_user_id = str(owner_user_by_email.get("user_id", ""))
                                # Check if any ID matches
                                if (owner_user_by_email_id == owner_id_str or 
                                    owner_user_by_email_user_id == owner_id_str):
                                    is_owner = True
                                    logger.info(f"✅ Found owner by email match: {current_user_email}, IDs: {owner_user_by_email_id}, {owner_user_by_email_user_id}")
                            
                            # Also check ticket document for owner_id match
                            if not is_owner:
                                artwork_doc = await db_artworks.find_one({"token_id": license_doc.get("token_id")})
                                if artwork_doc:
                                    artwork_owner_id = artwork_doc.get("owner_id")
                                    if artwork_owner_id:
                                        artwork_owner_id_str = str(artwork_owner_id)
                                        if artwork_owner_id_str == owner_id_str:
                                            # Check if current user is the ticket owner
                                            artwork_owner_user = await users_collection.find_one({"_id": ObjectId(artwork_owner_id_str) if ObjectId.is_valid(artwork_owner_id_str) else None})
                                            if artwork_owner_user and artwork_owner_user.get("email") == current_user_email:
                                                is_owner = True
                                                logger.info(f"✅ Found owner via ticket document: {current_user_email}")
                        except Exception as e:
                            logger.warning(f"Error in email fallback lookup: {e}")
            
            if not is_owner:
                logger.error(f"❌ Ownership check failed - License owner_id: {owner_id_str}, Current user_id: {current_user_id_str}, Current email: {current_user_email}")
                # Log the full license document for debugging
                logger.error(f"📄 Full license document: {license_doc}")
                logger.error(f"👤 Full current_user: {current_user}")
        else:
            # ✅ Crypto license: Check licensor_address or owner_address
            licensor_address = license_doc.get("licensor_address") or license_doc.get("owner_address")
            if not licensor_address:
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="License missing owner address")
            
            # Get current user's wallet address
            user_wallet = None
            if hasattr(current_user, 'wallet_address'):
                user_wallet = current_user.get("wallet_address")
            elif isinstance(current_user, dict) and 'wallet_address' in current_user:
                user_wallet = current_user['wallet_address']
            
            if not user_wallet:
                logger.error(f"❌ Crypto user missing wallet_address in current_user: {current_user}")
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="User authentication error: missing wallet_address")
            
            is_owner = licensor_address.lower() == user_wallet.lower()
            logger.info(f"🔍 Crypto license ownership check - License owner: {licensor_address}, Current user: {user_wallet}, Is owner: {is_owner}")
        
        if not is_owner:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only license owner can revoke")

        if not license_doc.get("is_active", False):
            raise HTTPException(status_code=400, detail="License is already revoked")

        # ✅ For crypto licenses: Prepare blockchain transaction
        if payment_method == "crypto" or not payment_method:
            try:
                token_id = license_doc.get("token_id")
                licensee_address = license_doc.get("buyer_address") or license_doc.get("licensee_address")
                
                if not token_id or not licensee_address:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="License missing token_id or licensee_address for blockchain revocation"
                    )
                
                # Prepare blockchain transaction
                tx_data = await web3_service.revoke_license(
                    token_id=token_id,
                    license_id=license_id,  # ✅ Add this - required parameter
                    licensee_address=licensee_address,
                    from_address=user_wallet
                )
                
                logger.info(f"✅ Prepared blockchain revocation transaction for license {license_id}")
                
                # Return transaction data for frontend to sign
                return {
                    "success": True,
                    "requires_blockchain": True,
                    "transaction": tx_data,
                    "message": "Please sign the transaction in your wallet to revoke the license on blockchain",
                    "license_id": license_id,
                    "token_id": token_id
                }
                
            except Exception as e:
                logger.error(f"❌ Error preparing blockchain revocation: {e}", exc_info=True)
                # Fallback: Still update database even if blockchain fails
                logger.warning(f"⚠️ Blockchain revocation failed, updating database only: {e}")
        
        # ✅ For PayPal licenses or if blockchain preparation fails: Update database directly
        update_result = await db_licenses.update_one(
            {"license_id": license_id},
            {
                "$set": {
                    "is_active": False,
                    "updated_at": datetime.utcnow(),
                    "revoked_at": datetime.utcnow()
                }
            }
        )

        if update_result.modified_count == 0:
            raise HTTPException(status_code=500, detail="Failed to update license status")

        token_id = license_doc.get("token_id")
        active_licenses = await db_licenses.count_documents({
            "token_id": token_id,
            "is_active": True,
            "end_date": {"$gt": datetime.utcnow()}
        })

        await db_artworks.update_one(
            {"token_id": token_id},
            {"$set": {"is_licensed": active_licenses > 0, "updated_at": datetime.utcnow()}}
        )

        user_identifier = current_user.get("user_id") or current_user.get("email") or current_user.get("wallet_address") or "unknown"
        logger.info(f"✅ Successfully revoked license {license_id} for user {user_identifier} (payment_method: {payment_method})")

        return {
            "success": True,
            "message": "License revoked successfully",
            "license_id": license_id,
            "remaining_active_licenses": active_licenses,
            "requires_blockchain": False
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error revoking license {license_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to revoke license: {str(e)}")
@router.post("/{license_id}/revoke/confirm", response_model=dict)
async def confirm_revoke_license(
    license_id: int,
    confirmation_data: dict,
    current_user: dict = Depends(get_current_user)
):
    """Confirm license revocation after blockchain transaction"""
    try:
        tx_hash = confirmation_data.get("tx_hash")
        if not tx_hash:
            raise HTTPException(status_code=400, detail="Missing transaction hash")

        # Verify transaction on blockchain
        tx_receipt = await web3_service.get_transaction_receipt(tx_hash)
        if not tx_receipt:
            raise HTTPException(status_code=400, detail="Transaction not found on blockchain")
        
        if tx_receipt.get("status") != 1:
            raise HTTPException(status_code=400, detail="Transaction failed on blockchain")

        db_licenses = get_license_collection()
        db_artworks = get_artwork_collection()

        license_doc = await db_licenses.find_one({"license_id": license_id})
        if not license_doc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="License not found")

        # ✅ Decode LicenseRevoked event from transaction logs
        # ✅ Decode LicenseRevoked event from transaction logs
        from web3 import Web3
        event_signature_hash = Web3.keccak(text="LicenseRevoked(uint256,uint256,address)").hex()
        revoked_license_id = None  # ✅ Actual blockchain licenseId
        revoked_token_id = None
        revoked_licensee = None
        
        for log in tx_receipt.get("logs", []):
            if len(log.get("topics", [])) >= 4:
                # Check if this is LicenseRevoked event
                if log.get("topics", [0]) == event_signature_hash:
                    # Decode topics: [0]=event_sig, [1]=licenseId, [2]=tokenId, [3]=licensee
                    revoked_license_id = int(log.get("topics", [1]), 16)  # ✅ licenseId from topic 1
                    revoked_token_id = int(log.get("topics", [2]), 16)  # tokenId from topic 2
                    revoked_licensee = Web3.to_checksum_address("0x" + log.get("topics", [3])[-40:])  # licensee from topic 3
                    logger.info(f"✅ LicenseRevoked event decoded - licenseId: {revoked_license_id}, tokenId: {revoked_token_id}, licensee: {revoked_licensee}")
                    break
        
        # ✅ Verify the revoked license matches our database record
        if revoked_token_id and revoked_licensee:
            db_token_id = license_doc.get("token_id")
            db_licensee = (license_doc.get("buyer_address") or license_doc.get("licensee_address", "")).lower()
            
            if revoked_token_id != db_token_id or revoked_licensee.lower() != db_licensee:
                logger.warning(f"⚠️ Event mismatch - Event: tokenId={revoked_token_id}, licensee={revoked_licensee}, DB: tokenId={db_token_id}, licensee={db_licensee}")
        
        # ✅ Verify blockchain state using actual licenseId from event
        blockchain_verified = False
        if revoked_license_id:
            try:
                blockchain_info = await web3_service.get_license_info(revoked_license_id)
                if blockchain_info:
                    blockchain_verified = blockchain_info.get("is_active") == False
                    logger.info(f"✅ Blockchain verification - licenseId {revoked_license_id} is_active: {blockchain_info.get('is_active')}")
                    if blockchain_info.get("is_active"):
                        logger.warning(f"⚠️ License {revoked_license_id} still shows as active on blockchain after revocation!")
            except Exception as verify_error:
                logger.warning(f"⚠️ Could not verify blockchain state: {verify_error}")

        # Update license status
        update_result = await db_licenses.update_one(
            {"license_id": license_id},
            {
                "$set": {
                    "is_active": False,
                    "updated_at": datetime.utcnow(),
                    "revoked_at": datetime.utcnow(),
                    "revoke_transaction_hash": tx_hash
                }
            }
        )

        if update_result.modified_count == 0:
            raise HTTPException(status_code=500, detail="Failed to update license status")

        token_id = license_doc.get("token_id")
        active_licenses = await db_licenses.count_documents({
            "token_id": token_id,
            "is_active": True,
            "end_date": {"$gt": datetime.utcnow()}
        })

        await db_artworks.update_one(
            {"token_id": token_id},
            {"$set": {"is_licensed": active_licenses > 0, "updated_at": datetime.utcnow()}}
        )

        logger.info(f"✅ Confirmed blockchain revocation for license {license_id} via transaction {tx_hash}")

        return {
            "success": True,
            "message": "License revoked successfully on blockchain",
            "license_id": license_id,
            "blockchain_license_id": revoked_license_id,  # ✅ Actual blockchain licenseId
            "transaction_hash": tx_hash,
            "remaining_active_licenses": active_licenses,
            "blockchain_verified": blockchain_verified,
            "event_decoded": {
                "blockchain_license_id": revoked_license_id,
                "token_id": revoked_token_id,
                "licensee": revoked_licensee
            } if revoked_license_id else None
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error confirming license revocation {license_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to confirm license revocation: {str(e)}")
@router.get("/", response_model=LicenseListResponse)
async def list_licenses(
    page: int = 1,
    size: int = 20,
    licensee_address: Optional[str] = None,
    licensor_address: Optional[str] = None,
    licensee_id: Optional[str] = None,
    licensor_id: Optional[str] = None,
    token_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    raw_filter: Optional[Dict] = None
):
    try:
        db_licenses = get_license_collection()
        users_collection = get_user_collection()
        filter_query = {}

        # ✅ Apply raw_filter if provided
        if raw_filter:
            filter_query.update(raw_filter)
        
        # ✅ Filter by token_id if provided
        if token_id is not None:
            # Ensure token_id is an integer, but also search for string version in case of data inconsistency
            token_id_int = int(token_id)
            # Use $in to match both int and string versions
            filter_query["token_id"] = {"$in": [token_id_int, str(token_id_int)]}
            logger.info(f"🔍 Filtering licenses by token_id: {token_id_int} (searching both int and string)")
        
        # ✅ Filter by is_active if provided
        if is_active is not None:
            filter_query["is_active"] = is_active
        
        # Build filter with actual database field names
        or_conditions = []
        
        if licensee_address:
            or_conditions.append({"buyer_address": licensee_address.lower()})
        if licensee_id:
            # ✅ Handle multiple user ID formats for licensee (similar to buyer endpoint)
            user = None
            if ObjectId.is_valid(licensee_id):
                user = await users_collection.find_one({"_id": ObjectId(licensee_id)})
            if not user:
                user = await users_collection.find_one({"user_id": licensee_id})
            if not user:
                user = await users_collection.find_one({"_id": licensee_id})
            if not user:
                user = await users_collection.find_one({"id": licensee_id})
            
            if user:
                # Get all possible user ID formats
                possible_buyer_ids = set()
                if user.get('user_id'):
                    possible_buyer_ids.add(str(user.get('user_id')))
                if user.get('id'):
                    possible_buyer_ids.add(str(user.get('id')))
                if user.get('_id'):
                    possible_buyer_ids.add(str(user.get('_id')))
                possible_buyer_ids.add(licensee_id)
                
                # Search with all possible buyer_id formats
                buyer_or_conditions = [{"buyer_id": bid} for bid in possible_buyer_ids]
                or_conditions.extend(buyer_or_conditions)
                
                # Also include wallet address if user has one
                wallet_address = user.get('wallet_address')
                if wallet_address:
                    or_conditions.append({"buyer_address": wallet_address.lower()})
            else:
                # Fallback: try as direct buyer_id
                or_conditions.append({"buyer_id": licensee_id})
                
        if licensor_address:
            or_conditions.append({"owner_address": licensor_address.lower()})
        if licensor_id:
            # ✅ Handle multiple user ID formats for licensor (similar to buyer endpoint)
            user = None
            if ObjectId.is_valid(licensor_id):
                user = await users_collection.find_one({"_id": ObjectId(licensor_id)})
            if not user:
                user = await users_collection.find_one({"user_id": licensor_id})
            if not user:
                user = await users_collection.find_one({"_id": licensor_id})
            if not user:
                user = await users_collection.find_one({"id": licensor_id})
            
            if user:
                # Get all possible user ID formats
                possible_owner_ids = set()
                if user.get('user_id'):
                    possible_owner_ids.add(str(user.get('user_id')))
                if user.get('id'):
                    possible_owner_ids.add(str(user.get('id')))
                if user.get('_id'):
                    possible_owner_ids.add(str(user.get('_id')))
                possible_owner_ids.add(licensor_id)
                
                # Search with all possible owner_id formats
                owner_or_conditions = [{"owner_id": oid} for oid in possible_owner_ids]
                or_conditions.extend(owner_or_conditions)
                
                # Also include wallet address if user has one
                wallet_address = user.get('wallet_address')
                if wallet_address:
                    or_conditions.append({"owner_address": wallet_address.lower()})
            else:
                # Fallback: try as direct owner_id
                or_conditions.append({"owner_id": licensor_id})
            
        if or_conditions:
            if "$or" in filter_query:
                # ✅ Merge existing $or from raw_filter with newly built or_conditions using $and
                original_or = filter_query.pop("$or")
                if "$and" not in filter_query:
                    filter_query["$and"] = []
                filter_query["$and"].append({"$or": original_or})
                filter_query["$and"].append({"$or": or_conditions})
            else:
                filter_query["$or"] = or_conditions

        # 🔍 Debugging: Log the final constructed query
        logger.info(f"🔍 FINAL list_licenses MongoDB Query: {filter_query}")

        # ⚡ OPTIMIZED: Get total count and licenses in parallel
        total_task = db_licenses.count_documents(filter_query)
        skip = (page - 1) * size
        licenses_task = db_licenses.find(filter_query).skip(skip).limit(size).sort("purchase_time", -1).to_list(length=size)
        
        # Execute both queries in parallel
        total, licenses_data = await asyncio.gather(total_task, licenses_task)
        has_next = (page * size) < total

        # ⚡ OPTIMIZED: Batch fetch all user emails at once (fixes N+1 problem)
        user_email_cache = {}
        owner_ids = set()
        buyer_ids = set()
        
        # Collect all unique user IDs that need email lookup
        for doc in licenses_data:
            payment_method = doc.get("payment_method", "crypto")
            if payment_method == "paypal":
                owner_id = doc.get("owner_id")
                buyer_id = doc.get("buyer_id")
                if owner_id:
                    owner_ids.add(str(owner_id))
                if buyer_id:
                    buyer_ids.add(str(buyer_id))
        
        # Batch fetch all users at once
        all_user_ids = owner_ids | buyer_ids
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
                    email = user.get("email")
                    # ⚡ OPTIMIZED: Cache email by all possible ID formats for lookup
                    user_email_cache[str(user["_id"])] = email
                    if user.get("user_id"):
                        user_email_cache[str(user["user_id"])] = email
                    if user.get("id"):
                        user_email_cache[str(user["id"])] = email
            
            # Batch fetch by string _id for remaining IDs
            remaining_by_string = set(string_id_queries) - {str(k) for k in user_email_cache.keys()}
            if remaining_by_string:
                string_cursor = users_collection.find({"_id": {"$in": list(remaining_by_string)}})
                async for user in string_cursor:
                    email = user.get("email")
                    user_email_cache[str(user["_id"])] = email
                    if user.get("user_id"):
                        user_email_cache[str(user["user_id"])] = email
                    if user.get("id"):
                        user_email_cache[str(user["id"])] = email
            
            # Batch fetch by user_id field for any still missing
            still_missing = all_user_ids - {str(k) for k in user_email_cache.keys()}
            if still_missing:
                user_id_cursor = users_collection.find({"user_id": {"$in": list(still_missing)}})
                async for user in user_id_cursor:
                    email = user.get("email")
                    if user.get("user_id"):
                        user_email_cache[str(user["user_id"])] = email
                        user_email_cache[str(user["_id"])] = email
                    if user.get("id"):
                        user_email_cache[str(user["id"])] = email
            
            # Batch fetch by id field for any still missing
            still_missing = all_user_ids - {str(k) for k in user_email_cache.keys()}
            if still_missing:
                id_cursor = users_collection.find({"id": {"$in": list(still_missing)}})
                async for user in id_cursor:
                    email = user.get("email")
                    if user.get("id"):
                        user_email_cache[str(user["id"])] = email
                        user_email_cache[str(user["_id"])] = email
                    if user.get("user_id"):
                        user_email_cache[str(user["user_id"])] = email
        
        licenses = []
        for doc in licenses_data:
            try:
                # ⚡ OPTIMIZED: Get emails from cache (no additional queries)
                owner_email = None
                buyer_email = None
                owner_id = doc.get("owner_id")
                buyer_id = doc.get("buyer_id")
                payment_method = doc.get("payment_method", "crypto")
                
                if payment_method == "paypal":
                     # ✅ Priority 1: Get email directly from license document (if stored)
                    buyer_email = doc.get("buyer_email")
                    owner_email = doc.get("owner_email")
                    
                    # ✅ Priority 2: If not in document, try cache
                    if not buyer_email and buyer_id:
                        buyer_email = user_email_cache.get(str(buyer_id))
                    if not owner_email and owner_id:
                        owner_email = user_email_cache.get(str(owner_id))
                    
                    # ✅ Priority 3: If still not found, fetch directly (fallback)
                    if not buyer_email and buyer_id:
                        try:
                            buyer_user = None
                            if ObjectId.is_valid(str(buyer_id)):
                                buyer_user = await users_collection.find_one({"_id": ObjectId(buyer_id)})
                            if not buyer_user:
                                buyer_user = await users_collection.find_one({"_id": buyer_id})
                            if not buyer_user:
                                buyer_user = await users_collection.find_one({"user_id": buyer_id})
                            if not buyer_user:
                                buyer_user = await users_collection.find_one({"id": buyer_id})
                            
                            if buyer_user:
                                buyer_email = buyer_user.get("email")
                                # Cache it for future use
                                if buyer_email:
                                    user_email_cache[str(buyer_id)] = buyer_email
                        except Exception as e:
                            logger.warning(f"⚠️ Failed to fetch buyer email for {buyer_id}: {e}")
                    
                    if not owner_email and owner_id:
                        try:
                            owner_user = None
                            if ObjectId.is_valid(str(owner_id)):
                                owner_user = await users_collection.find_one({"_id": ObjectId(owner_id)})
                            if not owner_user:
                                owner_user = await users_collection.find_one({"_id": owner_id})
                            if not owner_user:
                                owner_user = await users_collection.find_one({"user_id": owner_id})
                            if not owner_user:
                                owner_user = await users_collection.find_one({"id": owner_id})
                            
                            if owner_user:
                                owner_email = owner_user.get("email")
                                # Cache it for future use
                                if owner_email:
                                    user_email_cache[str(owner_id)] = owner_email
                        except Exception as e:
                            logger.warning(f"⚠️ Failed to fetch owner email for {owner_id}: {e}")
                
                # ✅ ENSURE PROPER TYPE CONVERSION BEFORE CREATING LICENSE OBJECT
                license_dict = {
                    "license_id": doc.get("license_id", 0),
                    "token_id": doc.get("token_id", 0),
                    "buyer_id": doc.get("buyer_id"),
                    "owner_id": owner_id,  # ✅ Add owner_id for PayPal licenses
                    "buyer_address": doc.get("buyer_address") or "",  # ✅ Handle None for PayPal licenses
                    "owner_address": doc.get("owner_address") or "",  # ✅ Handle None for PayPal licenses
                    "owner_email": owner_email,  # ✅ Owner email for PayPal licenses
                    "buyer_email": buyer_email,  # ✅ Buyer email for PayPal licenses (for owner view)
                    "license_type": doc.get("license_type", "LINK_ONLY"),
                    
                    # ✅ CONVERT FLOATS TO STRINGS
                    "total_amount_eth": str(doc.get("total_amount_eth", "0")),
                    "total_amount_wei": doc.get("total_amount_wei", "0"),
                    "total_amount_usd": doc.get("total_amount_usd"),  # ✅ Add USD amount for PayPal licenses
                    "is_active": doc.get("is_active", False),
                    
                    # ✅ CONVERT DATETIME TO STRING
                    "purchase_time": doc.get("purchase_time", datetime.utcnow()).isoformat() if isinstance(doc.get("purchase_time"), datetime) else str(doc.get("purchase_time", "")),
                    
                    # ✅ Preserve actual status from database (don't override PENDING_APPROVAL)
                    "status": doc.get("status") or ("CONFIRMED" if doc.get("is_active") else "PENDING"),  # ✅ Better status handling
                    "duration_days": doc.get("duration_days", 30),
                    "artwork_price_eth": float(doc.get("total_amount_eth", 0)) if doc.get("total_amount_eth") else 0.0,
                    "payment_method": payment_method,
                    "transaction_hash": doc.get("transaction_hash"),
                    "network": doc.get("network"),
                    "algorand_group_id": doc.get("algorand_group_id"),
                    "algorand_license_reference": doc.get("algorand_license_reference"),
                    
                    # ✅ CONVERT OPTIONAL AMOUNT FIELDS
                    "actual_amount_eth": str(doc.get("actual_amount_eth", doc.get("total_amount_eth", "0"))),
                    "license_fee_eth": str(doc.get("license_fee_eth", "0")),
                    "actual_amount_wei": doc.get("actual_amount_wei", doc.get("total_amount_wei", "0")),
                    "license_fee_wei": doc.get("license_fee_wei", "0"),
                }
                
                # Handle other date fields
                for field in ["start_date", "end_date", "created_at", "updated_at"]:
                    if field in doc and isinstance(doc[field], datetime):
                        license_dict[field] = doc[field].isoformat()
                    else:
                        license_dict[field] = doc.get(field, "")
                
                license_obj = License(**license_dict)
                licenses.append(license_obj)
                
            except Exception as e:
                logger.error(f"Skipping invalid license document {doc.get('license_id', 'unknown')}: {str(e)}")
                continue

        return LicenseListResponse(
            licenses=licenses,
            total=total,
            page=page,
            size=size,
            has_next=has_next
        )

    except Exception as e:
        logger.error(f"Error listing licenses: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list licenses: {str(e)}")

# ✅ Get pending license requests for owner (approval workflow)
# IMPORTANT: This route must be defined BEFORE /{license_id} routes to avoid route conflicts
@router.get("/pending-requests", response_model=LicenseListResponse)
async def get_pending_license_requests(
    current_user: dict = Depends(get_current_user),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100)
):
    """Get pending license requests that need owner approval"""
    try:
        db_licenses = get_license_collection()
        users_collection = get_user_collection()
        artworks_collection = get_artwork_collection()
        
        # Get current user ID
        user_id = str(current_user.get('id', '') or current_user.get('_id', ''))
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")
        
        # Find all licenses where current user is the owner and status is PENDING_APPROVAL
        filter_query = {
            "owner_id": user_id,
            "status": "PENDING_APPROVAL",
            "payment_method": "paypal"
        }
        
        total = await db_licenses.count_documents(filter_query)
        has_next = (page * size) < total
        skip = (page - 1) * size
        
        cursor = db_licenses.find(filter_query).skip(skip).limit(size).sort("created_at", -1)
        licenses_data = await cursor.to_list(length=size)
        
        licenses = []
        for doc in licenses_data:
            try:
                # Get buyer info
                buyer_id = doc.get("buyer_id")
                buyer_info = None
                if buyer_id:
                    buyer_user = None
                    if ObjectId.is_valid(buyer_id):
                        buyer_user = await users_collection.find_one({"_id": ObjectId(buyer_id)})
                    if not buyer_user:
                        buyer_user = await users_collection.find_one({"user_id": buyer_id})
                    if not buyer_user:
                        buyer_user = await users_collection.find_one({"_id": buyer_id})
                    if buyer_user:
                        buyer_info = {
                            "email": buyer_user.get("email"),
                            "name": buyer_user.get("name") or buyer_user.get("username")
                        }
                
                # Get ticket info
                token_id = doc.get("token_id")
                artwork_info = None
                if token_id:
                    ticket = await artworks_collection.find_one({"token_id": token_id}, sort=[("_id", -1)])
                    if ticket:
                        artwork_info = {
                            "title": ticket.get("title"),
                            "image_url": ticket.get("image_url")
                        }
                
                license_dict = {
                    "license_id": doc.get("license_id", 0),
                    "token_id": token_id,
                    "buyer_id": buyer_id,
                    "owner_id": doc.get("owner_id"),
                    "buyer_address": doc.get("buyer_address") or "",
                    "owner_address": doc.get("owner_address") or "",
                    "license_type": doc.get("license_type", "LINK_ONLY"),
                    "total_amount_eth": str(doc.get("total_amount_eth", "0")),
                    "total_amount_wei": doc.get("total_amount_wei", "0"),
                    "total_amount_usd": doc.get("total_amount_usd"),
                    "is_active": False,  # Pending approval
                    "purchase_time": doc.get("purchase_time", datetime.utcnow()).isoformat() if isinstance(doc.get("purchase_time"), datetime) else str(doc.get("purchase_time", "")),
                    "status": "PENDING_APPROVAL",
                    "payment_method": doc.get("payment_method", "paypal"),
                    "paypal_order_id": doc.get("paypal_order_id"),
                    "created_at": doc.get("created_at", datetime.utcnow()).isoformat() if isinstance(doc.get("created_at"), datetime) else str(doc.get("created_at", "")),
                    "updated_at": doc.get("updated_at", datetime.utcnow()).isoformat() if isinstance(doc.get("updated_at"), datetime) else str(doc.get("updated_at", "")),
                    "buyer_info": buyer_info,  # ✅ Buyer details for owner to review
                    "artwork_info": artwork_info  # ✅ Ticket details
                }
                
                license_obj = License(**license_dict)
                licenses.append(license_obj)
            except Exception as e:
                logger.error(f"Skipping invalid license document {doc.get('license_id', 'unknown')}: {str(e)}")
                continue
        
        return LicenseListResponse(
            licenses=licenses,
            total=total,
            page=page,
            size=size,
            has_next=has_next
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting pending license requests: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get pending requests: {str(e)}")

# Get license by ID
@router.get("/{license_id}", response_model=License)
async def get_license(license_id: int):
    try:
        db_licenses = get_license_collection()

        license_doc = await db_licenses.find_one({"license_id": license_id})
        if not license_doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="License not found"
            )

        license_obj = LicenseInDB.from_mongo(license_doc)
        return License.from_mongo(license_doc)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting license {license_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get license: {str(e)}"
        )

# Get licenses for a specific ticket
def get_artwork_licenses_cache(artwork_id: str, page: int, size: int, active_only: bool) -> Optional[Dict]:
    """Get cached licenses for ticket"""
    key = cache.cache_key("artwork_licenses", artwork_id=artwork_id, page=page, size=size, active_only=active_only)
    return cache.get(key)

def set_artwork_licenses_cache(artwork_id: str, page: int, size: int, active_only: bool, data: Dict, ttl: int = 300):
    """Cache licenses for ticket"""
    key = cache.cache_key("artwork_licenses", artwork_id=artwork_id, page=page, size=size, active_only=active_only)
    return cache.set(key, data, ttl)

# Line 2592 - Update the get_artwork_licenses endpoint:
@router.get("/ticket/{artwork_id}", response_model=LicenseListResponse)
async def get_artwork_licenses(
    artwork_id: str,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    active_only: bool = Query(False)
):
    """Get all licenses for a specific ticket by artwork_id (MongoDB ID or token_id)"""
    try:
        # ✅ REDIS CACHE: Step 1 - Try to get from cache first
        cached_response = get_artwork_licenses_cache(artwork_id, page, size, active_only)
        if cached_response:
            logger.info(f"⚡ REDIS CACHE HIT - Returning cached licenses for ticket {artwork_id}")
            return LicenseListResponse(**cached_response)
        
        logger.info(f"💨 REDIS CACHE MISS - Fetching licenses for artwork_id: {artwork_id}")
        
        # Determine query filter (artwork_id or token_id fallback)
        filter_params = {"$or": []}
        
        # 1. Add Ticket Identifier searches
        if ObjectId.is_valid(artwork_id):
            filter_params["$or"].extend([
                {"artwork_id": artwork_id},
                {"artwork_id": ObjectId(artwork_id)}
            ])
        
        # 2. Add Token ID search fallback
        try:
            # Try to find the ticket to get its token_id
            artwork_query = {"title": artwork_id}
            if ObjectId.is_valid(artwork_id):
                artwork_query = {"_id": ObjectId(artwork_id)}
                
            artwork_doc = await get_artwork_collection().find_one(artwork_query)
            
            if artwork_doc and artwork_doc.get("token_id") is not None:
                tid = artwork_doc["token_id"]
                filter_params["$or"].extend([
                    {"token_id": tid},
                    {"token_id": str(tid)},
                    {"token_id": int(tid)}
                ])
                logger.info(f"🔍 Added token_id {tid} to search filter for ticket {artwork_id}")
            elif not ObjectId.is_valid(artwork_id):
                # Fallback for when artwork_id is already a number/token_id
                try:
                    tid = int(artwork_id)
                    filter_params["$or"].extend([{"token_id": tid}, {"token_id": str(tid)}])
                except ValueError:
                    pass
        except Exception as e:
            logger.warning(f"⚠️ Error resolving token_id for filter: {e}")

        # Final safety check: if $or is empty, use artwork_id directly
        if not filter_params["$or"]:
            filter_params = {"artwork_id": artwork_id}

        if active_only:
            filter_params["is_active"] = True

        # Log the filter params
        logger.info(f"📋 Filter params for license query: {filter_params}")
        
        # Fetch licenses from database
        result = await list_licenses(
            page=page,
            size=size,
            raw_filter=filter_params
        )
        
        # ✅ REDIS CACHE: Step 2 - Cache the response for 5 minutes (300 seconds)
        try:
            set_artwork_licenses_cache(artwork_id, page, size, active_only, result.model_dump(), ttl=300)
            logger.info(f"💾 Cached licenses for ticket {artwork_id} (TTL: 5 min)")
        except Exception as cache_error:
            logger.warning(f"⚠️ Failed to cache licenses: {cache_error}")
        
        logger.info(f"✅ Found {result.total} total licenses for ticket {artwork_id}, returning {len(result.licenses)} on page {page}")
        
        return result
    except Exception as e:
        logger.error(f"❌ Error fetching licenses for ticket {artwork_id}: {e}", exc_info=True)
        raise

# Get the current license fee for a specific license type
@router.get("/fee/{license_type}")
async def get_license_fee(license_type: str):
    try:
        if web3_service.demo_mode:
            fee_eth = 0.1
            return {
                "license_type": license_type,
                "fee_eth": fee_eth,
                "fee_wei": Web3.to_wei(fee_eth, 'ether'),
                "note": "Fixed fee for all license types"
            }

        contract = web3_service.get_contract()
        fee_wei = contract.functions.LICENSE_FEE().call()
        fee_eth = Web3.from_wei(fee_wei, 'ether')

        return {
            "license_type": license_type,
            "fee_eth": float(fee_eth),
            "fee_wei": fee_wei,
            "note": "Fixed fee for all license types"
        }

    except Exception as e:
        logger.error(f"Error getting license fee: {e}")
        return {
            "license_type": license_type,
            "fee_eth": 0.1,
            "fee_wei": Web3.to_wei(0.1, 'ether'),
            "note": "Using fallback fixed fee",
            "error": str(e)
        }
# drmbackend/app/api/v1/licenses.py - Add before the last endpoint

@router.post("/cleanup-pending")
async def cleanup_pending_licenses_endpoint(
    max_age_hours: int = Query(24, ge=1, le=168, description="Maximum age in hours (1-168)"),
    dry_run: bool = Query(False, description="If True, only count without deleting"),
    current_user: dict = Depends(get_current_user)
):
    """
    Manually trigger cleanup of old pending licenses.
    Only accessible to admins or for testing.
    """
    try:
        # Optional: Add admin check here
        if not current_user.get("is_admin"):
            raise HTTPException(status_code=403, detail="Admin access required")
        
        result = await cleanup_old_pending_licenses(
            max_age_hours=max_age_hours,
            dry_run=dry_run
        )
        
        return {
            "success": True,
            "message": f"Cleanup completed: {result.get('cleaned_count', 0)} licenses {'would be' if dry_run else 'were'} cleaned",
            **result
        }
        
    except Exception as e:
        logger.error(f"❌ Error in cleanup endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {str(e)}")

async def validate_and_cleanup_pending_license(license_doc: dict) -> bool:
    """
    Validate a pending license and clean it up if invalid.
    
    Returns:
        True if license is valid and should block new purchase
        False if license is invalid and was cleaned up (allow new purchase)
    """
    try:
        license_id = license_doc.get("license_id")
        transaction_hash = license_doc.get("transaction_hash")
        
        # ✅ Case 1: No transaction hash = User cancelled in MetaMask
        # Allow new purchase immediately
        if not transaction_hash:
            logger.info(f"🧹 Pending license #{license_id} has no transaction hash (user cancelled) - cleaning up")
            db_licenses = get_license_collection()
            await db_licenses.delete_one({"license_id": license_id})
            return False  # Allow new purchase
        
        # ✅ Case 2: Transaction hash exists - Check if transaction failed
        try:
            tx_receipt = await web3_service.get_transaction_receipt(transaction_hash)
            
            if not tx_receipt:
                # Transaction not found on blockchain (might be pending or failed)
                # Check transaction age - if older than 10 minutes, likely failed
                created_at = license_doc.get("created_at")
                if created_at:
                    age_minutes = (datetime.utcnow() - created_at).total_seconds() / 60
                    if age_minutes > 10:
                        logger.info(f"🧹 Pending license #{license_id} transaction not found after {age_minutes:.1f} minutes - cleaning up")
                        db_licenses = get_license_collection()
                        await db_licenses.delete_one({"license_id": license_id})
                        return False  # Allow new purchase
                
                # Transaction might still be pending (recent)
                logger.info(f"⏳ Pending license #{license_id} transaction still pending on blockchain")
                return True  # Block new purchase (transaction might confirm)
            
            # Transaction found - check status
            if tx_receipt.get("status") == 0:
                # Transaction failed on blockchain
                logger.info(f"🧹 Pending license #{license_id} transaction failed on blockchain - cleaning up")
                db_licenses = get_license_collection()
                await db_licenses.delete_one({"license_id": license_id})
                return False  # Allow new purchase
            
            # Transaction succeeded but license not confirmed - might be in progress
            logger.info(f"✅ Pending license #{license_id} transaction succeeded - license should be confirmed")
            return True  # Block new purchase (license should be confirmed soon)
            
        except Exception as tx_error:
            logger.warning(f"⚠️ Error checking transaction for license #{license_id}: {tx_error}")
            # If we can't check, be conservative - keep the pending license
            return True  # Block new purchase
        
    except Exception as e:
        logger.error(f"❌ Error validating pending license: {e}", exc_info=True)
        # On error, be conservative - keep the pending license
        return True  # Block new purchase
# ✅ Approve or reject license request
@router.post("/{license_id}/approve")
async def approve_license_request(
    license_id: int,
    action: str = Form(...),  # "approve" or "reject"
    current_user: dict = Depends(get_current_user)
):
    """Approve or reject a pending license request"""
    try:
        db_licenses = get_license_collection()
        artworks_collection = get_artwork_collection()
        users_collection = get_user_collection()
        
        if action not in ["approve", "reject"]:
            raise HTTPException(status_code=400, detail="Action must be 'approve' or 'reject'")
        
        # Get current user ID
        user_id = str(current_user.get('id', '') or current_user.get('_id', ''))
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")
        
        # Find the license
        license_doc = await db_licenses.find_one({"license_id": license_id})
        if not license_doc:
            raise HTTPException(status_code=404, detail="License not found")
        
        # Verify current user is the owner
        owner_id = license_doc.get("owner_id")
        if str(owner_id) != user_id:
            raise HTTPException(status_code=403, detail="Only the ticket owner can approve/reject license requests")
        
        # Verify license is pending approval
        if license_doc.get("status") != "PENDING_APPROVAL":
            raise HTTPException(
                status_code=400, 
                detail=f"License is not pending approval. Current status: {license_doc.get('status')}"
            )
        
        if action == "approve":
            # Approve the license
            await db_licenses.update_one(
                {"license_id": license_id},
                {
                    "$set": {
                        "is_active": True,
                        "status": "CONFIRMED",
                        "updated_at": datetime.utcnow(),
                        "approved_at": datetime.utcnow(),
                        "approved_by": user_id
                    }
                }
            )
            
            # ✅ CORRECT: Use unique artwork_id for status update instead of token_id
            artwork_id = license_doc.get("artwork_id")
            if artwork_id:
                # Support both ObjectId and string formats for the ticket document ID
                artwork_query = {"$or": [{"_id": artwork_id}]}
                if ObjectId.is_valid(artwork_id):
                    artwork_query["$or"].append({"_id": ObjectId(artwork_id)})
                    
                await artworks_collection.update_one(
                    artwork_query,
                    {"$set": {"is_licensed": True, "updated_at": datetime.utcnow()}}
                )
                logger.info(f"✅ Ticket {artwork_id} marked as is_licensed=True after manual approval")
            
            logger.info(f"✅ License {license_id} approved by owner {user_id}")

            # ✅ LOG TRANSACTION for artist earnings dashboard (PayPal/Manual)
            try:
                db_transactions = get_transaction_collection()
                
                # Fetch buyer ID from license doc
                buyer_user_id = license_doc.get("buyer_id")
                
                license_transaction = {
                    "transaction_hash": license_doc.get("paypal_order_id") or f"MANUAL-{license_id}",
                    "token_id": license_doc.get("token_id"),
                    "artwork_id": license_doc.get("artwork_id"),
                    "from_user_id": buyer_user_id,
                    "from_address": license_doc.get("buyer_address"),
                    "to_user_id": user_id, # Current user is the owner who approved
                    "to_address": license_doc.get("owner_address"),
                    "transaction_type": TransactionType.LICENSE_PAYMENT.value,
                    "status": TransactionStatus.CONFIRMED.value,
                    "value": str(license_doc.get("total_amount_usd") or "0"),
                    "currency": "USD",
                    "created_at": datetime.utcnow(),
                    "payment_method": license_doc.get("payment_method", "paypal")
                }
                await db_transactions.insert_one(license_transaction)
                logger.info(f"✅ LICENSE_PAYMENT (PayPal) transaction logged for license {license_id}")
            except Exception as log_error:
                logger.error(f"⚠️ Failed to log PayPal license transaction: {log_error}")
            
            return {
                "success": True,
                "message": "License approved successfully",
                "license_id": license_id,
                "status": "CONFIRMED"
            }
        else:
            # Reject the license
            await db_licenses.update_one(
                {"license_id": license_id},
                {
                    "$set": {
                        "is_active": False,
                        "status": "REJECTED",
                        "updated_at": datetime.utcnow(),
                        "rejected_at": datetime.utcnow(),
                        "rejected_by": user_id
                    }
                }
            )
            
            logger.info(f"❌ License {license_id} rejected by owner {user_id}")
            
            return {
                "success": True,
                "message": "License rejected",
                "license_id": license_id,
                "status": "REJECTED"
            }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing license approval/rejection: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to process request: {str(e)}")
