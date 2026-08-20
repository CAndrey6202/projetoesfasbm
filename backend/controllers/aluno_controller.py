from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_required, current_user
from sqlalchemy import select, or_, and_
from sqlalchemy.orm import joinedload
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, SubmitField
from wtforms.validators import DataRequired, Optional, Email
import json

from ..models.database import db
from ..services.aluno_service import AlunoService
from ..services.turma_service import TurmaService
from ..models.user import User
from ..models.aluno import Aluno
from ..models.turma import Turma
from ..models.school import School
from ..models.user_school import UserSchool
from ..models.disciplina_turma import DisciplinaTurma
from ..models.instrutor import Instrutor
from ..models.avaliacao_instrutor import CampanhaAvaliacao, RespostaAvaliacao, RespostaAvaliacaoGeral, ControlePreenchimentoAvaliacao
import uuid
from ..services.user_service import UserService # Importante para resolver escola
from ..services.log_service import LogService # <--- ESPIO IMPORTADO AQUI
from utils.decorators import admin_or_programmer_required, school_admin_or_programmer_required, can_view_management_pages_required

aluno_bp = Blueprint('aluno', __name__, url_prefix='/aluno')

# DICIONRIO ESTRUTURADO PARA POSTOS E GRADUAES
posto_graduacao_structured = {
    'Praas': ['Soldado PM', '2º Sargento PM', '1º Sargento PM', 'Aluno Oficial'],
    'Oficiais': ['1º Tenente PM', 'Capito PM', 'Major PM', 'Tenente-Coronel PM', 'Coronel PM'],
    'Sade - Enfermagem': ['Ten Enf', 'Cap Enf', 'Maj Enf', 'Ten Cel Enf', 'Cel Enf'],
    'Sade - Mdicos': ['Ten Med', 'Cap Med', 'Maj Med', 'Ten Cel Med', 'Cel Med'],
    'Outros': ['Civil', 'Outro']
}

class DeleteForm(FlaskForm):
    pass

class EditAlunoForm(FlaskForm):
    nome_completo = StringField('Nome Completo', validators=[DataRequired()])
    email = StringField('E-mail', validators=[DataRequired(), Email()])
    matricula = StringField('Matrcula', render_kw={"readonly": True})

    posto_categoria = SelectField("Categoria", choices=list(posto_graduacao_structured.keys()), validators=[DataRequired()])
    posto_graduacao = SelectField('Posto/Graduao', validators=[DataRequired()])
    posto_graduacao_outro = StringField("Outro (especifique)", validators=[Optional()])

    opm = StringField('OPM', validators=[DataRequired()])
    turma_id = SelectField('Turma / Peloto', coerce=int, validators=[DataRequired()])
    funcao_atual = SelectField('Funo Atual', choices=[
        ('', '-- Nenhuma funo --'), ('P1', 'P1'), ('P2', 'P2'), ('P3', 'P3'), ('P4', 'P4'), ('P5', 'P5'),
        ('Aux Disc', 'Aux Disc'), ('Aux Cia', 'Aux Cia'), ('Aux Pel', 'Aux Pel'), ('C1', 'C1'), ('C2', 'C2'),
        ('C3', 'C3'), ('C4', 'C4'), ('C5', 'C5'), ('Formatura', 'Formatura'), ('Obras', 'Obras'),
        ('Atletismo', 'Atletismo'), ('Jubileu', 'Jubileu'), ('Dia da Criana', 'Dia da Criana'),
        ('Seminrio', 'Seminrio'), ('Chefe de Turma', 'Chefe de Turma'), ('Correio', 'Correio'),
        ('Cmt 1° GPM', 'Cmt 1° GPM'), ('Cmt 2° GPM', 'Cmt 2° GPM'), ('Cmt 3° GPM', 'Cmt 3° GPM'),
        ('Socorrista 1', 'Socorrista 1'), ('Socorrista 2', 'Socorrista 2'), ('Motorista 1', 'Motorista 1'),
        ('Motorista 2', 'Motorista 2'), ('Telefonista 1', 'Telefonista 1'), ('Telefonista 2', 'Telefonista 2')
    ], validators=[Optional()])
    submit = SubmitField('Atualizar Perfil')

