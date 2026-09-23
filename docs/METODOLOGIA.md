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

- `p_i,t`: precio del insumo `i` en el período `t`, **por cadena** (mediana
  entre los productos comparables encontrados en la búsqueda de esa cadena
  ese día — ver sección 4 sobre por qué mediana y no un SKU fijo).
- `p_i,0`: precio del mismo insumo, misma cadena, el día en que corrió el
  scraper por primera vez (el "período base", 100 puntos por definición).
- `q0_i`: gramos fijos de la ración (tabla de arriba).

Esto da un costo de ración **por cadena** cada día (lo que se muestra en el
comparador del sitio). La serie nacional (`serie_nacional` en
`data/indice_completo.json`) es el **promedio simple del costo de la ración
entre las cadenas con dato ese día** — ver sección 5. El costo de la ración
el día base queda registrado en `data/indice_completo.json` →
`costo_racion_base_clp`.

## 3. De dónde salen los precios

Tres cadenas se scrapean en automático, por dos vías distintas:

- **Jumbo y Santa Isabel** corren sobre la plataforma VTEX: se golpea el
  endpoint `api/catalog_system/pub/products/search` de sus cuentas VTEX
  directamente — el mismo mecanismo que usan comparadores de precios de
  terceros. Es JSON de solo lectura, sin login, sin carrito.
- **SuperBodega aCuenta** no tiene una API de búsqueda alcanzable sin
  ejecutar JavaScript (ver más abajo), pero cada página de producto trae el
  precio embebido en el HTML como **JSON-LD** (`schema.org/Product`) — el
  mismo tipo de dato estructurado que usa Google Shopping para mostrar
  precios en resultados de búsqueda, puesto ahí a propósito para que
  buscadores lo lean. `scraper/acuenta_client.py` solo lee ese bloque, en
  una lista fija de SKUs (`data/productos.json` → `acuenta` →
  `skus_por_categoria`) porque, a diferencia de Jumbo/Santa Isabel, no hay
  forma de buscar por texto sin un navegador. Si SMU descontinúa alguno de
  esos SKU esa categoría queda sin dato hasta que alguien actualice la
  lista a mano — es una limitación conocida, no un bug silencioso.

**El resto de las cadenas del comparador quedan con precio pendiente de
captura manual** (ver `data/productos.json` → `cadenas`, campos `metodo`,
`razon_corta` y `razon`, con el detalle exacto de cada una — el sitio
muestra `razon_corta` al pasar el mouse sobre "por qué no hay dato"):

- **Líder**: su `robots.txt` deshabilita explícitamente `/search*`,
  `/catalogo/product*`, `/catalogo/category*` y rutas equivalentes para
  cualquier bot genérico (solo permite Googlebot). Se respeta esa señal y no
  se scrapea, punto — tampoco con un navegador automatizado (Playwright):
  usar una herramienta más sofisticada específicamente porque el sitio
  bloquea peticiones simples es evadir la señal, no cumplirla. Ver
  `docs/LIMITACION_REGIONAL.md` para el detalle de por qué tampoco sirve
  para regionalizar el precio.
- **Unimarc, Mayorista 10 y Alvi** (las tres marcas de SMU): su sitio
  bloquea con Akamai incluso la lectura de `/robots.txt` (403). No se
  intenta evadir esa protección.
- **Tottus**: el endpoint de catálogo devolvió 503 de forma consistente en
  las pruebas y no corre en VTEX; queda fuera hasta encontrar su API real.

Este es, a propósito, un criterio conservador: se prefiere cubrir menos
cadenas de forma automática pero solo por vías que las propias tiendas no
restringen — ninguna cadena de esta lista se scrapea evadiendo una
protección activa. Las cadenas pendientes siguen apareciendo en el
comparador del sitio (con precio en blanco y la razón visible) en vez de
desaparecer de la lista — la ausencia de dato es información, no algo que
esconder.

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

## 5. Por qué el foco es "por cadena" y no "por región"

La versión original de este proyecto quería comparar precios por región,
igual que el IPC. Se investigó en serio (no es una suposición): se probó si
cambiar la ubicación/código postal entregado a Jumbo o Santa Isabel
destrababa un precio distinto, y se buscaron cadenas genuinamente
regionales con e-commerce real. Ninguna de las dos rindió frutos —
el detalle completo, con las pruebas técnicas exactas que se hicieron
(endpoints, resultados, códigos postales usados), está en
[`docs/LIMITACION_REGIONAL.md`](LIMITACION_REGIONAL.md). En resumen: el
catálogo online de Jumbo y Santa Isabel expone un **único precio de lista
por SKU a nivel nacional**, confirmado empíricamente, y no se encontró
ninguna cadena regional con precios publicados online fuera de las grandes
cadenas nacionales.

Por eso el índice compara **cadenas entre sí**, no regiones. El índice
nacional (`serie_nacional` en `data/indice_completo.json`) es el
**promedio del costo de la ración entre las cadenas que tienen dato
completo ese día** — hoy Jumbo y Santa Isabel; se recalcula solo cuando se
suma una cadena nueva (scrapeada o vía captura manual en
`data/precios_manuales_cadena.csv`), sin tocar el resto del pipeline.

Si en el futuro aparece una cadena real, acotada a una sola región, con
e-commerce funcional, o alguien aporta un precio de terreno capturado a
mano, `data/precios_manuales_cadena.csv` es el punto de entrada — ver
[`docs/LIMITACION_REGIONAL.md`](LIMITACION_REGIONAL.md#esto-sigue-abierto).

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
