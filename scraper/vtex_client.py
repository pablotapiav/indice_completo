"""
Cliente minimo, de solo lectura, para el API publico de busqueda de catalogo
de tiendas VTEX (usado por Jumbo.cl y SantaIsabel.cl).

Decisiones de seguridad / buenas practicas:
- Sin dependencias externas (solo stdlib) para minimizar riesgo de cadena de
  suministro en un repo publico.
- Solo se golpean endpoints de LECTURA de catalogo (busqueda de productos).
  Nunca carrito, cuenta, checkout ni ningun endpoint que requiera sesion o
  credenciales.
- User-Agent identificable con proposito y contacto, para que cualquier
  administrador del sitio pueda saber que es este proyecto y bloquearlo o
  contactarnos si asi lo prefiere.
- Rate limiting conservador entre requests (ver REQUEST_DELAY_SECONDS).
- Reintentos acotados con backoff simple; nunca reintentos infinitos.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

USER_AGENT = (
    "IndiceDelCompletoBot/1.0 "
    "(+https://github.com/; proyecto sin fines de lucro, solo lee catalogo "
    "publico de productos, respeta robots.txt, contacto via issues de GitHub)"
)

REQUEST_DELAY_SECONDS = 1.5
REQUEST_TIMEOUT_SECONDS = 15
MAX_RETRIES = 3


class VtexClientError(Exception):
    pass


@dataclass
class Oferta:
    product_id: str
    nombre: str
    categorias: list[str]
    precio: float
    ean: str | None


def _get_json(url: str) -> Any:
    last_error: Exception | None = None
    for intento in range(1, MAX_RETRIES + 1):
        req = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
                raw = resp.read()
                return json.loads(raw.decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            last_error = exc
            time.sleep(intento * 2)
        finally:
            time.sleep(REQUEST_DELAY_SECONDS)
    raise VtexClientError(f"No se pudo consultar {url}: {last_error}")


def buscar_productos(cuenta_vtex: str, termino: str, cantidad: int = 15) -> list[Oferta]:
    """Busca productos por texto libre en el catalogo publico VTEX de una cuenta.

    Usa el dominio *.vtexcommercestable.com.br directamente (no el frontend
    de la tienda), que expone JSON de catalogo sin necesidad de ejecutar
    JavaScript. Es el mismo mecanismo que usan comparadores de precios y
    integraciones de terceros publicadas por VTEX.
    """
    url = (
        f"https://{cuenta_vtex}.vtexcommercestable.com.br"
        f"/api/catalog_system/pub/products/search"
        f"?ft={urllib.parse.quote(termino)}&_from=0&_to={max(cantidad - 1, 0)}"
    )
    data = _get_json(url)
    ofertas: list[Oferta] = []
    for producto in data:
        items = producto.get("items") or []
        if not items:
            continue
        item = items[0]
        sellers = item.get("sellers") or []
        if not sellers:
            continue
        oferta_comercial = sellers[0].get("commertialOffer", {})
        precio = oferta_comercial.get("Price")
        disponible = oferta_comercial.get("IsAvailable", True)
        if precio is None or not disponible:
            continue
        ofertas.append(
            Oferta(
                product_id=str(producto.get("productId")),
                nombre=producto.get("productName", ""),
                categorias=producto.get("categories", []),
                precio=float(precio),
                ean=item.get("ean"),
            )
        )
    return ofertas
