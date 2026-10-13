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

class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        print("[HTTP] " + (format % args))

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/aircraft":
            self.handle_aircraft(parsed.query)
            return
        super().do_GET()

    def send_json(self, status, body):
        content = json.dumps(body).encode("utf-8")
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

        upstream = f"https://api.adsb.lol/v2/lat/{lat}/lon/{lon}/dist/{dist}"
        req = Request(upstream, headers={"Accept": "application/json", "User-Agent": "SkytraceRadar/1.0"})
        try:
            with urlopen(req, timeout=14) as response:
                body = response.read()
                status = response.status
                content_type = response.headers.get("Content-Type", "application/json; charset=utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except HTTPError as error:
            body = error.read()
            self.send_response(error.code)
            self.send_header("Content-Type", error.headers.get("Content-Type", "application/json; charset=utf-8"))
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (URLError, TimeoutError, OSError):
            self.send_json(502, {"detail": "La fonte ADS-B non è raggiungibile in questo momento."})


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
    print(" Proxy ADS-B locale attivo su /api/aircraft")
    print(" Per arrestarlo premi CTRL+C in questa finestra.")
    print("=" * 56)
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArresto del server...")
    finally:
        server.server_close()
