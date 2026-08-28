-- Ajuste incremental V2: avances nulos + período real por elemento.
-- No elimina OTs, usuarios, Packing Lists ni avances existentes.
BEGIN;

-- 1) Un proceso aún no registrado se representa con NULL, no con -1/N.A.
ALTER TABLE public.componentes_ot DROP CONSTRAINT IF EXISTS ck_componentes_ot_hab_range;
ALTER TABLE public.componentes_ot DROP CONSTRAINT IF EXISTS ck_componentes_ot_arm_range;
ALTER TABLE public.componentes_ot DROP CONSTRAINT IF EXISTS ck_componentes_ot_sol_range;
ALTER TABLE public.componentes_ot DROP CONSTRAINT IF EXISTS ck_componentes_ot_lim_range;
ALTER TABLE public.componentes_ot DROP CONSTRAINT IF EXISTS ck_componentes_ot_lib_range;
ALTER TABLE public.componentes_ot DROP CONSTRAINT IF EXISTS ck_componentes_ot_gal_range;
ALTER TABLE public.componentes_ot DROP CONSTRAINT IF EXISTS ck_componentes_ot_are_range;
ALTER TABLE public.componentes_ot DROP CONSTRAINT IF EXISTS ck_componentes_ot_pin_range;

ALTER TABLE public.componentes_ot ALTER COLUMN hab_real DROP NOT NULL;
ALTER TABLE public.componentes_ot ALTER COLUMN arm_real DROP NOT NULL;
ALTER TABLE public.componentes_ot ALTER COLUMN sol_real DROP NOT NULL;
ALTER TABLE public.componentes_ot ALTER COLUMN lim_real DROP NOT NULL;
ALTER TABLE public.componentes_ot ALTER COLUMN lib_real DROP NOT NULL;
ALTER TABLE public.componentes_ot ALTER COLUMN gal_real DROP NOT NULL;
ALTER TABLE public.componentes_ot ALTER COLUMN are_real DROP NOT NULL;
ALTER TABLE public.componentes_ot ALTER COLUMN pin_real DROP NOT NULL;
ALTER TABLE public.componentes_ot ALTER COLUMN hab_real DROP DEFAULT;
ALTER TABLE public.componentes_ot ALTER COLUMN arm_real DROP DEFAULT;
ALTER TABLE public.componentes_ot ALTER COLUMN sol_real DROP DEFAULT;
ALTER TABLE public.componentes_ot ALTER COLUMN lim_real DROP DEFAULT;
ALTER TABLE public.componentes_ot ALTER COLUMN lib_real DROP DEFAULT;
ALTER TABLE public.componentes_ot ALTER COLUMN gal_real DROP DEFAULT;
ALTER TABLE public.componentes_ot ALTER COLUMN are_real DROP DEFAULT;
ALTER TABLE public.componentes_ot ALTER COLUMN pin_real DROP DEFAULT;

UPDATE public.componentes_ot SET
    hab_real = NULLIF(hab_real, -1),
    arm_real = NULLIF(arm_real, -1),
    sol_real = NULLIF(sol_real, -1),
    lim_real = NULLIF(lim_real, -1),
    lib_real = NULLIF(lib_real, -1),
    gal_real = NULLIF(gal_real, -1),
    are_real = NULLIF(are_real, -1),
    pin_real = NULLIF(pin_real, -1);

ALTER TABLE public.componentes_ot ADD CONSTRAINT ck_componentes_ot_hab_range CHECK (hab_real IS NULL OR hab_real BETWEEN 0 AND cantidad);
ALTER TABLE public.componentes_ot ADD CONSTRAINT ck_componentes_ot_arm_range CHECK (arm_real IS NULL OR arm_real BETWEEN 0 AND cantidad);
ALTER TABLE public.componentes_ot ADD CONSTRAINT ck_componentes_ot_sol_range CHECK (sol_real IS NULL OR sol_real BETWEEN 0 AND cantidad);
ALTER TABLE public.componentes_ot ADD CONSTRAINT ck_componentes_ot_lim_range CHECK (lim_real IS NULL OR lim_real BETWEEN 0 AND cantidad);
ALTER TABLE public.componentes_ot ADD CONSTRAINT ck_componentes_ot_lib_range CHECK (lib_real IS NULL OR lib_real BETWEEN 0 AND cantidad);
ALTER TABLE public.componentes_ot ADD CONSTRAINT ck_componentes_ot_gal_range CHECK (gal_real IS NULL OR gal_real BETWEEN 0 AND cantidad);
ALTER TABLE public.componentes_ot ADD CONSTRAINT ck_componentes_ot_are_range CHECK (are_real IS NULL OR are_real BETWEEN 0 AND cantidad);
ALTER TABLE public.componentes_ot ADD CONSTRAINT ck_componentes_ot_pin_range CHECK (pin_real IS NULL OR pin_real BETWEEN 0 AND cantidad);

ALTER TABLE public.avance_elemento_proceso DROP CONSTRAINT IF EXISTS ck_avance_elemento_cantidad;
ALTER TABLE public.avance_elemento_proceso ALTER COLUMN cantidad_completada DROP NOT NULL;
ALTER TABLE public.avance_elemento_proceso ALTER COLUMN cantidad_completada DROP DEFAULT;
UPDATE public.avance_elemento_proceso
SET cantidad_completada = NULL
WHERE aplica = false;
ALTER TABLE public.avance_elemento_proceso ADD CONSTRAINT ck_avance_elemento_cantidad CHECK (cantidad_completada IS NULL OR cantidad_completada >= 0);

-- 2) Período real de cada pieza/elemento para seguimiento y reportes.
ALTER TABLE public.componentes_ot ADD COLUMN IF NOT EXISTS fecha_inicio_real date;
ALTER TABLE public.componentes_ot ADD COLUMN IF NOT EXISTS fecha_termino_real date;
UPDATE public.componentes_ot
SET fecha_termino_real = fecha_realizacion
WHERE fecha_termino_real IS NULL AND fecha_realizacion IS NOT NULL;
ALTER TABLE public.componentes_ot DROP CONSTRAINT IF EXISTS ck_componentes_ot_periodo_real;
ALTER TABLE public.componentes_ot ADD CONSTRAINT ck_componentes_ot_periodo_real CHECK (
    fecha_inicio_real IS NULL
    OR fecha_termino_real IS NULL
    OR fecha_termino_real >= fecha_inicio_real
);
CREATE INDEX IF NOT EXISTS ix_componentes_ot_periodo_real
ON public.componentes_ot(fecha_inicio_real, fecha_termino_real);

-- El esquema queda equivalente a las migraciones 0015 y 0016.
UPDATE public.alembic_version
SET version_num = '20260824_0016';

COMMIT;

-- Verificación: ninguna fecha final puede ser menor que su inicio.
SELECT
    COUNT(*) FILTER (WHERE fecha_inicio_real IS NOT NULL) AS elementos_con_inicio,
    COUNT(*) FILTER (WHERE fecha_termino_real IS NOT NULL) AS elementos_con_termino,
    COUNT(*) FILTER (
        WHERE fecha_inicio_real IS NOT NULL
          AND fecha_termino_real IS NOT NULL
          AND fecha_termino_real < fecha_inicio_real
    ) AS periodos_invalidos
FROM public.componentes_ot;
