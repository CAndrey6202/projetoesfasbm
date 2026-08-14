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
from ..models.avaliacao_instrutor import CampanhaAvaliacao, RespostaAvaliacao
from ..services.user_service import UserService # Importante para resolver escola
from ..services.log_service import LogService # <--- ESPIÃO IMPORTADO AQUI
from utils.decorators import admin_or_programmer_required, school_admin_or_programmer_required, can_view_management_pages_required

aluno_bp = Blueprint('aluno', __name__, url_prefix='/aluno')

# DICIONÁRIO ESTRUTURADO PARA POSTOS E GRADUAÇÕES
posto_graduacao_structured = {
    'Praças': ['Soldado PM', '2º Sargento PM', '1º Sargento PM', 'Aluno Oficial'],
    'Oficiais': ['1º Tenente PM', 'Capitão PM', 'Major PM', 'Tenente-Coronel PM', 'Coronel PM'],
    'Saúde - Enfermagem': ['Ten Enf', 'Cap Enf', 'Maj Enf', 'Ten Cel Enf', 'Cel Enf'],
    'Saúde - Médicos': ['Ten Med', 'Cap Med', 'Maj Med', 'Ten Cel Med', 'Cel Med'],
    'Outros': ['Civil', 'Outro']
}

class DeleteForm(FlaskForm):
    pass

