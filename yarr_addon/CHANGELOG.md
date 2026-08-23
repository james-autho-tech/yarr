# Changelog

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
