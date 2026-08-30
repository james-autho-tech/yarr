# yArr — Documentation

## What it does

All driven by `apps/yarr/apps.yaml` (behaviour) and the add-on's
Configuration tab (credentials):

1. **Genre discovery — movies** (`tick_discovery`, every
   `discovery_interval_hours`) — pulls TMDB picks, filters by `genres`
   + `min_rating`, excludes anything already watched (per Jellyfin's
   own watch history) / already in Radarr / already suggested before,
   and adds up to `max_suggestions_per_run` matches to Radarr.
2. **Genre discovery — TV** (`tick_tv_discovery`) — same idea, using
   `tv_genres`/`tv_min_rating`/`tv_max_suggestions_per_run` against
   Sonarr. Entirely opt-in: only runs once `sonarr_url`/`sonarr_api_key`
   are set in the Configuration tab.
3. **Surprise rotation** (`tick_surprise_check`/`tick_tv_surprise_check`,
   hourly polls against persisted random timestamps between
   `surprise_min_days`/`surprise_max_days` — separately for movies and
   TV) — same filtering, but tags the pick (`surprise_tag`/
   `tv_surprise_tag`) and tracks it separately. The web UI's **"Surprise
   Me Now"** / **"Surprise Me Now (TV)"** buttons trigger one
   immediately — these fire a plain HA event (`yarr_surprise_me_now`/
   `yarr_surprise_tv_now`) rather than pressing a real `input_button`
   entity, so there's nothing to set up in HA for them to work.
4. **Accept/Deny approval** (`surprise_requires_approval`, default
   `true`) — a surprise pick is proposed in the web UI (title, year,
   rating, genres) and never touches Radarr/Sonarr until you hit
   **Accept**. Only one proposal is outstanding at a time — a new one
   isn't picked until the current one is resolved. **Deny** tallies
   that pick's genres; once a genre has been denied
   `surprise_feedback_deny_threshold` times (default 2), it's
   automatically excluded from future picks on top of
   `excluded_genres` — this is genuinely learned from your decisions,
   not just logged. Set `surprise_requires_approval: false` to go back
   to auto-adding surprises outright with no gate.
5. **Watch-and-delete** — once Jellyfin reports a *tagged surprise
   film* played past `completion_threshold_pct`, or a *tagged surprise
   show's last episode* crosses it (mid-series episodes don't count —
   yArr checks Jellyfin's own "fully watched" status for the series
   before scheduling anything), yArr schedules deletion
   `delete_grace_period_hours` later and sends an HA notification and
   shows a **Keep It** button in the web UI. `input_boolean.yarr_keep_surprise`
   / `yarr_keep_surprise_tv` are AppDaemon-owned virtual states (not
   real helpers — see `ha_support.yaml` if you want them as real
   dashboard-toggleable ones instead), flipped on by that button before
   the grace period elapses to keep the title instead of deleting it.
   Every tracked surprise also has its own **Delete** button in the web
   UI for an immediate, unconditional removal regardless of watch
   status — for "this was rubbish, get rid of it now." This never
   touches your regular library or the genre auto-adds — only titles
   yArr itself added and tagged.

## TMDB setup

1. Create a free account at themoviedb.org, then generate an API key
   (v3 auth) at https://www.themoviedb.org/settings/api.
2. Put it into this add-on's Configuration tab as `tmdb_api_key`.

No OAuth, no device-code flow — that's it. TMDB has no concept of a
personal watch history, which is why "already watched" exclusion comes
from Jellyfin instead (see below) rather than from TMDB itself.

## TV/Sonarr setup (optional)

Set `sonarr_url`/`sonarr_api_key` in the Configuration tab — that's the
only switch. Once both are set, `tv_enabled` flips on and the TV
discovery/surprise ticks and the "Surprise Me Now (TV)" button start
working; leave either blank to stay movies-only.

Sonarr identifies shows by TheTVDB's id, not TMDB's, so yArr resolves
each TMDB candidate's `tvdb_id` via TMDB's own external-ids lookup
before it can be added — a result TMDB can't resolve a TVDB id for is
silently skipped, since Sonarr couldn't add it anyway.

`sonarr_language_profile_id` in `apps.yaml` is optional — only set it
if you're on Sonarr v3 and it rejects adds without one; Sonarr v4
dropped Language Profiles entirely.

