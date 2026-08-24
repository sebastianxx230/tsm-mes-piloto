from datetime import datetime, timedelta, timezone
from decimal import Decimal

from db_config import db


def utc_now():
    """Devuelve UTC sin zona para mantener compatibilidad con las columnas actuales."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _decimal_value(value):
    """Convierte Numeric a un valor JSON estable sin perder los nulos."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


class PackingList(db.Model):
    __tablename__ = 'packing_lists'
    __table_args__ = (
        db.UniqueConstraint(
            'ot_id',
            'orden',
            name='uq_packing_lists_ot_orden',
        ),
        db.CheckConstraint(
            'orden >= 0',
            name='ck_packing_lists_orden_nonnegative',
        ),
        db.CheckConstraint(
            'version >= 1',
            name='ck_packing_lists_version_positive',
        ),
        db.Index('ix_packing_lists_ot_orden', 'ot_id', 'orden'),
        db.Index('ix_packing_lists_archivado', 'archivado'),
    )

    id = db.Column(db.Integer, primary_key=True)
    ot_id = db.Column(
        db.Integer,
        db.ForeignKey('catalogo_ot.item', ondelete='CASCADE'),
        nullable=False,
    )
    nombre = db.Column(db.String(150), nullable=False)
    site = db.Column(db.String(150), nullable=True)
    orden = db.Column(
        db.Integer,
        nullable=False,
        default=0,
        server_default='0',
    )
    version = db.Column(
        db.Integer,
        nullable=False,
        default=1,
        server_default='1',
    )
    archivado = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
        server_default='false',
    )
    fecha_archivado = db.Column(db.DateTime, nullable=True)
    fecha_inicio_real = db.Column(db.Date, nullable=True)
    fecha_termino_real = db.Column(db.Date, nullable=True)
    archivado_por_id = db.Column(
        db.Integer,
        db.ForeignKey('usuarios.id', ondelete='SET NULL'),
        nullable=True,
    )
    fecha_creacion = db.Column(
        db.DateTime,
        nullable=False,
        default=utc_now,
    )
    fecha_actualizacion = db.Column(
        db.DateTime,
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    componentes = db.relationship(
        'ComponenteOT',
        backref='packing_list',
        lazy=True,
        cascade='all, delete-orphan',
        passive_deletes=True,
    )

    def incrementar_version(self):
        """Marca la lista como modificada para detectar importaciones obsoletas."""
        self.version = max(int(self.version or 0), 0) + 1
        self.fecha_actualizacion = utc_now()

    def to_dict(self):
        return {
            'id': self.id,
            'ot_id': self.ot_id,
            'nombre': self.nombre,
            'site': self.site,
            'orden': self.orden,
            'version': self.version,
            'archivado': self.archivado,
            'fecha_inicio_real': (
                self.fecha_inicio_real.isoformat()
                if self.fecha_inicio_real
                else None
            ),
            'fecha_termino_real': (
                self.fecha_termino_real.isoformat()
                if self.fecha_termino_real
                else None
            ),
            'fecha_actualizacion': (
                self.fecha_actualizacion.isoformat()
                if self.fecha_actualizacion
                else None
            ),
        }


class ComponenteOT(db.Model):
    __tablename__ = 'componentes_ot'
    __table_args__ = (
        db.CheckConstraint(
            'cantidad >= 0',
            name='ck_componentes_ot_cantidad_nonnegative',
        ),
        db.CheckConstraint(
            'hab_real IS NULL OR (hab_real >= 0 AND hab_real <= cantidad)',
            name='ck_componentes_ot_hab_range',
        ),
        db.CheckConstraint(
            'arm_real IS NULL OR (arm_real >= 0 AND arm_real <= cantidad)',
            name='ck_componentes_ot_arm_range',
        ),
        db.CheckConstraint(
            'sol_real IS NULL OR (sol_real >= 0 AND sol_real <= cantidad)',
            name='ck_componentes_ot_sol_range',
        ),
        db.CheckConstraint(
            'lim_real IS NULL OR (lim_real >= 0 AND lim_real <= cantidad)',
            name='ck_componentes_ot_lim_range',
        ),
        db.CheckConstraint(
            'lib_real IS NULL OR (lib_real >= 0 AND lib_real <= cantidad)',
            name='ck_componentes_ot_lib_range',
        ),
        db.CheckConstraint(
            'gal_real IS NULL OR (gal_real >= 0 AND gal_real <= cantidad)',
            name='ck_componentes_ot_gal_range',
        ),
        db.CheckConstraint(
            'are_real IS NULL OR (are_real >= 0 AND are_real <= cantidad)',
            name='ck_componentes_ot_are_range',
        ),
        db.CheckConstraint(
            'pin_real IS NULL OR (pin_real >= 0 AND pin_real <= cantidad)',
            name='ck_componentes_ot_pin_range',
        ),
        db.CheckConstraint(
            'des_real >= 0 AND des_real <= cantidad',
            name='ck_componentes_ot_des_range',
        ),
        db.CheckConstraint(
            'fecha_inicio_real IS NULL OR fecha_termino_real IS NULL OR '
            'fecha_termino_real >= fecha_inicio_real',
            name='ck_componentes_ot_periodo_real',
        ),
        db.Index('ix_componentes_ot_pl_id', 'pl_id'),
        db.Index('ix_componentes_ot_marca', 'marca'),
        db.Index(
            'ix_componentes_ot_categoria_estado',
            'categoria',
            'estado_suministro',
        ),
        db.Index(
            'ix_componentes_ot_periodo_real',
            'fecha_inicio_real',
            'fecha_termino_real',
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    pl_id = db.Column(
        db.Integer,
        db.ForeignKey('packing_lists.id', ondelete='CASCADE'),
        nullable=False,
    )

    marca = db.Column(db.String(100), nullable=False)
    cantidad = db.Column(db.Integer, nullable=False)
    descripcion = db.Column(db.Text)
    longitud = db.Column(db.String(50))

    # V2: ficha técnica general del item. Los campos originales permanecen
    # durante la transición para que la pantalla productiva actual siga activa.
    categoria = db.Column(
        db.String(30),
        nullable=False,
        default='FABRICACION',
        server_default='FABRICACION',
    )
    subcategoria = db.Column(db.String(50), nullable=True)
    unidad = db.Column(
        db.String(20),
        nullable=False,
        default='UND',
        server_default='UND',
    )
    ubicacion = db.Column(db.String(255), nullable=True)
    perfil = db.Column(db.String(150), nullable=True)
    material = db.Column(db.String(150), nullable=True)
    longitud_mm = db.Column(db.Numeric(14, 3), nullable=True)
    area_unitaria_m2 = db.Column(db.Numeric(14, 4), nullable=True)
    area_total_m2 = db.Column(db.Numeric(14, 4), nullable=True)
    peso_unitario_kg = db.Column(db.Numeric(14, 4), nullable=True)
    peso_total_kg = db.Column(db.Numeric(14, 4), nullable=True)
    fila_origen = db.Column(db.Integer, nullable=True)
    ruta_id = db.Column(
        db.Integer,
        db.ForeignKey('rutas_produccion.id', ondelete='SET NULL'),
        nullable=True,
    )
    importacion_id = db.Column(
        db.Integer,
        db.ForeignKey('importaciones_packing_list.id', ondelete='SET NULL'),
        nullable=True,
    )

    tipo = db.Column(db.String(20), nullable=False, default='fabricacion')
    estado_suministro = db.Column(
        db.String(30),
        nullable=False,
        default='Pendiente',
    )
    operario = db.Column(db.String(500), nullable=False, default='')
    fecha_inicio_real = db.Column(db.Date, nullable=True)
    fecha_termino_real = db.Column(db.Date, nullable=True)
    # Compatibilidad temporal con reportes V1; las pantallas nuevas usan el
    # período explícito anterior.
    fecha_realizacion = db.Column(db.Date, nullable=True)

    # NULL significa "aún no registrado". La pertenencia a la ruta se guarda
    # por separado en AvanceElementoProceso.aplica, sin mezclarla con el valor.
    hab_real = db.Column(db.Integer, nullable=True, default=None)
    arm_real = db.Column(db.Integer, nullable=True, default=None)
    sol_real = db.Column(db.Integer, nullable=True, default=None)
    lim_real = db.Column(db.Integer, nullable=True, default=None)
    lib_real = db.Column(db.Integer, nullable=True, default=None)
    gal_real = db.Column(db.Integer, nullable=True, default=None)
    are_real = db.Column(db.Integer, nullable=True, default=None)
    pin_real = db.Column(db.Integer, nullable=True, default=None)
    des_real = db.Column(db.Integer, nullable=False, default=0)
    alerta = db.Column(db.Boolean, nullable=False, default=False)

    # La ruta es opcional. Cargarla con JOIN hacía que PostgreSQL intentara
    # bloquear también el lado nullable de la relación al usar FOR UPDATE.
    # selectin mantiene la carga por lotes sin contaminar el SELECT bloqueado.
    ruta = db.relationship('RutaProduccion', lazy='selectin')
    avances_proceso = db.relationship(
        'AvanceElementoProceso',
        backref='componente',
        lazy=True,
        cascade='all, delete-orphan',
        passive_deletes=True,
    )

    def to_dict(self):
        return {
            'id': self.id,
            'pl_id': self.pl_id,
            'marca': self.marca,
            'cantidad': self.cantidad,
            'descripcion': self.descripcion,
            'longitud': self.longitud,
            'categoria': self.categoria,
            'subcategoria': self.subcategoria,
            'unidad': self.unidad,
            'ubicacion': self.ubicacion,
            'perfil': self.perfil,
            'material': self.material,
            'longitud_mm': _decimal_value(self.longitud_mm),
            'area_unitaria_m2': _decimal_value(self.area_unitaria_m2),
            'area_total_m2': _decimal_value(self.area_total_m2),
            'peso_unitario_kg': _decimal_value(self.peso_unitario_kg),
            'peso_total_kg': _decimal_value(self.peso_total_kg),
            'fila_origen': self.fila_origen,
            'ruta_id': self.ruta_id,
            'ruta_codigo': self.ruta.codigo if self.ruta else None,
            'tipo': self.tipo,
            'estado_suministro': self.estado_suministro,
            'operario': self.operario,
            'fecha_realizacion': (
                self.fecha_realizacion.isoformat()
                if self.fecha_realizacion
                else None
            ),
            'fecha_inicio_real': (
                self.fecha_inicio_real.isoformat()
                if self.fecha_inicio_real
                else None
            ),
            'fecha_termino_real': (
                self.fecha_termino_real.isoformat()
                if self.fecha_termino_real
                else None
            ),
            'hab_real': self.hab_real,
            'arm_real': self.arm_real,
            'sol_real': self.sol_real,
            'lim_real': self.lim_real,
            'lib_real': self.lib_real,
            'gal_real': self.gal_real,
            'are_real': self.are_real,
            'pin_real': self.pin_real,
            'des_real': self.des_real,
            'alerta': self.alerta,
        }


class PersonalProduccion(db.Model):
    """Directorio único de personal disponible para asignaciones de planta."""

    __tablename__ = 'personal_produccion'
    __table_args__ = (
        db.UniqueConstraint(
            'nombre_clave',
            name='uq_personal_produccion_nombre_clave',
        ),
        db.Index('ix_personal_produccion_activo_nombre', 'activo', 'nombre'),
    )

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False)
    nombre_clave = db.Column(db.String(160), nullable=False)
    activo = db.Column(
        db.Boolean,
        nullable=False,
        default=True,
        server_default='true',
    )
    fecha_creacion = db.Column(
        db.DateTime,
        nullable=False,
        default=utc_now,
    )
    fecha_actualizacion = db.Column(
        db.DateTime,
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    def to_dict(self):
        return {
            'id': self.id,
            'nombre': self.nombre,
            'activo': self.activo,
        }


class BitacoraOT(db.Model):
    __tablename__ = 'bitacora_ot'
    __table_args__ = (
        db.Index('ix_bitacora_ot_ot_fecha', 'ot_id', 'fecha_creacion'),
    )

    id = db.Column(db.Integer, primary_key=True)
    ot_id = db.Column(
        db.Integer,
        db.ForeignKey('catalogo_ot.item', ondelete='CASCADE'),
        nullable=False,
    )
    usuario_id = db.Column(
        db.Integer,
        db.ForeignKey('usuarios.id', ondelete='SET NULL'),
        nullable=True,
    )
    usuario_nombre = db.Column(db.String(100))
    mensaje = db.Column(db.Text, nullable=False)
    tipo = db.Column(db.String(50), nullable=False, default='manual')
    fecha_creacion = db.Column(
        db.DateTime,
        nullable=False,
        default=utc_now,
    )

    def to_dict(self):
        fecha_local = (
            self.fecha_creacion - timedelta(hours=5)
            if self.fecha_creacion
            else None
        )
        return {
            'id': self.id,
            'ot_id': self.ot_id,
            'usuario_id': self.usuario_id,
            'usuario_nombre': self.usuario_nombre,
            'mensaje': self.mensaje,
            'tipo': self.tipo,
            'fecha': (
                fecha_local.strftime('%d/%m/%Y %I:%M %p')
                if fecha_local
                else '-'
            ),
        }


class MovimientoAlmacen(db.Model):
    """Historial auditable de cambios de abastecimiento por componente."""

    __tablename__ = 'movimientos_almacen'
    __table_args__ = (
        db.Index(
            'ix_movimientos_almacen_ot_fecha',
            'ot_id',
            'fecha_creacion',
        ),
        db.Index(
            'ix_movimientos_almacen_componente_fecha',
            'componente_id',
            'fecha_creacion',
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    componente_id = db.Column(
        db.Integer,
        db.ForeignKey('componentes_ot.id', ondelete='SET NULL'),
        nullable=True,
    )
    packing_list_id = db.Column(
        db.Integer,
        db.ForeignKey('packing_lists.id', ondelete='SET NULL'),
        nullable=True,
    )
    ot_id = db.Column(
        db.Integer,
        db.ForeignKey('catalogo_ot.item', ondelete='CASCADE'),
        nullable=False,
    )
    codigo = db.Column(db.String(100), nullable=False)
    descripcion = db.Column(db.Text, nullable=True)
    cantidad = db.Column(db.Numeric(14, 3), nullable=False, default=0)
    unidad = db.Column(db.String(20), nullable=False, default='UND')
    estado_anterior = db.Column(db.String(30), nullable=False)
    estado_nuevo = db.Column(db.String(30), nullable=False)
    usuario_id = db.Column(
        db.Integer,
        db.ForeignKey('usuarios.id', ondelete='SET NULL'),
        nullable=True,
    )
    usuario_nombre = db.Column(db.String(100), nullable=True)
    fecha_creacion = db.Column(
        db.DateTime,
        nullable=False,
        default=utc_now,
    )


class FotoSeguimiento(db.Model):
    __tablename__ = 'fotos_seguimiento'
    __table_args__ = (
        db.UniqueConstraint(
            'ot_id',
            'drive_file_id',
            name='uq_fotos_seguimiento_ot_drive',
        ),
        db.CheckConstraint(
            'orden >= 0',
            name='ck_fotos_seguimiento_orden_nonnegative',
        ),
        db.Index('ix_fotos_seguimiento_ot_orden', 'ot_id', 'orden'),
    )

    id = db.Column(db.Integer, primary_key=True)
    ot_id = db.Column(
        db.Integer,
        db.ForeignKey('catalogo_ot.item', ondelete='CASCADE'),
        nullable=False,
    )
    drive_file_id = db.Column(db.String(150), nullable=False)
    nombre = db.Column(db.String(255), nullable=False)
    orden = db.Column(db.Integer, nullable=False, default=0)
    actualizado_por_id = db.Column(
        db.Integer,
        db.ForeignKey('usuarios.id', ondelete='SET NULL'),
        nullable=True,
    )
    fecha_actualizacion = db.Column(
        db.DateTime,
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    def to_dict(self):
        return {
            'id': self.id,
            'drive_file_id': self.drive_file_id,
            'name': self.nombre,
            'order': self.orden,
        }


class ProcesoProduccion(db.Model):
    """Catálogo extensible de procesos productivos de la V2."""

    __tablename__ = 'procesos_produccion'
    __table_args__ = (
        db.CheckConstraint('orden >= 0', name='ck_procesos_produccion_orden'),
        db.CheckConstraint(
            'peso_default >= 0 AND peso_default <= 100',
            name='ck_procesos_produccion_peso',
        ),
        db.Index('ix_procesos_produccion_activo_orden', 'activo', 'orden'),
    )

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(20), unique=True, nullable=False)
    nombre = db.Column(db.String(80), nullable=False)
    descripcion = db.Column(db.Text, nullable=True)
    orden = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    peso_default = db.Column(
        db.Numeric(5, 2),
        nullable=False,
        default=0,
        server_default='0',
    )
    controla_cantidad = db.Column(
        db.Boolean,
        nullable=False,
        default=True,
        server_default='true',
    )
    activo = db.Column(
        db.Boolean,
        nullable=False,
        default=True,
        server_default='true',
    )
    fecha_creacion = db.Column(db.DateTime, nullable=False, default=utc_now)
    fecha_actualizacion = db.Column(
        db.DateTime,
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    def to_dict(self):
        return {
            'id': self.id,
            'codigo': self.codigo,
            'nombre': self.nombre,
            'orden': self.orden,
            'peso_default': _decimal_value(self.peso_default),
            'controla_cantidad': self.controla_cantidad,
            'activo': self.activo,
        }


class RutaProduccion(db.Model):
    """Ruta reutilizable que define la secuencia válida de fabricación."""

    __tablename__ = 'rutas_produccion'
    __table_args__ = (
        db.Index('ix_rutas_produccion_activo_nombre', 'activo', 'nombre'),
    )

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(40), unique=True, nullable=False)
    nombre = db.Column(db.String(100), nullable=False)
    descripcion = db.Column(db.Text, nullable=True)
    activo = db.Column(
        db.Boolean,
        nullable=False,
        default=True,
        server_default='true',
    )
    fecha_creacion = db.Column(db.DateTime, nullable=False, default=utc_now)
    fecha_actualizacion = db.Column(
        db.DateTime,
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
    procesos = db.relationship(
        'RutaProceso',
        backref='ruta',
        lazy=True,
        cascade='all, delete-orphan',
        passive_deletes=True,
        order_by='RutaProceso.orden',
    )

    def to_dict(self, include_processes=False):
        payload = {
            'id': self.id,
            'codigo': self.codigo,
            'nombre': self.nombre,
            'descripcion': self.descripcion,
            'activo': self.activo,
        }
        if include_processes:
            payload['procesos'] = [step.to_dict() for step in self.procesos]
        return payload


class RutaProceso(db.Model):
    __tablename__ = 'ruta_procesos'
    __table_args__ = (
        db.UniqueConstraint(
            'ruta_id', 'proceso_id', name='uq_ruta_procesos_ruta_proceso'
        ),
        db.UniqueConstraint('ruta_id', 'orden', name='uq_ruta_procesos_orden'),
        db.CheckConstraint('orden >= 0', name='ck_ruta_procesos_orden'),
        db.CheckConstraint(
            'peso IS NULL OR (peso >= 0 AND peso <= 100)',
            name='ck_ruta_procesos_peso',
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    ruta_id = db.Column(
        db.Integer,
        db.ForeignKey('rutas_produccion.id', ondelete='CASCADE'),
        nullable=False,
    )
    proceso_id = db.Column(
        db.Integer,
        db.ForeignKey('procesos_produccion.id', ondelete='RESTRICT'),
        nullable=False,
    )
    orden = db.Column(db.Integer, nullable=False)
    obligatorio = db.Column(
        db.Boolean,
        nullable=False,
        default=True,
        server_default='true',
    )
    peso = db.Column(db.Numeric(5, 2), nullable=True)
    proceso = db.relationship('ProcesoProduccion', lazy='joined')

    def to_dict(self):
        return {
            'id': self.id,
            'orden': self.orden,
            'obligatorio': self.obligatorio,
            'peso': _decimal_value(self.peso),
            'proceso': self.proceso.to_dict(),
        }


class ImportacionPackingList(db.Model):
    """Trazabilidad de cada reemplazo proveniente de un libro Excel."""

    __tablename__ = 'importaciones_packing_list'
    __table_args__ = (
        db.Index(
            'ix_importaciones_packing_list_pl_fecha',
            'pl_id',
            'fecha_creacion',
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    pl_id = db.Column(
        db.Integer,
        db.ForeignKey('packing_lists.id', ondelete='CASCADE'),
        nullable=False,
    )
    archivo = db.Column(db.String(255), nullable=True)
    hoja = db.Column(db.String(100), nullable=True)
    ot_detectada = db.Column(db.String(50), nullable=True)
    cantidad_items = db.Column(db.Integer, nullable=False, default=0)
    advertencias = db.Column(db.JSON, nullable=False, default=list)
    creado_por_id = db.Column(
        db.Integer,
        db.ForeignKey('usuarios.id', ondelete='SET NULL'),
        nullable=True,
    )
    fecha_creacion = db.Column(db.DateTime, nullable=False, default=utc_now)


class AvanceElementoProceso(db.Model):
    """Estado normalizado de un proceso para un elemento de fabricación."""

    __tablename__ = 'avance_elemento_proceso'
    __table_args__ = (
        db.UniqueConstraint(
            'componente_id',
            'proceso_id',
            name='uq_avance_elemento_proceso',
        ),
        db.CheckConstraint('orden >= 0', name='ck_avance_elemento_orden'),
        db.CheckConstraint(
            'cantidad_completada IS NULL OR cantidad_completada >= 0',
            name='ck_avance_elemento_cantidad',
        ),
        db.Index(
            'ix_avance_elemento_componente_orden',
            'componente_id',
            'orden',
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    componente_id = db.Column(
        db.Integer,
        db.ForeignKey('componentes_ot.id', ondelete='CASCADE'),
        nullable=False,
    )
    proceso_id = db.Column(
        db.Integer,
        db.ForeignKey('procesos_produccion.id', ondelete='RESTRICT'),
        nullable=False,
    )
    orden = db.Column(db.Integer, nullable=False)
    aplica = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
        server_default='false',
    )
    cantidad_completada = db.Column(
        db.Integer,
        nullable=True,
        default=None,
    )
    fecha_inicio = db.Column(db.Date, nullable=True)
    fecha_fin = db.Column(db.Date, nullable=True)
    actualizado_por_id = db.Column(
        db.Integer,
        db.ForeignKey('usuarios.id', ondelete='SET NULL'),
        nullable=True,
    )
    fecha_actualizacion = db.Column(
        db.DateTime,
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
    proceso = db.relationship('ProcesoProduccion', lazy='joined')

    def to_dict(self):
        return {
            'id': self.id,
            'proceso': self.proceso.to_dict(),
            'orden': self.orden,
            'aplica': self.aplica,
            'cantidad_completada': self.cantidad_completada,
            'fecha_inicio': (
                self.fecha_inicio.isoformat() if self.fecha_inicio else None
            ),
            'fecha_fin': self.fecha_fin.isoformat() if self.fecha_fin else None,
            'fecha_actualizacion': (
                self.fecha_actualizacion.isoformat()
                if self.fecha_actualizacion
                else None
            ),
        }
