# 🌭 Índice del Completo (IdC)

**¿Cuánto cuesta armar un completo italiano según dónde lo compres, y cómo
se compara eso con el IPC oficial?**

Proyecto independiente, sin fines de lucro, con harto de chiste y algo de
metodología real: se trackea el precio de **vienesa, mayonesa, palta y
tomate** en distintas cadenas de supermercado de Chile, se arma un índice de
precios propio (base 100, tipo Laspeyres) y se compara contra el IPC del INE.

👉 Dashboard: `index.html` (ver [Cómo verlo](#cómo-verlo-localmente))

## Por qué existe esto

El completo italiano es, probablemente, el plato más transversal de Chile.
Seguirle la pista al costo de sus 4 ingredientes básicos es una forma
simpática de conversar sobre inflación — y una excusa para armar, en serio,
un mini-observatorio de precios abierto y auditable.

La idea original era compararlo **por región**. No se pudo — ver
[docs/LIMITACION_REGIONAL.md](docs/LIMITACION_REGIONAL.md) para el detalle
de qué se intentó y por qué se descartó. El foco de hoy es comparar **entre
cadenas de supermercado**: Líder, Jumbo, Unimarc, Santa Isabel, Mayorista 10,
SuperBodega aCuenta, Alvi y Tottus.

## Qué hace el repo

1. **Scraper** (`scraper/`) — lee el catálogo público de Jumbo y Santa
   Isabel (ambas sobre VTEX), busca cada insumo, filtra resultados
   irrelevantes y calcula un precio normalizado por categoría (mediana entre
   productos comparables). Solo lee catálogo público, nunca toca carrito,
   cuenta ni checkout. El resto de las cadenas (Líder, Unimarc, Mayorista 10,
   aCuenta, Alvi, Tottus) bloquean el scraping por robots.txt o protección
   anti-bot — quedan con precio pendiente de captura manual, ver
   [SECURITY.md](SECURITY.md) y [docs/METODOLOGIA.md](docs/METODOLOGIA.md)
   para el detalle exacto de cada una.
2. **Índice** (`index/`) — con esos precios arma el **Índice del Completo**:
   un índice de canasta fija, base 100 en el día que partió la medición,
   comparado entre cadenas. También trae el IPC oficial (vía
   [mindicador.cl](https://mindicador.cl)) y lo deja en la misma base 100
   para poder compararlo con el promedio nacional del IdC.
3. **Dashboard** (`index.html`) — página estática (sin build step, sin
   dependencias de terceros) que grafica ambas series y compara el precio
   entre cadenas, mostrando explícitamente cuáles no tienen dato y por qué.
4. **GitHub Actions** (`.github/workflows/actualizar_indice.yml`) — corre el
   scraper semanalmente y commitea los datos nuevos, para que el histórico
   se vaya construyendo solo con el tiempo.

## Metodología (versión corta)

```
IdC_t = 100 × Σ(q0_i × p_i,t) / Σ(q0_i × p_i,0)
```

Canasta fija por ración: 70 g vienesa + 15 g mayonesa + 50 g palta + 30 g
tomate. El detalle completo está en
[docs/METODOLOGIA.md](docs/METODOLOGIA.md). Léelo antes de citar el número:
es un índice de 4 productos hecho con metodología simple, no un sustituto
del IPC.

## Cómo correrlo

Requiere solo Python 3.9+ (librería estándar, sin dependencias externas —
decisión deliberada para minimizar riesgo de cadena de suministro en un repo
público, ver [SECURITY.md](SECURITY.md)).

```bash
python -m scraper.run_scraper      # scrapea Jumbo y Santa Isabel, guarda un snapshot
python -m index.compute_index      # recalcula el Índice del Completo (base 100)
python -m index.fetch_ipc_oficial  # trae el IPC oficial y lo alinea a la misma base
```

## Cómo verlo localmente

`index.html` hace `fetch()` a los JSON en `data/`, así que necesita
servirse por HTTP (no `file://`):

```bash
python -m http.server 8000
# abrir http://localhost:8000/
```

## Cómo contribuir con un precio real de Líder, Unimarc, etc.

Estas cadenas bloquean el scraping automático (ver
[docs/METODOLOGIA.md](docs/METODOLOGIA.md) y
[docs/LIMITACION_REGIONAL.md](docs/LIMITACION_REGIONAL.md) para el detalle
de cada una). Si tú, a mano, consultas un precio real en su sitio o en
tienda, agrégalo a `data/precios_manuales_cadena.csv` (columnas:
`fecha,cadena,categoria,precio_unitario,unidad,fuente_url,capturado_por,notas`)
y mándalo por PR — se integra automáticamente al comparador y al índice
nacional la próxima vez que corra `index/compute_index.py`.

## Licencia y disclaimer

Código bajo licencia MIT (ver [LICENSE](LICENSE)). Proyecto independiente,
no oficial, sin afiliación con el INE ni con ninguno de los supermercados
mencionados. Los precios son de catálogo online público y pueden diferir del
precio en tienda física. Con fines informativos, educativos y
humorístico-estadísticos.
