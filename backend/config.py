# backend/config.py

import os
basedir = os.path.abspath(os.path.dirname(__file__))

# Este bloco carrega o arquivo .env.local, tornando as variáveis disponíveis para 'os.environ.get'
from dotenv import load_dotenv
dotenv_path = os.path.join(os.path.dirname(basedir), '.env.local')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)

class Config:
    # --- CHAVE SECRETA ---
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'd2a1b9c8e7f6a5b4c3d2e1f0a9b8c7d6e5f4a3b2c1d0'

    # --- BANCO DE DADOS ---
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")

    SQLALCHEMY_ECHO = False

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_size": 5,
        "max_overflow": 10,
        "pool_recycle": 1800,
        "connect_args": {"connect_timeout": 10},
    }

    # --- NOVAS CONFIGURAÇÕES DE SEGURANÇA PARA COOKIES ---
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PREFERRED_URL_SCHEME = "https"

    # --- LOCALIZAÇÃO ---
    BABEL_DEFAULT_LOCALE = 'pt_BR'

    # --- CONFIGURAÇÕES DE E-MAIL (Brevo) ---
    BREVO_API_KEY = os.environ.get('BREVO_API_KEY')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER')

    # --- INICIALIZAÇÃO DO APP ---
    @staticmethod
    def init_app(app):
        if not app.config.get("SQLALCHEMY_DATABASE_URI"):
            raise ValueError(
                "A variável de ambiente 'DATABASE_URL' não foi carregada. "
                "Verifique o arquivo .env e o arquivo de configuração WSGI."
            )
        if not app.config.get("SECRET_KEY") and not app.testing:
            raise ValueError(
                "No SECRET_KEY set for Flask application. "
                "Set the SECRET_KEY environment variable."
            )

        # --- CONFIGURAÇÃO DE LOGGING ---
        import logging
        from logging import StreamHandler

        # Configurar logging para mostrar erros no console/terminal
        if not app.logger.handlers:
            handler = StreamHandler()
            handler.setLevel(logging.INFO)
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            app.logger.addHandler(handler)
            app.logger.setLevel(logging.INFO)

        # Mostrar também erros de SQLAlchemy no console se estiver em desenvolvimento
        if app.debug:
            logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)
            logging.getLogger('sqlalchemy.pool').setLevel(logging.INFO)