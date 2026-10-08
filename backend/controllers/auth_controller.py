# backend/controllers/auth_controller.py

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, current_app, session, make_response, jsonify
)
from flask_login import login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm
from flask_wtf.csrf import CSRFError
from wtforms import StringField, PasswordField, SubmitField, BooleanField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Regexp
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from sqlalchemy import select
from datetime import datetime, timedelta

from ..services.totp_service import TotpService
from ..models.database import db
from ..models.user import User
from ..models.user_school import UserSchool
from ..models.aluno import Aluno
from ..models.instrutor import Instrutor
from ..models.turma import Turma
from ..services.email_service import EmailService

from utils.normalizer import normalize_matricula, normalize_name

auth_bp = Blueprint("auth", __name__, url_prefix="")

@auth_bp.app_errorhandler(CSRFError)
def handle_csrf_error(e):
    """Captura erros de token CSRF expirado ou ausente para evitar tela em branco."""
    current_app.logger.warning(f"Falha de CSRF detectada: {e.description}")
    flash("Sua sessão expirou por inatividade. Por favor, tente novamente.", "warning")
    return redirect(request.referrer or url_for('auth.login'))

# --- Forms (Mantidos) ---
class CSRFOnlyForm(FlaskForm): pass

class LoginForm(FlaskForm):
    username = StringField("Usuário", validators=[DataRequired()])
    password = PasswordField("Senha", validators=[DataRequired()])
    remember = BooleanField("Lembrar-me")
    submit = SubmitField("Entrar")

class RequestResetForm(FlaskForm):
    email = StringField("E-mail", validators=[DataRequired(), Email()])
    submit = SubmitField("Enviar link de redefinição")

class ResetPasswordForm(FlaskForm):
    password = PasswordField("Nova senha", validators=[DataRequired(), Length(min=8)])
    password2 = PasswordField("Confirme a senha", validators=[DataRequired(), EqualTo("password")])
    submit = SubmitField("Redefinir senha")

class Verify2FAForm(FlaskForm):
    token = StringField("Código de 6 dígitos", validators=[DataRequired(), Length(min=6, max=6), Regexp(r'^\d{6}$', message="O código deve conter apenas 6 números.")])
    submit = SubmitField("Verificar")

class Setup2FAForm(FlaskForm):
    token = StringField("Código do App (6 dígitos)", validators=[DataRequired(), Length(min=6, max=6), Regexp(r'^\d{6}$', message="O código deve conter apenas 6 números.")])
    submit = SubmitField("Ativar 2FA")

# --- Helpers ---
def _get_serializer(salt: str = "reset-password"):
    secret = current_app.config.get("SECRET_KEY") or "CHANGEME"
    return URLSafeTimedSerializer(secret_key=secret, salt=salt)

@auth_bp.before_app_request
def enforce_2fa_setup():
    """Força usuários logados que não têm 2FA a configurá-lo antes de acessar o sistema."""
    # Ignora a obrigatoriedade de 2FA em ambiente de desenvolvimento local
    if current_app.debug:
        return
        
    if current_user.is_authenticated and not getattr(current_user, 'is_totp_enabled', False):
        allowed_endpoints = ['auth.configurar_2fa', 'auth.logout', 'static']

        if request.endpoint and request.endpoint not in allowed_endpoints and not request.endpoint.startswith('static'):
            flash("A Autenticação em Duas Etapas (2FA) é obrigatória. Configure para liberar seu acesso ao sistema.", "warning")
            return redirect(url_for('auth.configurar_2fa'))

def _find_user_for_login(identifier):
    ident = (identifier or "").strip()
    if not ident: return None
    mat_norm = normalize_matricula(ident)
    if mat_norm:
        user = db.session.execute(select(User).where(User.matricula == mat_norm)).scalar_one_or_none()
        if user: return user
    if "@" in ident:
        user = db.session.execute(select(User).where(User.email == ident.lower())).scalar_one_or_none()
        if user: return user
    user = db.session.execute(select(User).where(User.username == ident)).scalar_one_or_none()
    return user

