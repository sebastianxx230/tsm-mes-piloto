# db_config.py
from flask_sqlalchemy import SQLAlchemy

# Esta es la instancia de la base de datos (db)
# que será usada por app.py y los nuevos modelos de SQLAlchemy.
db = SQLAlchemy()