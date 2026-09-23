# Metodología del Índice del Completo (IdC)

Este documento explica, sin vueltas, cómo se calcula el índice, de dónde
salen los datos y cuáles son sus limitaciones. La idea es que cualquiera
pueda auditar el número, no solo creerle.

## 1. La canasta

El "completo italiano" se compone acá de 4 insumos (los que se pidió
trackear), en la proporción de **una ración estándar**:

| Insumo | Cantidad en la ración | Unidad de precio |
|---|---|---|
| Salchicha (vienesa) | 70 g | CLP / 100 g |
| Mayonesa | 15 g | CLP / 100 g |
| Palta | 50 g | CLP / kg |
| Tomate | 30 g | CLP / kg |

No incluye pan a propósito: el encargo original pidió específicamente estos
cuatro insumos. Las cantidades están en `data/productos.json` y se pueden
ajustar ahí — todo el cálculo las lee desde ese archivo, no están hardcodeadas.

## 2. Fórmula del índice

Es un índice de **Laspeyres de canasta fija**, igual en espíritu al IPC del
INE: se fija la canasta (las cantidades `q0`) en el período base y solo se
deja variar el precio en el tiempo.

```
IdC_t = 100 × Σ(q0_i × p_i,t) / Σ(q0_i × p_i,0)
```

- `p_i,t`: precio del insumo `i` en el período `t` (mediana entre las cadenas
  scrapeadas ese día — ver sección 4 sobre por qué mediana y no promedio).
- `p_i,0`: precio del mismo insumo el día en que corrió el scraper por
  primera vez (el "período base", 100 puntos por definición).
- `q0_i`: gramos fijos de la ración (tabla de arriba).

El costo de la ración completa el día base queda registrado en
`data/indice_completo.json` → `costo_racion_base_clp`.

## 3. De dónde salen los precios

Se scrapea el **catálogo público de e-commerce** de dos cadenas que corren
sobre la plataforma VTEX (Jumbo y Santa Isabel), golpeando el endpoint
`api/catalog_system/pub/products/search` de sus cuentas VTEX directamente —
el mismo mecanismo que usan comparadores de precios de terceros. Es JSON de
solo lectura, sin login, sin carrito, sin datos de ninguna persona.

**Cadenas explícitamente excluidas** (ver `data/productos.json` →
`cadenas_excluidas`, con la razón de cada una):

- **Líder**: su `robots.txt` deshabilita explícitamente `/search*`,
  `/catalogo/product*`, `/catalogo/category*` y rutas equivalentes. Se
  respeta esa señal y no se scrapea, punto.
- **Unimarc**: su sitio bloquea con Akamai incluso la lectura de
  `/robots.txt` (403). No se intenta evadir esa protección.
- **Tottus**: el endpoint de catálogo devolvió 503 de forma consistente en
  las pruebas; queda fuera hasta encontrar una vía compatible con su
  `robots.txt`.

Este es, a propósito, un criterio conservador: se prefiere cubrir menos
cadenas pero solo por vías que las propias tiendas no restringen.

## 4. Por qué mediana y no un SKU fijo

Una búsqueda por texto (ej. "palta hass") devuelve varios productos
(distintas marcas/formatos). En vez de fijar un único SKU —frágil: si se
descontinúa, el scraper se cae— se toma la **mediana** de los precios
normalizados entre los resultados relevantes de esa categoría, filtrados por
categoría de catálogo y por palabras clave (`data/productos.json` →
`categoria_whitelist`, `nombre_incluye`, `nombre_excluye`). Es la forma
barata de manejar sesgo de sustitución sin mantener una lista de SKUs a mano.

Normalización de unidades:

- **Salchicha y mayonesa**: se extrae el gramaje del nombre del producto
  (ej. "380 g", "1 kg") y se lleva a CLP/100g.
- **Palta y tomate**: se venden mayoritariamente "a granel", donde la
  convención chilena es que el precio listado ya es por kg. Cuando el nombre
  trae un gramaje explícito (ej. "Malla 1 kg") se usa ese para normalizar en
  vez de asumir la convención. Se excluyen listados ambiguos del tipo
  "(1 a 2 un. aprox)" porque no queda claro si el precio es por kg o por bolsa.

## 5. Cobertura regional — la parte más importante de leer

**Limitación honesta:** el catálogo online de Jumbo y Santa Isabel expone un
**único precio de lista por SKU a nivel nacional** — no se encontró
variación de precio por región/comuna en el API público (se probó con
distintos `sc` / sales channel y no hubo diferencia). Esto es consistente
con cómo varias cadenas manejan su catálogo online en Chile.

Por eso, **hoy** el mismo precio de referencia nacional se aplica como proxy
a las 16 regiones. El pipeline de agregación (`index/compute_index.py`) ya
está armado para regionalizar de verdad apenas haya datos reales de terreno:
si existe `data/precios_manual_regional.csv` con filas
`fecha,region_codigo,categoria,precio_unitario,unidad,fuente`, esos valores
reemplazan al proxy nacional **solo para esa región/fecha/categoría**, sin
tocar el resto. Es el punto de entrada para que alguien en Arica o Coyhaique
mande un PR con el precio real de su supermercado y la región deje de
depender del proxy.

El índice nacional se calcula como el **promedio ponderado por población**
de los 16 índices regionales (pesos en `data/regiones.json`, proyecciones
INE aproximadas) — mismo criterio de agregación que usa el IPC oficial,
aplicado sobre datos que hoy son mayoritariamente el mismo proxy repetido
16 veces. Apenas se sumen overrides regionales reales, el índice nacional
empieza a reflejar diferencias reales entre regiones.

## 6. Comparación con el IPC oficial

El IPC oficial (INE) se obtiene de [mindicador.cl](https://mindicador.cl),
una API pública y gratuita que replica series del Banco Central/INE
(variación mensual, %). `index/fetch_ipc_oficial.py` encadena esas
variaciones mensuales en un índice base 100, anclado en el mismo mes en que
partió la medición del IdC, para que ambas series se puedan graficar en el
mismo eje sin normalizar niveles distintos.

**Ojo con la comparación:** el IPC oficial mide la variación de precios de
una canasta de cientos de bienes y servicios representativa del gasto de los
hogares, con metodología, ponderadores y recolección de precios en terreno
mucho más rigurosa (INE). El IdC es un índice de 4 productos, con
metodología deliberadamente simple, hecho como ejercicio
humorístico-estadístico. Sirve para ilustrar y para jugar con la intuición
de "¿el completo sube más o menos que la vida en general?" — no reemplaza,
ni pretende reemplazar, al IPC.

## 7. Periodicidad

El scraper corre vía GitHub Actions (`.github/workflows/actualizar_indice.yml`)
en un cron semanal, agrega un punto nuevo al histórico y recalcula el
índice. Cada corrida es un commit automático a `data/`, así que todo el
historial de precios queda versionado y auditable en el propio repo.