class EditAlunoForm(FlaskForm):
    nome_completo = StringField('Nome Completo', validators=[DataRequired()])
    email = StringField('E-mail', validators=[DataRequired(), Email()])
    matricula = StringField('Matrícula', render_kw={"readonly": True})

    posto_categoria = SelectField("Categoria", choices=list(posto_graduacao_structured.keys()), validators=[DataRequired()])
    posto_graduacao = SelectField('Posto/Graduação', validators=[DataRequired()])
    posto_graduacao_outro = StringField("Outro (especifique)", validators=[Optional()])

    opm = StringField('OPM', validators=[DataRequired()])
    turma_id = SelectField('Turma / Pelotão', coerce=int, validators=[DataRequired()])
    funcao_atual = SelectField('Função Atual', choices=[
        ('', '-- Nenhuma função --'), ('P1', 'P1'), ('P2', 'P2'), ('P3', 'P3'), ('P4', 'P4'), ('P5', 'P5'),
        ('Aux Disc', 'Aux Disc'), ('Aux Cia', 'Aux Cia'), ('Aux Pel', 'Aux Pel'), ('C1', 'C1'), ('C2', 'C2'),
        ('C3', 'C3'), ('C4', 'C4'), ('C5', 'C5'), ('Formatura', 'Formatura'), ('Obras', 'Obras'),
        ('Atletismo', 'Atletismo'), ('Jubileu', 'Jubileu'), ('Dia da Criança', 'Dia da Criança'),
        ('Seminário', 'Seminário'), ('Chefe de Turma', 'Chefe de Turma'), ('Correio', 'Correio'),
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

    # 3. Filtrar pela Edição Ativa + MOSTRAR OS TRANSFERIDOS (Órfãos da Escola)
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

    # Paginação
    alunos_paginados = query.order_by(User.nome_completo).paginate(page=page, per_page=15, error_out=False)

    # Carrega turmas para o filtro (Respeitando a edição)
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
        flash("Aluno não encontrado nesta escola.", 'danger')
        return redirect(url_for('aluno.listar_alunos'))

    form = EditAlunoForm(obj=aluno)

    # Carrega turmas apenas da escola atual e da edição atual
    active_edicao = session.get('active_edicao_id')
    turmas = TurmaService.get_turmas_by_school(school_id, active_edicao)
    # Adiciona opção "Sem Turma"
    turma_choices = [(0, '-- Selecione --')] + [(t.id, t.nome) for t in turmas]
    form.turma_id.choices = turma_choices

    if request.method == 'GET':
        if aluno.user:
            form.nome_completo.data = aluno.user.nome_completo
            form.email.data = aluno.user.email
            form.matricula.data = aluno.user.matricula

            # Lógica de Posto/Graduação
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

    # Atualização dinâmica de choices no POST
    if form.is_submitted():
         categoria_selecionada = form.posto_categoria.data
         if categoria_selecionada in posto_graduacao_structured:
             form.posto_graduacao.choices = [(p, p) for p in posto_graduacao_structured[categoria_selecionada]]

    if form.validate_on_submit():
        # Lógica de Salvamento Manual para garantir controle
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

            # Aluno Info (INCLUINDO VÍNCULO DA EDIÇÃO APÓS A TRANSFERÊNCIA)
            aluno.opm = form.opm.data
            t_id = form.turma_id.data
            
            if t_id and t_id != 0:
                aluno.turma_id = t_id
                # Puxa o edicao_id da turma e atribui ao aluno para finalizar a transferência
                turma_selecionada = db.session.get(Turma, t_id)
                if turma_selecionada:
                    aluno.edicao_id = turma_selecionada.edicao_id
            else:
                aluno.turma_id = None

            aluno.funcao_atual = form.funcao_atual.data if form.funcao_atual.data else None

            db.session.commit()
            
            # --- ESPIÃO: EDIÇÃO DE ALUNO ---
            LogService.log(
                action="Editou Perfil do Aluno",
                details=f"Atualizou os dados do aluno {aluno.user.nome_completo} (Matrícula: {aluno.user.matricula}).",
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
    
    # --- ESPIÃO: ALTERAÇÃO DE FUNÇÃO ---
    if success:
        school_id = session.get('active_school_id') or UserService.get_current_school_id()
        LogService.log(
            action="Alterou Função do Aluno",
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
                matricula_aluno_removida = aluno.user.matricula or "Sem Matrícula"
                
                # --- INÍCIO DO SOFT DELETE ---
                # Em vez de apagar o aluno e o UserSchool, apenas alteramos o status
                aluno.status_matricula = 'Desligado'
                
                # Desvincula a role de 'aluno' mudando para 'aluno_desligado' para que não apareça nas listas da escola
                user_school = db.session.query(UserSchool).filter_by(user_id=current_user_id, school_id=school_id).first()
                if user_school:
                    user_school.role = 'aluno_desligado'
                
                db.session.commit()
                # --- FIM DO SOFT DELETE ---
                
                # --- LOG DE SEGURANÇA ---
                LogService.log(
                    action="Removeu Aluno da Escola (Soft Delete)",
                    details=f"O aluno {nome_aluno_removido} (Matrícula: {matricula_aluno_removida}) teve seu status alterado para Desligado.",
                    school_id=school_id
                )
                
                flash('Aluno removido da escola com sucesso (histórico preservado).', 'success')
            else:
                flash('Aluno não encontrado nesta escola.', 'danger')

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Erro ao excluir aluno: {str(e)}")
            flash(f'Erro ao excluir: {str(e)}', 'danger')
    else:
        flash('Falha CSRF.', 'danger')
        
    return redirect(url_for('aluno.listar_alunos'))

# --- AVALIAÇÃO DE INSTRUTORES ---

@aluno_bp.route('/responder-avaliacao/<int:id>', methods=['GET', 'POST'])
@login_required
def responder_avaliacao(id):
    if str(current_user.role).lower().strip() != 'aluno':
        flash('Acesso negado. Apenas alunos podem responder à avaliação.', 'danger')
        return redirect(url_for('dashboard.index'))
        
    campanha = db.session.get(CampanhaAvaliacao, id)
    if not campanha or not campanha.is_ativa:
        flash('Campanha inativa ou não encontrada.', 'danger')
        return redirect(url_for('dashboard.index'))
        
    aluno = db.session.query(Aluno).filter_by(user_id=current_user.id).first()
    if not aluno or not aluno.turma:
        flash('Turma não encontrada para o aluno.', 'danger')
        return redirect(url_for('dashboard.index'))
        
    # Ponto Crítico 3: Impedir vazamento de avaliações entre escolas
    if campanha.school_id != aluno.turma.school_id:
        flash('Esta campanha não pertence à sua escola.', 'danger')
        return redirect(url_for('dashboard.index'))
        
    instrutores_ids = set()
    
    # 1. Buscar via DisciplinaTurma
    vinculos = db.session.query(DisciplinaTurma).filter_by(pelotao=aluno.turma.nome).all()
    for v in vinculos:
        if v.instrutor_id_1: instrutores_ids.add(v.instrutor_id_1)
        if v.instrutor_id_2: instrutores_ids.add(v.instrutor_id_2)
            
    # 2. Buscar via Horario (pois às vezes o vínculo direto não está preenchido)
    from ..models.horario import Horario
    horarios = db.session.query(Horario).filter_by(pelotao=aluno.turma.nome).all()
    for h in horarios:
        if h.instrutor_id: instrutores_ids.add(h.instrutor_id)
        if h.instrutor_id_2: instrutores_ids.add(h.instrutor_id_2)
            
    if not instrutores_ids:
        flash('Nenhum instrutor alocado para a sua turma no momento.', 'warning')
        return redirect(url_for('dashboard.index'))
        
    # Obter os objetos Instrutor que o aluno deve avaliar, e que pertencem à escola do aluno
    instrutores_banco = db.session.query(Instrutor).filter(
        Instrutor.id.in_(instrutores_ids),
        Instrutor.school_id == aluno.turma.school_id
    ).all()
    
    # Filtrar instrutores padrão (C Al / S Ens) que não devem ser avaliados
    instrutores_para_avaliar = []
    for inst in instrutores_banco:
        nome_guerra = (inst.user.nome_de_guerra or "").lower()
        nome_completo = (inst.user.nome_completo or "").lower()
        if "c al" not in nome_guerra and "s ens" not in nome_guerra and "sens" not in nome_guerra and "c al" not in nome_completo and "s ens" not in nome_completo:
            instrutores_para_avaliar.append(inst)
    
    # Filtrar os instrutores que o aluno já avaliou nesta campanha
    respostas_existentes = db.session.query(RespostaAvaliacao.instrutor_id).filter_by(
        campanha_id=campanha.id, 
        aluno_id=aluno.id
    ).all()
    instrutores_ja_avaliados = {r[0] for r in respostas_existentes}
    
    instrutores_pendentes = [i for i in instrutores_para_avaliar if i.id not in instrutores_ja_avaliados]
    
    if not instrutores_pendentes:
        flash('Você já avaliou todos os instrutores da sua turma nesta campanha. Obrigado!', 'success')
        return redirect(url_for('questionario.index'))
        
    if request.method == 'POST':
        # O formulário pode enviar avaliação para múltiplos instrutores de uma vez
        todas_sucesso = True
        for instrutor in instrutores_pendentes:
            nota_str = request.form.get(f'nota_{instrutor.id}')
            comentario = request.form.get(f'comentario_{instrutor.id}')
            
            if nota_str:
                try:
                    nota = int(nota_str)
                    if 1 <= nota <= 5:
                        resposta = RespostaAvaliacao(
                            campanha_id=campanha.id,
                            aluno_id=aluno.id,
                            instrutor_id=instrutor.id,
                            turma_id=aluno.turma.id,
                            nota=nota,
                            comentario=comentario
                        )
                        db.session.add(resposta)
                except ValueError:
                    todas_sucesso = False
                    
        db.session.commit()
        if todas_sucesso:
            flash('Avaliações enviadas com sucesso!', 'success')
        else:
            flash('Avaliações enviadas, mas houve problemas com algumas notas.', 'warning')
        return redirect(url_for('questionario.index'))
        
    return render_template('questionario/responder_avaliacao_instrutores.html', 
                           campanha=campanha, 
                           instrutores=instrutores_pendentes)
