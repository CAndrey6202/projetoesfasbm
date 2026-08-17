from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session, Response, current_app, send_file
from flask_login import login_required, current_user
from sqlalchemy import select, or_, desc, and_
from sqlalchemy.orm import joinedload
from datetime import date, datetime, timedelta
from flask_wtf import FlaskForm
from wtforms import HiddenField, SubmitField
from wtforms.validators import DataRequired
from weasyprint import HTML
from urllib.parse import quote
import json
import traceback
import uuid
import io

from ..models.database import db
from ..models.background_job import BackgroundJob
from ..models.horario import Horario
from ..models.disciplina import Disciplina
from ..models.instrutor import Instrutor
from ..models.disciplina_turma import DisciplinaTurma
from ..models.semana import Semana
from ..models.turma import Turma
from ..models.ciclo import Ciclo
from ..models.user import User
from ..services.site_config_service import SiteConfigService
from utils.decorators import admin_or_programmer_required, can_schedule_classes_required
from ..services.horario_service import HorarioService
from ..services.user_service import UserService
from ..services.turma_service import TurmaService
from ..services.semana_service import SemanaService
from ..services.instrutor_service import InstrutorService
from ..services.log_service import LogService # <--- ESPIÃO IMPORTADO AQUI

horario_bp = Blueprint('horario', __name__, url_prefix='/horario')

class AprovarHorarioForm(FlaskForm):
    horario_id = HiddenField('Horário ID', validators=[DataRequired()])
    action = HiddenField('Ação', validators=[DataRequired()])
    submit = SubmitField('Enviar')

def _get_horario_context_data():
    school_id = UserService.get_current_school_id()

    tempos = []
    for i in range(1, 16):
        key = f"horario_periodo_{i:02d}"
        periodo_str = f"{i}º"
        time_str = SiteConfigService.get_config(key, 'N/D', school_id=school_id)
        tempos.append((periodo_str, time_str))

    # --- LÓGICA DIRETA: LER A POSIÇÃO CONFIGURADA PELO GESTOR NO CUSTOMIZER ---
    try:
        pos_int_1 = int(float(SiteConfigService.get_config('posicao_intervalo_manha', '3', school_id=school_id)))
    except (ValueError, TypeError):
        pos_int_1 = 3
        
    try:
        pos_almoco = int(float(SiteConfigService.get_config('posicao_intervalo_almoco', '6', school_id=school_id)))
    except (ValueError, TypeError):
        pos_almoco = 6
        
    try:
        pos_int_2 = int(float(SiteConfigService.get_config('posicao_intervalo_tarde', '9', school_id=school_id)))
    except (ValueError, TypeError):
        pos_int_2 = 9
    # -------------------------------------------------------------------------

    intervalos = {
        'intervalo_1': SiteConfigService.get_config('horario_intervalo_manha', 'N/D', school_id=school_id),
        'pos_int_1': pos_int_1,
        'almoco': SiteConfigService.get_config('horario_intervalo_almoco', 'N/D', school_id=school_id),
        'pos_almoco': pos_almoco,
        'intervalo_2': SiteConfigService.get_config('horario_intervalo_tarde', 'N/D', school_id=school_id),
        'pos_int_2': pos_int_2,
    }
    return tempos, intervalos


