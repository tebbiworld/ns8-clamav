# Changelog

## 1.2.0 — 2026-09-19

Alignment with the NethServer module conventions (NethServer/agents skills).

### Changed

- **Secrets moved out of the module environment.** The password hash of the web front end is now kept in `state/passwords.env` (mode 0600) instead of `state/environment`, which NS8 mirrors to Redis in plain text. Existing installations are migrated on update; the password does not change. The generated `clamav-web.env` is private (0600).
- **Working restore.** New `restore-module` steps re-apply every setting on the restored instance, including the web front end and its password; the backup now includes the secrets file.
- `update-module` only restarts a running instance.

### Added

- Robot Framework tests (install, update from the previous release, backup and restore) run on real NS8 nodes through `stephdl/ns8-ci-actions`.

## 1.1.0 — 2026-09-14

### Added

- **Web / REST front end** (optional, enabled by a host name): an upload form
  and a JSON API behind Traefik (TLS, Let's Encrypt, optional client-network
  allow-list) with HTTP basic authentication. `POST /api/v1/scan` streams the
  uploaded file(s) to clamd and answers `clean` / `infected` + signature /
  `error` per file; `GET /api/v1/version`; `GET /api/v1/health` (no login).
  Built from `web/` as `ghcr.io/tebbiworld/clamav-web`, standard library only.
- Instances created with 1.0.0 get a TCP port allocated for the front end on
  the first save.

## 1.0.0 — 2026-09-13

- Initial release: ClamAV daemon (official image, pinned) on TCP 3310 in the
  host network, reachable from modules on the same node and via the cluster
  VPN; optional LAN access through the node firewall; scan limits and freshclam
  schedule as settings; status (engine/signature version) on the settings page.
