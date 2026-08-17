from datetime import datetime, timedelta, timezone

from db_config import db


def utc_now():
    """Devuelve UTC sin zona para mantener compatibilidad con las columnas actuales."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


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
            'hab_real >= -1 AND hab_real <= cantidad',
            name='ck_componentes_ot_hab_range',
        ),
        db.CheckConstraint(
            'arm_real >= -1 AND arm_real <= cantidad',
            name='ck_componentes_ot_arm_range',
        ),
        db.CheckConstraint(
            'sol_real >= -1 AND sol_real <= cantidad',
            name='ck_componentes_ot_sol_range',
        ),
        db.CheckConstraint(
            'lim_real >= -1 AND lim_real <= cantidad',
            name='ck_componentes_ot_lim_range',
        ),
        db.CheckConstraint(
            'lib_real >= -1 AND lib_real <= cantidad',
            name='ck_componentes_ot_lib_range',
        ),
        db.CheckConstraint(
            'gal_real >= -1 AND gal_real <= cantidad',
            name='ck_componentes_ot_gal_range',
        ),
        db.CheckConstraint(
            'are_real >= -1 AND are_real <= cantidad',
            name='ck_componentes_ot_are_range',
        ),
        db.CheckConstraint(
            'pin_real >= -1 AND pin_real <= cantidad',
            name='ck_componentes_ot_pin_range',
        ),
        db.CheckConstraint(
            'des_real >= 0 AND des_real <= cantidad',
            name='ck_componentes_ot_des_range',
        ),
        db.Index('ix_componentes_ot_pl_id', 'pl_id'),
        db.Index('ix_componentes_ot_marca', 'marca'),
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

    tipo = db.Column(db.String(20), nullable=False, default='fabricacion')
    estado_suministro = db.Column(
        db.String(30),
        nullable=False,
        default='Pendiente',
    )
    operario = db.Column(db.String(500), nullable=False, default='')
    fecha_realizacion = db.Column(db.Date, nullable=True)

    # Una pieza nueva no debe asumir operaciones que quizá no necesita. Cada
    # proceso se habilita explícitamente desde su ficha; -1 significa N/A.
    hab_real = db.Column(db.Integer, nullable=False, default=-1)
    arm_real = db.Column(db.Integer, nullable=False, default=-1)
    sol_real = db.Column(db.Integer, nullable=False, default=-1)
    lim_real = db.Column(db.Integer, nullable=False, default=-1)
    lib_real = db.Column(db.Integer, nullable=False, default=-1)
    gal_real = db.Column(db.Integer, nullable=False, default=-1)
    are_real = db.Column(db.Integer, nullable=False, default=-1)
    pin_real = db.Column(db.Integer, nullable=False, default=-1)
    des_real = db.Column(db.Integer, nullable=False, default=0)
    alerta = db.Column(db.Boolean, nullable=False, default=False)

    def to_dict(self):
        return {
            'id': self.id,
            'pl_id': self.pl_id,
            'marca': self.marca,
            'cantidad': self.cantidad,
            'descripcion': self.descripcion,
            'longitud': self.longitud,
            'tipo': self.tipo,
            'estado_suministro': self.estado_suministro,
            'operario': self.operario,
            'fecha_realizacion': (
                self.fecha_realizacion.isoformat()
                if self.fecha_realizacion
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
