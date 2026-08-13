# backend/controllers/admin_controller.py

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, abort, session
from flask_login import login_required, current_user
from sqlalchemy import select, func, case, desc, and_, distinct
from sqlalchemy.orm import joinedload, aliased  
from collections import defaultdict
from datetime import datetime
from functools import wraps

from backend.models.database import db
from backend.models.school import School
from backend.models.turma import Turma
from backend.models.aluno import Aluno
from backend.models.disciplina import Disciplina
from backend.models.diario_classe import DiarioClasse
from backend.models.frequencia import FrequenciaAluno
from backend.models.user import User
from backend.models.instrutor import Instrutor
from backend.services.user_service import UserService
from backend.services.diario_service import DiarioService

admin_escola_bp = Blueprint('admin_escola', __name__, url_prefix='/admin-escola')

def sens_permission_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        
        school_id = UserService.get_current_school_id()
        
        if not (current_user.is_sens_in_school(school_id) or 
                current_user.is_admin_escola_in_school(school_id) or
                getattr(current_user, 'is_super_admin', False)):
            
            flash("Acesso restrito. Área exclusiva para a Seção de Ensino (SENS) nesta escola.", "danger")
            return redirect(url_for('main.dashboard'))
            
        return f(*args, **kwargs)
    return decorated_function

@admin_escola_bp.route('/')
@login_required
@sens_permission_required
def index():
    school_id = UserService.get_current_school_id()
    school = db.session.get(School, school_id)
    return render_template('admin/dashboard.html', school=school)

