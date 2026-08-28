-- RECONSTRUCCIÓN DESTRUCTIVA DEL PILOTO MES V3
-- Conserva public.catalogo_ot y public.usuarios, incluidas sus secuencias.
-- Elimina únicamente datos operativos, archivos y configuración derivada.
-- Ejecutar UNA sola vez en Neon SQL Editor con la aplicación detenida.

BEGIN;

DO $$
BEGIN
    IF to_regclass('public.catalogo_ot') IS NULL THEN
        RAISE EXCEPTION 'Se canceló: public.catalogo_ot no existe.';
    END IF;
    IF to_regclass('public.usuarios') IS NULL THEN
        RAISE EXCEPTION 'Se canceló: public.usuarios no existe.';
    END IF;
END $$;

LOCK TABLE public.catalogo_ot IN ACCESS EXCLUSIVE MODE;
LOCK TABLE public.usuarios IN ACCESS EXCLUSIVE MODE;
CREATE TEMP TABLE _catalogo_guard AS
SELECT COUNT(*)::bigint AS total FROM public.catalogo_ot;
CREATE TEMP TABLE _usuarios_guard AS
SELECT COUNT(*)::bigint AS total FROM public.usuarios;

DROP VIEW IF EXISTS public.vw_ot_personal_produccion;

DROP TABLE IF EXISTS
    public.asignaciones_personal_proceso,
    public.avance_elemento_proceso,
    public.produccion_avances,
    public.componentes_ot,
    public.importaciones_packing_list,
    public.ruta_procesos,
    public.rutas_produccion,
    public.procesos_produccion,
    public.packing_list_componentes,
    public.packing_lists,
    public.bitacora_ot,
    public.documentos_seguimiento,
    public.fotos_seguimiento,
    public.movimientos_almacen,
    public.personal_produccion,
    public.usuario_roles,
    public.rol_permisos,
    public.permisos_sistema,
    public.roles_sistema,
    public.alembic_version
CASCADE;

UPDATE public.usuarios
SET
    rol = COALESCE(NULLIF(BTRIM(rol), ''), 'viewer'),
    activo = COALESCE(activo, true),
    nombre = COALESCE(NULLIF(BTRIM(nombre), ''), username);

ALTER TABLE public.usuarios
    ALTER COLUMN rol SET DEFAULT 'viewer',
    ALTER COLUMN rol SET NOT NULL,
    ALTER COLUMN activo SET DEFAULT true,
    ALTER COLUMN activo SET NOT NULL,
    ALTER COLUMN nombre SET NOT NULL;

ALTER TABLE public.catalogo_ot
    DROP CONSTRAINT IF EXISTS ck_catalogo_ot_periodo_programado;

-- Los registros históricos sin fecha de término se conservan usando su fecha
-- de inicio como valor mínimo válido. Desde V3 toda OT exige ambas fechas.
UPDATE public.catalogo_ot
SET fecha_termino = fecha_iniciado
WHERE fecha_termino IS NULL;

ALTER TABLE public.catalogo_ot
    ADD CONSTRAINT ck_catalogo_ot_periodo_programado CHECK (
        fecha_termino >= fecha_iniciado
    ),
    ALTER COLUMN fecha_termino SET NOT NULL;

CREATE TABLE public.roles_sistema (
    id serial PRIMARY KEY,
    clave varchar(50) NOT NULL UNIQUE,
    nombre varchar(100) NOT NULL,
    descripcion text,
    activo boolean NOT NULL DEFAULT true
);

CREATE TABLE public.permisos_sistema (
    id serial PRIMARY KEY,
    clave varchar(80) NOT NULL UNIQUE,
    nombre varchar(120) NOT NULL,
    descripcion text
);

CREATE TABLE public.usuario_roles (
    usuario_id integer NOT NULL REFERENCES public.usuarios(id) ON DELETE CASCADE,
    rol_id integer NOT NULL REFERENCES public.roles_sistema(id) ON DELETE CASCADE,
    PRIMARY KEY (usuario_id, rol_id)
);

CREATE TABLE public.rol_permisos (
    rol_id integer NOT NULL REFERENCES public.roles_sistema(id) ON DELETE CASCADE,
    permiso_id integer NOT NULL REFERENCES public.permisos_sistema(id) ON DELETE CASCADE,
    PRIMARY KEY (rol_id, permiso_id)
);

