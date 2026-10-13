from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import json
import threading
import time
import webbrowser

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
START_PORT = 10000
MAX_PORT = 10100
ALLOWED_RANGES = {25, 50, 100, 150, 250}
PROVIDERS = [
    ("ADSB One", "https://api.adsb.one/v2/point", "point-v2"),
    ("Airplanes.live", "https://api.airplanes.live/v2/point", "point-v2"),
    ("ADSB.lol", "https://api.adsb.lol/v2/point", "point-v2"),
    ("ADSB.fi", "https://opendata.adsb.fi/api/v3/lat", "adsbfi-v3"),
]
PROVIDER_COOLDOWN_UNTIL = {}
PROVIDER_COOLDOWN_STATUS = {}
PROVIDER_LAST_REQUEST_AT = {}
PROVIDER_MIN_INTERVAL_SECONDS = {"ADSB.fi": 1.1}


class ApiProblem(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


def query_provider(name, base, lat, lon, dist, fmt="point-v2"):
    now = time.time()
    min_interval = PROVIDER_MIN_INTERVAL_SECONDS.get(name, 0)
    wait = min_interval - (now - PROVIDER_LAST_REQUEST_AT.get(name, 0))
    if wait > 0:
        return None, {"provider": name, "status": 429, "reason": f"limite prudenziale: riprova tra {int(wait + 0.99)} s"}
    if min_interval:
        PROVIDER_LAST_REQUEST_AT[name] = now
    if fmt == "adsbfi-v3":
        # ADSB.fi v3 uses /lat/{lat}/lon/{lon}/dist/{dist}.
        url = f"{base}/{lat}/lon/{lon}/dist/{dist}"
    else:
        url = f"{base}/{lat}/{lon}/{dist}"
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=10) as response:
            status = response.status
            content_type = response.headers.get("Content-Type", "sconosciuto")
            raw = response.read().decode("utf-8", "replace")
    except HTTPError as error:
        cooldown_seconds = 600 if error.code == 403 else 300 if error.code == 429 else 60
        PROVIDER_COOLDOWN_UNTIL[name] = time.time() + cooldown_seconds
        PROVIDER_COOLDOWN_STATUS[name] = error.code
        return None, {"provider": name, "status": error.code, "reason": "accesso rifiutato" if error.code == 403 else "limite richieste raggiunto" if error.code == 429 else f"HTTP {error.code}"}
    except (URLError, TimeoutError, OSError) as error:
        return None, {"provider": name, "status": 0, "reason": "timeout/errore di connessione"}

    try:
        data = json.loads(raw)
    except ValueError:
        PROVIDER_COOLDOWN_UNTIL[name] = time.time() + 300
        PROVIDER_COOLDOWN_STATUS[name] = status or 502
        return None, {"provider": name, "status": status, "reason": f"risposta non JSON ({content_type})"}
    if status < 200 or status >= 300:
        return None, {"provider": name, "status": status, "reason": f"HTTP {status}"}
    aircraft = data.get("ac") if isinstance(data, dict) else None
    if not isinstance(aircraft, list) and isinstance(data, dict):
        aircraft = data.get("aircraft")
    if not isinstance(aircraft, list):
        fields = ", ".join(list(data.keys())[:8]) if isinstance(data, dict) else "formato sconosciuto"
        PROVIDER_COOLDOWN_UNTIL[name] = time.time() + 300
        PROVIDER_COOLDOWN_STATUS[name] = status or 502
        return None, {"provider": name, "status": status, "reason": f"JSON senza elenco aeromobili ({fields})"}
    PROVIDER_COOLDOWN_UNTIL.pop(name, None)
    PROVIDER_COOLDOWN_STATUS.pop(name, None)
    return {"ac": aircraft, "total": len(aircraft), "time": data.get("now", data.get("time", int(time.time() * 1000))), "skytraceSource": name}, None


def get_aircraft(lat, lon, dist):
    failures = []
    for name, base, fmt in PROVIDERS:
        cooldown_until = PROVIDER_COOLDOWN_UNTIL.get(name, 0)
        if cooldown_until > time.time():
            failures.append({"provider": name, "status": PROVIDER_COOLDOWN_STATUS.get(name, 503), "reason": f"pausa automatica dopo un errore precedente; riprova tra circa {int((cooldown_until - time.time() + 59) // 60)} min"})
            continue
        data, failure = query_provider(name, base, lat, lon, dist, fmt)
        if data is not None:
            data["providersTried"] = [item["provider"] for item in failures]
            data["note"] = "Dati ADS-B pubblici; copertura e disponibilità dipendono dal provider."
            return data
        failures.append(failure)
    details = "; ".join(f"{f['provider']}: {('HTTP ' + str(f['status']) + ', ') if f['status'] else ''}{f['reason']}" for f in failures)
    status = 429 if any(f["status"] == 429 for f in failures) else 503 if all(f["status"] in (403, 429) for f in failures) else 502
    raise ApiProblem(f"Nessuna fonte ADS-B disponibile. {details}. Riprova più tardi: i provider pubblici possono limitare richieste, soprattutto da server cloud.", status)


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("[HTTP] " + (fmt % args))

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/api/health", "/api/health/"):
            self.send_json(200, {"ok": True, "service": "SKYTRACE local proxy", "mode": "local", "provider": "public ADS-B fallback", "providers": [p[0] for p in PROVIDERS], "attribution": "ADSB.fi data must be credited and linked when used; personal, non-commercial use only.", "credentialsRequired": False})
            return
        if parsed.path in ("/api/aircraft", "/api/aircraft/"):
            self.handle_aircraft(parsed.query)
            return
        super().do_GET()

    def send_json(self, status, body):
        content = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def handle_aircraft(self, query):
        params = parse_qs(query)
        try:
            lat = float(params.get("lat", [""])[0])
            lon = float(params.get("lon", [""])[0])
            dist = int(params.get("dist", [""])[0])
        except (ValueError, TypeError, IndexError):
            self.send_json(400, {"detail": "Coordinate o raggio non validi."})
            return
        if not (-90 <= lat <= 90 and -180 <= lon <= 180 and dist in ALLOWED_RANGES):
            self.send_json(400, {"detail": "Coordinate o raggio non validi."})
            return
        try:
            self.send_json(200, get_aircraft(lat, lon, dist))
        except ApiProblem as error:
            self.send_json(error.status, {"detail": str(error)})
        except Exception as error:
            print(f"[ERROR] {type(error).__name__}: {error}")
            self.send_json(502, {"detail": "Errore imprevisto nel proxy ADS-B. Controlla la finestra del server locale."})


def find_server():
    import os
    os.chdir(PUBLIC)
    for port in range(START_PORT, MAX_PORT + 1):
        try:
            return ThreadingHTTPServer(("127.0.0.1", port), QuietHandler), port
        except OSError:
            continue
    raise RuntimeError(f"Nessuna porta libera tra {START_PORT} e {MAX_PORT}.")


if __name__ == "__main__":
    try:
        server, port = find_server()
    except Exception as exc:
        print(f"Errore: {exc}")
        input("Premi Invio per chiudere...")
        raise SystemExit(1)
    url = f"http://127.0.0.1:{port}/"
    print("=" * 56)
    print(" SKYTRACE — Radar Aereo")
    print(f" Server locale: {url}")
    print(" Fonti: ADSB One -> Airplanes.live -> ADSB.lol -> ADSB.fi")
    print(" ADSB.fi: uso personale/non commerciale e attribuzione richiesti.")
    print(" Per arrestarlo premi CTRL+C in questa finestra.")
    print("=" * 56)
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArresto del server...")
    finally:
        server.server_close()