@aluno_bp.route('/listar')
@login_required
@can_view_management_pages_required
def listar_alunos():
    delete_form = DeleteForm()
    turma_filtrada = request.args.get('turma', None)
    page = request.args.get('page', 1, type=int)
    search_term = request.args.get('q', None)

    # 1. Garante ID da Escola
    school_id = session.get('active_school_id') or UserService.get_current_school_id()
    if not school_id:
        flash('Nenhuma escola associada ou selecionada.', 'danger')
        return redirect(url_for('main.dashboard'))

    # 2. QUERY BLINDADA
    query = db.session.query(Aluno).select_from(Aluno).join(User).join(
        UserSchool, Aluno.user_id == UserSchool.user_id
    ).outerjoin(Turma).options(
        joinedload(Aluno.turma),
        joinedload(Aluno.user)
    ).filter(
        UserSchool.school_id == school_id,
        UserSchool.role == 'aluno'
    )

    # 3. Filtrar pela Edio Ativa + MOSTRAR OS TRANSFERIDOS (rfos da Escola)
    active_edicao_id = session.get('active_edicao_id')
    if active_edicao_id:
        query = query.filter(
            or_(
                Turma.edicao_id == active_edicao_id,
                Aluno.edicao_id == active_edicao_id,
                and_(Aluno.edicao_id == None, Aluno.turma_id == None)
            )
        )

    # Filtros
    if search_term:
        term = f"%{search_term}%"
        query = query.filter(
            or_(
                User.nome_completo.ilike(term),
                User.matricula.ilike(term),
                User.nome_de_guerra.ilike(term)
            )
        )

    if turma_filtrada:
        if turma_filtrada.isdigit():
             query = query.filter(Aluno.turma_id == int(turma_filtrada))
        elif turma_filtrada.lower() == 'sem turma':
             query = query.filter(Aluno.turma_id == None)
        else:
             query = query.filter(Turma.nome == turma_filtrada)

    # Paginao
    alunos_paginados = query.order_by(User.nome_completo).paginate(page=page, per_page=15, error_out=False)

    # Carrega turmas para o filtro (Respeitando a edio)
    active_edicao = session.get('active_edicao_id')
    turmas = TurmaService.get_turmas_by_school(school_id, active_edicao)

    return render_template(
        'listar_alunos.html',
        alunos_paginados=alunos_paginados,
        turmas=turmas,
        turma_filtrada=turma_filtrada,
        delete_form=delete_form,
        search_term=search_term
    )

