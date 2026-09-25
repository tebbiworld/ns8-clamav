#!/usr/bin/env python3
# Copyright (C) 2026 tebbi
# SPDX-License-Identifier: GPL-3.0-or-later
"""Small HTTP/REST front end for a clamd daemon.

Endpoints (login required unless noted or WEB_AUTH=none):
  GET  /                 upload form (browser; redirects to /login)
  GET  /login, POST /login, POST /logout
                         login page with a session cookie
  POST /api/v1/scan      multipart/form-data field "file" (one or more), or a raw
                         body with header X-Filename; returns JSON per file
  GET  /api/v1/version   clamd engine / signature version
  GET  /api/v1/health    no login; 200 when clamd answers PING
The API takes the session cookie of the page or HTTP basic authentication.

WEB_AUTH selects how logins are checked:
  none   no login at all; access is limited only by the Traefik IP allow-list
  local  WEB_USER + WEB_PASSWORD_PBKDF2 (salt$iterations$hex)
  ldap   a user of the NS8 user domain, through the node's ldapproxy
         (LDAP_HOST/PORT/BASE_DN/BIND_DN/BIND_PASSWORD/SCHEMA, written by
         bin/discover-ldap), optionally only members of LDAP_GROUP
Other settings: HOST, PORT, CLAMD_HOST, CLAMD_PORT, MAX_UPLOAD_BYTES,
WEB_TITLE.
"""
import base64
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import signal
import socket
import struct
import sys
import threading
import time
import urllib.parse
from email.parser import BytesParser
from email.policy import default as email_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8080"))
CLAMD = (os.environ.get("CLAMD_HOST", "127.0.0.1"), int(os.environ.get("CLAMD_PORT", "3310")))
MAX_UPLOAD = int(os.environ.get("MAX_UPLOAD_BYTES", str(100 * 1024 * 1024)))
WEB_AUTH = os.environ.get("WEB_AUTH", "local").lower()
WEB_USER = os.environ.get("WEB_USER", "")
WEB_HASH = os.environ.get("WEB_PASSWORD_PBKDF2", "")
LDAP = {k: os.environ.get("LDAP_" + k, "") for k in ("HOST", "PORT", "BASE_DN", "BIND_DN", "BIND_PASSWORD", "SCHEMA", "GROUP")}
TITLE = os.environ.get("WEB_TITLE", "ClamAV scanner")

SESSION_COOKIE = "clamav_session"
SESSION_SECONDS = 8 * 3600
# a new key on every start: a restart logs everybody out, nothing to store
SESSION_KEY = secrets.token_bytes(32)
# the API checks basic auth on every request: remember a successful directory
# login briefly instead of binding for each file of a batch
_auth_cache = {}
_auth_cache_lock = threading.Lock()
AUTH_CACHE_SECONDS = 60


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


def check_local(user: str, password: str) -> bool:
    if not WEB_USER or not WEB_HASH:
        return False
    try:
        salt, iterations, digest = WEB_HASH.split("$")
    except ValueError:
        return False
    calc = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations)).hex()
    return hmac.compare_digest(user, WEB_USER) and hmac.compare_digest(calc, digest)


