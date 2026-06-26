"""Persistencia de suscriptores (chat_ids) en un GitHub gist privado.

El bot (bot.py) escribe aqui cada vez que alguien hace /start, y el
notifier (notify_telegram.py) lee aqui para difundir a todos.

Variables de entorno:
    GIST_TOKEN  -> GitHub Personal Access Token (scope: gist)
    GIST_ID     -> id del gist privado que guarda subscribers.json

Forma del gist: un unico archivo "subscribers.json" cuyo contenido es
    {"chat_ids": [123456789, -1001234567890]}
"""
from __future__ import annotations

import json
import logging
from typing import Iterable

import requests

GITHUB_API = "https://api.github.com/gists"
SUBSCRIBERS_FILE = "subscribers.json"

log = logging.getLogger("gist")


def _auth_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }


def read_chat_ids(token: str, gist_id: str) -> list[int]:
    """Lee los chat_ids guardados en el gist. Lista vacia si falla o esta vacio."""
    url = f"{GITHUB_API}/{gist_id}"
    r = requests.get(url, headers=_auth_headers(token), timeout=15)
    r.raise_for_status()
    data = r.json()
    content = data.get("files", {}).get(SUBSCRIBERS_FILE, {}).get("content", "{}")
    try:
        return [int(x) for x in json.loads(content).get("chat_ids", [])]
    except (ValueError, TypeError) as exc:
        log.warning("subscribers.json malformado: %s", exc)
        return []


def write_chat_ids(token: str, gist_id: str, chat_ids: Iterable[int]) -> None:
    """Reemplaza el contenido del gist con la lista dada (sin duplicados)."""
    unique = sorted(set(int(x) for x in chat_ids))
    payload = {
        "files": {
            SUBSCRIBERS_FILE: {
                "content": json.dumps({"chat_ids": unique}, indent=2),
            }
        },
    }
    url = f"{GITHUB_API}/{gist_id}"
    r = requests.patch(url, headers=_auth_headers(token), json=payload, timeout=15)
    r.raise_for_status()


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
