from __future__ import annotations

import os
import re
import secrets
from datetime import datetime
from typing import Optional
import json

from flask import (
    Blueprint, current_app, flash, redirect, render_template,
    request, url_for, jsonify, abort
)
from flask_login import current_user, login_required
from sqlalchemy import text, select, case, or_
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, SelectField, RadioField
from wtforms.validators import DataRequired, Email, EqualTo, Optional as WTFormsOptional, ValidationError
from flask_wtf.file import FileField, FileAllowed

from backend.models.database import db
from backend.services.aluno_service import AlunoService
from backend.services.instrutor_service import InstrutorService
from backend.models.user import User
from backend.models.turma import Turma
from backend.models.school import School
from backend.models.user_school import UserSchool
from backend.services.user_service import UserService
from backend.services.log_service import LogService # <--- ESPIÃO IMPORTADO AQUI
from utils.decorators import super_admin_required, admin_required

user_bp = Blueprint("user", __name__, url_prefix="/user")

posto_graduacao_structured = {
    'Praças': ['Soldado PM', '3º Sargento PM EXT', '2º Sargento PM', '1º Sargento PM', 'Aluno Oficial'],
    'Oficiais': ['1º Tenente PM', 'Capitão PM', 'Major PM', 'Tenente-Coronel PM', 'Coronel PM'],
    'Saúde - Enfermagem': ['Ten Enf', 'Cap Enf', 'Maj Enf', 'Ten Cel Enf', 'Cel Enf'],
    'Saúde - Médicos': ['Ten Med', 'Cap Med', 'Maj Med', 'Ten Cel Med', 'Cel Med'],
    'PME / RR': [
        'Soldado RR', '3º Sargento RR', '2º Sargento RR', '1º Sargento RR', '1º Tenente RR', 'Capitão RR', 'Major RR', 'Tenente-Coronel RR', 'Coronel RR',
        'Soldado PME', '3º Sargento PME', '2º Sargento PME', '1º Sargento PME', '1º Tenente PME', 'Capitão PME', 'Major PME', 'Tenente-Coronel PME', 'Coronel PME'
    ],
    'Outros': ['Civil', 'Outro']
}

class MeuPerfilForm(FlaskForm):
    nome_completo = StringField('Nome Completo', validators=[DataRequired()])
    email = StringField('E-mail', validators=[DataRequired(), Email()])
    posto_categoria = SelectField("Categoria", choices=list(posto_graduacao_structured.keys()), validators=[DataRequired()])
    posto_graduacao = SelectField('Posto/Graduação', choices=[], validators=[DataRequired()])
    turma_id = SelectField('Turma', coerce=int, validators=[WTFormsOptional()])
    is_rr = RadioField("Efetivo da Reserva Remunerada (RR/PME)", choices=[('True', 'Sim'), ('False', 'Não')], coerce=lambda x: x == 'True', default=False)

    # Aceita arquivos, sem limite manual de tamanho aqui (o Service vai comprimir)
    foto_perfil = FileField('Alterar Foto de Perfil', validators=[
        FileAllowed(['jpg', 'jpeg', 'png', 'gif', 'webp'], 'Apenas imagens!')
    ])

    current_password = PasswordField('Senha Atual', validators=[WTFormsOptional()])
    new_password = PasswordField('Nova Senha', validators=[WTFormsOptional(), EqualTo('confirm_new_password', message='As senhas não correspondem.')])
    confirm_new_password = PasswordField('Confirmar Nova Senha', validators=[WTFormsOptional()])
    submit = SubmitField('Salvar Alterações')

def norm_email(v: Optional[str]) -> Optional[str]:
    return v.strip().lower() if v else None

def norm_idfunc(v: Optional[str]) -> Optional[str]:
    if not v: return None
    return re.sub(r"\D+", "", v.strip()) or None

def set_password_hash_on_user(user_obj, plain: str):
    if hasattr(user_obj, "set_password") and callable(getattr(user_obj, "set_password")):
        user_obj.set_password(plain)
    else:
        user_obj.password_hash = generate_password_hash(plain)

def exists_in_users_by(column: str, value: str) -> bool:
    return db.session.scalar(select(User).where(getattr(User, column) == value, User.id != current_user.id)) is not None

def generate_unique_username(base: str, max_tries: int = 50) -> str:
    base = re.sub(r"[^a-z0-9._-]+", "-", base.lower())
    candidate = base or "user"
    if not exists_in_users_by("username", candidate): return candidate
    for i in range(1, max_tries + 1):
        candidate = f"{base}-{i}"
        if not exists_in_users_by("username", candidate): return candidate
    suffix = secrets.token_hex(2)
    candidate = f"{base}-{suffix}"
    return candidate