## Learning your taste instead of a genre list (optional)

Set `learn_genres_from_library: true` in `apps.yaml` to have yArr
derive `genres`/`tv_genres` from your own Jellyfin library instead of
the hand-typed lists — every watched/favourited item's genres are
scored (base weight 1, +0.1 per replay, +3 if favourited) and the top
`taste_top_n_genres` (default 5) become the effective genre filter,
refreshed on the same `watched_resync_hours` cadence as the watched-id
caches. If your library hasn't yielded anything yet (e.g. brand new),
yArr falls back to the configured `genres`/`tv_genres` lists rather
than running with no genre filter at all.

## Jellyfin setup

Jellyfin does several jobs here:

**Watch-history exclusion** — `jellyfin_url`/`jellyfin_api_key` (both
required) let yArr read your account's own played-movie/show list,
cached and resynced every `watched_resync_hours`. On a single-user
Jellyfin instance, yArr just uses whichever account its API key's own
user lookup returns first; if you run multiple Jellyfin users, set
`jellyfin_username` in `apps.yaml` to pick the right one.

**Playback-stop webhook** — yArr never opens its own port for this;
Jellyfin posts to a plain Home Assistant webhook URL instead, which an
automation (created automatically via HA's Config API — see
[ha_support.yaml](rootfs/opt/appdaemon/apps/yarr/ha_support.yaml) for
the equivalent YAML, kept only as documentation/manual fallback)
relays into an event yArr listens for. One webhook handles both movies
and TV episodes.

1. In Jellyfin, install the **Webhook** plugin (Dashboard → Plugins →
   Catalog).
2. Add a new webhook, pointed at:
   `<your HA base URL>/api/webhook/yarr_playback_stop`
3. Under **Notification Type**, enable **Playback Stop**.
4. Under **Item Type**, select **Movies and Episodes** (or leave
   unrestricted) — both flow through the same webhook, dispatched by
   `ItemType` on yArr's side.
5. Make sure the webhook's JSON template includes at least:
   `NotificationType`, `ItemType`, `Name`, `PlaybackPercentage`,
   `Provider_tmdb`, `Provider_imdb` (for movies), and `SeriesId`,
   `SeriesName` (for episodes) — Jellyfin's default template usually
   already includes all of these. If a movie payload ever omits the
   provider IDs, yArr falls back to looking them up via the Jellyfin
   API directly by item id.

This assumes Jellyfin is on the same network as Home Assistant (the
automation sets `local_only: true`). If Jellyfin is external, edit the
`yarr_playback_stop_relay` automation in Settings → Automations to set
`local_only: false` and use your HA external URL instead — at your own
risk, since that opens the webhook to anything that can reach that
URL. (Note: yArr recreates this automation on every add-on start, so a
manual edit like this gets overwritten on update — if you need this
permanently, do it in `ha_support.yaml` and switch to the manual
package-file install instead.)

### Testing the webhook manually

`curl` the webhook URL directly from a device on your network:

```bash
# Movie
curl -X POST '<your HA base URL>/api/webhook/yarr_playback_stop' \
  -H 'Content-Type: application/json' \
  -d '{"NotificationType":"PlaybackStop","ItemType":"Movie","Name":"Test Film",
       "PlaybackPercentage":"95","Provider_tmdb":"<a tmdb id currently tracked as a surprise>"}'

# Episode (series-level "fully watched" is still checked live via the
# Jellyfin API, so this alone won't trigger a delete unless every
# other episode in the series is also marked played in Jellyfin)
curl -X POST '<your HA base URL>/api/webhook/yarr_playback_stop' \
  -H 'Content-Type: application/json' \
  -d '{"NotificationType":"PlaybackStop","ItemType":"Episode","SeriesName":"Test Show",
       "PlaybackPercentage":"97","SeriesId":"<the Jellyfin item id of a tracked surprise series>"}'
```

## SABnzbd monitoring (optional)

Set `sabnzbd_url`/`sabnzbd_api_key` in the Configuration tab. Once both
are set, `sensor.yarr_sabnzbd_status` publishes queue status (speed,
size left, ETA, up to 10 in-progress items) every 60 seconds, and the
web UI gets a SABnzbd card. Read-only — yArr never pauses, cancels, or
reorders anything in the queue.

