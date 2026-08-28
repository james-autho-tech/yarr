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


def ha_call_service(domain_service, entity_id=None, **data):
    payload = json.dumps({**({"entity_id": entity_id} if entity_id else {}), **data}).encode()
    req = urllib.request.Request(
        f"http://supervisor/core/api/services/{domain_service}",
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
        "effective_genres": attrs.get("effective_genres", []),
        "learned_genres": attrs.get("learned_genres", []),

        "suggested_count": attrs.get("suggested_count", 0),
        "surprise_count": attrs.get("surprise_count", 0),
        "next_surprise_at": attrs.get("next_surprise_at"),
        "keep_surprise": is_on(states.get("input_boolean.yarr_keep_surprise")),
        "recent_suggested": attrs.get("recent_suggested", []),
        "surprises": attrs.get("surprises", []),

        "tv_enabled": attrs.get("tv_enabled", False),
        "suggested_shows_count": attrs.get("suggested_shows_count", 0),
        "surprise_shows_count": attrs.get("surprise_shows_count", 0),
        "next_tv_surprise_at": attrs.get("next_tv_surprise_at"),
        "keep_surprise_tv": is_on(states.get("input_boolean.yarr_keep_surprise_tv")),
        "effective_tv_genres": attrs.get("effective_tv_genres", []),
        "learned_tv_genres": attrs.get("learned_tv_genres", []),
        "recent_suggested_shows": attrs.get("recent_suggested_shows", []),
        "surprise_shows": attrs.get("surprise_shows", []),

        "sabnzbd_enabled": attrs.get("sabnzbd_enabled", False),
        "sabnzbd_status": sab.get("state", "unknown"),
        "sabnzbd_speed_kbps": sab_attrs.get("speed_kbps", 0),
        "sabnzbd_size_left": sab_attrs.get("size_left", ""),
        "sabnzbd_eta": sab_attrs.get("eta", ""),
        "sabnzbd_queue_count": sab_attrs.get("queue_count", 0),
        "sabnzbd_paused": sab_attrs.get("paused", False),
        "sabnzbd_items": sab_attrs.get("items", []),

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

main{max-width:820px;margin:0 auto;padding:26px 20px 60px}

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
</style></head><body>
<header>
  <div class="wordmark">y<span class="hi">Arr</span></div>
  <div class="tagline">Auto-stocks and auto-thins your Radarr/Sonarr library</div>
</header>
<nav class="tabs">
  <button class="tab-btn" data-tab="movies" onclick="selectTab('movies')">Movies</button>
  <button class="tab-btn" data-tab="tv" id="nav-tv" style="display:none" onclick="selectTab('tv')">TV</button>
  <button class="tab-btn" data-tab="sabnzbd" id="nav-sabnzbd" style="display:none" onclick="selectTab('sabnzbd')">SABnzbd</button>
  <button class="tab-btn" data-tab="log" onclick="selectTab('log')">Log</button>
</nav>
<main>
  <div id="banner"></div>
  <section id="movies-section" class="tab-page" data-tab="movies"></section>
  <section id="tv-section" class="tab-page" data-tab="tv"></section>
  <section id="sabnzbd-section" class="tab-page" data-tab="sabnzbd"></section>
  <section id="log-section" class="tab-page" data-tab="log"></section>
</main>
<script>
let currentTab = 'movies';
try { currentTab = localStorage.getItem('yarr_tab') || 'movies'; } catch (e) {}

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
function esc(s){return String(s==null?'':s).replace(/[&<>]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
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

function surpriseTable(rows) {
  if (!rows || !rows.length) return '<div class="empty-row">No surprise tracked right now.</div>';
  return `<table class="list"><thead><tr><th>Title</th><th>Year</th><th>Status</th><th></th></tr></thead><tbody>
    ${rows.map(r => `<tr><td class="title-cell">${esc(r.title)}</td><td class="year">${r.year||'—'}</td><td>${statusPill(r.status)}</td>
      <td class="countdown">${r.status==='deleting_soon' ? timeUntil(r.delete_at) : ''}</td></tr>`).join('')}
  </tbody></table>`;
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
    <div style="margin:14px 0 18px"><button onclick="surpriseNow()">Surprise Me Now</button>
      ${d.keep_surprise ? '<span class="keep-note">A pending deletion is currently set to be kept.</span>' : ''}</div>
    <div class="section-note" style="margin-bottom:6px">Recently suggested</div>
    ${suggestedTable(d.recent_suggested)}
    <div class="section-note" style="margin:16px 0 6px">Tracked surprises</div>
    ${surpriseTable(d.surprises)}
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
      <div style="margin:14px 0 18px"><button onclick="surpriseTvNow()">Surprise Me Now (TV)</button>
        ${d.keep_surprise_tv ? '<span class="keep-note">A pending deletion is currently set to be kept.</span>' : ''}</div>
      <div class="section-note" style="margin-bottom:6px">Recently suggested</div>
      ${suggestedTable(d.recent_suggested_shows)}
      <div class="section-note" style="margin:16px 0 6px">Tracked surprises</div>
      ${surpriseTable(d.surprise_shows)}
    `;
  }

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
async function surpriseNow(){ await post('api/surprise-now'); refresh(); }
async function surpriseTvNow(){ await post('api/surprise-tv-now'); refresh(); }
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

    def do_POST(self):
        path = self.path.split("?", 1)[0].rstrip("/")
        try:
            if path.endswith("/api/surprise-now"):
                ha_call_service("input_button/press", "input_button.yarr_surprise_me_now")
                self._send(200, json.dumps({"ok": True}).encode(), "application/json")
            elif path.endswith("/api/surprise-tv-now"):
                ha_call_service("input_button/press", "input_button.yarr_surprise_tv_now")
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