@user_bp.route("/meu-perfil", methods=["GET", "POST"])
@login_required
def meu_perfil():
    form = MeuPerfilForm(obj=current_user)
    form.turma_id.choices = []
    form.posto_categoria.choices = [(k, k) for k in posto_graduacao_structured.keys()]

    if request.method == 'GET':
        posto_atual = current_user.posto_graduacao
        categoria_encontrada = 'Outros'
        for categoria, postos in posto_graduacao_structured.items():
            if posto_atual in postos:
                categoria_encontrada = categoria
                break
        form.posto_categoria.data = categoria_encontrada

    categoria_selecionada = form.posto_categoria.data or 'Praças'
    form.posto_graduacao.choices = [(p, p) for p in posto_graduacao_structured.get(categoria_selecionada, [])]
    if request.method == 'GET':
        form.posto_graduacao.data = current_user.posto_graduacao

    # CORREÇÃO: Liberar visualização baseada na existência do perfil, não da ROLE.
    if hasattr(current_user, 'aluno_profile') and current_user.aluno_profile:
        school_id = current_user.aluno_profile.turma.school_id if current_user.aluno_profile.turma else None
        if school_id:
            turmas = db.session.scalars(select(Turma).filter_by(school_id=school_id).order_by(Turma.nome)).all()
            form.turma_id.choices = [(t.id, t.nome) for t in turmas]
            if request.method == 'GET':
                 form.turma_id.data = current_user.aluno_profile.turma_id

    elif hasattr(current_user, 'instrutor_profile') and current_user.instrutor_profile:
        if request.method == 'GET':
            form.is_rr.data = current_user.instrutor_profile.is_rr

    if form.validate_on_submit():
        try:
            current_user.nome_completo = form.nome_completo.data
            current_user.posto_graduacao = form.posto_graduacao.data
            nome_de_guerra = request.form.get('nome_de_guerra')
            if nome_de_guerra: current_user.nome_de_guerra = nome_de_guerra

            if form.email.data != current_user.email and exists_in_users_by("email", form.email.data):
                flash("Este e-mail já está em uso por outro usuário.", "warning")
            else:
                current_user.email = form.email.data

            if form.new_password.data:
                if not current_user.check_password(form.current_password.data):
                    flash("A senha atual está incorreta.", "danger")
                else:
                    set_password_hash_on_user(current_user, form.new_password.data)
                    current_user.must_change_password = False
                    flash("Senha alterada com sucesso.", "success")

            # CORREÇÃO: Liberar salvamento da foto baseada na existência do perfil
            if hasattr(current_user, 'aluno_profile') and current_user.aluno_profile:
                current_user.aluno_profile.turma_id = form.turma_id.data
                if form.foto_perfil.data:
                    success, message = AlunoService.update_profile_picture(current_user.aluno_profile.id, form.foto_perfil.data)
                    flash(message, 'success' if success else 'danger')

            elif hasattr(current_user, 'instrutor_profile') and current_user.instrutor_profile:
                current_user.instrutor_profile.is_rr = form.is_rr.data
                if form.foto_perfil.data:
                    success, message = InstrutorService.update_profile_picture(current_user.instrutor_profile.id, form.foto_perfil.data)
                    flash(message, 'success' if success else 'danger')

            db.session.commit()
            
            # --- ESPIÃO: MEU PERFIL ---
            school_id_log = UserService.get_current_school_id()
            if not school_id_log and hasattr(current_user, 'aluno_profile') and current_user.aluno_profile and current_user.aluno_profile.turma:
                school_id_log = current_user.aluno_profile.turma.school_id
                
            LogService.log(
                action="Atualizou Meu Perfil",
                details=f"O usuário {current_user.nome_completo} atualizou suas próprias informações pessoais/senha.",
                school_id=school_id_log
            )
            # --------------------------
            
            flash("Perfil atualizado com sucesso.", "success")
            return redirect(url_for("user.meu_perfil"))
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception(f"Erro ao salvar Meu Perfil: {e}")
            flash("Ocorreu um erro ao salvar seu perfil.", "danger")

    return render_template("meu_perfil.html", user=current_user, form=form, postos_data=posto_graduacao_structured)

