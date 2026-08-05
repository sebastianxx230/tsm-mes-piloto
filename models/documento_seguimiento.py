from datetime import datetime, timezone

from db_config import db


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class DocumentoSeguimiento(db.Model):
    __tablename__ = 'documentos_seguimiento'
    __table_args__ = (
        db.UniqueConstraint(
            'ot_id',
            'categoria',
            name='uq_documentos_seguimiento_ot_categoria',
        ),
        db.CheckConstraint(
            "categoria IN ('planos', 'otros')",
            name='ck_documentos_seguimiento_categoria',
        ),
        db.Index(
            'ix_documentos_seguimiento_ot_categoria',
            'ot_id',
            'categoria',
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    ot_id = db.Column(
        db.Integer,
        db.ForeignKey('catalogo_ot.item', ondelete='CASCADE'),
        nullable=False,
    )
    categoria = db.Column(db.String(20), nullable=False)
    drive_file_id = db.Column(db.String(150), nullable=False)
    drive_folder_id = db.Column(db.String(150), nullable=False)
    nombre = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(150), nullable=False)
    tamano = db.Column(db.BigInteger, nullable=True)
    carpeta_nombre = db.Column(db.String(255), nullable=False)
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

    @property
    def es_previsualizable(self):
        return (
                self.mime_type == 'application/pdf'
                or self.mime_type in {
                    'application/vnd.google-apps.document',
                    'application/vnd.google-apps.spreadsheet',
                    'application/vnd.google-apps.presentation',
                    'application/vnd.google-apps.drawing',
                }
                or self.nombre.lower().endswith('.pdf')
        )
