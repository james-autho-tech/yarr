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
    "pending_surprise": None,
    "blocked_movies": [{"id": 321, "title": "Rejected Film", "year": 2015,
                         "blocked_at": "2026-08-30T10:00:00+00:00"}],
    "tv_enabled": True,
    "suggested_shows_count": 2,
    "surprise_shows_count": 1,
    "next_tv_surprise_at": "2026-09-06T12:00:00+00:00",
    "effective_tv_genres": ["comedy"],
    "learned_tv_genres": [],
    "recent_suggested_shows": [{"title": "Some Show", "year": 2018, "decision": "added"}],
    "surprise_shows": [{"id": 456, "title": "Surprise Show", "year": 2017, "status": "watched"}],
    "pending_tv_surprise": None,
    "blocked_shows": [{"id": 654, "title": "Rejected Show", "year": 2016,
                        "blocked_at": "2026-08-30T10:00:00+00:00"}],
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
    "disk_used_pct": 92.0,
    "disk_free_gb": 58.0,
    "cycle_check_at": "2026-08-30T17:00:00+00:00",
    "low_space_threshold_pct": 90.0,
    "cycle_candidates_movies": [{"id": 3, "tmdb_id": 333, "title": "Stale Movie", "year": 2016,
                                  "size": 2_000_000_000, "poster_url": None,
                                  "never_watched": True, "last_played_at": None,
                                  "last_activity": "2020-01-01T00:00:00+00:00"}],
    "cycle_candidates_shows": [{"id": 4, "tvdb_id": 444, "title": "Stale Show", "year": 2015,
                                 "size": 6_000_000_000, "poster_url": None,
                                 "never_watched": False, "last_played_at": "2021-01-01T00:00:00+00:00",
                                 "last_activity": "2021-01-01T00:00:00+00:00"}],
    "library_movies": [{"id": 1, "tmdb_id": 111, "title": "Existing Movie", "year": 2019,
                         "monitored": True, "size": 3_000_000_000,
                         "poster_url": "https://image.tmdb.org/t/p/w300/existing.jpg",
                         "genres": ["Action"], "overview": "An existing movie's plot."}],
    "library_movie_count": 1,
    "library_shows": [{"id": 2, "tvdb_id": 222, "title": "Existing Show", "year": 2018,
                        "monitored": True, "size": 5_000_000_000, "poster_url": None,
                        "genres": ["Drama"], "overview": "An existing show's plot."}],
    "library_show_count": 1,
    "library_synced_at": "2026-08-30T17:00:00+00:00",
    "last_search_query": "Some Query",
    "last_search_media_type": "movie",
    "last_search_results": [{"tmdb_id": 999, "tvdb_id": None, "title": "New Movie",
                              "year": 2024, "rating": 7.8, "in_library": False,
                              "poster_url": "https://image.tmdb.org/t/p/w300/new.jpg"}],
    "last_search_at": "2026-08-30T17:00:00+00:00",
    "allow_library_delete": True,
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
            "input_boolean.yarr_dry_run": {"state": "off"},
            "input_boolean.yarr_surprise_enabled": {"state": "on"},
            "input_boolean.yarr_tv_surprise_enabled": {"state": "on"},
            "input_boolean.yarr_surprise_requires_approval": {"state": "on"},
            "input_boolean.yarr_learn_genres_from_library": {"state": "off"},
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
        page.wait_for_selector("#library-search-input")
        for tab in ["Library", "Movies", "TV", "Blocked", "SABnzbd", "Cleanup", "Settings", "Log"]:
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
        page.wait_for_selector("#library-search-input")
        movies = page.locator("#movies-section")
        tv = page.locator("#tv-section")
        dupes = page.locator("#dupes-section")

        page.click("button.tab-btn:has-text('Movies')")
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


def test_library_search_add_delete_and_filter(browser_page):
    page, errors = browser_page
    backend = FakeBackend()
    httpd, port = start_server(backend)
    try:
        page.goto(f"http://127.0.0.1:{port}/")
        page.wait_for_selector("#library-search-input")
        page.click("button.tab-btn:has-text('Library')")
        library = page.locator("#library-section")

        page.fill("#library-search-input", "another query")
        library.get_by_role("button", name="Search", exact=True).click()
        page.wait_for_timeout(1500)

        library.get_by_role("button", name="Add", exact=True).click()
        page.wait_for_timeout(1500)

        library.get_by_role("button", name="Refresh Library", exact=True).click()
        page.wait_for_timeout(1500)

        # Filtering must not touch the input's own value or the search
        # box — this is the whole point of keeping them out of the
        # innerHTML rebuild in refresh().
        page.fill("#library-filter-input", "Existing Movie")
        page.wait_for_timeout(200)
        assert library.locator("#library-movies-body .poster-card").count() == 1
        assert page.input_value("#library-filter-input") == "Existing Movie"

        page.fill("#library-filter-input", "")
        library.get_by_role("button", name="Delete", exact=True).first.click()
        page.wait_for_timeout(1500)

        assert errors == []
        fired_names = [e for e, _ in backend.fired]
        assert "yarr_search_media" in fired_names
        assert "yarr_request_add_movie" in fired_names
        assert "yarr_refresh_library" in fired_names
        assert "yarr_library_delete_movie" in fired_names
    finally:
        httpd.shutdown()


