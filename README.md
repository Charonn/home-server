# Home server setup stuff
Uses ansible to setup a home server with docker and these containers:
- traefik
- paperless
- nextcloud
- grafana
- prometheus
- mariadb
- redis
- dawarich (self-hosted location history, with its own PostGIS + Redis)
- steam-headless (remote gaming: Steam + Sunshine/Moonlight, on `ryzen_home_server` LXC)

## Apply to home-server
```bash
ansible-playbook site.yml --private-key=~/.ssh/* --tags home-server --diff --limit proxmox_home_server
```

## Dawarich (self-hosted Location History)

Deploys [Freika/dawarich](https://github.com/Freika/dawarich) (Google Timeline
replacement: location tracking + map) to the home server as a
`roles/home-server` task (`--tags dawarich`, `ryzen_home_server`), fully
self-contained in `/opt/dawarich`:

- `dawarich` (`freikin/dawarich:1.19.0`, pinned) — Rails web app + embedded
  Sidekiq (one container, upstream default since 1.x)
- `dawarich_db` (`postgis/postgis:17-3.5-alpine`) — Dawarich **requires
  PostGIS**, so it does NOT use the shared `postgres` stack
- `dawarich_redis` (`redis:8-alpine`) — dedicated instance, no queue
  contamination with nextcloud/immich on the shared redis
- `ts-dawarich` — Tailscale sidecar (same pattern as paperless/beszel/pgadmin):
  shares the app network namespace, serves the UI at
  `https://dawarich.shark-scylla.ts.net` (magicDNS, auto certs) and exposes
  tracking endpoints (`/api/v1/...`) for the Dawarich Android/iOS app or
  OwnTracks/Overland to that URL. HTTP port 3000 is also published on the box.

Apply:
```bash
ansible-playbook site.yml --tags dawarich --diff --limit ryzen_home_server
```

First login (upstream default, change immediately):
`demo@dawarich.app` / `safepassword`.

Secrets (vault only, `group_vars/ryzen_home_server/dawarich_vault.yml`,
read with `.vault_pass`):
- `dawarich_secret_key_base_vault` — Rails SECRET_KEY_BASE (`openssl rand -hex 64`)
- `dawarich_db_password_vault` — bundled PostGIS superuser password

Tunables (plain, `group_vars/ryzen_home_server/all.yml`): `dawarich_version`
(bump deliberately, releases can be breaking), `dawarich_host_path`,
`dawarich_public_port`, `dawarich_application_hosts`, `dawarich_timezone`.

Backup gap (deliberate, review point): the daily `backup.sh` Borg run dumps
MariaDB only — the Dawarich PostGIS DB in `/opt/dawarich/db` is **not** in the
backup chain yet. Add a `pg_dump` step there before relying on the data.

## Steam Headless (remote gaming)

Deployed as `josh5/steam-headless` to the `home-server` LXC (id 102) on the
`proxmox_ryzen` host with NVIDIA GTX 1050 Ti GPU passthrough. Provides:

- **Moonlight/Sunshine** for low-latency game streaming (enabled)
- noVNC web UI on `http://home-server.shark-scylla.ts.net:8083` and via the
  Tailscale sidecar at `https://steam-headless.shark-scylla.ts.net`
- Steam Remote Play (host networking)

Note: the Tailscale sidecar serves the **web UI** only. Moonlight streaming
requires direct UDP to the LXC, so it connects to
`home-server.shark-scylla.ts.net` (or the LAN IP), not via the sidecar.

The playbook fully automates the setup:
1. `proxmox_host` role (runs on `proxmox_ryzen`): ensures the `home-server` LXC
   (id 102) exists — **only if it is missing** (never recreated) —, applies
   `/dev/fuse` + `/dev/uinput` device passthrough and cgroup device allows to
   `/etc/pve/lxc/102.conf` and restarts the container **only when this config
   changed** (needed once).
2. `home-server` role on the LXC: registers the NVIDIA container runtime with
   Docker (`nvidia-ctk runtime configure`), deploys the compose stack.

Secrets (desktop password, Sunshine credentials, paths, image version) are in
the vault, mapped via `group_vars/ryzen_home_server/all.yml`.

Apply the LXC provisioning (device passthrough config on the Proxmox host):
```bash
ansible-playbook site.yml --tags home-server --diff --limit proxmox_ryzen
```
Apply the Steam Headless application on the LXC:
```bash
ansible-playbook site.yml --tags steam-headless --diff --limit ryzen_home_server
```
Dry run (no changes applied):
```bash
ansible-playbook site.yml --check --diff --limit proxmox_ryzen,ryzen_home_server
```


## En/Decrypt secrets
Secret is stored in .vault_pass
```bash
ansible-vault encrypt group_vars/all/default.vault.yml
ansible-vault decrypt group_vars/all/default.vault.yml
```

## Idle-Power-Reduktion (Rolle `idle_power`, Ziel: `proxmox_ryzen`)

Reduziert den Idle-Verbrauch des PVE-Towers (Ryzen 7 5700G):
CPU-Governor (`schedutil`, persistente systemd-Unit), ZFS-`txg_timeout`
(1800 s, Gate bewusst erzwungen — Marcel-OK), HDD-Spin-Down via `hdparm -B/-S`
(Backup 10 min, Daten 20 min, Boot nie), smartd mit `-n standby,q`
(kein Wecken der HDDs durch den 30-min-Poll). Details: Karte t_15bbb646.

Trockenlauf:
```bash
ansible-playbook site.yml --tags idle_power --limit proxmox_ryzen --check --diff
```

Anwenden:
```bash
ansible-playbook site.yml --tags idle_power --limit proxmox_ryzen
```

Wichtige Defaults (Rolle `roles/idle_power/defaults/main.yml`):
- `idle_power_pool_roles` Pool-Namen aus `zpool list` setzen (backup/boot/data)
- `idle_power_txg_force` nur anpassen, wenn das Crash-Fenster akzeptabel ist

### Backup-Interaktion (verifiziert 2026-10-10)
Das tägliche Backup (`/root/backup/backup.sh` auf der home-server-VM,
01:05, Borg + rclone + MariaDB-Dumps) beschreibt über die VM-Disk-
Passthroughs die Pools **HDD-2TB** (Borg-Repo, `sdb`) und **HDD-Big**
(VM-Rootvol, `/opt`). Ablauf: 01:05 Wecken -> Backup (letzte Dauer
12:32 min) -> +10/20 min parkt der Pool wieder; Rest der Nacht geparkt.
`pool_status.sh` (20:00, Telegram-Report) liest nur RAM-Metadaten und
weckt nicht. Konfliktfrei. smartd weckt dank `-n standby,q` nicht beim
30-min-Poll; Tests laufen, sobald die Platte eh wach ist.

Pool-Rollen sind als Defaults gesetzt: HDD-2TB=backup (10 min),
HDD-Big=data (20 min), SSD-Pool=boot (nie).