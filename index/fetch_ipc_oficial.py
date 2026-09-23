"""
Trae la serie oficial de IPC (variacion mensual %, INE) desde mindicador.cl
-una API publica, gratuita y ampliamente usada para indicadores economicos
chilenos (UF, dolar, IPC, etc.), sin necesidad de credenciales- y la
encadena a un indice base 100 anclado en el mismo mes que el periodo base
del Indice del Completo, para poder graficar ambas series en el mismo eje.

Salida: data/ipc_oficial.json
"""

from __future__ import annotations

import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
RUTA_INDICE = RAIZ / "data" / "indice_completo.json"
RUTA_SALIDA = RAIZ / "data" / "ipc_oficial.json"

URL_MINDICADOR = "https://mindicador.cl/api/ipc"
USER_AGENT = "IndiceDelCompletoBot/1.0 (+https://github.com/; lectura de serie publica IPC)"


def obtener_serie_mensual() -> list[dict]:
    req = urllib.request.Request(URL_MINDICADOR, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    serie = data.get("serie", [])
    # mindicador.cl entrega la serie de mas reciente a mas antigua; la
    # devolvemos ordenada cronologicamente (ascendente).
    out = []
    for punto in reversed(serie):
        fecha = punto["fecha"][:7]  # "YYYY-MM-DDTHH:..." -> "YYYY-MM"
        out.append({"mes": fecha, "variacion_pct": punto["valor"]})
    return out


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
        serie_mensual = obtener_serie_mensual()
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] No se pudo obtener el IPC oficial desde mindicador.cl: {exc}", file=sys.stderr)
        return 1

    serie_indexada = encadenar_base_100(serie_mensual, mes_base)

    salida = {
        "_descripcion": "IPC oficial (INE), variacion mensual encadenada a indice base 100 en el mismo periodo base del Indice del Completo.",
        "_fuente": "mindicador.cl (replica publica y gratuita de series del Banco Central / INE)",
        "base_periodo_mes": mes_base,
        "generado_en": datetime.now(timezone.utc).isoformat(),
        "serie": serie_indexada,
    }
    RUTA_SALIDA.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"IPC oficial guardado en {RUTA_SALIDA} (base {mes_base} = 100)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