## Media cleanup: duplicates + failed unpacks (optional)

Finds candidate duplicate files directly on your NAS by exact file
size — a strong signal on its own for video files above a size floor
(default 50MB, well past trailers/samples), and far cheaper than
hashing whole files across a large library. Deleting is manual and
per-file: yArr never auto-deletes anything it finds — it lists
candidate groups in the web UI's Duplicates tab, and each file gets
its own **Delete** button for you to act on individually.

This needs two things, in order:

1. **HA's own `/media` share has to actually point at your NAS** —
   Settings → System → Storage → Add Network Storage, using the same
   CIFS/NFS share your Radarr/Sonarr/Jellyfin containers already point
   at, with Usage set to **Media**. Supervisor add-ons (yArr included)
   can only mount HA's own predefined shares, not arbitrary Docker bind
   mounts — this step is what makes that share exist in the first
   place. yArr's `config.yaml` declares a writable `media` map entry
   (write access is needed for the per-file Delete button); it just has
   nothing to see until this step is done.
2. Set `media_scan_paths` in `apps.yaml` to the actual subpaths under
   `/media` your library lives at once that share exists (e.g.
   `/media/movies`, `/media/tv`) — check what's actually there via
   Developer Tools or HA's own Media browser if unsure. Empty (the
   default) means the whole feature stays off.

Runs on `media_scan_interval_hours` (default 24h), or trigger one
immediately with the **Scan Now** button in the web UI's Duplicates
tab. `media_scan_min_size_mb` (default 50) filters out small files
that would otherwise produce noisy false-feeling matches.

**Deleting a file**: the web UI's per-file Delete button (with a
confirm prompt) removes exactly that file off the NAS mount — yArr
only ever acts on a path that was actually part of the last scan's
results, never an arbitrary path, so it can't be tricked into deleting
something it hasn't itself just reported. After a successful delete:

- Any now-empty parent folder left behind gets removed too, walking
  upward until it hits a folder with content or one of your configured
  `media_scan_paths` roots — it never deletes the root itself, and
  never walks outside it.
- yArr tells Radarr and (if enabled) Sonarr to rescan their libraries,
  so neither one's database goes stale after a delete that bypassed
  their own delete flow entirely.
