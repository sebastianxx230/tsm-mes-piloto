# Migracion del MES a Render con Docker

Esta es la guia operativa para pasar el piloto desde Vercel a un servicio
Render Starter sin cambiar Neon. El primer despliegue usa la URL HTTPS
`onrender.com`; no se necesita dominio.

## Arquitectura objetivo

- Aplicacion: un contenedor Docker en Render Starter, una sola instancia.
- Base de datos: Neon PostgreSQL existente.
- Runtime: Gunicorn con un proceso y cuatro hilos.
- Archivos: Google Drive; el disco del contenedor no se usa como almacenamiento.
- CI: Render despliega `main` solamente cuando los checks de GitHub terminan
  correctamente.

No agregue `MIGRATIONS_DATABASE_URL` a Render. La conexion de propietario se
usa unicamente desde un equipo controlado para migraciones y backups.

## 1. Decisiones antes de crear el servicio

### Region

La region de Render no se puede cambiar despues de crear el servicio. Revise
la region en Neon y ajuste `region` en `render.yaml` antes del primer deploy:

| Neon | Render |
| --- | --- |
| `aws-us-east-1` | `virginia` |
| `aws-us-east-2` | `ohio` |
| `aws-us-west-2` | `oregon` |

Si Neon muestra otra region, no cree aun el servicio: seleccione la region de
Render con menor latencia disponible y documente la decision.

### Secretos que deben rotarse

- Rol y clave Neon usados por `DATABASE_URL`.
- Clave privada de la cuenta de servicio Google.
- `SECRET_KEY`; Render la genera automaticamente para un servicio nuevo.

El archivo `.rar` historico contenia un `.env`. No reutilice esos secretos ni
suba el `.rar`, `.env`, `.env.container` o `credentials.json` al repositorio.

## 2. Verificacion local

Instale WSL 2 y Docker Desktop. Desde la raiz del repositorio:

```powershell
Copy-Item .env.container.example .env.container
# Complete .env.container localmente sin compartirlo.
docker compose build
docker compose up -d
docker compose ps
python scripts/smoke_render.py http://localhost:8000
docker compose down
```

El contenedor debe figurar `healthy`. `/health/live` solo comprueba el proceso
y no mantiene despierto a Neon. `/health` comprueba tambien PostgreSQL.

## 3. Ensayo aislado en Neon

1. Cree una rama Neon llamada `pilot-preview` desde produccion.
2. Configure localmente:
   - `DATABASE_URL`: URL pooled de `pilot-preview`.
   - `MIGRATIONS_DATABASE_URL`: URL directa del propietario de `pilot-preview`.
3. Consulte la revision actual:

   ```sql
   SELECT version_num FROM alembic_version;
   ```

4. Siga `docs/NEON_PILOT_MIGRATION.md`. No use `stamp` si la revision no es la
   esperada.
5. Ejecute pruebas y la lista de humo contra `pilot-preview`.

## 4. Crear el Blueprint en Render

1. Publique la rama revisada en GitHub y confirme que CI esta en verde.
2. En Render seleccione **New > Blueprint**.
3. Conecte el repositorio privado y elija el `render.yaml` de la raiz.
4. Render solicitara los valores marcados `sync: false`:

   | Variable | Valor para el ensayo |
   | --- | --- |
   | `DATABASE_URL` | URL pooled de `pilot-preview` |
   | `GOOGLE_CREDENTIALS` | JSON completo de la cuenta de servicio |
   | `DRIVE_PARENT_FOLDER_ID` | Carpeta general autorizada |
   | `DRIVE_PARENT_FOLDER_ID_2025` | Carpeta 2025 autorizada |
   | `DRIVE_PARENT_FOLDER_ID_2026` | Carpeta 2026 autorizada |

5. Confirme que el servicio indique **Docker**, **Starter**, una instancia y
   health check `/health/live`.
6. Espere a que el deploy muestre `Live` y ejecute:

   ```powershell
   python scripts/smoke_render.py https://SU-SERVICIO.onrender.com
   ```

7. Complete la prueba de humo de `docs/PILOT_RUNBOOK.md`, incluido el reporte
   real mas pesado. Observe memoria y CPU en Render.

## 5. Corte a produccion

Realice el corte fuera del horario de trabajo y no permita escrituras durante
la ventana.

1. Anuncie el inicio de mantenimiento y detenga nuevas ediciones.
2. Genere y verifique un backup siguiendo `docs/BACKUP_RESTORE.md`.
3. Confirme la revision de Alembic en produccion.
4. Aplique la migracion aprobada con la URL directa:

   ```powershell
   .\.venv\Scripts\python.exe -m flask db upgrade
   .\.venv\Scripts\python.exe -m flask db current
   ```

5. En Render cambie solamente `DATABASE_URL` por la URL pooled de produccion y
   seleccione **Save and deploy**.
6. Espere el estado `Live` y ejecute el smoke test remoto.
7. Pruebe login de admin/editor/viewer, una lectura y una escritura controlada.
8. Comparta la nueva URL `onrender.com` con los usuarios.
9. Impida nuevas escrituras en Vercel. Una vez estable Render, revoque el rol o
   clave de Neon que usaba Vercel.
10. Vigile logs, memoria y errores durante los primeros 30 minutos y al inicio
    del siguiente turno.

No deje Vercel y Render abiertos a usuarios escribiendo simultaneamente sobre
produccion.

## 6. Rollback

### Falla antes de entregar la URL

- Mantenga Vercel como servicio activo.
- Restaure `DATABASE_URL` de Render a `pilot-preview`.
- Investigue usando los logs y el `request_id`.

### Falla despues del corte

1. Detenga nuevas escrituras y registre la hora exacta.
2. En Render use **Rollback** al ultimo deploy sano si el problema es codigo.
3. No ejecute `flask db downgrade` durante el incidente. Las migraciones del
   piloto son aditivas y la aplicacion anterior puede usar el esquema nuevo.
4. Si debe volver temporalmente a Vercel, entregue a Vercel un rol runtime
   vigente y retire el de Render para evitar dos escritores.

Una restauracion de base es el ultimo recurso y debe hacerse en una base nueva,
nunca sobrescribiendo la base fallida sin conservar evidencia.

## 7. Limites iniciales

- Mantenga `numInstances: 1`. Antes de usar dos replicas, cambie
  `RATELIMIT_STORAGE_URI` a Redis compartido.
- Mantenga `WEB_CONCURRENCY=1`, `WEB_THREADS=4` y `REPORT_WORKERS=2` en Starter.
- Si la memoria supera 80 % durante reportes, reduzca primero cantidad/tamano de
  imagenes. No aumente workers.
- El contenedor no es almacenamiento. Todo documento persistente permanece en
  Drive y todo dato relacional en Neon.
- No habilite previews automaticos en Render: generan instancias facturables.

## 8. Criterio de exito

La migracion esta terminada cuando:

- CI y el smoke test Docker estan en verde.
- Render permanece `Live` y no registra reinicios por memoria.
- `/health/live` y `/health` responden `200`.
- La revision de Alembic es la esperada.
- Los tres roles y las operaciones criticas funcionan.
- Vercel ya no puede escribir en produccion.
- Existe un backup verificado y un responsable conoce el rollback.