# --- Rotas ---

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        identifier = form.username.data.strip()
        password = form.password.data
        remember = bool(form.remember.data)

        user = _find_user_for_login(identifier)
        if not user or not user.check_password(password):
            flash("Credenciais inválidas.", "danger")
            return render_template("login.html", form=form)

        if not user.is_active:
            flash("Conta inativa.", "warning")
            return redirect(url_for("auth.register"))

        # INTERCEPTAÇÃO PARA 2FA
        if getattr(user, 'is_totp_enabled', False) and not current_app.debug:
            # VERIFICAÇÃO DE DISPOSITIVO CONFIÁVEL (30 DIAS)
            trust_token = request.cookies.get(f'trust_device_{user.id}')
            if trust_token and trust_token == user.totp_secret:
                login_user(user, remember=remember)
                session.pop('active_school_id', None)
                session.pop('is_dec_mode', None)
                session.permanent = True
                return redirect(url_for("main.selecionar_escola"))

            session['pending_2fa_user_id'] = user.id
            session['pending_2fa_remember'] = remember
            return redirect(url_for("auth.verificar_2fa"))

        # Login normal (sem 2FA)
        login_user(user, remember=remember)
        session.pop('active_school_id', None)
        session.pop('is_dec_mode', None)
        session.permanent = True
        return redirect(url_for("main.selecionar_escola"))

    return render_template("login.html", form=form)

@auth_bp.route("/verificar-2fa", methods=["GET", "POST"])
def verificar_2fa():
    user_id = session.get('pending_2fa_user_id')
    if not user_id:
        return redirect(url_for("auth.login"))

    user = db.session.get(User, user_id)
    if not user:
        session.pop('pending_2fa_user_id', None)
        return redirect(url_for("auth.login"))

    form = Verify2FAForm()
    reset_form = CSRFOnlyForm()

    if form.validate_on_submit():
        if TotpService.verify_token(user.totp_secret, form.token.data):
            remember = session.get('pending_2fa_remember', False)
            trust_device = request.form.get('trust_device') # Captura o checkbox do HTML

            # Limpa a sessão pendente ANTES de logar
            session.pop('pending_2fa_user_id', None)
            session.pop('pending_2fa_remember', None)

            login_user(user, remember=remember)
            session.pop('active_school_id', None)
            session.pop('is_dec_mode', None)
            session.permanent = True

            flash("Autenticação realizada com sucesso.", "success")

            response = make_response(redirect(url_for("main.selecionar_escola")))

            # IMPLEMENTAÇÃO DO BOTÃO DE RECONHECER DISPOSITIVO (30 DIAS)
            if trust_device:
                expires = datetime.now() + timedelta(days=30)
                # O cookie armazena o totp_secret (ou um hash dele) para validar este navegador específico
                response.set_cookie(
                    f'trust_device_{user.id}',
                    user.totp_secret,
                    expires=expires,
                    httponly=True,
                    secure=True,
                    samesite='Lax'
                )

            return response
        else:
            flash("Código de autenticação inválido. Tente novamente.", "danger")

    return render_template("auth/verify_2fa.html", form=form, reset_form=reset_form)

@auth_bp.route("/configurar-2fa", methods=["GET", "POST"])
@login_required
def configurar_2fa():
    form = Setup2FAForm()

    if current_user.is_totp_enabled:
        flash("A Autenticação em Duas Etapas já está ativada na sua conta.", "info")
        return redirect(url_for("main.dashboard"))

    if 'setup_2fa_secret' not in session:
        session['setup_2fa_secret'] = TotpService.generate_secret()

    secret = session['setup_2fa_secret']
    identificador = current_user.email if current_user.email else current_user.matricula
    uri = TotpService.get_provisioning_uri(secret, identificador, issuer_name="ESFASBM")

    if form.validate_on_submit():
        if TotpService.verify_token(secret, form.token.data):
            current_user.totp_secret = secret
            current_user.is_totp_enabled = True
            db.session.commit()
            session.pop('setup_2fa_secret', None)
            flash("Autenticação em Duas Etapas (2FA) ativada com sucesso! Faça login novamente para confirmar.", "success")
            return redirect(url_for("auth.logout"))
        else:
            flash("Código inválido. Certifique-se de escanear o QR Code corretamente e tente de novo.", "danger")

    return render_template("auth/setup_2fa.html", form=form, secret=secret, uri=uri)

@auth_bp.route("/solicitar-reset-2fa", methods=["POST"])
def solicitar_reset_2fa():
    user_id = session.get('pending_2fa_user_id')
    if not user_id:
        flash("Sessão expirada. Faça login novamente.", "warning")
        return redirect(url_for("auth.login"))

    user = db.session.get(User, user_id)
    if not user:
        return redirect(url_for("auth.login"))

    if not user.email:
        flash("Sua conta não possui e-mail cadastrado. Procure a secretaria para recuperar seu acesso.", "danger")
        return redirect(url_for("auth.verificar_2fa"))

    s = _get_serializer("reset-2fa")
    token = s.dumps({"user_id": user.id, "action": "reset_2fa"})

    try:
        if hasattr(EmailService, 'send_2fa_reset_email'):
            EmailService.send_2fa_reset_email(user, token)
            flash(f"Instruções de recuperação enviadas para o e-mail ({user.email[:3]}***).", "success")
        else:
            reset_url = url_for('auth.resetar_2fa_token', token=token, _external=True)  # nosemgrep
            current_app.logger.warning(f"Link de Recuperação 2FA gerado: {reset_url}")
            flash("Link de recuperação gerado no console do servidor (EmailService não configurado para 2FA).", "info")
    except Exception as e:
        current_app.logger.error(f"Erro ao enviar email de reset 2FA: {e}")
        flash("Erro ao tentar enviar o e-mail de recuperação.", "danger")

    return redirect(url_for("auth.login"))