def assegurar_materia_disposicao(school_id, active_edicao, ciclo_id, turma_obj):
    try:
        # 1. Procura ou cria o usuário dummy para o C Al / S Ens
        dummy_user = db.session.execute(
            select(User).where(User.username == 'c_al_s_ens')
        ).scalar_one_or_none()
        
        if not dummy_user:
            dummy_user = User(
                matricula='C_AL_S_ENS',
                username='c_al_s_ens',
                email='c_al_s_ens@escola.com.br',
                role='instrutor',
                is_active=False,
                nome_de_guerra='C Al / S Ens'
            )
            db.session.add(dummy_user)
            db.session.flush()
            
        # 2. Procura ou cria o instrutor dummy para a escola atual
        dummy_instrutor = db.session.execute(
            select(Instrutor).where(
                Instrutor.user_id == dummy_user.id,
                Instrutor.school_id == school_id
            )
        ).scalar_one_or_none()
        
        if not dummy_instrutor:
            dummy_instrutor = Instrutor(
                user_id=dummy_user.id,
                school_id=school_id
            )
            db.session.add(dummy_instrutor)
            db.session.flush()
            
        # 3. Procura ou cria a disciplina para a turma atual
        # NOTA: Não filtramos pelo ciclo_id no WHERE porque a constraint _materia_turma_uc é única para (materia, turma_id)
        disciplina = db.session.execute(
            select(Disciplina).where(
                Disciplina.materia == 'A disposição do C Al /S Ens',
                Disciplina.turma_id == turma_obj.id
            )
        ).scalar_one_or_none()
        
        if not disciplina:
            disciplina = Disciplina(
                materia='A disposição do C Al /S Ens',
                carga_horaria_prevista=0,
                carga_horaria_cumprida=0,
                turma_id=turma_obj.id,
                ciclo_id=ciclo_id
            )
            db.session.add(disciplina)
            db.session.flush()
            
        # 4. Procura ou cria a associação de disciplina e instrutor (vínculo)
        vinculo = db.session.execute(
            select(DisciplinaTurma).where(
                DisciplinaTurma.disciplina_id == disciplina.id,
                DisciplinaTurma.pelotao == turma_obj.nome
            )
        ).scalar_one_or_none()
        
        if not vinculo:
            vinculo = DisciplinaTurma(
                disciplina_id=disciplina.id,
                pelotao=turma_obj.nome,
                instrutor_id_1=dummy_instrutor.id
            )
            db.session.add(vinculo)
            db.session.flush()
        elif not vinculo.instrutor_id_1:
            vinculo.instrutor_id_1 = dummy_instrutor.id
            db.session.flush()
            
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        raise e


