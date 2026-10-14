# LocationSpoofer

Lokale Web-UI mit Karte, die den GPS-Standort eines per USB verbundenen iPhones setzt (Teleport) und wieder
zurücksetzt. Kein Jailbreak und keine App auf dem iPhone nötig.

**Funktionsweise:** Der Rechner nutzt denselben Developer-Dienst wie Xcode (`LocationSimulation` über DVT).
Die Gerätekommunikation übernimmt [pymobiledevice3](https://github.com/doronz88/pymobiledevice3):

- Der Tunnel zum iPhone läuft als Userspace-Tunnel und braucht weder Admin- noch Root-Rechte.
- Das Developer Disk Image wird automatisch geladen und eingebunden. Ab iOS 27 ist das der Cryptex1-DDI.

> **Stand:** Mit Unit-Tests und Smoke-Tests ohne Gerät geprüft, aber **noch nicht an einem echten iPhone**.
> Rückmeldungen vom ersten Test am Gerät bitte mit `locationspoofer -v` erzeugen.

## Voraussetzungen

| | |
|---|---|
| iPhone | iOS 17.4 oder neuer (Zielsystem: iOS 27), USB-Kabel, Entwicklermodus (siehe unten) |
| Rechner | **Windows oder Linux nativ**, Python 3.11 oder neuer |
| Windows | iTunes, das den „Apple Mobile Device Service“ mitbringt. Ob die App „Apple-Geräte“ allein reicht, ist nicht geprüft. |
| Linux | `usbmuxd`, `python3-venv`, ab Python 3.14 zusätzlich Compiler und Header (zwei Abhängigkeiten haben dort keine fertigen Wheels): `sudo apt install usbmuxd python3-venv build-essential python3-dev` |
| Netz | Internet für die Karte, den einmaligen DDI-Download und die DDI-Signatur durch Apple |

**WSL2 wird nicht empfohlen.** Das USB-Gerät müsste per `usbipd` durchgereicht werden und usbmuxd in WSL laufen.
Das ist ungetestet. Unter Windows nativ entfällt das.

## Installation

```bash
git clone https://github.com/bastianbinus/locationspoofer.git
cd locationspoofer
python -m venv .venv
# Windows: .venv\Scripts\activate    Linux: source .venv/bin/activate
pip install -e .
```

## Start

```bash
locationspoofer          # oder: python -m locationspoofer
```

Der Browser öffnet `http://127.0.0.1:8765/`. Optionen: `--port`, `--udid` (bei mehreren Geräten),
`--no-browser`, `-v` (ausführliches Logging) und `--lan` (siehe unten).

### Erste Einrichtung am iPhone

1. iPhone per USB anschließen und entsperren, in der UI auf **Verbinden** klicken.
2. Bei „Diesem Computer vertrauen?“ **Vertrauen** wählen und den Code eingeben.
3. Ist der Entwicklermodus aus, meldet die UI das und schaltet den Schalter in den Einstellungen frei.
   Dann **Einstellungen › Datenschutz & Sicherheit › Entwicklermodus** einschalten, neu starten und
   nach dem Entsperren **Aktivieren** wählen.
4. Erneut verbinden. Beim ersten Mal wird das Developer Disk Image heruntergeladen und von Apple für dein
   Gerät signiert. Das kann etwas dauern. Später läuft es aus dem Cache.

## Bedienung

- **Ziel setzen:** auf die Karte klicken oder Koordinaten einfügen (`48.13743, 11.57549`, z. B. aus Google Maps).
- **Teleportieren:** setzt den Standort und verbindet bei Bedarf automatisch.
- **Echter Standort:** beendet die Simulation.
- **Strg+C** im Terminal beendet den Server und setzt vorher den echten Standort zurück.

### Steuerung aus Safari auf dem iPhone (`--lan`)

`locationspoofer --lan` macht die UI im lokalen Netz erreichbar und gibt einen Link mit Zugangstoken aus.
Diesen Link auf dem iPhone öffnen. Ohne Token antwortet die API mit 401.

- Die Verbindung ist **unverschlüsselt (HTTP)**. Nur in vertrauenswürdigen Netzen verwenden.
- Der PC muss weiterlaufen, und das iPhone muss per USB angeschlossen bleiben.

## Grenzen

- **Die Simulation hält nur, solange die Verbindung besteht.** Der Server muss laufen und das Kabel stecken.
  Wird das Kabel getrennt, zeigt die UI den Verbindungsverlust an.
- **Nur USB.** Eine WLAN-Verbindung wird noch nicht unterstützt.
- **Find My** zeigt laut Berichten unter iOS 26 nach kurzer Zeit wieder die echte Position.
- **Apps und Spiele** mit Standortprüfung (z. B. Pokémon GO) verbieten das in ihren Nutzungsbedingungen.
  Es drohen Kontosperren.

## Fehlerbehebung

| Meldung | Lösung |
|---|---|
| USB-Dienst für iPhones läuft nicht | Windows: iTunes installieren. Linux: `sudo systemctl start usbmuxd` |
| Kein iPhone per USB gefunden | Kabel prüfen (Datenkabel?), iPhone entsperren |
| „Vertrauen“ bestätigen | Dialog auf dem iPhone bestätigen, erneut verbinden |
| Entwicklermodus ist aus | siehe Erste Einrichtung, Schritt 3 |
| Developer Disk Image ließ sich nicht installieren | `pip install -U "pymobiledevice3<12"`, erneut versuchen |

Für Details `locationspoofer -v` starten. Das Log enthält dann die vollständigen Tracebacks.

## Entwicklung

```bash
pip install -e ".[dev]"
pytest
```

Aufbau:

- `src/locationspoofer/device.py`: Gerätezugriff, Fehlerübersetzung, Zustandsverwaltung
- `src/locationspoofer/server.py`: HTTP-API mit Host-, CSRF- und Token-Prüfung
- `src/locationspoofer/static/`: Web-UI

## Lizenzen

- pymobiledevice3 steht unter **GPL-3.0-or-later**. Wer dieses Projekt weitergibt, muss das berücksichtigen.
- Leaflet 1.9.4 liegt unter `static/vendor/leaflet/` bei. Die BSD-2-Lizenz liegt im selben Ordner.
- Kartendaten stammen von © OpenStreetMap-Mitwirkenden.
