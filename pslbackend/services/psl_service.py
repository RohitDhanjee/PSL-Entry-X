"""
PSL Entry X Service
===========================
Dynamic QR Code generation for PSL match tickets.
QR codes expire every 60 seconds to prevent screenshot fraud.

This is an ISOLATED module for the hackathon demo.
"""

import hmac
import hashlib
import time
import os
import qrcode
import io
import base64
from datetime import datetime, timedelta
from typing import Optional
from app.core.config import settings


# Secret key for HMAC - in production, this should be in .env
PSL_SECRET_KEY = settings.SECRET_KEY or "psl-hackathon-secret-2024"


def generate_dynamic_qr(license_id: str, ticket_id: str) -> dict:
    """
    Generate a dynamic QR code that changes every 60 seconds.
    
    The QR contains an HMAC hash that can only be validated within
    the current 60-second window. Screenshots become useless after expiry.
    
    Args:
        license_id: The blockchain license ID
        ticket_id: The ticket/artwork ID
    
    Returns:
        dict with qr_code (base64), valid_until timestamp, seconds_remaining
    """
    current_minute = int(time.time() // 60)
    
    # Create HMAC hash: license_id + ticket_id + current_minute
    message = f"{license_id}:{ticket_id}:{current_minute}"
    qr_hash = hmac.new(
        PSL_SECRET_KEY.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()[:16]  # Short code for QR
    
    # QR payload includes hash and metadata for validation
    qr_payload = f"PSL-ENTRY-X:{ticket_id}:{qr_hash}"
    
    # Generate QR code image
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(qr_payload)
    qr.make(fit=True)
    
    # Create image and convert to base64
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    qr_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
    
    # Calculate timing
    current_time = int(time.time())
    next_minute = (current_minute + 1) * 60
    seconds_remaining = next_minute - current_time
    
    return {
        "qr_code": f"data:image/png;base64,{qr_base64}",
        "qr_hash": qr_hash,
        "valid_until": next_minute,
        "seconds_remaining": seconds_remaining,
        "ticket_id": ticket_id,
        "license_id": license_id
    }


def validate_qr(ticket_id: str, qr_hash: str, license_id: str) -> dict:
    """
    Validate a QR code hash - used by gate scanner.
    
    Checks if the provided hash matches the expected hash for the
    current 60-second window.
    
    Args:
        ticket_id: The ticket/artwork ID
        qr_hash: The hash from scanned QR
        license_id: The blockchain license ID
    
    Returns:
        dict with is_valid boolean and message
    """
    current_minute = int(time.time() // 60)
    
    # Generate expected hash for current minute
    message = f"{license_id}:{ticket_id}:{current_minute}"
    expected_hash = hmac.new(
        PSL_SECRET_KEY.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()[:16]
    
    # Constant-time comparison to prevent timing attacks
    is_valid = hmac.compare_digest(qr_hash, expected_hash)
    
    if is_valid:
        return {
            "is_valid": True,
            "message": "✅ Valid ticket! Entry granted.",
            "ticket_id": ticket_id
        }
    
    # Also check previous minute (grace period for slow scans)
    prev_message = f"{license_id}:{ticket_id}:{current_minute - 1}"
    prev_hash = hmac.new(
        PSL_SECRET_KEY.encode(),
        prev_message.encode(),
        hashlib.sha256
    ).hexdigest()[:16]
    
    if hmac.compare_digest(qr_hash, prev_hash):
        return {
            "is_valid": True,
            "message": "✅ Valid ticket (grace period)! Entry granted.",
            "ticket_id": ticket_id
        }
    
    return {
        "is_valid": False,
        "message": "❌ Invalid or expired QR code. Please refresh.",
        "ticket_id": ticket_id
    }


def can_reveal_ticket(match_datetime: Optional[datetime] = None) -> dict:
    """
    Check if ticket reveal is allowed based on match time.
    
    In production: Only allow reveal 2 hours before match.
    For hackathon demo: Always allow (DEMO_MODE=True).
    
    Args:
        match_datetime: The scheduled match date/time
    
    Returns:
        dict with can_reveal boolean and message
    """
    # Demo/development bypass for hackathon and local testing.
    # Production keeps strict time-gating unless DEMO_MODE is explicitly enabled.
    environment = (os.getenv("ENVIRONMENT", "development") or "development").lower()
    if getattr(settings, 'DEMO_MODE', True) or environment != "production":
        return {
            "can_reveal": True,
            "message": "🎫 Demo mode: Reveal enabled",
            "demo_mode": True
        }
    
    if not match_datetime:
        return {
            "can_reveal": False,
            "message": "Match time not set",
            "demo_mode": False
        }
    
    now = datetime.utcnow()
    reveal_window_start = match_datetime - timedelta(hours=2)
    
    if now < reveal_window_start:
        time_until_reveal = reveal_window_start - now
        hours = int(time_until_reveal.total_seconds() // 3600)
        minutes = int((time_until_reveal.total_seconds() % 3600) // 60)
        return {
            "can_reveal": False,
            "message": f"🔒 Reveal opens in {hours}h {minutes}m (2 hours before match)",
            "demo_mode": False,
            "reveal_time": reveal_window_start.isoformat()
        }
    
    if now > match_datetime:
        return {
            "can_reveal": False,
            "message": "🚫 Match has already started",
            "demo_mode": False
        }
    
    return {
        "can_reveal": True,
        "message": "🎫 Reveal window is open!",
        "demo_mode": False
    }


# PSL Ticket category constant
PSL_TICKET_CATEGORY = "PSL_SMART_TICKET"
