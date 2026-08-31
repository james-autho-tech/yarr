# yArr

Automated movie/TV discovery, surprise rotation, and library trimming
across TMDB/Radarr/Sonarr/Jellyfin, with optional SABnzbd queue
monitoring — bundling its own AppDaemon runtime.

- **Genre auto-add**: periodically pulls TMDB picks filtered by your
  favourite genres + a minimum rating, excluding anything already
  watched (per Jellyfin's own watch history), already in your library,
  or already suggested before, and adds good matches to Radarr (movies)
  and, if Sonarr is configured, Sonarr (TV shows).
- **Learn your taste (optional)**: instead of a hand-typed genre list,
  yArr can derive a weighted genre profile blending what Jellyfin says
  you've actually watched (weighted by play count/favourites) with
  what's sitting in your full Radarr/Sonarr library at all — owning
  something counts for less than having watched it, but both signals
  feed the same ranking.
- **Surprise me**: on a random jittered cadence (roughly every 5–10
  days, configurable, separately for movies and TV), picks one more
  title the same way — plus manual "Surprise Me Now" buttons if you
  don't want to wait.
- **Accept/Deny**: a surprise pick is proposed in the web UI and never
  touches Radarr/Sonarr until you Accept it. Deny it instead and yArr
  tallies that pick's genres — deny a genre enough times and it's
  automatically excluded from future picks, no config editing needed.
- **Watch it, lose it**: once Jellyfin reports an accepted surprise
  film played past a completion threshold — or a surprise show's
  *last* episode finishes — it's deleted after a configurable grace
  period (with a notification and a "keep it instead" toggle), or
  delete it immediately yourself from the web UI any time. Never your
  regular library or the genre auto-adds, only titles yArr itself
  added and tagged as a surprise.
- **Library**: search TMDB for anything and add it with one click
  (same root folder/quality profile as genre auto-add), and browse/
  manage your *entire* existing Radarr/Sonarr library — not just what
  yArr itself suggested — with a filterable table. Deleting from the
  full library is off by default (`allow_library_delete: true` to
  enable it) since it can remove something you've had for years,
  unlike every other delete in yArr.
- **SABnzbd monitoring (optional)**: read-only queue status (speed,
  ETA, active downloads) as an HA sensor and a web UI card — yArr never
  queues, pauses, or cancels anything in SABnzbd itself.
- **Media cleanup (optional)**: scans your NAS (via HA's own `/media`
  share) for files sharing an identical size — a strong, cheap signal
  for duplicate video files — and lists candidate groups in the web
  UI's Cleanup tab. Delete one file at a time, or use **Delete All
  Inferior Duplicates** to clear every group in one click where
  exactly one file matches Radarr's/Sonarr's tracked copy (ambiguous
  groups are always left for manual review). The same scan also finds
  leftover SABnzbd extraction junk — an `_UNPACK_`/`_FAILED_` folder
  left behind by a failed unpack (the usual cause of a bogus "UNPACK"
  entry in Jellyfin), or a stray archive piece that never got
  extracted. Empty (0-byte) junk is cleared automatically since there's
  nothing it could destroy; anything with real data in it needs a
  Delete button (per-item, or **Delete All Junk** for everything at
  once), and refreshes Jellyfin's library afterward. Every delete
  cleans up any now-empty folder left behind and triggers a
  Radarr/Sonarr rescan.

TV/Sonarr, SABnzbd, and the media cleanup scan are all entirely opt-in —
leave their Configuration-tab fields / apps.yaml paths blank to run
movies-only with no monitoring or scanning.

## Install

Settings → Add-ons → Add-on Store → ⋮ → **Repositories** → add
`https://github.com/james-autho-tech/yarr` → find "yArr" → Install.

1. Start the add-on once so it writes its config templates, then edit
   `/addon_configs/yarr/apps.yaml` for genres, rating floor, cadence,
   root folders/quality profiles, etc. — see the comments in the
   shipped template.
2. In the add-on's **Configuration** tab, set the required fields:
   `radarr_url` + `radarr_api_key`, `jellyfin_url` + `jellyfin_api_key`,
   and a free `tmdb_api_key` (create one at
   https://www.themoviedb.org/settings/api — no OAuth, just an API key).
   Optionally also set `sonarr_url` + `sonarr_api_key` for TV, and/or
   `sabnzbd_url` + `sabnzbd_api_key` for queue monitoring.
3. Set up Jellyfin's Webhook plugin to notify yArr when you finish a
   surprise film or show — see [DOCS.md](DOCS.md) for the exact steps.
4. Watch the AppDaemon log for the startup banner, or check the web
   UI's status cards.
