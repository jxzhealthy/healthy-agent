"""Authentication middleware for Healthy Agent."""

import hmac
import hashlib
import base64
import json
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp


def verify_api_key(key: str, valid_keys: list[str]) -> bool:
    """Verify API key against list of valid keys."""
    if not key or not valid_keys:
        return False
    return key in valid_keys


def verify_jwt(token: str, secret: str) -> Optional[dict]:
    """
    Verify JWT token and return payload.
    
    Tries to use PyJWT first, falls back to simple HMAC verification.
    Returns decoded payload dict or None if invalid.
    """
    # Try PyJWT first
    try:
        import jwt
        try:
            payload = jwt.decode(token, secret, algorithms=["HS256"])
            return payload
        except Exception:
            return None
    except ImportError:
        pass
    
    # Fallback to simple HMAC verification
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return None
        
        header_b64, payload_b64, signature_b64 = parts
        
        # Verify signature
        signing_input = f"{header_b64}.{payload_b64}".encode('utf-8')
        expected_sig = hmac.new(
            secret.encode('utf-8'),
            signing_input,
            hashlib.sha256
        ).digest()
        
        # Add padding if needed
        sig_padded = signature_b64 + '=' * (4 - len(signature_b64) % 4)
        actual_sig = base64.urlsafe_b64decode(sig_padded)
        
        if not hmac.compare_digest(expected_sig, actual_sig):
            return None
        
        # Decode payload
        payload_padded = payload_b64 + '=' * (4 - len(payload_b64) % 4)
        payload_bytes = base64.urlsafe_b64decode(payload_padded)
        payload = json.loads(payload_bytes)
        
        return payload
    except Exception:
        return None


def verify_token(token: str, auth_type: str = "bearer", api_keys: Optional[list[str]] = None, 
                 jwt_secret: Optional[str] = None) -> Optional[dict]:
    """
    Verify token based on auth type.
    
    Args:
        token: The token to verify
        auth_type: Either 'bearer' for JWT or 'api_key' for API key
        api_keys: List of valid API keys (for api_key auth type)
        jwt_secret: JWT secret key (for bearer auth type)
    
    Returns:
        User info dict if valid, None otherwise
    """
    if auth_type.lower() == "api_key":
        if verify_api_key(token, api_keys or []):
            return {"type": "api_key", "key": token}
        return None
    elif auth_type.lower() == "bearer":
        if jwt_secret:
            payload = verify_jwt(token, jwt_secret)
            if payload:
                return {"type": "jwt", "payload": payload}
        return None
    return None


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Authentication middleware for Starlette/FastAPI applications.
    
    Supports JWT (Bearer token) and API Key authentication.
    WebSocket connections can authenticate via query parameters.
    """
    
    EXEMPT_PATHS = ["/health", "/metrics"]
    
    def __init__(
        self,
        app: ASGIApp,
        auth_enabled: bool = False,
        api_keys: Optional[list[str]] = None,
        jwt_secret: str = ""
    ):
        super().__init__(app)
        self.auth_enabled = auth_enabled
        self.api_keys = api_keys or []
        self.jwt_secret = jwt_secret
    
    async def dispatch(self, request: Request, call_next):
        # If auth is disabled, pass through
        if not self.auth_enabled:
            return await call_next(request)
        
        # Check if path is exempt
        path = request.url.path
        if any(path.startswith(exempt) for exempt in self.EXEMPT_PATHS):
            return await call_next(request)
        
        # Try to extract and verify token
        user_info = await self._authenticate(request)
        
        if user_info is None:
            return Response(content="Unauthorized", status_code=401)
        
        # Store user info in request state
        request.state.user = user_info
        
        return await call_next(request)
    
    async def _authenticate(self, request: Request) -> Optional[dict]:
        """
        Authenticate request from headers or query params.
        
        Priority:
        1. Authorization: Bearer <token> header
        2. X-API-Key header
        3. Query param ?token=<jwt_token>
        4. Query param ?api_key=<api_key>
        """
        # Check headers first
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
            return verify_token(token, "bearer", api_keys=self.api_keys, jwt_secret=self.jwt_secret)
        
        api_key_header = request.headers.get("x-api-key", "")
        if api_key_header:
            return verify_token(api_key_header, "api_key", api_keys=self.api_keys, jwt_secret=self.jwt_secret)
        
        # Check query params (for WebSocket)
        token_param = request.query_params.get("token", "")
        if token_param:
            return verify_token(token_param, "bearer", api_keys=self.api_keys, jwt_secret=self.jwt_secret)
        
        api_key_param = request.query_params.get("api_key", "")
        if api_key_param:
            return verify_token(api_key_param, "api_key", api_keys=self.api_keys, jwt_secret=self.jwt_secret)
        
        return None
