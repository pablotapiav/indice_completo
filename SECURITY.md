# Seguridad

Este es un repo público, así que estas son las decisiones de diseño
tomadas explícitamente por seguridad:

## Sin secretos, sin credenciales

Nada en este proyecto requiere login, API key ni token. El scraper solo lee
endpoints públicos de catálogo (sin sesión) y `mindicador.cl` es una API
pública sin autenticación. El workflow de GitHub Actions usa únicamente el
`GITHUB_TOKEN` por defecto (permiso `contents: write`, generado y rotado
automáticamente por GitHub) para poder commitear los datos — no hay ningún
secret manual configurado en el repo. Si en algún momento ves un `.env`,
una API key o una credencial en un PR, es un error: repórtalo como issue.

## Scraping responsable

- **Solo lectura de catálogo público.** Nunca se toca carrito, cuenta,
  checkout ni ningún endpoint que requiera sesión.
- **Se respeta `robots.txt`.** Dos cadenas quedaron explícitamente fuera
  (Líder por `robots.txt`, Unimarc por bloqueo activo tipo Akamai) — ver
  `docs/METODOLOGIA.md` sección 3. No se intenta evadir ninguna protección
  anti-bot.
- **Rate limiting conservador** (`scraper/vtex_client.py`:
  `REQUEST_DELAY_SECONDS`) y reintentos acotados, nunca loops infinitos.
- **User-Agent identificable**, con propósito del bot explicado en el string
  y referencia a este repo, para que cualquier administrador de sitio sepa
  qué es y pueda bloquearlo o contactarnos si lo prefiere.
- El scraper corre en un cron semanal, no en loop ni con alta frecuencia.

## Sin dependencias externas en el scraper/índice

Todo `scraper/` e `index/` usa solo la librería estándar de Python. Es una
decisión deliberada: cero superficie de ataque de cadena de suministro
(`pip install` de paquetes de terceros) en el código que corre
automáticamente en CI con permisos de escritura al repo.

## Dashboard estático

`index.html` no carga ningún script de terceros (sin CDN, sin analytics, sin
tracking). Es HTML/CSS/JS plano que solo hace `fetch()` a los JSON del mismo
repo (`data/*.json`). No hay `eval`, no hay inyección de HTML desde datos no
confiables sin escapar — los valores numéricos se formatean con
`toLocaleString`/`toFixed`, los textos con `textContent` donde el contenido
podría variar.

## Reportar un problema

Si encuentras una vulnerabilidad, un secreto expuesto por error, o un
comportamiento del scraper que te parece agresivo hacia algún sitio, abre un
issue en el repo (o, si es sensible, contacta directamente a quien mantiene
el repo antes de hacerlo público).
