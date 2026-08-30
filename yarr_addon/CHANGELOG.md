# Changelog

## 0.10.0

- Added a **Delete All Inferior Duplicates** bulk button to the
  Duplicates tab. Each scan now also cross-checks every duplicate group
  against Radarr's/Sonarr's actually-tracked file paths and computes a
  "safe to bulk-delete" count/size — a group only counts as safe when
  exactly one file in it matches a tracked path; zero or multiple
  matches leaves that group untouched for manual review instead of
  guessing. Still entirely manual: one click, one confirm showing the
  count, then every safe file is deleted in a single pass (with the
  same empty-folder cleanup and Radarr/Sonarr rescan as the per-file
  delete) — nothing happens on its own, no scheduled auto-delete.

## 0.9.2

- Fixed the Duplicates tab's per-file **Delete** button doing nothing:
  a file path JSON-encodes to a double-quoted string, which collided
  with the double-quoted `onclick="..."` attribute it was embedded in
  and silently truncated the handler. Numeric-id delete buttons
  (surprises) never hit this since `JSON.stringify()` on a number has
  no quotes to collide with.

## 0.9.1

- Deleting a duplicate file now also: removes any now-empty parent
  folder left behind (stopping at the configured `media_scan_paths`
  root — never the root itself, never outside it), and fires a Radarr
  `RenameMovie` / Sonarr `RenameSeries` command for the surviving copy
  in case it doesn't match your configured naming format (best-effort
  — a failure here is logged but never undoes the delete).

## 0.9.0

- The duplicate media scan is no longer report-only: each file in a
  duplicate group now gets its own **Delete** button in the web UI
  (with a confirm prompt). yArr only ever deletes a path that was
  actually part of the last scan's results — never an arbitrary path —
  and every delete triggers a Radarr and (if enabled) Sonarr library
  rescan afterward, so their databases notice the file is gone right
  away instead of drifting out of sync until their own periodic disk
  scan catches up. Requires the `media` mount to be writable, so
  `config.yaml`'s map entry switched from read-only to read-write.

## 0.8.0

- Added an optional **duplicate media scan**: scans NAS paths (via
  HA's own `/media` share — needs Settings → System → Storage → Add
  Network Storage set up first, see DOCS.md) for files sharing an
  identical size, a strong and cheap signal for duplicate video files
  without hashing an entire library. Report-only — yArr never deletes,
  moves, or renames anything it finds, only lists candidate groups in
  a new Duplicates tab in the web UI (with total wasted space and a
  Scan Now button). Off by default; enable via `media_scan_paths` in
  `apps.yaml`.

## 0.7.1

- Added `tick_reconcile_surprises` (every 30 min): cross-checks tracked
  surprises against what's actually still in Radarr/Sonarr and
  untracks anything deleted directly there instead of through yArr —
  previously that left stale entries tracked forever.
