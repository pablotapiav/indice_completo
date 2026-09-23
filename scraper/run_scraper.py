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

from scraper.parsing import filtrar_y_normalizar  # noqa: E402
from scraper.vtex_client import VtexClientError, buscar_productos  # noqa: E402

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


def ejecutar_scraping() -> list[dict]:
    config = cargar_config()
    categorias = config["categorias"]
    cadenas = {k: v for k, v in config["cadenas"].items() if v.get("metodo") == "automatico"}
    cadenas_manuales = {k: v for k, v in config["cadenas"].items() if v.get("metodo") == "manual_pendiente"}
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

    for clave_cadena, cadena in cadenas.items():
        cuenta = cadena["cuenta_vtex"]
        for clave_categoria, cat_config in categorias.items():
            termino = cat_config["termino_busqueda"]
            try:
                ofertas = buscar_productos(cuenta, termino, cantidad=15)
            except VtexClientError as exc:
                print(f"[WARN] {clave_cadena}/{clave_categoria}: {exc}", file=sys.stderr)
                continue

            resultado = filtrar_y_normalizar(ofertas, cat_config)
            if resultado is None:
                print(
                    f"[WARN] {clave_cadena}/{clave_categoria}: sin resultados utiles "
                    f"tras filtrar ({len(ofertas)} ofertas crudas)",
                    file=sys.stderr,
                )
                continue

            fila = {
                "fecha": hoy,
                "cadena": clave_cadena,
                "categoria": clave_categoria,
                "precio_unitario": resultado.precio_unitario,
                "unidad": resultado.unidad,
                "n_muestras": resultado.n_muestras,
                "productos_usados": resultado.productos_usados,
            }
            filas.append(fila)
            print(
                f"[OK] {clave_cadena}/{clave_categoria}: "
                f"${resultado.precio_unitario} por {resultado.unidad} "
                f"(mediana de {resultado.n_muestras} productos)"
            )

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
