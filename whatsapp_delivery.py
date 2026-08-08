"""Prepara y confirma alertas nuevas para el grupo de WhatsApp de CasaFix."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from analyze_flips import build_report

INPUT_JSON = Path("oportunidades_flipping.json")
REPORT_FILE = Path("reporte_whatsapp.txt")
PENDING_FILE = Path(".whatsapp_alert_pending.json")
HISTORY_FILE = Path(".whatsapp_alert_history.json")
MAX_HISTORY = 2000


def read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def prepare() -> int:
    records = read_json(INPUT_JSON, [])
    sent = set(read_json(HISTORY_FILE, []))
    fresh = [record for record in records if record.get("link") not in sent]
    PENDING_FILE.write_text(
        json.dumps(fresh, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    report = build_report(pd.DataFrame(fresh))
    REPORT_FILE.write_text(report, encoding="utf-8")
    print(f"Alertas nuevas: {len(fresh)}")
    return 0


def mark_sent() -> int:
    pending = read_json(PENDING_FILE, [])
    history = read_json(HISTORY_FILE, [])
    seen = set(history)
    for record in pending:
        link = record.get("link")
        if link and link not in seen:
            history.append(link)
            seen.add(link)
    HISTORY_FILE.write_text(
        json.dumps(history[-MAX_HISTORY:], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    PENDING_FILE.write_text("[]\n", encoding="utf-8")
    print(f"Historial confirmado: {len(pending)} alerta(s)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "mark-sent"))
    args = parser.parse_args()
    return prepare() if args.action == "prepare" else mark_sent()


if __name__ == "__main__":
    raise SystemExit(main())
