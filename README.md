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

### Backup-Interaktion (vzdump)
Das Backup weckt die Platten im Backup-Pool kurzzeitig pro Durchlauf —
das ist intendiert (Spin-Down = Idle-Modus zwischen Backups, kein
Dauer-Offline). Das `idle-spin.service` re-appliziert nach jedem Boot;
keine Interaktion mit laufenden Backups. smartd weckt dank
`-n standby,q` **nicht** beim 30-min-Poll — Tests laufen, sobald die
Platte eh wach ist (z. B. Backup-Fenster).
