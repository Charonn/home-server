# Home server setup stuff
Uses ansible to setup a home server with docker and these containers:
- traefik
- paperless
- nextcloud
- grafana
- prometheus
- no-ip
- mariadb
- redis

## Apply to home-server
```bash
ansible-playbook site.yml --private-key=~/.ssh/* --tags home-server --diff --limit proxmox_home_server
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
(3600 s, Gate gegen VM-Datenpools), HDD-Spin-Down via `hdparm -B/-S`
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