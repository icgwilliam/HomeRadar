"""HomeRadar: scraper de fincaraiz.com.co + limpieza.

Genera dos CSV en el directorio actual:
  - propiedades_raw.csv      (datos crudos)
  - propiedades_limpias.csv  (numerico, dedupe, valor_m2)

Uso:
    python homeradar.py
"""
from __future__ import annotations

import csv
import logging
import random
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ---------------------------------------------------------------------------
# Configuracion
# ---------------------------------------------------------------------------
BASE_URL = "https://www.fincaraiz.com.co"
START_URL = (
    "https://www.fincaraiz.com.co/venta/apartamentos/santa-paula/zona-norte/"
    "bogota/2-habitaciones/2-banos/1-parqueadero"
)
OUTPUT_RAW = Path("propiedades_raw.csv")
OUTPUT_CLEAN = Path("propiedades_limpias.csv")
MAX_PAGES = 50
REQUEST_TIMEOUT = 15
SLEEP_RANGE = (1.0, 2.5)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("homeradar")


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def build_session() -> requests.Session:
    s = requests.Session()
    retry_kwargs = dict(
        total=4,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        raise_on_status=False,
    )
    try:
        retry = Retry(allowed_methods=("GET",), **retry_kwargs)
    except TypeError:
        retry = Retry(method_whitelist=("GET",), **retry_kwargs)
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "es-CO,es;q=0.9"})
    return s


