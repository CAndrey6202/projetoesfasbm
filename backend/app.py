# backend/app.py

import os
import sys
from unittest.mock import MagicMock

# Adicionar o diretório raiz ao path para imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# --- HACK PARA RODAR LOCAL NO WINDOWS SEM O WEASYPRINT ---
if os.environ.get('FLASK_ENV') == 'development' or os.name == 'nt':
    sys.modules['weasyprint'] = MagicMock()
# ---------------------------------------------------------

import click
import firebase_admin
from flask import Flask, render_template, g, session, send_from_directory
from flask_login import LoginManager, current_user
from flask_migrate import Migrate
from flask_babel import Babel
from firebase_admin import credentials

from backend.config import Config
from backend.extensions import limiter, csrf
from backend.models.database import db
from backend.models.user import User
from backend.services.asset_service import AssetService

# --- Importações de TODOS os modelos para o Flask-Migrate ---
from backend.models.aluno import Aluno
# from backend.models.avaliacao import AvaliacaoAtitudinal, AvaliacaoItem
from backend.models.disciplina import Disciplina
from backend.models.disciplina_turma import DisciplinaTurma
from backend.models.discipline_rule import DisciplineRule
from backend.models.historico import HistoricoAluno
from backend.models.historico_disciplina import HistoricoDisciplina
from backend.models.horario import Horario
from backend.models.image_asset import ImageAsset
from backend.models.instrutor import Instrutor
from backend.models.notification import Notification
from backend.models.opcao_resposta import OpcaoResposta
from backend.models.password_reset_token import PasswordResetToken
from backend.models.pergunta import Pergunta
from backend.models.processo_disciplina import ProcessoDisciplina
from backend.models.push_subscription import PushSubscription
from backend.models.questionario import Questionario
from backend.models.resposta import Resposta
from backend.models.school import School
from backend.models.semana import Semana
from backend.models.site_config import SiteConfig
from backend.models.turma import Turma
from backend.models.turma_cargo import TurmaCargo
from backend.models.user_school import UserSchool
from backend.models.fada_avaliacao import FadaAvaliacao
from backend.models.diario_classe import DiarioClasse
from backend.models.frequencia import FrequenciaAluno
# ### NOVO MODELO ###
from backend.models.elogio import Elogio
from backend.models.edicao import Edicao
from backend.models.chamado_suporte import ChamadoSuporte
# --- NOVO MÓDULO: DESLIGAMENTOS ---
from backend.models.desligamento import RegistroDesligamento
# --- NOVO MÓDULO: BANCO DE QUESTÕES E PROVAS ---
from backend.models.banco_questoes import QuestaoBanco, DelegacaoProva, RascunhoProva, ConfiguracaoEnvio
# --- NOVO MÓDULO: RECURSOS ---
from backend.models.recurso import ProvaRecurso, Recurso, DisciplinaHabilitada
from backend.models.background_job import BackgroundJob
# ------------------------------------------------------------
from datetime import datetime, timezone, timedelta
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

def create_app(config_class=Config):
    """
    Fábrica de aplicação: cria e configura a instância do Flask.
    """
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    template_dir = os.path.join(project_root, 'templates')
    static_dir = os.path.join(project_root, 'static')

    app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
    app.config.from_object(config_class)

    config_class.init_app(app)

    # --- INICIALIZAÇÃO DO FIREBASE ---
    try:
        cred_path = os.path.join(os.path.dirname(__file__), 'credentials.json')
        if os.path.exists(cred_path):
            if not firebase_admin._apps:
                cred = credentials.Certificate(cred_path)
                firebase_admin.initialize_app(cred)
                app.logger.info("Firebase Admin SDK inicializado com sucesso.")
        else:
                 app.logger.warning(f"Arquivo 'credentials.json' não encontrado em {cred_path}. Funcionalidades do Firebase não estarão disponíveis.")
    except ValueError:
       pass # App já inicializado
    except Exception as e:
        app.logger.error(f"ERRO ao inicializar o Firebase Admin SDK: {e}")
    # --- FIM DA INICIALIZAÇÃO ---

    # ### FILTRO DE FUSO HORÁRIO ###
    @app.template_filter('br_time')
    def format_datetime_as_brt(dt_utc, format_str=None):
        if not dt_utc:
            return "N/A"
        try:
            BRT = ZoneInfo("America/Sao_Paulo")
            if dt_utc.tzinfo is None:
                dt_utc = dt_utc.replace(tzinfo=timezone.utc)
            dt_brt = dt_utc.astimezone(BRT)
            if format_str:
                return dt_brt.strftime(format_str)
            else:
                return dt_brt.strftime("%d/%m/%Y às %H:%M")
        except Exception as e:
            return str(dt_utc)
    # ### FIM DO FILTRO ###

    # ### PWA ###
    @app.route('/sw.js')
    def service_worker():
        return send_from_directory(app.static_folder, 'sw.js', mimetype='application/javascript')

    @app.route('/manifest.json')
    def manifest():
        return send_from_directory(app.static_folder, 'manifest.json', mimetype='application/json')
    # ### FIM PWA ###

    db.init_app(app)
    Migrate(app, db)
    csrf.init_app(app)
    limiter.init_app(app) # <-- CORRIGIDO AQUI (era limter)
    Babel(app)

    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        from sqlalchemy.orm import selectinload
        return db.session.query(User).options(
            selectinload(User.user_schools),
            selectinload(User.alunos_profiles),
            selectinload(User.instrutor_profile)
        ).get(int(user_id))

    # =========================================================
    # CORREÇÃO CRÍTICA DE PERMISSÕES POR ESCOLA (Context Inject)
    # =========================================================
    @app.before_request
    def set_user_context():
        if current_user.is_authenticated:
            if current_user.role == 'super_admin':
                view_as = session.get('view_as_school_id')
                if view_as:
                    current_user.temp_active_school_id = int(view_as)
                    return

            sid = session.get('active_school_id')
            if sid:
                current_user.temp_active_school_id = int(sid)
    # =========================================================

    # ALTERAÇÃO: Injetando timedelta globalmente para uso nos templates
    app.jinja_env.globals.update(timedelta=timedelta)

    with app.app_context():
        AssetService.initialize_upload_folder(app)
        register_blueprints(app)
        register_handlers_and_processors(app)

    register_cli_commands(app)
    return app

