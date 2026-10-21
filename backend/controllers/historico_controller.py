from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from sqlalchemy import select
from wtforms import StringField, TextAreaField, DateTimeLocalField, SubmitField, SelectField
from wtforms.validators import DataRequired

from ..models.database import db
from ..models.historico_disciplina import HistoricoDisciplina
from ..models.disciplina import Disciplina
from ..models.turma import Turma
from ..models.elogio import Elogio
from ..models.processo_disciplina import ProcessoDisciplina
from ..services.historico_service import HistoricoService
from ..services.aluno_service import AlunoService
from ..services.turma_service import TurmaService
from utils.decorators import admin_or_programmer_required, aluno_profile_required, can_view_management_pages_required

historico_bp = Blueprint('historico', __name__, url_prefix='/historico')


def _sincronizar_matriculas_aluno_por_ciclo(aluno):
    """
    Garante que o aluno esteja matriculado nas disciplinas da turma a que pertenceu em cada ciclo,
    preservando integralmente as disciplinas e notas de ciclos anteriores e removendo
    eventuais matrículas em branco geradas em turmas diferentes no mesmo ciclo.
    """
    if not aluno or not aluno.turma or not aluno.turma.school:
        return []

    school_id = aluno.turma.school.id
    edicao_id_aluno = aluno.turma.edicao_id

    TurmaService.sincronizar_historico_ciclos(school_id, edicao_id_aluno)
    ciclos = TurmaService.get_ciclos_da_escola(school_id, edicao_id_aluno)
    mapa_ciclo_turma = TurmaService.get_mapa_turma_por_ciclo_aluno(aluno.id)

    disciplinas_da_escola = db.session.scalars(
        select(Disciplina).join(Turma).where(
            Turma.school_id == school_id,
            Turma.edicao_id == edicao_id_aluno
        )
    ).all()

    alterou = False

    # 1. Remove matrículas sem nenhuma nota que pertençam a outra turma naquele ciclo
    for h in list(aluno.historico_disciplinas):
        disc = h.disciplina
        if not disc:
            continue
        turma_correta_no_ciclo = mapa_ciclo_turma.get(disc.ciclo_id, aluno.turma_id)
        if disc.turma_id != turma_correta_no_ciclo:
            sem_notas = (h.nota_p1 is None and h.nota_p2 is None and h.nota_rec is None and h.nota is None)
            if sem_notas:
                db.session.delete(h)
                alterou = True

    if alterou:
        db.session.flush()

    matriculas_existentes_ids = {h.disciplina_id for h in aluno.historico_disciplinas if h in db.session}

    # 2. Matricula nas disciplinas da turma correta do aluno em cada ciclo
    for disciplina in disciplinas_da_escola:
        turma_correta_no_ciclo = mapa_ciclo_turma.get(disciplina.ciclo_id, aluno.turma_id)
        if disciplina.turma_id == turma_correta_no_ciclo and disciplina.id not in matriculas_existentes_ids:
            db.session.add(HistoricoDisciplina(aluno_id=aluno.id, disciplina_id=disciplina.id))
            alterou = True

    if alterou:
        db.session.commit()

    return ciclos


@historico_bp.route('/')
@login_required
@aluno_profile_required
def index():
    """Página principal de seleção do 'Meu CTSP'."""
    return render_template('meu_ctsp_index.html')

@historico_bp.route('/sancoes')
@login_required
@aluno_profile_required
def sancoes():
    """Página para visualizar sanções disciplinares do aluno logado."""
    aluno_id = current_user.aluno_profile.id
    
    processos_lista = db.session.scalars(
        select(ProcessoDisciplina)
        .where(ProcessoDisciplina.aluno_id == aluno_id)
        .order_by(ProcessoDisciplina.data_ocorrencia.desc())
    ).all()
    
    return render_template('sancoes.html', sancoes=processos_lista)

@historico_bp.route('/elogios')
@login_required
@aluno_profile_required
def elogios():
    """Página para visualizar elogios do aluno logado."""
    aluno_id = current_user.aluno_profile.id
    
    elogios_lista = db.session.scalars(
        select(Elogio).where(Elogio.aluno_id == aluno_id).order_by(Elogio.data_elogio.desc())
    ).all()
    
    return render_template('elogios.html', elogios=elogios_lista)

