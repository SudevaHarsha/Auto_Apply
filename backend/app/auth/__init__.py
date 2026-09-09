"""auth domain service layer (S3).

Operations map 1:1 to the canonical auth endpoints (api_contracts §7, §17, §23).
HTTP route assembly is the backend_api step (S14); this package never mounts routers.
"""

from backend.app.auth.service import AuthResult, AuthService, RefreshResult, UserOut
from backend.app.auth.settings_service import SettingsService
from backend.app.auth.user_profile_service import UserProfileService

__all__ = [
    "AuthService",
    "AuthResult",
    "RefreshResult",
    "UserOut",
    "SettingsService",
    "UserProfileService",
]