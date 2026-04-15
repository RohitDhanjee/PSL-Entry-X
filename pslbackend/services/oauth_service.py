import httpx
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests
from app.core.config import settings
from typing import Optional, Dict
import secrets
import logging

logger = logging.getLogger(__name__)


class OAuthService:
    def __init__(self):
        self.google_client_id = settings.GOOGLE_CLIENT_ID
        self.google_client_secret = settings.GOOGLE_CLIENT_SECRET
        self.google_redirect_uri = settings.GOOGLE_REDIRECT_URI
        
    def generate_state(self) -> str:
        """Generate a random state string for CSRF protection"""
        return secrets.token_urlsafe(32)
    
    def get_google_auth_url(self, redirect_uri: str = None, state: str = None) -> str:
        """
        Generate Google OAuth authorization URL
        """
        if not redirect_uri:
            redirect_uri = self.google_redirect_uri
            
        if not state:
            state = self.generate_state()
        
        # Google OAuth 2.0 authorization endpoint
        auth_url = "https://accounts.google.com/o/oauth2/v2/auth"
        
        # Build query parameters
        params = {
            "client_id": self.google_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "offline",
            "prompt": "consent"
        }
        
        # Construct full URL
        query_string = "&".join([f"{key}={value}" for key, value in params.items()])
        full_url = f"{auth_url}?{query_string}"
        
        logger.info(f"Generated Google auth URL with state: {state}")
        return full_url
    
    async def exchange_code_for_token(self, code: str, redirect_uri: str = None) -> Dict:
        """
        Exchange authorization code for access token
        """
        if not redirect_uri:
            redirect_uri = self.google_redirect_uri
        
        token_url = "https://oauth2.googleapis.com/token"
        
        data = {
            "code": code,
            "client_id": self.google_client_id,
            "client_secret": self.google_client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(token_url, data=data)
            
            if response.status_code != 200:
                logger.error(f"Token exchange failed: {response.text}")
                raise Exception("Failed to exchange code for token")
            
            token_data = response.json()
            logger.info("✅ Successfully exchanged code for tokens")
            return token_data
    
    async def verify_google_id_token(self, token: str) -> Optional[Dict]:
        """
        Verify Google ID token and return user info
        This is the main method used by the frontend Google Sign-In button
        """
        try:
            logger.info("🔄 Verifying Google ID token with Google...")
            
            # Verify the token with Google
            idinfo = google_id_token.verify_oauth2_token(
                token,
                google_requests.Request(),
                self.google_client_id
            )
            
            # Verify issuer
            if idinfo['iss'] not in ['accounts.google.com', 'https://accounts.google.com']:
                logger.error(f"Invalid issuer: {idinfo['iss']}")
                return None
            
            logger.info(f"✅ Token verified successfully for: {idinfo.get('email')}")
            
            # Return user info
            return {
                "sub": idinfo.get("sub"),  # Google user ID
                "email": idinfo.get("email"),
                "name": idinfo.get("name"),
                "picture": idinfo.get("picture"),
                "email_verified": idinfo.get("email_verified", False),
                "given_name": idinfo.get("given_name"),
                "family_name": idinfo.get("family_name"),
            }
            
        except ValueError as e:
            # Invalid token
            logger.error(f"❌ Token verification failed: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"❌ Unexpected error verifying token: {str(e)}")
            import traceback
            traceback.print_exc()
            return None
    
    async def get_google_user_info(self, access_token: str) -> Optional[Dict]:
        """
        Get user info from Google using access token
        Used in OAuth callback flow
        """
        try:
            userinfo_url = "https://www.googleapis.com/oauth2/v2/userinfo"
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    userinfo_url,
                    headers={"Authorization": f"Bearer {access_token}"}
                )
                
                if response.status_code != 200:
                    logger.error(f"Failed to get user info: {response.text}")
                    return None
                
                user_info = response.json()
                logger.info(f"✅ Retrieved user info for: {user_info.get('email')}")
                return user_info
                
        except Exception as e:
            logger.error(f"Error getting user info: {str(e)}")
            return None


# Create singleton instance
oauth_service = OAuthService()