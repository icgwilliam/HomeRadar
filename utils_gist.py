"""Persistencia en un GitHub gist privado (suscriptores + historial).

El bot (bot.py) escribe los chat_ids de suscriptores, y el notifier
(notify_telegram.py) lee tanto suscriptores como historial de IDs ya
enviados para no repetir propiedades.

Variables de entorno:
    GIST_TOKEN  -> GitHub Personal Access Token (scope: gist)
    GIST_ID     -> id del gist privado

Archivos dentro del gist:
    subscribers.json   -> {"chat_ids": [123, -456]}
    sent_history.json  -> {"property_ids": ["MC6821347", "..."], "links": ["https://...", "..."]}
"""
from __future__ import annotations

import json
import logging
from typing import Iterable

import requests

GITHUB_API = "https://api.github.com/gists"
SUBSCRIBERS_FILE = "subscribers.json"
HISTORY_FILE = "sent_history.json"
MAX_HISTORY = 2000  # retener maximo N IDs/links para no crecer indefinidamente

log = logging.getLogger("gist")


def _auth_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }


def _read_gist_files(token: str, gist_id: str) -> dict:
    """Devuelve {filename: content_str} del gist."""
    url = f"{GITHUB_API}/{gist_id}"
    r = requests.get(url, headers=_auth_headers(token), timeout=15)
    r.raise_for_status()
    data = r.json()
    return {
        name: fdata.get("content", "")
        for name, fdata in data.get("files", {}).items()
    }


def _update_file(token: str, gist_id: str, filename: str, content: str) -> None:
    payload = {"files": {filename: {"content": content}}}
    url = f"{GITHUB_API}/{gist_id}"
    r = requests.patch(url, headers=_auth_headers(token), json=payload, timeout=15)
    r.raise_for_status()


def read_chat_ids(token: str, gist_id: str) -> list[int]:
    """Lee los chat_ids guardados en el gist. Lista vacia si falla o esta vacio."""
    try:
        files = _read_gist_files(token, gist_id)
    except requests.RequestException as exc:
        log.warning("No se pudo leer el gist: %s", exc)
        return []
    content = files.get(SUBSCRIBERS_FILE, "{}")
    try:
        return [int(x) for x in json.loads(content).get("chat_ids", [])]
    except (ValueError, TypeError) as exc:
        log.warning("subscribers.json malformado: %s", exc)
        return []


def write_chat_ids(token: str, gist_id: str, chat_ids: Iterable[int]) -> None:
    """Reemplaza el contenido del gist con la lista dada (sin duplicados)."""
    unique = sorted(set(int(x) for x in chat_ids))
    _update_file(token, gist_id, SUBSCRIBERS_FILE,
                 json.dumps({"chat_ids": unique}, indent=2))


def read_sent_history(token: str, gist_id: str) -> set[str]:
    """Lee el conjunto de links ya enviados. Set vacio si falla."""
    try:
        files = _read_gist_files(token, gist_id)
    except requests.RequestException as exc:
        log.warning("No se pudo leer el historial del gist: %s", exc)
        return set()
    content = files.get(HISTORY_FILE, "{}")
    try:
        data = json.loads(content)
        return set(data.get("links", []))
    except (ValueError, TypeError) as exc:
        log.warning("sent_history.json malformado: %s", exc)
        return set()


def write_sent_history(token: str, gist_id: str, links: Iterable[str]) -> None:
    """Guarda el historial de links enviados (dedupe + truncado a MAX_HISTORY)."""
    unique = sorted(set(links))
    unique = unique[-MAX_HISTORY:]  # conservar los mas recientes
    _update_file(token, gist_id, HISTORY_FILE,
                 json.dumps({"links": unique}, indent=2))


def add_sent_links(token: str, gist_id: str, new_links: Iterable[str]) -> set[str]:
    """Anade nuevos links al historial y devuelve el historial actualizado."""
    current = read_sent_history(token, gist_id)
    current.update(new_links)
    write_sent_history(token, gist_id, current)
    return current


def add_chat_id(token: str, gist_id: str, chat_id: int) -> list[int]:
    current = read_chat_ids(token, gist_id)
    if chat_id in current:
        return current
    current.append(chat_id)
    write_chat_ids(token, gist_id, current)
    return current


def remove_chat_id(token: str, gist_id: str, chat_id: int) -> list[int]:
    current = read_chat_ids(token, gist_id)
    current = [c for c in current if c != chat_id]
    write_chat_ids(token, gist_id, current)
    return current
