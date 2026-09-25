# Changelog

## Unreleased

### Changed

- **Settings page shows the Nextcloud values per instance.** It finds every Nextcloud of the cluster and shows the node it runs on with the *Host* to enter: `10.0.2.2` on the same node, the VPN address of this node otherwise. After ClamAV or Nextcloud moves to another node the value follows. Before, the page always showed the same-node address first, which is wrong for a Nextcloud on another node.
- Addresses are shown without `:3310`. Nextcloud has separate *Host* and *Port* fields, and pasting `address:3310` into *Host* breaks the connection.

## 1.3.0 — 2026-09-25

### Added

- **Login with the users of a user domain.** The web front end and the REST API can check logins against an NS8 user domain (Active Directory or OpenLDAP), optionally only for the members of one group (nested groups count in AD). The module binds to the domain and reaches it through the node's ldapproxy; no service account has to be entered. The connection settings are read again on every start and after a change of the domain.
- **Login page instead of the browser dialog.** Browsers get a login form with a session cookie (HttpOnly, Secure, SameSite=Strict, 8 hours) and a log out button. Scripts keep using HTTP basic authentication with the same credentials.
- **Login can be switched off**, for a scanner that is only reachable from trusted networks; the settings page warns when no client networks are set.

### Changed

- The *Login* setting has three choices: users of a user domain, own login name and password (the previous behaviour, still the default), no login.
- New authorization `cluster:accountconsumer` to bind the user domain.

## 1.2.0 — 2026-09-19

Alignment with the NethServer module conventions (NethServer/agents skills).

### Changed

- **Secrets moved out of the module environment.** The password hash of the web front end is now kept in `state/passwords.env` (mode 0600) instead of `state/environment`, which NS8 mirrors to Redis in plain text. Existing installations are migrated on update; the password does not change. The generated `clamav-web.env` is private (0600).
- **Working restore.** New `restore-module` steps re-apply every setting on the restored instance, including the web front end and its password; the backup now includes the secrets file.
- `update-module` only restarts a running instance.

### Added

- Robot Framework tests (install, update from the previous release, backup and restore) run on real NS8 nodes through `stephdl/ns8-ci-actions`.

### Platform integration

- **Clone and move.** New `clone-module` step (a link to the restore step): a cloned or moved instance gets its route and settings back instead of coming up unconfigured. The settings are read from the source instance, including those a new instance starts with a default for.
- `org.nethserver.max-per-node=1`: the module owns fixed ports on the node, a second instance on the same node is refused at install time instead of failing at start.
- Release notes are linked from the software centre (`relnotes_url`).

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
