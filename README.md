# ns8-clamav

A [NethServer 8](https://github.com/NethServer/ns8-core) module that runs the
[ClamAV](https://www.clamav.net/) daemon from the official `clamav/clamav`
image as a **scan service for the cluster**: Nextcloud's *Antivirus for files*
app, ecoDMS, Samba or any other client that speaks the clamd protocol connects
to it over TCP 3310.

Why a separate module: the NS8 Mail module ships its own clamd, but bound to
`127.0.0.1:11330` of the mail node only. This module runs wherever it is needed
and is reachable from every node through the cluster VPN.

## Architecture

One rootless container, host network:

| | |
| --- | --- |
| Image | `docker.io/clamav/clamav:<pinned>` — clamd + freshclam + initial signature database |
| Port | TCP 3310 on all addresses of the node |
| Volume `clamav-db` | signature database (~300 MB), refreshed by freshclam; not in the backup, re-downloaded when missing |
| Container `clamav-web` (optional) | upload form + REST API, `ghcr.io/tebbiworld/clamav-web`, behind Traefik |
| Memory | clamd keeps the signatures in RAM: plan **1–1.5 GB** for the node |

Who can connect is decided by the node firewall:

| Client | Address to use | Allowed |
| --- | --- | --- |
| Module on the same node, slirp4netns network (NS8 Nextcloud) | `10.0.2.2:3310` | always |
| Module on the same node, pasta network | `host.containers.internal:3310` | always |
| Module or service on another node | `<VPN address of this node>:3310` (10.5.4.x, zone *trusted*) | always |
| Clients in the LAN | `<LAN address>:3310` | only with **LAN access** enabled (opens 3310/tcp in the public zone) |

One instance per node (fixed port). The Mail module's clamd (11330) does not
clash.

## Install

```
add-module ghcr.io/tebbiworld/clamav:latest 1
```

The first start downloads the signature database; clamd answers after a few
minutes. The settings page shows engine and signature version once it is up.

## Settings

| Setting | clamd option | Default |
| --- | --- | --- |
| LAN access | firewall public service `3310/tcp` | off |
| Maximum file size (MB) | `MaxFileSize` | 100 |
| Maximum scan size (MB) | `MaxScanSize` | 400 |
| Maximum stream length (MB) | `StreamMaxLength` | 100 |
| Signature update checks per day | `freshclam --checks` | 12 |

Settings are written to `state/clamav.env` as `CLAMD_CONF_*` variables, which
the image entrypoint applies to `clamd.conf` at start.

## Nextcloud

Install the app *Antivirus for files* (`files_antivirus`), then in
*Administration → Security → Antivirus for files*:

| Field | Value |
| --- | --- |
| Mode | **Daemon (host)** |
| Host | `10.0.2.2` if Nextcloud runs on this node, otherwise the VPN address of this node (settings page) |
| Port | `3310` |

The settings page lists every Nextcloud instance of the cluster with the exact
*Host* and *Port* to enter. Enter the address alone in *Host*, never `address:3310`.
When ClamAV or Nextcloud moves to another node, the host changes: take the new value
from the settings page and update Nextcloud (`occ config:app:set files_antivirus av_host --value=<host>`).
| Maximum stream length | the module's value in bytes (default 100 MB = `104857600`) |

`occ files_antivirus:status` (Nextcloud ≥ 29) or uploading the
[EICAR test file](https://www.eicar.org/download-anti-malware-testfile/)
confirms the connection.

## Using the scanner from other machines

Enable **LAN access** (opens 3310/tcp in the node firewall). The clamd protocol
has no authentication or encryption, so do this only in a trusted network and
restrict the source addresses in the firewall if needed. Files are scanned as a
stream (`INSTREAM`); `SCAN <path>` only works for paths inside the container.

```
# any Linux/macOS/Windows machine with the ClamAV client package, no local signatures needed
printf 'TCPAddr <node address>\nTCPSocket 3310\n' > clamd-remote.conf
clamdscan --stream --config-file=clamd-remote.conf --fdpass=no file.pdf
```

Minimal Python client:

```python
import socket, struct, sys
host, path = sys.argv[1], sys.argv[2]
s = socket.create_connection((host, 3310)); s.sendall(b"zINSTREAM\0")
with open(path, "rb") as f:
    while chunk := f.read(65536):
        s.sendall(struct.pack("!I", len(chunk)) + chunk)
s.sendall(struct.pack("!I", 0)); print(s.recv(4096).decode().strip("\0\n"))
```

Mail filters (rspamd, Amavis), proxies (c-icap), Samba `vfs_virusfilter` and
other software with a clamd integration use host `<node address>`, port 3310.

## Web / REST front end

Set a host name in the *Web / REST front end* section (and how users
log in, see below) and the module publishes, through Traefik with TLS:

| | |
| --- | --- |
| `https://<host>/` | upload form (one or more files, results as a table) |
| `POST /api/v1/scan` | multipart field `file` (several allowed) or a raw body with header `X-Filename`; JSON: `{"results":[{"file","size","result":"clean|infected|error","signature","detail"}],"infected":bool,"errors":bool}` |
| `GET /api/v1/version` | engine and signature database version |
| `GET /api/v1/health` | `{"clamd":"up"}` / 503 — no login, for monitoring |
| `GET /favicon.ico` | the ClamAV logo — no login |

```
curl -u scan:secret -F file=@invoice.pdf -F file=@setup.exe https://scan.example.org/api/v1/scan
```

Everything except `/api/v1/health` requires a login, chosen under *Login*:

- **Directory users**, from one of two sources:
  - **User domain of this cluster** (recommended) — any user of an NS8 user
    domain (Active Directory or OpenLDAP). The module binds to the domain and
    reaches it through the node's ldapproxy; no service account is entered or
    stored, password changes and DC moves are followed automatically. The
    group is chosen from a list read from the domain.
  - **LDAP server of its own** (advanced) — URL (`ldaps://` or `ldap://` with
    optional StartTLS), certificate check (on by default, system CAs), type
    (Active Directory or OpenLDAP posixAccount), base DN, bind DN and password,
    optional login attribute. The bind password is kept in
    `state/passwords.env`, never in the module environment. Only needed for a
    directory that is not a user domain: NS8 can also add an external AD/LDAP
    as a user domain, which is then offered in the first choice.

  In both cases the login can be limited to the members of one group (nested
  groups count in AD; for a server of its own also a group DN).
- **Own login name and password** — one account stored in the module.
- **No login** — anyone who reaches the host name may scan; combine it with
  the allow-list of client networks, which Traefik enforces.

The browser gets a login page with a session cookie (8 hours, log out button);
scripts use HTTP basic authentication with the same credentials. Uploads are
streamed to clamd and never stored; the maximum size follows *Maximum stream
length*. The front end is a small Python service (standard library plus ldap3)
(`web/app.py`) shipped as `ghcr.io/tebbiworld/clamav-web`, running in the host
network on `127.0.0.1:<allocated port>`.

## Backup

`state/environment`, `state/passwords.env` (password hash of the local login,
bind password of an LDAP server of its own) and `state/clamav.env`. The signature database is not
backed up on purpose; after a restore the container downloads it again.

## Notes

* `update-module` restarts the daemon, so a new pinned ClamAV version runs right
  after the update.
* `runagent -m clamav1 podman logs clamav` shows freshclam and clamd output.
* Every scan of the web/REST front end writes one line to the journal, e.g.
  `event="scan" result="infected" file="invoice.pdf" size="18432" signature="Win.Test.EICAR_HDB-1" user="alice" src="192.0.2.10"`
  - ready for a Loki query such as `{...} |= "event=\"scan\"" | logfmt | result="infected"`.
* The settings page warns when the signature database is older than two days
  (freshclam could not update it).
* The directory login code is shared with ns8-idevice-backup and kept
  identical there: `web/ldapauth.py` (login), `imageroot/pypkg/ldapsettings.py`
  (settings, `ldap.env`, group list) and `ui/src/components/LdapLogin.vue`.
* Test from the node: `printf 'zPING\0' | python3 -c "import socket,sys; s=socket.create_connection(('127.0.0.1',3310)); s.sendall(sys.stdin.buffer.read()); print(s.recv(16))"` → `b'PONG\x00'`.
* The module logo is the official ClamAV mascot (© Cisco Systems, trademark), used unmodified to identify the packaged software.
* ClamAV is GPL-2.0; the image is published by Cisco Talos and pulled at
  runtime. The module's own code is GPL-3.0-or-later.
