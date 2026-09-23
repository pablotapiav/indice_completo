"""
Calcula el Indice del Completo (IdC): un indice de precios tipo Laspeyres,
base 100, sobre una canasta fija (racion de completo italiano: salchicha +
mayonesa + palta + tomate).

Formula (Laspeyres, canasta fija q0 del periodo base):

    IdC_t = 100 * sum(q0_i * p_i,t) / sum(q0_i * p_i,0)

donde p_i,t es el precio del insumo i en el periodo t y q0_i es la cantidad
fija de la racion (data/productos.json).

Enfoque: comparador ENTRE CADENAS (Lider, Jumbo, Unimarc, Santa Isabel,
Mayorista 10, aCuenta, Alvi, Tottus), no entre regiones. El intento original
de regionalizar el indice se abandonó tras comprobar que no hay forma legítima
de obtener precio real por región (ver docs/LIMITACION_REGIONAL.md). El
indice nacional de la serie temporal se calcula como el promedio del costo de
la ración entre las cadenas que sí tienen dato ese día (scrapeado o cargado a
mano vía data/precios_manuales_cadena.csv).

Salida: data/indice_completo.json
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
RUTA_HISTORICO = RAIZ / "data" / "precios_historico.csv"
RUTA_MANUAL_CADENA = RAIZ / "data" / "precios_manuales_cadena.csv"
RUTA_PRODUCTOS = RAIZ / "data" / "productos.json"
RUTA_SALIDA = RAIZ / "data" / "indice_completo.json"

CATEGORIAS_UNIDAD_KG = {"palta", "tomate"}  # precio_unitario esta en CLP/kg
CATEGORIAS_UNIDAD_100G = {"salchicha", "mayonesa"}  # precio_unitario esta en CLP/100g

COLUMNAS_HISTORICO = ["fecha", "cadena", "categoria", "precio_unitario", "unidad", "n_muestras"]


def cargar_config() -> dict:
    return json.loads(RUTA_PRODUCTOS.read_text(encoding="utf-8"))


def cargar_racion(config: dict) -> dict[str, float]:
    racion = config["racion_completo_italiano"]
    return {
        "salchicha": racion["salchicha_g"],
        "mayonesa": racion["mayonesa_g"],
        "palta": racion["palta_g"],
        "tomate": racion["tomate_g"],
    }


def costo_racion(precios_por_categoria: dict[str, float], gramos_racion: dict[str, float]) -> float | None:
    total = 0.0
    for categoria, gramos in gramos_racion.items():
        precio = precios_por_categoria.get(categoria)
        if precio is None:
            return None  # canasta incompleta esa fecha/cadena -> no se calcula ese punto
        if categoria in CATEGORIAS_UNIDAD_KG:
            total += precio * (gramos / 1000)
        else:
            total += precio * (gramos / 100)
    return round(total, 2)


def _leer_csv_precios(ruta: Path) -> list[dict]:
    if not ruta.exists():
        return []
    with ruta.open(encoding="utf-8") as f:
        return [
            {
                "fecha": fila["fecha"],
                "cadena": fila["cadena"],
                "categoria": fila["categoria"],
                "precio_unitario": float(fila["precio_unitario"]),
            }
            for fila in csv.DictReader(f)
            if fila.get("fecha") and fila.get("precio_unitario")
        ]


def cargar_precios_por_cadena() -> dict[str, dict[str, dict[str, float]]]:
    """{cadena: {fecha: {categoria: precio_unitario}}}, fusionando scraper + captura manual.

    Si una fecha/cadena/categoria existe en ambas fuentes, gana el dato scrapeado
    (data/precios_historico.csv) por ser el mecanismo primario; el CSV manual solo
    rellena lo que el scraper no puede tocar (cadenas bloqueadas o con robots.txt
    restrictivo, ver data/productos.json -> cadenas -> metodo).
    """
    resultado: dict[str, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    for fila in _leer_csv_precios(RUTA_MANUAL_CADENA):
        resultado[fila["cadena"]][fila["fecha"]][fila["categoria"]] = fila["precio_unitario"]
    for fila in _leer_csv_precios(RUTA_HISTORICO):
        resultado[fila["cadena"]][fila["fecha"]][fila["categoria"]] = fila["precio_unitario"]
    return resultado


def construir_serie_cadena(fechas_ordenadas: list[str], precios_cadena: dict[str, dict[str, float]], gramos_racion: dict[str, float]) -> list[dict]:
    serie = []
    for fecha in fechas_ordenadas:
        costo = costo_racion(precios_cadena.get(fecha, {}), gramos_racion)
        if costo is not None:
            serie.append({"fecha": fecha, "precio_completo_clp": costo})
    return serie


def main() -> int:
    config = cargar_config()
    gramos_racion = cargar_racion(config)
    precios_por_cadena = cargar_precios_por_cadena()

    if not precios_por_cadena:
        print("[ERROR] No hay datos de precios (ni scrapeados ni manuales). Corre primero el scraper.", file=sys.stderr)
        return 1

    todas_las_fechas = sorted({f for cadena in precios_por_cadena.values() for f in cadena})

    series_por_cadena: dict[str, list[dict]] = {}
    for cadena, precios in precios_por_cadena.items():
        serie = construir_serie_cadena(todas_las_fechas, precios, gramos_racion)
        if serie:
            series_por_cadena[cadena] = serie

    if not series_por_cadena:
        print("[ERROR] Ninguna cadena tiene canasta completa (faltan categorias) en ninguna fecha.", file=sys.stderr)
        return 1

    # Serie nacional de referencia: promedio del costo de la racion entre las
    # cadenas que tienen dato completo cada fecha (se recalcula con las
    # cadenas disponibles ese dia, no exige que todas tengan historico).
    costo_por_fecha: dict[str, list[float]] = defaultdict(list)
    for serie in series_por_cadena.values():
        for punto in serie:
            costo_por_fecha[punto["fecha"]].append(punto["precio_completo_clp"])

    fechas_con_dato = sorted(costo_por_fecha.keys())
    costo_promedio_por_fecha = {f: round(sum(v) / len(v), 2) for f, v in costo_por_fecha.items()}
    costo_base = costo_promedio_por_fecha[fechas_con_dato[0]]

    serie_nacional = [
        {
            "fecha": fecha,
            "precio_completo_clp": costo_promedio_por_fecha[fecha],
            "indice": round(100 * costo_promedio_por_fecha[fecha] / costo_base, 2),
        }
        for fecha in fechas_con_dato
    ]

    # Snapshot "hoy" por cadena, para el comparador. Incluye TODAS las cadenas
    # definidas en productos.json (incluidas las pendientes de captura manual,
    # con precio null) para que la ausencia de dato quede visible, no oculta.
    cadenas_catalogo = []
    for clave, meta in config["cadenas"].items():
        serie = series_por_cadena.get(clave, [])
        ultimo = serie[-1] if serie else None
        cadenas_catalogo.append(
            {
                "clave": clave,
                "nombre": meta["nombre"],
                "url": meta.get("url"),
                "metodo": meta.get("metodo"),
                "razon_pendiente": meta.get("razon"),
                "precio_completo_clp": ultimo["precio_completo_clp"] if ultimo else None,
                "fecha": ultimo["fecha"] if ultimo else None,
            }
        )
    cadenas_catalogo.sort(key=lambda c: (c["precio_completo_clp"] is None, c["precio_completo_clp"] or 0))

    salida = {
        "_descripcion": "Indice del Completo (IdC): Laspeyres base 100 sobre salchicha+mayonesa+palta+tomate, comparado ENTRE CADENAS.",
        "_metodologia": "docs/METODOLOGIA.md",
        "_nota_regional": "docs/LIMITACION_REGIONAL.md",
        "base_periodo": fechas_con_dato[0],
        "costo_racion_base_clp": costo_base,
        "generado_en": datetime.now(timezone.utc).isoformat(),
        "serie_nacional": serie_nacional,
        "cadenas": cadenas_catalogo,
    }
    RUTA_SALIDA.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Indice calculado: {RUTA_SALIDA}")
    print(f"Base: {fechas_con_dato[0]} -> costo racion promedio = ${costo_base} CLP")
    print(f"Cadenas con dato: {', '.join(series_por_cadena.keys())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
