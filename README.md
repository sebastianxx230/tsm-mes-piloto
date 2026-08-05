# TSM25 — Sistema de producción

TSM25 es el MES interno de Top Solution Metal. Centraliza órdenes de trabajo,
packing lists, elementos, avances de fabricación, bitácora y reportes
fotográficos almacenados en Google Drive.

## Funciones principales

- Autenticación y perfiles `admin`, `editor` y `viewer`.
- Catálogo, búsqueda y estados de órdenes de trabajo.
- Importación de elementos desde Excel y matriz de producción.
- Seguimiento de avances por lote y proceso.
- Bitácora de la OT y trazabilidad de personal.
- Selección y generación de reportes fotográficos desde Google Drive.
- Conteo de fotos desde el catálogo al pasar el cursor por el icono de reporte.
- Administración de usuarios y bloqueo seguro de cuentas.

## Permisos

| Capacidad | Viewer | Editor | Admin |
| --- | :---: | :---: | :---: |
| Consultar catálogo y seguimiento | Sí | Sí | Sí |
| Modificar OT y producción | No | Sí | Sí |
| Consultar/generar reportes | No | Sí | Sí |
| Archivar OT o packing list | No | No | Sí |
| Administrar usuarios | No | No | Sí |

La autorización se valida en Flask; ocultar un botón no concede ni revoca
permisos.

## Requisitos

- Python 3.12
- PostgreSQL 14 o posterior
- Credencial de servicio de Google con acceso de lectura a las carpetas Drive

## Instalación local

```bash
python -m venv .venv
.venv/Scripts/activate
pip install -r requirements-dev.txt
copy .env.example .env
flask db upgrade
flask run
```

En Linux/macOS use `source .venv/bin/activate` y `cp` en lugar de `copy`.
Complete `.env` con valores locales reales; nunca lo suba a Git.

## Variables de entorno

Consulte [.env.example](.env.example). `SECRET_KEY` y `DATABASE_URL` son
obligatorias. `MIGRATIONS_DATABASE_URL` es la URL directa usada por Alembic y
backups; `DATABASE_URL` debe ser la URL pooled de Neon. La aplicación falla al
arrancar si falta una variable obligatoria. En producción
multiinstancia configure un almacenamiento compartido compatible con
Flask-Limiter en `RATELIMIT_STORAGE_URI`.

## Migraciones

El esquema se administra únicamente con Flask-Migrate/Alembic. El arranque de
la aplicación no crea ni modifica tablas.

Base nueva:

```bash
flask db upgrade
```

Base Neon existente creada antes de introducir Alembic:

1. Cree y verifique un backup.
2. Compare el esquema existente con la revisión inicial.
3. Marque únicamente el esquema inicial: `flask db stamp 20260730_0001`.
4. Aplique los índices nuevos: `flask db upgrade`.

No ejecute `stamp` sobre una base vacía. Revise el SQL con
`flask db upgrade --sql` antes de producción.

## Pruebas y CI

```bash
pytest -q
python -m compileall -q app.py controllers models utils
npm run build:css
docker build -t tsm25:local .
```

El workflow de GitHub ejecuta pruebas, compilación, detección básica de secretos
y construcción de la imagen Docker en cada pull request y cambio a `main`.

## Ejecución con Docker

```bash
docker build -t tsm25 .
docker run --env-file .env -p 8000:8000 tsm25
```

El contenedor ejecuta Gunicorn como usuario sin privilegios. El endpoint
`GET /health` comprueba tanto Flask como la conexión a PostgreSQL.

## Google Drive y conteo de fotos

La cuenta de servicio debe tener acceso de lectura a las carpetas padre. El
catálogo no consulta las OTs al cargar: el conteo se solicita al pasar el cursor
o enfocar el icono fotográfico y se conserva durante cinco minutos por defecto.
Se cuentan imágenes únicas de la carpeta de la OT y de sus subcarpetas directas.

## Operación

- [Backup y restauración](docs/BACKUP_RESTORE.md)
- [Retención de datos](docs/DATA_RETENTION.md)
- [Operación del piloto y transición](docs/PILOT_RUNBOOK.md)

Los logs se emiten como JSON e incluyen un `request_id`, estado HTTP y duración.
Puede enviar `X-Request-ID` desde un proxy para correlacionar peticiones.

## Despliegue

Antes de desplegar: ejecute CI, haga backup, aplique migraciones una sola vez y
luego actualice la aplicación. Configure secretos desde el proveedor. Tras
eliminar la clave histórica del código, rote `SECRET_KEY` en Vercel para
invalidar todas las sesiones antiguas.

Vercel sigue soportado temporalmente por `vercel.json`, con recursos estáticos
preparados en `public/`. Sus funciones limitan solicitudes y respuestas a
4.5 MB; para reportes y documentos pesados use el contenedor. Vercel Hobby no
permite uso comercial, por lo que una empresa debe usar Pro o un hosting de
contenedores con términos adecuados.

## Limitaciones conocidas

- La búsqueda/paginación del catálogo todavía ocurre en el navegador.
- La auditoría básica comparte la bitácora; después puede evolucionar a una tabla dedicada.
- La generación de reportes continúa siendo síncrona y tiene límites de entrada.
