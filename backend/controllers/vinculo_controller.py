from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_required, current_user
from sqlalchemy import select, or_
from flask_wtf import FlaskForm
from wtforms import SelectField, SubmitField
from wtforms.validators import DataRequired, Optional

from ..models.database import db
from ..models.turma import Turma
from ..models.ciclo import Ciclo
from ..models.disciplina import Disciplina
from ..models.disciplina_turma import DisciplinaTurma
from ..services.user_service import UserService 
from ..services.vinculo_service import VinculoService
from ..services.instrutor_service import InstrutorService
from ..services.turma_service import TurmaService
from ..services.log_service import LogService # <--- ESPIÃO IMPORTADO AQUI
from utils.decorators import sens_or_admin_or_programmer_required

vinculo_bp = Blueprint('vinculo', __name__, url_prefix='/vinculos')

class VinculoForm(FlaskForm):
    instrutor_id_1 = SelectField('Instrutor 1', coerce=int, validators=[Optional()])
    instrutor_id_2 = SelectField('Instrutor 2', coerce=int, validators=[Optional()])
    disciplina_id = SelectField('Disciplina', coerce=int, validators=[DataRequired(message="Por favor, selecione uma disciplina.")])
    submit = SubmitField('Salvar')

class DeleteForm(FlaskForm):
    pass

@vinculo_bp.route('/')
@login_required
@sens_or_admin_or_programmer_required
def gerenciar_vinculos():
    school_id = UserService.get_current_school_id()
    if not school_id:
        flash("Nenhuma escola associada ou selecionada.", "warning")
        return redirect(url_for('main.dashboard'))

    turma_filtrada_id = request.args.get('turma_id', type=int)
    ciclo_filtrado_id = request.args.get('ciclo_id', type=int)
    
    if turma_filtrada_id:
        turma_check = db.session.get(Turma, turma_filtrada_id)
        if not turma_check or turma_check.school_id != school_id:
            flash("Turma selecionada inválida ou de outra escola.", "warning")
            turma_filtrada_id = None 

    active_edicao = session.get('active_edicao_id')

    ciclos = db.session.scalars(
        select(Ciclo).where(
            Ciclo.school_id == school_id,
            or_(Ciclo.edicao_id == active_edicao, Ciclo.edicao_id == None)
        ).order_by(Ciclo.nome)
    ).all()
    if not ciclos and school_id:
        ciclos = db.session.scalars(
            select(Ciclo).where(Ciclo.school_id == school_id).order_by(Ciclo.nome)
        ).all()

    vinculos = VinculoService.get_all_vinculos(turma_filtrada_id, school_id, active_edicao, ciclo_id=ciclo_filtrado_id)
    turmas = TurmaService.get_turmas_by_school(school_id, active_edicao)
    delete_form = DeleteForm()
    
    return render_template('gerenciar_vinculos.html', 
                           vinculos=vinculos, 
                           turmas=turmas,
                           ciclos=ciclos,
                           ciclo_filtrado_id=ciclo_filtrado_id,
                           turma_filtrada_id=turma_filtrada_id,
                           delete_form=delete_form,
                           can_manage_vinculos=True)

@vinculo_bp.route('/adicionar', methods=['GET', 'POST'])
@login_required
@sens_or_admin_or_programmer_required
def adicionar_vinculo():
    school_id = UserService.get_current_school_id()
    if not school_id:
        return redirect(url_for('main.dashboard'))

    form = VinculoForm()
    instrutores = InstrutorService.get_all_instrutores_sem_paginacao(user=current_user)
    active_edicao = session.get('active_edicao_id')
    turmas = TurmaService.get_turmas_by_school(school_id, active_edicao)

    instrutor_choices = []
    for i in instrutores:
        nome = i.user.nome_de_guerra or i.user.username
        posto = i.user.posto_graduacao
        display_text = f"{nome} - {posto}" if posto else nome
        instrutor_choices.append((i.id, display_text))

    form.instrutor_id_1.choices = [(0, '-- Nenhum --')] + instrutor_choices
    form.instrutor_id_2.choices = [(0, '-- Nenhum --')] + instrutor_choices
    
    if request.method == 'POST':
        turma_id_selecionada = request.form.get('turma_id', type=int)
        turma_check = db.session.get(Turma, turma_id_selecionada)
        if turma_id_selecionada and turma_check and turma_check.school_id == school_id:
            disciplinas_da_turma = db.session.scalars(
                select(Disciplina).where(Disciplina.turma_id == turma_id_selecionada).order_by(Disciplina.materia)
            ).all()
            form.disciplina_id.choices = [(d.id, d.materia) for d in disciplinas_da_turma]
        else:
            form.disciplina_id.choices = []
    else:
        form.disciplina_id.choices = []

    if form.validate_on_submit():
        success, message = VinculoService.add_vinculo(form.data)
        
        # --- ESPIÃO: ADICIONOU VÍNCULO ---
        if success:
            LogService.log(
                action="Criou Vínculo",
                details=f"Um novo vínculo de instrutor foi criado para a disciplina ID {form.data.get('disciplina_id')}.",
                school_id=school_id
            )
        # ---------------------------------
        
        flash(message, 'success' if success else 'danger')
        if success:
            return redirect(url_for('vinculo.gerenciar_vinculos'))
    elif form.errors:
        for field, error_messages in form.errors.items():
            for error in error_messages:
                flash(f"Erro no campo '{getattr(form, field).label.text}': {error}", 'danger')
    
    return render_template('adicionar_vinculo.html', form=form, turmas=turmas)