@horario_bp.route('/')
@login_required
def index():
    school_id = UserService.get_current_school_id()
    local_role = current_user.get_role_in_school(school_id) if school_id else None

    if (local_role == 'aluno') or (current_user.role == 'aluno' and not current_user.is_staff):
        if not current_user.aluno_profile or not current_user.aluno_profile.turma:
            flash("Você não está matriculado em nenhuma turma.", 'warning')
            return redirect(url_for('main.dashboard'))
        turma_do_aluno = current_user.aluno_profile.turma
        school_id = turma_do_aluno.school_id
        active_edicao = turma_do_aluno.edicao_id
        turma_selecionada_nome = turma_do_aluno.nome
        todas_as_turmas = [turma_do_aluno]
    else:
        school_id = UserService.get_current_school_id()
        if not school_id:
            flash("Nenhuma escola selecionada.", "warning")
            return redirect(url_for('main.dashboard'))

        active_edicao = session.get('active_edicao_id')
        todas_as_turmas = TurmaService.get_turmas_by_school(school_id, active_edicao)

        if not current_user.is_staff:
            todas_as_turmas = []
            my_instrutor_ids = db.session.scalars(
                select(Instrutor.id).where(Instrutor.user_id == current_user.id)
            ).all()

            if my_instrutor_ids:
                try:
                    turmas_vinculadas = db.session.scalars(
                        select(Turma)
                        .join(Disciplina, Disciplina.turma_id == Turma.id)
                        .join(DisciplinaTurma, DisciplinaTurma.disciplina_id == Disciplina.id)
                        .where(
                            Turma.school_id == school_id,
                            Turma.edicao_id == active_edicao,
                            or_(
                                DisciplinaTurma.instrutor_id_1.in_(my_instrutor_ids),
                                DisciplinaTurma.instrutor_id_2.in_(my_instrutor_ids)
                            )
                        )
                        .distinct()
                        .order_by(Turma.nome)
                    ).all()

                    todas_as_turmas = list(turmas_vinculadas)
                except Exception as e:
                    current_app.logger.error(f"Erro ao filtrar turmas do instrutor: {e}")
                    pass

        turma_selecionada_nome = request.args.get('pelotao', session.get('ultima_turma_visualizada'))

        if not turma_selecionada_nome and todas_as_turmas:
            turma_selecionada_nome = todas_as_turmas[0].nome
        elif turma_selecionada_nome and turma_selecionada_nome not in [t.nome for t in todas_as_turmas]:
             turma_selecionada_nome = todas_as_turmas[0].nome if todas_as_turmas else None

    turma_atual_obj = None
    if turma_selecionada_nome:
        turma_atual_obj = db.session.scalar(select(Turma).where(Turma.nome == turma_selecionada_nome, Turma.school_id == school_id, Turma.edicao_id == active_edicao))

    ciclo_selecionado_id = request.args.get('ciclo', session.get('ultimo_ciclo_horario'), type=int)

    ciclos = db.session.scalars(
        select(Ciclo).where(
            Ciclo.school_id == school_id, 
            or_(Ciclo.edicao_id == active_edicao, Ciclo.edicao_id == None)
        ).order_by(Ciclo.nome)
    ).all()

    if not ciclo_selecionado_id or ciclo_selecionado_id not in [c.id for c in ciclos]:
        ciclo_selecionado_id = ciclos[0].id if ciclos else None

    session['ultimo_ciclo_horario'] = ciclo_selecionado_id

    todas_as_semanas = []
    if ciclo_selecionado_id:
        todas_as_semanas = db.session.scalars(
            select(Semana)
            .where(Semana.ciclo_id == ciclo_selecionado_id)
            .order_by(Semana.data_inicio.desc())
        ).all()

    semana_id = request.args.get('semana_id', type=int)
    semana_selecionada = SemanaService.get_semana_selecionada(semana_id, ciclo_selecionado_id, override_school_id=school_id, override_edicao_id=active_edicao)

    horario_matrix = None
    datas_semana = {}
    if turma_selecionada_nome and semana_selecionada:
        # Garante a existência da matéria e instrutor dummy para período livre
        if school_id and active_edicao and ciclo_selecionado_id and turma_atual_obj:
            try:
                assegurar_materia_disposicao(school_id, active_edicao, ciclo_selecionado_id, turma_atual_obj)
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Erro ao assegurar materia disposicao: {e}")

        session['ultima_turma_visualizada'] = turma_selecionada_nome
        horario_matrix = HorarioService.construir_matriz_horario(turma_selecionada_nome, semana_selecionada.id, current_user)
        datas_semana = HorarioService.get_datas_da_semana(semana_selecionada)

    can_schedule_in_this_turma = False
    instrutor_turmas_vinculadas = []
    priority_active = False
    priority_allowed_names = []
    all_materias_names = []

    if school_id:
        try:
            all_materias_names = db.session.scalars(
                select(Disciplina.materia)
                .join(Turma)
                .where(Turma.school_id == school_id, Turma.edicao_id == active_edicao)
                .distinct()
                .order_by(Disciplina.materia)
            ).all()
        except Exception:
            all_materias_names = []

    if semana_selecionada:
        priority_active = getattr(semana_selecionada, 'priority_active', False)
        try:
            priority_allowed_names = json.loads(getattr(semana_selecionada, 'priority_disciplines', '[]') or '[]')
        except:
            priority_allowed_names = []

        if current_user.is_sens or current_user.is_admin_escola:
            can_schedule_in_this_turma = True
        else:
            my_instrutor_ids = db.session.scalars(
                select(Instrutor.id).where(Instrutor.user_id == current_user.id)
            ).all()

            if my_instrutor_ids:
                instrutor_turmas_vinculadas = db.session.scalars(
                    select(Turma)
                    .join(Disciplina, Disciplina.turma_id == Turma.id)
                    .join(DisciplinaTurma, DisciplinaTurma.disciplina_id == Disciplina.id)
                    .where(
                        Turma.school_id == school_id,
                        Turma.edicao_id == active_edicao,
                        or_(
                            DisciplinaTurma.instrutor_id_1.in_(my_instrutor_ids),
                            DisciplinaTurma.instrutor_id_2.in_(my_instrutor_ids)
                        )
                    )
                    .distinct()
                    .order_by(Turma.nome)
                ).all()

                if any(t.nome == turma_selecionada_nome for t in instrutor_turmas_vinculadas):
                    if not priority_active:
                        can_schedule_in_this_turma = True
                    else:
                        if priority_allowed_names:
                            query_match = select(DisciplinaTurma)\
                                .join(Disciplina, DisciplinaTurma.disciplina_id == Disciplina.id)\
                                .join(Turma, Disciplina.turma_id == Turma.id)\
                                .where(
                                    Turma.nome == turma_selecionada_nome,
                                    Disciplina.materia.in_(priority_allowed_names),
                                    or_(
                                        DisciplinaTurma.instrutor_id_1.in_(my_instrutor_ids),
                                        DisciplinaTurma.instrutor_id_2.in_(my_instrutor_ids)
                                    )
                                )
                            if db.session.execute(query_match).first():
                                can_schedule_in_this_turma = True

    tempos, intervalos = _get_horario_context_data()
    all_disciplinas = []

    return render_template('quadro_horario.html',
                           horario_matrix=horario_matrix,
                           pelotao_selecionado=turma_selecionada_nome,
                           turma_atual=turma_atual_obj,
                           semana_selecionada=semana_selecionada,
                           todas_as_turmas=todas_as_turmas,
                           todas_as_semanas=todas_as_semanas,
                           ciclos=ciclos,
                           ciclo_selecionado=ciclo_selecionado_id,
                           datas_semana=datas_semana,
                           can_schedule_in_this_turma=can_schedule_in_this_turma,
                           instrutor_turmas_vinculadas=instrutor_turmas_vinculadas,
                           tempos=tempos,
                           intervalos=intervalos,
                           all_disciplinas=all_disciplinas,
                           priority_active=priority_active,
                           priority_allowed_names=priority_allowed_names,
                           all_materias_names=all_materias_names)

