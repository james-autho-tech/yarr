#!/usr/bin/env python3
"""Minimal Ingress web UI for yArr — stdlib http.server only, reads/
writes HA state exclusively (this process and the AppDaemon engine
never talk to each other directly; HA is the integration point)."""

import http.server
import json
import os
import socketserver
import urllib.error
import urllib.request

SUPERVISOR_TOKEN = os.environ["SUPERVISOR_TOKEN"]
PORT = 8100


def ha_get_all_states():
    req = urllib.request.Request(
        "http://supervisor/core/api/states",
        headers={"Authorization": f"Bearer {SUPERVISOR_TOKEN}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            states = json.load(resp)
        return {s["entity_id"]: s for s in states}
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
        return {}


def ha_fire_event(event_type, data=None):
    """POST /api/events/<type> — a bare custom event, no entity/service
    involved at all. Used for the surprise-me buttons instead of
    pressing an input_button entity: a real install showed HA's Config
    REST API 404s on input_boolean/input_button creation (modern HA
    moved those to a config-entry flow that endpoint doesn't serve),
    so yarr.py listens for these events directly instead."""
    payload = json.dumps(data or {}).encode()
    req = urllib.request.Request(
        f"http://supervisor/core/api/events/{event_type}",
        data=payload, method="POST",
        headers={"Authorization": f"Bearer {SUPERVISOR_TOKEN}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status


def ha_set_state(entity_id, state, attributes=None):
    """POST /api/states/<id> — HA's raw state-set endpoint, works for
    any entity_id with no backing integration required. Used for the
    keep-surprise toggles, which yarr.py owns as plain AppDaemon
    virtual states rather than real input_boolean helpers (same reason
    as ha_fire_event above)."""
    body = {"state": state}
    if attributes:
        body["attributes"] = attributes
    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        f"http://supervisor/core/api/states/{entity_id}",
        data=payload, method="POST",
        headers={"Authorization": f"Bearer {SUPERVISOR_TOKEN}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status


def is_on(state_obj):
    return bool(state_obj) and state_obj.get("state") == "on"


def build_status():
    states = ha_get_all_states()
    status = states.get("sensor.yarr_status") or {}
    attrs = status.get("attributes", {})
    sab = states.get("sensor.yarr_sabnzbd_status") or {}
    sab_attrs = sab.get("attributes", {})
    return {
        "state": status.get("state", "unknown"),
        "missing_secrets": attrs.get("missing_secrets", []),
        "enabled": is_on(states.get("input_boolean.yarr_enable")),

        "learn_genres_from_library": attrs.get("learn_genres_from_library", False),
        "excluded_genres": attrs.get("excluded_genres", []),
        "denied_genres": attrs.get("denied_genres", []),
        "effective_genres": attrs.get("effective_genres", []),
        "learned_genres": attrs.get("learned_genres", []),

        "suggested_count": attrs.get("suggested_count", 0),
        "surprise_count": attrs.get("surprise_count", 0),
        "next_surprise_at": attrs.get("next_surprise_at"),
        "keep_surprise": is_on(states.get("input_boolean.yarr_keep_surprise")),
        "recent_suggested": attrs.get("recent_suggested", []),
        "surprises": attrs.get("surprises", []),
        "surprise_requires_approval": attrs.get("surprise_requires_approval", True),
        "pending_surprise": attrs.get("pending_surprise"),

        "tv_enabled": attrs.get("tv_enabled", False),
        "suggested_shows_count": attrs.get("suggested_shows_count", 0),
        "surprise_shows_count": attrs.get("surprise_shows_count", 0),
        "next_tv_surprise_at": attrs.get("next_tv_surprise_at"),
        "keep_surprise_tv": is_on(states.get("input_boolean.yarr_keep_surprise_tv")),
        "effective_tv_genres": attrs.get("effective_tv_genres", []),
        "learned_tv_genres": attrs.get("learned_tv_genres", []),
        "recent_suggested_shows": attrs.get("recent_suggested_shows", []),
        "surprise_shows": attrs.get("surprise_shows", []),
        "pending_tv_surprise": attrs.get("pending_tv_surprise"),

        "sabnzbd_enabled": attrs.get("sabnzbd_enabled", False),
        "sabnzbd_status": sab.get("state", "unknown"),
        "sabnzbd_speed_kbps": sab_attrs.get("speed_kbps", 0),
        "sabnzbd_size_left": sab_attrs.get("size_left", ""),
        "sabnzbd_eta": sab_attrs.get("eta", ""),
        "sabnzbd_queue_count": sab_attrs.get("queue_count", 0),
        "sabnzbd_paused": sab_attrs.get("paused", False),
        "sabnzbd_items": sab_attrs.get("items", []),

        "media_scan_enabled": attrs.get("media_scan_enabled", False),
        "duplicate_groups": attrs.get("duplicate_groups", []),
        "duplicate_group_count": attrs.get("duplicate_group_count", 0),
        "duplicate_wasted_bytes": attrs.get("duplicate_wasted_bytes", 0),
        "duplicate_scan_at": attrs.get("duplicate_scan_at"),
        "duplicate_deletable_count": attrs.get("duplicate_deletable_count"),
        "duplicate_deletable_bytes": attrs.get("duplicate_deletable_bytes"),
        "junk_entries": attrs.get("junk_entries", []),
        "junk_count": attrs.get("junk_count", 0),
        "junk_bytes": attrs.get("junk_bytes", 0),
        "junk_scan_at": attrs.get("junk_scan_at"),

        "library_movies": attrs.get("library_movies", []),
        "library_movie_count": attrs.get("library_movie_count", 0),
        "library_shows": attrs.get("library_shows", []),
        "library_show_count": attrs.get("library_show_count", 0),
        "library_synced_at": attrs.get("library_synced_at"),
        "last_search_query": attrs.get("last_search_query"),
        "last_search_media_type": attrs.get("last_search_media_type"),
        "last_search_results": attrs.get("last_search_results", []),
        "last_search_at": attrs.get("last_search_at"),
        "allow_library_delete": attrs.get("allow_library_delete", False),

        "log": attrs.get("log", []),
    }


PAGE = """<!doctype html><html><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>yArr</title>
<style>
:root{
  --bg:#0a0a0b; --panel:#151517; --edge:#28282c;
  --ink:#ffffff; --sub:#9c9ca3; --faint:#67676e;
  --accent:#ff5a1f; --accent-ink:#0a0a0b;
  --ok:#22c55e; --warn:#ff5a1f; --err:#ef4444;
  --mono: ui-monospace, SFMono-Regular, "Cascadia Mono", Consolas, monospace;
  --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 var(--sans);
     -webkit-font-smoothing:antialiased}
a{color:var(--accent)}
code{font-family:var(--mono);background:var(--panel);padding:1px 6px;border-radius:3px;font-size:.85em}

header{padding:28px 24px 22px;border-bottom:2px solid var(--ink)}
.wordmark{font-size:34px;font-weight:900;letter-spacing:-.02em;line-height:1}
.wordmark .hi{color:var(--accent)}
.tagline{color:var(--sub);font-size:13px;margin-top:6px;font-weight:500}

main{max-width:1600px;margin:0 auto;padding:26px 20px 60px}
/* Text/table-based tabs stay at the original reading width — only the
   Library tab's poster grid benefits from using the full wide main,
   which is otherwise wasted space on anything wider than a phone. */
.tab-page:not([data-tab="library"]){max-width:820px;margin:0 auto}

.banner{background:var(--err);color:#1a0605;border-radius:6px;padding:14px 18px;
        margin-bottom:24px;font-size:14px;font-weight:600}
.banner code{background:rgba(0,0,0,.2);color:#1a0605}

section{margin-bottom:36px}
.section-head{display:flex;align-items:baseline;justify-content:space-between;
              margin-bottom:16px;padding-bottom:10px;border-bottom:2px solid var(--edge)}
.section-title{font-size:22px;font-weight:800;color:var(--ink);letter-spacing:-.01em}
.section-note{color:var(--sub);font-size:12px;font-weight:700;text-transform:uppercase;
              letter-spacing:.06em}

.stat-row{display:flex;flex-wrap:wrap;gap:2px;margin-bottom:18px;background:var(--edge);
          border-radius:8px;overflow:hidden}
.stat{flex:1 1 140px;background:var(--panel);padding:14px 16px}
.stat .lbl{color:var(--sub);font-size:11px;text-transform:uppercase;letter-spacing:.07em;
           font-weight:700}
.stat .val{font-family:var(--mono);font-size:26px;font-weight:700;margin-top:3px;color:var(--ink)}
.stat .val.small{font-size:14px;font-weight:600}

.chips{display:flex;flex-wrap:wrap;gap:7px;margin:10px 0 4px}
.chip{font-size:12px;font-weight:700;padding:4px 12px;border-radius:4px;
      color:var(--ink);background:var(--panel);border:1px solid var(--edge)}
.chip.on{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}
.chip.off{background:transparent;color:var(--err);border-color:var(--err);
          text-decoration:line-through}
.mode-line{font-size:13px;color:var(--sub);margin-top:4px;font-weight:600}

button{background:var(--accent);color:var(--accent-ink);border:none;border-radius:6px;
       padding:12px 22px;font-weight:800;font-size:14px;cursor:pointer;font-family:var(--sans);
       text-transform:uppercase;letter-spacing:.03em}
button:hover{filter:brightness(1.1)}
button.ghost{background:transparent;color:var(--ink);border:2px solid var(--ink)}
button.ghost:hover{background:var(--ink);color:var(--bg)}

input.text-input{background:var(--panel);color:var(--ink);border:2px solid var(--edge);
      border-radius:6px;padding:11px 14px;font-size:14px;font-family:var(--sans);
      min-width:220px}
input.text-input:focus{outline:none;border-color:var(--accent)}
.search-row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:16px}
.pill-toggle{display:flex;border:2px solid var(--edge);border-radius:6px;overflow:hidden}
.pill-toggle button{background:transparent;color:var(--sub);border:none;border-radius:0;
      padding:11px 16px}
.pill-toggle button.active{background:var(--accent);color:var(--accent-ink)}
.badge{font-size:11px;padding:3px 10px;border-radius:4px;font-weight:800;letter-spacing:.02em;
      text-transform:uppercase;background:var(--ok);color:#06210e}

.poster-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));
      gap:14px;margin:14px 0}
.poster-card{background:var(--panel);border:1px solid var(--edge);border-radius:8px;
      overflow:hidden;display:flex;flex-direction:column}
.poster-card .poster-img{width:100%;aspect-ratio:2/3;object-fit:cover;
      background:var(--edge);display:block}
.poster-placeholder{width:100%;aspect-ratio:2/3;background:var(--edge);
      display:flex;align-items:center;justify-content:center;color:var(--faint);
      font-size:12px;font-weight:700;text-align:center;padding:10px}
.poster-body{padding:10px 10px 12px;display:flex;flex-direction:column;gap:6px;flex:1}
.poster-title{font-weight:700;font-size:13px;line-height:1.3;color:var(--ink)}
.poster-meta{font-size:11px;color:var(--faint);font-family:var(--mono)}
.poster-actions{margin-top:auto;padding-top:4px}
.poster-actions button{width:100%;padding:9px 8px;font-size:11px}
.poster-clickable{cursor:pointer;display:flex;flex-direction:column;flex:1}
.poster-clickable:hover .poster-title{color:var(--accent)}

.detail-modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);
      z-index:100;align-items:flex-start;justify-content:center;padding:40px 20px;
      overflow-y:auto}
.detail-modal.show{display:flex}
.detail-card{background:var(--panel);border:1px solid var(--edge);border-radius:10px;
      max-width:640px;width:100%;position:relative;padding:26px}
.detail-close{position:absolute;top:14px;right:14px;background:transparent;color:var(--sub);
      border:none;font-size:22px;line-height:1;padding:6px 10px;cursor:pointer;
      font-weight:400;text-transform:none}
.detail-close:hover{color:var(--ink);filter:none}
.detail-body{display:flex;gap:22px;flex-wrap:wrap}
.detail-poster{flex:0 0 180px;width:180px}
.detail-poster img,.detail-poster .poster-placeholder{width:100%;aspect-ratio:2/3;
      border-radius:6px}
.detail-info{flex:1 1 300px;min-width:220px}
.detail-title{font-size:22px;font-weight:800;color:var(--ink);margin-bottom:4px}
.detail-overview{color:var(--sub);font-size:14px;line-height:1.6;margin-top:14px}

table{width:100%;border-collapse:collapse;font-size:14px}
table.list td, table.list th{padding:10px 6px;text-align:left;border-bottom:1px solid var(--edge)}
table.list th{color:var(--sub);font-size:11px;text-transform:uppercase;letter-spacing:.06em;
              font-weight:700}
table.list tr:last-child td{border-bottom:none}
.title-cell{color:var(--ink);font-weight:600}
.year{color:var(--faint);font-family:var(--mono);font-size:12.5px}
.empty-row{color:var(--faint);padding:14px 6px;font-size:14px}

.pill{font-size:11px;padding:3px 10px;border-radius:4px;font-weight:800;letter-spacing:.02em;
      text-transform:uppercase}
.pill.pending_watch{background:var(--panel);color:var(--sub);border:1px solid var(--edge)}
.pill.watched{background:var(--ok);color:#06210e}
.pill.deleting_soon{background:var(--err);color:#2a0705}
.pill.added{background:var(--ok);color:#06210e}
.pill.rejected_low_rating,.pill.rejected_in_radarr,.pill.rejected_watched{
  background:var(--panel);color:var(--faint);border:1px solid var(--edge)}
.countdown{color:var(--faint);font-size:12px;font-family:var(--mono);font-weight:600}

.keep-note{margin-top:12px;font-size:13px;color:var(--accent);font-weight:700}

.proposal{background:var(--panel);border:2px solid var(--accent);border-radius:8px;
          padding:16px 18px;margin-bottom:18px}
.proposal .ptitle{font-size:18px;font-weight:800}
.proposal .pmeta{color:var(--sub);font-size:13px;margin-top:2px}
.proposal .pactions{display:flex;gap:10px;margin-top:14px}
button.deny{background:transparent;color:var(--err);border:2px solid var(--err);
            border-radius:6px;padding:12px 22px;font-weight:800;font-size:14px;cursor:pointer;
            font-family:var(--sans);text-transform:uppercase;letter-spacing:.03em}
button.deny:hover{background:var(--err);color:#1a0605}
button.small-delete{background:transparent;color:var(--faint);border:1px solid var(--edge);
                     border-radius:4px;padding:4px 10px;font-size:11px;font-weight:700;
                     text-transform:uppercase;letter-spacing:.03em;cursor:pointer;
                     font-family:var(--sans)}
button.small-delete:hover{color:var(--err);border-color:var(--err)}

.log-line{display:flex;gap:12px;padding:8px 4px;border-bottom:1px solid var(--edge);font-size:13px}
.log-line:last-child{border-bottom:none}
.log-ts{color:var(--faint);font-family:var(--mono);font-size:11.5px;white-space:nowrap;
        padding-top:1px}
.log-msg{color:var(--ink)}
.log-line.error .log-msg{color:var(--err)}
.log-line.warn .log-msg{color:var(--warn)}

nav.tabs{display:flex;gap:4px;padding:0 24px;border-bottom:2px solid var(--ink);
         overflow-x:auto}
.tab-btn{background:none;border:none;color:var(--sub);font-family:var(--sans);
         font-weight:800;font-size:13px;text-transform:uppercase;letter-spacing:.04em;
         padding:14px 16px;cursor:pointer;border-bottom:3px solid transparent;
         margin-bottom:-2px;white-space:nowrap}
.tab-btn:hover{color:var(--ink)}
.tab-btn.active{color:var(--accent);border-bottom-color:var(--accent)}
.tab-page{display:none}
.tab-page.active{display:block}

button:disabled{opacity:.55;cursor:default;filter:none}
button.ghost:disabled:hover{background:transparent;color:var(--ink)}
button.small-delete:disabled:hover{color:var(--faint);border-color:var(--edge)}

.toast{position:fixed;left:50%;bottom:26px;transform:translate(-50%,16px);
       background:var(--panel);color:var(--ink);border:2px solid var(--edge);
       border-radius:8px;padding:12px 20px;font-size:13px;font-weight:700;
       max-width:min(560px,90vw);box-shadow:0 8px 24px rgba(0,0,0,.4);
       opacity:0;pointer-events:none;transition:opacity .15s,transform .15s;z-index:50}
.toast.show{opacity:1;transform:translate(-50%,0)}
.toast.info{border-color:var(--accent)}
.toast.warn{border-color:var(--warn);color:var(--warn)}
.toast.error{border-color:var(--err);color:var(--err)}
</style></head><body>
<header>
  <div class="wordmark">y<span class="hi">Arr</span></div>
  <div class="tagline">Auto-stocks and auto-thins your Radarr/Sonarr library</div>
</header>
<nav class="tabs">
  <button class="tab-btn" data-tab="library" onclick="selectTab('library')">Library</button>
  <button class="tab-btn" data-tab="movies" onclick="selectTab('movies')">Movies</button>
  <button class="tab-btn" data-tab="tv" id="nav-tv" style="display:none" onclick="selectTab('tv')">TV</button>
  <button class="tab-btn" data-tab="sabnzbd" id="nav-sabnzbd" style="display:none" onclick="selectTab('sabnzbd')">SABnzbd</button>
  <button class="tab-btn" data-tab="dupes" id="nav-dupes" style="display:none" onclick="selectTab('dupes')">Cleanup</button>
  <button class="tab-btn" data-tab="log" onclick="selectTab('log')">Log</button>
</nav>
<main>
  <div id="banner"></div>
  <section id="library-section" class="tab-page" data-tab="library">
    <div class="section-head"><span class="section-title">Search &amp; Request</span></div>
    <div class="search-row">
      <div class="pill-toggle" id="search-type-toggle" style="display:none">
        <button id="search-type-movie" class="active" onclick="setSearchMediaType('movie')">Movie</button>
        <button id="search-type-tv" onclick="setSearchMediaType('tv')">TV</button>
      </div>
      <input class="text-input" id="library-search-input" type="text"
             placeholder="Search for a movie or show..."
             onkeydown="if(event.key==='Enter'){event.preventDefault();runSearch(document.getElementById('library-search-btn'));}">
      <button id="library-search-btn" onclick="runSearch(this)">Search</button>
    </div>
    <div id="search-meta" class="mode-line" style="margin-bottom:12px"></div>
    <div id="search-results-container"></div>

    <div class="section-head" style="margin-top:30px"><span class="section-title">Your Library</span>
      <span class="section-note" id="library-synced-note"></span></div>
    <div class="stat-row" id="library-stats"></div>
    <div id="library-delete-note"></div>
    <div class="search-row" style="margin-top:14px">
      <button onclick="runAction(this,'api/refresh-library')">Refresh Library</button>
      <input class="text-input" id="library-filter-input" type="text"
             placeholder="Filter your library..." oninput="onLibraryFilterInput()">
    </div>
    <div class="section-note" style="margin-bottom:6px">Movies</div>
    <div class="poster-grid" id="library-movies-body"></div>
    <div id="library-shows-block" style="display:none">
      <div class="section-note" style="margin:20px 0 6px">Shows</div>
      <div class="poster-grid" id="library-shows-body"></div>
    </div>
  </section>
  <section id="movies-section" class="tab-page" data-tab="movies"></section>
  <section id="tv-section" class="tab-page" data-tab="tv"></section>
  <section id="sabnzbd-section" class="tab-page" data-tab="sabnzbd"></section>
  <section id="dupes-section" class="tab-page" data-tab="dupes"></section>
  <section id="log-section" class="tab-page" data-tab="log"></section>
</main>
<div id="toast" class="toast"></div>
<div id="detail-modal" class="detail-modal" onclick="if(event.target===this) closeDetailModal()">
  <div class="detail-card">
    <button class="detail-close" onclick="closeDetailModal()">&times;</button>
    <div class="detail-body" id="detail-body"></div>
  </div>
</div>
<script>
let currentTab = 'library';
try { currentTab = localStorage.getItem('yarr_tab') || 'library'; } catch (e) {}
let lastJunkEntries = [];
let lastSearchResults = [];
let lastLibraryMovies = [];
let lastLibraryShows = [];
let searchMediaType = 'movie';
let allowLibraryDelete = false;

function selectTab(tab) {
  currentTab = tab;
  try { localStorage.setItem('yarr_tab', tab); } catch (e) {}
  document.querySelectorAll('.tab-page').forEach(el => el.classList.toggle('active', el.dataset.tab === tab));
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.toggle('active', el.dataset.tab === tab));
}

async function post(path, body) {
  const r = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body||{})});
  return r.json();
}

let toastTimer = null;
function showToast(msg, level) {
  const box = document.getElementById('toast');
  box.textContent = msg;
  box.className = 'toast show ' + (level || 'info');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { box.className = 'toast'; }, 6000);
}

async function fetchStatus() { return (await fetch('api/status')).json(); }

// Every action here fires an HA event and returns immediately — the
// actual work happens a moment later inside yarr.py. Rather than
// leaving a click looking like it did nothing, this shows the button
// as working, then polls api/status for a new Log entry (yarr.py
// republishes its status right after every action completes) so the
// toast reflects the real outcome instead of guessing.
async function runAction(btn, path, body, { confirmMsg, watchLog = true } = {}) {
  if (confirmMsg && !confirm(confirmMsg)) return;
  const originalText = btn ? btn.textContent : null;
  if (btn) { btn.disabled = true; btn.textContent = 'Working…'; }
  try {
    const before = watchLog ? await fetchStatus() : null;
    const beforeTs = before && before.log && before.log[0] ? before.log[0].ts : null;
    await post(path, body);
    if (watchLog) {
      let found = null;
      for (let i = 0; i < 8 && !found; i++) {
        await new Promise(r => setTimeout(r, 1200));
        const s = await fetchStatus();
        const last = s.log && s.log[0];
        if (last && last.ts !== beforeTs) found = last;
      }
      showToast(found ? found.message : 'Requested — check the Log tab if nothing changes.',
                found ? (found.level || 'info') : 'warn');
    } else {
      showToast('Done.', 'info');
    }
  } catch (e) {
    showToast('Request failed: ' + e.message, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = originalText; }
    refresh();
  }
}
function esc(s){return String(s==null?'':s).replace(/[&<>]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
function escAttr(s){return esc(s).replace(/"/g,'&quot;').replace(/'/g,'&#39;');}
function fmtDate(iso){ return iso ? new Date(iso).toLocaleString(undefined,{weekday:'short',day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}) : '—'; }
function timeUntil(iso){
  if(!iso) return '';
  const ms = new Date(iso) - new Date();
  if (ms <= 0) return 'any moment';
  const h = Math.round(ms/3600000);
  if (h < 1) return 'under an hour';
  if (h < 48) return h + 'h from now';
  return Math.round(h/24) + 'd from now';
}
function fmtBytes(n){
  if (!n) return '0 B';
  const units = ['B','KB','MB','GB','TB'];
  let i = 0;
  while (n >= 1024 && i < units.length-1) { n /= 1024; i++; }
  return n.toFixed(1) + ' ' + units[i];
}
function baseName(p){ const parts = String(p||'').split('/'); return parts[parts.length-1] || p; }
function chipsRow(list, cls) {
  if (!list || !list.length) return '<span class="section-note">none set</span>';
  return `<div class="chips">${list.map(g=>`<span class="chip ${cls||''}">${esc(g)}</span>`).join('')}</div>`;
}
function statusPill(s){
  const labels = {pending_watch:'awaiting watch', watched:'watched', deleting_soon:'deleting soon'};
  return `<span class="pill ${s}">${labels[s]||s}</span>`;
}
function decisionPill(d){ return `<span class="pill ${d}">${esc(d).replace(/_/g,' ')}</span>`; }

function suggestedTable(rows) {
  if (!rows || !rows.length) return '<div class="empty-row">Nothing suggested yet.</div>';
  return `<table class="list"><thead><tr><th>Title</th><th>Year</th><th>Outcome</th></tr></thead><tbody>
    ${rows.map(r => `<tr><td class="title-cell">${esc(r.title)}</td><td class="year">${r.year||'—'}</td><td>${decisionPill(r.decision)}</td></tr>`).join('')}
  </tbody></table>`;
}

function surpriseTable(rows, deleteFn) {
  if (!rows || !rows.length) return '<div class="empty-row">No surprise tracked right now.</div>';
  return `<table class="list"><thead><tr><th>Title</th><th>Year</th><th>Status</th><th></th><th></th></tr></thead><tbody>
    ${rows.map(r => `<tr><td class="title-cell">${esc(r.title)}</td><td class="year">${r.year||'—'}</td><td>${statusPill(r.status)}</td>
      <td class="countdown">${r.status==='deleting_soon' ? timeUntil(r.delete_at) : ''}</td>
      <td><button class="small-delete" onclick="${deleteFn}(${JSON.stringify(r.id)}, this)">Delete</button></td></tr>`).join('')}
  </tbody></table>`;
}

function proposalCard(pending, acceptFn, denyFn) {
  if (!pending) return '';
  return `<div class="proposal">
    <div class="section-note" style="margin-bottom:6px">Awaiting your decision</div>
    <div class="ptitle">${esc(pending.title)} ${pending.year ? '('+pending.year+')' : ''}</div>
    <div class="pmeta">Rating ${(pending.rating||0).toFixed(1)} · ${(pending.genres||[]).map(esc).join(', ') || 'no genres listed'}</div>
    <div class="pactions">
      <button onclick="${acceptFn}(this)">Accept</button>
      <button class="deny" onclick="${denyFn}(this)">Deny</button>
    </div>
  </div>`;
}

function posterImg(url, title) {
  return url ? `<img class="poster-img" src="${esc(url)}" alt="${esc(title)}" loading="lazy">`
             : `<div class="poster-placeholder">${esc(title)}</div>`;
}
function searchResultCard(r, i) {
  return `<div class="poster-card">
    <div class="poster-clickable" onclick="showDetail('search', ${i})">
      ${posterImg(r.poster_url, r.title)}
      <div class="poster-body">
        <div class="poster-title">${esc(r.title)}</div>
        <div class="poster-meta">${r.year||'—'} · ★ ${(r.rating||0).toFixed(1)}</div>
      </div>
    </div>
    <div class="poster-actions">${r.in_library ? '<span class="badge">In library</span>' : `<button onclick="addSearchResult(${i}, this)">Add</button>`}</div>
  </div>`;
}
function libraryMovieCard(m, i) {
  return `<div class="poster-card">
    <div class="poster-clickable" onclick="showDetail('movies', ${i})">
      ${posterImg(m.poster_url, m.title)}
      <div class="poster-body">
        <div class="poster-title">${esc(m.title)}</div>
        <div class="poster-meta">${m.year||'—'} · ${fmtBytes(m.size||0)}</div>
      </div>
    </div>
    <div class="poster-actions"><button class="small-delete" onclick="deleteLibraryMovie(${i}, this)" ${allowLibraryDelete?'':'disabled'}>Delete</button></div>
  </div>`;
}
function libraryShowCard(s, i) {
  return `<div class="poster-card">
    <div class="poster-clickable" onclick="showDetail('shows', ${i})">
      ${posterImg(s.poster_url, s.title)}
      <div class="poster-body">
        <div class="poster-title">${esc(s.title)}</div>
        <div class="poster-meta">${s.year||'—'} · ${fmtBytes(s.size||0)}</div>
      </div>
    </div>
    <div class="poster-actions"><button class="small-delete" onclick="deleteLibraryShow(${i}, this)" ${allowLibraryDelete?'':'disabled'}>Delete</button></div>
  </div>`;
}
function showDetail(source, i) {
  const item = source === 'search' ? lastSearchResults[i]
             : source === 'shows' ? lastLibraryShows[i]
             : lastLibraryMovies[i];
  if (!item) return;
  document.getElementById('detail-body').innerHTML = `
    <div class="detail-poster">${posterImg(item.poster_url, item.title)}</div>
    <div class="detail-info">
      <div class="detail-title">${esc(item.title)}${item.year ? ' ('+item.year+')' : ''}</div>
      <div class="poster-meta">${item.rating!=null ? '★ '+(item.rating||0).toFixed(1)+' · ' : ''}${item.size!=null ? fmtBytes(item.size||0) : ''}</div>
      ${chipsRow(item.genres)}
      <div class="detail-overview">${esc(item.overview) || 'No synopsis available.'}</div>
    </div>
  `;
  document.getElementById('detail-modal').classList.add('show');
}
function closeDetailModal() {
  document.getElementById('detail-modal').classList.remove('show');
}
function setSearchMediaType(t) {
  searchMediaType = t;
  document.getElementById('search-type-movie').classList.toggle('active', t === 'movie');
  document.getElementById('search-type-tv').classList.toggle('active', t === 'tv');
}
async function runSearch(btn) {
  const input = document.getElementById('library-search-input');
  const q = input ? input.value.trim() : '';
  if (!q) return;
  await runAction(btn, 'api/search-media', {query: q, media_type: searchMediaType});
}
function addSearchResult(i, btn) {
  const r = lastSearchResults[i];
  if (!r || r.in_library) return;
  const msg = `Add "${r.title}"${r.year ? ' ('+r.year+')' : ''} to your library?`;
  if (searchMediaType === 'tv') {
    runAction(btn, 'api/request-add-show', {tvdb_id: r.tvdb_id}, {confirmMsg: msg});
  } else {
    runAction(btn, 'api/request-add-movie', {tmdb_id: r.tmdb_id}, {confirmMsg: msg});
  }
}
function deleteLibraryMovie(i, btn) {
  const m = lastLibraryMovies[i];
  if (!m || !allowLibraryDelete) return;
  const msg = `Permanently delete "${m.title}"${m.year ? ' ('+m.year+')' : ''} and its files? `
    + 'This is a real library item, not something yArr added — this cannot be undone.';
  runAction(btn, 'api/library-delete-movie', {id: m.id}, {confirmMsg: msg});
}
function deleteLibraryShow(i, btn) {
  const s = lastLibraryShows[i];
  if (!s || !allowLibraryDelete) return;
  const msg = `Permanently delete "${s.title}"${s.year ? ' ('+s.year+')' : ''} and its files? `
    + 'This is a real library item, not something yArr added — this cannot be undone.';
  runAction(btn, 'api/library-delete-show', {id: s.id}, {confirmMsg: msg});
}
function onLibraryFilterInput() {
  const input = document.getElementById('library-filter-input');
  const q = (input ? input.value : '').toLowerCase();
  const moviesBody = document.getElementById('library-movies-body');
  if (moviesBody) {
    const rows = lastLibraryMovies.map((item, i) => ({item, i})).filter(({item}) => item.title.toLowerCase().includes(q));
    moviesBody.innerHTML = rows.length ? rows.map(({item, i}) => libraryMovieCard(item, i)).join('')
      : `<div class="empty-row">${lastLibraryMovies.length ? 'No matches.' : 'No movies found — press Refresh Library.'}</div>`;
  }
  const showsBody = document.getElementById('library-shows-body');
  if (showsBody) {
    const rows = lastLibraryShows.map((item, i) => ({item, i})).filter(({item}) => item.title.toLowerCase().includes(q));
    showsBody.innerHTML = rows.length ? rows.map(({item, i}) => libraryShowCard(item, i)).join('')
      : `<div class="empty-row">${lastLibraryShows.length ? 'No matches.' : 'No shows found — press Refresh Library.'}</div>`;
  }
}

async function refresh() {
  const d = await (await fetch('api/status')).json();

  document.getElementById('banner').innerHTML =
    (d.missing_secrets && d.missing_secrets.length)
      ? `<div class="banner"><b>Not fully configured.</b> Missing ${d.missing_secrets.map(s=>`<code>${esc(s)}</code>`).join(', ')} — set these in the add-on's Configuration tab.</div>`
      : '';

  const genreMode = d.learn_genres_from_library
    ? (d.learned_genres && d.learned_genres.length ? 'Learning from your Jellyfin library' : 'Learning enabled, waiting on library data')
    : 'Fixed genre list';

  document.getElementById('movies-section').innerHTML = `
    <div class="section-head"><span class="section-title">Movies · Radarr</span><span class="section-note">${d.state==='OK' ? 'engine running' : 'not configured'}</span></div>
    <div class="stat-row">
      <div class="stat"><div class="lbl">Suggested</div><div class="val">${d.suggested_count}</div></div>
      <div class="stat"><div class="lbl">Surprise tracked</div><div class="val">${d.surprise_count}</div></div>
      <div class="stat"><div class="lbl">Next surprise</div><div class="val small">${fmtDate(d.next_surprise_at)}</div></div>
    </div>
    <div class="mode-line">${genreMode}</div>
    ${chipsRow(d.effective_genres)}
    ${d.excluded_genres && d.excluded_genres.length ? `<div class="mode-line" style="margin-top:8px">Never suggested</div>${chipsRow(d.excluded_genres, 'off')}` : ''}
    ${d.denied_genres && d.denied_genres.length ? `<div class="mode-line" style="margin-top:8px">Denied enough times to auto-suppress</div>${chipsRow(d.denied_genres, 'off')}` : ''}
    ${proposalCard(d.pending_surprise, 'acceptSurprise', 'denySurprise')}
    <div style="margin:14px 0 18px;display:flex;align-items:center;gap:14px;flex-wrap:wrap">
      <button onclick="runAction(this,'api/surprise-now')" ${d.pending_surprise ? 'disabled' : ''}>Surprise Me Now</button>
      ${(d.surprises||[]).some(s => s.status === 'deleting_soon') ? (
        d.keep_surprise
          ? '<span class="keep-note">Pending deletion will be kept.</span>'
          : `<button class="ghost" onclick="runAction(this,'api/keep-surprise',{},{watchLog:false})">Keep It</button>`
      ) : ''}
    </div>
    <div class="section-note" style="margin-bottom:6px">Recently suggested</div>
    ${suggestedTable(d.recent_suggested)}
    <div class="section-note" style="margin:16px 0 6px">Tracked surprises</div>
    ${surpriseTable(d.surprises, 'deleteSurprise')}
  `;

  document.getElementById('nav-tv').style.display = d.tv_enabled ? '' : 'none';
  if (!d.tv_enabled && currentTab === 'tv') currentTab = 'movies';
  const tvSection = document.getElementById('tv-section');
  if (d.tv_enabled) {
    const tvGenreMode = d.learn_genres_from_library
      ? (d.learned_tv_genres && d.learned_tv_genres.length ? 'Learning from your Jellyfin library' : 'Learning enabled, waiting on library data')
      : 'Fixed genre list';
    tvSection.innerHTML = `
      <div class="section-head"><span class="section-title">TV · Sonarr</span></div>
      <div class="stat-row">
        <div class="stat"><div class="lbl">Suggested</div><div class="val">${d.suggested_shows_count}</div></div>
        <div class="stat"><div class="lbl">Surprise tracked</div><div class="val">${d.surprise_shows_count}</div></div>
        <div class="stat"><div class="lbl">Next surprise</div><div class="val small">${fmtDate(d.next_tv_surprise_at)}</div></div>
      </div>
      <div class="mode-line">${tvGenreMode}</div>
      ${chipsRow(d.effective_tv_genres)}
      ${proposalCard(d.pending_tv_surprise, 'acceptTvSurprise', 'denyTvSurprise')}
      <div style="margin:14px 0 18px;display:flex;align-items:center;gap:14px;flex-wrap:wrap">
        <button onclick="runAction(this,'api/surprise-tv-now')" ${d.pending_tv_surprise ? 'disabled' : ''}>Surprise Me Now (TV)</button>
        ${(d.surprise_shows||[]).some(s => s.status === 'deleting_soon') ? (
          d.keep_surprise_tv
            ? '<span class="keep-note">Pending deletion will be kept.</span>'
            : `<button class="ghost" onclick="runAction(this,'api/keep-surprise-tv',{},{watchLog:false})">Keep It</button>`
        ) : ''}
      </div>
      <div class="section-note" style="margin-bottom:6px">Recently suggested</div>
      ${suggestedTable(d.recent_suggested_shows)}
      <div class="section-note" style="margin:16px 0 6px">Tracked surprises</div>
      ${surpriseTable(d.surprise_shows, 'deleteTvSurprise')}
    `;
  }

  // Library tab — only the data sub-containers get their innerHTML
  // replaced here, never the search/filter <input> elements
  // themselves (those live in the static shell HTML above), so typing
  // into either box survives the 5s poll cycle instead of getting
  // wiped out from under the user mid-keystroke.
  lastSearchResults = d.last_search_results || [];
  lastLibraryMovies = d.library_movies || [];
  lastLibraryShows = d.library_shows || [];
  allowLibraryDelete = !!d.allow_library_delete;

  document.getElementById('search-type-toggle').style.display = d.tv_enabled ? '' : 'none';
  document.getElementById('search-meta').textContent = d.last_search_query
    ? `Last searched ${d.last_search_media_type||'movie'}: "${d.last_search_query}" (${lastSearchResults.length} result(s))`
    : '';
  document.getElementById('search-results-container').innerHTML = lastSearchResults.length
    ? `<div class="poster-grid" style="margin-bottom:30px">${lastSearchResults.map((r,i) => searchResultCard(r,i)).join('')}</div>`
    : '<div class="empty-row" style="margin-bottom:30px">No search results yet — type something above and press Search.</div>';

  document.getElementById('library-synced-note').textContent =
    'synced ' + (d.library_synced_at ? fmtDate(d.library_synced_at) : 'never');
  document.getElementById('library-stats').innerHTML = `
    <div class="stat"><div class="lbl">Movies</div><div class="val">${d.library_movie_count||0}</div></div>
    ${d.tv_enabled ? `<div class="stat"><div class="lbl">Shows</div><div class="val">${d.library_show_count||0}</div></div>` : ''}
  `;
  document.getElementById('library-delete-note').innerHTML = allowLibraryDelete ? '' :
    '<div class="mode-line">Deleting from your library is off by default — set <code>allow_library_delete: true</code> in apps.yaml to enable the Delete buttons below. This removes real files, not something yArr added itself.</div>';
  document.getElementById('library-shows-block').style.display = d.tv_enabled ? '' : 'none';
  onLibraryFilterInput();

  document.getElementById('nav-sabnzbd').style.display = d.sabnzbd_enabled ? '' : 'none';
  if (!d.sabnzbd_enabled && currentTab === 'sabnzbd') currentTab = 'movies';
  const sabSection = document.getElementById('sabnzbd-section');
  if (d.sabnzbd_enabled) {
    const items = d.sabnzbd_items || [];
    sabSection.innerHTML = `
      <div class="section-head"><span class="section-title">SABnzbd</span>
        <span class="section-note">${d.sabnzbd_paused ? 'paused' : esc(d.sabnzbd_status)}</span></div>
      <div class="stat-row">
        <div class="stat"><div class="lbl">Speed</div><div class="val">${(d.sabnzbd_speed_kbps||0).toFixed(0)} KB/s</div></div>
        <div class="stat"><div class="lbl">Queue</div><div class="val">${d.sabnzbd_queue_count}</div></div>
        <div class="stat"><div class="lbl">Size left</div><div class="val small">${esc(d.sabnzbd_size_left)||'—'}</div></div>
        <div class="stat"><div class="lbl">ETA</div><div class="val small">${esc(d.sabnzbd_eta)||'—'}</div></div>
      </div>
      ${items.length ? `<table class="list"><thead><tr><th>File</th><th>Progress</th><th>Status</th></tr></thead><tbody>
        ${items.map(i => `<tr><td class="title-cell">${esc(i.filename)}</td><td class="year">${(i.percentage||0).toFixed(0)}%</td><td class="year">${esc(i.status)}</td></tr>`).join('')}
      </tbody></table>` : '<div class="empty-row">Queue is empty.</div>'}
    `;
  }

  document.getElementById('nav-dupes').style.display = d.media_scan_enabled ? '' : 'none';
  if (!d.media_scan_enabled && currentTab === 'dupes') currentTab = 'movies';
  const dupesSection = document.getElementById('dupes-section');
  if (d.media_scan_enabled) {
    const groups = d.duplicate_groups || [];
    const junk = d.junk_entries || [];
    lastJunkEntries = junk;
    dupesSection.innerHTML = `
      <div class="section-head"><span class="section-title">Duplicates</span>
        <span class="section-note">last scan ${d.duplicate_scan_at ? fmtDate(d.duplicate_scan_at) : 'never'}</span></div>
      <div class="stat-row">
        <div class="stat"><div class="lbl">Groups found</div><div class="val">${d.duplicate_group_count||0}</div></div>
        <div class="stat"><div class="lbl">Space wasted</div><div class="val small">${fmtBytes(d.duplicate_wasted_bytes||0)}</div></div>
        <div class="stat"><div class="lbl">Safe to bulk-delete</div><div class="val small">${d.duplicate_deletable_count==null ? 'unknown' : d.duplicate_deletable_count + ' file(s) / ' + fmtBytes(d.duplicate_deletable_bytes||0)}</div></div>
      </div>
      <div class="mode-line">Same file size is the signal — review before deleting. Deleting here removes the file from disk immediately and tells Radarr/Sonarr to rescan. "Safe to bulk-delete" only counts groups where exactly one file matches Radarr/Sonarr's tracked copy, as of the last scan.</div>
      <div style="margin:14px 0 18px;display:flex;gap:10px;flex-wrap:wrap">
        <button onclick="runAction(this,'api/scan-duplicates-now')">Scan Now</button>
        <button class="ghost" onclick="runAction(this,'api/bulk-delete-duplicates',{},{confirmMsg:'Delete ${d.duplicate_deletable_count||0} duplicate file(s) whose group has a single Radarr/Sonarr-tracked copy? Ambiguous groups are skipped. This cannot be undone.'})" ${!d.duplicate_deletable_count ? 'disabled' : ''}>Delete All Inferior Duplicates</button>
      </div>
      ${d.duplicate_deletable_count==null ? '<div class="mode-line" style="margin-top:-8px">Bulk-delete count is unknown until the next successful scan (Radarr/Sonarr may have been unreachable during the last one) — press Scan Now.</div>' : ''}
      ${groups.length ? groups.map(g => `
        <table class="list" style="margin-bottom:14px"><thead><tr><th>File</th><th>Size</th><th></th></tr></thead><tbody>
          ${g.map(f => `<tr><td class="title-cell" title="${esc(f.path)}">${esc(baseName(f.path))}</td><td class="year">${fmtBytes(f.size)}</td>
            <td><button class="small-delete" onclick="runAction(this,'api/delete-duplicate-file',{path:${escAttr(JSON.stringify(f.path))}},{confirmMsg:'Delete this file from disk now? This cannot be undone.'})">Delete</button></td></tr>`).join('')}
        </tbody></table>
      `).join('') : '<div class="empty-row">No duplicate groups found.</div>'}

      <div class="section-head" style="margin-top:30px"><span class="section-title">Failed Unpacks / Junk</span>
        <span class="section-note">last scan ${d.junk_scan_at ? fmtDate(d.junk_scan_at) : 'never'}</span></div>
      <div class="stat-row">
        <div class="stat"><div class="lbl">Items found</div><div class="val">${d.junk_count||0}</div></div>
        <div class="stat"><div class="lbl">Space wasted</div><div class="val small">${fmtBytes(d.junk_bytes||0)}</div></div>
      </div>
      <div class="mode-line">Leftover SABnzbd extraction junk: an _UNPACK_/_FAILED_ folder left behind by a failed or interrupted unpack, or a stray archive piece that never got extracted — the usual cause of a bogus "UNPACK" entry showing up in Jellyfin. Empty (0-byte) junk is deleted automatically on every scan; anything listed below has real data in it and needs a button press. Deleting refreshes Jellyfin's library afterward.</div>
      ${junk.length ? `<div style="margin:14px 0 0"><button class="ghost" onclick="bulkDeleteJunk(this)">Delete All Junk</button></div>` : ''}
      ${junk.length ? `<table class="list" style="margin:14px 0"><thead><tr><th>Item</th><th>Size</th><th></th></tr></thead><tbody>
        ${junk.map(j => `<tr><td class="title-cell" title="${esc(j.path)}">${esc(baseName(j.path))}${j.is_dir ? ' <span class="section-note">(folder)</span>' : ''}</td><td class="year">${fmtBytes(j.size)}</td>
          <td><button class="small-delete" onclick="runAction(this,'api/delete-junk-entry',{path:${escAttr(JSON.stringify(j.path))}},{confirmMsg:${escAttr(JSON.stringify(j.is_dir ? 'Delete this entire folder and everything inside it? This cannot be undone.' : 'Delete this file from disk now? This cannot be undone.'))}})">Delete</button></td></tr>`).join('')}
      </tbody></table>` : '<div class="empty-row" style="margin-top:14px">No leftover unpack junk found.</div>'}
    `;
  }

  const log = d.log || [];
  document.getElementById('log-section').innerHTML = `
    <div class="section-head"><span class="section-title">Log</span>
      <span class="section-note">most recent ${log.length}</span></div>
    ${log.length ? log.map(e => `<div class="log-line ${e.level||'info'}">
        <span class="log-ts">${fmtDate(e.ts)}</span><span class="log-msg">${esc(e.message)}</span>
      </div>`).join('') : '<div class="empty-row">Nothing logged yet.</div>'}
  `;

  selectTab(currentTab);
}
function acceptSurprise(btn){ runAction(btn,'api/accept-surprise'); }
function denySurprise(btn){ runAction(btn,'api/deny-surprise'); }
function acceptTvSurprise(btn){ runAction(btn,'api/accept-surprise-tv'); }
function denyTvSurprise(btn){ runAction(btn,'api/deny-surprise-tv'); }
function deleteSurprise(id, btn){ runAction(btn,'api/delete-surprise',{id},{confirmMsg:'Delete this from Radarr now?'}); }
function deleteTvSurprise(id, btn){ runAction(btn,'api/delete-surprise-tv',{id},{confirmMsg:'Delete this from Sonarr now?'}); }
function bulkDeleteJunk(btn) {
  const names = lastJunkEntries.map(j => baseName(j.path));
  const msg = `Delete all ${lastJunkEntries.length} junk item(s)? This cannot be undone.\\n\\n` + names.join('\\n');
  runAction(btn, 'api/bulk-delete-junk', {}, { confirmMsg: msg });
}
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDetailModal(); });
refresh();
setInterval(refresh, 5000);
</script>
</body></html>
"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/")
        if path in ("", "/"):
            self._send(200, PAGE.encode(), "text/html; charset=utf-8")
        elif path.endswith("/api/status"):
            self._send(200, json.dumps(build_status()).encode(), "application/json")
        else:
            self._send(404, b"not found", "text/plain")

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        return json.loads(raw) if raw else {}

    def do_POST(self):
        path = self.path.split("?", 1)[0].rstrip("/")
        try:
            if path.endswith("/api/surprise-now"):
                ha_fire_event("yarr_surprise_me_now")
                self._send(200, json.dumps({"ok": True}).encode(), "application/json")
            elif path.endswith("/api/surprise-tv-now"):
                ha_fire_event("yarr_surprise_tv_now")
                self._send(200, json.dumps({"ok": True}).encode(), "application/json")
            elif path.endswith("/api/keep-surprise"):
                ha_set_state("input_boolean.yarr_keep_surprise", "on",
                             {"friendly_name": "yArr: Keep the pending surprise film", "icon": "mdi:heart"})
                self._send(200, json.dumps({"ok": True}).encode(), "application/json")
            elif path.endswith("/api/keep-surprise-tv"):
                ha_set_state("input_boolean.yarr_keep_surprise_tv", "on",
                             {"friendly_name": "yArr: Keep the pending surprise show", "icon": "mdi:heart"})
                self._send(200, json.dumps({"ok": True}).encode(), "application/json")
            elif path.endswith("/api/accept-surprise"):
                ha_fire_event("yarr_accept_surprise")
                self._send(200, json.dumps({"ok": True}).encode(), "application/json")
            elif path.endswith("/api/deny-surprise"):
                ha_fire_event("yarr_deny_surprise")
                self._send(200, json.dumps({"ok": True}).encode(), "application/json")
            elif path.endswith("/api/accept-surprise-tv"):
                ha_fire_event("yarr_accept_tv_surprise")
                self._send(200, json.dumps({"ok": True}).encode(), "application/json")
            elif path.endswith("/api/deny-surprise-tv"):
                ha_fire_event("yarr_deny_tv_surprise")
                self._send(200, json.dumps({"ok": True}).encode(), "application/json")
            elif path.endswith("/api/delete-surprise"):
                tmdb_id = self._read_json_body().get("id")
                ha_fire_event("yarr_delete_surprise_now", {"tmdb_id": tmdb_id})
                self._send(200, json.dumps({"ok": True}).encode(), "application/json")
            elif path.endswith("/api/delete-surprise-tv"):
                tvdb_id = self._read_json_body().get("id")
                ha_fire_event("yarr_delete_tv_surprise_now", {"tvdb_id": tvdb_id})
                self._send(200, json.dumps({"ok": True}).encode(), "application/json")
            elif path.endswith("/api/scan-duplicates-now"):
                ha_fire_event("yarr_scan_duplicates_now")
                self._send(200, json.dumps({"ok": True}).encode(), "application/json")
            elif path.endswith("/api/delete-duplicate-file"):
                file_path = self._read_json_body().get("path")
                ha_fire_event("yarr_delete_duplicate_file", {"path": file_path})
                self._send(200, json.dumps({"ok": True}).encode(), "application/json")
            elif path.endswith("/api/bulk-delete-duplicates"):
                ha_fire_event("yarr_bulk_delete_duplicates")
                self._send(200, json.dumps({"ok": True}).encode(), "application/json")
            elif path.endswith("/api/delete-junk-entry"):
                file_path = self._read_json_body().get("path")
                ha_fire_event("yarr_delete_junk_entry", {"path": file_path})
                self._send(200, json.dumps({"ok": True}).encode(), "application/json")
            elif path.endswith("/api/bulk-delete-junk"):
                ha_fire_event("yarr_bulk_delete_junk")
                self._send(200, json.dumps({"ok": True}).encode(), "application/json")
            elif path.endswith("/api/search-media"):
                body = self._read_json_body()
                ha_fire_event("yarr_search_media",
                              {"query": body.get("query", ""), "media_type": body.get("media_type", "movie")})
                self._send(200, json.dumps({"ok": True}).encode(), "application/json")
            elif path.endswith("/api/request-add-movie"):
                tmdb_id = self._read_json_body().get("tmdb_id")
                ha_fire_event("yarr_request_add_movie", {"tmdb_id": tmdb_id})
                self._send(200, json.dumps({"ok": True}).encode(), "application/json")
            elif path.endswith("/api/request-add-show"):
                tvdb_id = self._read_json_body().get("tvdb_id")
                ha_fire_event("yarr_request_add_show", {"tvdb_id": tvdb_id})
                self._send(200, json.dumps({"ok": True}).encode(), "application/json")
            elif path.endswith("/api/refresh-library"):
                ha_fire_event("yarr_refresh_library")
                self._send(200, json.dumps({"ok": True}).encode(), "application/json")
            elif path.endswith("/api/library-delete-movie"):
                movie_id = self._read_json_body().get("id")
                ha_fire_event("yarr_library_delete_movie", {"id": movie_id})
                self._send(200, json.dumps({"ok": True}).encode(), "application/json")
            elif path.endswith("/api/library-delete-show"):
                series_id = self._read_json_body().get("id")
                ha_fire_event("yarr_library_delete_show", {"id": series_id})
                self._send(200, json.dumps({"ok": True}).encode(), "application/json")
            else:
                self._send(404, b"not found", "text/plain")
        except Exception as exc:  # noqa: BLE001 — surface it to the caller, don't crash the server
            self._send(500, json.dumps({"error": str(exc)}).encode(), "application/json")

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    with socketserver.TCPServer(("0.0.0.0", PORT), Handler) as httpd:
        httpd.serve_forever()