def test_library_detail_modal_opens_and_closes(browser_page):
    page, errors = browser_page
    backend = FakeBackend()
    httpd, port = start_server(backend)
    try:
        page.goto(f"http://127.0.0.1:{port}/")
        page.wait_for_selector("#library-search-input")
        library = page.locator("#library-section")

        # Clicking the poster/title area opens the modal with the
        # item's overview and genres — never the Delete button next to
        # it, which is a DOM sibling specifically so a click there
        # can't bubble into the card's own click handler.
        library.locator("#library-movies-body .poster-clickable").first.click()
        modal = page.locator("#detail-modal")
        assert "show" in (modal.get_attribute("class") or "")
        assert page.locator("#detail-body").inner_text().find("Existing Movie") != -1
        assert page.locator("#detail-body").inner_text().find("An existing movie's plot.") != -1

        page.keyboard.press("Escape")
        assert "show" not in (modal.get_attribute("class") or "")

        # Deleting must never have opened the modal as a side effect.
        library.get_by_role("button", name="Delete", exact=True).first.click()
        page.wait_for_timeout(300)
        assert "show" not in (modal.get_attribute("class") or "")

        assert errors == []
    finally:
        httpd.shutdown()


def test_settings_toggles_fire_and_do_not_crash(browser_page):
    page, errors = browser_page
    backend = FakeBackend()
    httpd, port = start_server(backend)
    try:
        page.goto(f"http://127.0.0.1:{port}/")
        page.wait_for_selector("#library-search-input")
        page.click("button.tab-btn:has-text('Settings')")
        settings = page.locator("#settings-section")

        settings.locator(".settings-row", has_text="Dry run").get_by_role(
            "button", name="On", exact=True).click()
        page.wait_for_timeout(1200)
        settings.locator(".settings-row", has_text="Learn genres from library").get_by_role(
            "button", name="On", exact=True).click()
        page.wait_for_timeout(1200)
        settings.locator(".settings-row", has_text="Surprises need Accept/Deny").get_by_role(
            "button", name="Off", exact=True).click()
        page.wait_for_timeout(1200)

        assert errors == []
        fired_names = [e for e, _ in backend.fired]
        assert "set_state:input_boolean.yarr_dry_run" in fired_names
        assert "set_state:input_boolean.yarr_learn_genres_from_library" in fired_names
        assert "set_state:input_boolean.yarr_surprise_requires_approval" in fired_names
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
        page.wait_for_selector("#library-search-input")
        page.click("button.tab-btn:has-text('Movies')")
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


def test_blocked_tab_unblock_movie_and_show(browser_page):
    page, errors = browser_page
    backend = FakeBackend()
    httpd, port = start_server(backend)
    try:
        page.goto(f"http://127.0.0.1:{port}/")
        page.wait_for_selector("#library-search-input")
        page.click("button.tab-btn:has-text('Blocked')")
        blocked = page.locator("#blocked-section")
        page.wait_for_selector("text=Rejected Film")

        blocked.locator("#blocked-movies-list").get_by_role(
            "button", name="Unblock", exact=True).click()
        page.wait_for_timeout(1200)
        blocked.locator("#blocked-shows-list").get_by_role(
            "button", name="Unblock", exact=True).click()
        page.wait_for_timeout(1200)

        assert errors == []
        fired_names = [e for e, _ in backend.fired]
        assert "yarr_unblock_movie" in fired_names
        assert "yarr_unblock_show" in fired_names
    finally:
        httpd.shutdown()


def test_free_up_space_check_and_delete_candidate(browser_page):
    page, errors = browser_page
    backend = FakeBackend()
    httpd, port = start_server(backend)
    try:
        page.goto(f"http://127.0.0.1:{port}/")
        page.wait_for_selector("#library-search-input")
        page.click("button.tab-btn:has-text('Library')")
        space = page.locator("#space-section")
        page.wait_for_selector("text=Stale Movie")

        space.get_by_role("button", name="Check Space Now", exact=True).click()
        page.wait_for_timeout(1200)

        space.get_by_role("button", name="Delete", exact=True).first.click()
        page.wait_for_timeout(1200)

        assert errors == []
        fired_names = [e for e, _ in backend.fired]
        assert "yarr_check_space_now" in fired_names
        assert "yarr_library_delete_movie" in fired_names
    finally:
        httpd.shutdown()
