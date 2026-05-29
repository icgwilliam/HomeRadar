"""Envia las propiedades a Telegram ordenadas por valor_m2 ascendente.

Lee TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID del entorno.
Particiona el listado en mensajes <=4096 chars (limite Telegram).
"""
from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

import pandas as pd
import requests

INPUT_FILE = Path("propiedades_limpias.csv")
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
MAX_MSG_LEN = 4000  # margen sobre el limite de 4096
BOGOTA = ZoneInfo("America/Bogota")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("notify")


def _fmt_money(value: float | int | None) -> str:
    if value is None or pd.isna(value):
        return "?"
    return f"${int(value):,}".replace(",", ".")


def _fmt_num(value, suffix: str = "") -> str:
    if value is None or pd.isna(value):
        return "?"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f"{value}{suffix}"


def _escape_html(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def format_property(rank: int, row: pd.Series) -> str:
    title = _escape_html(row.get("title") or "Sin titulo")[:80]
    safe_link = _escape_html(row["link"])
    precio = _fmt_money(row.get("precio"))
    area = _fmt_num(row.get("area_m2"), " m²")
    valor_m2 = _fmt_money(row.get("valor_m2"))
    habs = _fmt_num(row.get("habitaciones"))
    banos = _fmt_num(row.get("banos"))

    return (
        f"<b>#{rank}</b> · <b>{valor_m2}/m²</b>\n"
        f"{title}\n"
        f"💰 {precio} · 📐 {area} · 🛏 {habs}h · 🚿 {banos}b\n"
        f'<a href="{safe_link}">Ver propiedad</a>'
    )


def chunk_messages(blocks: Iterable[str], header: str) -> list[str]:
    """Agrupa bloques de propiedades en mensajes <= MAX_MSG_LEN chars."""
    messages: list[str] = []
    current = header
    for block in blocks:
        candidate = current + "\n\n" + block if current else block
        if len(candidate) > MAX_MSG_LEN:
            if current:
                messages.append(current)
            current = block
        else:
            current = candidate
    if current:
        messages.append(current)
    return messages


def _redact(text: str, secret: str | None) -> str:
    """Reemplaza el token por '***' para evitar leakage en logs publicos."""
    if not secret:
        return text
    return text.replace(secret, "***")


def send_message(token: str, chat_id: str, text: str) -> None:
    url = TELEGRAM_API.format(token=token)
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    r = requests.post(url, json=payload, timeout=20)
    if not r.ok:
        # Sanitizar antes de loggear: Telegram puede incluir la URL en el body
        # de algunos errores y eso filtraria el token en logs publicos.
        try:
            description = r.json().get("description", "")
        except ValueError:
            description = r.text
        log.error("Telegram error %s: %s", r.status_code, _redact(description, token))
        r.raise_for_status()


def main() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log.error("Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID en el entorno")
        return 1

    if not INPUT_FILE.exists():
        log.error("No existe %s; corre homeradar.py primero", INPUT_FILE)
        return 1

    df = pd.read_csv(INPUT_FILE)
    df = df.dropna(subset=["valor_m2"]).sort_values("valor_m2", ascending=True)
    total = len(df)

    today = datetime.now(BOGOTA).strftime("%Y-%m-%d")
    if total == 0:
        send_message(
            token,
            chat_id,
            f"🏠 <b>HomeRadar {today}</b>\nNo se encontraron propiedades hoy.",
        )
        return 0

    mediana = df["valor_m2"].median()
    p25 = df["valor_m2"].quantile(0.25)

    header = (
        f"🏠 <b>HomeRadar · {today}</b>\n"
        f"<b>{total}</b> propiedades · ordenadas por valor/m² ↑\n"
        f"Mediana: <b>{_fmt_money(mediana)}/m²</b> · "
        f"P25: <b>{_fmt_money(p25)}/m²</b>"
    )

    blocks = [format_property(i + 1, row) for i, (_, row) in enumerate(df.iterrows())]
    messages = chunk_messages(blocks, header)

    log.info("Enviando %d mensaje(s) a Telegram (%d propiedades)", len(messages), total)
    failed = 0
    for i, msg in enumerate(messages, 1):
        try:
            send_message(token, chat_id, msg)
        except requests.RequestException as exc:
            failed += 1
            log.error("Mensaje %d/%d fallo, continuando: %s",
                      i, len(messages), _redact(str(exc), token))
        if i < len(messages):
            time.sleep(1)  # respetar rate-limit de Telegram (~30 msg/s)

    if failed:
        log.warning("Listo con %d/%d mensajes fallidos", failed, len(messages))
        return 2  # exit no-cero para que el workflow marque warning
    log.info("Listo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
