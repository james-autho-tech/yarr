# yArr

Automated movie discovery, surprise-film rotation and library trimming
across Trakt/Radarr/Jellyfin, bundling its own AppDaemon runtime.

- **Genre auto-add**: periodically pulls Trakt recommendations filtered
  by your favourite genres + a minimum rating, excluding anything
  already watched, already in Radarr, or already suggested before, and
  adds good matches to Radarr.
- **Surprise me**: on a random jittered cadence (roughly every 5–10
  days, configurable), picks one more film the same way, tags it in
  Radarr so it's identifiable, and adds it — plus a manual "Surprise Me
  Now" button if you don't want to wait.
- **Watch it, lose it**: once Jellyfin reports a surprise film played
  past a completion threshold, it's deleted from Radarr after a
  configurable grace period (with a notification and a "keep it
  instead" toggle) — never your regular library or the genre auto-adds,
  only films yArr itself tagged as a surprise.

v1 is a Supervisor add-on only — no separate HACS install path.

## Install

Settings → Add-ons → Add-on Store → ⋮ → **Repositories** → add this
repository's URL → find "yArr" → Install.

1. Start the add-on once so it writes its config templates, then edit
   `/addon_configs/yarr/apps.yaml` for genres, rating floor, cadence,
   Radarr root folder/quality profile, etc. — see the comments in the
   shipped template.
2. In the add-on's **Configuration** tab, set `radarr_url` +
   `radarr_api_key` and `trakt_client_id` + `trakt_client_secret`
   (create a Trakt API app at https://trakt.tv/oauth/applications —
   any redirect URI works, the device-code flow below doesn't use it).
   `jellyfin_url`/`jellyfin_api_key` are optional — only needed as a
   fallback if Jellyfin's webhook payload ever omits provider IDs.
3. Open the add-on's web UI (sidebar panel) and click **Connect
   Trakt** — it shows a code and a URL; approve it there.
4. Set up Jellyfin's Webhook plugin to notify yArr when you finish a
   surprise film — see [DOCS.md](DOCS.md) for the exact steps.
5. Watch the AppDaemon log for the startup banner, or check the web
   UI's status card.
