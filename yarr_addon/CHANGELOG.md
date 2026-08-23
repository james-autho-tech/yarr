# Changelog

## 0.1.0

- Initial release: TMDB-driven genre auto-add to Radarr, an automatic
  random "surprise film" rotation (tagged separately in Radarr), and a
  Jellyfin-webhook-triggered watch-and-delete loop for surprise films
  only, with a configurable grace period and a keep-it-instead toggle.
  Watch-history exclusion reads Jellyfin's own per-user played status
  directly (TMDB has no personal-account concept, so this replaced an
  earlier Trakt-based design that turned out to need a paid VIP tier
  for its recommendations API).
