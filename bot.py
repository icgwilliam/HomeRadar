"""Bot webhook de HomeRadar: suscripcion/desuscripcion via Telegram.

Cualquiera que escanee el QR (que abre t.me/<bot>) y envie /start queda
suscrito y recibira el listado diario de propiedades. /stop lo da de baja.

Los chat_ids se persisten en un GitHub gist privado (ver utils_gist.py),
que tanto este bot (escritura) como el notifier (lectura) comparten.

Diseñado para correr en un host siempre arriba (Railway / Render / fly.io /
cualquier VPS). Expone un endpoint POST /webhook que Telegram llama.

Variables de entorno:
    TELEGRAM_BOT_TOKEN  -> token de @BotFather
    GIST_TOKEN          -> GitHub PAT (scope: gist)
    GIST_ID             -> id del gist privado con subscribers.json
    WEBHOOK_PORT        -> puerto a escuchar (default 8000, plataformas inyectan PORT)

Uso local (polling, sin exponer puertos):
    python bot.py --poll

Deploy webhook: ver README seccion "Desplegar el bot".
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import requests

import utils_gist

TELEGRAM_API = "https://api.telegram.org/bot{token}"
HELP_TEXT = (
    "🏠 <b>HomeRadar</b>\n"
    "Recibiras el listado diario de apartamentos en Chapinero/Usaquen "
    "ordenados por mejor valor/m², todos los dias ~9:00 AM.\n\n"
    "Comandos:\n"
    "• /start — suscribirte\n"
    "• /stop — dejar de recibir\n"
    "• /help — esta ayuda"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("bot")


def _env_or_die(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        log.error("Falta %s en el entorno", name)
        sys.exit(1)
    return val


def tg_call(token: str, method: str, payload: dict) -> dict:
    url = f"{TELEGRAM_API.format(token=token)}/{method}"
    r = requests.post(url, json=payload, timeout=15)
    if not r.ok:
        log.error("Telegram %s -> %s %s", method, r.status_code, r.text[:200])
    return r.json()


def handle_update(token: str, gist_token: str, gist_id: str, update: dict) -> None:
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return
    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or "").strip()
    name = msg.get("from", {}).get("first_name", "")

    if text.startswith("/start"):
        try:
            utils_gist.add_chat_id(gist_token, gist_id, chat_id)
            tg_call(token, "sendMessage", {
                "chat_id": chat_id,
                "parse_mode": "HTML",
                "text": f"¡Hola {name}! Ya estas suscrito a HomeRadar 🏠\n{HELP_TEXT}",
            })
            log.info("Suscrito: %s (%s)", chat_id, name)
        except requests.RequestException as exc:
            log.error("No se pudo guardar suscriptor %s: %s", chat_id, exc)
            tg_call(token, "sendMessage", {
                "chat_id": chat_id,
                "text": "No pude registrarte ahora. Intenta de nuevo en un momento.",
            })

    elif text.startswith("/stop"):
        try:
            utils_gist.remove_chat_id(gist_token, gist_id, chat_id)
            tg_call(token, "sendMessage", {
                "chat_id": chat_id,
                "text": "Te dimos de baja. Vuelve con /start cuando quieras. 👋",
            })
            log.info("Desuscrito: %s (%s)", chat_id, name)
        except requests.RequestException as exc:
            log.error("No se pudo desuscribir %s: %s", chat_id, exc)

    elif text.startswith("/help"):
        tg_call(token, "sendMessage", {
            "chat_id": chat_id,
            "parse_mode": "HTML",
            "text": HELP_TEXT,
        })
    # mensajes libres: no hacer nada (bot de difusion)


def run_polling(token: str, gist_token: str, gist_id: str) -> None:
    log.info("Modo polling (local)")
    base = TELEGRAM_API.format(token=token)
    # limpia webhook previo
    requests.get(f"{base}/deleteWebhook", timeout=10)
    offset = None
    while True:
        params = {"timeout": 30}
        if offset:
            params["offset"] = offset
        try:
            r = requests.get(f"{base}/getUpdates", params=params, timeout=35)
            data = r.json()
        except requests.RequestException as exc:
            log.warning("getUpdates fallo: %s", exc)
            time.sleep(5)
            continue
        for upd in data.get("result", []):
            offset = upd["update_id"] + 1
            try:
                handle_update(token, gist_token, gist_id, upd)
            except Exception as exc:  # noqa: BLE001
                log.exception("Error procesando update: %s", exc)


class WebhookHandler(BaseHTTPRequestHandler):
    token: str = ""
    gist_token: str = ""
    gist_id: str = ""

    def do_GET(self) -> None:  # noqa: N802  (health checks de Railway/Telegram)
        path = urlparse(self.path).path
        if path == "/" or path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"HomeRadar bot OK")
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/webhook":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"
        try:
            update = json.loads(body)
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            return
        # responder 200 rapido a Telegram y procesar despues
        self.send_response(200)
        self.end_headers()
        try:
            handle_update(self.token, self.gist_token, self.gist_id, update)
        except Exception as exc:  # noqa: BLE001
            log.exception("Error procesando update: %s", exc)

    def log_message(self, fmt, *args):  # silenciar logs ruidosos
        log.debug("http: " + fmt, *args)


def run_webhook(token: str, gist_token: str, gist_id: str, port: int, url: str) -> None:
    base = TELEGRAM_API.format(token=token)
    WebhookHandler.token = token
    WebhookHandler.gist_token = gist_token
    WebhookHandler.gist_id = gist_id

    # Arrancar el servidor PRIMERO: asi Railway/Telegram ven el endpoint
    # inmediatamente y no matan el proceso por health check fallido.
    server = ThreadingHTTPServer(("0.0.0.0", port), WebhookHandler)
    log.info("Escuchando en 0.0.0.0:%d (health: GET /)", port)

    webhook_url = f"{url.rstrip('/')}/webhook"
    log.info("Registrando webhook %s", webhook_url)
    try:
        resp = requests.post(f"{base}/setWebhook", json={"url": webhook_url}, timeout=15)
        if resp.ok and resp.json().get("ok"):
            log.info("Webhook registrado OK en Telegram")
        else:
            log.error("setWebhook fallo: %s %s", resp.status_code, resp.text[:200])
    except requests.RequestException as exc:
        log.error("setWebhook red no disponible: %s", exc)

    server.serve_forever()


def main() -> int:
    parser = argparse.ArgumentParser(description="HomeRadar bot webhook")
    parser.add_argument("--poll", action="store_true", help="usar getUpdates (local)")
    parser.add_argument("--url", default=os.environ.get("WEBHOOK_URL", ""),
                        help="URL publica del webhook (ej. https://homeradar-bot.up.railway.app)")
    args = parser.parse_args()

    token = _env_or_die("TELEGRAM_BOT_TOKEN")
    gist_token = _env_or_die("GIST_TOKEN")
    gist_id = _env_or_die("GIST_ID")
    port = int(os.environ.get("PORT") or os.environ.get("WEBHOOK_PORT") or 8000)

    if args.poll:
        run_polling(token, gist_token, gist_id)
    else:
        if not args.url:
            log.error("Modo webhook requiere --url o WEBHOOK_URL")
            return 1
        run_webhook(token, gist_token, gist_id, port, args.url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