@auth_bp.route("/resetar-2fa/<token>")
def resetar_2fa_token(token):
    s = _get_serializer("reset-2fa")
    try:
        data = s.loads(token, max_age=3600)
        if data.get("action") != "reset_2fa":
            raise BadSignature()
        user_id = data.get("user_id")
    except (SignatureExpired, BadSignature):
        flash("O link de recuperação é inválido ou expirou.", "danger")
        return redirect(url_for("auth.login"))

    user = db.session.get(User, user_id)
    if user:
        user.totp_secret = None
        user.is_totp_enabled = False
        db.session.commit()

        # Opcional: Limpar cookies de confiança ao resetar 2FA
        response = make_response(redirect(url_for("auth.login")))
        response.delete_cookie(f'trust_device_{user.id}')

        flash("Sua Autenticação em Duas Etapas foi desativada. Faça login e configure um novo aparelho.", "success")
        return response

    return redirect(url_for("auth.login"))

@auth_bp.route("/logout")
@login_required
def logout():
    session.clear()
    logout_user()
    flash("Você saiu do sistema.", "info")
    return redirect(url_for("auth.login"))

# --- NOVA ROTA DE API PARA O JAVASCRIPT ---
@auth_bp.route("/api/turmas/<matricula>")
def api_turmas(matricula):
    mat_norm = normalize_matricula(matricula)
    if not mat_norm:
        return jsonify([])

    user = db.session.execute(select(User).where(User.matricula == mat_norm)).scalar_one_or_none()
    if not user:
        return jsonify({"role": "desconhecido", "turmas": []})

    vinculo = db.session.execute(select(UserSchool).where(UserSchool.user_id == user.id)).scalars().first()
    if not vinculo:
        return jsonify({"role": user.role, "turmas": []})

    turmas = db.session.execute(select(Turma).where(Turma.school_id == vinculo.school_id).order_by(Turma.nome)).scalars().all()
    
    # Check if user has a global role, or use school role
    # Since auth controller register doesn't have school context yet, we use global user role or vinculo role
    effective_role = vinculo.role if vinculo.role else user.role
    
    return jsonify({
        "role": effective_role,
        "turmas": [{"id": t.id, "nome": t.nome} for t in turmas]
    })
# ------------------------------------------