def check_ldap(user: str, password: str) -> bool:
    import ldap3
    from ldap3.utils.conv import escape_filter_chars
    if not LDAP["HOST"] or not LDAP["BASE_DN"]:
        print("login refused: the user domain is not available (see bin/discover-ldap)", file=sys.stderr)
        return False
    # the ldapproxy listens in clear text on the node's loopback and talks TLS
    # to the directory itself
    server = ldap3.Server(LDAP["HOST"], port=int(LDAP["PORT"] or 389), connect_timeout=5)
    ad = LDAP["SCHEMA"] == "ad"
    name = escape_filter_chars(user)
    if ad:
        # enabled user accounts only
        ufilter = f"(&(objectClass=user)(sAMAccountName={name})(!(userAccountControl:1.2.840.113556.1.4.803:=2)))"
    else:
        ufilter = f"(&(objectClass=posixAccount)(uid={name}))"
    try:
        with ldap3.Connection(server, LDAP["BIND_DN"], LDAP["BIND_PASSWORD"], auto_bind=True, receive_timeout=10) as conn:
            conn.search(LDAP["BASE_DN"], ufilter, attributes=[])
            if len(conn.entries) != 1:
                return False
            user_dn = conn.entries[0].entry_dn
            group = LDAP["GROUP"]
            if group:
                gname = escape_filter_chars(group)
                if ad:
                    conn.search(LDAP["BASE_DN"], f"(&(objectClass=group)(sAMAccountName={gname}))", attributes=[])
                    if len(conn.entries) != 1:
                        print(f"login refused: group {group!r} not found", file=sys.stderr)
                        return False
                    group_dn = escape_filter_chars(conn.entries[0].entry_dn)
                    # LDAP_MATCHING_RULE_IN_CHAIN: members of nested groups count too
                    conn.search(user_dn, f"(memberOf:1.2.840.113556.1.4.1941:={group_dn})", search_scope=ldap3.BASE, attributes=[])
                else:
                    conn.search(LDAP["BASE_DN"], f"(&(objectClass=posixGroup)(cn={gname})(memberUid={name}))", attributes=[])
                if len(conn.entries) < 1:
                    print(f"login refused: {user} is not a member of {group}", file=sys.stderr)
                    return False
        # the password check itself: bind as the user
        with ldap3.Connection(server, user_dn, password, auto_bind=True, receive_timeout=10):
            return True
    except ldap3.core.exceptions.LDAPBindError:
        return False
    except ldap3.core.exceptions.LDAPException as exc:
        print(f"LDAP error: {exc}", file=sys.stderr)
        return False


def check_credentials(user: str, password: str) -> bool:
    # an empty password would be an anonymous (always successful) LDAP bind
    if not user or not password:
        return False
    key = hashlib.sha256(f"{user}\0{password}".encode()).hexdigest()
    now = time.monotonic()
    with _auth_cache_lock:
        if _auth_cache.get(key, 0) > now:
            return True
    ok = check_ldap(user, password) if WEB_AUTH == "ldap" else check_local(user, password)
    if ok:
        with _auth_cache_lock:
            for k in [k for k, exp in _auth_cache.items() if exp <= now]:
                del _auth_cache[k]
            _auth_cache[key] = now + AUTH_CACHE_SECONDS
    else:
        time.sleep(1)  # slow down password guessing
    return ok


def check_basic(header: str) -> bool:
    if not header or not header.startswith("Basic "):
        return False
    try:
        user, _, password = base64.b64decode(header[6:]).decode().partition(":")
    except Exception:
        return False
    return check_credentials(user, password)


