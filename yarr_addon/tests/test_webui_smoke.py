"""Browser smoke test for the Ingress web UI — the only thing in this
suite that actually executes webui.py's JS in a real engine. The rest
of this test suite proves core/'s pure logic is right, and CI's
esprima step proves the shipped page's <script> block parses; neither
would have caught either of these real incidents:

  - v0.10.x: a duplicate file's path, JSON-stringified straight into
    an onclick="..." attribute, collided with the attribute's own
    quotes and silently truncated the handler — the Delete button did
    nothing, no error anywhere.
  - v0.11.0: an HTML fragment built as a single-quoted JS string
    contained another single-quoted JS string nested inside it,
    relying on a backslash escape that Python's own (non-raw) string
    parsing silently consumed before it reached the browser — the
    resulting unescaped quote broke the entire <script> block, so
    nothing on the page worked at all.

Both are runtime/DOM-level failures: the static script text was less
wrong than what the browser actually received once the template
interpolated real data into it. This test loads the actual generated
page in headless Chromium with fixture data, clicks every visible
action button, and asserts nothing throws — which would have caught
both bugs above. It does NOT validate business logic (e.g. whether a
button's underlying handler computes the right answer) — that's what
core/'s pytest suite and manual verification against a real install
are for.

Skipped automatically if the `playwright` package or its browser isn't
installed (a plain local `pytest` run) — CI installs both.
"""
import copy
import os
import socketserver
import sys
import threading

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright  # noqa: E402

os.environ.setdefault("SUPERVISOR_TOKEN", "test-token")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "rootfs", "opt", "yarr-web"))
import webui  # noqa: E402


BASE_STATUS_ATTRS = {
    "missing_secrets": [],
    "learn_genres_from_library": False,
    "excluded_genres": ["horror"],
    "denied_genres": [],
    "effective_genres": ["action", "comedy"],
    "learned_genres": [],
    "suggested_count": 3,
    "surprise_count": 1,
    "next_surprise_at": "2026-09-05T12:00:00+00:00",
    "recent_suggested": [{"title": "Some Film", "year": 2020, "decision": "added"}],
    "surprises": [{"id": 123, "title": "Surprise Film", "year": 2019,
                   "status": "deleting_soon", "delete_at": "2026-09-01T00:00:00+00:00"}],
    "surprise_requires_approval": True,
    "pending_surprise": None,
    "tv_enabled": True,
    "suggested_shows_count": 2,
    "surprise_shows_count": 1,
    "next_tv_surprise_at": "2026-09-06T12:00:00+00:00",
    "effective_tv_genres": ["comedy"],
    "learned_tv_genres": [],
    "recent_suggested_shows": [{"title": "Some Show", "year": 2018, "decision": "added"}],
    "surprise_shows": [{"id": 456, "title": "Surprise Show", "year": 2017, "status": "watched"}],
    "pending_tv_surprise": None,
    "sabnzbd_enabled": True,
    "media_scan_enabled": True,
    "duplicate_groups": [[
        {"path": "/media/movies/A/film.mkv", "size": 4_000_000_000},
        {"path": "/media/movies/A (copy)/film.mkv", "size": 4_000_000_000},
    ]],
    "duplicate_group_count": 1,
    "duplicate_wasted_bytes": 4_000_000_000,
    "duplicate_scan_at": "2026-08-30T17:00:00+00:00",
    "duplicate_deletable_count": 1,
    "duplicate_deletable_bytes": 4_000_000_000,
    "junk_entries": [
        {"path": "/media/tv/Show/_UNPACK_Show.S01E01", "size": 1_500_000_000, "is_dir": True},
    ],
    "junk_count": 1,
    "junk_bytes": 1_500_000_000,
    "junk_scan_at": "2026-08-30T17:00:00+00:00",
    "log": [{"ts": "2026-08-30T17:00:00+00:00", "level": "info", "message": "Initial state."}],
}

SABNZBD_STATUS = {
    "state": "Downloading",
    "attributes": {"speed_kbps": 512, "size_left": "1.2 GB", "eta": "5m", "paused": False,
                    "queue_count": 1,
                    "items": [{"filename": "some.nzb", "percentage": 42, "status": "Downloading"}]},
}


class FakeBackend:
    """Stands in for the real Supervisor/AppDaemon: records every event
    the web UI fires, and — since there's no real AppDaemon here to
    republish sensor.yarr_status a moment later — immediately appends a
    new log entry itself, so runAction's poll-for-a-new-log-entry logic
    (webui.py's client-side JS) resolves in ~1s instead of exhausting
    all 8 tries every click."""

    def __init__(self, attrs_overrides=None):
        self.attrs = copy.deepcopy(BASE_STATUS_ATTRS)
        self.attrs.update(attrs_overrides or {})
        self.fired = []
        self._n = 0

    def get_all_states(self):
        return {
            "sensor.yarr_status": {"state": "OK", "attributes": self.attrs},
            "sensor.yarr_sabnzbd_status": SABNZBD_STATUS,
            "input_boolean.yarr_enable": {"state": "on"},
            "input_boolean.yarr_keep_surprise": {"state": "off"},
            "input_boolean.yarr_keep_surprise_tv": {"state": "off"},
        }

    def fire_event(self, event_type, data=None):
        self._n += 1
        self.fired.append((event_type, data))
        self.attrs["log"] = [{"ts": f"2026-08-30T18:{self._n:02d}:00+00:00",
                               "level": "info", "message": f"handled {event_type}"}] + self.attrs["log"]
        return 200

    def set_state(self, entity_id, state, attributes=None):
        self.fired.append((f"set_state:{entity_id}", state))
        return 200


