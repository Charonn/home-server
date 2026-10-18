# Home server setup stuff
Uses ansible to setup a home server with docker and these containers:
- traefik
- paperless
- nextcloud
- grafana
- prometheus
- mariadb
- redis
- steam-headless (remote gaming: Steam + Sunshine/Moonlight, on `ryzen_home_server` LXC)

## Apply to home-server
```bash
ansible-playbook site.yml --private-key=~/.ssh/* --tags home-server --diff --limit proxmox_home_server
```

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