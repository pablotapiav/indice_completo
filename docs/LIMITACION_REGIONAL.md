# Por qué el Índice del Completo no es regional (todavía)

La idea original de este proyecto era comparar el precio del completo
**por región**, en línea con el IPC del INE. Se investigó en serio, con
pruebas técnicas reales, no solo intuición — y el resultado fue negativo.
Esto documenta qué se probó, qué dio, y por qué se cambió el foco a
**comparar entre cadenas de supermercado** en vez de entre regiones.

## Lo que se intentó

### Idea 1: hacerle creer a Jumbo/Santa Isabel que estamos en otra región

La hipótesis: cambiando la ubicación entregada al sitio (código postal,
comuna registrada en una cuenta) se podría "destrabar" una lista de precios
distinta por región, como pasa con la disponibilidad de despacho.

**Se probó, no teóricamente, con requests reales:**

1. **Endpoint de regionalización de VTEX**
   (`/api/checkout/pub/regions?country=CHL&postalCode=...`) consultado con
   códigos postales de Arica, La Serena, Antofagasta y Concepción —
   puntas opuestas del país. Los 4 devolvieron **exactamente el mismo
   `regionId`** (`v2.1BB18CE648B5111D0933734ED83EC783` en Jumbo). No hay
   regionalización real por comuna en el backend.

2. **Barrido del parámetro `sc` (sales channel)** de VTEX — el mecanismo que
   normalmente separa listas de precio distintas por canal/zona — probado de
   `sc=1` a `sc=100` en Jumbo y Santa Isabel. **Solo existe `sc=1`**; todo lo
   demás devuelve `404 Not Found`. No hay una segunda lista de precios
   esperando a alguien que "aparente" vivir en otra región: el catálogo es
   una única lista de precios nacional, punto.

**Conclusión:** no hay nada que destrabar. Cambiar la ubicación (o registrar
una cuenta con una dirección falsa en otra comuna) no iba a cambiar ningún
precio, porque el backend no tiene esa segunda lista. Y aunque la hubiera
tenido, construir tooling para hacerle creer a un tercero que estamos en un
lugar donde no estamos — vía datos falsos de identidad/ubicación — no es
algo que este proyecto vaya a automatizar, independiente del resultado.

Esto también descarta usar un navegador automatizado (Playwright) para
"seleccionar comuna" en la UI: el navegador llama exactamente al mismo
backend que se consultó directo. Si la API no tiene una segunda lista de
precios, no importa qué tan realista sea el cliente que la consulte.

### Idea 2: usar una cadena genuinamente regional (precio de góndola real de esa región)

Esta es la idea metodológicamente correcta — el problema es que Chile no da
mucha tela para cortar acá. Se buscaron cadenas independientes/regionales
con e-commerce real fuera de las 5 grandes cadenas nacionales. Lo que se
encontró:

- La mayoría de los supermercados regionales/independientes chilenos **no
  tienen e-commerce transaccional con precios publicados** (a lo más una
  página informativa o redes sociales).
- Las alternativas que sí tienen tienda online (SuperBodega aCuenta, Ahorro
  Cordillera, ServiceShop) están concentradas en Región Metropolitana y
  Valparaíso — no dan cobertura regional adicional.
- SuperBodega aCuenta es además marca de SMU (mismo grupo que Unimarc), así
  que aunque tuviera tienda online funcional, probablemente comparte el
  mismo motor de precios nacional.

**Conclusión:** no se encontró, por ahora, ninguna cadena con e-commerce real
acotada a una sola región (ej. solo Aysén, solo Magallanes, solo Atacama)
que permita un precio de góndola genuinamente regional.

## Qué se hizo con esto

Se cambió el foco del índice: en vez de comparar 16 regiones con un precio
nacional repetido 16 veces (lo cual sería, en la práctica, un número falso
con apariencia de granularidad que no tiene), el **Índice del Completo ahora
compara cadenas de supermercado entre sí** — Líder, Jumbo, Unimarc, Santa
Isabel, Mayorista 10, aCuenta, Alvi y Tottus — que es una comparación real y
honesta con los datos que efectivamente se pueden conseguir de forma legítima
(ver `docs/METODOLOGIA.md` y `SECURITY.md` sobre qué cadenas se scrapean
automático y cuáles no, y por qué).

## Esto sigue abierto

Si en algún momento:

- Se identifica una cadena real, con e-commerce funcional, acotada a una
  sola región, o
- Alguien tiene un precio de góndola real capturado en terreno (foto de
  etiqueta, boleta, etc.) para una región específica,

ese dato tiene un lugar natural en `data/precios_manuales_cadena.csv` (o una
extensión con columna de región, si llega a haber suficientes datos como
para justificarlo). El pipeline (`index/compute_index.py`) está armado para
sumar cadenas nuevas sin reescribir nada — el límite de hoy es de datos
disponibles, no de arquitectura.