@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    # Inicialmente vazio para não carregar turmas de todas as escolas
    turmas = []
    form_data = request.form.to_dict()

    if request.method == "POST":
        pwd = form_data.get("password", "")
        pwd2 = form_data.get("password2", "")
        matricula_norm = normalize_matricula(form_data.get("matricula"))

        # Recupera as turmas da escola do usuário em caso de recarregamento da página (erros de validação)
        if matricula_norm:
            temp_user = db.session.execute(select(User).where(User.matricula == matricula_norm)).scalar_one_or_none()
            if temp_user:
                vinculo = db.session.execute(select(UserSchool).where(UserSchool.user_id == temp_user.id)).scalars().first()
                if vinculo:
                    turmas = db.session.scalars(select(Turma).where(Turma.school_id == vinculo.school_id).order_by(Turma.nome)).all()

        if not pwd or pwd != pwd2 or len(pwd) < 8:
            flash("Senha inválida.", "danger")
            return render_template("register.html", form_data=form_data, turmas=turmas)

        if not matricula_norm:
            flash("Matrícula inválida.", "danger")
            return render_template("register.html", form_data=form_data, turmas=turmas)

        user = db.session.execute(select(User).where(User.matricula == matricula_norm)).scalar_one_or_none()
        if not user:
            flash("Matrícula não encontrada.", "danger")
            return render_template("register.html", form_data=form_data, turmas=turmas)

        vinculos = db.session.scalars(select(UserSchool).where(UserSchool.user_id == user.id)).all()
        if not vinculos:
            flash("Sem vínculo escolar.", "danger")
            return render_template("register.html", form_data=form_data, turmas=turmas)

        primeira_escola_id = vinculos[0].school_id

        # SEGURANÇA: Fixar a permissão (role) original para evitar Escalonamento de Privilégio
        role = user.role
        
        user.nome_completo = normalize_name(form_data.get("nome_completo"))
        user.nome_de_guerra = normalize_name(form_data.get("nome_de_guerra"))
        user.posto_graduacao = form_data.get("posto_graduacao") or None
        user.email = (form_data.get("email") or "").strip().lower() or None
        user.set_password(pwd)
        user.is_active = True
        user.must_change_password = False

        if role == "aluno":
            opm_value = form_data.get("opm", "Não informado")
            turma_id_value = form_data.get('turma_id')
            turma_id = int(turma_id_value) if turma_id_value else None

            if not user.aluno_profile:
                perfil = Aluno(user_id=user.id, opm=opm_value, turma_id=turma_id)
                db.session.add(perfil)
            else:
                user.aluno_profile.opm = opm_value
                user.aluno_profile.turma_id = turma_id

        if role == "instrutor":
            if not user.instrutor_profile:
                db.session.add(Instrutor(user_id=user.id, school_id=primeira_escola_id))

        try:
            db.session.commit()
            
            # AUDITORIA: Gravar o log de segurança da ativação
            try:
                from ..services.log_service import LogService
                LogService.log_action(
                    user_id=user.id,
                    school_id=primeira_escola_id,
                    action="CONTA_ATIVADA",
                    details=f"O usuário {user.matricula} finalizou seu cadastro inicial com o perfil de {role.upper()}."
                )
            except Exception as e:
                current_app.logger.error(f"Erro ao registrar log de segurança de ativação: {e}")

            flash("Conta ativada!", "success")
            return redirect(url_for("auth.login"))
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Erro ativar")
            flash("Erro ao ativar conta.", "danger")
            return render_template("register.html", form_data=form_data, turmas=turmas)

    return render_template("register.html", form_data={}, turmas=turmas)

@auth_bp.route("/recuperar-senha", methods=["GET", "POST"])
def recuperar_senha():
    form = RequestResetForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        user = db.session.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if not user:
            flash("Se o e-mail existir, você receberá instruções.", "info")
            return redirect(url_for("auth.recuperar_senha"))

        s = _get_serializer()
        token = s.dumps({"user_id": user.id})
        EmailService.send_password_reset_email(user, token)
        flash("Se o e-mail existir, você receberá instruções.", "info")
        return redirect(url_for("auth.login"))
    return render_template("recuperar_senha.html", form=form)

@auth_bp.route("/redefinir-senha/<token>", methods=["GET", "POST"])
def redefinir_senha(token):
    form = ResetPasswordForm()
    s = _get_serializer()
    user_id = None
    try:
        data = s.loads(token, max_age=3600)
        user_id = data.get("user_id")
    except (SignatureExpired, BadSignature):
        flash("Token inválido.", "warning")
        return redirect(url_for("auth.recuperar_senha"))

    user = db.session.get(User, user_id)
    if not user:
        flash("Usuário não encontrado.", "danger")
        return redirect(url_for("auth.recuperar_senha"))

    if form.validate_on_submit():
        try:
            user.set_password(form.password.data)
            user.must_change_password = False
            user.totp_secret = None
            user.is_totp_enabled = False
            db.session.commit()
            flash("Senha redefinida e segurança (2FA) resetada com sucesso.", "success")
            return redirect(url_for("auth.login"))
        except Exception:
            db.session.rollback()
            flash("Erro ao redefinir.", "danger")

    return render_template("redefinir_senha.html", form=form, token=token)

@auth_bp.route("/ativar-modo-dec", methods=["GET", "POST"])
@login_required
def ativar_modo_dec():
    if current_user.role != 'super_admin':
        flash("Acesso negado. Você não possui privilégios de gestão DEC.", "danger")
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        password = request.form.get("password")
        if current_user.check_password(password):
            session['is_dec_mode'] = True
            session.pop('active_school_id', None)
            session.pop('view_as_school_id', None)
            session.pop('view_as_school_name', None)
            flash("Modo de Gestão DEC ativado com segurança.", "success")
            return redirect(url_for("super_admin.dashboard"))
        else:
            flash("Senha incorreta. Acesso de gestão negado.", "danger")

    return render_template("ativar_dec.html")

@auth_bp.route("/desativar-modo-dec")
@login_required
def desativar_modo_dec():
    session.pop('is_dec_mode', None)
    session.pop('view_as_school_id', None)
    session.pop('view_as_school_name', None)
    flash("Modo DEC desativado. Você retornou à visão padrão.", "info")
    return redirect(url_for("main.dashboard"))