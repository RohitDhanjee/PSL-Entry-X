"""
Download Service — Controlled, time-limited signed download URLs for DRM.
Uses JWT tokens to generate expiring download links with rate limiting.
"""

import hashlib
import time
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from jose import jwt, JWTError

logger = logging.getLogger(__name__)

# In-memory rate limit store (use Redis in production for multi-worker)
_download_rate_limits: Dict[str, list] = {}
MAX_DOWNLOADS_PER_HOUR = 5
DOWNLOAD_TOKEN_EXPIRY_MINUTES = 15


class DownloadService:
    """Service for generating and validating signed download URLs"""

    def __init__(self, secret_key: str):
        self.secret_key = secret_key

    def generate_download_token(
        self,
        token_id: int,
        user_id: str,
        license_type: str,
        license_id: int,
    ) -> Dict[str, Any]:
        """
        Generate a JWT-signed download token with expiry.

        Args:
            token_id: Artwork token ID
            user_id: Buyer's user ID
            license_type: License type string
            license_id: License ID number

        Returns:
            Dict with download_token and expiry info
        """
        # Check rate limit first
        rate_key = f"{user_id}:{token_id}"
        if not self._check_rate_limit(rate_key):
            return {
                "success": False,
                "error": "Rate limit exceeded. Maximum 5 downloads per hour.",
                "retry_after_seconds": self._get_retry_after(rate_key),
            }

        # Create JWT payload securely using POSIX timestamps
        now_ts = time.time()
        expiry_ts = now_ts + (DOWNLOAD_TOKEN_EXPIRY_MINUTES * 60)

        payload = {
            "token_id": token_id,
            "user_id": user_id,
            "license_type": license_type,
            "license_id": license_id,
            "purpose": "download",
            "iat": now_ts,
            "exp": expiry_ts,
            "jti": hashlib.sha256(
                f"{user_id}:{token_id}:{now_ts}".encode()
            ).hexdigest()[:16],
        }

        download_token = jwt.encode(payload, self.secret_key, algorithm="HS256")

        # Record download in rate limiter
        self._record_download(rate_key)

        logger.info(
            f"✅ Generated download token for artwork #{token_id}, "
            f"user={user_id}, expires in {DOWNLOAD_TOKEN_EXPIRY_MINUTES}min"
        )

        return {
            "success": True,
            "download_token": download_token,
            "expires_at": datetime.fromtimestamp(expiry_ts).isoformat(),
            "expires_in_seconds": DOWNLOAD_TOKEN_EXPIRY_MINUTES * 60,
            "downloads_remaining": self._get_remaining_downloads(rate_key),
        }

    def validate_download_token(self, download_token: str) -> Dict[str, Any]:
        """
        Validate a download JWT token.

        Returns:
            Dict with validation result and payload if valid
        """
        try:
            payload = jwt.decode(
                download_token, self.secret_key, algorithms=["HS256"]
            )

            # Check purpose
            if payload.get("purpose") != "download":
                return {"valid": False, "error": "Invalid token purpose"}

            return {
                "valid": True,
                "token_id": payload["token_id"],
                "user_id": payload["user_id"],
                "license_type": payload["license_type"],
                "license_id": payload["license_id"],
            }

        except JWTError as e:
            if "expired" in str(e).lower():
                return {"valid": False, "error": "Download link has expired"}
            return {"valid": False, "error": f"Invalid download token: {str(e)}"}
        except Exception as e:
            return {"valid": False, "error": f"Token validation failed: {str(e)}"}

    # --- Rate Limiting ---

    def _check_rate_limit(self, rate_key: str) -> bool:
        """Check if user is within download rate limit"""
        self._cleanup_expired_entries(rate_key)
        entries = _download_rate_limits.get(rate_key, [])
        return len(entries) < MAX_DOWNLOADS_PER_HOUR

    def _record_download(self, rate_key: str) -> None:
        """Record a download for rate limiting"""
        if rate_key not in _download_rate_limits:
            _download_rate_limits[rate_key] = []
        _download_rate_limits[rate_key].append(time.time())

    def _cleanup_expired_entries(self, rate_key: str) -> None:
        """Remove rate limit entries older than 1 hour"""
        if rate_key in _download_rate_limits:
            one_hour_ago = time.time() - 3600
            _download_rate_limits[rate_key] = [
                t for t in _download_rate_limits[rate_key] if t > one_hour_ago
            ]

    def _get_remaining_downloads(self, rate_key: str) -> int:
        """Get remaining downloads in current hour window"""
        self._cleanup_expired_entries(rate_key)
        used = len(_download_rate_limits.get(rate_key, []))
        return max(0, MAX_DOWNLOADS_PER_HOUR - used)

    def _get_retry_after(self, rate_key: str) -> int:
        """Get seconds until next download is allowed"""
        entries = _download_rate_limits.get(rate_key, [])
        if not entries:
            return 0
        oldest = min(entries)
        retry_after = int(oldest + 3600 - time.time())
        return max(0, retry_after)

    # --- License Type Validation ---

    @staticmethod
    def can_download(license_type: str) -> bool:
        """
        Check if a license type allows downloading the original file.
        
        Currently based on existing 3 types. Will be expanded to 8 types
        in Phase 2 (licensing system expansion).
        """
        # Types that allow download (will be expanded in Phase 2)
        download_allowed = {
            "FULL_ACCESS",
            "COMMERCIAL",
            "EXTENDED_COMMERCIAL",
            "EXCLUSIVE",
            "ARTWORK_OWNERSHIP",
        }
        return license_type in download_allowed

    @staticmethod
    def needs_watermark(license_type: str) -> bool:
        """
        Check if a license type should see watermarked previews.
        
        Currently based on existing 3 types. Will be expanded in Phase 2.
        """
        # Types that see watermarked versions
        watermarked_types = {
            "LINK_ONLY",
            "PERSONAL_USE",
            "NON_COMMERCIAL",
            "ACCESS_WITH_WM",
        }
        return license_type in watermarked_types
