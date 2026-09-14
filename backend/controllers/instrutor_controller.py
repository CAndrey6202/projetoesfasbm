from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from wtforms import StringField, SelectField, BooleanField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Optional, Email, EqualTo
from flask_wtf import FlaskForm
import json

from ..services.instrutor_service import InstrutorService
from ..services.user_service import UserService
from ..services.log_service import LogService  # <--- ESPIÃO IMPORTADO AQUI
from ..models.user import User
from ..models.database import db  # Importante para o commit manual
from utils.decorators import (
    admin_or_programmer_required,
    school_admin_or_programmer_required,
    can_view_management_pages_required,
)

instrutor_bp = Blueprint("instrutor", __name__, url_prefix="/instrutor")

posto_graduacao_structured = {
    'Praças': ['Soldado PM', '3º Sargento PM EXT', '2º Sargento PM', '1º Sargento PM', 'Aluno Oficial'],
    'Oficiais': ['1º Tenente PM', 'Capitão PM', 'Major PM', 'Tenente-Coronel PM', 'Coronel PM'],
    'Saúde - Enfermagem': ['Ten Enf', 'Cap Enf', 'Maj Enf', 'Ten Cel Enf', 'Cel Enf'],
    'Saúde - Médicos': ['Ten Med', 'Cap Med', 'Maj Med', 'Ten Cel Med', 'Cel Med'],
    'Veteranos / RR': ['Soldado RR', '3º Sargento RR', '2º Sargento RR', '1º Sargento RR', '1º Tenente RR', 'Capitão RR', 'Major RR', 'Tenente-Coronel RR', 'Coronel RR'],
    'Outros': ['Civil', 'Outro']
}

class InstrutorForm(FlaskForm):
    nome_completo = StringField("Nome Completo", validators=[DataRequired()])
    nome_de_guerra = StringField("Nome de Guerra", validators=[DataRequired()])
    matricula = StringField("Matrícula", validators=[DataRequired()])
    email = StringField("E-mail", validators=[DataRequired(), Email()])
    password = PasswordField("Senha", validators=[DataRequired(), EqualTo("password2", message="As senhas devem corresponder.")])
    password2 = PasswordField("Confirmar Senha", validators=[DataRequired()])

    posto_categoria = SelectField("Categoria", choices=list(posto_graduacao_structured.keys()), validators=[DataRequired()])
    posto_graduacao = SelectField("Posto/Graduação", validators=[DataRequired()])
    posto_graduacao_outro = StringField("Outro (especifique)", validators=[Optional()])

    telefone = StringField("Telefone", validators=[Optional()])
    # Alterado para SelectField para maior estabilidade
    is_rr = SelectField("Efetivo da Reserva Remunerada (RR)", choices=[('0', 'Não'), ('1', 'Sim')], default='0')
    submit = SubmitField("Salvar")


class EditInstrutorForm(FlaskForm):
    nome_completo = StringField("Nome Completo", validators=[DataRequired()])
    nome_de_guerra = StringField("Nome de Guerra", validators=[DataRequired()])
    matricula = StringField("Matrícula", render_kw={"readonly": True})
    email = StringField("E-mail", validators=[DataRequired(), Email()])

    posto_categoria = SelectField("Categoria", choices=list(posto_graduacao_structured.keys()), validators=[DataRequired()])
    posto_graduacao = SelectField("Posto/Graduação", validators=[DataRequired()])
    posto_graduacao_outro = StringField("Outro (especifique)", validators=[Optional()])

    telefone = StringField("Telefone", validators=[Optional()])
    # CORREÇÃO: SelectField com valores string '0' e '1'
    is_rr = SelectField("Efetivo da Reserva Remunerada (RR)", choices=[('0', 'Não'), ('1', 'Sim')], default='0')
    submit = SubmitField("Salvar Alterações")


class DeleteForm(FlaskForm):
    pass


@instrutor_bp.route("/")
@login_required
@can_view_management_pages_required
def listar_instrutores():
    page = request.args.get('page', 1, type=int)
    search_term = request.args.get('q', None)

    instrutores_paginados = InstrutorService.get_all_instrutores(current_user, search_term=search_term, page=page, per_page=15)
    delete_form = DeleteForm()

    return render_template(
        "listar_instrutores.html",
        instrutores_paginados=instrutores_paginados,
        delete_form=delete_form,
        search_term=search_term
    )


@instrutor_bp.route("/cadastrar", methods=["GET", "POST"])
@login_required
@school_admin_or_programmer_required
def cadastrar_instrutor():
    form = InstrutorForm()

    if form.is_submitted():
         categoria_selecionada = form.posto_categoria.data
         if categoria_selecionada in posto_graduacao_structured:
              form.posto_graduacao.choices = [(p, p) for p in posto_graduacao_structured[categoria_selecionada]]

    if form.validate_on_submit():
        school_id = UserService.get_current_school_id()
        if not school_id:
            flash("Não foi possível identificar a escola para associar o instrutor.", "danger")
            return redirect(url_for("instrutor.listar_instrutores"))

        # Ajuste manual para garantir envio correto do boleano no create
        form_data = form.data.copy()
        form_data['is_rr'] = True if form.is_rr.data == '1' else False

        success, message = InstrutorService.create_full_instrutor(form_data, school_id)
        if success:
            # --- ESPIÃO: CADASTRO DE INSTRUTOR ---
            LogService.log(
                action="Cadastrou Instrutor",
                details=f"Um novo instrutor foi cadastrado: {form_data.get('nome_completo')} (Matrícula: {form_data.get('matricula')}).",
                school_id=school_id
            )
            # -------------------------------------
            flash(message, "success")
            return redirect(url_for("instrutor.listar_instrutores"))
        else:
            flash(message, "danger")

    return render_template("cadastro_instrutor.html", form=form, postos_data=posto_graduacao_structured)


