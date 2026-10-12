"""
Trae la serie oficial de IPC (variacion mensual %, INE) desde un POOL de
fuentes ordenadas por prioridad y la encadena a un indice base 100 anclado
en el mismo mes que el periodo base del Indice del Completo, para poder
graficar ambas series en el mismo eje.

Cada fuente se prueba en orden (con reintentos). Una fuente se descarta y se
pasa a la siguiente si: falla la red/parseo, entrega una serie invalida, o
entrega una serie DESACTUALIZADA (ultimo mes demasiado antiguo; el INE
publica el IPC ~el dia 8 del mes siguiente). Si todas fallan, se conserva el
archivo anterior y el job no se cae.

Fuentes (prioridad):
  1. Banco Central (BDE, SieteRestWS) - oficial; requiere credenciales gratuitas
     en BCCH_USER / BCCH_PASS (se omite si no estan definidas). La serie se
     puede cambiar con BCCH_SERIE_IPC (variacion mensual %).
  2. mindicador.cl - publica, sin credenciales.
  3. boostr.cl - publica, sin credenciales.

Salida: data/ipc_oficial.json
"""


from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
RUTA_INDICE = RAIZ / "data" / "indice_completo.json"
RUTA_SALIDA = RAIZ / "data" / "ipc_oficial.json"

REINTENTOS = 3
TIMEOUT_S = 30
ESPERA_BASE_S = 5  # backoff exponencial: 5s, 10s
MAX_ANTIGUEDAD_DIAS = 75  # ultimo mes publicado no puede ser mas viejo que esto
MIN_PUNTOS = 12
USER_AGENT = "IndiceDelCompletoBot/1.0 (+https://github.com/; lectura de serie publica IPC)"

BCCH_URL = "https://si3.bcentral.cl/SieteRestWS/SieteRestWS.ashx"
# Variacion mensual del IPC general (INE). Verificar el codigo en
# https://si3.bcentral.cl/ (buscador de series) si el Banco Central lo cambia.
BCCH_SERIE_DEFECTO = "F074.IPC.VAR.Z.EP23.C.M"


