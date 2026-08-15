# Paquete final de configuración del piloto

Este paquete contiene únicamente archivos seguros para copiar al repositorio.
No contiene contraseñas, URLs privadas de Neon ni el JSON real de Google.

## Qué copiar

Copie el contenido de esta carpeta sobre la raíz del proyecto, conservando las
subcarpetas `docs/` y `migrations/versions/`.

- `app.py` es una copia verificada del archivo actual. No necesita cambios
  adicionales para el piloto.
- `.env.vercel.example` es el inventario que debe reproducir en **Vercel >
  Settings > Environment Variables > Production**, sustituyendo los valores de
  ejemplo por los secretos que ya creó.
- `.env.example` sirve para desarrollo y migraciones locales. Cópielo como
  `.env`; nunca suba el `.env` real.
- `.env.container.example` sirve para Docker. Cópielo como `.env.container`;
  nunca suba ese archivo real.
- `compose.yaml` y `Dockerfile` ejecutan la aplicación Flask completa con
  Gunicorn. El contenedor no es un programa separado solamente para fotos.

## Orden recomendado

1. Copie estos archivos al repositorio y confirme que Git no muestra `.env`,
   `.env.container` ni `credentials.json`.
2. En Neon SQL Editor ejecute solamente:

   ```sql
   SELECT version_num FROM alembic_version;
   ```

3. Si devuelve `20260804_0008`, siga `docs/NEON_PILOT_MIGRATION.md` primero en
   una rama `pilot-preview`. Si devuelve otra revisión, deténgase y revísela
   antes de aplicar cambios.
4. Use `docs/RENDER_DEPLOYMENT.md` para probar Docker, desplegar primero contra
   `pilot-preview` y realizar el corte controlado a producción.

No coloque `MIGRATIONS_DATABASE_URL` en Vercel ni Render: esa conexión de
propietario se usa únicamente desde un equipo controlado para migraciones y
backups.
