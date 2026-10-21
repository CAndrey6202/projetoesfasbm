# backend/controllers/turma_controller.py

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, abort, session
from flask_login import login_required, current_user
from sqlalchemy import select, or_, and_
from sqlalchemy.orm import joinedload
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, SelectMultipleField, SelectField, DateField
from wtforms.validators import DataRequired, Length, Optional
from wtforms.widgets import CheckboxInput, ListWidget
from datetime import datetime

from ..models.database import db
from ..models.turma import Turma, TurmaStatus
from ..models.aluno import Aluno
from ..models.user import User 
from ..models.user_school import UserSchool
from ..models.turma_cargo import TurmaCargo 
from ..models.aluno_ciclo_turma import AlunoCicloTurma
from ..services.turma_service import TurmaService
from ..services.user_service import UserService 
from ..services.log_service import LogService
from utils.decorators import admin_or_programmer_required, school_admin_or_programmer_required, can_view_management_pages_required

turma_bp = Blueprint('turma', __name__, url_prefix='/turma')

# USA A LISTA OFICIAL DO MODELO
CARGOS_LISTA = TurmaCargo.get_all_roles()

class TurmaForm(FlaskForm):
    nome = StringField('Nome da Turma', validators=[DataRequired(), Length(max=100)])
    ano = StringField('Ano / Edição', validators=[DataRequired(), Length(max=20)])
    data_formatura = DateField('Data de Formatura', format='%Y-%m-%d', validators=[Optional()])

    status = SelectField(
        'Status da Turma',
        choices=[(s.value, s.name.replace('_', ' ').title()) for s in TurmaStatus],
        validators=[DataRequired()]
    )
    alunos_ids = SelectMultipleField('Alunos da Turma', coerce=int, validators=[Optional()],
                                     option_widget=CheckboxInput(), widget=ListWidget(prefix_label=False))
    submit = SubmitField('Salvar Turma')

class DeleteForm(FlaskForm):
    pass

@turma_bp.route('/')
@login_required
@can_view_management_pages_required
def listar_turmas():
    delete_form = DeleteForm()
    school_id = UserService.get_current_school_id()
    if not school_id:
        flash('Nenhuma escola associada.', 'warning')
        return redirect(url_for('main.dashboard'))
        
    active_edicao_id = session.get('active_edicao_id')
    ciclo_id = request.args.get('ciclo_id', type=int)

    TurmaService.sincronizar_historico_ciclos(school_id, edicao_id=active_edicao_id)
    ciclos = TurmaService.get_ciclos_da_escola(school_id, edicao_id=active_edicao_id)
    turmas = TurmaService.get_turmas_by_school(school_id, edicao_id=active_edicao_id)

    if current_user.role.lower() == 'aluno' and current_user.aluno_profile and current_user.aluno_profile.turma_id:
        user_turma_id = TurmaService.get_turma_id_aluno_no_ciclo(
            current_user.aluno_profile.id,
            ciclo_id=ciclo_id,
            default_turma_id=current_user.aluno_profile.turma_id
        )
        turmas = sorted(turmas, key=lambda t: t.id != user_turma_id)

    contagem_alunos_por_turma = {}
    for t in turmas:
        if ciclo_id:
            contagem_alunos_por_turma[t.id] = len(TurmaService.get_alunos_da_turma_no_ciclo(t.id, ciclo_id=ciclo_id))
        else:
            contagem_alunos_por_turma[t.id] = len(t.alunos)

    return render_template(
        'listar_turmas.html',
        turmas=turmas,
        delete_form=delete_form,
        ciclos=ciclos,
        ciclo_selecionado_id=ciclo_id,
        contagem_alunos_por_turma=contagem_alunos_por_turma
    )

@turma_bp.route('/<int:turma_id>')
@login_required
@can_view_management_pages_required
def detalhes_turma(turma_id):
    school_id = UserService.get_current_school_id()
    turma = db.session.get(Turma, turma_id)
    
    if not turma or turma.school_id != school_id:
        flash('Turma não encontrada.', 'danger')
        return redirect(url_for('turma.listar_turmas'))
    
    ciclo_id = request.args.get('ciclo_id', type=int)
    ciclos = TurmaService.get_ciclos_da_escola(school_id, edicao_id=turma.edicao_id)

    cargos_atuais = TurmaService.get_cargos_da_turma(turma_id, CARGOS_LISTA)
    
    if ciclo_id:
        lista_alunos_base = TurmaService.get_alunos_da_turma_no_ciclo(turma_id, ciclo_id=ciclo_id)
    else:
        lista_alunos_base = turma.alunos

    alunos_ordenados = sorted(
        lista_alunos_base, 
        key=lambda a: (a.user.nome_completo.lower() if a.user and a.user.nome_completo else "")
    )
    
    return render_template(
        'detalhes_turma.html',
        turma=turma,
        cargos_lista=CARGOS_LISTA,
        cargos_atuais=cargos_atuais,
        alunos_ordenados=alunos_ordenados,
        ciclos=ciclos,
        ciclo_selecionado_id=ciclo_id
    )

