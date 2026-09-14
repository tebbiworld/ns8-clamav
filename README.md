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
There is no HTTP/REST layer or web form yet.

## Backup

`state/environment` and `state/clamav.env` only. The signature database is not
backed up on purpose; after a restore the container downloads it again.

## Notes

* `update-module` restarts the daemon, so a new pinned ClamAV version runs right
  after the update.
* `runagent -m clamav1 podman logs clamav` shows freshclam and clamd output.
* Test from the node: `printf 'zPING\0' | python3 -c "import socket,sys; s=socket.create_connection(('127.0.0.1',3310)); s.sendall(sys.stdin.buffer.read()); print(s.recv(16))"` → `b'PONG\x00'`.
* The module logo is the official ClamAV mascot (© Cisco Systems, trademark), used unmodified to identify the packaged software.
* ClamAV is GPL-2.0; the image is published by Cisco Talos and pulled at
  runtime. The module's own code is GPL-3.0-or-later.
