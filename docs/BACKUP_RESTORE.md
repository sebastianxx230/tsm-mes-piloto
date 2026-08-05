# Backup y restauración de PostgreSQL

## Antes de una migración

1. Identifique la base y confirme que la URL no apunte a un entorno equivocado.
2. Genere un backup en formato custom:

   ```bash
   pg_dump --format=custom --no-owner --no-acl --file=tsm25.backup "$MIGRATIONS_DATABASE_URL"
   ```

3. Verifique el archivo:

   ```bash
   pg_restore --list tsm25.backup
   ```

4. Guárdelo cifrado fuera del servidor de la aplicación y registre fecha,
   entorno, commit y responsable.

`MIGRATIONS_DATABASE_URL` debe ser la conexión directa de Neon. No use el
hostname terminado en `-pooler` para migraciones, `pg_dump` o `pg_restore`.

## Prueba de restauración

Restaure siempre sobre una base temporal, nunca sobre producción:

```bash
createdb tsm25_restore_test
pg_restore --clean --if-exists --no-owner --no-acl \
  --dbname=tsm25_restore_test tsm25.backup
```

Compruebe conteos de `usuarios`, `catalogo_ot`, `packing_lists`,
`componentes_ot` y `bitacora_ot`; luego arranque la aplicación apuntando a la
base temporal y valide login, catálogo y una OT.

## Recuperación

Si una migración falla, detenga nuevos despliegues, conserve los logs y restaure
en una base nueva. Cambie `DATABASE_URL` y `MIGRATIONS_DATABASE_URL` solo después
de verificar la copia. No
sobrescriba la base fallida hasta entender la causa.