@user_bp.route("/change-password-ajax", methods=["POST"])
@login_required
def change_password_ajax():
    data = request.json
    current_password = data.get('current_password')
    new_password = data.get('new_password')
    confirm_new_password = data.get('confirm_new_password')

    if not all([current_password, new_password, confirm_new_password]):
        return jsonify({'success': False, 'message': 'Todos os campos são obrigatórios.'}), 400
    if not current_user.check_password(current_password):
        return jsonify({'success': False, 'message': 'A senha atual está incorreta.'}), 400
    if new_password != confirm_new_password:
        return jsonify({'success': False, 'message': 'As novas senhas não correspondem.'}), 400
    if len(new_password) < 8:
        return jsonify({'success': False, 'message': 'A nova senha deve ter pelo menos 8 caracteres.'}), 400

    try:
        set_password_hash_on_user(current_user, new_password)
        current_user.must_change_password = False
        db.session.commit()
        
        # --- ESPIÃO: SENHA AJAX ---
        school_id_log = UserService.get_current_school_id()
        LogService.log(
            action="Alterou Senha",
            details=f"O usuário {current_user.nome_completo} alterou sua senha de acesso via painel.",
            school_id=school_id_log
        )
        # --------------------------
        
        return jsonify({'success': True, 'message': 'Senha alterada com sucesso!'})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erro ao alterar senha via AJAX: {e}")
        return jsonify({'success': False, 'message': 'Ocorreu um erro interno ao alterar a senha.'}), 500

@user_bp.route("/criar-admin", methods=["GET", "POST"])
@login_required
def criar_admin_escola():
    school_id = UserService.get_current_school_id()
    if not current_user.is_admin_escola_in_school(school_id):
        flash("Você não tem permissão para criar administradores.", "danger")
        return redirect(url_for("main.dashboard"))

    if not school_id:
        flash("Selecione uma escola primeiro.", "danger")
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        try:
            nome = (request.form.get("nome") or "").strip()
            email = norm_email(request.form.get("email"))
            id_func = norm_idfunc(request.form.get("id_func"))

            if not all([nome, email, id_func]):
                 flash("Todos os campos são obrigatórios.", "warning")
                 return redirect(url_for("user.criar_admin_escola"))

            base_username = (email.split("@")[0] if "@" in email else email)
            username = generate_unique_username(base_username)

            if db.session.scalar(select(User).where(User.email == email)):
                flash("E-mail já está em uso.", "warning")
                return redirect(url_for("user.criar_admin_escola"))
            if db.session.scalar(select(User).where(User.matricula == id_func)):
                flash("Matrícula (ID Func) já está em uso.", "warning")
                return redirect(url_for("user.criar_admin_escola"))

            temp_pass = secrets.token_urlsafe(8)

            user = User(
                matricula=id_func,
                username=username,
                email=email,
                nome_completo=nome,
                role="aluno",
                is_active=True,
                must_change_password=True
            )
            set_password_hash_on_user(user, temp_pass)

            db.session.add(user)
            db.session.flush()

            UserService.set_user_role_for_school(user.id, school_id, "admin_escola")
            db.session.commit()
            
            # --- ESPIÃO: CRIOU ADMIN ---
            LogService.log(
                action="Criou Administrador",
                details=f"Um novo administrador de escola foi criado: {nome} (Username: {username}).",
                school_id=school_id
            )
            # ---------------------------

            flash(f"Administrador criado com sucesso. Username: {username} • Senha temporária: {temp_pass}", "success")
            return redirect(url_for("user.gerenciar_usuarios"))

        except IntegrityError as ie:
            db.session.rollback()
            msg = str(getattr(ie, "orig", ie))
            flash(f"Erro de integridade: {msg}", "danger")
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Erro ao criar administrador")
            flash("Ocorreu um erro ao criar o administrador.", "danger")

    return render_template("criar_admin_escola.html")

