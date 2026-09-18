<!--
First community post for the NS8 ClamAV module, written in the style
of https://community.nethserver.org/t/ns8-forgejo-testing/28554 (first post).
Paste into a new topic on community.nethserver.org, category "App", tag "ns8".
Fill in the wiki link once the page is published.
-->

# NS8 ClamAV (testing)

Hi all,

I've built an NS8 module for [ClamAV](https://www.clamav.net/) — the ClamAV antivirus daemon, run as a scan service for the whole cluster with a small web/REST front end.

It's in my community repository. To try it, add the repo once:

```
api-cli run add-repository --data '{"name":"tebbiworld","url":"https://raw.githubusercontent.com/tebbiworld/ns8-repo/main/ns8/updates/","status":true,"testing":false}'
```

then install **ClamAV** from the Software Center. (Or straight from the image: `add-module ghcr.io/tebbiworld/clamav:latest 1`.)

What it does:

* Runs clamd from the official ClamAV image on TCP 3310, reachable from every node over the cluster VPN
* Ready-made integration for Nextcloud's *Antivirus for files* app (Daemon host mode), and works with ecoDMS, Samba, mail filters or anything else that speaks the clamd protocol
* Optional web/REST front end behind Traefik: an upload form plus `POST /api/v1/scan`, and version/health endpoints for monitoring
* freshclam keeps the signature database up to date; settings for max file/scan/stream size and the daily update-check count
* One instance per node; the Mail module's own clamd (on 11330) doesn't clash

A few things to know:

* clamd keeps the signatures in RAM — plan roughly **1–1.5 GB** for the node.
* The clamd protocol has no authentication or encryption. LAN access is off by default; enable it only in a trusted network, and restrict source addresses in the firewall if needed.
* The web front end needs HTTP basic auth (everything except the health endpoint); uploads are streamed to clamd and never stored.
* The signature database isn't in the backup on purpose — it's just re-downloaded after a restore.

It's running nicely here scanning Nextcloud uploads, but I'd like to know how it holds up in other setups — if you wire it into your own scanner or module, do let me know.

Docs: NethServer wiki (tebbiworld repository) · Source: [github.com/tebbiworld/ns8-clamav](https://github.com/tebbiworld/ns8-clamav)

Thanks!

*Category: App · Tags: ns8*
