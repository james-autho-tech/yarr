# Changelog

## 0.18.0

- Added **Free Up Space** to the Library tab (opt-in via
  `media_scan_paths`, same as the Duplicates/Cleanup feature): when
  disk usage crosses `low_space_threshold_pct` (default 90%), yArr
  ranks the least recently watched (or never watched) titles in your
  library and lists them for review — oldest activity first. Purely a
  recommendation list; deleting a candidate uses the exact same Delete
  action (and `allow_library_delete` gate) as the rest of the Library
  tab, no new deletion path. **Check Space Now** triggers an immediate
  check.

## 0.17.0

- Denying a proposed surprise now **blocks that exact title outright**,
  everywhere — not just its genre. A blocked movie/show is a hard
  exclusion from genre auto-add and future surprise picks, on any
  medium, until unblocked.
- Added a **Blocked** tab to the web UI listing every blocked movie
  and show, each with an **Unblock** button to make it eligible again
  immediately, no restart needed.

## 0.16.0

- Added a **Settings** tab: `dry_run`, `surprise_enabled`,
  `tv_surprise_enabled`, `surprise_requires_approval`, and
  `learn_genres_from_library` are now live toggles in the web UI
  instead of apps.yaml-only settings — flip one and it takes effect
  immediately, no file edit or restart. Same mechanism as the existing
  "yArr Engine" master switch and "Keep It" buttons (an AppDaemon-owned
  virtual `input_boolean`, not a real HA helper). `apps.yaml` still has
  entries for all five, but they only ever seed the toggle's value the
  first time it's created — upgrading to this version won't silently
  change anyone's current behaviour, and editing apps.yaml after that
  point does nothing for these five; the toggle is the sole source of
  truth from then on.

## 0.15.0

- `learn_genres_from_library` now blends **two** taste signals instead
  of one: Jellyfin's watch history (as before — watched/favourited
  items, weighted by play count) *and* your full Radarr/Sonarr
  library's genre mix (the Library tab's own data — everything you've
  collected, whether watched or not). Owning something is a weaker
  signal than watching it, so library-only items carry no extra
  weight, but a title that's both owned and watched naturally ranks
  higher than one merely sitting there unwatched, since it contributes
  to both signals. No new config — this only changes what
  `learn_genres_from_library: true` already does; no code changes if
  you're not using it.

## 0.14.2

- **Library is now the first tab** and the default landing view.
- Clicking a poster/title in the Library tab opens a **detail view**
  (synopsis, genres, rating/size) instead of only showing the card's
  title and year — the Add/Delete button sits outside the clickable
  area so it never triggers the detail view by accident. Press Escape
  or click outside the card to close it.
- **The page is much wider on desktop** — the poster grid was
  capped at the same 820px reading-width used for the text-table
  tabs, which meant only ~5 columns even on a wide monitor. The
  Library tab now uses the full page width (up to 1600px); the
  text/table tabs (Movies, TV, SABnzbd, Cleanup, Log) keep the
  original narrower width, since a table of text doesn't benefit
  from stretching edge to edge the way a poster grid does.

## 0.14.1

- The Library tab (search results and your existing library) now
  shows **poster art in a card grid** instead of plain text rows.
  Search results use TMDB's own poster image; your existing library
  uses the poster Radarr/Sonarr already has cached (their own
  `images` field, which carries a publicly-reachable TMDB-hosted URL)
  — no extra API calls needed either way. Falls back to a plain
  title card when no poster is available.

## 0.14.0

- Added a **Library** tab: search TMDB for any movie/show and add it
  with one click (reuses your existing root folder/quality profile
  config, same add path as genre auto-add and surprises), and browse/
  manage your **entire** existing Radarr/Sonarr library — not just
  what yArr itself suggested or surprised you with — with size, year,
  and a client-side filter box. Search is press-Search-and-wait, not
  live-as-you-type: the web UI and AppDaemon never talk to each other
  directly (every action round-trips through an HA event), so a
  keystroke-by-keystroke search isn't feasible without giving the web
  UI its own direct TMDB access, which would break that architecture.
- **Deleting from the full library is off by default** — it can remove
  a movie/show you've had for years, never touched by yArr at all, a
  much bigger blast radius than anything else yArr deletes. Requires
  `allow_library_delete: true` in `apps.yaml` on top of the web UI's
  own confirm dialog before the Delete buttons in the Library tab do
  anything; the tab explains this and shows the buttons disabled until
  it's set.
- Library data refreshes automatically every `library_refresh_interval_hours`
  (default 1h — cheap, just a Radarr/Sonarr GET each, no NAS
  filesystem walk) or on demand via the tab's **Refresh Library**
  button.

## 0.13.1

- **Junk detection got three real safety gates, after a genuine
  incident**: a user's deliberate "Delete All Junk" click removed a
  folder that turned out to still be needed, because file age alone
  can't tell a stalled-but-abandoned unpack apart from one still
  legitimately in progress. Now, before anything is ever called junk:
  it must not match anything in SABnzbd's own live queue (downloading,
  paused, or mid-repair — checked by normalized name if SABnzbd
  monitoring is configured); it must not contain a complete-looking
  video file (≥100MB `.mkv`/`.mp4`/etc. — something can finish
  extracting and still sit under an `_UNPACK_` name if only the final
  import step got interrupted); and its size must have been reliably
  measurable at all (a network hiccup mid-scan previously could
  silently undercount a real folder as smaller than it is — now any
  read failure excludes it from this scan entirely rather than
  guessing zero).