@turma_bp.route('/remanejar-ciclo', methods=['GET', 'POST'])
@login_required
def remanejar_ciclo():
    school_id = UserService.get_current_school_id()
    if not school_id:
        flash("Escola não selecionada.", "warning")
        return redirect(url_for('main.dashboard'))

    if not (
        current_user.is_sens_in_school(school_id)
        or current_user.is_admin_escola_in_school(school_id)
        or current_user.role in ['super_admin', 'admin_escola', 'programador']
    ):
        flash("Permissão negada. Apenas a Chefia de Ensino (SENS) ou Administração da Escola podem remanejar turmas por ciclo.", "danger")
        return redirect(url_for('turma.listar_turmas'))

    active_edicao_id = session.get('active_edicao_id')
    TurmaService.sincronizar_historico_ciclos(school_id, edicao_id=active_edicao_id)

    turmas = TurmaService.get_turmas_by_school(school_id, edicao_id=active_edicao_id)
    ciclos = TurmaService.get_ciclos_da_escola(school_id, edicao_id=active_edicao_id)

    if not ciclos:
        flash("Cadastre ao menos um Ciclo nas disciplinas/semanas antes de remanejar alunos por ciclo.", "warning")
        return redirect(url_for('turma.listar_turmas'))

    if request.method == 'POST':
        ciclo_origem_id = request.form.get('ciclo_origem_id', type=int)
        ciclo_destino_id = request.form.get('ciclo_destino_id', type=int)

        mapeamento = {}
        for key, val in request.form.items():
            if key.startswith('nova_turma_'):
                aid_str = key.replace('nova_turma_', '').strip()
                if aid_str.isdigit() and val and str(val).isdigit():
                    mapeamento[int(aid_str)] = int(val)

        ok, msg = TurmaService.remanejar_alunos_ciclo(
            school_id=school_id,
            edicao_id=active_edicao_id,
            ciclo_origem_id=ciclo_origem_id,
            ciclo_destino_id=ciclo_destino_id,
            mapeamento_aluno_turma=mapeamento
        )

        if ok:
            LogService.log(
                action="Remanejou Alunos por Ciclo",
                details=f"Remanejamento de alunos executado para o ciclo ID {ciclo_destino_id} ({len(mapeamento)} alunos).",
                school_id=school_id
            )
            flash(msg, "success")
            return redirect(url_for('turma.remanejar_ciclo', ciclo_origem_id=ciclo_origem_id, ciclo_destino_id=ciclo_destino_id))
        else:
            flash(msg, "danger")

    # Definição inteligente dos ciclos padrão (ex: Origem = Ciclo 1, Destino = Ciclo 2)
    default_origem = ciclos[-2].id if len(ciclos) >= 2 else ciclos[0].id
    default_destino = ciclos[-1].id if len(ciclos) >= 2 else ciclos[0].id

    ciclo_origem_id = request.args.get('ciclo_origem_id', type=int) or default_origem
    ciclo_destino_id = request.args.get('ciclo_destino_id', type=int) or default_destino

    # Busca todos os alunos da edição ativa na escola
    query_alunos = (
        select(Aluno)
        .join(User, Aluno.user_id == User.id)
        .join(UserSchool, User.id == UserSchool.user_id)
        .outerjoin(Turma, Aluno.turma_id == Turma.id)
        .options(joinedload(Aluno.user), joinedload(Aluno.turma))
        .where(
            UserSchool.school_id == school_id,
            UserSchool.role == 'aluno'
        )
    )
    if active_edicao_id:
        query_alunos = query_alunos.where(
            or_(
                Turma.edicao_id == active_edicao_id,
                Aluno.edicao_id == active_edicao_id
            )
        )
    alunos = db.session.scalars(query_alunos.order_by(Turma.nome, User.nome_completo)).unique().all()

    # Carrega o mapa {aluno_id: {ciclo_id: turma_id}}
    vinculos_all = db.session.scalars(
        select(AlunoCicloTurma).where(AlunoCicloTurma.ciclo_id.in_([c.id for c in ciclos]))
    ).all()
    mapa_aluno_ciclo = {}
    for v in vinculos_all:
        mapa_aluno_ciclo.setdefault(v.aluno_id, {})[v.ciclo_id] = v.turma_id

    turmas_dict = {t.id: t.nome for t in turmas}

    alunos_view = []
    for a in alunos:
        ciclos_do_aluno = mapa_aluno_ciclo.get(a.id, {})
        turma_origem_id = ciclos_do_aluno.get(ciclo_origem_id, a.turma_id)
        turma_destino_id = ciclos_do_aluno.get(ciclo_destino_id, a.turma_id)
        alunos_view.append({
            'aluno': a,
            'turma_origem_id': turma_origem_id,
            'turma_origem_nome': turmas_dict.get(turma_origem_id, a.turma.nome if a.turma else 'Sem Turma'),
            'turma_destino_id': turma_destino_id,
            'historico_ciclos': {
                c.nome: turmas_dict.get(ciclos_do_aluno.get(c.id), '-')
                for c in ciclos
            }
        })

    return render_template(
        'remanejar_ciclo.html',
        turmas=turmas,
        ciclos=ciclos,
        ciclo_origem_id=ciclo_origem_id,
        ciclo_destino_id=ciclo_destino_id,
        alunos_view=alunos_view
    )