@user_bp.route("/gerenciar-usuarios", methods=["GET"])
@login_required
@admin_required
def gerenciar_usuarios():
    school_id = UserService.get_current_school_id()
    if not school_id:
        flash("Selecione uma escola para gerenciar usuários.", "warning")
        return redirect(url_for('main.dashboard'))

    q = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)

    role_priority = case(
        (UserSchool.role == 'admin_escola', 1),
        (UserSchool.role == 'admin_sens', 2),
        (UserSchool.role == 'admin_cal', 2),
        (UserSchool.role == 'instrutor', 3),
        else_=4
    )

    stmt_assigned = select(User, UserSchool).join(UserSchool).where(UserSchool.school_id == school_id)
    if q:
        stmt_assigned = stmt_assigned.where(
            or_(User.nome_completo.ilike(f"%{q}%"), User.matricula.ilike(f"%{q}%"), User.email.ilike(f"%{q}%"))
        )
    stmt_assigned = stmt_assigned.order_by(role_priority, User.nome_completo)
    
    pagination_assigned = db.paginate(stmt_assigned, page=page, per_page=50, error_out=False)

    # -------------------------------------------------------------------------
    # CORREÇÃO AQUI: Construir manualmente a tupla (usuario, vinculo) 
    # já que o db.paginate retorna apenas a lista de usuários no .items
    # -------------------------------------------------------------------------
    usuarios_com_role_tuples = []
    for u in pagination_assigned.items:
        vinculo = db.session.scalar(
            select(UserSchool).where(UserSchool.user_id == u.id, UserSchool.school_id == school_id)
        )
        usuarios_com_role_tuples.append((u, vinculo))
    # -------------------------------------------------------------------------

    # Se for super_admin, carregar limitadamente pré-cadastrados, órfãos e usuários ativos para a tela
    orfãos = []
    pre_cadastrados = []
    todos_usuarios_ativos = []
    if current_user.role == 'super_admin':
        assigned_user_ids = db.session.scalars(db.select(UserSchool.user_id).distinct()).all()
        
        stmt_orfaos = select(User).where(User.id.notin_(assigned_user_ids), User.role != 'super_admin', User.is_active == True)
        if q: stmt_orfaos = stmt_orfaos.where(or_(User.nome_completo.ilike(f"%{q}%"), User.matricula.ilike(f"%{q}%")))
        orfãos = db.session.scalars(stmt_orfaos.limit(50)).all()
        
        stmt_pre = select(User).where(User.is_active == False)
        if q: stmt_pre = stmt_pre.where(or_(User.nome_completo.ilike(f"%{q}%"), User.matricula.ilike(f"%{q}%")))
        pre_cadastrados = db.session.scalars(stmt_pre.limit(50)).all()

        stmt_ativos = select(User).where(User.role != 'super_admin', User.is_active == True)
        if q: stmt_ativos = stmt_ativos.where(or_(User.nome_completo.ilike(f"%{q}%"), User.matricula.ilike(f"%{q}%")))
        todos_usuarios_ativos = db.session.scalars(stmt_ativos.order_by(User.nome_completo).limit(100)).all()

    return render_template(
        "manage_users.html", 
        usuarios_com_role=usuarios_com_role_tuples, 
        pagination=pagination_assigned,
        q=q,
        orfaos=orfãos, 
        pre_cadastrados=pre_cadastrados,
        todos_usuarios_ativos=todos_usuarios_ativos
    )


@user_bp.route("/alterar-papel/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def alterar_papel_usuario(user_id):
    school_id = UserService.get_current_school_id()
    if not school_id:
        return redirect(url_for('main.dashboard'))

    user = db.session.get(User, user_id)
    if not user:
        flash("Usuário não encontrado.", "danger")
        return redirect(url_for('user.gerenciar_usuarios'))

    if user.id == current_user.id:
        flash("Você não pode alterar seu próprio papel por aqui.", "warning")
        return redirect(url_for('user.gerenciar_usuarios'))

    novo_role = request.form.get('novo_role')
    papeis_validos = ['admin_cal', 'admin_sens', 'admin_escola', 'instrutor', 'aluno']

    if novo_role not in papeis_validos:
        flash("Papel inválido selecionado.", "danger")
        return redirect(url_for('user.gerenciar_usuarios'))

    success, msg = UserService.set_user_role_for_school(user.id, school_id, novo_role)

    if success:
        # --- ESPIÃO: ALTEROU PAPEL ---
        LogService.log(
            action="Alterou Permissão de Usuário",
            details=f"A permissão do usuário '{user.nome_completo}' foi alterada para '{novo_role.upper()}'.",
            school_id=school_id
        )
        # -----------------------------
        flash(f"Permissões de {user.nome_completo} atualizadas para: {novo_role.upper()}", "success")
    else:
        flash(msg, "danger")

    return redirect(url_for('user.gerenciar_usuarios'))

@user_bp.route("/vincular-usuario", methods=["POST"])
@login_required
@super_admin_required
def vincular_usuario_escola():
    school_id = UserService.get_current_school_id()
    if not school_id:
        return redirect(url_for('main.dashboard'))

    user_id = request.form.get('user_id')
    role = request.form.get('role')

    if not user_id or not role:
        flash("Selecione um usuário e um papel.", "danger")
        return redirect(url_for('user.gerenciar_usuarios'))

    success, message = UserService.assign_school_role(int(user_id), school_id, role)
    
    # --- ESPIÃO: VINCULOU USUÁRIO ---
    if success:
        user_vinculado = db.session.get(User, int(user_id))
        nome_vinculado = user_vinculado.nome_completo if user_vinculado else f"ID {user_id}"
        LogService.log(
            action="Vinculou Usuário à Escola",
            details=f"O usuário '{nome_vinculado}' foi vinculado a esta escola com o papel '{role.upper()}'.",
            school_id=school_id
        )
    # --------------------------------
    
    flash(message, 'success' if success else 'danger')

    return redirect(url_for('user.gerenciar_usuarios'))
