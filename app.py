from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field
from supabase import Client, create_client

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("hotel-booking-api")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY")
SUPABASE_PUBLISHABLE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY")
if not SUPABASE_URL or not SUPABASE_SECRET_KEY or not SUPABASE_PUBLISHABLE_KEY:
    raise RuntimeError(
        "Missing SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, or SUPABASE_SECRET_KEY. "
        "Copy .env.example to .env and fill them in."
    )

# This client runs only on the server. Never put the secret key in a browser or GitHub.
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)
app = FastAPI(title="Hotel Booking API", version="1.0.0")


class RegisterRequest(BaseModel):
    email: EmailStr
    phone: str = Field(min_length=8, max_length=30, examples=["0812345678"])
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class AvailabilityRequest(BaseModel):
    room_type_id: str = Field(min_length=1, examples=["standard"])
    check_in: date
    check_out: date


class BookingRequest(BaseModel):
    room_type_id: str = Field(min_length=1, examples=["standard"])
    guest_phone: str = Field(min_length=5, max_length=30)
    guest_name: str = Field(min_length=1, max_length=120)
    check_in: date
    check_out: date
    channel: str = Field(default="voicebot", max_length=40)


class CancelBookingRequest(BaseModel):
    booking_id: str = Field(min_length=1, max_length=80)
    phone: str = Field(min_length=5, max_length=30)


def validate_date_range(check_in: date, check_out: date) -> None:
    if check_out <= check_in:
        raise HTTPException(
            status_code=400,
            detail="check_out must be later than check_in.",
        )


def normalized_phone(phone: str) -> str:
    # Removes common formatting characters, while retaining an optional leading +.
    return "".join(ch for ch in phone.strip() if ch.isdigit() or ch == "+")


def get_operational_rooms(room_type_id: Optional[str] = None) -> list[dict[str, Any]]:
    query = (
        supabase.table("rooms")
        .select("room_number,room_type_id,floor,status")
        .eq("status", "operational")
    )
    if room_type_id:
        query = query.eq("room_type_id", room_type_id)
    response = query.execute()
    return response.data or []


def get_booked_room_numbers(check_in: date, check_out: date) -> set[str]:
    # Date-range overlap: existing check-in < requested check-out AND
    # existing check-out > requested check-in. Only confirmed bookings block rooms.
    response = (
        supabase.table("bookings")
        .select("room_number,check_in,check_out,status")
        .eq("status", "Confirmed")
        .lt("check_in", check_out.isoformat())
        .gt("check_out", check_in.isoformat())
        .execute()
    )
    return {
        str(row["room_number"])
        for row in (response.data or [])
        if row.get("room_number") is not None
    }


def get_available_rooms(room_type_id: str, check_in: date, check_out: date) -> list[dict[str, Any]]:
    rooms = get_operational_rooms(room_type_id)
    booked_numbers = get_booked_room_numbers(check_in, check_out)
    return [room for room in rooms if str(room["room_number"]) not in booked_numbers]


