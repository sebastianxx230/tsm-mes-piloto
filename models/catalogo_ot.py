from datetime import datetime, timezone

from db_config import db
from utils.production_metrics import (
    DEFAULT_ACTIVE_PROCESSES,
    DEFAULT_PROCESS_WEIGHTS,
    process_settings,
)


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)

class CatalogoOT(db.Model):
    __tablename__ = 'catalogo_ot'
    __table_args__ = (
        db.Index('ix_catalogo_ot_fecha_iniciado', 'fecha_iniciado'),
        db.Index('ix_catalogo_ot_estado', 'estado'),
        db.Index('ix_catalogo_ot_archivado', 'archivado'),
        db.CheckConstraint('version >= 1', name='ck_catalogo_ot_version_positive'),
    )

    item = db.Column(db.Integer, primary_key=True)
    ot = db.Column(db.String(50), unique=True, nullable=False)
    cliente = db.Column(db.String(100), nullable=False)
    fecha_iniciado = db.Column(db.Date, nullable=False)
    fecha_termino = db.Column(db.Date, nullable=True)
    descripcion = db.Column(db.Text)
    estado = db.Column(db.String(30), default='En Proceso')
    version = db.Column(db.Integer, nullable=False, default=1, server_default='1')
    process_weights = db.Column(
        db.JSON,
        nullable=False,
        default=lambda: dict(DEFAULT_PROCESS_WEIGHTS),
    )
    active_processes = db.Column(
        db.JSON,
        nullable=False,
        default=lambda: dict(DEFAULT_ACTIVE_PROCESSES),
    )
    archivado = db.Column(db.Boolean, nullable=False, default=False, server_default='false')
    fecha_archivado = db.Column(db.DateTime, nullable=True)
    archivado_por_id = db.Column(
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

    packing_lists = db.relationship('PackingList', backref='ot_rel', lazy=True, cascade='all, delete-orphan')
    bitacoras = db.relationship('BitacoraOT', backref='ot_rel', lazy=True, cascade='all, delete-orphan')
    fotos_seguimiento = db.relationship(
        'FotoSeguimiento',
        backref='ot_rel',
        lazy=True,
        cascade='all, delete-orphan',
    )
    def to_dict(self):
        weights, active_processes = process_settings(self)
        return {
            'item': self.item,
            'ot': self.ot,
            'cliente': self.cliente,
            'fecha_iniciado': self.fecha_iniciado.strftime('%d/%m/%Y') if self.fecha_iniciado else '-',
            'fecha_termino': self.fecha_termino.strftime('%d/%m/%Y') if self.fecha_termino else '-',
            'descripcion': self.descripcion,
            'estado': self.estado,
            'version': self.version,
            'process_weights': weights,
            'active_processes': active_processes,
            'archivado': self.archivado,
        }

    def incrementar_version(self):
        self.version = max(int(self.version or 0), 0) + 1
        self.fecha_actualizacion = utc_now()