@admin_escola_bp.route('/espelho-diarios')
@login_required
@sens_permission_required
def espelho_diarios():
    school_id = UserService.get_current_school_id()
    if not school_id:
        flash("Escola não encontrada.", "danger")
        return redirect(url_for('main.dashboard'))

    active_edicao = session.get('active_edicao_id')

    # =========================================================================
    # CORREÇÃO: Subquery isolada para contar faltas REAIS (evita duplicação)
    # =========================================================================
    
    # Esta subquery consolida as faltas por aluno e disciplina ANTES de cruzar com as outras tabelas
    subquery_faltas = db.session.query(
        FrequenciaAluno.aluno_id,
        DiarioClasse.disciplina_id,
        func.count(FrequenciaAluno.id).label('contagem')
    ).join(DiarioClasse, FrequenciaAluno.diario_id == DiarioClasse.id)\
     .filter(
         FrequenciaAluno.presente == False,
         DiarioClasse.is_deleted == False
     )\
     .group_by(FrequenciaAluno.aluno_id, DiarioClasse.disciplina_id).subquery()

    # Query principal unindo Alunos com a contagem exata da subquery
    stats_query = db.session.query(
        Aluno.id.label('aluno_id'),
        User.nome_completo,
        User.nome_de_guerra,
        User.matricula,
        Turma.nome.label('turma_nome'),
        Disciplina.materia,
        Disciplina.carga_horaria_prevista,
        subquery_faltas.c.contagem
    ).join(Turma, Aluno.turma_id == Turma.id)\
     .join(User, Aluno.user_id == User.id)\
     .join(subquery_faltas, Aluno.id == subquery_faltas.c.aluno_id)\
     .join(Disciplina, subquery_faltas.c.disciplina_id == Disciplina.id)\
     .filter(
         Turma.school_id == school_id,
         Turma.edicao_id == active_edicao
     ).all()

    alunos_map = defaultdict(lambda: {
        'nome_completo': '', 
        'nome_de_guerra': '',
        'matricula': '',
        'turma': '', 
        'total_global_faltas': 0, 
        'disciplinas_risco': [],
        'max_gravidade': 0
    })

    for aluno_id, nome_completo, nome_de_guerra, matricula, turma_nome, materia, carga_total, faltas in stats_query:
        carga_total = carga_total or 1
        porcentagem = (faltas / carga_total) * 100
        
        status_materia = 'normal'
        nivel_gravidade = 0
        if porcentagem >= 30:
            status_materia = 'reprovado'
            nivel_gravidade = 2
        elif porcentagem >= 20: 
            status_materia = 'alerta'
            nivel_gravidade = 1
        
        data = alunos_map[aluno_id]
        if not data['nome_completo']:
            data['nome_completo'] = nome_completo
            data['nome_de_guerra'] = nome_de_guerra
            data['matricula'] = matricula
            data['turma'] = turma_nome
        
        data['total_global_faltas'] += faltas
        
        if status_materia in ['reprovado', 'alerta']:
            data['disciplinas_risco'].append({
                'materia': materia,
                'faltas': faltas,
                'limite': int(carga_total * 0.3), 
                'porcentagem': round(porcentagem, 1),
                'status': status_materia
            })
            if nivel_gravidade > data['max_gravidade']:
                data['max_gravidade'] = nivel_gravidade

    alunos_alertas = []
    for uid, data in alunos_map.items():
        if data['disciplinas_risco'] or data['total_global_faltas'] >= 5:
            gravidade_str = 'moderado'
            if data['max_gravidade'] == 2: gravidade_str = 'critico'
            elif data['max_gravidade'] == 1: gravidade_str = 'atencao'
            
            nome_display = data['nome_completo'] or data['nome_de_guerra'] or "Sem Nome"
            matricula_display = data['matricula'] or "N/D"

            alunos_alertas.append({
                'id': uid,
                'nome': nome_display,
                'matricula': matricula_display,
                'turma': data['turma'],
                'total_faltas': data['total_global_faltas'],
                'riscos': data['disciplinas_risco'], 
                'gravidade': gravidade_str
            })

    alunos_alertas.sort(key=lambda x: ({'critico': 0, 'atencao': 1, 'moderado': 2}[x['gravidade']], -x['total_faltas']))

    # =========================================================================
    # PARTE 2: LÓGICA DA LISTA DE DIÁRIOS OPTIMIZADA
    # =========================================================================
    page = request.args.get('page', 1, type=int)
    turma_id = request.args.get('turma_id', type=int)
    disciplina_id = request.args.get('disciplina_id', type=int)
    data_str = request.args.get('data')
    status_diario = request.args.get('status_diario')

    per_page = 20

    # Convertemos a data antes para enviar o filtro direto se o Service aceitar,
    # ou filtramos minimamente se necessário.
    data_filtro = None
    if data_str:
        try:
            data_filtro = datetime.strptime(data_str, '%Y-%m-%d').date()
        except ValueError:
            pass

    # Ajustamos para trazer apenas os itens da PÁGINA ATUAL direto do banco,
    # em vez de trazer 10.000 registros para a RAM.
    # NOTA: Se o seu DiarioService permitir passar 'data' ou já fizer paginação real por lá,
    # use os parâmetros reais. Se não permitir, usamos uma busca menor (ex: 100 ou 200 itens max por vez)
    resultado_service = DiarioService.get_diarios_pendentes(
        school_id=school_id,
        user_id=None, 
        turma_id=turma_id,
        disciplina_id=disciplina_id,
        status=status_diario,
        data_aula=data_filtro,
        page=page,         
        per_page=per_page
    )

    diarios_paginados = resultado_service.items
    total_items = resultado_service.total
        
    class FakePagination:
        def __init__(self, items, page, per_page, total):
            self.items = items
            self.page = page
            self.per_page = per_page
            self.total = total
            self.pages = (total + per_page - 1) // per_page if per_page > 0 else 0
            self.has_prev = page > 1
            self.has_next = page < self.pages
            self.prev_num = page - 1
            self.next_num = page + 1

    pagination = FakePagination(diarios_paginados, page, per_page, total_items)
    
    turmas, disciplinas = DiarioService.get_filtros_disponiveis(school_id, user_id=None, turma_selected_id=turma_id)

    # OTIMIZAÇÃO DOS ALUNOS: Trazemos apenas as colunas textuais exatas que vamos usar
    # Isso impede o SQLAlchemy de instanciar objetos "vivos" pesados de Aluno/User na RAM
    todos_alunos_query = db.session.execute(
        select(Aluno.id, Turma.nome, User.nome_completo, User.nome_de_guerra, User.matricula)
        .join(Turma)
        .join(User, Aluno.user_id == User.id)
        .where(
            Turma.school_id == school_id,
            Turma.edicao_id == active_edicao
        )
        .order_by(Turma.nome, User.nome_completo)
    ).all()

    todos_alunos_json = []
    for row in todos_alunos_query:
        aluno_id, t_nome, u_nome, u_guerra, u_matricula = row
        nome_display = u_nome or u_guerra or "Sem Nome"
        matricula_display = u_matricula or "N/D"

        todos_alunos_json.append({
            'id': aluno_id,
            'nome': nome_display,
            'matricula': matricula_display,
            'turma': t_nome,
            'faltas': alunos_map[aluno_id]['total_global_faltas'] if aluno_id in alunos_map else 0
        })

    return render_template(
        'admin/espelho_diarios.html', 
        alunos_alertas=alunos_alertas,
        todos_alunos=todos_alunos_json,
        diarios=diarios_paginados,
        pagination=pagination,
        turmas=turmas,
        disciplinas=disciplinas,
        turma_id=turma_id,
        disciplina_id=disciplina_id,
        data_selecionada=data_str,
        status_diario=status_diario
    )

