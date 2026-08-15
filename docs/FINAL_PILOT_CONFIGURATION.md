# Configuración final del piloto

## Archivos de variables

- `.env.example`: desarrollo y migraciones locales.
- `.env.vercel.example`: inventario temporal para Vercel.
- `.env.container.example`: ejecución local con Docker.
- `render.yaml`: configuración productiva de Render, incluidos los nombres de
  secretos que se proporcionan exclusivamente desde el Dashboard.

Los archivos `.env` y `.env.container` reales quedan excluidos de Git y de la
imagen Docker. `credentials.json` también está excluido; en producción se usa
`GOOGLE_CREDENTIALS`.

`MIGRATIONS_DATABASE_URL` nunca se configura en Vercel o Render. Solo se usa
desde un equipo controlado para migraciones y backups.

## Aplicación

`app.py` valida `SECRET_KEY` y `DATABASE_URL`, usa cookies seguras, CSRF,
`ProxyFix`, límites de carga y pool de conexiones fuera de Vercel.

- `/health/live`: liveness sin consulta a PostgreSQL. Es el health check de
  Docker y Render para no mantener despierto continuamente el compute Neon.
- `/health` y `/health/ready`: verificación profunda de Flask y PostgreSQL.
- `CHECK_DATABASE_ON_STARTUP=True`: evita publicar un contenedor con
  credenciales PostgreSQL inválidas.

## Render

El objetivo productivo es una instancia Docker Starter administrada por
`render.yaml`. La configuración inicial usa un proceso Gunicorn, cuatro hilos y
dos workers internos de reportes para mantenerse dentro de 512 MB.

Antes de crear el servicio, haga coincidir la región de Render con la región del
proyecto Neon. La región de Render no puede modificarse después de crear el
servicio.

Siga `docs/RENDER_DEPLOYMENT.md` para el ensayo con `pilot-preview`, la ventana
de corte, smoke test y rollback.

## Docker local

1. Instale WSL 2 y Docker Desktop.
2. Copie `.env.container.example` a `.env.container` y complete los secretos.
3. Ejecute `docker compose build`.
4. Ejecute `docker compose up -d`.
5. Ejecute `python scripts/smoke_render.py http://localhost:8000`.
6. Al terminar, ejecute `docker compose down`.

El repositorio contiene CI para construir la imagen, aplicar migraciones sobre
un PostgreSQL desechable, iniciar el contenedor y validar ambos endpoints de
salud.

## Vercel durante la transición

Vercel puede conservarse durante la prueba aislada, pero no se deben entregar
Vercel y Render a usuarios escribiendo simultáneamente sobre Neon producción.
Una vez validado Render, retire a Vercel su credencial runtime.