@vinculo_bp.route('/editar/<int:vinculo_id>', methods=['GET', 'POST'])
@login_required
@sens_or_admin_or_programmer_required
def editar_vinculo(vinculo_id):
    school_id = UserService.get_current_school_id()
    if not school_id:
        return redirect(url_for('main.dashboard'))

    vinculo = db.session.get(DisciplinaTurma, vinculo_id)

    if not vinculo:
        flash("Vínculo não encontrado.", "danger")
        return redirect(url_for('vinculo.gerenciar_vinculos'))
    
    if not vinculo.disciplina:
        flash("Erro de integridade: Vínculo sem disciplina associada.", "danger")
        return redirect(url_for('vinculo.gerenciar_vinculos'))

    turma_real = vinculo.disciplina.turma

    if not turma_real or turma_real.school_id != school_id:
        flash("Este vínculo pertence a uma turma que não está nesta escola.", "danger")
        return redirect(url_for('vinculo.gerenciar_vinculos'))

    form = VinculoForm(obj=vinculo)
    
    instrutores = InstrutorService.get_all_instrutores_sem_paginacao(user=current_user)
    
    instrutor_choices = []
    for i in instrutores:
        nome = i.user.nome_de_guerra or i.user.username
        posto = i.user.posto_graduacao
        display_text = f"{nome} - {posto}" if posto else nome
        instrutor_choices.append((i.id, display_text))

    form.instrutor_id_1.choices = [(0, '-- Nenhum --')] + instrutor_choices
    form.instrutor_id_2.choices = [(0, '-- Nenhum --')] + instrutor_choices

    form.disciplina_id.choices = [(d.id, d.materia) for d in turma_real.disciplinas]
    
    if form.validate_on_submit():
        success, message = VinculoService.edit_vinculo(vinculo_id, form.data)
        
        # --- ESPIÃO: EDITOU VÍNCULO ---
        if success:
            LogService.log(
                action="Editou Vínculo",
                details=f"O vínculo ID {vinculo_id} da disciplina '{vinculo.disciplina.materia}' foi atualizado.",
                school_id=school_id
            )
        # ------------------------------
        
        flash(message, 'success' if success else 'danger')
        return redirect(url_for('vinculo.gerenciar_vinculos', turma_id=turma_real.id))
    
    if request.method == 'GET':
        form.instrutor_id_1.data = vinculo.instrutor_id_1 or 0
        form.instrutor_id_2.data = vinculo.instrutor_id_2 or 0
        form.disciplina_id.data = vinculo.disciplina_id

    return render_template('editar_vinculo.html', form=form, vinculo=vinculo, turma=turma_real)

@vinculo_bp.route('/excluir/<int:vinculo_id>', methods=['POST'])
@login_required
@sens_or_admin_or_programmer_required
def excluir_vinculo(vinculo_id):
    school_id = UserService.get_current_school_id()
    if not school_id:
        return redirect(url_for('main.dashboard'))

    vinculo = db.session.get(DisciplinaTurma, vinculo_id)

    if not vinculo:
        flash("Vínculo não encontrado.", "danger")
        return redirect(url_for('vinculo.gerenciar_vinculos'))
        
    if not vinculo.disciplina:
        flash("Erro de integridade: Vínculo sem disciplina associada.", "danger")
        return redirect(url_for('vinculo.gerenciar_vinculos'))

    turma_real = vinculo.disciplina.turma
    
    if not turma_real or turma_real.school_id != school_id:
        flash("Este vínculo pertence a uma turma que não está nesta escola.", "danger")
        return redirect(url_for('vinculo.gerenciar_vinculos'))
    
    turma_id_para_redirecionar = turma_real.id

    form = DeleteForm()
    if form.validate_on_submit():
        nome_disciplina = vinculo.disciplina.materia if vinculo.disciplina else "N/D"
        turma_nome = turma_real.nome if turma_real else "N/D"
        
        success, message = VinculoService.delete_vinculo(vinculo_id)
        
        # --- ESPIÃO: EXCLUIU VÍNCULO ---
        if success:
            LogService.log(
                action="Excluiu Vínculo",
                details=f"O vínculo da disciplina '{nome_disciplina}' (Turma: {turma_nome}) foi removido.",
                school_id=school_id
            )
        # -------------------------------
        
        flash(message, 'success' if success else 'danger')
        
    return redirect(url_for('vinculo.gerenciar_vinculos', turma_id=turma_id_para_redirecionar))