@admin_escola_bp.route('/detalhe-faltas/<int:aluno_id>')
@login_required
@sens_permission_required
def detalhe_faltas_aluno(aluno_id):
    aluno = db.session.scalar(
        select(Aluno)
        .options(joinedload(Aluno.user), joinedload(Aluno.turma))
        .where(Aluno.id == aluno_id)
    )
    if not aluno:
        return "Aluno não encontrado", 404

    school_id = UserService.get_current_school_id()

    faltas_query = db.session.scalars(
        select(FrequenciaAluno)
        .join(DiarioClasse, FrequenciaAluno.diario_id == DiarioClasse.id)
        .join(Turma, DiarioClasse.turma_id == Turma.id)
        .join(Disciplina, DiarioClasse.disciplina_id == Disciplina.id)
        .where(
            FrequenciaAluno.aluno_id == aluno_id, 
            FrequenciaAluno.presente == False,
            DiarioClasse.is_deleted == False,
            Turma.school_id == school_id 
        )
        .order_by(Disciplina.materia, DiarioClasse.data_aula.desc())
    ).unique().all()
    
    disciplinas_map = {}
    for f in faltas_query:
        disc = f.diario.disciplina
        if disc.id not in disciplinas_map:
            disciplinas_map[disc.id] = {
                'nome': disc.materia,
                'carga_horaria': disc.carga_horaria_prevista or 1,
                'total_faltas': 0,
                'dias': []
            }
        
        disciplinas_map[disc.id]['total_faltas'] += 1
        disciplinas_map[disc.id]['dias'].append({
            'data': f.diario.data_aula.strftime('%d/%m/%Y'),
            'justificativa': f.justificativa or "Sem justificativa",
            'id': f.id
        })

    resumo_final = []
    for d_id, data in disciplinas_map.items():
        percentual = (data['total_faltas'] / data['carga_horaria']) * 100
        status = 'success'
        if percentual >= 30: status = 'danger'
        elif percentual >= 20: status = 'warning'
        
        resumo_final.append({
            'disciplina': data['nome'],
            'total_faltas': data['total_faltas'],
            'limite_reprovacao': int(data['carga_horaria'] * 0.3),
            'percentual': round(percentual, 1),
            'status': status,
            'dias': data['dias']
        })
    
    resumo_final.sort(key=lambda x: x['percentual'], reverse=True)
    return render_template('admin/partials/_detalhe_dia_modal.html', aluno=aluno, resumo=resumo_final)

