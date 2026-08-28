-- Reinicio controlado del piloto MES.
--
-- Conserva deliberadamente:
--   catalogo_ot, usuarios, roles/permisos, procesos/rutas y alembic_version.
--
-- No usa CASCADE: si en el futuro aparece una tabla operativa dependiente que
-- no esté declarada aquí, PostgreSQL bloqueará el reinicio en lugar de borrar
-- información fuera del alcance esperado.

BEGIN;

TRUNCATE TABLE
    public.avance_elemento_proceso,
    public.produccion_avances,
    public.componentes_ot,
    public.packing_list_componentes,
    public.importaciones_packing_list,
    public.packing_lists,
    public.bitacora_ot,
    public.documentos_seguimiento,
    public.fotos_seguimiento,
    public.personal_produccion
RESTART IDENTITY;

COMMIT;
