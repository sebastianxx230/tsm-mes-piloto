# Configuracion final del piloto

## Archivos de variables

- `.env.example`: copiar a `.env` solo para desarrollo/migraciones locales.
- `.env.vercel.example`: inventario de variables para Vercel Production. No
  contiene `MIGRATIONS_DATABASE_URL` para no entregar permisos de propietario
  al runtime.
- `.env.container.example`: copiar a `.env.container` para Docker.

Los archivos `.env` y `.env.container` reales quedan excluidos tanto de Git
como de la imagen Docker. `credentials.json` tambien esta excluido; en
produccion se usa `GOOGLE_CREDENTIALS`.

## app.py

El `app.py` del piloto ya valida `SECRET_KEY` y `DATABASE_URL`, usa cookies
seguras, CSRF, `ProxyFix`, limites de carga, `NullPool` en Vercel y el endpoint
`/health`. No requiere otro cambio para esta etapa.

## Vercel

Vercel ejecuta `app.py` como una Function de Python. Use el perfil limitado de
`.env.vercel.example`. La respuesta HTML del reporte contiene fotografias en
Base64, por lo que los reportes grandes pueden superar el limite de payload de
Vercel incluso si el tiempo de ejecucion es suficiente.

## Docker

Docker ejecuta la aplicacion Flask completa con Gunicorn. No es un segundo
programa exclusivo para fotografias. Permite usar el perfil de reportes grande
cuando se despliega en un proveedor de contenedores que acepte esos tamanos.

Preparacion local en Windows:

1. Instale WSL 2 y Docker Desktop.
2. Copie `.env.container.example` a `.env.container` y complete los secretos.
3. Ejecute `docker compose build`.
4. Ejecute `docker compose up -d`.
5. Compruebe `http://localhost:8000/health`.

El sistema actual no tiene Docker Desktop ni WSL instalados, por lo que la
construccion del contenedor debe verificarse despues de instalarlos.