@admin_escola_bp.route('/editar-diario-bloco/<int:diario_id>', methods=['GET', 'POST'])
@login_required
@sens_permission_required
def editar_diario_bloco(diario_id):
    ref_diario = db.session.get(DiarioClasse, diario_id)
    if not ref_diario:
        flash('Diário não encontrado', 'danger')
        return redirect(url_for('admin_escola.espelho_diarios'))

    diarios_bloco = db.session.scalars(
        select(DiarioClasse)
        .where(
            DiarioClasse.turma_id == ref_diario.turma_id,
            DiarioClasse.disciplina_id == ref_diario.disciplina_id,
            DiarioClasse.data_aula == ref_diario.data_aula
        )
        .order_by(DiarioClasse.periodo, DiarioClasse.id) 
    ).all()

    alunos = db.session.scalars(
        select(Aluno)
        .join(User)
        .where(Aluno.turma_id == ref_diario.turma_id)
        .order_by(Aluno.num_aluno, User.nome_de_guerra)
    ).all()

    if request.method == 'POST':
        conteudo = request.form.get('conteudo')
        observacoes = request.form.get('observacoes')

        try:
            for diario in diarios_bloco:
                diario.conteudo_ministrado = conteudo
                diario.observacoes = observacoes
                
                for aluno in alunos:
                    campo_name = f"presenca_{aluno.id}_{diario.id}"
                    esta_presente = (request.form.get(campo_name) == 'on')

                    freq = db.session.scalar(
                        select(FrequenciaAluno).where(
                            FrequenciaAluno.diario_id == diario.id,
                            FrequenciaAluno.aluno_id == aluno.id
                        )
                    )

                    if not freq:
                        freq = FrequenciaAluno(diario_id=diario.id, aluno_id=aluno.id)
                        db.session.add(freq)
                    
                    freq.presente = esta_presente
                    if esta_presente:
                        freq.justificativa = None
            
            db.session.commit()
            flash('Diário de classe atualizado com sucesso!', 'success')
            return redirect(url_for('admin_escola.espelho_diarios'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao salvar: {str(e)}', 'danger')

    return render_template(
        'admin/editar_diario_bloco.html',
        ref=ref_diario,
        diarios=diarios_bloco,
        alunos=alunos
    )

@admin_escola_bp.route('/retornar-diario', methods=['POST'])
@login_required
@sens_permission_required
def retornar_diario():
    diario_id = request.form.get('diario_id')
    motivo = request.form.get('motivo_devolucao')
    
    if not diario_id or not motivo:
        flash("Dados inválidos para retorno.", "danger")
        return redirect(url_for('admin_escola.espelho_diarios'))
    
    sucesso, msg = DiarioService.retornar_diario_admin(diario_id, current_user, motivo)
    if sucesso:
        flash(msg, "success")
    else:
        flash(msg, "danger")
        
    return redirect(url_for('admin_escola.espelho_diarios'))


@admin_escola_bp.route('/excluir-diario/<int:diario_id>', methods=['POST'])
@login_required
@sens_permission_required
def excluir_diario(diario_id):
    """
    Rota para o administrador excluir permanentemente um diário (e suas frequências em cascata).
    """
    sucesso, msg = DiarioService.excluir_diario_admin(diario_id, current_user)
    
    if sucesso:
        flash(msg, "success")
    else:
        flash(msg, "danger")
        
    return redirect(url_for('admin_escola.espelho_diarios'))

@admin_escola_bp.route('/forcar-criacao-diario', methods=['POST'])
@login_required
@sens_permission_required
def forcar_criacao_diario():
    """
    MODO MASTER: Força a criação de um diário para que apareça para o Aluno e/ou Instrutor
    """
    school_id = UserService.get_current_school_id()
    admin_id = current_user.id
    
    turma_id = request.form.get('turma_id')
    disciplina_id = request.form.get('disciplina_id')
    data_aula = request.form.get('data_aula')
    periodos = request.form.getlist('periodos')

    if not all([turma_id, disciplina_id, data_aula, periodos]):
        flash("Preencha todos os campos e selecione ao menos um período para forçar a criação.", "warning")
        return redirect(url_for('admin_escola.espelho_diarios'))

    ok, msg = DiarioService.forcar_criacao_diario_manual(
        school_id=school_id,
        admin_id=admin_id,
        turma_id=turma_id,
        disciplina_id=disciplina_id,
        data_aula_str=data_aula,
        periodos=periodos
    )

    if ok:
        flash(msg, "success")
    else:
        flash(msg, "danger")

    return redirect(url_for('admin_escola.espelho_diarios'))

@admin_escola_bp.route('/imprimir-relatorio')
@login_required
@sens_permission_required
def imprimir_relatorio():
    school_id = UserService.get_current_school_id()
    turma_id = request.args.get('turma_id', type=int)
    disciplina_id = request.args.get('disciplina_id', type=int)
    
    if not turma_id or not disciplina_id:
        flash("Para gerar o Relatório Oficial, selecione Turma e Disciplina nos filtros.", "warning")
        return redirect(url_for('admin_escola.espelho_diarios'))

    turma = db.session.get(Turma, turma_id)
    disciplina = db.session.get(Disciplina, disciplina_id)
    
    diarios = DiarioService.get_diarios_agrupados(
        school_id=school_id,
        user_id=None, 
        turma_id=turma_id,
        disciplina_id=disciplina_id,
        status=None 
    )
    
    total_aulas = sum(d.total_aulas_bloco for d in diarios)
    
    return render_template(
        'admin/relatorio_impressao.html',
        school=db.session.get(School, school_id),
        turma=turma,
        disciplina=disciplina,
        diarios=diarios,
        total_aulas=total_aulas,
        data_emissao=datetime.now()
    )