@aluno_bp.route('/editar/<int:aluno_id>', methods=['GET', 'POST'])
@login_required
@school_admin_or_programmer_required
def editar_aluno(aluno_id):
    school_id = session.get('active_school_id') or UserService.get_current_school_id()
    if not school_id:
        flash('Nenhuma escola associada.', 'danger')
        return redirect(url_for('aluno.listar_alunos'))

    # Busca segura garantindo escola
    aluno = db.session.query(Aluno).select_from(Aluno).join(User).join(
        UserSchool, Aluno.user_id == UserSchool.user_id
    ).filter(
        Aluno.id == aluno_id,
        UserSchool.school_id == school_id
    ).first()

    if not aluno:
        flash("Aluno no encontrado nesta escola.", 'danger')
        return redirect(url_for('aluno.listar_alunos'))

    form = EditAlunoForm(obj=aluno)

    # Carrega turmas apenas da escola atual e da edio atual
    active_edicao = session.get('active_edicao_id')
    turmas = TurmaService.get_turmas_by_school(school_id, active_edicao)
    # Adiciona opo "Sem Turma"
    turma_choices = [(0, '-- Selecione --')] + [(t.id, t.nome) for t in turmas]
    form.turma_id.choices = turma_choices

    if request.method == 'GET':
        if aluno.user:
            form.nome_completo.data = aluno.user.nome_completo
            form.email.data = aluno.user.email
            form.matricula.data = aluno.user.matricula

            # Lgica de Posto/Graduao
            posto_atual = aluno.user.posto_graduacao
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

        form.opm.data = aluno.opm
        form.turma_id.data = aluno.turma_id if aluno.turma_id else 0

    # Atualizao dinmica de choices no POST
    if form.is_submitted():
         categoria_selecionada = form.posto_categoria.data
         if categoria_selecionada in posto_graduacao_structured:
             form.posto_graduacao.choices = [(p, p) for p in posto_graduacao_structured[categoria_selecionada]]

    if form.validate_on_submit():
        # Lgica de Salvamento Manual para garantir controle
        try:
            # User Info
            aluno.user.nome_completo = form.nome_completo.data
            aluno.user.email = form.email.data

            # Posto
            cat = form.posto_categoria.data
            grad = form.posto_graduacao.data
            if cat == 'Outros' and grad == 'Outro':
                aluno.user.posto_graduacao = form.posto_graduacao_outro.data
            else:
                aluno.user.posto_graduacao = grad

            # Aluno Info (INCLUINDO VNCULO DA EDIO APS A TRANSFERNCIA)
            aluno.opm = form.opm.data
            t_id = form.turma_id.data
            
            if t_id and t_id != 0:
                aluno.turma_id = t_id
                # Puxa o edicao_id da turma e atribui ao aluno para finalizar a transferncia
                turma_selecionada = db.session.get(Turma, t_id)
                if turma_selecionada:
                    aluno.edicao_id = turma_selecionada.edicao_id
            else:
                aluno.turma_id = None

            aluno.funcao_atual = form.funcao_atual.data if form.funcao_atual.data else None

            db.session.commit()
            
            # --- ESPIO: EDIO DE ALUNO ---
            LogService.log(
                action="Editou Perfil do Aluno",
                details=f"Atualizou os dados do aluno {aluno.user.nome_completo} (Matrcula: {aluno.user.matricula}).",
                school_id=school_id
            )
            # -------------------------------
            
            flash('Aluno atualizado com sucesso!', 'success')
            return redirect(url_for('aluno.listar_alunos'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao atualizar: {str(e)}', 'danger')

    return render_template('editar_aluno.html', aluno=aluno, form=form, postos_data=posto_graduacao_structured)

@aluno_bp.route('/editar/<int:aluno_id>/funcao', methods=['POST'])
@login_required
@school_admin_or_programmer_required
def editar_funcao_aluno(aluno_id):
    success, message = AlunoService.update_funcao_aluno(aluno_id, request.form)
    
    # --- ESPIO: ALTERAO DE FUNO ---
    if success:
        school_id = session.get('active_school_id') or UserService.get_current_school_id()
        LogService.log(
            action="Alterou Funo do Aluno",
            details=f"Aluno ID {aluno_id}: {message}",
            school_id=school_id
        )
    # -----------------------------------

    flash(message, 'success' if success else 'danger')
    return redirect(url_for('aluno.editar_aluno', aluno_id=aluno_id))

@aluno_bp.route('/excluir/<int:aluno_id>', methods=['POST'])
@login_required
@school_admin_or_programmer_required
def excluir_aluno(aluno_id):
    form = DeleteForm()
    if form.validate_on_submit():
        school_id = session.get('active_school_id') or UserService.get_current_school_id()
        if not school_id:
             flash('Erro de escola.', 'danger')
             return redirect(url_for('aluno.listar_alunos'))

        try:
            # Busca o aluno garantindo que pertence à escola ativa
            aluno = db.session.query(Aluno).select_from(Aluno).join(
                UserSchool, Aluno.user_id == UserSchool.user_id
            ).filter(
                Aluno.id == aluno_id,
                UserSchool.school_id == school_id
            ).first()

            if aluno:
                current_user_id = aluno.user_id
                # Salva os dados antes de apagar do banco
                nome_aluno_removido = aluno.user.nome_completo or "Sem Nome"
                matricula_aluno_removida = aluno.user.matricula or "Sem Matrcula"
                
                # --- INCIO DO SOFT DELETE ---
                # Em vez de apagar o aluno e o UserSchool, apenas alteramos o status
                aluno.status_matricula = 'Desligado'
                
                # Desvincula a role de 'aluno' mudando para 'aluno_desligado' para que no aparea nas listas da escola
                user_school = db.session.query(UserSchool).filter_by(user_id=current_user_id, school_id=school_id).first()
                if user_school:
                    user_school.role = 'aluno_desligado'
                
                db.session.commit()
                # --- FIM DO SOFT DELETE ---
                
                # --- LOG DE SEGURANA ---
                LogService.log(
                    action="Removeu Aluno da Escola (Soft Delete)",
                    details=f"O aluno {nome_aluno_removido} (Matrcula: {matricula_aluno_removida}) teve seu status alterado para Desligado.",
                    school_id=school_id
                )
                
                flash('Aluno removido da escola com sucesso (histrico preservado).', 'success')
            else:
                flash('Aluno no encontrado nesta escola.', 'danger')

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Erro ao excluir aluno: {str(e)}")
            flash(f'Erro ao excluir: {str(e)}', 'danger')
    else:
        flash('Falha CSRF.', 'danger')
        
    return redirect(url_for('aluno.listar_alunos'))

# --- AVALIAO DE INSTRUTORES ---

@aluno_bp.route('/responder-avaliacao/<int:id>', methods=['GET', 'POST'])
@login_required
def responder_avaliacao(id):
    school_id = session.get('active_school_id')
    local_role = current_user.get_role_in_school(school_id) if school_id else None
    if str(current_user.role).lower().strip() != 'aluno' and local_role != 'aluno':
        flash('Acesso negado. Apenas alunos podem responder à avaliao.', 'danger')
        return redirect(url_for('dashboard.index'))
        
    campanha = db.session.get(CampanhaAvaliacao, id)
    if not campanha or not campanha.is_ativa:
        flash('Campanha inativa ou no encontrada.', 'danger')
        return redirect(url_for('dashboard.index'))
        
    aluno = db.session.query(Aluno).filter_by(user_id=current_user.id).first()
    if not aluno or not aluno.turma:
        flash('Turma no encontrada para o aluno.', 'danger')
        return redirect(url_for('dashboard.index'))
        
    if campanha.school_id != aluno.turma.school_id:
        flash('Esta campanha no pertence à sua escola.', 'danger')
        return redirect(url_for('dashboard.index'))
        
    # Verifica se já preencheu
    controle = db.session.query(ControlePreenchimentoAvaliacao).filter_by(
        campanha_id=campanha.id, 
        aluno_id=aluno.id
    ).first()
    if controle:
        flash('Você já respondeu a esta avaliao do mdulo. Obrigado!', 'success')
        return redirect(url_for('questionario.index'))
        
    # Buscar os instrutores da turma conectando com Disciplina
    from backend.models.disciplina import Disciplina
    
    disciplinas_da_turma = db.session.query(Disciplina).filter_by(turma_id=aluno.turma.id).all()
    disciplina_ids = [d.id for d in disciplinas_da_turma]
    
    vinculos = db.session.query(DisciplinaTurma).filter(DisciplinaTurma.disciplina_id.in_(disciplina_ids)).all()
    
    registros = []
    for v in vinculos:
        if v.instrutor_id_1:
            inst = db.session.query(Instrutor).get(v.instrutor_id_1)
            disc = db.session.query(Disciplina).get(v.disciplina_id)
                if inst: registros.append((inst, disc))
        if v.instrutor_id_2:
            inst = db.session.query(Instrutor).get(v.instrutor_id_2)
            disc = db.session.query(Disciplina).get(v.disciplina_id)
            if inst: registros.append((inst, disc))
            
    instrutores_para_avaliar = []
    for inst, disc in registros:
        nome_guerra = (inst.user.nome_de_guerra or "").lower()
        nome_completo = (inst.user.nome_completo or "").lower()
        materia = (disc.materia or "").lower()
        
        # Ignorar instrutores/disciplinas padrao (A disposicao, C_AL_S_ENS, etc)
        is_default = False
        if "c_al_s_ens" in nome_guerra or "c_al_s_ens" in nome_completo:
            is_default = True
        if "c al" in nome_guerra or "s ens" in nome_guerra or "sens" in nome_guerra:
            is_default = True
        if "disposi" in materia or "c_al" in materia:
            is_default = True
            
        if not is_default:
            instrutores_para_avaliar.append({
                'id': inst.id,
                'user': inst.user,
                'disciplina': disc
            })
            
    if request.method == 'POST':
        import uuid
        token = uuid.uuid4().hex[:12]
        
        # 1. Salvar Avaliao Geral
        try:
            resp_geral = RespostaAvaliacaoGeral(
                campanha_id=campanha.id,
                turma_id=aluno.turma.id,
                token_sigilo=token,
                nota_organizacao=int(request.form.get('nota_espaco_fisico', 3)),
                nota_tecnologia=int(request.form.get('nota_tecnologia', 3)),
                nota_corpo_alunos=int(request.form.get('nota_corpo_alunos', 3)),
                nota_direcao=int(request.form.get('nota_direcao', 3)),
                nota_satisfacao_geral=int(request.form.get('nota_satisfacao_geral', 3)),
                comentarios_gerais=request.form.get('comentarios_gerais')
            )
            db.session.add(resp_geral)
        except Exception as e:
            flash('Erro ao processar as notas gerais.', 'danger')
            return redirect(request.url)
            
        # 2. Salvar Avaliao dos Instrutores
        for instrutor_dict in instrutores_para_avaliar:
            inst_id = instrutor_dict['id']
            try:
                resp_inst = RespostaAvaliacao(
                    campanha_id=campanha.id,
                    instrutor_id=inst_id,
                    turma_id=aluno.turma.id,
                    token_sigilo=token,
                    nota_relacionamento=int(request.form.get(f'nota_relacionamento_{inst_id}', 3)),
                    nota_dominio=int(request.form.get(f'nota_dominio_{inst_id}', 3)),
                    nota_relevancia=int(request.form.get(f'nota_relevancia_{inst_id}', 3)),
                    comentario=request.form.get(f'comentario_{inst_id}')
                )
                db.session.add(resp_inst)
            except Exception as e:
                pass 

        # 3. Registrar que o aluno preencheu
        ctrl = ControlePreenchimentoAvaliacao(
            campanha_id=campanha.id,
            aluno_id=aluno.id
        )
        db.session.add(ctrl)
        
        db.session.commit()
        
        if 'bloqueio_avaliacao' in session:
            session.pop('bloqueio_avaliacao', None)
            session.pop('campanha_pendente_id', None)
            
        flash('Avaliação de Módulo enviada com sucesso! Muito obrigado pela sua contribuição anônima.', 'success')
        return redirect(url_for('questionario.index'))
        
    return render_template('questionario/responder_avaliacao_instrutores.html', 
                           campanha=campanha, 
                           instrutores=instrutores_para_avaliar,
                           aluno=aluno)