- The surviving copy (whichever duplicate wasn't deleted) gets a
  Radarr `RenameMovie` / Sonarr `RenameSeries` command fired for it, in
  case it doesn't match your configured naming format — it's arbitrary
  which of the duplicates Radarr/Sonarr originally considered "the"
  file. Best-effort: a failure here is logged but never undoes the
  delete itself.

**Bulk delete**: the Duplicates tab also has a **Delete All Inferior
Duplicates** button. Each scan cross-checks every group against
Radarr's/Sonarr's actually-tracked files and computes how many are
safe to remove — shown as "Safe to bulk-delete" next to the group
count. A group only counts as safe when *exactly one* file in it
matches a tracked file; if zero or more than one match, that group is
left alone for manual review rather than guessed at. One click, one
confirm (showing the count), then every safe file across every group
is deleted in one pass, followed by a single Radarr/Sonarr rescan —
same empty-folder cleanup as the per-file delete, but no per-file
rename pass (the survivor in a bulk-safe group is by definition already
the file Radarr/Sonarr has tracked, so it should already match your
naming format).

The tracked-file match is by **filename, not full path** — Radarr/
Sonarr almost always see your library through a different mount than
yArr does (their own Docker container's own volume mount vs. Home
Assistant's `/media` share pointed at the same NAS share), so the two
sides' absolute paths for the identical physical file routinely don't
match at all, only the filename does. Comparing full paths here would
silently leave every group "unmatched" with no error — exactly what
happened before this was fixed, with the bulk-delete count stuck at 0
on every scan despite the scan itself succeeding.

**Failed unpacks / junk** (same tab, same scan pass): SABnzbd renames
a download's working folder to `_UNPACK_<name>` while extracting it,
or `_FAILED_<name>` if extraction errors out, and normally cleans up
after a successful unpack. A failed or interrupted unpack can leave
that folder sitting there indefinitely — and if it's inside a path
Jellyfin scans, Jellyfin shows it as a bogus library entry (this is
the usual cause of a stray "UNPACK" item showing up in Jellyfin). The
same scan pass also looks for stray raw archive pieces (`.rar`,
`.r00`-`.r99`, `.par2`) that never got extracted into anything at all.
Both are reported under **Failed Unpacks / Junk** in the same tab.
Deleting a folder here removes it and everything inside it
(`shutil.rmtree`, not a single file). After any delete, yArr also asks
Jellyfin to refresh its library (`POST /Library/Refresh`) so the bogus
entry disappears right away instead of waiting for Jellyfin's own next
scheduled scan — the only write this add-on ever makes to Jellyfin;
everything else is read-only.

**Age safety net**: a folder or file only ever counts as junk once it
hasn't been modified for `junk_min_age_hours` (default 1h). Without
this, a folder SABnzbd is actively extracting into *right now* would
look identical to one it abandoned — deleting it mid-extraction would
actually destroy a download in progress. Anything too recent is simply
left alone until the next scan.

**Auto-delete vs. manual delete**: an empty (0-byte) junk item —
SABnzbd created the folder or file but never wrote any real data into
it before giving up — is deleted automatically on every scan, no
button required, because there is no content it could possibly
destroy. Anything with real bytes in it always needs an explicit
delete: either its own per-item Delete button, or **Delete All Junk**
(one click, one confirm showing the count) to clear every remaining
item from the last scan in a single pass — no "only one tracked copy"
ambiguity check like bulk duplicate delete, since a junk entry is
unambiguously junk by definition once it's on this list at all.

## Troubleshooting

- **"Surprise Me Now" (or the webhook, or the keep-it toggle) does
  nothing** — these no longer depend on real `input_boolean`/
  `input_button` helpers existing in HA at all (an earlier version did,
  and a real install showed HA's Config REST API 404s on both — modern
  HA moved simple helpers to a config-entry flow that endpoint doesn't
  serve). Buttons fire a plain HA event directly and the keep-it
  toggles are AppDaemon-owned virtual states created on first start —
  both work with zero HA-side setup. If it's still not working, check
  the AppDaemon log for `Could not sync automation.yarr_playback_stop_relay`
  (only the webhook-relay automation still goes through the Config
  API) — that usually means HA core wasn't fully up yet when the
  add-on started; restart the add-on once HA itself is confirmed
  running.
- **A tracked surprise stays listed after you deleted it directly in
  Radarr/Sonarr** (not via yArr's own Delete button) — yArr only finds
  out through its own delete flow or through `tick_reconcile_surprises`,
  which cross-checks the current library every 30 minutes and untracks
  anything no longer actually present. It'll clear itself within that
  window; there's nothing to configure. This is also why a delete can
  now fail with something like `Expected query to return 1 rows but
  returned 0` (Sonarr) or a 404 (Radarr) and still get untracked on
  yArr's side — the id is already gone, so the delete call itself
  fails, but there's no reason to keep tracking something that isn't
  there.
- **"No surprise candidate matched your filters this time" happens a
  lot** — TMDB returns 20 results per page, and page 1 alone gets
  exhausted fast once genre/rating/exclusion/already-suggested filters
  are all applied. Raise `tmdb_pages` in `apps.yaml` (default 3) for a
  bigger pool to filter from.
- **Web UI shows "Not configured"** — one of `radarr_url`,
  `radarr_api_key`, `tmdb_api_key`, `jellyfin_url`, `jellyfin_api_key`
  is missing from the Configuration tab. `sensor.yarr_status`'s
  `missing_secrets` attribute lists exactly which ones. (`sonarr_*`
  and `sabnzbd_*` are never "missing" — they're optional features that
  silently stay off until both halves of a pair are set.)
- **apps.yaml edits don't seem to apply** — check the AppDaemon log for
  a parse error; a broken file (e.g. a `!secret` tag — not supported
  here, see below) gets backed up to `apps.yaml.broken` and replaced
  with the template automatically.
- **Never put API keys in apps.yaml** — AppDaemon's own app-config
  loader has no `secrets.yaml` support, unlike HA core. Use the
  Configuration tab for every credential field.
- **`dry_run: true`** in `apps.yaml` computes and logs picks without
  ever calling Radarr/Sonarr — useful for checking your genre/rating
  settings are producing sensible picks before trusting it for real.
