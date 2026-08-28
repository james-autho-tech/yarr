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
    }


PAGE = """<!doctype html><html><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>yArr</title>
<style>
:root{
  --bg:#15120e; --panel:#1d1913; --panel-2:#241f18; --edge:#332c22;
  --ink:#f1ebe0; --sub:#a3947d; --faint:#6f6350;
  --accent:#dba33a; --accent-ink:#1a1206;
  --ok:#7fae74; --warn:#dba33a; --err:#c25a4c;
  --serif: Georgia, "Iowan Old Style", "Palatino Linotype", "Book Antiqua", serif;
  --mono: ui-monospace, SFMono-Regular, "Cascadia Mono", Consolas, monospace;
  --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 var(--sans);
     background-image:radial-gradient(ellipse at top, rgba(219,163,58,.05), transparent 60%)}
a{color:var(--accent)}
code{font-family:var(--mono);background:var(--panel-2);padding:1px 6px;border-radius:3px;font-size:.85em}

header{padding:22px 24px 18px;border-bottom:1px solid var(--edge)}
.wordmark{font-family:var(--serif);font-size:26px;font-weight:700;letter-spacing:.01em;
          display:flex;align-items:baseline;gap:10px}
.wordmark .rule{display:inline-block;width:28px;height:3px;background:var(--accent);
                 border-radius:2px;transform:translateY(-4px)}
.tagline{color:var(--sub);font-size:12.5px;margin-top:3px;letter-spacing:.02em}

main{max-width:760px;margin:0 auto;padding:22px 20px 60px}

.banner{background:rgba(194,90,76,.12);border:1px solid rgba(194,90,76,.35);
        border-radius:8px;padding:12px 16px;margin-bottom:20px;font-size:13px;color:#e8c3bb}
.banner b{color:var(--err)}

section{margin-bottom:30px}
.section-head{display:flex;align-items:baseline;justify-content:space-between;
              border-bottom:1px solid var(--edge);padding-bottom:8px;margin-bottom:14px}
.section-title{font-family:var(--serif);font-size:16px;color:var(--ink);letter-spacing:.01em}
.section-note{color:var(--faint);font-size:12px}

.stat-row{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:16px}
.stat{flex:1 1 130px;background:var(--panel);border:1px solid var(--edge);border-radius:8px;
      padding:11px 14px}
.stat .lbl{color:var(--sub);font-size:11px;text-transform:uppercase;letter-spacing:.06em}
.stat .val{font-family:var(--mono);font-size:19px;margin-top:2px;color:var(--ink)}
.stat .val.small{font-size:13px}

.chips{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 4px}
.chip{font-size:11.5px;padding:3px 10px;border-radius:20px;border:1px solid var(--edge);
      color:var(--sub);background:var(--panel-2)}
.chip.on{border-color:var(--accent);color:var(--accent);background:rgba(219,163,58,.1)}
.chip.off{border-color:rgba(194,90,76,.4);color:#d69086;background:rgba(194,90,76,.08)}
.mode-line{font-size:12.5px;color:var(--sub);margin-top:2px}

button{background:var(--accent);color:var(--accent-ink);border:none;border-radius:6px;
       padding:9px 16px;font-weight:600;font-size:13px;cursor:pointer;font-family:var(--sans)}
button:hover{filter:brightness(1.08)}
button.ghost{background:transparent;color:var(--sub);border:1px solid var(--edge)}
button.ghost:hover{color:var(--ink);border-color:var(--sub)}

table{width:100%;border-collapse:collapse;font-size:13px}
table.list td, table.list th{padding:7px 4px;text-align:left;border-bottom:1px solid var(--edge)}
table.list th{color:var(--faint);font-size:11px;text-transform:uppercase;letter-spacing:.05em;
              font-weight:600}
table.list tr:last-child td{border-bottom:none}
.title-cell{color:var(--ink)}
.year{color:var(--faint);font-family:var(--mono);font-size:12px}
.empty-row{color:var(--faint);font-style:italic;padding:10px 4px;font-size:13px}

.pill{font-size:11px;padding:2px 9px;border-radius:20px;font-weight:600;letter-spacing:.02em}
.pill.pending_watch{background:rgba(163,148,125,.15);color:var(--sub)}
.pill.watched{background:rgba(127,174,116,.15);color:var(--ok)}
.pill.deleting_soon{background:rgba(194,90,76,.15);color:var(--err)}
.pill.added{background:rgba(127,174,116,.15);color:var(--ok)}
.pill.rejected_low_rating,.pill.rejected_in_radarr,.pill.rejected_watched{
  background:rgba(163,148,125,.12);color:var(--faint)}
.countdown{color:var(--faint);font-size:11.5px;font-family:var(--mono)}

.keep-note{margin-top:10px;font-size:12.5px;color:var(--warn)}
</style></head><body>
<header>
  <div class="wordmark"><span class="rule"></span>yArr</div>
  <div class="tagline">Quietly stocking and thinning your library</div>
</header>
<main>
  <div id="banner"></div>
  <section id="movies-section"></section>
  <section id="tv-section" style="display:none"></section>
  <section id="sabnzbd-section" style="display:none"></section>
</main>
<script>
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

  const tvSection = document.getElementById('tv-section');
  if (d.tv_enabled) {
    tvSection.style.display = '';
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
  } else {
    tvSection.style.display = 'none';
  }

  const sabSection = document.getElementById('sabnzbd-section');
  if (d.sabnzbd_enabled) {
    sabSection.style.display = '';
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
  } else {
    sabSection.style.display = 'none';
  }
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