- Delete failures (manual, grace-period, or reconciliation-adjacent) no
  longer get stuck retrying forever — if Radarr/Sonarr rejects the
  delete (most commonly because it's already gone), yArr untracks it
  anyway with a warning instead of repeating the same failure every
  cycle. Fixes a real case: a Sonarr series already deleted directly
  caused every delete attempt to 500 indefinitely.
- Added `tmdb_pages` (default 3, was implicitly 1): TMDB's 20-results-
  per-page default pool was getting exhausted fast once genre/rating/
  exclusion/already-suggested filters were applied, causing "no
  surprise candidate matched" more often than the actual pool of good
  titles would suggest.

## 0.7.0

- **Surprise picks now require Accept/Deny approval by default**
  (`surprise_requires_approval: true`). A pick is proposed in the web
  UI (title, year, rating, genres) and never touches Radarr/Sonarr
  until accepted; only one proposal is outstanding at a time. Set to
  `false` to restore the old auto-add-outright behaviour.
- **Denying a proposal actually teaches yArr something**: each denied
  pick's genres are tallied, and once a genre crosses
  `surprise_feedback_deny_threshold` (default 2) denials, it's
  automatically excluded from future picks on top of
  `excluded_genres` — a real feedback loop, not just a log entry.
- Added a **Delete** button on every tracked surprise in the web UI —
  immediate, unconditional removal from Radarr/Sonarr regardless of
  watch status, independent of the watch-triggered grace-period flow.

## 0.6.1

- Radarr/Sonarr add failures now surface the actual response body in
  the log (e.g. the real validation reason: bad root folder path,
  already-added title, etc.) instead of just "HTTP 400", which made
  every failure look identical and undebuggable from the log alone.

## 0.6.0

- **Fixed 0.5.0's fix**: a real install showed HA's Config REST API
  returns HTTP 404 for `input_boolean`/`input_button` (modern HA moved
  simple helpers to a config-entry flow that endpoint doesn't serve —
  only `automation`/`scene`/`script` still support it; confirmed
  working since `automation.yarr_playback_stop_relay` synced fine in
  the same run). Dropped the dependency entirely instead of chasing
  the right API: yarr.py now owns `yarr_enable`/`yarr_keep_surprise`/
  `yarr_keep_surprise_tv` directly as AppDaemon virtual states
  (created on first start if missing), and the "Surprise Me Now"
  buttons fire a plain HA event (`POST /api/events/<type>`) instead of
  pressing an `input_button` entity — neither needs any HA-side setup
  at all now. `ha_support.yaml` documents how to add real helpers
  instead if you want them toggleable from your own dashboard too.
- Also fixed a startup-ordering bug: the (now-automation-only) Config
  API sync ran *before* the existing "wait for HA core to be ready"
  retry loop, so it could silently no-op if HA hadn't finished starting
  yet. Moved it after.
- Added a working **Keep It** button in the web UI for a pending
  deletion — this control was described in earlier versions but never
  actually wired up to anything.

## 0.5.0

- **Dropped the `homeassistant_config` filesystem mount entirely.**
  Helpers (`input_boolean`/`input_button`) and the Jellyfin
  webhook-relay automation are now created via HA's Core Config REST
  API (`/api/config/<domain>/config/<id>` — the same endpoint Settings
  → Helpers/Automations itself uses) instead of writing a YAML package
  file. This needs nothing beyond the ordinary Core API access every
  add-on already has, so it no longer depends on HA's per-add-on
  **Protection mode**, which a real install showed can silently block
  the old filesystem write even with the map entry correctly declared.
  `ha_support.yaml` is kept only as a readable reference / manual
  fallback, not something the add-on writes anymore.
- Added tabbed navigation to the web UI (Movies / TV / SABnzbd / Log)
  instead of one long scrolling page — remembers your last-viewed tab.

## 0.4.0

- Added a persisted rolling event log (additions, surprises,
  deletions, kept items, errors) surfaced as a Log section in the web
  UI — survives restarts, capped at 50 entries.
- Reworked the web UI's visual design again: true near-black
  background, pure white text, and one confident bold accent colour
  used decisively, with larger/bolder type throughout instead of
  uniformly small text.
- Documented the real cause of "Surprise Me Now" silently doing
  nothing on a fresh install: Home Assistant's per-add-on **Protection
  mode** blocks the `homeassistant_config:rw` write even when
  config.yaml declares it, so the helper entities (buttons/toggles)
  never get created until it's turned off manually — see DOCS.md.

## 0.3.0

- Added `excluded_genres`: a hard veto checked independently of
  `genres`/`tv_genres` (or a learned profile) — a title carrying an
  excluded genre is never suggested or surprised, full stop. Lets
  `learn_genres_from_library` be used safely without a disliked genre
  ever sneaking back in via watch history.
- Suggested/surprise records now carry the release year, and the
  status sensor exposes real recent-suggestion and tracked-surprise
  lists (title, year, decision/status, delete countdown) instead of
  just counts — surfaced in the web UI as proper tables.
- The status sensor also now reports `learn_genres_from_library`,
  `excluded_genres`, and the currently *effective* genre list (fixed
  or learned) — previously there was no way to see whether library
  taste-learning was active or what it had derived.
- Reworked the web UI's visual design (distinct palette/typography
  instead of a generic dashboard look) and added the SABnzbd queue's
  individual item list, not just aggregate numbers.

## 0.2.2

- Removed `armv7`/`armhf`/`i386` from `arch`/`build.yaml` (deprecated
  and unsupported as of HA 2025.12) and dropped `startup`/`boot`/
  `hassio_role` from config.yaml — all three were just restating the
  schema's own default values, which HA's add-on linter now flags.

## 0.2.1

- Fixed a bad install/update on a fresh config: `sonarr_url` and
  `sabnzbd_url` were typed `url?` in config.yaml, but HA's `url` schema
  type validates the value as an actual URL even when the field is
  optional — an empty-string default (needed so they can be left blank
  to stay opt-out) failed with "expected a URL". Switched to `str?`,
  which has no such format check.

## 0.2.0

- Added TV support: genre auto-add and surprise rotation against
  Sonarr, mirroring the movie feature set. Sonarr identifies shows by
  TVDB id rather than TMDB id, so candidates get their tvdb_id resolved
  via TMDB's external-ids lookup before being added. A surprise show is
  only deleted once its *last* episode is confirmed watched (checked
  live against Jellyfin's own per-series played status), not
  episode-by-episode. Entirely opt-in — set `sonarr_url`/`sonarr_api_key`
  to enable it, leave blank to stay movies-only.
- Added `learn_genres_from_library`: an alternative to hand-typing
  `genres`/`tv_genres`, deriving a weighted genre profile from your
  Jellyfin watch history (favourites and replay count weighted higher).
- Added optional read-only SABnzbd queue monitoring
  (`sabnzbd_url`/`sabnzbd_api_key`) — a status sensor and web UI card,
  never writes anything to the queue.
- One Jellyfin webhook now handles both movie and episode PlaybackStop
  events (dispatched by `ItemType`), rather than needing a second
  webhook for TV.

## 0.1.0

- Initial release: TMDB-driven genre auto-add to Radarr, an automatic
  random "surprise film" rotation (tagged separately in Radarr), and a
  Jellyfin-webhook-triggered watch-and-delete loop for surprise films
  only, with a configurable grace period and a keep-it-instead toggle.
  Watch-history exclusion reads Jellyfin's own per-user played status
  directly (TMDB has no personal-account concept, so this replaced an
  earlier Trakt-based design that turned out to need a paid VIP tier
  for its recommendations API).
