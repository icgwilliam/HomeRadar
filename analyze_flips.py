"""Detecta oportunidades preliminares de house flipping.

El análisis es deliberadamente auditable: usa comparables internos del lote
diario y no presenta el margen bruto como utilidad final. La remodelación,
impuestos, financiación, escrituración, sostenimiento y venta se validan
después con datos reales.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import unicodedata
from pathlib import Path

import pandas as pd

INPUT_FILE = Path("propiedades_limpias.csv")
OUTPUT_CSV = Path("oportunidades_flipping.csv")
OUTPUT_JSON = Path("oportunidades_flipping.json")
OUTPUT_REPORT = Path("reporte_whatsapp.txt")

DEFAULT_MAX_PRICE = 500_000_000
DEFAULT_LOCALITIES = ("usaquen", "suba", "chapinero")
DEFAULT_MIN_DISCOUNT = 0.12
DEFAULT_MIN_SCORE = 60
MIN_COMPS = 5
MIN_AREA_M2 = 25
MAX_AREA_M2 = 250
MIN_VALUE_M2 = 2_000_000
MAX_VALUE_M2 = 30_000_000

OPPORTUNITY_PATTERNS = {
    "para remodelar": 12,
    "remodelar": 9,
    "precio negociable": 8,
    "negociable": 5,
    "venta urgente": 10,
    "oportunidad": 6,
    "remate": 4,
    "sucesion": 3,
}


def normalize(value: object) -> str:
    text = "" if value is None or (isinstance(value, float) and math.isnan(value)) else str(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text.lower()).strip()


def infer_locality(row: pd.Series, localities: tuple[str, ...]) -> str | None:
    haystack = normalize(f"{row.get('ubicacion', '')} {row.get('title', '')}")
    return next((locality for locality in localities if locality in haystack), None)


def keyword_score(row: pd.Series) -> tuple[int, str]:
    haystack = normalize(f"{row.get('title', '')} {row.get('ubicacion', '')}")
    matches = [phrase for phrase in OPPORTUNITY_PATTERNS if phrase in haystack]
    score = min(20, sum(OPPORTUNITY_PATTERNS[phrase] for phrase in matches))
    return score, ", ".join(matches)


def known_yes(value: object) -> bool | None:
    text = normalize(value)
    if text in {"si", "s", "yes", "true", "1"}:
        return True
    if text in {"no", "n", "false", "0"}:
        return False
    return None


def bedroom_fit(row: pd.Series) -> bool | None:
    rooms = row.get("habitaciones")
    if pd.isna(rooms):
        return None
    place = normalize(f"{row.get('title', '')} {row.get('ubicacion', '')}")
    expected = 3 if any(zone in place for zone in ("santa barbara", "santa ana")) else 2
    return int(rooms) == expected


def age_fit(value: object) -> bool | None:
    text = normalize(value)
    if not text:
        return None
    if any(term in text for term in (
        "menor", "1 ano", "1 año", "1 a 5", "0 y 5",
        "5 a 10", "5 y 10", "10 a 20", "10 y 20",
    )):
        return True
    if any(term in text for term in ("mas de 30", "más de 30")):
        return False
    return None


def criterion(ok: bool | None, yes: str, no: str, pending: str = "❓ pendiente") -> str:
    if ok is None or pd.isna(ok):
        return pending
    if bool(ok):
        return f"✅ {yes}"
    return f"❌ {no}"


def analyze(
    df: pd.DataFrame,
    max_price: int = DEFAULT_MAX_PRICE,
    localities: tuple[str, ...] = DEFAULT_LOCALITIES,
    min_discount: float = DEFAULT_MIN_DISCOUNT,
    min_score: int = DEFAULT_MIN_SCORE,
) -> pd.DataFrame:
    required = {"link", "title", "precio", "area_m2", "valor_m2"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Faltan columnas requeridas: {', '.join(sorted(missing))}")

    work = df.copy()
    work["localidad"] = work.apply(lambda row: infer_locality(row, localities), axis=1)
    market = work[
        work["localidad"].notna()
        & work["precio"].notna()
        & work["area_m2"].notna()
        & work["valor_m2"].notna()
        & (work["precio"] > 0)
        & work["area_m2"].between(MIN_AREA_M2, MAX_AREA_M2)
        & work["valor_m2"].between(MIN_VALUE_M2, MAX_VALUE_M2)
    ].copy()

    if market.empty:
        return market

    medians: list[float] = []
    comp_counts: list[int] = []
    for _, row in market.iterrows():
        comparable = market[
            (market["localidad"] == row["localidad"])
            & market["area_m2"].between(row["area_m2"] * 0.70, row["area_m2"] * 1.30)
            & (market["link"] != row["link"])
        ]
        medians.append(float(comparable["valor_m2"].median()) if not comparable.empty else math.nan)
        comp_counts.append(len(comparable))

    market["mediana_comparables_m2"] = medians
    market["numero_comparables"] = comp_counts
    market["descuento_mercado"] = 1 - (market["valor_m2"] / market["mediana_comparables_m2"])
    market["arv_preliminar"] = (market["mediana_comparables_m2"] * market["area_m2"]).round()
    market["margen_bruto_preliminar"] = (market["arv_preliminar"] - market["precio"]).round()
    market["margen_sobre_compra"] = market["margen_bruto_preliminar"] / market["precio"]

    keyword_results = market.apply(keyword_score, axis=1)
    market["puntaje_palabras"] = [result[0] for result in keyword_results]
    market["senales_texto"] = [result[1] for result in keyword_results]

    admin = pd.to_numeric(
        market.get("administracion", pd.Series(math.nan, index=market.index)),
        errors="coerce",
    )
    market["administracion_m2"] = admin / market["area_m2"]
    market["mediana_administracion_m2"] = market.groupby("localidad")["administracion_m2"].transform("median")
    market["administracion_baja"] = (
        market["administracion_m2"].notna()
        & market["mediana_administracion_m2"].notna()
        & (market["administracion_m2"] <= market["mediana_administracion_m2"])
    )
    market.loc[market["administracion_m2"].isna(), "administracion_baja"] = pd.NA

    market["alcobas_adecuadas"] = market.apply(bedroom_fit, axis=1)
    market["antiguedad_adecuada"] = market.get(
        "antiguedad", pd.Series("", index=market.index)
    ).apply(age_fit)
    market["ascensor_confirmado"] = market.get(
        "ascensor", pd.Series("", index=market.index)
    ).apply(known_yes)
    market["exterior_confirmado"] = market.get(
        "exterior", pd.Series("", index=market.index)
    ).apply(known_yes)
    market["vista_confirmada"] = market.get(
        "vista", pd.Series("", index=market.index)
    ).apply(known_yes)
    floor = pd.to_numeric(
        market.get("piso", pd.Series(math.nan, index=market.index)),
        errors="coerce",
    )

    discount_points = market["descuento_mercado"].clip(lower=0, upper=0.25) / 0.25 * 25
    margin_points = market["margen_sobre_compra"].clip(lower=0, upper=0.40) / 0.40 * 25
    location_points = pd.Series(15.0, index=market.index)

    parking = pd.to_numeric(
        market.get("parqueaderos", pd.Series(math.nan, index=market.index)),
        errors="coerce",
    )
    parking_points = parking.map(lambda value: 10 if value >= 2 else 7 if value >= 1 else 0)
    parking_points = parking_points.fillna(5)
    bedroom_points = market["alcobas_adecuadas"].map({True: 5.0, False: 1.0}).fillna(2.5)
    age_points = market["antiguedad_adecuada"].map({True: 5.0, False: 0.0}).fillna(2.5)

    elevator_points = market["ascensor_confirmado"].map({True: 6.0, False: 0.0}).fillna(3.0)
    admin_points = market["administracion_baja"].map({True: 4.0, False: 1.0}).fillna(2.0)
    floor_points = floor.map(lambda value: 2.0 if value >= 5 else 1.0).fillna(1.0)
    exterior_points = market["exterior_confirmado"].map({True: 2.0, False: 0.0}).fillna(1.0)
    view_points = market["vista_confirmada"].map({True: 1.0, False: 0.0}).fillna(0.5)
    quality_points = elevator_points + admin_points + floor_points + exterior_points + view_points

    score = (
        discount_points + margin_points + location_points + parking_points
        + bedroom_points + age_points + quality_points
    )
    # Un inmueble puede no tener comparables de área en su localidad. En ese
    # caso el descuento (y por tanto el puntaje) es NaN; se conserva en el lote
    # para el análisis, pero recibe puntaje cero y luego queda excluido por el
    # mínimo de comparables.
    market["puntaje"] = (
        score.replace([float("inf"), float("-inf")], math.nan)
        .fillna(0)
        .round()
        .clip(lower=0, upper=100)
        .astype(int)
    )

    market["confianza"] = pd.cut(
        market["numero_comparables"],
        bins=[0, 4, 9, float("inf")],
        labels=["baja", "media", "alta"],
    ).astype(str)

    candidates = market[
        (market["precio"] <= max_price)
        & (market["numero_comparables"] >= MIN_COMPS)
        & (market["descuento_mercado"] >= min_discount)
        & (market["ascensor_confirmado"] != False)
        & (market["puntaje"] >= min_score)
    ].copy()
    return candidates.sort_values(
        ["puntaje", "descuento_mercado", "margen_bruto_preliminar"],
        ascending=[False, False, False],
    ).reset_index(drop=True)


def money(value: object) -> str:
    return f"${int(float(value)):,}".replace(",", ".")


def build_report(candidates: pd.DataFrame, max_items: int = 5) -> str:
    if candidates.empty:
        return ""

    lines = [
        "🏠 *ALERTA CASAFIX · HomeRadar*",
        f"{len(candidates)} oportunidad(es) preliminar(es).",
        "Cifras antes de remodelación, impuestos, financiación y venta.",
    ]
    for index, row in candidates.head(max_items).iterrows():
        signals = f"\nSeñales: {row['senales_texto']}." if row.get("senales_texto") else ""
        parking = row.get("parqueaderos")
        parking_ok = None if pd.isna(parking) else float(parking) >= 1
        parking_label = "dato pendiente" if pd.isna(parking) else f"{int(parking)} propio(s)"
        floor = row.get("piso")
        floor_text = "❓ piso pendiente" if pd.isna(floor) else (
            f"✅ piso alto ({int(floor)})" if float(floor) >= 5 else f"➖ piso {int(floor)} aceptable"
        )
        admin_ok = row.get("administracion_baja")
        lines.extend([
            "",
            f"*{index + 1}. Puntaje {int(row['puntaje'])}/100 · {str(row['localidad']).title()}*",
            str(row.get("title") or "Sin título")[:100],
            f"Compra: {money(row['precio'])} · Área: {float(row['area_m2']):g} m²",
            f"Valor/m²: {money(row['valor_m2'])} · descuento estimado: {row['descuento_mercado']:.1%}",
            f"ARV preliminar: {money(row['arv_preliminar'])} · margen bruto: {money(row['margen_bruto_preliminar'])}",
            f"Comparables: {int(row['numero_comparables'])} · confianza {row['confianza']}.{signals}",
            "*Criterios:*",
            f"• Ubicación: ✅ zona objetivo · Parqueadero: {criterion(parking_ok, parking_label, 'sin parqueadero')}",
            f"• Alcobas/microzona: {criterion(row.get('alcobas_adecuadas'), 'acordes', 'no ideales')} · Antigüedad: {criterion(row.get('antiguedad_adecuada'), 'posterior a 1998', 'anterior a 1998')}",
            f"• Ascensor: {criterion(row.get('ascensor_confirmado'), 'confirmado', 'sin ascensor')} · {floor_text}",
            f"• Administración: {criterion(admin_ok, 'baja frente a pares', 'alta frente a pares')} · Exterior: {criterion(row.get('exterior_confirmado'), 'sí', 'no')}",
            f"• Buena vista: {criterion(row.get('vista_confirmada'), 'sí', 'no')}",
            str(row["link"]),
        ])
    lines.extend([
        "",
        "⚠️ Preselección automática; requiere validar estado jurídico, visita, presupuesto de obra y comparables cerrados.",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Analiza oportunidades de house flipping")
    parser.add_argument("--input", type=Path, default=INPUT_FILE)
    parser.add_argument("--max-price", type=int, default=DEFAULT_MAX_PRICE)
    parser.add_argument("--localities", default=",".join(DEFAULT_LOCALITIES))
    parser.add_argument("--min-discount", type=float, default=DEFAULT_MIN_DISCOUNT)
    parser.add_argument("--min-score", type=int, default=DEFAULT_MIN_SCORE)
    args = parser.parse_args()

    localities = tuple(normalize(item) for item in args.localities.split(",") if item.strip())
    frame = pd.read_csv(args.input)
    candidates = analyze(
        frame,
        max_price=args.max_price,
        localities=localities,
        min_discount=args.min_discount,
        min_score=args.min_score,
    )
    candidates.to_csv(OUTPUT_CSV, index=False, encoding="utf-8")
    OUTPUT_JSON.write_text(
        json.dumps(candidates.to_dict(orient="records"), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    OUTPUT_REPORT.write_text(build_report(candidates), encoding="utf-8")
    print(f"Oportunidades: {len(candidates)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
