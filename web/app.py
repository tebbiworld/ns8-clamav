#!/usr/bin/env python3
# Copyright (C) 2026 tebbi
# SPDX-License-Identifier: GPL-3.0-or-later
"""Small HTTP/REST front end for a clamd daemon.

Endpoints (HTTP basic auth unless noted):
  GET  /                 upload form (browser)
  POST /api/v1/scan      multipart/form-data field "file" (one or more), or a raw
                         body with header X-Filename; returns JSON per file
  GET  /api/v1/version   clamd engine / signature version
  GET  /api/v1/health    no auth; 200 when clamd answers PING
Configuration through the environment: HOST, PORT, CLAMD_HOST, CLAMD_PORT,
MAX_UPLOAD_BYTES, WEB_USER, WEB_PASSWORD_PBKDF2 (salt$iterations$hex),
WEB_TITLE.
"""
import base64
import hashlib
import hmac
import html
import json
import os
import re
import signal
import socket
import struct
import sys
from email.parser import BytesParser
from email.policy import default as email_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8080"))
CLAMD = (os.environ.get("CLAMD_HOST", "127.0.0.1"), int(os.environ.get("CLAMD_PORT", "3310")))
MAX_UPLOAD = int(os.environ.get("MAX_UPLOAD_BYTES", str(100 * 1024 * 1024)))
WEB_USER = os.environ.get("WEB_USER", "")
WEB_HASH = os.environ.get("WEB_PASSWORD_PBKDF2", "")
TITLE = os.environ.get("WEB_TITLE", "ClamAV scanner")


def clamd_cmd(cmd: bytes) -> str:
    with socket.create_connection(CLAMD, timeout=10) as s:
        s.sendall(cmd)
        return recv_reply(s)


def recv_reply(s) -> str:
    data = b""
    while not data.endswith(b"\0"):
        chunk = s.recv(4096)
        if not chunk:
            break
        data += chunk
    return data.decode(errors="replace").strip("\0\n")


def clamd_scan(payload: bytes) -> str:
    with socket.create_connection(CLAMD, timeout=300) as s:
        s.sendall(b"zINSTREAM\0")
        view = memoryview(payload)
        for i in range(0, len(view), 65536):
            chunk = view[i:i + 65536]
            s.sendall(struct.pack("!I", len(chunk)) + chunk.tobytes())
        s.sendall(struct.pack("!I", 0))
        return recv_reply(s)


def scan_result(name: str, payload: bytes) -> dict:
    try:
        reply = clamd_scan(payload)
    except OSError as exc:
        return {"file": name, "size": len(payload), "result": "error", "detail": f"clamd unreachable: {exc}"}
    m = re.match(r"stream: (.*?)(?: FOUND| ERROR)?$", reply)
    if reply.endswith(" FOUND"):
        return {"file": name, "size": len(payload), "result": "infected", "signature": m.group(1) if m else reply}
    if reply.endswith("OK"):
        return {"file": name, "size": len(payload), "result": "clean"}
    return {"file": name, "size": len(payload), "result": "error", "detail": reply}


