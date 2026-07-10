"""Scraper de metrocuadrado.com via JSON embebido en el HTML server-side.

Metrocuadrado es una SPA Next.js: el HTML inicial incluye las primeras
~59 propiedades serializadas dentro de los chunks de streaming RSC
(campo ``initialResults``). Los datos ya vienen numericos (precio en
COP, area en m2), asi que no requiere visitar paginas de detalle.

Limitacion: el API REST de paginacion requiere sesion/headers que no
se pueden replicar con ``requests`` puro, asi que solo se obtienen las
propiedades embebidas (1 request por zona). Para el uso diario
(~60-120 props entre Usaquen y Chapinero) es suficiente.

Genera ``metrocuadrado_raw.csv`` con el mismo esquema que fincaraiz
para que ``homeradar.clean()`` pueda fusionar ambos.
"""
from __future__ import annotations

import csv
import logging
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ---------------------------------------------------------------------------
# Configuracion
# ---------------------------------------------------------------------------
BASE_URL = "https://www.metrocuadrado.com"
ZONAS = [
    "https://www.metrocuadrado.com/apartamento/venta/bogota/usaquen/?search=form",
    "https://www.metrocuadrado.com/apartamento/venta/usado/bogota/chapinero/?search=form",
]
OUTPUT_RAW = Path("metrocuadrado_raw.csv")
REQUEST_TIMEOUT = 20
SLEEP_RANGE = (1.0, 2.5)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
)

FIELDS = [
    "link", "title", "precio", "habitaciones", "banos", "area",
    "estrato", "administracion", "antiguedad", "ubicacion", "parqueaderos",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("metrocuadrado")


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


# ---------------------------------------------------------------------------
# Modelo
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Parsing del JSON embebido
# ---------------------------------------------------------------------------
# Orden de campos en el chunk serializado (escapes \\"):
#   title -> link -> midinmueble -> mvalorventa -> marea ->
#   mnrocuartos -> mnrobanos -> mnrogarajes -> mbarrio
PROP_RE = re.compile(
    r'\\"title\\":\\"([^"]*)\\",\\"link\\":\\"([^"]*)\\".*?'
    r'\\"mvalorventa\\":(\d+),\\"mvalorarriendo\\".*?'
    r'\\"marea\\":(\d+),\\"mareac\\":(\d+),\\"areaprivada\\":[^,]+,\\"mnrocuartos\\":\\"([^"]*)\\",'
    r'\\"mnrobanos\\":\\"([^"]*)\\",\\"mnrogarajes\\":\\"([^"]*)\\".*?'
    r'\\"mbarrio\\":\\"([^"]*)\\"'
)


def parse_listing(html: str, zona_name: str) -> list[Property]:
    """Extrae las propiedades del JSON embebido en el HTML."""
    idx = html.find("initialResults")
    if idx < 0:
        log.warning("No se encontro 'initialResults' en %s", zona_name)
        return []
    chunk = html[idx:]
    matches = PROP_RE.findall(chunk)
    props: list[Property] = []
    for m in matches:
        title, link, precio, area, _area_c, habs, banos, garajes, barrio = m
        props.append(Property(
            link=BASE_URL + link,
            title=title,
            precio=str(int(precio)),
            habitaciones=habs,
            banos=banos,
            area=f"{area} m2",
            ubicacion=f"{barrio}, {zona_name}",
            parqueaderos=garajes,
        ))
    log.info("  %s: %d propiedades", zona_name, len(props))
    return props


# ---------------------------------------------------------------------------
# Sink CSV
# ---------------------------------------------------------------------------
class CsvSink:
    def __init__(self, path: Path, fieldnames: list[str]):
        self.path = path
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
def _zona_name(url: str) -> str:
    # extrae 'usaquen' o 'chapinero' de la URL
    m = re.search(r"/bogota/([a-z-]+)/?", url)
    return m.group(1) if m else "zona"


def scrape(urls: list[str] = ZONAS, output: Path = OUTPUT_RAW) -> Path:
    session = build_session()
    with CsvSink(output, FIELDS) as sink:
        for url in urls:
            zona = _zona_name(url)
            log.info("Scrapeando metrocuadrado: %s -> %s", zona, url)
            try:
                r = session.get(url, timeout=REQUEST_TIMEOUT)
                r.raise_for_status()
            except requests.RequestException as exc:
                log.warning("GET fallo %s -> %s", url, exc)
                continue

            props = parse_listing(r.text, zona)
            for p in props:
                sink.write(p)
                log.info("  $%s | %s", f"{int(p.precio):,}" if p.precio.isdigit() else "?", p.title[:60])

            time.sleep(__import__("random").uniform(*SLEEP_RANGE))

        log.info("Scrape metrocuadrado listo: %d propiedades en %s", sink.count, output)
    return output


if __name__ == "__main__":
    scrape()