def get_room_type(room_type_id: str) -> dict[str, Any] | None:
    response = (
        supabase.table("room_types")
        .select("id,name,capacity,price_per_night,description,image_url")
        .eq("id", room_type_id)
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else None


def create_auth_client() -> Client:
    """Create a per-request Auth client so users do not share a mutable session."""
    return create_client(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY)


def normalize_auth_phone(phone: str) -> str:
    """Normalize a phone number while preserving a leading + for international numbers."""
    normalized = "".join(ch for ch in phone.strip() if ch.isdigit() or ch == "+")
    digit_count = sum(ch.isdigit() for ch in normalized)
    if (
        not 8 <= digit_count <= 15
        or normalized.count("+") > 1
        or ("+" in normalized and not normalized.startswith("+"))
    ):
        raise HTTPException(status_code=400, detail="Invalid phone number.")
    return normalized


def serialize_auth_user(user: Any, fallback_phone: Optional[str] = None) -> dict[str, Any]:
    metadata = getattr(user, "user_metadata", None) or {}
    return {
        "id": str(user.id),
        "email": getattr(user, "email", None),
        "phone": fallback_phone or metadata.get("phone"),
        "email_confirmed": getattr(user, "email_confirmed_at", None) is not None,
    }


def serialize_auth_session(session: Any) -> Optional[dict[str, Any]]:
    if session is None:
        return None
    return {
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "token_type": session.token_type,
        "expires_in": session.expires_in,
        "expires_at": getattr(session, "expires_at", None),
    }


# Verify users with Supabase Auth and look up roles in public.profiles.
# Never trust a role supplied by the client or stored in user-editable user_metadata.
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict[str, Any]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Missing bearer access token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        auth_response = create_auth_client().auth.get_user(credentials.credentials)
        auth_user = getattr(auth_response, "user", None)
    except Exception as exc:
        logger.info("Access-token verification failed (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired access token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    if auth_user is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired access token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        profile_response = (
            supabase.table("profiles")
            .select("id,phone,role")
            .eq("id", str(auth_user.id))
            .limit(1)
            .execute()
        )
        rows = profile_response.data or []
    except Exception as exc:
        logger.exception("Could not load profile role")
        raise HTTPException(status_code=503, detail="Could not verify account permissions.") from exc

    if not rows:
        raise HTTPException(status_code=403, detail="Account profile is missing. Contact the hotel administrator.")

    profile = rows[0]
    return {
        "id": str(auth_user.id),
        "email": getattr(auth_user, "email", None),
        "phone": profile.get("phone"),
        "role": profile.get("role", "user"),
    }


def require_admin(current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin role required.")
    return current_user


@app.post("/api/auth/register", status_code=201)
def register(payload: RegisterRequest) -> dict[str, Any]:
    """Register using Supabase Auth; never store or hash passwords in our own table."""
    phone = normalize_auth_phone(payload.phone)
    email = str(payload.email).strip().lower()

    try:
        auth_client = create_auth_client()
        response = auth_client.auth.sign_up(
            {
                "email": email,
                "password": payload.password,
                "options": {"data": {"phone": phone}},
            }
        )
    except Exception as exc:
        # Keep internal auth/database error details out of the public response.
        logger.info("Registration request failed (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=400,
            detail="Could not register. The email or phone may already be in use, or the input may be invalid.",
        ) from exc

    if not getattr(response, "user", None):
        raise HTTPException(status_code=400, detail="Registration could not be completed.")

    session = getattr(response, "session", None)
    if session is None:
        message = "Registration received. Check your email to confirm your account before logging in."
    else:
        message = "Registration successful."

    return {
        "message": message,
        "user": serialize_auth_user(response.user, fallback_phone=phone),
        "session": serialize_auth_session(session),
    }


@app.post("/api/auth/login")
def login(payload: LoginRequest) -> dict[str, Any]:
    """Log in with email/password and return the Supabase Auth session tokens."""
    email = str(payload.email).strip().lower()
    try:
        auth_client = create_auth_client()
        response = auth_client.auth.sign_in_with_password(
            {"email": email, "password": payload.password}
        )
    except Exception as exc:
        # Avoid revealing whether an email exists or returning raw Auth errors.
        logger.info("Login request failed (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=401,
            detail="Invalid email/password, or the email has not been confirmed.",
        ) from exc

    if not getattr(response, "user", None) or not getattr(response, "session", None):
        raise HTTPException(
            status_code=401,
            detail="Invalid email/password, or the email has not been confirmed.",
        )

    return {
        "message": "Login successful.",
        "user": serialize_auth_user(response.user),
        "session": serialize_auth_session(response.session),
    }


@app.get("/api/admin/me")
def admin_me(admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    """Confirm the caller is an administrator and return their basic profile."""
    return {"user": admin}


@app.get("/api/admin/bookings")
def admin_list_bookings(
    admin: dict[str, Any] = Depends(require_admin),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """List all bookings. Requires a valid logged-in Admin access token."""
    response = (
        supabase.table("bookings")
        .select("*")
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    bookings = response.data or []
    return {"count": len(bookings), "limit": limit, "offset": offset, "bookings": bookings}


@app.get("/api/admin/rooms")
def admin_list_rooms(admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    """List every physical room, including non-operational rooms. Admin only."""
    rooms_response = (
        supabase.table("rooms")
        .select("room_number,room_type_id,floor,status")
        .order("room_number")
        .execute()
    )
    types_response = (
        supabase.table("room_types")
        .select("id,name,capacity,price_per_night")
        .execute()
    )
    type_by_id = {row["id"]: row for row in (types_response.data or [])}
    rooms = [
        {**room, "room_type": type_by_id.get(room.get("room_type_id"))}
        for room in (rooms_response.data or [])
    ]
    return {"count": len(rooms), "rooms": rooms}


@app.get("/api/admin/room-types")
def admin_list_room_types(admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    """List all room types and pricing. Admin only."""
    response = (
        supabase.table("room_types")
        .select("*")
        .order("price_per_night")
        .execute()
    )
    room_types = response.data or []
    return {"count": len(room_types), "room_types": room_types}


@app.get("/api/admin/profiles")
def admin_list_profiles(
    admin: dict[str, Any] = Depends(require_admin),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """List user profiles and role assignments. Admin only."""
    response = (
        supabase.table("profiles")
        .select("id,phone,role,created_at")
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    profiles = response.data or []
    return {"count": len(profiles), "limit": limit, "offset": offset, "profiles": profiles}


@app.get("/api/admin/users")
def admin_list_auth_users(
    admin: dict[str, Any] = Depends(require_admin),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=1000),
) -> dict[str, Any]:
    """List Supabase Auth accounts. Requires the server-side Secret Key."""
    try:
        response = supabase.auth.admin.list_users(params={"page": page, "per_page": per_page})
        user_records = getattr(response, "users", response)
        user_records = list(user_records or [])

        profiles_response = supabase.table("profiles").select("id,phone,role").execute()
        profile_by_id = {row["id"]: row for row in (profiles_response.data or [])}
        users = []
        for auth_user in user_records:
            profile = profile_by_id.get(str(auth_user.id), {})
            users.append({
                "id": str(auth_user.id),
                "email": getattr(auth_user, "email", None),
                "phone": profile.get("phone") or getattr(auth_user, "phone", None),
                "role": profile.get("role", "user"),
                "email_confirmed_at": getattr(auth_user, "email_confirmed_at", None),
                "created_at": getattr(auth_user, "created_at", None),
                "last_sign_in_at": getattr(auth_user, "last_sign_in_at", None),
            })
        return {"page": page, "per_page": per_page, "count": len(users), "users": users}
    except Exception as exc:
        logger.exception("Could not list Auth users for administrator")
        raise HTTPException(status_code=503, detail="Could not load user accounts.") from exc


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/rooms")
def list_rooms(
    check_in: Optional[date] = Query(default=None, description="Optional check-in date, YYYY-MM-DD"),
    check_out: Optional[date] = Query(default=None, description="Optional check-out date, YYYY-MM-DD"),
) -> dict[str, Any]:
    if (check_in is None) != (check_out is None):
        raise HTTPException(status_code=400, detail="Provide both check_in and check_out, or neither.")

    # Without dates, report availability for tonight (Bangkok date to the next day).
    if check_in is None or check_out is None:
        today_bkk = datetime.now(ZoneInfo("Asia/Bangkok")).date()
        check_in, check_out = today_bkk, today_bkk + timedelta(days=1)
    validate_date_range(check_in, check_out)

    room_types_response = (
        supabase.table("room_types")
        .select("id,name,capacity,price_per_night,description,image_url")
        .order("price_per_night")
        .execute()
    )
    room_types = room_types_response.data or []
    output: list[dict[str, Any]] = []
    for room_type in room_types:
        rooms = get_operational_rooms(room_type["id"])
        available_rooms = get_available_rooms(room_type["id"], check_in, check_out)
        output.append(
            {
                **room_type,
                "total_rooms": len(rooms),
                "available_count": len(available_rooms),
            }
        )

    return {
        "check_in": check_in.isoformat(),
        "check_out": check_out.isoformat(),
        "room_types": output,
    }


@app.post("/api/check-availability")
def check_availability(payload: AvailabilityRequest) -> dict[str, Any]:
    validate_date_range(payload.check_in, payload.check_out)
    room_type = get_room_type(payload.room_type_id)
    if not room_type:
        raise HTTPException(status_code=404, detail="Room type not found.")

    available_rooms = get_available_rooms(
        payload.room_type_id, payload.check_in, payload.check_out
    )
    total_nights = (payload.check_out - payload.check_in).days
    price = float(room_type["price_per_night"])
    return {
        "room_type_id": room_type["id"],
        "room_type_name": room_type["name"],
        "check_in": payload.check_in.isoformat(),
        "check_out": payload.check_out.isoformat(),
        "total_nights": total_nights,
        "price_per_night": price,
        "estimated_total_price": price * total_nights,
        "available": len(available_rooms) > 0,
        "available_count": len(available_rooms),
    }


@app.post("/api/bookings", status_code=201)
def create_booking(payload: BookingRequest) -> Any:
    validate_date_range(payload.check_in, payload.check_out)
    phone = normalized_phone(payload.guest_phone)
    if len(phone) < 5:
        raise HTTPException(status_code=400, detail="Invalid guest_phone.")

    try:
        # The SQL function performs physical-room selection and insert atomically.
        response = supabase.rpc(
            "create_hotel_booking",
            {
                "p_room_type_id": payload.room_type_id,
                "p_guest_phone": phone,
                "p_guest_name": payload.guest_name.strip(),
                "p_check_in": payload.check_in.isoformat(),
                "p_check_out": payload.check_out.isoformat(),
                "p_channel": payload.channel,
            },
        ).execute()
        return response.data
    except Exception as exc:  # Do not return raw database details to an API caller.
        message = str(exc)
        logger.exception("Could not create hotel booking")
        if "NO_ROOM_AVAILABLE" in message:
            raise HTTPException(status_code=409, detail="No room is available for those dates.") from exc
        if "ROOM_TYPE_NOT_FOUND" in message:
            raise HTTPException(status_code=404, detail="Room type not found.") from exc
        if any(code in message for code in ("INVALID_DATE_RANGE", "GUEST_NAME_REQUIRED", "GUEST_PHONE_REQUIRED")):
            raise HTTPException(status_code=400, detail="Invalid booking details.") from exc
        raise HTTPException(status_code=500, detail="Could not create booking. Check server logs.") from exc


@app.get("/api/bookings")
def lookup_bookings(phone: str = Query(min_length=5, max_length=30)) -> dict[str, Any]:
    normalized = normalized_phone(phone)
    response = (
        supabase.table("bookings")
        .select(
            "booking_id,room_number,room_type_id,guest_phone,guest_name,check_in,check_out,"
            "total_nights,total_price,status,channel,created_at"
        )
        .eq("guest_phone", normalized)
        .order("check_in", desc=True)
        .execute()
    )
    bookings = response.data or []
    return {"phone": normalized, "count": len(bookings), "bookings": bookings}


@app.post("/api/bookings/cancel")
def cancel_booking(payload: CancelBookingRequest) -> Any:
    phone = normalized_phone(payload.phone)
    try:
        response = supabase.rpc(
            "cancel_hotel_booking",
            {
                "p_booking_id": payload.booking_id.strip(),
                "p_guest_phone": phone,
            },
        ).execute()
        return response.data
    except Exception as exc:
        message = str(exc)
        logger.exception("Could not cancel hotel booking")
        if "BOOKING_NOT_FOUND_OR_NOT_CANCELLABLE" in message:
            raise HTTPException(
                status_code=404,
                detail="Booking not found, phone does not match, or booking cannot be cancelled.",
            ) from exc
        raise HTTPException(status_code=500, detail="Could not cancel booking. Check server logs.") from exc