def check_auth(header: str) -> bool:
    if not WEB_USER or not WEB_HASH:
        return False
    if not header or not header.startswith("Basic "):
        return False
    try:
        user, _, password = base64.b64decode(header[6:]).decode().partition(":")
        salt, iterations, digest = WEB_HASH.split("$")
    except Exception:
        return False
    calc = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations)).hex()
    return hmac.compare_digest(user, WEB_USER) and hmac.compare_digest(calc, digest)


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{title}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{{font-family:system-ui,sans-serif;max-width:40rem;margin:3rem auto;padding:0 1rem;color:#222}}
h1{{font-size:1.4rem}} .box{{border:2px dashed #999;border-radius:8px;padding:2rem;text-align:center}}
table{{border-collapse:collapse;margin-top:1.5rem;width:100%}} td,th{{border-bottom:1px solid #ddd;padding:.4rem .6rem;text-align:left}}
.clean{{color:#1a7f37;font-weight:600}} .infected{{color:#b3261e;font-weight:600}} .error{{color:#8a6d00;font-weight:600}}
small{{color:#666}} code{{background:#f3f3f3;padding:.1rem .3rem}}</style></head><body>
<h1>{title}</h1>
<form class="box" id="f"><input type="file" id="files" name="file" multiple> <button type="submit">Scan</button>
<p><small>Files are streamed to the ClamAV daemon and not stored. Maximum size {max_mb} MB per file. Engine {version}</small></p></form>
<table id="t" hidden><thead><tr><th>File</th><th>Size</th><th>Result</th></tr></thead><tbody></tbody></table>
<p><small>REST: <code>curl -u user:password -F file=@document.pdf {base}/api/v1/scan</code></small></p>
<script>
const f=document.getElementById('f'),t=document.getElementById('t'),tb=t.querySelector('tbody');
f.addEventListener('submit',async e=>{{e.preventDefault();const fd=new FormData();for(const x of document.getElementById('files').files)fd.append('file',x);
if(!fd.has('file'))return;t.hidden=false;const tr=document.createElement('tr');tr.innerHTML='<td colspan=3>Scanning…</td>';tb.prepend(tr);
try{{const r=await fetch('api/v1/scan',{{method:'POST',body:fd}});const j=await r.json();tr.remove();
for(const x of j.results){{const row=document.createElement('tr');row.innerHTML=`<td>${{esc(x.file)}}</td><td>${{x.size}}</td><td class="${{x.result}}">${{x.result}}${{x.signature?' — '+esc(x.signature):''}}${{x.detail?' — '+esc(x.detail):''}}</td>`;tb.prepend(row);}}
}}catch(err){{tr.innerHTML='<td colspan=3 class="error">'+esc(String(err))+'</td>';}}}});
function esc(s){{return String(s).replace(/[&<>"]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c]))}}
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "clamav-web/1.0"

    def log_message(self, fmt, *args):  # journal-friendly one-liners
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    def send_json(self, code: int, obj) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def require_auth(self) -> bool:
        if check_auth(self.headers.get("Authorization", "")):
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="%s"' % TITLE)
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path == "/api/v1/health":
            try:
                ok = clamd_cmd(b"zPING\0") == "PONG"
            except OSError:
                ok = False
            return self.send_json(200 if ok else 503, {"clamd": "up" if ok else "down"})
        if not self.require_auth():
            return
        if path == "/api/v1/version":
            try:
                v = clamd_cmd(b"zVERSION\0")
            except OSError as exc:
                return self.send_json(503, {"error": f"clamd unreachable: {exc}"})
            parts = v.split("/")
            return self.send_json(200, {"version": v, "engine": parts[0].replace("ClamAV ", ""),
                                        "signatures": parts[1] if len(parts) > 1 else "", "signature_date": parts[2] if len(parts) > 2 else ""})
        if path == "/":
            try:
                version = html.escape(clamd_cmd(b"zVERSION\0"))
            except OSError:
                version = "<span class=error>clamd not reachable</span>"
            body = PAGE.format(title=html.escape(TITLE), max_mb=MAX_UPLOAD // (1024 * 1024), version=version,
                               base=html.escape(f"https://{self.headers.get('Host', 'host')}")).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        self.send_json(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?", 1)[0].rstrip("/")
        if path != "/api/v1/scan":
            return self.send_json(404, {"error": "not found"})
        if not self.require_auth():
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return self.send_json(400, {"error": "empty request body"})
        if length > MAX_UPLOAD + 65536:
            return self.send_json(413, {"error": f"request larger than {MAX_UPLOAD} bytes"})
        body = self.rfile.read(length)
        ctype = self.headers.get("Content-Type", "")
        files = []
        if ctype.startswith("multipart/form-data"):
            msg = BytesParser(policy=email_policy).parsebytes(
                b"Content-Type: " + ctype.encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + body)
            for part in msg.iter_parts():
                if part.get_param("name", header="content-disposition") == "file":
                    files.append((part.get_filename() or "upload", part.get_payload(decode=True) or b""))
        else:
            files.append((self.headers.get("X-Filename", "upload"), body))
        if not files:
            return self.send_json(400, {"error": 'no "file" field in form data'})
        results = []
        for name, payload in files:
            if len(payload) > MAX_UPLOAD:
                results.append({"file": name, "size": len(payload), "result": "error", "detail": f"larger than {MAX_UPLOAD} bytes"})
            else:
                results.append(scan_result(name, payload))
        infected = any(r["result"] == "infected" for r in results)
        errors = any(r["result"] == "error" for r in results)
        self.send_json(200, {"results": results, "infected": infected, "errors": errors})


if __name__ == "__main__":
    # PID 1 in the container: without a handler SIGTERM would be ignored and
    # podman would kill the container after its timeout (exit 137).
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    if not WEB_USER or not WEB_HASH:
        print("WEB_USER / WEB_PASSWORD_PBKDF2 not set: refusing to start without credentials", file=sys.stderr)
        sys.exit(1)
    print(f"clamav-web listening on {HOST}:{PORT}, clamd at {CLAMD[0]}:{CLAMD[1]}, max upload {MAX_UPLOAD} bytes", file=sys.stderr)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