@horario_bp.route('/dashboard-instrutor', methods=['GET'])
@login_required
def dashboard_instrutor():
    try:
        school_id = UserService.get_current_school_id()

        if not current_user.is_instrutor_in_school(school_id) and not current_user.is_admin_escola:
            return "Acesso negado: Você não é instrutor nesta escola.", 403

        instrutor_ids = db.session.scalars(
            select(Instrutor.id).where(Instrutor.user_id == current_user.id)
        ).all()
        if not instrutor_ids:
            return "Perfil de instrutor não encontrado.", 404
        instrutor = db.session.scalar(select(Instrutor).where(Instrutor.id.in_(instrutor_ids)))

        todas_aulas = db.session.scalars(
            select(Horario)
            .join(Disciplina, Horario.disciplina_id == Disciplina.id)
            .join(Semana, Horario.semana_id == Semana.id)
            .join(Ciclo, Semana.ciclo_id == Ciclo.id)
            .options(joinedload(Horario.semana), joinedload(Horario.disciplina))
            .where(
                Ciclo.school_id == school_id,
                or_(Horario.instrutor_id.in_(instrutor_ids), Horario.instrutor_id_2.in_(instrutor_ids))
            )
            .order_by(desc(Semana.data_inicio), Horario.dia_semana, Horario.periodo)
        ).unique().all()

        hoje = date.today()
        aulas_passadas = []
        aulas_futuras = []

        total_ministrados = 0
        total_futuros = 0
        stats_disciplinas = {}

        mapa_dias = {
            'segunda': 0, 'terca': 1, 'quarta': 2,
            'quinta': 3, 'sexta': 4, 'sabado': 5, 'domingo': 6,
            'terça': 1, 'sábado': 5
        }

        for aula in todas_aulas:
            try:
                dia_lower = str(aula.dia_semana).lower().replace('-feira', '').strip() if aula.dia_semana else ''
                delta_dias = mapa_dias.get(dia_lower, 0)
                if aula.semana and aula.semana.data_inicio:
                    data_real = aula.semana.data_inicio + timedelta(days=delta_dias)
                else:
                    data_real = hoje
            except:
                data_real = hoje

            lista_tempos = [str(p) for p in range(aula.periodo, aula.periodo + aula.duracao)]
            tempos_str = ", ".join(lista_tempos)
            qtd = aula.duracao

            nome_materia = getattr(aula.disciplina, 'materia', 'Disciplina sem nome')

            info = {
                'id': aula.id,
                'data': data_real,
                'dia_semana': aula.dia_semana,
                'tempos': tempos_str,
                'disciplina': nome_materia,
                'turma': aula.pelotao,
                'sala': 'Sala de Aula',
                'qtd': qtd,
                'is_auxiliar': (aula.instrutor_id_2 in instrutor_ids)
            }

            if nome_materia not in stats_disciplinas:
                stats_disciplinas[nome_materia] = 0
            stats_disciplinas[nome_materia] += qtd

            if data_real < hoje:
                aulas_passadas.append(info)
                total_ministrados += qtd
            else:
                aulas_futuras.append(info)
                total_futuros += qtd

        aulas_futuras.sort(key=lambda x: x['data'])

        return render_template(
            'horario/dashboard_instrutor_content.html',
            instrutor=instrutor,
            aulas_passadas=aulas_passadas,
            aulas_futuras=aulas_futuras,
            total_ministrados=total_ministrados,
            total_futuros=total_futuros,
            stats_disciplinas=stats_disciplinas,
            hoje=hoje
        )

    except Exception as e:
        print(traceback.format_exc())
        return f"ERRO INTERNO: {str(e)}", 500

@horario_bp.route('/save-priority-config', methods=['POST'])
@login_required
@admin_or_programmer_required
def save_priority_config():
    return jsonify({'success': False, 'message': 'Use a rota /semana/<id>/salvar-prioridade'}), 404