@instrutor_bp.route("/editar/<int:instrutor_id>", methods=["GET", "POST"])
@login_required
@school_admin_or_programmer_required
def editar_instrutor(instrutor_id):
    instrutor = InstrutorService.get_instrutor_by_id(instrutor_id)
    if not instrutor or not instrutor.user:
        flash("Instrutor não encontrado.", "danger")
        return redirect(url_for("instrutor.listar_instrutores"))

    form = EditInstrutorForm(obj=instrutor)

    if request.method == 'GET':
        # Preenche os dados do Usuário
        form.nome_completo.data = instrutor.user.nome_completo
        form.nome_de_guerra.data = instrutor.user.nome_de_guerra
        form.matricula.data = instrutor.user.matricula
        form.email.data = instrutor.user.email

        # CORREÇÃO: Preenche o RR corretamente convertendo booleano para string
        form.is_rr.data = '1' if instrutor.is_rr else '0'

        # Lógica de Posto/Graduação
        posto_atual = instrutor.user.posto_graduacao
        categoria_encontrada = None
        for categoria, postos in posto_graduacao_structured.items():
            if posto_atual in postos:
                categoria_encontrada = categoria
                break

        if categoria_encontrada:
            form.posto_categoria.data = categoria_encontrada
            form.posto_graduacao.choices = [(p, p) for p in posto_graduacao_structured[categoria_encontrada]]
            form.posto_graduacao.data = posto_atual
        elif posto_atual:
            form.posto_categoria.data = 'Outros'
            form.posto_graduacao.choices = [(p, p) for p in posto_graduacao_structured['Outros']]
            form.posto_graduacao.data = 'Outro'
            form.posto_graduacao_outro.data = posto_atual

    if form.is_submitted():
         categoria_selecionada = form.posto_categoria.data
         if categoria_selecionada in posto_graduacao_structured:
              form.posto_graduacao.choices = [(p, p) for p in posto_graduacao_structured[categoria_selecionada]]

    if form.validate_on_submit():
        try:
            # --- ATUALIZAÇÃO MANUAL E SEGURA ---
            # 1. Atualiza dados do Usuário
            instrutor.user.nome_completo = form.nome_completo.data
            instrutor.user.nome_de_guerra = form.nome_de_guerra.data
            instrutor.user.email = form.email.data

            if form.posto_graduacao.data == 'Outro':
                instrutor.user.posto_graduacao = form.posto_graduacao_outro.data
            else:
                instrutor.user.posto_graduacao = form.posto_graduacao.data

            # 2. Atualiza dados do Instrutor
            instrutor.telefone = form.telefone.data

            # CORREÇÃO CRÍTICA: Converte '1'/'0' para True/False explicitamente
            instrutor.is_rr = (form.is_rr.data == '1')

            db.session.commit()
            
            # --- ESPIÃO: EDIÇÃO DE INSTRUTOR ---
            school_id = UserService.get_current_school_id()
            LogService.log(
                action="Editou Instrutor",
                details=f"Os dados do instrutor {instrutor.user.nome_completo} (Matrícula: {instrutor.user.matricula}) foram atualizados.",
                school_id=school_id
            )
            # -----------------------------------
            
            flash("Instrutor atualizado com sucesso.", "success")
            return redirect(url_for("instrutor.listar_instrutores"))

        except Exception as e:
            db.session.rollback()
            flash(f"Erro ao atualizar: {str(e)}", "danger")

    return render_template("editar_instrutor.html", form=form, instrutor=instrutor, postos_data=posto_graduacao_structured)


@instrutor_bp.route("/excluir/<int:instrutor_id>", methods=["POST"])
@login_required
@school_admin_or_programmer_required
def excluir_instrutor(instrutor_id):
    form = DeleteForm()
    if form.validate_on_submit():
        # Busca os dados do instrutor antes de apagar para registrar no log
        instrutor_temp = InstrutorService.get_instrutor_by_id(instrutor_id)
        nome_instrutor = instrutor_temp.user.nome_completo if instrutor_temp and instrutor_temp.user else f"ID {instrutor_id}"
        matricula_instrutor = instrutor_temp.user.matricula if instrutor_temp and instrutor_temp.user else "N/D"

        success, message = InstrutorService.delete_instrutor(instrutor_id)
        if success:
            # --- ESPIÃO: EXCLUSÃO DE INSTRUTOR ---
            school_id = UserService.get_current_school_id()
            LogService.log(
                action="Excluiu Instrutor",
                details=f"O instrutor {nome_instrutor} (Matrícula: {matricula_instrutor}) foi removido do sistema.",
                school_id=school_id
            )
            # -------------------------------------
            flash(message, "success")
        else:
            flash(message, "danger")
    else:
        flash("Falha na validação do formulário de exclusão.", "danger")
    return redirect(url_for("instrutor.listar_instrutores"))
