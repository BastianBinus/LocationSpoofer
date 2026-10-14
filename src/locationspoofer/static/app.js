"use strict";

const POLL_INTERVAL_MS = 3000;
const STORAGE_KEY = "locationspoofer.target";
const GERMANY = { latitude: 51.1657, longitude: 10.4515 };

const els = {
  form: document.getElementById("teleport-form"),
  coordinates: document.getElementById("coordinates"),
  teleport: document.getElementById("teleport"),
  reset: document.getElementById("reset"),
  connect: document.getElementById("connect"),
  dot: document.getElementById("status-dot"),
  device: document.getElementById("device-text"),
  active: document.getElementById("active-text"),
  message: document.getElementById("message"),
};

let busy = false;
let lastStatus = null;
let lastServerError = null;
let target = loadTarget();

const css = getComputedStyle(document.documentElement);
const map = L.map("map").setView(
  target ? [target.latitude, target.longitude] : [GERMANY.latitude, GERMANY.longitude],
  target ? 14 : 6,
);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>-Mitwirkende',
}).addTo(map);

const targetMarker = L.circleMarker([0, 0], {
  radius: 10, color: css.getPropertyValue("--accent").trim(), weight: 3, fillOpacity: 0.15,
});
const activeMarker = L.circleMarker([0, 0], {
  radius: 7, color: "#ffffff", weight: 3, fillColor: css.getPropertyValue("--active").trim(), fillOpacity: 1,
}).bindTooltip("Simulierter Standort");

function formatCoordinates({ latitude, longitude }) {
  return `${latitude.toFixed(6)}, ${longitude.toFixed(6)}`;
}

function parseCoordinates(text) {
  const match = text.trim().match(/^(-?\d{1,3}(?:\.\d+)?)\s*[,;\s]\s*(-?\d{1,3}(?:\.\d+)?)$/);
  if (!match) return null;
  const latitude = Number(match[1]);
  const longitude = Number(match[2]);
  if (Math.abs(latitude) > 90 || Math.abs(longitude) > 180) return null;
  return { latitude, longitude };
}

function loadTarget() {
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEY));
    return value && Number.isFinite(value.latitude) && Number.isFinite(value.longitude) ? value : null;
  } catch {
    return null;
  }
}

function setTarget(value, { updateInput = true } = {}) {
  target = value;
  if (updateInput) els.coordinates.value = formatCoordinates(value);
  els.coordinates.removeAttribute("aria-invalid");
  targetMarker.setLatLng([value.latitude, value.longitude]).addTo(map);
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  } catch {
    // Ohne Speicher geht nur das Merken des letzten Ziels verloren.
  }
}

function showMessage(text, kind = "error") {
  els.message.hidden = !text;
  els.message.textContent = text || "";
  els.message.dataset.kind = kind;
}

function setBusy(value, info) {
  busy = value;
  for (const button of [els.teleport, els.reset, els.connect]) button.disabled = value;
  if (value && info) showMessage(info, "info");
}

function describeDetail(detail, status) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return "Ungültige Koordinaten.";
  return `Anfrage fehlgeschlagen (HTTP ${status}).`;
}

async function api(method, path, body) {
  const response = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(describeDetail(data.detail, response.status));
  return data;
}

function render(status) {
  lastStatus = status;
  els.dot.dataset.state = status.state;

  if (status.state === "connected" && status.device) {
    const { name, ios_version: ios } = status.device;
    els.device.textContent = `${name || "iPhone"} · iOS ${ios}`;
  } else if (status.state === "connecting") {
    els.device.textContent = "Verbinde …";
  } else {
    els.device.textContent = "Nicht verbunden";
  }
  els.connect.hidden = status.state !== "disconnected";

  if (status.location) {
    els.active.innerHTML = "";
    els.active.append("Simuliert: ");
    const strong = document.createElement("strong");
    strong.textContent = formatCoordinates(status.location);
    els.active.append(strong);
    activeMarker.setLatLng([status.location.latitude, status.location.longitude]).addTo(map);
  } else {
    els.active.textContent = status.state === "connected" ? "Echter Standort aktiv" : "Keine Simulation aktiv";
    activeMarker.remove();
  }

  // Nur bei geändertem Serverfehler überschreiben, damit lokale Hinweise nicht beim nächsten Poll verschwinden.
  if (!busy && status.error !== lastServerError) showMessage(status.error);
  lastServerError = status.error;
}

async function run(action, info) {
  if (busy) return;
  setBusy(true, info);
  try {
    render(await action());
    showMessage(null);
  } catch (error) {
    showMessage(error.message);
    await refresh();
  } finally {
    setBusy(false);
  }
}

async function refresh() {
  try {
    render(await api("GET", "/api/status"));
  } catch (error) {
    showMessage(`Server nicht erreichbar: ${error.message}`);
  }
}

const CONNECT_INFO =
  "Verbinde … Beim ersten Mal wird das Developer Disk Image geladen, das kann eine Minute dauern. " +
  "Falls das iPhone fragt: „Vertrauen“ tippen.";

function connectInfo() {
  return lastStatus && lastStatus.state === "connected" ? null : CONNECT_INFO;
}

els.form.addEventListener("submit", (event) => {
  event.preventDefault();
  const value = parseCoordinates(els.coordinates.value);
  if (!value) {
    els.coordinates.setAttribute("aria-invalid", "true");
    showMessage("Format: Breite, Länge – z. B. 48.13743, 11.57549");
    return;
  }
  setTarget(value);
  run(() => api("POST", "/api/location", value), connectInfo());
});

els.coordinates.addEventListener("input", () => {
  const value = parseCoordinates(els.coordinates.value);
  if (value) {
    setTarget(value, { updateInput: false });
    map.panTo([value.latitude, value.longitude]);
  }
});

els.reset.addEventListener("click", () => run(() => api("DELETE", "/api/location"), connectInfo()));
els.connect.addEventListener("click", () => run(() => api("POST", "/api/connect"), CONNECT_INFO));
map.on("click", (event) => setTarget({ latitude: event.latlng.lat, longitude: event.latlng.lng }));

if (target) setTarget(target);
refresh();
setInterval(() => {
  if (!busy && document.visibilityState === "visible") refresh();
}, POLL_INTERVAL_MS);
