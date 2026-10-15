"""Start SKYTRACE's local ADS-B proxy and expose it through a protected Cloudflare Quick Tunnel.

The tunnel URL is temporary and only works while this process and the PC remain online.
All routes require HTTP Basic authentication so a random visitor cannot freely consume
upstream ADS-B API quotas.
"""
from __future__ import annotations

import base64
import hmac
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import ThreadingHTTPServer
from pathlib import Path

import avvia_localhost as local

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
USERNAME = "skytrace"
PASSWORD = secrets.token_urlsafe(18)
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com", re.IGNORECASE)


class ProtectedHandler(local.QuietHandler):
    server_version = "SKYTRACE-Live/1.0"
    sys_version = ""

    def _authorized(self) -> bool:
        expected = "Basic " + base64.b64encode(f"{USERNAME}:{PASSWORD}".encode("utf-8")).decode("ascii")
        received = self.headers.get("Authorization", "")
        return hmac.compare_digest(received, expected)

    def _challenge(self) -> None:
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="SKYTRACE Live Radar", charset="UTF-8"')
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if not self._authorized():
            self._challenge()
            return
        super().do_GET()

    def do_HEAD(self):
        if not self._authorized():
            self._challenge()
            return
        super().do_HEAD()


def find_cloudflared() -> str | None:
    executable = shutil.which("cloudflared") or shutil.which("cloudflared.exe")
    if executable:
        return executable
    for candidate in (ROOT / "cloudflared.exe", ROOT / "cloudflared"):
        if candidate.is_file():
            return str(candidate)
    return None


def start_server():
    os.chdir(PUBLIC)
    for port in range(local.START_PORT, local.MAX_PORT + 1):
        try:
            return ThreadingHTTPServer(("127.0.0.1", port), ProtectedHandler), port
        except OSError:
            continue
    raise RuntimeError(f"Nessuna porta libera tra {local.START_PORT} e {local.MAX_PORT}.")


def main() -> int:
    cloudflared = find_cloudflared()
    if not cloudflared:
        print("Non trovo cloudflared.")
        print("Installa Cloudflare Tunnel seguendo la guida ufficiale:")
        print("https://developers.cloudflare.com/tunnel/downloads/")
        print("Su Windows puoi anche eseguire in PowerShell: winget install --id Cloudflare.cloudflared -e")
        input("Dopo l'installazione, premi Invio e riavvia AVVIA_LIVE_TUNNEL.bat...")
        return 1

    try:
        server, port = start_server()
    except Exception as exc:
        print(f"Errore di avvio: {exc}")
        input("Premi Invio per chiudere...")
        return 1

    origin = f"http://127.0.0.1:{port}"
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    print("=" * 70)
    print(" SKYTRACE — FEED LIVE GRATUITO TRAMITE IL TUO PC")
    print(f" Proxy locale: {origin}")
    print(f" Username accesso web: {USERNAME}")
    print(f" Password accesso web: {PASSWORD}")
    print(" Avvio Cloudflare Quick Tunnel; l'URL pubblico temporaneo apparirà sotto.")
    print(" Il PC e questa finestra devono restare accesi per mantenere il feed live.")
    print(" L'URL cambia al prossimo avvio. Per terminare premi CTRL+C.")
    print("=" * 70, flush=True)

    command = [cloudflared, "tunnel", "--url", origin, "--no-autoupdate"]
    try:
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", bufsize=1)
    except OSError as exc:
        server.shutdown()
        server.server_close()
        print(f"Impossibile avviare cloudflared: {exc}")
        input("Premi Invio per chiudere...")
        return 1

    opened = False
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line.rstrip(), flush=True)
            if not opened:
                match = URL_RE.search(line)
                if match:
                    public_url = match.group(0)
                    opened = True
                    print("\n" + "!" * 70)
                    print("RADAR LIVE: " + public_url)
                    print("Quando il browser chiede le credenziali, inserisci:")
                    print(f"  Username: {USERNAME}")
                    print(f"  Password: {PASSWORD}")
                    print("Non pubblicare la password: protegge il tuo proxy locale.")
                    print("!" * 70 + "\n", flush=True)
                    threading.Timer(1.0, lambda: webbrowser.open(public_url + "/")).start()
            if proc.poll() is not None:
                break
    except KeyboardInterrupt:
        print("\nChiusura del tunnel e del server…")
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