# ==========================================
# ROTA RESTAURADA DO PDF
# ==========================================
@horario_bp.route('/exportar-pdf')
@login_required
@admin_or_programmer_required
def exportar_pdf():
    pelotao = request.args.get('pelotao')
    semana_id = request.args.get('semana_id', type=int)
    if not pelotao or not semana_id:
        flash('Parâmetros inválidos.', 'danger')
        return redirect(url_for('horario.index'))
    semana = db.session.get(Semana, semana_id)

    active_school = UserService.get_current_school_id()
    if not semana or (active_school and semana.ciclo.school_id != active_school):
        flash('Semana não encontrada ou permissão negada.', 'danger')
        return redirect(url_for('horario.index'))

    horario_matrix = HorarioService.construir_matriz_horario(pelotao, semana_id, current_user)
    datas_semana = HorarioService.get_datas_da_semana(semana)
    tempos, intervalos = _get_horario_context_data()
    
    rendered_html = render_template('horario_pdf.html', 
                                    pelotao_selecionado=pelotao, 
                                    semana_selecionada=semana, 
                                    horario_matrix=horario_matrix, 
                                    datas_semana=datas_semana,
                                    tempos=tempos,
                                    intervalos=intervalos)
    try:
        semana_nome = semana.nome.replace(' ', '_').replace('/', '-').replace('\\', '-') if (semana and semana.nome) else 'semana'
        for char in [':', '*', '?', '"', '<', '>', '|']:
            semana_nome = semana_nome.replace(char, '')
        pdf_filename = f"quadro_horario_{pelotao.replace(' ', '_')}_{semana_nome}.pdf"
        job_id = str(uuid.uuid4())
        job = BackgroundJob(
            id=job_id,
            task_type='generate_pdf',
            payload=rendered_html,
            meta_data=json.dumps({"filename": pdf_filename}),
            user_id=current_user.id
        )
        db.session.add(job)
        db.session.commit()
        
        return jsonify({'success': True, 'job_id': job_id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})


