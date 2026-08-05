from db_config import db
from flask_login import UserMixin

class Usuario(db.Model, UserMixin):
    __tablename__ = 'usuarios'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    rol = db.Column(db.String(20), nullable=False) # 'admin', 'editor', 'viewer'
    activo = db.Column(db.Boolean, default=True)
    nombre = db.Column(db.String(100), nullable=False)

    @staticmethod
    def get_by_id(user_id):
        return db.session.get(Usuario, int(user_id))

    @staticmethod
    def get_by_username(username):
        return Usuario.query.filter_by(username=username).first()
