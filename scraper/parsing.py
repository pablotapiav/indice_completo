"""
Normalizacion de resultados de busqueda a un precio comparable por categoria.

Cada categoria de la canasta (salchicha, mayonesa, palta, tomate) se expresa
en una unidad fija (CLP/100g o CLP/kg) para poder sumarlas de forma consistente
en el indice, aunque los envases scrapeados tengan gramajes distintos.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass

from scraper.vtex_client import Oferta

_PATRON_KG = re.compile(r"(\d+(?:[.,]\d+)?)\s*kg", re.IGNORECASE)
_PATRON_G = re.compile(r"(\d+(?:[.,]\d+)?)\s*g\b", re.IGNORECASE)
_PATRON_ML = re.compile(r"(\d+(?:[.,]\d+)?)\s*ml", re.IGNORECASE)


def extraer_gramos(nombre: str) -> float | None:
    """Extrae el gramaje/volumen de un nombre de producto. ml se asume ~1g/ml."""
    m = _PATRON_KG.search(nombre)
    if m:
        return float(m.group(1).replace(",", ".")) * 1000
    m = _PATRON_G.search(nombre)
    if m:
        return float(m.group(1).replace(",", "."))
    m = _PATRON_ML.search(nombre)
    if m:
        return float(m.group(1).replace(",", "."))
    return None


def _cumple_categoria(oferta: Oferta, whitelist: list[str]) -> bool:
    if not whitelist:
        return True
    if not oferta.categorias:
        # La fuente no entrega arbol de categorias (ej. aCuenta, via JSON-LD
        # de pagina de producto) - se confia en los filtros de nombre y en
        # que el SKU ya fue verificado a mano antes de agregarse.
        return True
    ruta = " > ".join(oferta.categorias).lower()
    return any(w.lower() in ruta for w in whitelist)


def _cumple_nombre(nombre_lower: str, incluye: list[str], excluye: list[str]) -> bool:
    if incluye and not any(p in nombre_lower for p in incluye):
        return False
    if excluye and any(p in nombre_lower for p in excluye):
        return False
    return True


@dataclass
class PrecioNormalizado:
    precio_unitario: float  # CLP por 100g o CLP por kg, segun `unidad`
    unidad: str
    n_muestras: int
    productos_usados: list[str]


def filtrar_y_normalizar(
    ofertas: list[Oferta], config_categoria: dict
) -> PrecioNormalizado | None:
    """Filtra ofertas irrelevantes y calcula la MEDIANA del precio normalizado.

    Se usa la mediana (no el promedio ni un SKU fijo) para reducir el sesgo
    de sustitucion: si un producto puntual sale del catalogo o cambia de
    presentacion, el indice no se rompe ni se distorsiona por un outlier.
    Es una simplificacion metodologica documentada en docs/METODOLOGIA.md.
    """
    whitelist = config_categoria.get("categoria_whitelist", [])
    incluye = [p.lower() for p in config_categoria.get("nombre_incluye", [])]
    excluye = [p.lower() for p in config_categoria.get("nombre_excluye", [])]
    unidad = config_categoria["unidad"]  # "100g" o "kg"

    normalizados: list[tuple[float, str]] = []
    for oferta in ofertas:
        nombre_lower = oferta.nombre.lower()
        if not _cumple_categoria(oferta, whitelist):
            continue
        if not _cumple_nombre(nombre_lower, incluye, excluye):
            continue

        if unidad == "kg":
            # Si el nombre trae un gramaje explicito (ej. "Malla 1 kg", o
            # "Granel 500 g (2 a 3 un aprox)") se usa siempre ese numero para
            # normalizar - es confiable independiente de si ademas menciona
            # un conteo de unidades aproximado. Solo cuando NO hay gramaje
            # explicito se recurre a la convencion chilena de que "Granel"
            # ya viene listado por kg - y esa convencion se descarta si el
            # nombre sugiere que el precio es por unidad/bolsa (ambiguo).
            gramos = extraer_gramos(nombre_lower)
            if gramos:
                precio_kg = oferta.precio / gramos * 1000
            elif re.search(r"\bun\.?\b|\bunidad(es)?\b", nombre_lower):
                continue  # ambiguo: no se sabe si el precio es por kg o por bolsa/unidad
            else:
                precio_kg = oferta.precio
            normalizados.append((precio_kg, oferta.nombre))
        else:  # "100g"
            gramos = extraer_gramos(nombre_lower)
            if not gramos:
                continue
            precio_100g = oferta.precio / gramos * 100
            normalizados.append((precio_100g, oferta.nombre))

    if not normalizados:
        return None

    valores = [v for v, _ in normalizados]
    return PrecioNormalizado(
        precio_unitario=round(statistics.median(valores), 2),
        unidad=unidad,
        n_muestras=len(normalizados),
        productos_usados=[n for _, n in normalizados],
    )