def make_session(user: str) -> str:
    payload = base64.urlsafe_b64encode(json.dumps([user, int(time.time()) + SESSION_SECONDS]).encode()).decode()
    sig = hmac.new(SESSION_KEY, payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def session_user(cookie_header: str) -> str:
    for part in (cookie_header or "").split(";"):
        name, _, value = part.strip().partition("=")
        if name != SESSION_COOKIE or "." not in value:
            continue
        payload, _, sig = value.rpartition(".")
        if not hmac.compare_digest(sig, hmac.new(SESSION_KEY, payload.encode(), hashlib.sha256).hexdigest()):
            return ""
        try:
            user, expires = json.loads(base64.urlsafe_b64decode(payload))
        except Exception:
            return ""
        return user if expires > time.time() else ""
    return ""


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{title}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{{font-family:system-ui,sans-serif;max-width:40rem;margin:3rem auto;padding:0 1rem;color:#222}}
h1{{font-size:1.4rem}} .logout{{float:right;margin-top:-3rem}} .box{{border:2px dashed #999;border-radius:8px;padding:2rem;text-align:center}}
table{{border-collapse:collapse;margin-top:1.5rem;width:100%}} td,th{{border-bottom:1px solid #ddd;padding:.4rem .6rem;text-align:left}}
.clean{{color:#1a7f37;font-weight:600}} .infected{{color:#b3261e;font-weight:600}} .error{{color:#8a6d00;font-weight:600}}
small{{color:#666}} code{{background:#f3f3f3;padding:.1rem .3rem}}</style></head><body>
<h1>{title}</h1>
{logout}
<form class="box" id="f"><input type="file" id="files" name="file" multiple> <button type="submit">Scan</button>
<p><small>Files are streamed to the ClamAV daemon and not stored. Maximum size {max_mb} MB per file. Engine {version}</small></p></form>
<table id="t" hidden><thead><tr><th>File</th><th>Size</th><th>Result</th></tr></thead><tbody></tbody></table>
<p><small>REST: <code>curl {login}-F file=@document.pdf {base}/api/v1/scan</code></small></p>
<script>
const f=document.getElementById('f'),t=document.getElementById('t'),tb=t.querySelector('tbody');
f.addEventListener('submit',async e=>{{e.preventDefault();const fd=new FormData();for(const x of document.getElementById('files').files)fd.append('file',x);
if(!fd.has('file'))return;t.hidden=false;const tr=document.createElement('tr');tr.innerHTML='<td colspan=3>Scanning…</td>';tb.prepend(tr);
try{{const r=await fetch('api/v1/scan',{{method:'POST',body:fd,headers:{{'X-Requested-With':'clamav-web'}}}});if(r.status==401){{location.href='login';return;}}const j=await r.json();tr.remove();
for(const x of j.results){{const row=document.createElement('tr');row.innerHTML=`<td>${{esc(x.file)}}</td><td>${{x.size}}</td><td class="${{x.result}}">${{x.result}}${{x.signature?' — '+esc(x.signature):''}}${{x.detail?' — '+esc(x.detail):''}}</td>`;tb.prepend(row);}}
}}catch(err){{tr.innerHTML='<td colspan=3 class="error">'+esc(String(err))+'</td>';}}}});
function esc(s){{return String(s).replace(/[&<>"]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c]))}}
</script></body></html>"""


LOGIN_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{title}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{{font-family:system-ui,sans-serif;max-width:22rem;margin:4rem auto;padding:0 1rem;color:#222}}
h1{{font-size:1.3rem}} label{{display:block;margin-top:1rem}} input{{width:100%;padding:.5rem;box-sizing:border-box;font-size:1rem}}
button{{margin-top:1.2rem;padding:.5rem 1.2rem;font-size:1rem}} .error{{color:#b3261e}} small{{color:#666}}</style></head><body>
<h1>{title}</h1><form method="post" action="login">
<label>User name<input name="user" autocomplete="username" autofocus required></label>
<label>Password<input name="password" type="password" autocomplete="current-password" required></label>
{error}<button type="submit">Log in</button></form>
<p><small>{hint}</small></p></body></html>"""


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

    def send_html(self, code: int, body: str, headers=()) -> None:
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, location: str, headers=()) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()

    def current_user(self, api_post: bool = False) -> str:
        """The logged-in user ("-" without login), or "" when not logged in."""
        if WEB_AUTH == "none":
            return "-"
        user = session_user(self.headers.get("Cookie", ""))
        # a cookie is sent along cross-site too: a POST must also carry the
        # header that only the page's own script sets (a custom header forces
        # a CORS preflight, which this service never answers)
        if user and (not api_post or self.headers.get("X-Requested-With") == "clamav-web"):
            return user
        auth = self.headers.get("Authorization", "")
        if auth and check_basic(auth):
            return base64.b64decode(auth[6:]).decode().partition(":")[0]
        return ""

    def require_api_auth(self, api_post: bool = False) -> bool:
        if self.current_user(api_post):
            return True
        self.send_response(401)
        # the page's own requests must not pop up the browser's login dialog
        if self.headers.get("X-Requested-With") != "clamav-web":
            self.send_header("WWW-Authenticate", 'Basic realm="%s"' % TITLE)
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def login_page(self, code: int = 200, error: str = "") -> None:
        hint = "Log in with your account of the user domain." if WEB_AUTH == "ldap" else "Log in with the login name set in the ClamAV settings."
        self.send_html(code, LOGIN_PAGE.format(title=html.escape(TITLE), hint=hint,
                                               error=f'<p class="error">{html.escape(error)}</p>' if error else ""))

    def do_login(self) -> None:
        if WEB_AUTH == "none":
            return self.redirect("./")
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 4096:
            return self.login_page(400, "Invalid request.")
        form = urllib.parse.parse_qs(self.rfile.read(length).decode(errors="replace"))
        user = (form.get("user") or [""])[0].strip()
        password = (form.get("password") or [""])[0]
        if not check_credentials(user, password):
            print(f"failed login for {user!r} from {self.headers.get('X-Forwarded-For', self.client_address[0])}", file=sys.stderr)
            return self.login_page(401, "Wrong user name or password.")
        cookie = f"{SESSION_COOKIE}={make_session(user)}; Path=/; Max-Age={SESSION_SECONDS}; HttpOnly; Secure; SameSite=Strict"
        self.redirect("./", [("Set-Cookie", cookie)])

    def do_logout(self) -> None:
        self.redirect("login", [("Set-Cookie", f"{SESSION_COOKIE}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Strict")])

    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path == "/api/v1/health":
            try:
                ok = clamd_cmd(b"zPING\0") == "PONG"
            except OSError:
                ok = False
            return self.send_json(200 if ok else 503, {"clamd": "up" if ok else "down"})
        if path == "/login":
            if WEB_AUTH == "none" or self.current_user():
                return self.redirect("./")
            return self.login_page()
        if path == "/":
            user = self.current_user()
            if not user:
                return self.redirect("login")
            return self.send_index(user)
        if not self.require_api_auth():
            return
        if path == "/api/v1/version":
            try:
                v = clamd_cmd(b"zVERSION\0")
            except OSError as exc:
                return self.send_json(503, {"error": f"clamd unreachable: {exc}"})
            parts = v.split("/")
            return self.send_json(200, {"version": v, "engine": parts[0].replace("ClamAV ", ""),
                                        "signatures": parts[1] if len(parts) > 1 else "", "signature_date": parts[2] if len(parts) > 2 else ""})
        self.send_json(404, {"error": "not found"})

    def send_index(self, user: str) -> None:
        try:
            version = html.escape(clamd_cmd(b"zVERSION\0"))
        except OSError:
            version = "<span class=error>clamd not reachable</span>"
        logout = "" if WEB_AUTH == "none" else (
            f'<form class="logout" method="post" action="logout"><small>{html.escape(user)}</small> '
            '<button type="submit">Log out</button></form>')
        self.send_html(200, PAGE.format(title=html.escape(TITLE), max_mb=MAX_UPLOAD // (1024 * 1024), version=version,
                                        login="" if WEB_AUTH == "none" else "-u user:password ", logout=logout,
                                        base=html.escape(f"https://{self.headers.get('Host', 'host')}")))

    def do_POST(self):
        path = self.path.split("?", 1)[0].rstrip("/")
        if path == "/login":
            return self.do_login()
        if path == "/logout":
            return self.do_logout()
        if path != "/api/v1/scan":
            return self.send_json(404, {"error": "not found"})
        if not self.require_api_auth(api_post=True):
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
    if WEB_AUTH not in ("none", "local", "ldap"):
        print(f"unknown WEB_AUTH={WEB_AUTH!r}: expected none, local or ldap", file=sys.stderr)
        sys.exit(1)
    if WEB_AUTH == "local" and (not WEB_USER or not WEB_HASH):
        print("WEB_USER / WEB_PASSWORD_PBKDF2 not set: refusing to start without credentials", file=sys.stderr)
        sys.exit(1)
    if WEB_AUTH == "ldap" and not LDAP["HOST"]:
        # keep running: the form shows up, every login is refused
        print("WEB_AUTH=ldap but the user domain is not available: all logins will be refused", file=sys.stderr)
    if WEB_AUTH == "none":
        print("login disabled (WEB_AUTH=none): anyone who reaches the route may scan", file=sys.stderr)
    else:
        print(f"login: {WEB_AUTH}" + (f", group {LDAP['GROUP']}" if WEB_AUTH == "ldap" and LDAP["GROUP"] else ""), file=sys.stderr)
    print(f"clamav-web listening on {HOST}:{PORT}, clamd at {CLAMD[0]}:{CLAMD[1]}, max upload {MAX_UPLOAD} bytes", file=sys.stderr)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
