"""Pure decision layer around Trakt's OAuth device-code flow. Actual
HTTP calls live in clients/trakt.py; this module only makes yes/no
timing decisions so they're unit-testable without any network I/O."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum


class TraktAuthState(str, Enum):
    DISCONNECTED = "disconnected"
    AWAITING_APPROVAL = "awaiting_approval"
    CONNECTED = "connected"
    EXPIRED = "expired"
    ERROR = "error"


@dataclass(frozen=True)
class DeviceCodeResponse:
    device_code: str
    user_code: str
    verification_url: str
    expires_in: int
    interval: int
    issued_at: datetime


@dataclass(frozen=True)
class TokenSet:
    access_token: str
    refresh_token: str
    expires_at: datetime


def is_device_code_expired(resp: DeviceCodeResponse, now: datetime) -> bool:
    return now >= resp.issued_at + timedelta(seconds=resp.expires_in)


def should_poll(resp: DeviceCodeResponse, now: datetime, last_poll_at) -> bool:
    """Rate-limits polling to resp.interval — safe to call on every
    adapter tick without hammering Trakt's token endpoint."""
    if is_device_code_expired(resp, now):
        return False
    if last_poll_at is None:
        return True
    return now >= last_poll_at + timedelta(seconds=resp.interval)


def needs_refresh(tokens: TokenSet, now: datetime, margin_days: int = 7) -> bool:
    return now >= tokens.expires_at - timedelta(days=margin_days)
