# yArr — Documentation

## What it does

Three loops, all driven by `apps/yarr/apps.yaml` (behaviour) and the
add-on's Configuration tab (credentials):

1. **Genre discovery** (`tick_discovery`, every `discovery_interval_hours`)
   — pulls TMDB picks, filters by `genres` + `min_rating`, excludes
   anything already watched (per Jellyfin's own watch history) /
   already in Radarr / already suggested before, and adds up to
   `max_suggestions_per_run` matches to Radarr.
2. **Surprise rotation** (`tick_surprise_check`, hourly poll against a
   persisted random timestamp between `surprise_min_days` and
   `surprise_max_days` apart) — same filtering, but tags the pick in
   Radarr with `surprise_tag` and tracks it separately. The
   **"yArr: Surprise Me Now"** HA button (also in the web UI) triggers
   one immediately.
3. **Watch-and-delete** — once Jellyfin reports a *tagged surprise
   film* played past `completion_threshold_pct`, yArr schedules its
   deletion `delete_grace_period_hours` later and sends an HA
   notification. Flip **"yArr: Keep the pending surprise film"**
   (`input_boolean.yarr_keep_surprise`) on before the grace period
   elapses to keep it instead. This never touches your regular library
   or the genre auto-adds — only films yArr itself added and tagged.

## TMDB setup

1. Create a free account at themoviedb.org, then generate an API key
   (v3 auth) at https://www.themoviedb.org/settings/api.
2. Put it into this add-on's Configuration tab as `tmdb_api_key`.

No OAuth, no device-code flow — that's it. TMDB has no concept of a
personal watch history, which is why "already watched" exclusion comes
from Jellyfin instead (see below) rather than from TMDB itself.

## Jellyfin setup

Jellyfin does two jobs here:

**Watch-history exclusion** — `jellyfin_url`/`jellyfin_api_key` (both
required) let yArr read your account's own played-movie list, cached
and resynced every `watched_resync_hours`. On a single-user Jellyfin
instance, yArr just uses whichever account its API key's own user
lookup returns first; if you run multiple Jellyfin users, set
`jellyfin_username` in `apps.yaml` to pick the right one.

**Playback-stop webhook** — yArr never opens its own port for this;
Jellyfin posts to a plain Home Assistant webhook URL instead, which an
automation (installed automatically as `/config/packages/yarr.yaml`)
relays into an event yArr listens for.

1. In Jellyfin, install the **Webhook** plugin (Dashboard → Plugins →
   Catalog).
2. Add a new webhook, pointed at:
   `<your HA base URL>/api/webhook/yarr_playback_stop`
3. Under **Notification Type**, enable only **Playback Stop**.
4. Under **Item Type**, restrict to **Movies**.
5. Make sure the webhook's JSON template includes at least:
   `NotificationType`, `ItemType`, `Name`, `PlaybackPercentage`,
   `Provider_tmdb`, `Provider_imdb` — Jellyfin's default template
   usually already does. If your Jellyfin instance's template ever
   omits the provider IDs, yArr falls back to looking them up via the
   Jellyfin API directly by item id.

This assumes Jellyfin is on the same network as Home Assistant
(the automation sets `local_only: true`). If Jellyfin is external,
edit `/config/packages/yarr.yaml`'s trigger to `local_only: false` and
use your HA external URL instead — at your own risk, since that opens
the webhook to anything that can reach that URL.

### Testing the webhook manually

`curl` the webhook URL directly from a device on your network:

```bash
curl -X POST '<your HA base URL>/api/webhook/yarr_playback_stop' \
  -H 'Content-Type: application/json' \
  -d '{"NotificationType":"PlaybackStop","ItemType":"Movie","Name":"Test Film",
       "PlaybackPercentage":"95","Provider_tmdb":"<a tmdb id currently tracked as a surprise>"}'
```

## Troubleshooting

- **Web UI shows "Not configured"** — one of `radarr_url`,
  `radarr_api_key`, `tmdb_api_key`, `jellyfin_url`, `jellyfin_api_key`
  is missing from the Configuration tab. `sensor.yarr_status`'s
  `missing_secrets` attribute lists exactly which ones.
- **apps.yaml edits don't seem to apply** — check the AppDaemon log for
  a parse error; a broken file (e.g. a `!secret` tag — not supported
  here, see below) gets backed up to `apps.yaml.broken` and replaced
  with the template automatically.
- **Never put API keys in apps.yaml** — AppDaemon's own app-config
  loader has no `secrets.yaml` support, unlike HA core. Use the
  Configuration tab for all five credential fields.
- **`dry_run: true`** in `apps.yaml` computes and logs picks without
  ever calling Radarr — useful for checking your genre/rating settings
  before trusting it for real.
