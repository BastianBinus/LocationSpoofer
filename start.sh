#!/usr/bin/env bash
# Startet LocationSpoofer (Linux). Beim ersten Aufruf wird die virtuelle Umgebung eingerichtet.
# Argumente werden durchgereicht, z. B.: ./start.sh -v   oder   ./start.sh --lan
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"

if [[ ! -x .venv/bin/locationspoofer ]]; then
    echo "Erster Start: richte .venv ein …"
    python3 -m venv .venv
    if ! .venv/bin/pip install -e .; then
        echo "Installation fehlgeschlagen. Fehlen Build-Werkzeuge? sudo apt install build-essential python3-dev" >&2
        exit 1
    fi
fi

# usbmuxd startet normalerweise per udev beim Einstecken des iPhones; falls nicht, hier nachhelfen.
if command -v systemctl >/dev/null && ! systemctl is-active --quiet usbmuxd; then
    echo "Starte usbmuxd (sudo) …"
    sudo systemctl start usbmuxd || echo "Warnung: usbmuxd ließ sich nicht starten." >&2
fi

exec .venv/bin/locationspoofer "$@"
