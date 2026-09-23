"""
Punto de entrada del scraper del Indice del Completo (IdC).

Recorre cada cadena configurada (Jumbo, Santa Isabel) x cada categoria de la
canasta (salchicha, mayonesa, palta, tomate), obtiene un precio normalizado
por categoria, y deja dos artefactos:

  data/precios/precios_<YYYY-MM-DD>.json   -> snapshot crudo del dia (auditable)
  data/precios_historico.csv               -> serie historica acumulada (append-only)

Nota de cobertura regional: el catalogo online de estas cadenas es nacional
(un unico precio de lista por SKU, sin variacion confirmada por region -
ver docs/METODOLOGIA.md). Por eso el mismo precio normalizado se usa como
referencia para las 16 regiones; el modulo index/compute_index.py deja el
punto de extension para incorporar precios regionales reales via
data/precios_manual_regional.csv cuando existan.

Uso:
    python -m scraper.run_scraper
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from scraper.acuenta_client import AcuentaClientError, obtener_producto_por_sku  # noqa: E402
from scraper.parsing import filtrar_y_normalizar  # noqa: E402
from scraper.vtex_client import Oferta, VtexClientError, buscar_productos  # noqa: E402

RUTA_PRODUCTOS = RAIZ / "data" / "productos.json"
RUTA_SNAPSHOTS = RAIZ / "data" / "precios"
RUTA_HISTORICO = RAIZ / "data" / "precios_historico.csv"

COLUMNAS_HISTORICO = [
    "fecha",
    "cadena",
    "categoria",
    "precio_unitario",
    "unidad",
    "n_muestras",
]


def cargar_config() -> dict:
    return json.loads(RUTA_PRODUCTOS.read_text(encoding="utf-8"))


def _registrar_resultado(filas: list[dict], hoy: str, clave_cadena: str, clave_categoria: str, ofertas: list[Oferta], cat_config: dict) -> None:
    resultado = filtrar_y_normalizar(ofertas, cat_config)
    if resultado is None:
        print(
            f"[WARN] {clave_cadena}/{clave_categoria}: sin resultados utiles "
            f"tras filtrar ({len(ofertas)} ofertas crudas)",
            file=sys.stderr,
        )
        return

    filas.append(
        {
            "fecha": hoy,
            "cadena": clave_cadena,
            "categoria": clave_categoria,
            "precio_unitario": resultado.precio_unitario,
            "unidad": resultado.unidad,
            "n_muestras": resultado.n_muestras,
            "productos_usados": resultado.productos_usados,
        }
    )
    print(
        f"[OK] {clave_cadena}/{clave_categoria}: "
        f"${resultado.precio_unitario} por {resultado.unidad} "
        f"(mediana de {resultado.n_muestras} productos)"
    )


def _scrapear_vtex(cadenas: dict, categorias: dict, filas: list[dict], hoy: str) -> None:
    for clave_cadena, cadena in cadenas.items():
        cuenta = cadena["cuenta_vtex"]
        for clave_categoria, cat_config in categorias.items():
            termino = cat_config["termino_busqueda"]
            try:
                ofertas = buscar_productos(cuenta, termino, cantidad=15)
            except VtexClientError as exc:
                print(f"[WARN] {clave_cadena}/{clave_categoria}: {exc}", file=sys.stderr)
                continue
            _registrar_resultado(filas, hoy, clave_cadena, clave_categoria, ofertas, cat_config)


def _scrapear_sku_fijo(cadenas: dict, categorias: dict, filas: list[dict], hoy: str) -> None:
    """Cadenas sin busqueda utilizable (ej. aCuenta): se consulta una lista
    fija de SKUs por categoria (data/productos.json) y se lee el JSON-LD de
    cada pagina de producto individual."""
    for clave_cadena, cadena in cadenas.items():
        skus_por_categoria = cadena.get("skus_por_categoria", {})
        for clave_categoria, cat_config in categorias.items():
            skus = skus_por_categoria.get(clave_categoria, [])
            if not skus:
                print(f"[WARN] {clave_cadena}/{clave_categoria}: sin SKUs configurados", file=sys.stderr)
                continue

            ofertas: list[Oferta] = []
            for sku in skus:
                try:
                    producto = obtener_producto_por_sku(sku)
                except AcuentaClientError as exc:
                    print(f"[WARN] {clave_cadena}/{clave_categoria}/sku={sku}: {exc}", file=sys.stderr)
                    continue
                if producto is None:
                    print(f"[WARN] {clave_cadena}/{clave_categoria}/sku={sku}: SKU sin datos (¿descontinuado?)", file=sys.stderr)
                    continue
                if not producto.disponible:
                    continue
                # Sin arbol de categorias real (no viene en el JSON-LD): se
                # deja vacio y el filtro de categoria se salta para esta
                # oferta (ver parsing._cumple_categoria), confiando en que
                # el SKU ya fue verificado a mano antes de agregarlo.
                ofertas.append(Oferta(product_id=producto.sku, nombre=producto.nombre, categorias=[], precio=producto.precio, ean=None))

            _registrar_resultado(filas, hoy, clave_cadena, clave_categoria, ofertas, cat_config)


def ejecutar_scraping() -> list[dict]:
    config = cargar_config()
    categorias = config["categorias"]
    todas_cadenas = config["cadenas"]

    cadenas_vtex = {k: v for k, v in todas_cadenas.items() if v.get("metodo") == "automatico"}
    cadenas_sku_fijo = {k: v for k, v in todas_cadenas.items() if v.get("metodo") == "automatico_sku_fijo"}
    cadenas_manuales = {k: v for k, v in todas_cadenas.items() if v.get("metodo") == "manual_pendiente"}
    if cadenas_manuales:
        print(
            f"[INFO] {len(cadenas_manuales)} cadena(s) quedan fuera del scraper automático "
            f"({', '.join(c['nombre'] for c in cadenas_manuales.values())}) - ver razones en "
            "data/productos.json y docs/LIMITACION_REGIONAL.md. Precio vía "
            "data/precios_manuales_cadena.csv si alguien lo captura a mano.",
            file=sys.stderr,
        )

    filas: list[dict] = []
    hoy = date.today().isoformat()

    _scrapear_vtex(cadenas_vtex, categorias, filas, hoy)
    _scrapear_sku_fijo(cadenas_sku_fijo, categorias, filas, hoy)

    return filas


def guardar_snapshot(filas: list[dict]) -> Path:
    RUTA_SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    hoy = date.today().isoformat()
    ruta = RUTA_SNAPSHOTS / f"precios_{hoy}.json"
    payload = {
        "generado_en": datetime.now(timezone.utc).isoformat(),
        "filas": filas,
    }
    ruta.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return ruta


def append_historico(filas: list[dict]) -> None:
    """Agrega filas nuevas al histórico, reemplazando cualquier fila previa con
    la misma (fecha, cadena, categoria) - así correr el scraper dos veces el
    mismo día no deja duplicados."""
    claves_nuevas = {(f["fecha"], f["cadena"], f["categoria"]) for f in filas}

    filas_previas: list[dict] = []
    if RUTA_HISTORICO.exists():
        with RUTA_HISTORICO.open(encoding="utf-8") as f:
            for fila in csv.DictReader(f):
                clave = (fila["fecha"], fila["cadena"], fila["categoria"])
                if clave not in claves_nuevas:
                    filas_previas.append(fila)

    todas = filas_previas + [{k: fila[k] for k in COLUMNAS_HISTORICO} for fila in filas]
    todas.sort(key=lambda f: (f["fecha"], f["cadena"], f["categoria"]))

    with RUTA_HISTORICO.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNAS_HISTORICO)
        writer.writeheader()
        writer.writerows(todas)


def main() -> int:
    filas = ejecutar_scraping()
    if not filas:
        print("[ERROR] El scraper no obtuvo ningun precio valido.", file=sys.stderr)
        return 1

    ruta_snapshot = guardar_snapshot(filas)
    append_historico(filas)
    print(f"\nSnapshot guardado en {ruta_snapshot}")
    print(f"Historico actualizado en {RUTA_HISTORICO}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