CREATE TABLE public.procesos_produccion (
    id serial PRIMARY KEY,
    codigo varchar(20) NOT NULL UNIQUE,
    nombre varchar(80) NOT NULL,
    descripcion text,
    orden integer NOT NULL DEFAULT 0 CHECK (orden >= 0),
    peso_default numeric(5,2) NOT NULL DEFAULT 0 CHECK (peso_default BETWEEN 0 AND 100),
    controla_cantidad boolean NOT NULL DEFAULT true,
    activo boolean NOT NULL DEFAULT true,
    fecha_creacion timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fecha_actualizacion timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE public.rutas_produccion (
    id serial PRIMARY KEY,
    codigo varchar(40) NOT NULL UNIQUE,
    nombre varchar(100) NOT NULL,
    descripcion text,
    activo boolean NOT NULL DEFAULT true,
    fecha_creacion timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fecha_actualizacion timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE public.ruta_procesos (
    id serial PRIMARY KEY,
    ruta_id integer NOT NULL REFERENCES public.rutas_produccion(id) ON DELETE CASCADE,
    proceso_id integer NOT NULL REFERENCES public.procesos_produccion(id) ON DELETE RESTRICT,
    orden integer NOT NULL CHECK (orden >= 0),
    obligatorio boolean NOT NULL DEFAULT true,
    peso numeric(5,2) CHECK (peso IS NULL OR peso BETWEEN 0 AND 100),
    CONSTRAINT uq_ruta_procesos_ruta_proceso UNIQUE (ruta_id, proceso_id),
    CONSTRAINT uq_ruta_procesos_orden UNIQUE (ruta_id, orden)
);

CREATE TABLE public.packing_lists (
    id serial PRIMARY KEY,
    ot_id integer NOT NULL REFERENCES public.catalogo_ot(item) ON DELETE CASCADE,
    nombre varchar(150) NOT NULL,
    site varchar(150),
    orden integer NOT NULL DEFAULT 0 CHECK (orden >= 0),
    version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
    archivado boolean NOT NULL DEFAULT false,
    fecha_archivado timestamp,
    fecha_inicio_real date,
    fecha_termino_real date,
    archivado_por_id integer REFERENCES public.usuarios(id) ON DELETE SET NULL,
    fecha_creacion timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fecha_actualizacion timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_packing_lists_ot_orden UNIQUE (ot_id, orden)
);

CREATE TABLE public.importaciones_packing_list (
    id serial PRIMARY KEY,
    pl_id integer NOT NULL REFERENCES public.packing_lists(id) ON DELETE CASCADE,
    archivo varchar(255),
    hoja varchar(100),
    ot_detectada varchar(50),
    cantidad_items integer NOT NULL DEFAULT 0,
    advertencias json NOT NULL DEFAULT '[]'::json,
    creado_por_id integer REFERENCES public.usuarios(id) ON DELETE SET NULL,
    fecha_creacion timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE public.componentes_ot (
    id serial PRIMARY KEY,
    pl_id integer NOT NULL REFERENCES public.packing_lists(id) ON DELETE CASCADE,
    marca varchar(100) NOT NULL,
    cantidad integer NOT NULL CHECK (cantidad >= 0),
    descripcion text,
    longitud varchar(50),
    categoria varchar(30) NOT NULL DEFAULT 'FABRICACION',
    subcategoria varchar(50),
    unidad varchar(20) NOT NULL DEFAULT 'UND',
    ubicacion varchar(255),
    perfil varchar(150),
    material varchar(150),
    longitud_mm numeric(14,3),
    area_unitaria_m2 numeric(14,4),
    area_total_m2 numeric(14,4),
    peso_unitario_kg numeric(14,4),
    peso_total_kg numeric(14,4),
    fila_origen integer,
    ruta_id integer REFERENCES public.rutas_produccion(id) ON DELETE SET NULL,
    importacion_id integer REFERENCES public.importaciones_packing_list(id) ON DELETE SET NULL,
    tipo varchar(20) NOT NULL DEFAULT 'fabricacion',
    estado_suministro varchar(30) NOT NULL DEFAULT 'Pendiente' CHECK (
        estado_suministro IN (
            'Pendiente', 'No requerido', 'No comprado', 'En compra',
            'Comprado', 'En almacén', 'Despachado'
        )
    ),
    operario varchar(500) NOT NULL DEFAULT '',
    fecha_realizacion date,
    fecha_inicio_real date,
    fecha_termino_real date,
    hab_real integer CHECK (hab_real IS NULL OR hab_real BETWEEN 0 AND cantidad),
    arm_real integer CHECK (arm_real IS NULL OR arm_real BETWEEN 0 AND cantidad),
    sol_real integer CHECK (sol_real IS NULL OR sol_real BETWEEN 0 AND cantidad),
    lim_real integer CHECK (lim_real IS NULL OR lim_real BETWEEN 0 AND cantidad),
    lib_real integer CHECK (lib_real IS NULL OR lib_real BETWEEN 0 AND cantidad),
    gal_real integer CHECK (gal_real IS NULL OR gal_real BETWEEN 0 AND cantidad),
    are_real integer CHECK (are_real IS NULL OR are_real BETWEEN 0 AND cantidad),
    pin_real integer CHECK (pin_real IS NULL OR pin_real BETWEEN 0 AND cantidad),
    des_real integer NOT NULL DEFAULT 0 CHECK (des_real BETWEEN 0 AND cantidad),
    alerta boolean NOT NULL DEFAULT false,
    CONSTRAINT ck_componentes_ot_periodo_real CHECK (
        fecha_inicio_real IS NULL OR fecha_termino_real IS NULL
        OR fecha_termino_real >= fecha_inicio_real
    )
);

CREATE TABLE public.avance_elemento_proceso (
    id serial PRIMARY KEY,
    componente_id integer NOT NULL REFERENCES public.componentes_ot(id) ON DELETE CASCADE,
    proceso_id integer NOT NULL REFERENCES public.procesos_produccion(id) ON DELETE RESTRICT,
    orden integer NOT NULL CHECK (orden >= 0),
    aplica boolean NOT NULL DEFAULT false,
    cantidad_completada integer CHECK (cantidad_completada IS NULL OR cantidad_completada >= 0),
    fecha_inicio date,
    fecha_fin date,
    actualizado_por_id integer REFERENCES public.usuarios(id) ON DELETE SET NULL,
    fecha_actualizacion timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_avance_elemento_proceso UNIQUE (componente_id, proceso_id)
);

CREATE TABLE public.personal_produccion (
    id serial PRIMARY KEY,
    nombre varchar(120) NOT NULL,
    nombre_clave varchar(160) NOT NULL UNIQUE,
    activo boolean NOT NULL DEFAULT true,
    fecha_creacion timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fecha_actualizacion timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE public.asignaciones_personal_proceso (
    id serial PRIMARY KEY,
    avance_id integer NOT NULL REFERENCES public.avance_elemento_proceso(id) ON DELETE CASCADE,
    personal_id integer NOT NULL REFERENCES public.personal_produccion(id) ON DELETE RESTRICT,
    asignado_por_id integer REFERENCES public.usuarios(id) ON DELETE SET NULL,
    fecha_creacion timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fecha_actualizacion timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_asignacion_personal_avance UNIQUE (avance_id, personal_id)
);

CREATE TABLE public.bitacora_ot (
    id serial PRIMARY KEY,
    ot_id integer NOT NULL REFERENCES public.catalogo_ot(item) ON DELETE CASCADE,
    usuario_id integer REFERENCES public.usuarios(id) ON DELETE SET NULL,
    usuario_nombre varchar(100),
    mensaje text NOT NULL,
    tipo varchar(50) NOT NULL DEFAULT 'manual',
    fecha_creacion timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE public.movimientos_almacen (
    id serial PRIMARY KEY,
    componente_id integer REFERENCES public.componentes_ot(id) ON DELETE SET NULL,
    packing_list_id integer REFERENCES public.packing_lists(id) ON DELETE SET NULL,
    ot_id integer NOT NULL REFERENCES public.catalogo_ot(item) ON DELETE CASCADE,
    codigo varchar(100) NOT NULL,
    descripcion text,
    cantidad numeric(14,3) NOT NULL DEFAULT 0,
    unidad varchar(20) NOT NULL DEFAULT 'UND',
    estado_anterior varchar(30) NOT NULL,
    estado_nuevo varchar(30) NOT NULL,
    usuario_id integer REFERENCES public.usuarios(id) ON DELETE SET NULL,
    usuario_nombre varchar(100),
    fecha_creacion timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE public.fotos_seguimiento (
    id serial PRIMARY KEY,
    ot_id integer NOT NULL REFERENCES public.catalogo_ot(item) ON DELETE CASCADE,
    drive_file_id varchar(150) NOT NULL,
    nombre varchar(255) NOT NULL,
    orden integer NOT NULL DEFAULT 0 CHECK (orden >= 0),
    actualizado_por_id integer REFERENCES public.usuarios(id) ON DELETE SET NULL,
    fecha_actualizacion timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_fotos_seguimiento_ot_drive UNIQUE (ot_id, drive_file_id)
);

CREATE TABLE public.documentos_seguimiento (
    id serial PRIMARY KEY,
    ot_id integer NOT NULL REFERENCES public.catalogo_ot(item) ON DELETE CASCADE,
    categoria varchar(20) NOT NULL CHECK (categoria IN ('planos', 'otros')),
    drive_file_id varchar(150) NOT NULL,
    drive_folder_id varchar(150) NOT NULL,
    nombre varchar(255) NOT NULL,
    mime_type varchar(150) NOT NULL,
    tamano bigint,
    carpeta_nombre varchar(255) NOT NULL,
    actualizado_por_id integer REFERENCES public.usuarios(id) ON DELETE SET NULL,
    fecha_actualizacion timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_documentos_seguimiento_ot_categoria UNIQUE (ot_id, categoria)
);

CREATE INDEX ix_packing_lists_ot_orden ON public.packing_lists(ot_id, orden);
CREATE INDEX ix_packing_lists_archivado ON public.packing_lists(archivado);
CREATE INDEX ix_componentes_ot_pl_id ON public.componentes_ot(pl_id);
CREATE INDEX ix_componentes_ot_marca ON public.componentes_ot(marca);
CREATE INDEX ix_componentes_ot_periodo_real ON public.componentes_ot(fecha_inicio_real, fecha_termino_real);
CREATE INDEX ix_componentes_ot_categoria_estado ON public.componentes_ot(categoria, estado_suministro);
CREATE INDEX ix_avance_elemento_componente_orden ON public.avance_elemento_proceso(componente_id, orden);
CREATE INDEX ix_personal_produccion_activo_nombre ON public.personal_produccion(activo, nombre);
CREATE INDEX ix_asignaciones_personal_avance ON public.asignaciones_personal_proceso(avance_id);
CREATE INDEX ix_asignaciones_personal_personal_avance ON public.asignaciones_personal_proceso(personal_id, avance_id);
CREATE INDEX ix_bitacora_ot_ot_fecha ON public.bitacora_ot(ot_id, fecha_creacion);
CREATE INDEX ix_movimientos_almacen_ot_fecha ON public.movimientos_almacen(ot_id, fecha_creacion);
CREATE INDEX ix_movimientos_almacen_componente_fecha ON public.movimientos_almacen(componente_id, fecha_creacion);
CREATE INDEX ix_fotos_seguimiento_ot_orden ON public.fotos_seguimiento(ot_id, orden);
CREATE INDEX ix_documentos_seguimiento_ot_categoria ON public.documentos_seguimiento(ot_id, categoria);
CREATE INDEX ix_procesos_produccion_activo_orden ON public.procesos_produccion(activo, orden);
CREATE INDEX ix_rutas_produccion_activo_nombre ON public.rutas_produccion(activo, nombre);
CREATE INDEX ix_importaciones_packing_list_pl_fecha ON public.importaciones_packing_list(pl_id, fecha_creacion);

INSERT INTO public.permisos_sistema (clave, nombre) VALUES
('ot.view','Consultar órdenes de trabajo'),('ot.create','Crear órdenes de trabajo'),('ot.edit','Editar órdenes de trabajo'),('ot.archive','Archivar órdenes de trabajo'),
('production.view','Consultar producción'),('production.summary.view','Consultar resumen de producción'),('production.edit','Registrar avances de producción'),('production.process.edit','Configurar procesos y rutas'),('production.personnel.assign','Asignar personal de producción'),('production.incident.create','Registrar incidencias de producción'),('production.progress.view','Consultar avance operativo de producción'),
('messages.view','Consultar mensajes de órdenes de trabajo'),('messages.write','Registrar mensajes de órdenes de trabajo'),
('planning.view','Consultar planeamiento'),('planning.edit','Editar planeamiento'),('planning.schedule.edit','Editar programación'),
('warehouse.view','Consultar almacén'),('warehouse.movements.create','Registrar movimientos de almacén'),('warehouse.kardex.view','Consultar Kardex'),('warehouse.adjust','Ajustar existencias de almacén'),
('logistics.view','Consultar logística'),('logistics.dispatch.create','Crear despachos'),('logistics.dispatch.edit','Editar despachos'),
('quality.view','Consultar calidad'),('quality.inspect','Registrar inspecciones'),('quality.release','Liberar elementos'),('quality.documents.upload','Subir documentos de calidad'),
('documents.view','Consultar documentos'),('documents.upload','Subir documentos'),('documents.publish','Publicar documentos'),
('photos.view','Consultar fotografías'),('photos.upload','Subir fotografías'),('photos.publish','Publicar fotografías'),
('reports.view','Consultar reportes'),('reports.generate','Generar reportes'),('reports.export','Exportar reportes'),
('client_portal.create','Crear enlaces de portal cliente'),('client_portal.publish','Publicar en portal cliente'),('client_portal.revoke','Revocar enlaces de portal cliente'),
('users.manage','Gestionar usuarios'),('roles.manage','Gestionar roles'),('permissions.manage','Gestionar permisos'),('settings.manage','Gestionar configuración técnica'),('audit.view','Consultar auditoría');

INSERT INTO public.roles_sistema (clave, nombre, descripcion) VALUES
('administrador_sistema','Administrador del sistema','Configuración técnica, usuarios, roles y auditoría.'),
('produccion_oficina','Producción Oficina','Gestión operativa completa de producción.'),
('produccion_planta','Producción Planta','Consulta simplificada del avance de planta.'),
('planeamiento','Planeamiento','Programación y seguimiento del plan.'),
('almacen','Almacén','Abastecimiento y movimientos de materiales.'),
('logistica','Logística','Despachos y documentación de salida.'),
('calidad','Calidad','Inspecciones, liberaciones y documentación.'),
('comercial','Comercial','Consulta de hitos e información publicable.'),
('gerencia','Gerencia','Indicadores ejecutivos de todos los módulos.'),
('administracion','Administración','Consulta administrativa y reportes.');

WITH grants(role_key, permission_key) AS (VALUES
('administrador_sistema','users.manage'),('administrador_sistema','roles.manage'),('administrador_sistema','permissions.manage'),('administrador_sistema','settings.manage'),('administrador_sistema','audit.view'),
('produccion_oficina','ot.view'),('produccion_oficina','ot.create'),('produccion_oficina','ot.edit'),('produccion_oficina','ot.archive'),('produccion_oficina','production.view'),('produccion_oficina','production.summary.view'),('produccion_oficina','production.edit'),('produccion_oficina','production.process.edit'),('produccion_oficina','production.personnel.assign'),('produccion_oficina','production.incident.create'),('produccion_oficina','production.progress.view'),('produccion_oficina','messages.view'),('produccion_oficina','messages.write'),('produccion_oficina','warehouse.view'),('produccion_oficina','documents.view'),('produccion_oficina','documents.upload'),('produccion_oficina','documents.publish'),('produccion_oficina','photos.view'),('produccion_oficina','photos.upload'),('produccion_oficina','photos.publish'),('produccion_oficina','reports.view'),('produccion_oficina','reports.generate'),('produccion_oficina','reports.export'),
('produccion_planta','ot.view'),('produccion_planta','production.view'),('produccion_planta','production.summary.view'),('produccion_planta','production.progress.view'),('produccion_planta','messages.view'),('produccion_planta','documents.view'),('produccion_planta','photos.view'),('produccion_planta','reports.view'),
('planeamiento','ot.view'),('planeamiento','production.view'),('planeamiento','production.summary.view'),('planeamiento','production.progress.view'),('planeamiento','messages.view'),('planeamiento','planning.view'),('planeamiento','planning.edit'),('planeamiento','planning.schedule.edit'),('planeamiento','reports.view'),('planeamiento','reports.export'),
('almacen','ot.view'),('almacen','production.summary.view'),('almacen','messages.view'),('almacen','messages.write'),('almacen','warehouse.view'),('almacen','warehouse.movements.create'),('almacen','warehouse.kardex.view'),('almacen','warehouse.adjust'),('almacen','reports.view'),('almacen','reports.export'),
('logistica','ot.view'),('logistica','production.summary.view'),('logistica','messages.view'),('logistica','warehouse.view'),('logistica','logistics.view'),('logistica','logistics.dispatch.create'),('logistica','logistics.dispatch.edit'),('logistica','documents.view'),('logistica','documents.upload'),('logistica','reports.view'),('logistica','reports.export'),
('calidad','ot.view'),('calidad','production.view'),('calidad','production.summary.view'),('calidad','production.progress.view'),('calidad','messages.view'),('calidad','quality.view'),('calidad','quality.inspect'),('calidad','quality.release'),('calidad','quality.documents.upload'),('calidad','documents.view'),('calidad','documents.upload'),('calidad','photos.view'),('calidad','photos.upload'),('calidad','reports.view'),('calidad','reports.export'),
('comercial','ot.view'),('comercial','production.summary.view'),('comercial','messages.view'),('comercial','documents.view'),('comercial','photos.view'),('comercial','reports.view'),('comercial','reports.export'),
('gerencia','ot.view'),('gerencia','production.summary.view'),('gerencia','production.progress.view'),('gerencia','messages.view'),('gerencia','planning.view'),('gerencia','warehouse.view'),('gerencia','logistics.view'),('gerencia','quality.view'),('gerencia','documents.view'),('gerencia','photos.view'),('gerencia','reports.view'),('gerencia','reports.export'),
('administracion','ot.view'),('administracion','production.summary.view'),('administracion','messages.view'),('administracion','planning.view'),('administracion','warehouse.view'),('administracion','logistics.view'),('administracion','documents.view'),('administracion','reports.view'),('administracion','reports.export')
)
INSERT INTO public.rol_permisos (rol_id, permiso_id)
SELECT r.id, p.id FROM grants g
JOIN public.roles_sistema r ON r.clave = g.role_key
JOIN public.permisos_sistema p ON p.clave = g.permission_key;

-- Conserva las cuentas existentes y reconstruye sus asignaciones V2.
WITH legacy_assignments(legacy_role, role_key) AS (VALUES
    ('admin', 'administrador_sistema'),
    ('admin', 'produccion_oficina'),
    ('editor', 'produccion_oficina'),
    ('viewer', 'produccion_planta'),
    ('produccion_oficina', 'produccion_oficina'),
    ('produccion_planta', 'produccion_planta'),
    ('planeamiento', 'planeamiento'),
    ('almacen', 'almacen'),
    ('logistica', 'logistica'),
    ('calidad', 'calidad'),
    ('comercial', 'comercial'),
    ('gerencia', 'gerencia'),
    ('administracion', 'administracion')
)
INSERT INTO public.usuario_roles (usuario_id, rol_id)
SELECT u.id, r.id
FROM public.usuarios u
JOIN legacy_assignments a
  ON LOWER(BTRIM(u.rol)) = a.legacy_role
JOIN public.roles_sistema r
  ON r.clave = a.role_key
ON CONFLICT DO NOTHING;

INSERT INTO public.procesos_produccion (codigo,nombre,orden,peso_default) VALUES
('hab','Habilitado',0,12),('arm','Armado',1,24),('sol','Soldadura',2,28),
('lim','Limpieza',3,12),('lib','Liberación',4,6),('gal','Galvanizado',5,6),
('are','Arenado',6,6),('pin','Pintado',7,6),('des','Despacho',8,0);

INSERT INTO public.rutas_produccion (codigo,nombre) VALUES
('GALVANIZADO','Fabricación galvanizada'),
('PINTADO','Fabricación pintada');

WITH route_steps(route_code, process_code, step_order) AS (VALUES
('GALVANIZADO','hab',0),('GALVANIZADO','arm',1),('GALVANIZADO','sol',2),('GALVANIZADO','lim',3),('GALVANIZADO','lib',4),('GALVANIZADO','gal',5),('GALVANIZADO','des',6),
('PINTADO','hab',0),('PINTADO','arm',1),('PINTADO','sol',2),('PINTADO','lim',3),('PINTADO','lib',4),('PINTADO','are',5),('PINTADO','pin',6),('PINTADO','des',7)
)
INSERT INTO public.ruta_procesos (ruta_id, proceso_id, orden)
SELECT r.id, p.id, s.step_order FROM route_steps s
JOIN public.rutas_produccion r ON r.codigo = s.route_code
JOIN public.procesos_produccion p ON p.codigo = s.process_code;

CREATE VIEW public.vw_ot_personal_produccion AS
SELECT
    ot.item AS ot_id,
    ot.ot,
    ot.cliente,
    ot.fecha_iniciado AS fecha_inicio_ot,
    ot.fecha_termino AS fecha_termino_ot,
    pl.id AS packing_list_id,
    pl.nombre AS packing_list,
    pl.site,
    componente.id AS componente_id,
    componente.marca AS codigo_elemento,
    componente.descripcion AS elemento,
    componente.cantidad AS cantidad_elemento,
    proceso.id AS proceso_id,
    proceso.codigo AS proceso_codigo,
    proceso.nombre AS proceso,
    avance.orden AS orden_proceso,
    avance.aplica,
    avance.cantidad_completada,
    avance.fecha_inicio,
    avance.fecha_fin AS fecha_termino,
    personal.id AS personal_id,
    personal.nombre AS personal,
    personal.activo AS personal_activo,
    asignacion.asignado_por_id,
    asignacion.fecha_creacion AS fecha_asignacion,
    asignacion.fecha_actualizacion
FROM public.asignaciones_personal_proceso asignacion
JOIN public.avance_elemento_proceso avance ON avance.id = asignacion.avance_id
JOIN public.personal_produccion personal ON personal.id = asignacion.personal_id
JOIN public.procesos_produccion proceso ON proceso.id = avance.proceso_id
JOIN public.componentes_ot componente ON componente.id = avance.componente_id
JOIN public.packing_lists pl ON pl.id = componente.pl_id
JOIN public.catalogo_ot ot ON ot.item = pl.ot_id
WHERE pl.archivado = false;

CREATE TABLE public.alembic_version (
    version_num varchar(32) PRIMARY KEY
);
INSERT INTO public.alembic_version(version_num) VALUES ('20260828_0018');

DO $$
DECLARE expected_count bigint;
DECLARE actual_count bigint;
DECLARE expected_users bigint;
DECLARE actual_users bigint;
BEGIN
    SELECT total INTO expected_count FROM _catalogo_guard;
    SELECT COUNT(*) INTO actual_count FROM public.catalogo_ot;
    IF actual_count <> expected_count THEN
        RAISE EXCEPTION 'Se canceló: catalogo_ot cambió de % a % filas.', expected_count, actual_count;
    END IF;
    SELECT total INTO expected_users FROM _usuarios_guard;
    SELECT COUNT(*) INTO actual_users FROM public.usuarios;
    IF actual_users <> expected_users THEN
        RAISE EXCEPTION 'Se canceló: usuarios cambió de % a % filas.', expected_users, actual_users;
    END IF;
END $$;

COMMIT;

-- Verificación esperada: catalog_count y users conservan sus valores previos.
SELECT
    (SELECT COUNT(*) FROM public.catalogo_ot) AS catalog_count,
    (SELECT COUNT(*) FROM public.usuarios) AS users,
    (SELECT COUNT(*) FROM public.roles_sistema) AS roles,
    (SELECT COUNT(*) FROM public.permisos_sistema) AS permissions,
    (SELECT version_num FROM public.alembic_version) AS migration;
