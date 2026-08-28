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
