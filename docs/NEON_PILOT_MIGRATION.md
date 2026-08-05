# Migracion de Neon para el piloto

La aplicacion usa Alembic. No copie manualmente instrucciones `ALTER TABLE`
en produccion: aplique la migracion incluida en el repositorio.

## 1. Preparar una rama de prueba

1. Cree en Neon una rama hija llamada `pilot-preview` desde la base actual.
2. Copie `.env.example` a `.env`.
3. Configure `DATABASE_URL` con la URL pooled de `pilot-preview`.
4. Configure `MIGRATIONS_DATABASE_URL` con la URL directa del propietario de
   `pilot-preview`. El hostname no debe contener `-pooler`.

No copie `MIGRATIONS_DATABASE_URL` al dashboard de Vercel.

## 2. Confirmar la revision actual

En Neon SQL Editor:

```sql
SELECT version_num FROM alembic_version;
```

El inventario recibido es compatible con una base anterior a `0009`. Continue
solo si la consulta devuelve `20260804_0008`. Si devuelve otro valor, detengase
y revise la diferencia antes de migrar.

Desde PowerShell, dentro de la carpeta donde esta `app.py`:

```powershell
.\.venv\Scripts\python.exe -m flask db current
.\.venv\Scripts\python.exe -m flask db upgrade 20260805_0009
.\.venv\Scripts\python.exe -m flask db current
```

El ultimo comando debe mostrar `20260805_0009 (head)`.

## 3. Verificar las columnas nuevas

```sql
SELECT table_name, column_name
FROM information_schema.columns
WHERE table_schema = 'public'
  AND (
    (table_name = 'catalogo_ot' AND column_name IN (
      'version', 'process_weights', 'active_processes', 'archivado',
      'fecha_archivado', 'archivado_por_id', 'fecha_actualizacion'
    ))
    OR
    (table_name = 'packing_lists' AND column_name IN (
      'archivado', 'fecha_archivado', 'archivado_por_id'
    ))
  )
ORDER BY table_name, column_name;
```

La consulta debe devolver diez filas.

## 4. Produccion

Despues de probar login, catalogo, edicion, importacion, avances, archivado y
reportes en `pilot-preview`:

1. Genere y verifique un backup de la rama productiva con la URL directa.
2. Ejecute la auditoria de integridad.
3. Aplique la misma migracion una sola vez en produccion.
4. Despliegue el commit que ya fue probado.

No use `flask db stamp` ni `flask db downgrade` sin revisar primero una copia.