def start_server(backend):
    webui.ha_get_all_states = backend.get_all_states
    webui.ha_fire_event = backend.fire_event
    webui.ha_set_state = backend.set_state
    httpd = socketserver.TCPServer(("127.0.0.1", 0), webui.Handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, port


@pytest.fixture
def browser_page():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
        page.on("dialog", lambda dialog: dialog.accept())
        yield page, errors
        browser.close()


def test_page_loads_all_tabs_no_errors(browser_page):
    page, errors = browser_page
    backend = FakeBackend()
    httpd, port = start_server(backend)
    try:
        page.goto(f"http://127.0.0.1:{port}/")
        page.wait_for_selector("text=Surprise Me Now")
        for tab in ["Movies", "TV", "SABnzbd", "Cleanup", "Log"]:
            page.click(f"button.tab-btn:has-text('{tab}')")
        assert errors == []
    finally:
        httpd.shutdown()


def test_every_action_button_fires_and_does_not_crash(browser_page):
    page, errors = browser_page
    backend = FakeBackend()
    httpd, port = start_server(backend)
    try:
        page.goto(f"http://127.0.0.1:{port}/")
        page.wait_for_selector("text=Surprise Me Now")
        movies = page.locator("#movies-section")
        tv = page.locator("#tv-section")
        dupes = page.locator("#dupes-section")

        movies.get_by_role("button", name="Surprise Me Now", exact=True).click()
        page.wait_for_timeout(1500)
        movies.locator("button.ghost", has_text="Keep It").click()
        page.wait_for_timeout(300)
        movies.get_by_role("button", name="Delete", exact=True).first.click()
        page.wait_for_timeout(1500)

        page.click("button.tab-btn:has-text('TV')")
        tv.get_by_role("button", name="Surprise Me Now (TV)", exact=True).click()
        page.wait_for_timeout(1500)

        page.click("button.tab-btn:has-text('Cleanup')")
        dupes.get_by_role("button", name="Scan Now", exact=True).click()
        page.wait_for_timeout(1500)
        dupes.get_by_role("button", name="Delete All Inferior Duplicates", exact=True).click()
        page.wait_for_timeout(1500)
        dupes.get_by_role("button", name="Delete All Junk", exact=True).click()
        page.wait_for_timeout(1500)
        dupes.get_by_role("button", name="Delete", exact=True).first.click()
        page.wait_for_timeout(1500)
        dupes.get_by_role("button", name="Delete", exact=True).last.click()
        page.wait_for_timeout(1500)

        assert errors == []
        fired_names = [e for e, _ in backend.fired]
        assert "yarr_surprise_me_now" in fired_names
        assert "yarr_surprise_tv_now" in fired_names
        assert "yarr_delete_surprise_now" in fired_names
        assert "yarr_scan_duplicates_now" in fired_names
        assert "yarr_bulk_delete_duplicates" in fired_names
        assert "yarr_bulk_delete_junk" in fired_names
        assert "yarr_delete_duplicate_file" in fired_names
        assert "yarr_delete_junk_entry" in fired_names
        assert "set_state:input_boolean.yarr_keep_surprise" in fired_names
    finally:
        httpd.shutdown()


def test_accept_and_deny_pending_surprises(browser_page):
    page, errors = browser_page
    backend = FakeBackend({
        "pending_surprise": {"title": "Pending Film", "year": 2021, "rating": 7.2, "genres": ["comedy"]},
        "pending_tv_surprise": {"title": "Pending Show", "year": 2022, "rating": 6.8, "genres": ["comedy"]},
    })
    httpd, port = start_server(backend)
    try:
        page.goto(f"http://127.0.0.1:{port}/")
        page.wait_for_selector("text=Pending Film")
        page.get_by_role("button", name="Accept", exact=True).click()
        page.wait_for_timeout(1500)

        page.click("button.tab-btn:has-text('TV')")
        page.wait_for_selector("text=Pending Show")
        page.get_by_role("button", name="Deny", exact=True).click()
        page.wait_for_timeout(1500)

        assert errors == []
        fired_names = [e for e, _ in backend.fired]
        assert "yarr_accept_surprise" in fired_names
        assert "yarr_deny_tv_surprise" in fired_names
    finally:
        httpd.shutdown()
