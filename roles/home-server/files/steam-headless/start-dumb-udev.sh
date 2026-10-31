#!/usr/bin/env bash
###
# File: start-dumb-udev.sh
# Patched for the home-server LXC:
#   The upstream script runs `supervisorctl restart xorg` every time
#   Sunshine's virtual input devices (re)appear. Sunshine creates those pads
#   on every startup, so this restarts Xorg in a loop that kills Sunshine's
#   capture -> crash loop (upstream issue #231). The restart is disabled
#   below; the node sync still runs so Xorg/uinput keep working.
###
set -e

state_dir=/run/udev-input-fix

# CATCH TERM SIGNAL:
_term() {
    kill -TERM "${sync_pid:-}" 2>/dev/null
    kill -TERM "${dumb_udev_pid:-}" 2>/dev/null
    kill -TERM "${udevd_pid:-}" 2>/dev/null
}
trap _term SIGTERM SIGINT

sync_input_nodes() {
    mkdir -p /dev/input

    for sys in /sys/class/input/*/dev; do
        [[ -f "${sys}" ]] || continue

        node=$(basename "$(dirname "${sys}")")
        path="/dev/input/${node}"
        [[ -e "${path}" ]] && continue

        IFS=: read -r major minor < "${sys}"
        mknod "${path}" c "${major}" "${minor}" 2>/dev/null || continue
        chmod 0660 "${path}" 2>/dev/null || true
        chgrp input "${path}" 2>/dev/null || true
    done
}

sunshine_inputs_present() {
    for name_file in /sys/class/input/*/device/name; do
        [[ -f "${name_file}" ]] || continue
        case "$(cat "${name_file}" 2>/dev/null || true)" in
            *passthrough*|Sunshine*)
                return 0
                ;;
        esac
    done
    return 1
}

# EXECUTE PROCESS:
# If a real udev daemon can be started in this restricted environment, prefer
# that over dumb-udev. This gives us /run/udev/control and keeps the existing
# Xorg startup ordering intact, even when /sys is mounted read-only.
mkdir -p "${state_dir}"
if command -v udevd &>/dev/null; then
    unshare --net udevd --daemon &>/dev/null || true
else
    unshare --net /lib/systemd/systemd-udevd --daemon &>/dev/null || true
fi

if pgrep -x systemd-udevd >/dev/null 2>&1; then
    udevd_pid=$(pgrep -xo systemd-udevd || true)
fi

dumb-udev &
dumb_udev_pid=$!

while true; do
    sync_input_nodes

    if sunshine_inputs_present; then
        if [[ ! -e "${state_dir}/xorg-restarted" ]]; then
            # PATCHED (upstream issue #231): the original script restarts Xorg
            # here, which kills Sunshine's X11 capture and crash-loops the
            # stack. Disabled - the input nodes are synced above and Sunshine
            # keeps running.
            sleep 2
            sync_input_nodes
            true # disabled: supervisorctl restart xorg
            : > "${state_dir}/xorg-restarted"
        fi
    else
        rm -f "${state_dir}/xorg-restarted"
    fi

    sleep 1
done &
sync_pid=$!

# WAIT FOR CHILD PROCESS:
wait "$dumb_udev_pid"