# ==========================================
# NOVA ROTA EXCLUSIVA PARA EXCEL
# ==========================================
@horario_bp.route('/exportar-excel')
@login_required
@admin_or_programmer_required
def exportar_excel():
    pelotao = request.args.get('pelotao')
    semana_id = request.args.get('semana_id', type=int)
    if not pelotao or not semana_id:
        flash('Parâmetros inválidos.', 'danger')
        return redirect(url_for('horario.index'))
        
    semana = db.session.get(Semana, semana_id)
    active_school = UserService.get_current_school_id()
    
    if not semana or (active_school and semana.ciclo.school_id != active_school):
        flash('Semana não encontrada ou permissão negada.', 'danger')
        return redirect(url_for('horario.index'))

    horario_matrix = HorarioService.construir_matriz_horario(pelotao, semana_id, current_user)
    datas_semana = HorarioService.get_datas_da_semana(semana)
    tempos, intervalos = _get_horario_context_data()
    
    try:
        from ..services.xlsx_service import gerar_quadro_horario_xlsx
        
        xlsx_bytes = gerar_quadro_horario_xlsx(
            pelotao=pelotao,
            semana=semana,
            horario_matrix=horario_matrix,
            datas_semana=datas_semana,
            tempos=tempos,
            intervalos=intervalos
        )
        
        semana_nome = semana.nome.replace(' ', '_').replace('/', '-').replace('\\', '-') if (semana and semana.nome) else 'semana'
        for char in [':', '*', '?', '"', '<', '>', '|']:
            semana_nome = semana_nome.replace(char, '')
        filename = f"quadro_horario_{pelotao.replace(' ', '_')}_{semana_nome}.xlsx"
        
        return send_file(
            io.BytesIO(xlsx_bytes),
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except Exception as e:
        current_app.logger.error(f"Erro ao gerar Excel: {str(e)}\n{traceback.format_exc()}")
        flash(f'Erro ao gerar documento Excel: {str(e)}', 'danger')
        return redirect(url_for('horario.index'))


@horario_bp.route('/editar/<path:pelotao>/<int:semana_id>/<int:ciclo_id>')
@login_required
@can_schedule_classes_required
def editar_horario_grid(pelotao, semana_id, ciclo_id):
    semana = db.session.get(Semana, semana_id)
    active_school = UserService.get_current_school_id()
    if not semana or (active_school and semana.ciclo.school_id != active_school):
        flash("Semana não encontrada.", "danger")
        return redirect(url_for('horario.index'))

    # Garante a existência da matéria e instrutor dummy para período livre no modo de edição
    active_edicao = semana.ciclo.edicao_id if (semana and semana.ciclo) else None
    if active_school and active_edicao:
        turma_obj = db.session.scalar(select(Turma).where(Turma.nome == pelotao, Turma.school_id == active_school, Turma.edicao_id == active_edicao))
        if turma_obj:
            try:
                assegurar_materia_disposicao(active_school, active_edicao, ciclo_id, turma_obj)
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Erro ao assegurar materia disposicao no edit: {e}")

    context_data = HorarioService.get_edit_grid_context(pelotao, semana_id, ciclo_id, current_user)
    if not context_data.get('success'):
        flash(context_data.get('message', 'Erro ao carregar dados.'), 'danger')
        return redirect(url_for('horario.index'))
    tempos, intervalos = _get_horario_context_data()
    context_data['tempos'] = tempos
    context_data['intervalos'] = intervalos
    return render_template('editar_quadro_horario.html', **context_data)

@horario_bp.route('/get-aula/<int:horario_id>')
@login_required
def get_aula_details(horario_id):
    aula_details = HorarioService.get_aula_details(horario_id, current_user)
    if not aula_details:
        return jsonify({'success': False, 'message': 'Aula não encontrada.'}), 404
    return jsonify({'success': True, **aula_details})

@horario_bp.route('/api/instrutores-vinculados/<path:pelotao>/<int:disciplina_id>')
@login_required
def get_instrutores_vinculados(pelotao, disciplina_id):
    school_id = UserService.get_current_school_id()
    if not school_id:
        return jsonify([])

    # Busca o vínculo validando a escola e a turma exata
    vinculo = db.session.scalar(
        select(DisciplinaTurma)
        .join(Disciplina, DisciplinaTurma.disciplina_id == Disciplina.id)
        .join(Turma, Disciplina.turma_id == Turma.id)
        .options(
            joinedload(DisciplinaTurma.instrutor_1).joinedload(Instrutor.user),
            joinedload(DisciplinaTurma.instrutor_2).joinedload(Instrutor.user)
        )
        .where(
            DisciplinaTurma.disciplina_id == disciplina_id,
            Turma.school_id == school_id,
            Turma.nome == pelotao  # Validação extra com o parâmetro da URL
        )
    )
    
    if not vinculo: return jsonify([])

    opcoes = []
    
    # LÓGICA CORRIGIDA: Se tiver os 2, manda SÓ a opção combinada. 
    # Caso contrário, manda só quem estiver preenchido.
    if vinculo.instrutor_1 and vinculo.instrutor_2:
        id_combinado = f"{vinculo.instrutor_1.id}-{vinculo.instrutor_2.id}"
        
        posto1 = vinculo.instrutor_1.user.posto_graduacao or ''
        nome1 = vinculo.instrutor_1.user.nome_de_guerra or vinculo.instrutor_1.user.username
        
        posto2 = vinculo.instrutor_2.user.posto_graduacao or ''
        nome2 = vinculo.instrutor_2.user.nome_de_guerra or vinculo.instrutor_2.user.username
        
        nome_combinado = f"{posto1} {nome1} e {posto2} {nome2}".strip()
        opcoes.append({'id': id_combinado, 'nome': nome_combinado})
        
    elif vinculo.instrutor_1:
        posto = vinculo.instrutor_1.user.posto_graduacao or ''
        nome_guerra = vinculo.instrutor_1.user.nome_de_guerra or vinculo.instrutor_1.user.username
        opcoes.append({'id': vinculo.instrutor_1.id, 'nome': f"{posto} {nome_guerra}".strip()})
        
    elif vinculo.instrutor_2:
        posto = vinculo.instrutor_2.user.posto_graduacao or ''
        nome_guerra = vinculo.instrutor_2.user.nome_de_guerra or vinculo.instrutor_2.user.username
        opcoes.append({'id': vinculo.instrutor_2.id, 'nome': f"{posto} {nome_guerra}".strip()})

    return jsonify(opcoes)

@horario_bp.route('/salvar-aula', methods=['POST'])
@login_required
def salvar_aula():
    data = request.json
    success, message, status_code = HorarioService.save_aula(data, current_user)
    
    # --- ESPIÃO: SALVAR/EDITAR AULA ---
    if success:
        school_id = UserService.get_current_school_id()
        LogService.log(
            action="Salvou Aula no Horário",
            details=f"O usuário modificou ou inseriu uma aula no quadro horário. Sistema: {message}",
            school_id=school_id
        )
    # ----------------------------------
    
    return jsonify({'success': success, 'message': message}), status_code

@horario_bp.route('/remover-aula', methods=['POST'])
@login_required
def remover_aula():
    data = request.json
    horario_id = data.get('horario_id')
    success, message = HorarioService.remove_aula(horario_id, current_user)
    
    # --- ESPIÃO: REMOVER AULA ---
    if success:
        school_id = UserService.get_current_school_id()
        LogService.log(
            action="Removeu Aula do Horário",
            details=f"O usuário removeu a aula de ID {horario_id} da grade horária.",
            school_id=school_id
        )
        return jsonify({'success': True, 'message': message})
    # ----------------------------
    else: 
        return jsonify({'success': False, 'message': message}), 403

@horario_bp.route('/aprovar', methods=['GET', 'POST'])
@login_required
@admin_or_programmer_required
def aprovar_horarios():
    form = AprovarHorarioForm()
    if form.validate_on_submit():
        horario_id = form.horario_id.data
        action = form.action.data
        success, message = HorarioService.aprovar_horario(horario_id, action)
        
        # --- ESPIÃO: APROVAÇÃO/REJEIÇÃO DE HORÁRIO ---
        if success:
            school_id = UserService.get_current_school_id()
            LogService.log(
                action=f"Revisão de Horário: {action}",
                details=f"O gestor aplicou a ação '{action}' no horário pendente ID {horario_id}. Resultado: {message}",
                school_id=school_id
            )
        # ---------------------------------------------
        
        flash(message, 'success' if success else 'danger')
        return redirect(request.referrer or url_for('horario.aprovar_horarios'))

    aulas_pendentes = HorarioService.get_aulas_pendentes_agrupadas()
    return render_template('aprovar_horarios.html', aulas_pendentes=aulas_pendentes, form=form)


@horario_bp.route('/aprovar-parcial', methods=['POST'])
@login_required
@admin_or_programmer_required
def aprovar_parcial():
    data = request.json
    horario_id = data.get('horario_id')
    periodos = [int(p) for p in data.get('periodos', [])]

    success, message = HorarioService.aprovar_horario_parcialmente(horario_id, periodos)

    if success:
        # --- ESPIÃO: APROVAÇÃO PARCIAL ---
        school_id = UserService.get_current_school_id()
        LogService.log(
            action="Aprovação Parcial de Horário",
            details=f"O gestor aprovou parcialmente o horário ID {horario_id} para os períodos {periodos}.",
            school_id=school_id
        )
        # ---------------------------------
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'success': False, 'message': message}), 400


