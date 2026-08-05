-- TSM MES: auditoria de solo lectura antes del piloto.
-- Ejecute cada bloque por separado en Neon SQL Editor.
-- Este archivo no crea, modifica ni elimina datos.

-- 1) Revision de Alembic instalada.
SELECT version_num AS revision_alembic
FROM alembic_version;

-- 2) Cantidad exacta de filas por tabla.
SELECT *
FROM (
    SELECT 'alembic_version' AS tabla, COUNT(*) AS filas FROM alembic_version
    UNION ALL SELECT 'bitacora_ot', COUNT(*) FROM bitacora_ot
    UNION ALL SELECT 'catalogo_ot', COUNT(*) FROM catalogo_ot
    UNION ALL SELECT 'componentes_ot', COUNT(*) FROM componentes_ot
    UNION ALL SELECT 'documentos_seguimiento', COUNT(*) FROM documentos_seguimiento
    UNION ALL SELECT 'fotos_seguimiento', COUNT(*) FROM fotos_seguimiento
    UNION ALL SELECT 'packing_list_componentes', COUNT(*) FROM packing_list_componentes
    UNION ALL SELECT 'packing_lists', COUNT(*) FROM packing_lists
    UNION ALL SELECT 'produccion_avances', COUNT(*) FROM produccion_avances
    UNION ALL SELECT 'usuarios', COUNT(*) FROM usuarios
) AS conteos
ORDER BY tabla;

-- 3) Restricciones reales: PK, FK, UNIQUE y CHECK.
SELECT
    tc.table_name AS tabla,
    tc.constraint_name AS restriccion,
    tc.constraint_type AS tipo,
    kcu.column_name AS columna,
    ccu.table_name AS tabla_referenciada,
    ccu.column_name AS columna_referenciada
FROM information_schema.table_constraints AS tc
LEFT JOIN information_schema.key_column_usage AS kcu
    ON tc.constraint_name = kcu.constraint_name
   AND tc.constraint_schema = kcu.constraint_schema
LEFT JOIN information_schema.constraint_column_usage AS ccu
    ON tc.constraint_name = ccu.constraint_name
   AND tc.constraint_schema = ccu.constraint_schema
WHERE tc.table_schema = 'public'
ORDER BY tc.table_name, tc.constraint_type, tc.constraint_name, kcu.ordinal_position;

-- 4) Indices existentes.
SELECT
    tablename AS tabla,
    indexname AS indice,
    indexdef AS definicion
FROM pg_indexes
WHERE schemaname = 'public'
ORDER BY tablename, indexname;

-- 5) Duplicados que romperian reglas importantes.
SELECT 'catalogo_ot.ot duplicado' AS control, COUNT(*) AS grupos_con_error
FROM (SELECT ot FROM catalogo_ot GROUP BY ot HAVING COUNT(*) > 1) AS x
UNION ALL
SELECT 'usuarios.username duplicado', COUNT(*)
FROM (SELECT username FROM usuarios GROUP BY username HAVING COUNT(*) > 1) AS x
UNION ALL
SELECT 'packing_lists (ot_id, orden) duplicado', COUNT(*)
FROM (
    SELECT ot_id, orden
    FROM packing_lists
    GROUP BY ot_id, orden
    HAVING COUNT(*) > 1
) AS x
UNION ALL
SELECT 'fotos (ot_id, drive_file_id) duplicado', COUNT(*)
FROM (
    SELECT ot_id, drive_file_id
    FROM fotos_seguimiento
    GROUP BY ot_id, drive_file_id
    HAVING COUNT(*) > 1
) AS x;

-- 6) Relaciones huerfanas. Todos los resultados deben ser cero.
SELECT 'packing_lists sin OT' AS control, COUNT(*) AS filas_con_error
FROM packing_lists AS p
LEFT JOIN catalogo_ot AS o ON o.item = p.ot_id
WHERE o.item IS NULL
UNION ALL
SELECT 'componentes_ot sin packing list', COUNT(*)
FROM componentes_ot AS c
LEFT JOIN packing_lists AS p ON p.id = c.pl_id
WHERE p.id IS NULL
UNION ALL
SELECT 'bitacora_ot sin OT', COUNT(*)
FROM bitacora_ot AS b
LEFT JOIN catalogo_ot AS o ON o.item = b.ot_id
WHERE o.item IS NULL
UNION ALL
SELECT 'documentos_seguimiento sin OT', COUNT(*)
FROM documentos_seguimiento AS d
LEFT JOIN catalogo_ot AS o ON o.item = d.ot_id
WHERE o.item IS NULL
UNION ALL
SELECT 'fotos_seguimiento sin OT', COUNT(*)
FROM fotos_seguimiento AS f
LEFT JOIN catalogo_ot AS o ON o.item = f.ot_id
WHERE o.item IS NULL;

-- 7) Valores de produccion fuera de rango. El resultado debe ser cero.
SELECT COUNT(*) AS componentes_con_avances_fuera_de_rango
FROM componentes_ot
WHERE cantidad < 0
   OR hab_real < -1 OR hab_real > cantidad
   OR arm_real < -1 OR arm_real > cantidad
   OR sol_real < -1 OR sol_real > cantidad
   OR lim_real < -1 OR lim_real > cantidad
   OR lib_real < -1 OR lib_real > cantidad
   OR gal_real < -1 OR gal_real > cantidad
   OR are_real < -1 OR are_real > cantidad
   OR pin_real < -1 OR pin_real > cantidad
   OR des_real < 0 OR des_real > cantidad;

-- 8) Nulos que conviene corregir en una migracion posterior controlada.
SELECT
    COUNT(*) FILTER (WHERE tipo IS NULL) AS bitacora_tipo_nulo,
    COUNT(*) FILTER (WHERE fecha_creacion IS NULL) AS bitacora_fecha_nula
FROM bitacora_ot;

SELECT COUNT(*) FILTER (WHERE activo IS NULL) AS usuarios_activo_nulo
FROM usuarios;