def register_blueprints(app):
    """Importa e registra os blueprints na aplicação."""
    from backend.controllers.admin_controller import admin_escola_bp
    from backend.controllers.admin_tools_controller import tools_bp
    from backend.controllers.aluno_controller import aluno_bp
    from backend.controllers.assets_controller import assets_bp
    from backend.controllers.auth_controller import auth_bp
    #from backend.controllers.avaliacao_controller import avaliacao_bp
    from backend.controllers.customizer_controller import customizer_bp
    from backend.controllers.disciplina_controller import disciplina_bp
    from backend.controllers.historico_controller import historico_bp
    from backend.controllers.horario_controller import horario_bp
    from backend.controllers.instrutor_controller import instrutor_bp
    from backend.controllers.justica_controller import justica_bp
    from backend.controllers.main_controller import main_bp
    from backend.controllers.notification_controller import notification_bp
    from backend.controllers.push_controller import push_bp
    from backend.controllers.questionario_controller import questionario_bp
    from backend.controllers.relatorios_controller import relatorios_bp
    from backend.controllers.semana_controller import semana_bp
    from backend.controllers.super_admin_controller import super_admin_bp
    from backend.controllers.jobs_controller import jobs_bp
    from backend.controllers.turma_controller import turma_bp
    from backend.controllers.user_controller import user_bp
    from backend.controllers.vinculo_controller import vinculo_bp
    from backend.controllers.chefe_turma_controller import chefe_bp
    from backend.controllers.suporte_controller import suporte_bp

    # ### NOVOS CONTROLLERS ###
    from backend.controllers.elogio_controller import elogio_bp
    from backend.controllers.regras_controller import regras_bp
    from backend.controllers.diario_controller import diario_bp
    from backend.controllers.questoes_controller import questoes_bp
    from backend.controllers.recursos_controller import recursos_bp
    from backend.controllers.edicao_controller import edicao_bp
    from backend.controllers.log_controller import log_bp
    from backend.controllers.cursos_controller import cursos_api_bp, cursos_bp
    from backend.controllers.desligamento_controller import desligamento_bp # <-- IMPORTAÇÃO AQUI

    app.register_blueprint(admin_escola_bp)
    app.register_blueprint(tools_bp)
    app.register_blueprint(aluno_bp)
    app.register_blueprint(assets_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(customizer_bp)
    app.register_blueprint(disciplina_bp)
    app.register_blueprint(historico_bp)
    app.register_blueprint(horario_bp)
    app.register_blueprint(instrutor_bp)
    app.register_blueprint(justica_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(notification_bp)
    app.register_blueprint(push_bp)
    app.register_blueprint(questionario_bp)
    app.register_blueprint(relatorios_bp)
    app.register_blueprint(semana_bp)
    app.register_blueprint(super_admin_bp)
    app.register_blueprint(jobs_bp)
    app.register_blueprint(turma_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(vinculo_bp)
    app.register_blueprint(chefe_bp)
    app.register_blueprint(suporte_bp)
    app.register_blueprint(desligamento_bp) # <-- REGISTRO AQUI

    # ### REGISTRO DE NOVOS BLUEPRINTS ###
    app.register_blueprint(elogio_bp)
    app.register_blueprint(regras_bp)
    app.register_blueprint(diario_bp)
    app.register_blueprint(questoes_bp)
    app.register_blueprint(recursos_bp)
    app.register_blueprint(edicao_bp)
    app.register_blueprint(log_bp)
    app.register_blueprint(cursos_api_bp)
    app.register_blueprint(cursos_bp)

def register_handlers_and_processors(app):

    @app.before_request
    def load_globals():
        from flask import request
        
        # --- FILTRO DE DESEMPENHO EM PRODUÇÃO ---
        # Evita consultas pesadas ao banco de dados para assets visuais e PWA
        if request.path.startswith('/static/') or request.path in ['/sw.js', '/manifest.json', '/favicon.ico']:
            return
        # -----------------------------------------

        from backend.services.site_config_service import SiteConfigService

        if 'site_config' not in g:
            if app.config.get("TESTING", False):
                SiteConfigService.init_default_configs()

            configs = SiteConfigService.get_all_configs()
            g.site_config = {c.config_key: c.config_value for c in configs}

        g.active_school = None
        g.active_edicao = None
        school_id_to_load = None

        if current_user.is_authenticated:
            if current_user.role == 'super_admin':
                school_id_to_load = session.get('view_as_school_id')

            if school_id_to_load is None:
                 school_id_to_load = session.get('active_school_id')

            if school_id_to_load is None and hasattr(current_user, 'user_schools') and current_user.user_schools:
                school_id_to_load = current_user.user_schools[0].school_id

            if school_id_to_load is None and str(current_user.role).lower() == 'aluno':
                if current_user.aluno_profile and current_user.aluno_profile.turma:
                    school_id_to_load = current_user.aluno_profile.turma.school_id

            if school_id_to_load:
                g.active_school = db.session.get(School, int(school_id_to_load))

            # Carregar Edição Ativa da sessão
            edicao_id = session.get('active_edicao_id')
            
            if not edicao_id and str(current_user.role).lower() == 'aluno' and current_user.aluno_profile:
                edicao_id = current_user.aluno_profile.edicao_id
                if edicao_id:
                    session['active_edicao_id'] = edicao_id
                    
            if edicao_id:
                from backend.models.edicao import Edicao
                edicao = db.session.get(Edicao, int(edicao_id))
                # Valida que a edição belongs à escola ativa
                if edicao and g.active_school and edicao.school_id == g.active_school.id:
                    g.active_edicao = edicao
                else:
                    session.pop('active_edicao_id', None)
                    
            # Se ainda não tem edição ativa, seleciona a mais recente automaticamente
            if not g.active_edicao and g.active_school:
                from backend.models.edicao import Edicao
                latest_edicao = Edicao.query.filter_by(school_id=g.active_school.id).order_by(Edicao.id.desc()).first()
                if latest_edicao:
                    g.active_edicao = latest_edicao
                    session['active_edicao_id'] = latest_edicao.id

    @app.context_processor
    def inject_globals_to_template():
        # Listar edições da escola ativa para o dropdown da navbar
        edicoes_disponiveis = []
        if g.get('active_school'):
            from backend.models.edicao import Edicao
            edicoes_disponiveis = Edicao.query.filter_by(school_id=g.active_school.id).order_by(Edicao.id.desc()).all()

        dec_mode_active = session.get('is_dec_mode', False) and current_user.is_authenticated and current_user.role == 'super_admin'

        # --- VERIFICAÇÃO DE PENDÊNCIAS DE SUPORTE ---
        tem_pendencia_suporte = False
        if current_user.is_authenticated and (current_user.role == 'super_admin' or getattr(current_user, 'is_dec_manager', False)):
            try:
                from backend.models.chamado_suporte import ChamadoSuporte
                # Verifica status que indicam pendência (Aberto, Pendente, Novo)
                tem_pendencia_suporte = ChamadoSuporte.query.filter(ChamadoSuporte.status.in_(['Aberto', 'Pendente', 'Novo'])).count() > 0
            except Exception as e:
                app.logger.error(f"Erro ao consultar chamados de suporte: {e}")
        # ---------------------------------------------

        # --- VERIFICACAO DE BLOQUEIO POR AVALIACAO OBRIGATORIA ---
        bloqueio_avaliacao = False
        campanha_pendente_id = None
        
        if current_user.is_authenticated:
            local_role = current_user.get_role_in_school(school_id_to_load) if school_id_to_load else None
            if str(getattr(current_user, 'role', '')).lower().strip() == 'aluno' or local_role == 'aluno':
                try:
                    from backend.services.aluno_service import AlunoService
                    bloqueio_avaliacao, campanha_pendente_id = AlunoService.check_pending_mandatory_evaluations(current_user)
                except Exception as e:
                    app.logger.error(f'Erro ao checar avaliacoes pendentes: {e}')
        # ---------------------------------------------

        return {
            'site_config': g.get('site_config'),
            'active_school': g.get('active_school'),
            'active_edicao': g.get('active_edicao'),
            'edicoes_disponiveis': edicoes_disponiveis,
            'dec_mode_active': dec_mode_active,
            'tem_pendencia_suporte': tem_pendencia_suporte,
            'bloqueio_avaliacao': bloqueio_avaliacao,
            'campanha_pendente_id': campanha_pendente_id
        }

    @app.after_request
    def add_header(response):
        # Controle de Cache (Evita que páginas sensíveis fiquem gravadas no navegador)
        from flask import request
        if request.path.startswith('/static/') or request.path in ['/sw.js', '/manifest.json', '/favicon.ico']:
            response.headers["Cache-Control"] = "public, max-age=31536000" # 1 ano de cache
        else:
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"

        # Prevenção contra ataques MIME Sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Prevenção contra Clickjacking (Bandeira Laranja do ZAP corrigida)
        response.headers["X-Frame-Options"] = "DENY"

        # Controle de vazamento de URLs no Referer
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Bloqueio de APIs sensíveis do navegador (Permissão)
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"

        # Content-Security-Policy Rigoroso (7 Bandeiras Laranjas do ZAP corrigidas de uma vez)
        csp = [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' https://code.jquery.com https://cdn.jsdelivr.net https://www.googletagmanager.com",
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com https://cdnjs.cloudflare.com",
            "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com",
            "img-src 'self' data: *",
            "connect-src 'self' https://cdn.jsdelivr.net https://www.google-analytics.com https://analytics.google.com https://region1.google-analytics.com https://stats.g.doubleclick.net",
            "media-src 'self' https://cadtech.com.br https://*.cadtech.com.br https://commondatastorage.googleapis.com data: blob:",
            "frame-src 'self' https://www.youtube.com https://*.youtube.com https://*.live.com https://*.live.net https://*.sharepoint.com",
            "object-src 'none'",
            "frame-ancestors 'none'",
            "manifest-src 'self'",
            "worker-src 'self'"
        ]
        response.headers["Content-Security-Policy"] = "; ".join(csp)

        # Remove informações que revelam a versão do servidor
        response.headers.pop("Server", None)
        response.headers.pop("X-Powered-By", None)

        return response

    @app.errorhandler(404)
    def not_found_error(error):
        return render_template('404.html'), 404

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        return render_template('500.html'), 500

def register_cli_commands(app):
    @app.cli.command("create-super-admin")
    def create_super_admin():
        with app.app_context():
            super_admin_password = os.environ.get('SUPER_ADMIN_PASSWORD')
            if not super_admin_password:
                print("A variável de ambiente SUPER_ADMIN_PASSWORD não está definida.")
                return
            user = db.session.execute(db.select(User).filter_by(username='super_admin')).scalar_one_or_none()
            if user:
                print("Usuário 'super_admin' já existe. Atualizando senha e ativando...")
                user.is_active = True
                user.set_password(super_admin_password)
            else:
                print("Criando o usuário super administrador 'super_admin'...")
                user = User(
                    matricula='SUPER_ADMIN',
                    username='super_admin',
                    email='super_admin@escola.com.br',
                    role='super_admin',
                    is_active=True
                )
                user.set_password(super_admin_password)
                db.session.add(user)
            db.session.commit()
            print("Comando executado com sucesso!")

    @app.cli.command("clear-data")
    @click.option('--app', is_flag=True, help='Limpa apenas os dados da aplicação (alunos, turmas, etc).')
    def clear_data_command(app_flag):
        from scripts.clear_data import clear_transactional_data
        if not app_flag:
                if input("ATENÇÃO: Este comando irá apagar TODOS os dados de alunos, turmas, etc. Deseja continuar? (s/n): ").lower() != 's':
                    print("Operação cancelada.")
                    return
        with create_app().app_context():
            clear_transactional_data()

    @app.cli.command("seed-questionario")
    def seed_questionario_command():
        from scripts.seed_questionario import popular_questionario_db
        with create_app().app_context():
            popular_questionario_db()
        print("Comando de popular questionário executado.")

    @app.cli.command("seed-npccal")
    def seed_npccal_command():
        """Popula o banco de dados com as regras de disciplina (NPCCAL)."""
        from scripts.seed_npccal import seed_rules
        with app.app_context():
            seed_rules()

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)
