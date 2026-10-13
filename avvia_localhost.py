from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import json
import os
import threading
import webbrowser

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
START_PORT = 10000
MAX_PORT = 10100
ALLOWED_RANGES = {25, 50, 100, 150, 250}


def data_sources(lat, lon, dist):
    return [
        ("ADSB One", f"https://api.adsb.one/v2/point/{lat}/{lon}/{dist}"),
        ("Airplanes.live", f"https://api.airplanes.live/v2/point/{lat}/{lon}/{dist}"),
        ("ADSB.lol", f"https://api.adsb.lol/v2/lat/{lat}/lon/{lon}/dist/{dist}"),
    ]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        print("[HTTP] " + (format % args))

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/api/health", "/api/health/"):
            self.send_json(200, {
                "ok": True,
                "service": "SKYTRACE local proxy",
                "mode": "local",
                "providers": ["ADSB One", "Airplanes.live", "ADSB.lol"],
            })
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

        failures = []
        for source_name, upstream_url in data_sources(lat, lon, dist):
            req = Request(upstream_url, headers={
                "Accept": "application/json",
                "User-Agent": "SKYTRACE-Radar/1.1 (public aircraft visualization)",
            })
            try:
                with urlopen(req, timeout=6) as response:
                    raw = response.read().decode("utf-8", "replace")
                    status = response.status
                    content_type = response.headers.get("Content-Type", "application/json")
            except HTTPError as error:
                raw = error.read(500).decode("utf-8", "replace")
                status = error.code
                content_type = error.headers.get("Content-Type", "tipo sconosciuto")
            except (URLError, TimeoutError, OSError):
                failures.append(f"{source_name}: connessione non riuscita")
                continue

            try:
                payload = json.loads(raw)
            except (ValueError, TypeError):
                failures.append(f"{source_name}: HTTP {status}, risposta non JSON ({content_type})")
                continue
            if status < 200 or status >= 300:
                detail = payload.get("detail", payload.get("message", "")) if isinstance(payload, dict) else ""
                suffix = f" — {str(detail)[:100]}" if detail else ""
                failures.append(f"{source_name}: HTTP {status}{suffix}")
                continue
            if not isinstance(payload, dict) or not isinstance(payload.get("ac", payload.get("aircraft")), list):
                failures.append(f"{source_name}: formato JSON non riconosciuto")
                continue

            if "ac" not in payload and isinstance(payload.get("aircraft"), list):
                payload["ac"] = payload["aircraft"]
            payload["skytraceSource"] = source_name
            self.send_json(200, payload)
            print(f"[ADS-B] Dati ottenuti da {source_name}")
            return

        self.send_json(502, {
            "detail": "Nessuna fonte ADS-B disponibile. " + "; ".join(failures) + ". Riprova tra qualche secondo: l'accesso alle fonti pubbliche può essere limitato o temporaneamente indisponibile.",
            "providersTried": len(failures),
        })


def find_server():
    os.chdir(PUBLIC)
    for port in range(START_PORT, MAX_PORT + 1):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), QuietHandler)
            return server, port
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
    print(" Proxy ADS-B con 3 fonti di fallback attivo su /api/aircraft")
    print(" Per arrestarlo premi CTRL+C in questa finestra.")
    print("=" * 56)
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArresto del server...")
    finally:
        server.server_close()
