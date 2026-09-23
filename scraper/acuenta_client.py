"""
Cliente minimo, de solo lectura, para paginas de producto individuales de
acuenta.cl (SuperBodega aCuenta).

A diferencia de Jumbo/Santa Isabel (VTEX, con API de busqueda), aCuenta no
tiene una API de catalogo alcanzable sin ejecutar JavaScript: su busqueda es
una SPA (plataforma Instaleap). Lo que SI trae cada pagina de producto,
servido en el HTML inicial sin necesidad de JS, es un bloque JSON-LD
(schema.org/Product) - metadata puesta ahi a proposito para que buscadores
la lean (es el mismo mecanismo que usa Google Shopping para mostrar precios
en resultados de busqueda). Este cliente solo lee ese bloque.

Como no hay busqueda, la lista de SKUs a consultar es fija y se mantiene a
mano en data/productos.json -> cadenas -> acuenta -> skus_por_categoria.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

USER_AGENT = (
    "IndiceDelCompletoBot/1.0 "
    "(+https://github.com/; proyecto sin fines de lucro, solo lee JSON-LD "
    "publico de paginas de producto, respeta robots.txt)"
)

REQUEST_DELAY_SECONDS = 1.5
REQUEST_TIMEOUT_SECONDS = 15
MAX_RETRIES = 3

_PATRON_JSONLD = re.compile(
    r'<script id="product-structured-data" type="application/ld\+json">(.*?)</script>',
    re.DOTALL,
)


class AcuentaClientError(Exception):
    pass


@dataclass
class ProductoAcuenta:
    sku: str
    nombre: str
    precio: float
    disponible: bool


def _get_html(url: str) -> str:
    last_error: Exception | None = None
    for intento in range(1, MAX_RETRIES + 1):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
                return resp.read().decode("utf-8", "ignore")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            last_error = exc
            time.sleep(intento * 2)
        finally:
            time.sleep(REQUEST_DELAY_SECONDS)
    raise AcuentaClientError(f"No se pudo consultar {url}: {last_error}")


def obtener_producto_por_sku(sku: str) -> ProductoAcuenta | None:
    """Lee https://www.acuenta.cl/p/<cualquier-slug>-<sku> - el slug es
    cosmetico, el sitio resuelve el producto por el ID numerico al final de
    la URL sin importar el texto que lo precede (verificado empiricamente)."""
    url = f"https://www.acuenta.cl/p/sku-{sku}"
    html = _get_html(url)

    m = _PATRON_JSONLD.search(html)
    if not m:
        return None  # producto descontinuado / SKU invalido / sin structured data

    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None

    oferta = data.get("offers", {})
    precio = oferta.get("priceSpecification", {}).get("price")
    if precio is None:
        return None

    disponible = oferta.get("availability", "").endswith("InStock")
    return ProductoAcuenta(
        sku=data.get("sku", sku),
        nombre=data.get("name", ""),
        precio=float(precio),
        disponible=disponible,
    )