def fetch(session: requests.Session, url: str) -> Optional[BeautifulSoup]:
    try:
        r = session.get(url, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
    except requests.RequestException as exc:
        log.warning("GET fallo %s -> %s", url, exc)
        return None
    return BeautifulSoup(r.text, "html.parser")


# ---------------------------------------------------------------------------
# Modelo y parsing
# ---------------------------------------------------------------------------
FIELDS = [
    "link", "title", "precio", "habitaciones", "banos", "area",
    "estrato", "administracion", "antiguedad", "ubicacion", "parqueaderos",
]


@dataclass
class Property:
    link: str
    title: str = ""
    precio: str = ""
    habitaciones: str = ""
    banos: str = ""
    area: str = ""
    estrato: str = ""
    administracion: str = ""
    antiguedad: str = ""
    ubicacion: str = ""
    parqueaderos: str = ""


DETAIL_KEYS = {
    "precio":          "precio",
    "habitaciones":    "habitaciones",
    "banos":           "banos",
    "baños":           "banos",
    "area construida": "area",
    "área construida": "area",
    "area":            "area",
    "área":            "area",
    "estrato":         "estrato",
    "administracion":  "administracion",
    "administración":  "administracion",
    "antiguedad":      "antiguedad",
    "antigüedad":      "antiguedad",
    "ubicacion":       "ubicacion",
    "ubicación":       "ubicacion",
    "parqueaderos":    "parqueaderos",
}


def _norm(text: str) -> str:
    return text.strip().lower()


def get_property_links(soup: BeautifulSoup) -> list[str]:
    cards = soup.select("div.listingCard a.lc-data")
    return [BASE_URL + c["href"] for c in cards if c.get("href")]


def parse_property(soup: BeautifulSoup, url: str) -> Property:
    prop = Property(link=url)

    if (h1 := soup.find("h1")) is not None:
        prop.title = h1.get_text(strip=True)

    for sel in (".property-price-tag", ".price", "span.ant-typography strong"):
        if (node := soup.select_one(sel)) is not None:
            txt = node.get_text(strip=True)
            if txt:
                prop.precio = txt
                break

    typology = [t.get_text(strip=True) for t in soup.select(".property-typology-tag-desktop span")]
    if len(typology) >= 3:
        prop.habitaciones = prop.habitaciones or typology[0]
        prop.banos        = prop.banos        or typology[1]
        prop.area         = prop.area         or typology[2]

    for row in soup.select("div.ant-row.ant-row-space-between"):
        spans = row.find_all("span")
        if len(spans) != 2:
            continue
        key = _norm(spans[0].get_text())
        val = spans[1].get_text(strip=True)
        if (field_name := DETAIL_KEYS.get(key)) and not getattr(prop, field_name):
            setattr(prop, field_name, val)

    return prop


# ---------------------------------------------------------------------------
# Sink CSV incremental
# ---------------------------------------------------------------------------
class CsvSink:
    def __init__(self, path: Path, fieldnames: list[str]):
        self.path = path
        self.fieldnames = fieldnames
        self._fh = path.open("w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._fh, fieldnames=fieldnames)
        self._writer.writeheader()
        self._fh.flush()
        self.count = 0

    def write(self, prop: Property) -> None:
        self._writer.writerow(asdict(prop))
        self._fh.flush()
        self.count += 1

    def close(self) -> None:
        self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


# ---------------------------------------------------------------------------
# Scrape
# ---------------------------------------------------------------------------
def scrape(start_url: str = START_URL, output: Path = OUTPUT_RAW, max_pages: int = MAX_PAGES) -> Path:
    session = build_session()
    seen_links: set[str] = set()

    with CsvSink(output, FIELDS) as sink:
        for page in range(1, max_pages + 1):
            url = f"{start_url}/pagina{page}"
            log.info("Pagina %d -> %s", page, url)
            soup = fetch(session, url)
            if soup is None:
                log.warning("Saltando pagina %d por error de red", page)
                continue

            links = get_property_links(soup)
            if not links:
                log.info("Pagina sin links, fin del scraping")
                break
            new_links = [l for l in links if l not in seen_links]
            if not new_links:
                log.info("Solo duplicados, fin del scraping")
                break

            for link in new_links:
                seen_links.add(link)
                time.sleep(random.uniform(*SLEEP_RANGE))
                detail = fetch(session, link)
                if detail is None:
                    continue
                try:
                    prop = parse_property(detail, link)
                    sink.write(prop)
                    log.info("  %s | %s", prop.precio or "?", prop.title[:60])
                except (AttributeError, KeyError) as exc:
                    log.warning("Error parseando %s -> %s", link, exc)

            time.sleep(random.uniform(*SLEEP_RANGE))

        log.info("Scrape listo: %d propiedades en %s", sink.count, output)
    return output


# ---------------------------------------------------------------------------
# Limpieza
# ---------------------------------------------------------------------------
def limpiar_precio(precio_str):
    if not precio_str or pd.isna(precio_str):
        return None
    match = re.search(r"(\d[\d\.\,]{5,})", str(precio_str))
    if not match:
        return None
    digits = re.sub(r"[^\d]", "", match.group(1))
    return int(digits) if digits else None


def limpiar_area(area_str):
    """Convierte '97.54 m²', '97,54 m²', '120 m2', '1.250 mts2' a float.

    Heuristica para el separador (en Colombia conviven ambos formatos):
      - Si hay punto Y coma -> el ultimo es decimal, el otro es miles.
      - Si solo hay un separador con 1-2 digitos a la derecha -> decimal.
      - Si solo hay un separador con 3 digitos a la derecha -> miles (ej. '1.250').
    """
    if not area_str or pd.isna(area_str):
        return None
    # Acepta '120 m2', '120 m²', '120 m', '114 mts2', '80 MT2', '97.54 m² construidos'.
    # Probamos primero con sufijo de unidad de area completo; si falla, sin sufijo.
    pattern_full = r"([\d\.\,]+)\s*m(?:ts?)?[²2]"
    pattern_loose = r"([\d\.\,]+)\s*m(?:ts?)?\b"
    match = (
        re.search(pattern_full, str(area_str), flags=re.IGNORECASE)
        or re.search(pattern_loose, str(area_str), flags=re.IGNORECASE)
    )
    if not match:
        return None

    raw = match.group(1)
    has_dot = "." in raw
    has_comma = "," in raw

    if has_dot and has_comma:
        # El que aparece de ultimo es el decimal
        if raw.rfind(",") > raw.rfind("."):
            normalized = raw.replace(".", "").replace(",", ".")
        else:
            normalized = raw.replace(",", "")
    elif has_comma:
        # Una sola coma: tratarla como decimal (formato es-CO)
        normalized = raw.replace(",", ".")
    elif has_dot:
        # Un solo punto: decimal si tiene 1-2 digitos a la derecha; miles si tiene 3.
        right = raw.rsplit(".", 1)[1]
        normalized = raw if len(right) <= 2 else raw.replace(".", "")
    else:
        normalized = raw

    try:
        return float(normalized)
    except ValueError:
        return None


def limpiar_numero(texto):
    if not texto or pd.isna(texto):
        return None
    match = re.search(r"(\d+)", str(texto))
    return int(match.group(1)) if match else None


def clean(input_file: Path = OUTPUT_RAW, output_file: Path = OUTPUT_CLEAN) -> pd.DataFrame:
    df_raw = pd.read_csv(input_file)

    df = pd.DataFrame({
        "link":         df_raw["link"],
        "title":        df_raw["title"] if "title" in df_raw.columns else "",
        "precio":       df_raw["precio"].apply(limpiar_precio),
        "habitaciones": df_raw["habitaciones"].apply(limpiar_numero),
        "banos":        df_raw["banos"].apply(limpiar_numero),
        "area_m2":      df_raw["area"].apply(limpiar_area),
    })
    if "estrato" in df_raw.columns:
        df["estrato"] = df_raw["estrato"].apply(limpiar_numero)

    df = df.drop_duplicates(subset="link").reset_index(drop=True)
    df["valor_m2"] = (df["precio"] / df["area_m2"]).round(2)

    df.to_csv(output_file, index=False, encoding="utf-8")
    log.info("Limpieza lista: %d filas en %s", len(df), output_file)
    return df


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    scrape()
    clean()


if __name__ == "__main__":
    main()
