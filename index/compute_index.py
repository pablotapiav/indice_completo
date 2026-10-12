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
de obtener precio real por región (ver docs/LIMITACION_REGIONAL.md).

Indice nacional (serie temporal): ENCADENADO de modelo emparejado. La
variacion entre dos fechas consecutivas es la media geometrica de las
variaciones del costo de la racion SOLO de las cadenas con dato en ambas
fechas:

    IdC_t = IdC_{t-1} * geomean_c( costo_c,t / costo_c,t-1 )

Asi, que una cadena entre o salga de la muestra (scrapeada o cargada a mano
vía data/precios_manuales_cadena.csv) no mueve el indice por efecto
composicion. El "precio_completo_clp" nacional (promedio de niveles) se
conserva solo como dato informativo; NO se usa para calcular el indice.

Salida: data/indice_completo.json
"""

from __future__ import annotations

import csv
import json
import math
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


def calcular_desglose(precios_por_categoria: dict[str, float], gramos_racion: dict[str, float]) -> list[dict]:
    """Cuanto aporta cada insumo al costo de la racion, dado un precio por
    categoria ya resuelto (precio de una cadena puntual, o promedio entre
    varias para la serie nacional)."""
    desglose = []
    for categoria, gramos in gramos_racion.items():
        precio_unitario = precios_por_categoria.get(categoria)
        if precio_unitario is None:
            continue
        unidad = "kg" if categoria in CATEGORIAS_UNIDAD_KG else "100g"
        factor = gramos / 1000 if unidad == "kg" else gramos / 100
        desglose.append(
            {
                "categoria": categoria,
                "precio_unitario": precio_unitario,
                "unidad": unidad,
                "gramos_racion": gramos,
                "aporte_clp": round(precio_unitario * factor, 2),
            }
        )
    return desglose


def construir_serie_cadena(fechas_ordenadas: list[str], precios_cadena: dict[str, dict[str, float]], gramos_racion: dict[str, float]) -> list[dict]:
    serie = []
    for fecha in fechas_ordenadas:
        precios_fecha = precios_cadena.get(fecha, {})
        costo = costo_racion(precios_fecha, gramos_racion)
        if costo is not None:
            serie.append(
                {
                    "fecha": fecha,
                    "precio_completo_clp": costo,
                    "desglose": calcular_desglose(precios_fecha, gramos_racion),
                }
            )
    return serie


def indice_encadenado(
    fechas: list[str], costo_por_cadena_fecha: dict[str, dict[str, float]]
) -> tuple[dict[str, float], dict[str, bool]]:
    """Indice base 100 en fechas[0], encadenando la media geometrica de las
    variaciones de las cadenas presentes en AMBAS fechas consecutivas.

    Si dos fechas consecutivas no comparten ninguna cadena no hay como medir la
    variacion: se repite el indice anterior y se marca enlazado=False.
    """
    indices = {fechas[0]: 100.0}
    enlazado = {fechas[0]: True}
    for previa, actual in zip(fechas, fechas[1:]):
        comunes = set(costo_por_cadena_fecha[previa]) & set(costo_por_cadena_fecha[actual])
        if not comunes:
            indices[actual] = indices[previa]
            enlazado[actual] = False
            continue
        log_suma = sum(
            math.log(costo_por_cadena_fecha[actual][c] / costo_por_cadena_fecha[previa][c]) for c in comunes
        )
        indices[actual] = indices[previa] * math.exp(log_suma / len(comunes))
        enlazado[actual] = True
    return indices, enlazado


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
    # cadenas disponibles ese dia, no exige que todas tengan historico). El
    # desglose nacional promedia el precio POR CATEGORIA entre esas mismas
    # cadenas, para poder mostrar "como se compone" el punto nacional al
    # pasar el mouse sobre el grafico.
    costo_por_fecha: dict[str, list[float]] = defaultdict(list)
    categoria_por_fecha: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for cadena, serie in series_por_cadena.items():
        for punto in serie:
            costo_por_fecha[punto["fecha"]].append(punto["precio_completo_clp"])
            for item in punto["desglose"]:
                categoria_por_fecha[punto["fecha"]][item["categoria"]].append(item["precio_unitario"])

    fechas_con_dato = sorted(costo_por_fecha.keys())
    costo_promedio_por_fecha = {f: round(sum(v) / len(v), 2) for f, v in costo_por_fecha.items()}
    costo_base = costo_promedio_por_fecha[fechas_con_dato[0]]

    costo_cadena_fecha: dict[str, dict[str, float]] = defaultdict(dict)
    for cadena, serie in series_por_cadena.items():
        for punto in serie:
            costo_cadena_fecha[punto["fecha"]][cadena] = punto["precio_completo_clp"]
    indices, enlazado = indice_encadenado(fechas_con_dato, costo_cadena_fecha)

    serie_nacional = []
    for fecha in fechas_con_dato:
        precios_promedio_categoria = {
            cat: round(sum(valores) / len(valores), 2) for cat, valores in categoria_por_fecha[fecha].items()
        }
        punto_nacional = {
            "fecha": fecha,
            "precio_completo_clp": costo_promedio_por_fecha[fecha],
            "indice": round(indices[fecha], 2),
            "n_cadenas": len(costo_por_fecha[fecha]),
            "desglose": calcular_desglose(precios_promedio_categoria, gramos_racion),
        }
        if not enlazado[fecha]:
            punto_nacional["sin_enlace"] = True  # sin cadenas en comun con la fecha previa: indice repetido
        serie_nacional.append(punto_nacional)

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
                "razon_corta": meta.get("razon_corta"),
                "razon_pendiente": meta.get("razon"),
                "precio_completo_clp": ultimo["precio_completo_clp"] if ultimo else None,
                "fecha": ultimo["fecha"] if ultimo else None,
                "desglose": ultimo["desglose"] if ultimo else None,
                "serie": serie,
            }
        )
    cadenas_catalogo.sort(key=lambda c: (c["precio_completo_clp"] is None, c["precio_completo_clp"] or 0))

    salida = {
        "_descripcion": "Indice del Completo (IdC): canasta fija (Laspeyres por cadena) sobre salchicha+mayonesa+palta+tomate, comparado ENTRE CADENAS; indice nacional encadenado de modelo emparejado (media geometrica de variaciones de las cadenas presentes en ambas fechas), base 100.",
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