@turma_bp.route('/<int:turma_id>/salvar-cargos', methods=['POST'])
@login_required
def salvar_cargos_turma(turma_id):
    school_id = UserService.get_current_school_id()
    if not school_id:
        flash("Sessão expirada ou escola não selecionada.", "warning")
        return redirect(url_for('main.dashboard'))

    if not current_user.is_sens_in_school(school_id):
        flash("Permissão negada. Apenas Chefia de Ensino (SENS) ou Comandante podem alterar cargos.", "danger")
        return redirect(url_for('turma.detalhes_turma', turma_id=turma_id))

    turma = db.session.get(Turma, turma_id)
    if not turma or turma.school_id != school_id:
        flash('Turma não encontrada.', 'danger')
        return redirect(url_for('turma.listar_turmas'))

    success, message = TurmaService.atualizar_cargos(turma_id, request.form)
    
    if success:
        LogService.log(
            action="Atualizou Cargos da Turma",
            details=f"Os cargos/funções da turma '{turma.nome}' foram atualizados.",
            school_id=school_id
        )
    
    flash(message, 'success' if success else 'danger')
    return redirect(url_for('turma.detalhes_turma', turma_id=turma_id))

@turma_bp.route('/cadastrar', methods=['GET', 'POST'])
@login_required
@school_admin_or_programmer_required
def cadastrar_turma():
    form = TurmaForm()
    school_id = UserService.get_current_school_id()
    if not school_id: return redirect(url_for('turma.listar_turmas'))

    active_edicao = session.get('active_edicao_id')
    alunos_sem_turma = db.session.scalars(select(Aluno).join(User).join(UserSchool).where(Aluno.turma_id.is_(None), UserSchool.school_id == school_id, Aluno.edicao_id == active_edicao)).all()
    form.alunos_ids.choices = [(a.id, f"{a.user.nome_completo}") for a in alunos_sem_turma]

    if form.validate_on_submit():
        active_edicao_id = session.get('active_edicao_id')
        success, message = TurmaService.create_turma(form.data, school_id, edicao_id=active_edicao_id)
        if success:
            LogService.log(
                action="Cadastrou Turma",
                details=f"A turma '{form.data.get('nome')}' foi criada.",
                school_id=school_id
            )
            flash(message, 'success')
            return redirect(url_for('turma.listar_turmas'))
        else:
            flash(message, 'danger')
    return render_template('cadastrar_turma.html', form=form)

@turma_bp.route('/editar/<int:turma_id>', methods=['GET', 'POST'])
@login_required
@school_admin_or_programmer_required
def editar_turma(turma_id):
    school_id = UserService.get_current_school_id()
    turma = db.session.get(Turma, turma_id)
    if not turma or turma.school_id != school_id: return redirect(url_for('turma.listar_turmas'))
    
    form = TurmaForm(obj=turma)
    
    active_edicao = session.get('active_edicao_id')
    alunos = db.session.scalars(select(Aluno).join(User).join(UserSchool).where(UserSchool.school_id == school_id, Aluno.edicao_id == active_edicao, or_(Aluno.turma_id.is_(None), Aluno.turma_id == turma_id))).all()
    form.alunos_ids.choices = [(a.id, f"{a.user.nome_completo}") for a in alunos]
    
    if form.validate_on_submit():
        dados_para_salvar = form.data.copy()
        
        if not hasattr(turma, 'data_formatura') and 'data_formatura' in dados_para_salvar:
            dados_para_salvar.pop('data_formatura')

        success, message = TurmaService.update_turma(turma_id, dados_para_salvar)
        
        if success:
            LogService.log(
                action="Editou Turma",
                details=f"Os dados da turma '{turma.nome}' foram atualizados.",
                school_id=school_id
            )
            flash(message, 'success')
            return redirect(url_for('turma.listar_turmas'))
        else:
            flash(message, 'danger')
            
    if request.method == 'GET':
        form.alunos_ids.data = [a.id for a in turma.alunos]
        if hasattr(turma, 'data_formatura') and getattr(turma, 'data_formatura'):
            form.data_formatura.data = turma.data_formatura

    return render_template('editar_turma.html', form=form, turma=turma)

@turma_bp.route('/excluir/<int:turma_id>', methods=['POST'])
@login_required
@school_admin_or_programmer_required
def excluir_turma(turma_id):
    school_id = UserService.get_current_school_id()
    turma = db.session.get(Turma, turma_id)
    if not turma or turma.school_id != school_id: return redirect(url_for('turma.listar_turmas'))
    form = DeleteForm()
    if form.validate_on_submit():
        nome_turma = turma.nome
        
        success, message = TurmaService.delete_turma(turma_id)
        if success:
            LogService.log(
                action="Excluiu Turma",
                details=f"A turma '{nome_turma}' foi removida do sistema.",
                school_id=school_id
            )
            flash(message, 'success')
        else:
            flash(message, 'danger')
    return redirect(url_for('turma.listar_turmas'))
