"""
PSL Entry X API Endpoints
=================================
Hackathon Demo: Dynamic QR-based stadium entry system.

Endpoints:
- GET  /psl/tickets           - List user's PSL tickets
- POST /psl/tickets/reveal    - Reveal dynamic QR for gate entry
- POST /psl/tickets/validate  - Validate QR at gate (scanner)
- GET  /psl/tickets/{id}      - Get single ticket details
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from bson import ObjectId

from app.api.v1.dependencies import get_current_user
from app.db.database import get_db
from app.core.config import settings
from services.psl_service import (
    generate_dynamic_qr,
    validate_qr,
    can_reveal_ticket,
    PSL_TICKET_CATEGORY
)

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/psl", tags=["PSL Entry X"])


def _resolve_ticket_image_url(ticket: dict) -> str:
    """Return the best available ticket image source across legacy/new fields."""
    psl_meta = ticket.get("psl_metadata") or {}
    metadata = ticket.get("metadata") or {}
    attributes = ticket.get("attributes") or {}

    candidates = [
        ticket.get("image_url"),
        ticket.get("image_ipfs_uri"),
        ticket.get("image_uri"),
        ticket.get("image"),
        ticket.get("thumbnail_url"),
        psl_meta.get("image_url"),
        psl_meta.get("image"),
        metadata.get("image_url"),
        metadata.get("image"),
        attributes.get("image"),
    ]

    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return ""


async def _resolve_artwork_for_reveal(db, ticket_id: str, license_id: Optional[str] = None):
    """Resolve ticket for reveal flow across mixed legacy/new identifier formats."""
    candidate_filters = []

    if ticket_id:
        candidate_filters.append({"_id": ticket_id})
        candidate_filters.append({"token_id": ticket_id})
        candidate_filters.append({"nft_token_id": ticket_id})
        if ObjectId.is_valid(ticket_id):
            candidate_filters.insert(0, {"_id": ObjectId(ticket_id)})

    for artwork_filter in candidate_filters:
        query = {**artwork_filter, "is_deleted": {"$ne": True}}
        ticket = await db.tickets.find_one(query)
        if ticket:
            return ticket

    if license_id and ObjectId.is_valid(license_id):
        license_doc = await db.licenses.find_one({"_id": ObjectId(license_id)})
        if license_doc:
            license_artwork_id = license_doc.get("artwork_id")
            license_artwork_filters = []
            if license_artwork_id is not None:
                license_artwork_filters.append({"_id": license_artwork_id})
                license_artwork_filters.append({"token_id": str(license_artwork_id)})
                if isinstance(license_artwork_id, str) and ObjectId.is_valid(license_artwork_id):
                    license_artwork_filters.insert(0, {"_id": ObjectId(license_artwork_id)})

            for artwork_filter in license_artwork_filters:
                query = {**artwork_filter, "is_deleted": {"$ne": True}}
                ticket = await db.tickets.find_one(query)
                if ticket:
                    logger.warning(
                        "Resolved reveal ticket via license.artwork_id fallback (ticket_id=%s, license_id=%s)",
                        ticket_id,
                        license_id,
                    )
                    return ticket

    return None


def _extract_user_identity(current_user: dict):
    """Normalize user identity fields used by PSL ownership checks."""
    user_id = str(
        current_user.get("user_id")
        or current_user.get("_id")
        or current_user.get("id")
        or ""
    ).strip()
    user_email = (current_user.get("email") or "").strip().lower()
    wallet_address = (current_user.get("wallet_address") or "").strip().lower()
    return user_id, user_email, wallet_address


def _is_psl_ticket_document(ticket: dict) -> bool:
    """Detect PSL tickets across legacy and current schema shapes."""
    attributes = ticket.get("attributes") or {}
    return bool(
        ticket.get("is_psl_ticket") is True
        or ticket.get("subject_category") == "PSL_SMART_TICKET"
        or ticket.get("category") in [PSL_TICKET_CATEGORY, "PSL_TICKET"]
        or attributes.get("is_psl_ticket") is True
        or attributes.get("psl_ticket")
    )


def _can_manage_ticket(ticket: dict, current_user: dict) -> bool:
    """Issuer can manage ticket if they are owner/creator by id/email/wallet."""
    user_id, user_email, wallet_address = _extract_user_identity(current_user)

    creator_id = str(ticket.get("creator_id") or "").strip()
    owner_id = str(ticket.get("owner_id") or "").strip()
    creator_email = (ticket.get("creator_email") or "").strip().lower()
    owner_email = (ticket.get("owner_email") or "").strip().lower()
    creator_address = (ticket.get("creator_address") or "").strip().lower()
    owner_address = (ticket.get("owner_address") or "").strip().lower()

    return bool(
        (user_id and (creator_id == user_id or owner_id == user_id))
        or (user_email and (creator_email == user_email or owner_email == user_email))
        or (wallet_address and (creator_address == wallet_address or owner_address == wallet_address))
    )


def _is_ticket_creator(ticket: dict, current_user: dict) -> bool:
    """Only original organizer/creator can reissue a ticket."""
    user_id, user_email, wallet_address = _extract_user_identity(current_user)

    creator_id = str(ticket.get("creator_id") or "").strip()
    creator_email = (ticket.get("creator_email") or "").strip().lower()
    creator_address = (ticket.get("creator_address") or "").strip().lower()

    return bool(
        (user_id and creator_id == user_id)
        or (user_email and creator_email == user_email)
        or (wallet_address and creator_address == wallet_address)
    )


def _is_authorized_psl_issuer(current_user: dict) -> bool:
    """True when the current user email is configured as an authorized PSL issuer."""
    user_email = (current_user.get("email") or "").strip().lower()
    if not user_email:
        return False

    allowed_issuers = settings.AUTHORIZED_PSL_ISSUERS or []
    normalized_allowed = {str(email).strip().lower() for email in allowed_issuers if str(email).strip()}
    return user_email in normalized_allowed


def _is_secondary_owner(ticket: dict) -> bool:
    """Return True when current owner identity differs from original creator identity."""
    creator_identifiers = {
        str(ticket.get("creator_id") or "").strip().lower(),
        str(ticket.get("creator_email") or "").strip().lower(),
        str(ticket.get("creator_address") or "").strip().lower(),
    }
    owner_identifiers = {
        str(ticket.get("owner_id") or "").strip().lower(),
        str(ticket.get("owner_email") or "").strip().lower(),
        str(ticket.get("owner_address") or "").strip().lower(),
    }

    creator_identifiers = {v for v in creator_identifiers if v}
    owner_identifiers = {v for v in owner_identifiers if v}

    if not creator_identifiers or not owner_identifiers:
        return False

    return creator_identifiers.isdisjoint(owner_identifiers)


def _resolve_match_datetime(ticket: dict) -> Optional[datetime]:
    """Resolve match datetime from primary field or PSL metadata."""
    match_value = ticket.get("match_datetime")

    if not match_value:
        psl_meta = ticket.get("psl_metadata") or ticket.get("metadata") or {}
        match_date = str(psl_meta.get("match_date") or "").strip()
        match_time = str(psl_meta.get("match_time") or "19:00").strip()
        if match_date:
            match_value = f"{match_date}T{match_time}"

    if isinstance(match_value, datetime):
        return match_value

    if isinstance(match_value, str) and match_value.strip():
        try:
            return datetime.fromisoformat(match_value.strip().replace("Z", "+00:00"))
        except Exception:
            return None

    return None


def _is_match_finished(ticket: dict) -> bool:
    """True when ticket match time has already passed."""
    match_dt = _resolve_match_datetime(ticket)
    if not match_dt:
        return False

    if match_dt.tzinfo is not None:
        return datetime.now(match_dt.tzinfo) > match_dt

    return datetime.utcnow() > match_dt


# ============== Pydantic Models ==============

class TicketRevealRequest(BaseModel):
    """Request to reveal a ticket QR code"""
    license_id: str
    ticket_id: str
    wallet_signature: Optional[str] = None  # For wallet verification


class TicketValidateRequest(BaseModel):
    """Request to validate a scanned QR code at gate"""
    ticket_id: str
    qr_hash: str
    license_id: str


class TicketTransferSyncRequest(BaseModel):
    """Request to sync a ticket transfer on-chain to the database"""
    recipient_wallet: str
    tx_hash: str
    resale_price: Optional[float] = None
    original_price: Optional[float] = None


class PSLTicketResponse(BaseModel):
    """Response model for a PSL ticket"""
    ticket_id: str
    title: str
    match_info: Optional[str] = None
    seat_number: Optional[str] = None
    stand: Optional[str] = None
    match_datetime: Optional[str] = None
    image_url: str
    metadata_uri: Optional[str] = None
    license_id: Optional[str] = None
    is_redeemed: bool = False
    can_reveal: bool = True
    price: Optional[float] = 0.0
    is_for_sale: bool = False
    token_id: Optional[int] = None
    is_secondary_owner: bool = False


class PSLTicketUpdateRequest(BaseModel):
    """Issuer update payload for PSL tickets."""
    title: Optional[str] = Field(None, max_length=100)
    match_info: Optional[str] = Field(None, max_length=1000)
    seat_number: Optional[str] = Field(None, max_length=60)
    stand: Optional[str] = Field(None, max_length=120)
    venue: Optional[str] = Field(None, max_length=200)
    match_date: Optional[str] = None
    match_time: Optional[str] = None
    price: Optional[float] = Field(None, ge=0)


class PSLReissueRequest(BaseModel):
    """Payload for organizer-driven PSL ticket reissue flow."""
    price: Optional[float] = Field(None, ge=0)
    list_for_sale: bool = True


class QRRevealResponse(BaseModel):
    """Response model for QR reveal"""
    qr_code: str  # Base64 encoded QR image
    qr_hash: str
    valid_until: int  # Unix timestamp
    seconds_remaining: int
    ticket_id: str
    license_id: str
    message: str


class QRValidateResponse(BaseModel):
    """Response model for QR validation"""
    is_valid: bool
    message: str
    ticket_id: str


# ============== API Endpoints ==============

@router.get("/tickets", response_model=List[PSLTicketResponse])
async def get_my_psl_tickets(current_user: dict = Depends(get_current_user)):
    """
    Get all PSL tickets owned by the current user.
    Returns:
    1. Tickets where user has a valid license
    2. Tickets created/owned by the user through standard upload flow
    """
    try:
        db = get_db()
        user_email = (current_user.get("email") or "").strip()
        # IMPORTANT: JWT dependency provides user_id (not id/_id) for authenticated users.
        user_id = str(
            current_user.get("user_id")
            or current_user.get("_id")
            or current_user.get("id")
            or ""
        ).strip()
        wallet_address = (current_user.get("wallet_address") or "").strip()
        wallet_address_lower = wallet_address.lower() if wallet_address else ""
        
        logger.info(f"🎫 Fetching PSL tickets for user: {user_email}, id: {user_id}")
        
        # If no user identifier, return empty list
        if not user_email and not wallet_address_lower and not user_id:
            logger.warning("No user identifier found, returning empty list")
            return []
        
        tickets = []
        seen_ids = set()
        
        # ============ Strategy 1: Find tickets via licenses ============
        license_query = {"is_active": True}
        or_conditions = []
        if user_email:
            or_conditions.append({"licensee_email": user_email})
        if wallet_address:
            or_conditions.append({"licensee_wallet": wallet_address})
        if wallet_address_lower and wallet_address_lower != wallet_address:
            or_conditions.append({"licensee_wallet": wallet_address_lower})
        
        if or_conditions:
            license_query["$or"] = or_conditions
        
        licenses_cursor = db.licenses.find(license_query)
        licenses = await licenses_cursor.to_list(length=100)
        
        logger.info(f"Found {len(licenses)} total licenses for user")
        
        # Get ticket IDs from licenses
        artwork_ids = [lic.get("artwork_id") for lic in licenses if lic.get("artwork_id")]
        
        # Fetch corresponding tickets that are PSL tickets
        for artwork_id in artwork_ids:
            try:
                ticket = await db.tickets.find_one({
                    "_id": ObjectId(artwork_id) if isinstance(artwork_id, str) else artwork_id,
                    "is_deleted": {"$ne": True},
                    "$or": [
                        {"category": PSL_TICKET_CATEGORY},
                        {"category": "PSL_TICKET"},
                        {"subject_category": "PSL_SMART_TICKET"},
                        {"tags": {"$in": ["psl", "ticket", "PSL"]}},
                        {"is_psl_ticket": True},
                        {"attributes.is_psl_ticket": True},
                        {"attributes.psl_ticket": {"$exists": True}}
                    ]
                })
                
                if ticket and str(ticket["_id"]) not in seen_ids:
                    seen_ids.add(str(ticket["_id"]))
                    # Find the corresponding license
                    license_doc = next(
                        (lic for lic in licenses if str(lic.get("artwork_id")) == str(artwork_id)),
                        None
                    )
                    
                    # Extract PSL metadata (from either direct fields or psl_metadata object)
                    psl_meta = ticket.get("psl_metadata") or ticket.get("metadata") or {}
                    
                    tickets.append(PSLTicketResponse(
                        ticket_id=str(ticket["_id"]),
                        title=ticket.get("title", "PSL Match Ticket"),
                        match_info=ticket.get("description", ""),
                        seat_number=ticket.get("seat_number") or psl_meta.get("seat_number"),
                        stand=ticket.get("stand") or psl_meta.get("stand"),
                        match_datetime=ticket.get("match_datetime") or psl_meta.get("match_datetime") or f"{psl_meta.get('match_date', '')}T{psl_meta.get('match_time', '')}",
                        image_url=_resolve_ticket_image_url(ticket),
                        metadata_uri=ticket.get("metadata_uri"),
                        license_id=str(license_doc["_id"]) if license_doc else None,
                        is_redeemed=ticket.get("is_redeemed", False),
                        can_reveal=not ticket.get("is_redeemed", False),
                        price=ticket.get("price") or psl_meta.get("price") or 0.0,
                        is_for_sale=bool(ticket.get("is_for_sale", False)),
                        token_id=ticket.get("token_id"),
                        is_secondary_owner=_is_secondary_owner(ticket),
                    ))
            except Exception as e:
                logger.error(f"Error fetching ticket {artwork_id}: {e}")
                continue
        
        # ============ Strategy 2: Find tickets created/owned by user ============
        ownership_conditions = []
        if user_id:
            ownership_conditions.append({"creator_id": user_id})
            ownership_conditions.append({"owner_id": user_id})

            # Backward compatibility: some records may store owner/creator IDs as ObjectId.
            if ObjectId.is_valid(user_id):
                oid = ObjectId(user_id)
                ownership_conditions.append({"creator_id": oid})
                ownership_conditions.append({"owner_id": oid})

        if wallet_address_lower:
            ownership_conditions.append({"creator_address": wallet_address_lower})
            ownership_conditions.append({"owner_address": wallet_address_lower})
        if wallet_address and wallet_address != wallet_address_lower:
            ownership_conditions.append({"creator_address": wallet_address})
            ownership_conditions.append({"owner_address": wallet_address})
        if user_email:
            ownership_conditions.append({"creator_email": user_email})
            ownership_conditions.append({"owner_email": user_email})
        
        if ownership_conditions:
            owned_tickets_query = {
                "$and": [
                    {"is_deleted": {"$ne": True}},
                    {"$or": ownership_conditions},
                    {"$or": [
                        {"is_psl_ticket": True},
                        {"subject_category": "PSL_SMART_TICKET"},
                        {"category": PSL_TICKET_CATEGORY},
                        {"attributes.is_psl_ticket": True},
                        {"attributes.psl_ticket": {"$exists": True}}
                    ]}
                ]
            }
            
            owned_tickets_cursor = db.tickets.find(owned_tickets_query)
            owned_tickets = await owned_tickets_cursor.to_list(length=50)
            
            for ticket in owned_tickets:
                if str(ticket["_id"]) not in seen_ids:
                    seen_ids.add(str(ticket["_id"]))
                    psl_meta = ticket.get("psl_metadata") or ticket.get("metadata") or {}
                    
                    tickets.append(PSLTicketResponse(
                        ticket_id=str(ticket["_id"]),
                        title=ticket.get("title", "PSL Match Ticket"),
                        match_info=ticket.get("description", ""),
                        seat_number=ticket.get("seat_number") or psl_meta.get("seat_number"),
                        stand=ticket.get("stand") or psl_meta.get("stand"),
                        match_datetime=ticket.get("match_datetime") or psl_meta.get("match_datetime") or f"{psl_meta.get('match_date', '')}T{psl_meta.get('match_time', '')}",
                        image_url=_resolve_ticket_image_url(ticket),
                        metadata_uri=ticket.get("metadata_uri"),
                        license_id=None,  # Creator owns it, no license needed
                        is_redeemed=ticket.get("is_redeemed", False),
                        can_reveal=True,  # Owner can always reveal
                        price=ticket.get("price") or psl_meta.get("price") or 0.0,
                        is_for_sale=bool(ticket.get("is_for_sale", False)),
                        token_id=ticket.get("token_id"),
                        is_secondary_owner=_is_secondary_owner(ticket),
                    ))
        
        logger.info(f"✅ Found {len(tickets)} total PSL tickets for user")
        return tickets
        
    except Exception as e:
        logger.error(f"❌ Error fetching PSL tickets: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch tickets: {str(e)}"
        )


@router.get("/tickets/{ticket_id}", response_model=PSLTicketResponse)
async def get_ticket_details(
    ticket_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get details of a specific PSL ticket."""
    try:
        db = get_db()
        user_email = current_user.get("email")
        
        # Fetch ticket (supports ObjectId, string _id, and token-id style identifiers)
        ticket = await _resolve_artwork_for_reveal(db, ticket_id)
        if not ticket:
            raise HTTPException(status_code=404, detail="Ticket not found")
        
        # Verify user owns a license for this ticket
        license_doc = await db.licenses.find_one({
            "artwork_id": ticket_id,
            "$or": [
                {"licensee_email": user_email},
                {"licensee_wallet": current_user.get("wallet_address", "")}
            ],
            "is_active": True
        })
        
        if not license_doc:
            raise HTTPException(status_code=403, detail="You don't own this ticket")
        
        return PSLTicketResponse(
            ticket_id=str(ticket["_id"]),
            title=ticket.get("title", "PSL Match Ticket"),
            match_info=ticket.get("description", ""),
            seat_number=ticket.get("seat_number", ticket.get("metadata", {}).get("seat_number")),
            stand=ticket.get("stand", ticket.get("metadata", {}).get("stand")),
            match_datetime=ticket.get("match_datetime", ticket.get("metadata", {}).get("match_datetime")),
            image_url=_resolve_ticket_image_url(ticket),
            metadata_uri=ticket.get("metadata_uri"),
            license_id=str(license_doc["_id"]),
            is_redeemed=ticket.get("is_redeemed", False),
            can_reveal=not ticket.get("is_redeemed", False),
            price=ticket.get("price") or ticket.get("metadata", {}).get("price") or 0.0,
            is_for_sale=bool(ticket.get("is_for_sale", False)),
            token_id=ticket.get("token_id"),
            is_secondary_owner=_is_secondary_owner(ticket),
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error fetching ticket details: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/tickets/{ticket_id}", response_model=PSLTicketResponse)
async def update_psl_ticket(
    ticket_id: str,
    update_request: PSLTicketUpdateRequest,
    current_user: dict = Depends(get_current_user)
):
    """Allow issuer/owner to update PSL ticket details without re-uploading image."""
    try:
        db = get_db()

        ticket = await _resolve_artwork_for_reveal(db, ticket_id)
        if not ticket:
            raise HTTPException(status_code=404, detail="Ticket not found")

        if not _is_psl_ticket_document(ticket):
            raise HTTPException(status_code=400, detail="Only PSL tickets can be updated from this endpoint")

        if not (_is_ticket_creator(ticket, current_user) or _is_authorized_psl_issuer(current_user)):
            raise HTTPException(status_code=403, detail="Only the original organizer or an authorized PSL issuer can update this ticket")

        if ticket.get("is_redeemed"):
            raise HTTPException(
                status_code=400,
                detail="Redeemed ticket is locked and cannot be edited"
            )

        update_data = update_request.model_dump(exclude_unset=True)
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields provided for update")

        psl_meta = dict(ticket.get("psl_metadata") or {})
        mongo_update = {"updated_at": datetime.utcnow()}

        if "title" in update_data:
            mongo_update["title"] = (update_data.get("title") or "").strip()

        if "match_info" in update_data:
            mongo_update["description"] = (update_data.get("match_info") or "").strip()

        if "seat_number" in update_data:
            seat_number = (update_data.get("seat_number") or "").strip()
            mongo_update["seat_number"] = seat_number
            psl_meta["seat_number"] = seat_number

        if "stand" in update_data:
            stand = (update_data.get("stand") or "").strip()
            mongo_update["stand"] = stand
            psl_meta["stand"] = stand

        if "venue" in update_data:
            venue = (update_data.get("venue") or "").strip()
            psl_meta["venue"] = venue

        if "price" in update_data:
            mongo_update["price"] = float(update_data.get("price") or 0)
            psl_meta["price"] = float(update_data.get("price") or 0)

        effective_match_date = update_data.get("match_date", psl_meta.get("match_date", ""))
        effective_match_time = update_data.get("match_time", psl_meta.get("match_time", "19:00"))

        if "match_date" in update_data:
            psl_meta["match_date"] = (update_data.get("match_date") or "").strip()
        if "match_time" in update_data:
            psl_meta["match_time"] = (update_data.get("match_time") or "").strip()

        if effective_match_date:
            mongo_update["match_datetime"] = f"{str(effective_match_date).strip()}T{str(effective_match_time or '19:00').strip()}"

        mongo_update["psl_metadata"] = psl_meta

        await db.tickets.update_one(
            {"_id": ticket["_id"]},
            {"$set": mongo_update}
        )

        updated_ticket = await db.tickets.find_one({"_id": ticket["_id"], "is_deleted": {"$ne": True}})
        if not updated_ticket:
            raise HTTPException(status_code=500, detail="Failed to reload updated ticket")

        updated_meta = updated_ticket.get("psl_metadata") or updated_ticket.get("metadata") or {}
        return PSLTicketResponse(
            ticket_id=str(updated_ticket["_id"]),
            title=updated_ticket.get("title", "PSL Match Ticket"),
            match_info=updated_ticket.get("description", ""),
            seat_number=updated_ticket.get("seat_number") or updated_meta.get("seat_number"),
            stand=updated_ticket.get("stand") or updated_meta.get("stand"),
            match_datetime=updated_ticket.get("match_datetime") or updated_meta.get("match_datetime") or f"{updated_meta.get('match_date', '')}T{updated_meta.get('match_time', '')}",
            image_url=_resolve_ticket_image_url(updated_ticket),
            metadata_uri=updated_ticket.get("metadata_uri"),
            license_id=None,
            is_redeemed=updated_ticket.get("is_redeemed", False),
            can_reveal=not updated_ticket.get("is_redeemed", False),
            price=updated_ticket.get("price") or updated_meta.get("price") or 0.0,
            is_for_sale=bool(updated_ticket.get("is_for_sale", False)),
            token_id=updated_ticket.get("token_id"),
            is_secondary_owner=_is_secondary_owner(updated_ticket),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error updating PSL ticket {ticket_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update PSL ticket")


@router.delete("/tickets/{ticket_id}")
async def delete_psl_ticket(
    ticket_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Soft delete issuer-owned PSL ticket record."""
    try:
        db = get_db()

        ticket = await _resolve_artwork_for_reveal(db, ticket_id)
        if not ticket:
            raise HTTPException(status_code=404, detail="Ticket not found")

        if not _is_psl_ticket_document(ticket):
            raise HTTPException(status_code=400, detail="Only PSL tickets can be deleted from this endpoint")

        if not (_is_ticket_creator(ticket, current_user) or _is_authorized_psl_issuer(current_user)):
            raise HTTPException(status_code=403, detail="Only the original organizer or an authorized PSL issuer can delete this ticket")

        if ticket.get("is_redeemed"):
            raise HTTPException(
                status_code=400,
                detail="Used ticket cannot be deleted"
            )

        active_licenses = await db.licenses.count_documents({
            "artwork_id": {"$in": [ticket["_id"], str(ticket["_id"])]},
            "is_active": True
        })
        if active_licenses > 0:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete this ticket because active licenses exist"
            )

        user_id, user_email, wallet_address = _extract_user_identity(current_user)
        deleted_by = user_id or user_email or wallet_address or "unknown"

        await db.tickets.update_one(
            {"_id": ticket["_id"]},
            {
                "$set": {
                    "is_deleted": True,
                    "deleted_at": datetime.utcnow(),
                    "deleted_by": deleted_by,
                    "is_for_sale": False,
                    "updated_at": datetime.utcnow()
                }
            }
        )

        return {
            "success": True,
            "ticket_id": str(ticket["_id"]),
            "message": "Ticket record deleted successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error deleting PSL ticket {ticket_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete PSL ticket")


@router.post("/tickets/{ticket_id}/reissue-draft")
async def reissue_psl_ticket_draft(
    ticket_id: str,
    request: Optional[PSLReissueRequest] = None,
    current_user: dict = Depends(get_current_user)
):
    """
    Create a fresh off-chain PSL draft from an existing organizer ticket.
    The frontend can then register this draft on-chain and list it for sale.
    """
    try:
        db = get_db()

        source_ticket = await _resolve_artwork_for_reveal(db, ticket_id)
        if not source_ticket:
            raise HTTPException(status_code=404, detail="Source ticket not found")

        if not _is_psl_ticket_document(source_ticket):
            raise HTTPException(status_code=400, detail="Only PSL tickets can be reissued")

        if not (_is_ticket_creator(source_ticket, current_user) or _is_authorized_psl_issuer(current_user)):
            raise HTTPException(
                status_code=403,
                detail="Only the original organizer or an authorized PSL issuer can reissue this ticket"
            )

        if not _is_match_finished(source_ticket):
            raise HTTPException(
                status_code=400,
                detail="Match has not finished yet. Reupload + sell again is available only after match completion."
            )

        payload = request or PSLReissueRequest()
        user_id, user_email, wallet_address = _extract_user_identity(current_user)
        owner_id = str(
            current_user.get("id")
            or current_user.get("_id")
            or current_user.get("user_id")
            or user_id
            or ""
        ).strip()

        psl_meta = dict(source_ticket.get("psl_metadata") or source_ticket.get("metadata") or {})
        source_id = str(source_ticket.get("_id"))

        generation_count = await db.tickets.count_documents({"source_ticket_id": source_id})
        reissue_generation = generation_count + 1

        source_price = source_ticket.get("price")
        if source_price is None:
            source_price = psl_meta.get("price")

        effective_price = payload.price if payload.price is not None else (source_price or 0.0)

        now = datetime.utcnow()
        new_ticket = {
            "title": source_ticket.get("title", "PSL Match Ticket"),
            "description": source_ticket.get("description", ""),
            "metadata_uri": source_ticket.get("metadata_uri"),
            "image_url": source_ticket.get("image_url"),
            "image_uri": source_ticket.get("image_uri"),
            "image_ipfs_uri": source_ticket.get("image_ipfs_uri"),
            "thumbnail_url": source_ticket.get("thumbnail_url"),
            "is_psl_ticket": True,
            "category": source_ticket.get("category") or PSL_TICKET_CATEGORY,
            "medium_category": source_ticket.get("medium_category") or "PSL_SMART_TICKET",
            "style_category": source_ticket.get("style_category") or "PSL_SMART_TICKET",
            "subject_category": source_ticket.get("subject_category") or "PSL_SMART_TICKET",
            "royalty_percentage": source_ticket.get("royalty_percentage", 0),
            "price": float(effective_price),
            "seat_number": source_ticket.get("seat_number") or psl_meta.get("seat_number"),
            "stand": source_ticket.get("stand") or psl_meta.get("stand"),
            "match_datetime": source_ticket.get("match_datetime") or psl_meta.get("match_datetime"),
            "psl_metadata": psl_meta,
            "creator_id": source_ticket.get("creator_id") or owner_id,
            "creator_email": source_ticket.get("creator_email") or user_email,
            "creator_address": source_ticket.get("creator_address") or wallet_address,
            "owner_id": owner_id,
            "owner_email": user_email,
            "owner_address": wallet_address,
            "network": source_ticket.get("network") or "wirefluid",
            "payment_method": "crypto",
            "is_on_chain": False,
            "is_for_sale": False,
            "is_redeemed": False,
            "redeemed_at": None,
            "redeemed_qr_hash": None,
            "is_deleted": False,
            "created_at": now,
            "updated_at": now,
            "source_ticket_id": source_id,
            "reissue_generation": reissue_generation,
            "reissued_by": owner_id or user_email or wallet_address,
        }

        insert_result = await db.tickets.insert_one(new_ticket)
        new_ticket_id = str(insert_result.inserted_id)

        logger.info(
            "✅ Created PSL reissue draft from ticket %s -> %s (generation=%s)",
            source_id,
            new_ticket_id,
            reissue_generation,
        )

        return {
            "success": True,
            "message": "Reissue draft created. Continue with blockchain registration.",
            "new_ticket_id": new_ticket_id,
            "source_ticket_id": source_id,
            "price": float(effective_price),
            "list_for_sale": bool(payload.list_for_sale),
            "reissue_generation": reissue_generation,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error creating reissue draft for ticket {ticket_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to create reissue draft")


@router.post("/tickets/reveal", response_model=QRRevealResponse)
async def reveal_ticket_qr(
    request: TicketRevealRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Reveal the dynamic QR code for stadium entry.
    
    The QR code is valid for 60 seconds only.
    Screenshots become useless after expiry.
    
    Access allowed for:
    1. Users with a valid license for this ticket
    2. Ticket owner/creator (no license needed)
    """
    try:
        db = get_db()
        user_email = (current_user.get("email") or "").strip()
        user_email_lower = user_email.lower() if user_email else ""
        user_id = str(
            current_user.get("user_id")
            or current_user.get("_id")
            or current_user.get("id")
            or ""
        ).strip()
        wallet_address = (current_user.get("wallet_address") or "").strip()
        wallet_address_lower = wallet_address.lower() if wallet_address else ""
        
        logger.info(f"🎫 QR Reveal request - ticket: {request.ticket_id}, license: {request.license_id}, user: {user_email}")
        
        # Validate ticket_id
        if not request.ticket_id or request.ticket_id == "null" or request.ticket_id == "None":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="❌ Invalid ticket ID"
            )
        
        # 1. Fetch the ticket (ticket)
        ticket = await _resolve_artwork_for_reveal(db, request.ticket_id, request.license_id)
        
        if not ticket:
            logger.warning(
                "Reveal failed: ticket not found (ticket_id=%s, license_id=%s)",
                request.ticket_id,
                request.license_id,
            )
            raise HTTPException(status_code=404, detail="Ticket not found")
        
        # 2. Check ownership or license
        is_owner = False
        has_license = False
        license_id_to_use = request.license_id

        artwork_creator_id = str(ticket.get("creator_id") or "").strip()
        artwork_owner_id = str(ticket.get("owner_id") or "").strip()
        artwork_creator_email = (ticket.get("creator_email") or "").strip().lower()
        artwork_owner_email = (ticket.get("owner_email") or "").strip().lower()
        artwork_creator_address = (ticket.get("creator_address") or "").strip().lower()
        artwork_owner_address = (ticket.get("owner_address") or "").strip().lower()
        
        # Check if user is the owner/creator
        if user_id:
            is_owner = (
                artwork_creator_id == user_id or
                artwork_owner_id == user_id
            )
        if user_email_lower and not is_owner:
            is_owner = (
                artwork_creator_email == user_email_lower or
                artwork_owner_email == user_email_lower
            )
        if wallet_address_lower and not is_owner:
            is_owner = (
                artwork_creator_address == wallet_address_lower or
                artwork_owner_address == wallet_address_lower
            )
        
        # If not owner, verify license
        if not is_owner:
            if not request.license_id or request.license_id == "null" or request.license_id == "None":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="❌ Invalid license ID - you don't own this ticket"
                )
            
            try:
                license_oid = ObjectId(request.license_id)
            except Exception as e:
                logger.error(f"Invalid license_id format: {request.license_id}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="❌ Invalid license ID format"
                )

            license_user_conditions = []
            if user_email:
                license_user_conditions.append({"licensee_email": user_email})
            if user_email_lower and user_email_lower != user_email:
                license_user_conditions.append({"licensee_email": user_email_lower})
            if wallet_address:
                license_user_conditions.append({"licensee_wallet": wallet_address})
            if wallet_address_lower and wallet_address_lower != wallet_address:
                license_user_conditions.append({"licensee_wallet": wallet_address_lower})

            if not license_user_conditions:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="❌ User identity missing for license verification"
                )
            
            license_doc = await db.licenses.find_one({
                "_id": license_oid,
                "$or": license_user_conditions,
                "is_active": True
            })
            
            if not license_doc:
                logger.warning(
                    "License ownership check failed for ticket %s and license %s (email=%s, wallet=%s)",
                    request.ticket_id,
                    request.license_id,
                    user_email,
                    wallet_address,
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="❌ You don't own this ticket license"
                )
            has_license = True
        else:
            # Owner doesn't need license - use ticket_id as license_id for QR generation
            logger.info(f"✅ User is ticket owner, bypassing license check")
            license_id_to_use = request.ticket_id  # Use ticket_id for QR hash
        
        # 3. Check if ticket is already redeemed
        if ticket.get("is_redeemed", False):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="🚫 This ticket has already been used"
            )
        
        # 4. Check if reveal window is open
        match_datetime = ticket.get("match_datetime")
        
        # Try to extract from psl_metadata if not in direct field
        if not match_datetime:
            psl_meta = ticket.get("psl_metadata") or {}
            match_date = psl_meta.get("match_date")
            match_time = psl_meta.get("match_time")
            if match_date:
                match_datetime = f"{match_date}T{match_time or '19:00'}"
        
        if match_datetime and isinstance(match_datetime, str):
            try:
                match_datetime = datetime.fromisoformat(match_datetime)
            except:
                match_datetime = None
        
        reveal_check = can_reveal_ticket(match_datetime)
        if not reveal_check["can_reveal"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=reveal_check["message"]
            )
        
        # 5. Generate dynamic QR code
        qr_data = generate_dynamic_qr(license_id_to_use, request.ticket_id)
        
        logger.info(f"✅ QR revealed for ticket {request.ticket_id}, valid for {qr_data['seconds_remaining']}s, owner: {is_owner}")
        
        return QRRevealResponse(
            qr_code=qr_data["qr_code"],
            qr_hash=qr_data["qr_hash"],
            valid_until=qr_data["valid_until"],
            seconds_remaining=qr_data["seconds_remaining"],
            ticket_id=request.ticket_id,
            license_id=license_id_to_use,
            message=f"🎫 QR valid for {qr_data['seconds_remaining']} seconds"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error revealing QR: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tickets/validate", response_model=QRValidateResponse)
async def validate_ticket_qr(request: TicketValidateRequest):
    """
    Validate a QR code at the stadium gate.
    
    This endpoint is used by security scanners.
    If valid, the ticket is marked as redeemed.
    """
    try:
        db = get_db()
        
        logger.info(f"🔍 Validating QR for ticket: {request.ticket_id}")
        
        # 1. Validate the QR hash
        validation = validate_qr(request.ticket_id, request.qr_hash, request.license_id)
        
        if not validation["is_valid"]:
            logger.warning(f"❌ Invalid QR for ticket {request.ticket_id}")
            return QRValidateResponse(
                is_valid=False,
                message=validation["message"],
                ticket_id=request.ticket_id
            )
        
        # 2. Check if ticket exists and isn't already redeemed
        ticket = await db.tickets.find_one({"_id": ObjectId(request.ticket_id)})
        if not ticket:
            return QRValidateResponse(
                is_valid=False,
                message="❌ Ticket not found in system",
                ticket_id=request.ticket_id
            )
        
        if ticket.get("is_redeemed", False):
            return QRValidateResponse(
                is_valid=False,
                message="🚫 Ticket already used! Entry denied.",
                ticket_id=request.ticket_id
            )
        
        # 3. Mark ticket as redeemed
        await db.tickets.update_one(
            {"_id": ObjectId(request.ticket_id)},
            {
                "$set": {
                    "is_redeemed": True,
                    "redeemed_at": datetime.utcnow(),
                    "redeemed_qr_hash": request.qr_hash
                }
            }
        )
        
        logger.info(f"✅ Ticket {request.ticket_id} validated and redeemed!")
        
        return QRValidateResponse(
            is_valid=True,
            message="✅ Valid ticket! Welcome to the match! 🏏",
            ticket_id=request.ticket_id
        )
        
    except Exception as e:
        logger.error(f"❌ Error validating QR: {e}")
        return QRValidateResponse(
            is_valid=False,
            message=f"❌ Validation error: {str(e)}",
            ticket_id=request.ticket_id
        )


@router.get("/reveal-status/{ticket_id}")
async def check_reveal_status(
    ticket_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Check if a ticket's QR can be revealed (time-gate check).
    """
    try:
        db = get_db()
        
        ticket = await db.tickets.find_one({"_id": ObjectId(ticket_id)})
        if not ticket:
            raise HTTPException(status_code=404, detail="Ticket not found")
        
        match_datetime = ticket.get("match_datetime")
        if match_datetime and isinstance(match_datetime, str):
            try:
                match_datetime = datetime.fromisoformat(match_datetime)
            except:
                match_datetime = None
        
        return can_reveal_ticket(match_datetime)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking reveal status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/tickets/{ticket_id}/transfer-sync")
async def sync_ticket_transfer(
    ticket_id: str,
    request: TicketTransferSyncRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Sync an on-chain ticket transfer with the backend database.
    Updates ownership/license records after MetaMask transaction confirms.
    """
    try:
        db = get_db()
        recipient_wallet = request.recipient_wallet.lower().strip()
        
        # Verify Price Cap (Anti-Scalping)
        if request.resale_price is not None and request.original_price is not None:
            if request.resale_price > request.original_price * 1.5:
                raise HTTPException(status_code=400, detail="Resale price exceeds 150% anti-scalping cap")
                
        # 1. Resolve the actual ticket document (handles string/ObjectId/token_id)
        ticket = await _resolve_artwork_for_reveal(db, ticket_id)
        if not ticket:
            logger.error(f"❌ Transfer Sync failed: Ticket {ticket_id} not found in database")
            raise HTTPException(status_code=404, detail="Ticket not found in system")
            
        real_id = ticket["_id"] # Use the actual ID type from the document
        
        # 2. Update the Ticket owner
        artwork_update = await db.tickets.update_one(
            {"_id": real_id},
            {"$set": {
                "owner_id": recipient_wallet,
                "owner_address": recipient_wallet,
                "last_tx_hash": request.tx_hash,
                "updated_at": datetime.utcnow()
            }}
        )
        
        # 3. Deactivate old licenses and create a new one for the recipient
        # Check for license using both ObjectID and string formats for maximum safety
        await db.licenses.update_many(
            {"artwork_id": {"$in": [real_id, str(real_id)]}, "is_active": True},
            {"$set": {"is_active": False}}
        )
        
        new_license = {
            "artwork_id": real_id,
            "licensee_wallet": recipient_wallet,
            "licensee_email": f"web3_{recipient_wallet[:8]}@pslentryx.com",
            "is_active": True,
            "license_type": "ARTWORK_OWNERSHIP",
            "start_date": datetime.utcnow(),
            "end_date": datetime.utcnow().replace(year=2100),
            "tx_hash": request.tx_hash,
            "price": request.resale_price or ticket.get("price") or 0.0
        }
        await db.licenses.insert_one(new_license)
        
        logger.info(f"✅ Ticket {ticket_id} (real_id: {real_id}) transferred successfully to {recipient_wallet}")
        return {"success": True, "message": "Ticket ownership synced successfully"}
        
        logger.info(f"✅ Ticket {ticket_id} transferred successfully to {recipient_wallet}")
        return {"success": True, "message": "Ticket ownership synced successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error syncing ticket transfer: {e}")
        raise HTTPException(status_code=500, detail=str(e))