def _get_json(url: str) -> dict:
    """GET con reintentos y backoff exponencial ante caidas pasajeras."""
    ultimo_error: Exception | None = None
    for intento in range(1, REINTENTOS + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            ultimo_error = exc
            if intento < REINTENTOS:
                espera = ESPERA_BASE_S * 2 ** (intento - 1)
                print(f"[AVISO]   intento {intento}/{REINTENTOS} fallo ({exc}); reintento en {espera}s", file=sys.stderr)
                time.sleep(espera)
    raise ultimo_error  # type: ignore[misc]


def _a_mes(texto: str) -> str:
    """Normaliza 'YYYY-MM-DD...' o 'DD-MM-YYYY' a 'YYYY-MM'."""
    t = str(texto).strip()
    if len(t) >= 10 and t[2] == "-" and t[5] == "-":  # DD-MM-YYYY
        return f"{t[6:10]}-{t[3:5]}"
    return t[:7]


def _num(v) -> float:
    return float(str(v).replace(",", "."))


def fuente_bcentral() -> list[dict]:
    user, pw = os.environ.get("BCCH_USER"), os.environ.get("BCCH_PASS")
    if not user or not pw:
        raise RuntimeError("sin credenciales BCCH_USER/BCCH_PASS")
    serie = os.environ.get("BCCH_SERIE_IPC", BCCH_SERIE_DEFECTO)
    desde = f"{datetime.now(timezone.utc).year - 6}-01-01"
    q = urllib.parse.urlencode({
        "user": user, "pass": pw, "function": "GetSeries", "timeseries": serie, "firstdate": desde,
    })
    data = _get_json(f"{BCCH_URL}?{q}")
    if data.get("Codigo") not in (0, "0", None):
        raise RuntimeError(f"BCCh respondio Codigo={data.get('Codigo')}: {data.get('Descripcion')}")
    obs = data["Series"]["Obs"]
    return [
        {"mes": _a_mes(o["indexDateString"]), "variacion_pct": _num(o["value"])}
        for o in obs
        if str(o.get("value", "")).strip() not in ("", "NaN", "None")
    ]


def fuente_mindicador() -> list[dict]:
    data = _get_json("https://mindicador.cl/api/ipc")
    # mindicador entrega la serie de mas reciente a mas antigua.
    return [{"mes": _a_mes(p["fecha"]), "variacion_pct": _num(p["valor"])} for p in reversed(data.get("serie", []))]


def fuente_boostr() -> list[dict]:
    anio = datetime.now(timezone.utc).year
    out: list[dict] = []
    for a in (anio - 1, anio):
        data = _get_json(f"https://api.boostr.cl/economy/indicator/ipc/{a}.json")
        filas = data.get("data", data.get("serie", []))
        for f in filas:
            fecha = f.get("date") or f.get("fecha")
            valor = f.get("value") if f.get("value") is not None else f.get("valor")
            out.append({"mes": _a_mes(fecha), "variacion_pct": _num(valor)})
    return out


FUENTES = [
    ("Banco Central (BDE)", fuente_bcentral),
    ("mindicador.cl", fuente_mindicador),
    ("boostr.cl", fuente_boostr),
]


def validar_serie(serie: list[dict], hoy: date | None = None) -> None:
    """Lanza ValueError si la serie no sirve (corta, rara o desactualizada)."""
    hoy = hoy or datetime.now(timezone.utc).date()
    if len(serie) < MIN_PUNTOS:
        raise ValueError(f"serie muy corta ({len(serie)} puntos)")
    meses = [p["mes"] for p in serie]
    if any(len(m) != 7 or m[4] != "-" for m in meses):
        raise ValueError("fechas con formato inesperado")
    if meses != sorted(set(meses)):
        raise ValueError("meses duplicados o desordenados")
    if any(abs(p["variacion_pct"]) > 10 for p in serie):
        raise ValueError("variaciones mensuales fuera de rango (>10%)")
    ultimo = serie[-1]["mes"]
    fin_mes = date(int(ultimo[:4]), int(ultimo[5:7]), 28) + timedelta(days=4)
    fin_mes = fin_mes.replace(day=1) - timedelta(days=1)
    antig = (hoy - fin_mes).days
    if antig > MAX_ANTIGUEDAD_DIAS:
        raise ValueError(f"desactualizada: ultimo mes {ultimo} ({antig} dias desde su cierre)")


def obtener_serie_mensual() -> tuple[str, list[dict]]:
    """Recorre el pool en orden y devuelve (nombre_fuente, serie) de la primera valida."""
    errores = []
    for nombre, fn in FUENTES:
        print(f"[INFO] Probando fuente: {nombre}", file=sys.stderr)
        try:
            serie = sorted(fn(), key=lambda p: p["mes"])
            validar_serie(serie)
        except Exception as exc:  # noqa: BLE001
            print(f"[AVISO] {nombre} descartada: {exc}", file=sys.stderr)
            errores.append(f"{nombre}: {exc}")
            continue
        print(f"[INFO] Usando {nombre} (ultimo mes {serie[-1]['mes']})", file=sys.stderr)
        return nombre, serie
    raise RuntimeError("; ".join(errores))


def encadenar_base_100(serie_mensual: list[dict], mes_base: str) -> list[dict]:
    """Construye un indice base 100 en `mes_base`, encadenando variaciones %."""
    meses = [p["mes"] for p in serie_mensual]
    if mes_base not in meses:
        # Si el mes base exacto no esta en la serie oficial (ej. mes en curso
        # aun no publicado por el INE), se ancla en el mes disponible mas
        # cercano hacia atras.
        anteriores = [m for m in meses if m <= mes_base]
        mes_base = anteriores[-1] if anteriores else meses[0]

    idx_base = meses.index(mes_base)
    indices = [None] * len(serie_mensual)
    indices[idx_base] = 100.0

    # Hacia adelante desde la base.
    for i in range(idx_base + 1, len(serie_mensual)):
        var = serie_mensual[i]["variacion_pct"] / 100
        indices[i] = round(indices[i - 1] * (1 + var), 4)

    # Hacia atras desde la base.
    for i in range(idx_base - 1, -1, -1):
        var = serie_mensual[i + 1]["variacion_pct"] / 100
        indices[i] = round(indices[i + 1] / (1 + var), 4)

    return [
        {"mes": p["mes"], "indice": indices[i]} for i, p in enumerate(serie_mensual)
    ]


def main() -> int:
    if not RUTA_INDICE.exists():
        print("[ERROR] Corre primero index/compute_index.py para fijar el periodo base.", file=sys.stderr)
        return 1

    indice_completo = json.loads(RUTA_INDICE.read_text(encoding="utf-8"))
    mes_base = indice_completo["base_periodo"][:7]

    try:
        fuente, serie_mensual = obtener_serie_mensual()
    except Exception as exc:  # noqa: BLE001
        # El IPC es un dato secundario: no debe tumbar la corrida semanal ni
        # impedir el commit del scraping. Se conserva el ultimo archivo.
        print(f"[AVISO] Ninguna fuente de IPC disponible: {exc}", file=sys.stderr)
        if RUTA_SALIDA.exists():
            print(f"Se conserva el {RUTA_SALIDA.name} anterior sin actualizar.", file=sys.stderr)
        return 0

    serie_indexada = encadenar_base_100(serie_mensual, mes_base)

    salida = {
        "_descripcion": "IPC oficial (INE), variacion mensual encadenada a indice base 100 en el mismo periodo base del Indice del Completo.",
        "_fuente": fuente,
        "base_periodo_mes": mes_base,
        "generado_en": datetime.now(timezone.utc).isoformat(),
        "serie": serie_indexada,
    }
    RUTA_SALIDA.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"IPC oficial guardado en {RUTA_SALIDA} (base {mes_base} = 100)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