- **Delete All Junk's confirm dialog now lists the actual item names**,
  not just a count — so there's a real chance to notice something
  that shouldn't be there before confirming, not just a number.

## 0.13.0

- **Empty junk is now deleted automatically.** A leftover
  `_UNPACK_`/`_FAILED_` folder or stray archive piece with 0 bytes in
  it — SABnzbd created it but never wrote any real data before giving
  up — is removed on every scan with no button press, since there's no
  content it could possibly destroy. Anything with real data in it
  still requires an explicit delete.
- Added a **Delete All Junk** bulk button (Cleanup tab) for clearing
  every remaining (non-empty) junk item from the last scan in one
  click — no per-group ambiguity check needed here, unlike bulk
  duplicate delete, since a junk entry is unambiguously junk by
  definition once it's on the list at all.
- Added `junk_min_age_hours` (default 1h): a folder or file only ever
  counts as junk once it hasn't been modified for this long. Without
  it, a folder SABnzbd is actively extracting into right now would
  look identical to one it abandoned — this is what stops an
  in-progress download from getting deleted mid-extraction, for both
  the new auto-delete and the existing manual delete paths.

## 0.12.0

- Added **failed-unpack / junk cleanup** to the media scan (Duplicates
  tab, renamed **Cleanup**): detects `_UNPACK_`/`_FAILED_` folders
  SABnzbd leaves behind after a failed or interrupted extraction (the
  usual cause of a bogus "UNPACK" entry showing up in Jellyfin), plus
  stray archive pieces (`.rar`/`.r00`-`.r99`/`.par2`) that never got
  extracted at all. Found in the same filesystem walk as the duplicate
  scan, at no extra scanning cost. Each item gets its own Delete button
  — a whole-folder delete for an unpack folder, a single-file delete
  for a stray archive piece — with the same "only ever a path from the
  last scan" safety rule as duplicate delete. After deleting, yArr also
  refreshes Jellyfin's library so the bogus entry disappears right away
  instead of waiting for Jellyfin's own scan — the first write this
  add-on ever makes to Jellyfin; everything else there stays read-only.

## 0.11.2

- **Fixed the bulk-delete count being permanently stuck at 0** with no
  error logged: the tracked-file match compared *full paths*, but
  Radarr/Sonarr (their own Docker container's mount) and yArr (Home
  Assistant's `/media` share) routinely see the identical physical
  file at two different absolute paths — a normal consequence of
  separate containers, not an edge case. Every group therefore always
  looked "unmatched," silently. Confirmed via a real install: the log
  showed successful scans with no compute error, yet the bulk-delete
  button stayed disabled on every one. Fixed by matching on filename
  instead of full path, for both the bulk-delete gate and the per-file
  delete's rename-the-survivor step (which had the exact same silent
  bug — it just never found a match and quietly did nothing).

## 0.11.1

- **Fixed a broken web UI**: 0.11.0's "Keep It" button HTML was built
  as a single-quoted JS string containing a nested single-quoted JS
  string (from the new `runAction(this,'api/keep-surprise',...)`
  call). Because `webui.py`'s page template is a plain (non-raw)
  Python string, the backslash meant to escape that inner quote for
  the browser got silently consumed by Python's own string parsing
  first, shipping the page with an unescaped quote that terminated the
  outer string early — a real JS syntax error that killed the entire
  `<script>` block, so nothing on the page worked at all (not just
  that button). Fixed by using a backtick template literal instead of
  nested single quotes. Added a CI check (esprima-based) that parses
  the shipped page's embedded JS on every push so this class of bug
  fails the build instead of shipping silently broken.

## 0.11.0

- **Every button now gives real feedback.** Root cause of "I pressed
  it and nothing happened": the status sensor only republished on its
  own fixed 60-second tick, so a button that worked instantly could
  look dead in the web UI for up to a minute. Every action handler
  (accept/deny, all four delete flows, scan now, bulk delete) now
  forces an immediate republish right after it finishes.
- On the client side, every action button shows "Working…" while its
  request is in flight, then a toast pops up with the actual outcome
  (pulled from the new Log entry the action just produced) instead of
  refreshing silently. A failed request shows an error toast instead
  of failing invisibly.
- If you clicked **Delete All Inferior Duplicates** and it looked
  disabled/inert: it only enables once a scan has computed a non-null
  "safe to bulk-delete" count, which requires Radarr (and Sonarr, if
  TV is enabled) to have been reachable *during that scan* — the
  0.10.1 Sonarr fix only takes effect starting with your next Scan Now
  or scheduled scan, not retroactively on an old one. The Duplicates
  tab now says so explicitly when the count is unknown.

## 0.10.1

- Fixed a real install error: Sonarr's `/episodefile` endpoint rejects
  an unscoped GET ("seriesId or episodeFileIds must be provided"),
  which made the "safe to bulk-delete" count fail on every scan once
  TV was enabled. Both `get_all_episode_file_paths` (bulk delete) and
  `find_series_id_by_file_path` (per-file rename) now fetch the series
  list first and query `/episodefile?seriesId=X` per series instead.

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