# ==============================================================================
# ROTA RESTAURADA: PRÓXIMAS AULAS E HISTÓRICO (ADMIN ESCOLA) - COM DELEGAÇÃO AO SERVICE
# ==============================================================================
@horario_bp.route('/proximas_aulas_admin')
@login_required
@admin_or_programmer_required
def proximas_aulas_admin():
    school_id = UserService.get_current_school_id()
    if not school_id:
        flash("Nenhuma escola selecionada.", "warning")
        return redirect(url_for('main.dashboard'))

    # CORREÇÃO: Pegar a edição ativa ANTES da query de ciclos para não dar UnboundLocalError
    active_edicao = session.get('active_edicao_id')

    # Para buscar o histórico, precisamos obrigatoriamente de um ciclo.
    ciclos = db.session.scalars(
        select(Ciclo).where(
            Ciclo.school_id == school_id, 
            or_(Ciclo.edicao_id == active_edicao, Ciclo.edicao_id == None)
        ).order_by(Ciclo.nome)
    ).all()
    
    ciclo_selecionado_id = request.args.get('ciclo', session.get('ultimo_ciclo_horario'), type=int)
    if not ciclo_selecionado_id or ciclo_selecionado_id not in [c.id for c in ciclos]:
        ciclo_selecionado_id = ciclos[0].id if ciclos else None
        
    session['ultimo_ciclo_horario'] = ciclo_selecionado_id

    # Parâmetros de Filtro - Agora usando turma_nome em vez de disciplina_id
    instrutor_id = request.args.get('instrutor_id', type=int)
    turma_nome = request.args.get('turma_nome')

    # 1. Buscar todos os instrutores para o Select
    instrutores_paginados = InstrutorService.get_all_instrutores_sem_paginacao(current_user)
    instrutores_formatados = []
    lista_instrutores = instrutores_paginados if isinstance(instrutores_paginados, list) else getattr(instrutores_paginados, 'items', [])
    
    for i in lista_instrutores:
        if i.user:
            posto = i.user.posto_graduacao or ''
            nome = i.user.nome_de_guerra or i.user.username
            instrutores_formatados.append({
                "id": i.id, 
                "nome": f"{posto} {nome}".strip()
            })

    # 2. Buscar todas as Turmas da Escola para o Select
    turmas_banco = db.session.scalars(
        select(Turma)
        .where(
            Turma.school_id == school_id,
            Turma.edicao_id == active_edicao
        )
        .order_by(Turma.nome)
    ).all()
    
    turmas_formatadas = []
    for t in turmas_banco:
        turmas_formatadas.append({
            "id": t.nome, # O banco usa o nome da turma na tabela Horario
            "nome": t.nome
        })

    # 3. Contexto de Vínculos (Para o Painel HTML)
    info_vinculos = None
    if instrutor_id:
        vinculos_banco = db.session.scalars(
            select(DisciplinaTurma)
            .join(Disciplina, DisciplinaTurma.disciplina_id == Disciplina.id)
            .join(Turma, Disciplina.turma_id == Turma.id)
            .options(joinedload(DisciplinaTurma.disciplina))
            .where(
                Turma.school_id == school_id,
                Turma.edicao_id == active_edicao,
                or_(
                    DisciplinaTurma.instrutor_id_1 == instrutor_id,
                    DisciplinaTurma.instrutor_id_2 == instrutor_id
                )
            )
        ).all()
        
        agrupado_instrutor = {}
        for v in vinculos_banco:
            if v.disciplina:
                if v.pelotao not in agrupado_instrutor:
                    agrupado_instrutor[v.pelotao] = []
                agrupado_instrutor[v.pelotao].append(v.disciplina.materia)
        
        if agrupado_instrutor:
            info_vinculos = {'tipo': 'instrutor', 'dados': agrupado_instrutor}
            
    elif turma_nome:
        vinculos_banco = db.session.scalars(
            select(DisciplinaTurma)
            .join(Disciplina, DisciplinaTurma.disciplina_id == Disciplina.id)
            .join(Turma, Disciplina.turma_id == Turma.id)
            .options(
                joinedload(DisciplinaTurma.disciplina),
                joinedload(DisciplinaTurma.instrutor_1).joinedload(Instrutor.user),
                joinedload(DisciplinaTurma.instrutor_2).joinedload(Instrutor.user)
            )
            .where(
                Turma.school_id == school_id,
                Turma.nome == turma_nome
            )
        ).all()
        
        lista_disc = []
        for v in vinculos_banco:
            instrutores_v = []
            if v.instrutor_1 and v.instrutor_1.user:
                posto = v.instrutor_1.user.posto_graduacao or ''
                nome = v.instrutor_1.user.nome_de_guerra or v.instrutor_1.user.username
                instrutores_v.append(f"{posto} {nome}".strip())
            
            if v.instrutor_2 and v.instrutor_2.user:
                posto = v.instrutor_2.user.posto_graduacao or ''
                nome = v.instrutor_2.user.nome_de_guerra or v.instrutor_2.user.username
                instrutores_v.append(f"{posto} {nome}".strip())
            
            lista_disc.append({
                'disciplina': getattr(v.disciplina, 'materia', 'N/D'),
                'instrutores': " / ".join(instrutores_v) if instrutores_v else "Nenhum instrutor vinculado"
            })
        
        if lista_disc:
            info_vinculos = {'tipo': 'turma', 'turma_nome': turma_nome, 'dados': lista_disc}

    # 4. Obter as aulas do Service (Retorna agrupado e traduzido: ['futuras'] e ['passadas'])
    aulas_dict = HorarioService.get_aulas_painel_admin(school_id, ciclo_selecionado_id, instrutor_id=instrutor_id, turma_nome=turma_nome)

    # 5. Mapeia para renderizar no template que criamos
    return render_template(
        'horario/proximas_aulas_admin.html',
        aulas=aulas_dict['futuras'],
        aulas_passadas=aulas_dict['passadas'],
        instrutores=instrutores_formatados,
        turmas=turmas_formatadas,
        instrutor_selecionado=instrutor_id,
        turma_selecionada=turma_nome,
        info_vinculos=info_vinculos,
        ciclos=ciclos,
        ciclo_selecionado=ciclo_selecionado_id
    )
