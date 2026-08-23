from datetime import datetime, timedelta, timezone

from core.trakt_auth import DeviceCodeResponse, TokenSet, is_device_code_expired, should_poll, needs_refresh


def make_resp(now, expires_in=600, interval=5):
    return DeviceCodeResponse(device_code="dc", user_code="ABCD-1234",
                               verification_url="https://trakt.tv/activate",
                               expires_in=expires_in, interval=interval, issued_at=now)


def test_is_device_code_expired():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    resp = make_resp(now, expires_in=600)
    assert is_device_code_expired(resp, now + timedelta(seconds=599)) is False
    assert is_device_code_expired(resp, now + timedelta(seconds=601)) is True


def test_should_poll_first_time_true():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    resp = make_resp(now)
    assert should_poll(resp, now, None) is True


def test_should_poll_respects_interval():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    resp = make_resp(now, interval=5)
    last = now
    assert should_poll(resp, now + timedelta(seconds=3), last) is False
    assert should_poll(resp, now + timedelta(seconds=5), last) is True


def test_should_poll_false_once_device_code_expired():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    resp = make_resp(now, expires_in=10)
    assert should_poll(resp, now + timedelta(seconds=20), None) is False


def test_needs_refresh_margin_boundary():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    tokens = TokenSet(access_token="a", refresh_token="r", expires_at=now + timedelta(days=7))
    assert needs_refresh(tokens, now, margin_days=7) is True
    tokens2 = TokenSet(access_token="a", refresh_token="r", expires_at=now + timedelta(days=8))
    assert needs_refresh(tokens2, now, margin_days=7) is False
