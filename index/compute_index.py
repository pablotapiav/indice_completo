"""
Calcula el Indice del Completo (IdC): un indice de precios tipo Laspeyres,
base 100, sobre una canasta fija (racion de completo italiano: salchicha +
mayonesa + palta + tomate).

Formula (Laspeyres, canasta fija q0 del periodo base):

    IdC_t = 100 * sum(q0_i * p_i,t) / sum(q0_i * p_i,0)

donde p_i,t es el precio del insumo i en el periodo t (mediana entre cadenas
scrapeadas) y q0_i es la cantidad fija de la racion (data/productos.json).

Cobertura regional: por defecto, el precio nacional de referencia (mediana
entre cadenas) se aplica a las 16 regiones (ver limitacion documentada en
docs/METODOLOGIA.md: el catalogo online de las cadenas scrapeadas no expone
variacion de precio por region). Si existe data/precios_manual_regional.csv
con filas para una region/fecha/categoria especifica, esas filas reemplazan
al precio nacional para esa region, permitiendo ir regionalizando el indice
a medida que se sume informacion real de terreno (crowdsourcing via PR).

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
RUTA_MANUAL_REGIONAL = RAIZ / "data" / "precios_manual_regional.csv"
RUTA_PRODUCTOS = RAIZ / "data" / "productos.json"
RUTA_REGIONES = RAIZ / "data" / "regiones.json"
RUTA_SALIDA = RAIZ / "data" / "indice_completo.json"

CATEGORIAS_UNIDAD_KG = {"palta", "tomate"}  # precio_unitario esta en CLP/kg
CATEGORIAS_UNIDAD_100G = {"salchicha", "mayonesa"}  # precio_unitario esta en CLP/100g


def cargar_racion() -> dict[str, float]:
    productos = json.loads(RUTA_PRODUCTOS.read_text(encoding="utf-8"))
    racion = productos["racion_completo_italiano"]
    return {
        "salchicha": racion["salchicha_g"],
        "mayonesa": racion["mayonesa_g"],
        "palta": racion["palta_g"],
        "tomate": racion["tomate_g"],
    }


def costo_racion(precios_por_categoria: dict[str, float], gramos_racion: dict[str, float]) -> float | None:
    """precios_por_categoria: {categoria: precio_unitario (CLP/kg o CLP/100g)}"""
    total = 0.0
    for categoria, gramos in gramos_racion.items():
        precio = precios_por_categoria.get(categoria)
        if precio is None:
            return None  # canasta incompleta esa fecha/region -> no se calcula ese punto
        if categoria in CATEGORIAS_UNIDAD_KG:
            total += precio * (gramos / 1000)
        else:
            total += precio * (gramos / 100)
    return round(total, 2)


def leer_historico_nacional() -> dict[str, dict[str, float]]:
    """Devuelve {fecha: {categoria: precio_unitario_mediano_entre_cadenas}}."""
    if not RUTA_HISTORICO.exists():
        return {}
    por_fecha_categoria: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    with RUTA_HISTORICO.open(encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            por_fecha_categoria[fila["fecha"]][fila["categoria"]].append(float(fila["precio_unitario"]))

    resultado: dict[str, dict[str, float]] = {}
    for fecha, categorias in por_fecha_categoria.items():
        resultado[fecha] = {
            cat: round(sum(valores) / len(valores), 2) for cat, valores in categorias.items()
        }
    return resultado


def leer_overrides_regionales() -> dict[str, dict[str, dict[str, float]]]:
    """{region_codigo: {fecha: {categoria: precio_unitario}}} desde el CSV manual, si existe."""
    if not RUTA_MANUAL_REGIONAL.exists():
        return {}
    overrides: dict[str, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    with RUTA_MANUAL_REGIONAL.open(encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            overrides[fila["region_codigo"]][fila["fecha"]][fila["categoria"]] = float(
                fila["precio_unitario"]
            )
    return overrides


def construir_serie(
    fechas_ordenadas: list[str],
    precios_por_fecha: dict[str, dict[str, float]],
    gramos_racion: dict[str, float],
) -> list[dict]:
    serie = []
    costo_base = None
    for fecha in fechas_ordenadas:
        costo = costo_racion(precios_por_fecha.get(fecha, {}), gramos_racion)
        if costo is None:
            continue
        if costo_base is None:
            costo_base = costo
        indice = round(100 * costo / costo_base, 2)
        serie.append({"fecha": fecha, "precio_completo_clp": costo, "indice": indice})
    return serie


def main() -> int:
    historico_nacional = leer_historico_nacional()
    if not historico_nacional:
        print("[ERROR] No hay data/precios_historico.csv con datos. Corre primero el scraper.", file=sys.stderr)
        return 1

    gramos_racion = cargar_racion()
    regiones = json.loads(RUTA_REGIONES.read_text(encoding="utf-8"))["regiones"]
    overrides = leer_overrides_regionales()

    fechas_ordenadas = sorted(historico_nacional.keys())

    serie_nacional_referencia = construir_serie(fechas_ordenadas, historico_nacional, gramos_racion)
    if not serie_nacional_referencia:
        print("[ERROR] No fue posible calcular ni un punto de la canasta (faltan categorias).", file=sys.stderr)
        return 1
    costo_base_nacional = serie_nacional_referencia[0]["precio_completo_clp"]

    serie_regional: dict[str, list[dict]] = {}
    poblacion_total = sum(r["poblacion"] for r in regiones)
    indices_nacionales_ponderados: dict[str, float] = {}

    for region in regiones:
        codigo = region["codigo"]
        precios_region: dict[str, dict[str, float]] = {}
        for fecha in fechas_ordenadas:
            precios_fecha = dict(historico_nacional.get(fecha, {}))
            precios_fecha.update(overrides.get(codigo, {}).get(fecha, {}))
            precios_region[fecha] = precios_fecha

        serie = construir_serie(fechas_ordenadas, precios_region, gramos_racion)
        # Se rebasa la serie regional al mismo costo base nacional del periodo 0,
        # para que todas las regiones y el indice nacional compartan exactamente
        # el mismo punto de partida (100) el primer dia de captura.
        serie_regional[codigo] = serie

        peso = region["poblacion"] / poblacion_total
        for punto in serie:
            indices_nacionales_ponderados[punto["fecha"]] = (
                indices_nacionales_ponderados.get(punto["fecha"], 0.0) + punto["indice"] * peso
            )

    serie_nacional = [
        {"fecha": fecha, "indice": round(indices_nacionales_ponderados[fecha], 2)}
        for fecha in fechas_ordenadas
        if fecha in indices_nacionales_ponderados
    ]

    salida = {
        "_descripcion": "Indice del Completo (IdC): Laspeyres base 100 sobre salchicha+mayonesa+palta+tomate.",
        "_metodologia": "docs/METODOLOGIA.md",
        "base_periodo": fechas_ordenadas[0],
        "costo_racion_base_clp": costo_base_nacional,
        "generado_en": datetime.now(timezone.utc).isoformat(),
        "serie_nacional": serie_nacional,
        "serie_referencia_sin_ponderar": serie_nacional_referencia,
        "serie_regional": serie_regional,
        "regiones": [
            {"codigo": r["codigo"], "nombre": r["nombre"], "capital": r["capital"]} for r in regiones
        ],
    }
    RUTA_SALIDA.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Indice calculado: {RUTA_SALIDA}")
    print(f"Base: {fechas_ordenadas[0]} -> costo racion = ${costo_base_nacional} CLP")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
