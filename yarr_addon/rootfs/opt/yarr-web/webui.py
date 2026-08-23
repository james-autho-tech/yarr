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
        "suggested_count": attrs.get("suggested_count", 0),
        "surprise_count": attrs.get("surprise_count", 0),
        "next_surprise_at": attrs.get("next_surprise_at"),
        "missing_secrets": attrs.get("missing_secrets", []),
        "enabled": is_on(states.get("input_boolean.yarr_enable")),
        "keep_surprise": is_on(states.get("input_boolean.yarr_keep_surprise")),
        "tv_enabled": attrs.get("tv_enabled", False),
        "suggested_shows_count": attrs.get("suggested_shows_count", 0),
        "surprise_shows_count": attrs.get("surprise_shows_count", 0),
        "next_tv_surprise_at": attrs.get("next_tv_surprise_at"),
        "keep_surprise_tv": is_on(states.get("input_boolean.yarr_keep_surprise_tv")),
        "sabnzbd_enabled": attrs.get("sabnzbd_enabled", False),
        "sabnzbd_status": sab.get("state", "unknown"),
        "sabnzbd_speed_kbps": sab_attrs.get("speed_kbps", 0),
        "sabnzbd_size_left": sab_attrs.get("size_left", ""),
        "sabnzbd_eta": sab_attrs.get("eta", ""),
        "sabnzbd_queue_count": sab_attrs.get("queue_count", 0),
    }


PAGE = """<!doctype html><html><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>yArr</title>
<style>
:root{--bg:#0f1115;--panel:#171a21;--ink:#e9edf3;--sub:#9aa4b2;--accent:#4fb0ff;--ok:#3ecf8e;--warn:#f5a623;--err:#f0556b;--border:#262b35}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
header{padding:16px 20px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:10px}
header h1{font-size:18px;margin:0}
main{max-width:720px;margin:0 auto;padding:20px}
.card{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:16px 18px;margin-bottom:16px}
.h{font-size:13px;text-transform:uppercase;letter-spacing:.04em;color:var(--sub);margin-bottom:10px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.tile{background:#11141b;border:1px solid var(--border);border-radius:8px;padding:10px 12px}
.tile .lbl{color:var(--sub);font-size:12px}
.tile .val{font-size:20px;font-weight:600}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;font-weight:600}
.badge.ok{background:rgba(62,207,142,.15);color:var(--ok)}
.badge.warn{background:rgba(245,166,35,.15);color:var(--warn)}
.badge.err{background:rgba(240,85,107,.15);color:var(--err)}
button{background:var(--accent);color:#04121f;border:none;border-radius:8px;padding:10px 14px;font-weight:600;cursor:pointer}
button.secondary{background:#232833;color:var(--ink)}
button:disabled{opacity:.5;cursor:default}
code{background:#11141b;padding:2px 6px;border-radius:4px}
.sub{color:var(--sub);font-size:13px;margin-top:6px}
a{color:var(--accent)}
</style></head><body>
<header><h1>🏴‍☠️ yArr</h1></header>
<main>
  <div class="card" id="status-card"></div>
  <div class="card" id="surprise-card"></div>
  <div class="card" id="tv-card" style="display:none"></div>
  <div class="card" id="sabnzbd-card" style="display:none"></div>
</main>
<script>
async function post(path, body) {
  const r = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body||{})});
  return r.json();
}

async function refresh() {
  const d = await (await fetch('api/status')).json();

  document.getElementById('status-card').innerHTML = `
    <div class="h">Status</div>
    <div class="grid">
      <div class="tile"><div class="lbl">Engine</div><div class="val">${d.state==='OK' ? '<span class="badge ok">Running</span>' : '<span class="badge warn">Not configured</span>'}</div></div>
      <div class="tile"><div class="lbl">Suggested films</div><div class="val">${d.suggested_count}</div></div>
      <div class="tile"><div class="lbl">Surprise films tracked</div><div class="val">${d.surprise_count}</div></div>
      <div class="tile"><div class="lbl">Next surprise</div><div class="val" style="font-size:13px">${d.next_surprise_at ? new Date(d.next_surprise_at).toLocaleString() : '—'}</div></div>
    </div>
    ${(d.missing_secrets && d.missing_secrets.length) ? `<div class="sub">Missing: <code>${d.missing_secrets.join('</code>, <code>')}</code> — set these in the Configuration tab.</div>` : ''}
  `;

  document.getElementById('surprise-card').innerHTML = `
    <div class="h">Surprise me (movies)</div>
    <button class="secondary" onclick="surpriseNow()">Surprise Me Now</button>
    <div class="sub">${d.keep_surprise ? 'A pending surprise deletion is currently set to be kept.' : ''}</div>
  `;

  const tvCard = document.getElementById('tv-card');
  if (d.tv_enabled) {
    tvCard.style.display = '';
    tvCard.innerHTML = `
      <div class="h">TV (Sonarr)</div>
      <div class="grid">
        <div class="tile"><div class="lbl">Suggested shows</div><div class="val">${d.suggested_shows_count}</div></div>
        <div class="tile"><div class="lbl">Surprise shows tracked</div><div class="val">${d.surprise_shows_count}</div></div>
        <div class="tile"><div class="lbl">Next TV surprise</div><div class="val" style="font-size:13px">${d.next_tv_surprise_at ? new Date(d.next_tv_surprise_at).toLocaleString() : '—'}</div></div>
      </div>
      <br><button class="secondary" onclick="surpriseTvNow()">Surprise Me Now (TV)</button>
      <div class="sub">${d.keep_surprise_tv ? 'A pending surprise show deletion is currently set to be kept.' : ''}</div>
    `;
  } else {
    tvCard.style.display = 'none';
  }

  const sabCard = document.getElementById('sabnzbd-card');
  if (d.sabnzbd_enabled) {
    sabCard.style.display = '';
    sabCard.innerHTML = `
      <div class="h">SABnzbd</div>
      <div class="grid">
        <div class="tile"><div class="lbl">Status</div><div class="val" style="font-size:16px">${d.sabnzbd_status}</div></div>
        <div class="tile"><div class="lbl">Speed</div><div class="val" style="font-size:16px">${(d.sabnzbd_speed_kbps||0).toFixed(0)} KB/s</div></div>
        <div class="tile"><div class="lbl">Queue</div><div class="val">${d.sabnzbd_queue_count}</div></div>
        <div class="tile"><div class="lbl">ETA</div><div class="val" style="font-size:16px">${d.sabnzbd_eta || '—'}</div></div>
      </div>
    `;
  } else {
    sabCard.style.display = 'none';
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
