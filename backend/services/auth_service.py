"""Server-side Supabase Auth validation. Never trusts client supplied roles or organizations."""
from dataclasses import dataclass
from fastapi import Depends, Header, HTTPException
from services.database_service import _client

@dataclass(frozen=True)
class CurrentUser:
    user_id: str
    organization_id: str
    role: str
    email: str

def require_user(authorization: str | None = Header(default=None)) -> CurrentUser:
    if not authorization or not authorization.startswith("Bearer ") or not authorization[7:].strip():
        raise HTTPException(status_code=401, detail="Authentication is required.")
    try:
        auth_user = _client().auth.get_user(authorization[7:].strip()).user
        if not auth_user:
            raise ValueError("user unavailable")
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Your session is invalid or expired.") from exc
    try:
        result = _client().table("profiles").select("organization_id,role,email").eq("id", auth_user.id).execute()
        profile=(result.data or [None])[0]
        if not profile or not profile.get("organization_id") or profile.get("role") not in {"admin", "reviewer", "requester"}:
            raise HTTPException(status_code=403, detail="Your account profile or organization membership is incomplete.")
        # The verified Auth email is authoritative for invitation acceptance;
        # profile.email is mutable application data and must not be trusted for it.
        return CurrentUser(str(auth_user.id), str(profile["organization_id"]), profile["role"], auth_user.email or "")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=403, detail="Your account profile or organization membership is unavailable.") from exc

def require_role(*roles: str):
    def dependency(user: CurrentUser=Depends(require_user)):
        if user.role not in roles: raise HTTPException(status_code=403,detail='You do not have permission for this action.')
        return user
    return dependency