@historico_bp.route('/funcional/<int:aluno_id>')
@login_required
@aluno_profile_required
def historico_funcional(aluno_id):
    """Página para visualizar o histórico unificado do aluno."""
    aluno = AlunoService.get_aluno_by_id(aluno_id)
    if not aluno:
        flash("Aluno não encontrado.", "danger")
        return redirect(url_for('main.dashboard'))
    
    if current_user.role == 'aluno' and current_user.aluno_profile.id != aluno_id:
        flash("Você não tem permissão para ver o histórico de outro aluno.", "danger")
        return redirect(url_for('main.dashboard'))

    historico_unificado = HistoricoService.get_unified_historico_for_aluno(aluno_id)
    elogios_lista = Elogio.query.filter_by(aluno_id=aluno.id).all()

    return render_template('historico_funcional.html', 
                           aluno=aluno, 
                           historico=historico_unificado,
                           elogios=elogios_lista)


@historico_bp.route('/minhas-notas')
@login_required
@aluno_profile_required
def minhas_notas():
    aluno_id = current_user.aluno_profile.id
    aluno = AlunoService.get_aluno_by_id(aluno_id)
    if not aluno:
        flash("Aluno não encontrado.", 'danger')
        return redirect(url_for('main.dashboard'))

    ciclos = _sincronizar_matriculas_aluno_por_ciclo(aluno)
    ciclo_id = request.args.get('ciclo_id', type=int)

    historico_disciplinas = HistoricoService.get_historico_disciplinas_for_aluno(aluno_id)
    notas_finais = [h.nota for h in historico_disciplinas if h.nota is not None]
    media_final_curso = sum(notas_finais) / len(notas_finais) if notas_finais else 0.0

    if ciclo_id:
        historico_disciplinas = [
            h for h in historico_disciplinas
            if h.disciplina and h.disciplina.ciclo_id == ciclo_id
        ]

    elogios_lista = Elogio.query.filter_by(aluno_id=aluno.id).all()

    return render_template('historico_aluno.html',
                           aluno=aluno,
                           historico_disciplinas=historico_disciplinas,
                           media_final_curso=media_final_curso,
                           elogios=elogios_lista,
                           ciclos=ciclos,
                           ciclo_selecionado_id=ciclo_id,
                           is_own_profile=True)

@historico_bp.route('/ver/<int:aluno_id>')
@login_required
@can_view_management_pages_required
def ver_historico_aluno(aluno_id):
    if current_user.role not in ['super_admin', 'admin_escola']:
        flash("Você não tem permissão para visualizar este histórico.", 'danger')
        return redirect(url_for('main.dashboard'))

    aluno = AlunoService.get_aluno_by_id(aluno_id)
    if not aluno:
        flash("Aluno não encontrado.", 'danger')
        return redirect(url_for('aluno.listar_alunos'))

    ciclos = _sincronizar_matriculas_aluno_por_ciclo(aluno)
    ciclo_id = request.args.get('ciclo_id', type=int)

    historico_disciplinas = HistoricoService.get_historico_disciplinas_for_aluno(aluno_id)
    notas_finais = [h.nota for h in historico_disciplinas if h.nota is not None]
    media_final_curso = sum(notas_finais) / len(notas_finais) if notas_finais else 0.0

    if ciclo_id:
        historico_disciplinas = [
            h for h in historico_disciplinas
            if h.disciplina and h.disciplina.ciclo_id == ciclo_id
        ]

    elogios_lista = Elogio.query.filter_by(aluno_id=aluno.id).all()

    return render_template('historico_aluno.html',
                           aluno=aluno,
                           historico_disciplinas=historico_disciplinas,
                           media_final_curso=media_final_curso,
                           elogios=elogios_lista,
                           ciclos=ciclos,
                           ciclo_selecionado_id=ciclo_id,
                           is_own_profile=False)


@historico_bp.route('/avaliar/<int:historico_id>', methods=['POST'])
@login_required
def avaliar_aluno_disciplina(historico_id):
    registro = db.session.get(HistoricoDisciplina, historico_id)
    if not registro:
        flash("Registro de avaliação não encontrado.", 'danger')
        return redirect(url_for('main.dashboard'))

    is_own_profile = hasattr(current_user, 'aluno_profile') and current_user.aluno_profile.id == registro.aluno_id
    is_admin = getattr(current_user, 'role', None) in ['super_admin', 'admin_escola']

    if not (is_own_profile or is_admin):
        flash("Você não tem permissão para realizar esta ação.", 'danger')
        return redirect(url_for('main.dashboard'))

    form_data = request.form.to_dict()
    success, message, aluno_id = HistoricoService.avaliar_aluno(historico_id, form_data, from_admin=is_admin)

    if success:
        flash(message, 'success')
    else:
        flash(message, 'danger')

    if is_admin:
        return redirect(url_for('historico.ver_historico_aluno', aluno_id=aluno_id))
    return redirect(url_for('historico.minhas_notas'))
