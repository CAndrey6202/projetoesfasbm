import os
from flask import current_app, url_for
from flask_login import current_user
from sqlalchemy import select, func, or_, and_
from sqlalchemy.orm import joinedload
from datetime import date, timedelta
from collections import defaultdict
import uuid
import json

from ..models.database import db
from ..models.horario import Horario
from ..models.disciplina import Disciplina
from ..models.instrutor import Instrutor
from ..models.disciplina_turma import DisciplinaTurma
from ..models.semana import Semana
from ..models.turma import Turma
from ..models.user import User
from ..models.ciclo import Ciclo
from ..models.school import School
from .notification_service import NotificationService
from .instrutor_service import InstrutorService
from .site_config_service import SiteConfigService
from .user_service import UserService


class HorarioService:

    @staticmethod
    def can_edit_horario(horario, user, preloaded_instrutor_ids=None):
        if not horario or not user:
            return False

        if user.is_sens or user.is_admin_escola:
            return True

        if preloaded_instrutor_ids is not None:
            my_instrutor_ids = preloaded_instrutor_ids
        else:
            # CORREÇÃO: Pegar apenas o ID de instrutor vinculado à escola atual
            school_id = UserService.get_current_school_id()
            my_instrutor_ids = db.session.scalars(
                select(Instrutor.id).where(
                    Instrutor.user_id == user.id,
                    Instrutor.school_id == school_id
                )
            ).all()

        if my_instrutor_ids:
            return (
                horario.instrutor_id in my_instrutor_ids or
                horario.instrutor_id_2 in my_instrutor_ids
            )
        return False

    @staticmethod
    def get_aula_details(horario_id, user):
        aula = db.session.get(Horario, int(horario_id))
        if not aula:
            return None

        if not HorarioService.can_edit_horario(aula, user):
            pass

        instrutor_val = str(aula.instrutor_id)
        if aula.instrutor_id_2:
            instrutor_val += f"-{aula.instrutor_id_2}"

        # Lógica corrigida para retornar a lista EXATA de períodos para o Javascript marcar
        periodos = []
        
        if aula.group_id:
            # Se for um grupo, busca todas as aulas do grupo e adiciona os períodos na lista
            aulas_grupo = db.session.scalars(
                select(Horario).where(Horario.group_id == aula.group_id).order_by(Horario.periodo)
            ).all()
            for a in aulas_grupo:
                for i in range(a.duracao):
                    periodos.append(a.periodo + i)
            # Para enviar dados legados também
            periodo_real = min(periodos) if periodos else aula.periodo
            duracao_real = len(periodos) if periodos else aula.duracao
        else:
            # Se não for grupo, adiciona apenas o período inicial e os próximos baseado na duração
            periodo_real = aula.periodo
            duracao_real = aula.duracao
            for i in range(aula.duracao):
                periodos.append(aula.periodo + i)

        return {
            'id': aula.id,
            'disciplina_id': aula.disciplina_id,
            'disciplina_nome': aula.disciplina.materia if aula.disciplina else "Desconhecida",
            'instrutor_id': instrutor_val,
            'instrutor_value': instrutor_val,  # Adicionado para ser lido no JS corretamente
            'observacao': aula.observacao,
            'duracao': duracao_real,
            'periodo': periodo_real,
            'periodos': periodos, # Nova lista de períodos explícita
            'dia': aula.dia_semana,
            'pelotao': aula.pelotao,
            'semana_id': aula.semana_id,
            'group_id': aula.group_id,
            'status': aula.status
        }

    @staticmethod
    def construir_matriz_horario(pelotao, semana_id, user):
        semana = db.session.get(Semana, semana_id)
        school_id = UserService.get_current_school_id()

        a_disposicao = {
            'materia': 'A disposição do C Al /S Ens',
            'instrutor': None,
            'duracao': 1,
            'is_disposicao': True,
            'id': None,
            'status': 'confirmado',
            'blocked': False
        }

        # Carrega os bloqueios ignorando divergências de maiúsculas/minúsculas
        blocked_dict = {}
        try:
            if getattr(semana, 'blocked_blocks', None):
                raw_dict = json.loads(semana.blocked_blocks)
                blocked_dict = {str(k).strip().upper(): v for k, v in raw_dict.items()}
        except Exception:
            pass
        
        pelotao_key = str(pelotao).strip().upper()
        blocked_for_pelotao = blocked_dict.get(pelotao_key, {})

        dias = ['segunda', 'terca', 'quarta', 'quinta', 'sexta', 'sabado', 'domingo']

        horario_matrix = []
        for p_idx in range(15):
            row = []
            for d_idx, dia_nome in enumerate(dias):
                p_real = p_idx + 1
                blocked_periods = [str(x) for x in blocked_for_pelotao.get(dia_nome, [])]
                is_blocked = str(p_real) in blocked_periods

                cell = dict(a_disposicao)
                cell['blocked'] = is_blocked
                row.append(cell)
            horario_matrix.append(row)

        # CORREÇÃO: Encontra as semanas que compartilham o mesmo período de data SOMENTE nesta escola
        semanas_sobrepostas = select(Semana.id).join(Ciclo).where(
            Semana.data_inicio == semana.data_inicio,
            Semana.data_fim == semana.data_fim,
            Ciclo.school_id == school_id
        )

        aulas_query = (
            select(Horario)
            .options(
                joinedload(Horario.disciplina),
                joinedload(Horario.instrutor).joinedload(Instrutor.user),
                joinedload(Horario.instrutor_2).joinedload(Instrutor.user),
            )
            .where(Horario.pelotao == pelotao, Horario.semana_id.in_(semanas_sobrepostas))
        )
        all_aulas = db.session.scalars(aulas_query).all()

        preloaded_instrutor_ids = []
        if user and not (user.is_sens or user.is_admin_escola):
            school_id = UserService.get_current_school_id()
            preloaded_instrutor_ids = db.session.scalars(
                select(Instrutor.id).where(
                    Instrutor.user_id == user.id,
                    Instrutor.school_id == school_id
                )
            ).all()

        for aula in all_aulas:
            try:
                dia_idx = dias.index(aula.dia_semana)
                periodo_idx = aula.periodo - 1

                can_see_pending_details = HorarioService.can_edit_horario(aula, user, preloaded_instrutor_ids)
                show_details = aula.status != 'pendente' or can_see_pending_details

                instrutores_display_list = []
                if aula.instrutor and aula.instrutor.user:
                    posto = aula.instrutor.user.posto_graduacao or ''
                    nome = aula.instrutor.user.nome_de_guerra or aula.instrutor.user.username
                    nome_completo = f"{posto} {nome}".strip()
                    instrutores_display_list.append(nome_completo)

                if aula.instrutor_2 and aula.instrutor_2.user:
                    posto = aula.instrutor_2.user.posto_graduacao or ''
                    nome = aula.instrutor_2.user.nome_de_guerra or aula.instrutor_2.user.username
                    nome_completo = f"{posto} {nome}".strip()
                    instrutores_display_list.append(nome_completo)

                instrutor_display = " / ".join(instrutores_display_list) if instrutores_display_list else "N/D"

                aula_is_blocked = str(aula.periodo) in [str(x) for x in blocked_for_pelotao.get(aula.dia_semana, [])]

                # Condição especial para Matéria de Disposição
                is_disposicao_materia = aula.disciplina and aula.disciplina.materia.strip().upper() == 'A DISPOSIÇÃO DO C AL /S ENS'

                aula_info = {
                    'id': aula.id,
                    'materia': 'A disposição do C Al /S Ens' if is_disposicao_materia else (aula.disciplina.materia if show_details else 'Aguardando Aprovação'),
                    'instrutor': None if is_disposicao_materia else (instrutor_display if show_details else None),
                    'observacao': aula.observacao,
                    'duracao': aula.duracao,
                    'status': 'confirmado' if is_disposicao_materia else aula.status,
                    'is_disposicao': True if is_disposicao_materia else False,
                    'can_edit': can_see_pending_details,
                    'is_continuation': False,
                    'group_id': aula.group_id,
                    'blocked': aula_is_blocked,
                    'raw_instrutor_id': aula.instrutor_id,
                    'raw_instrutor_id_2': aula.instrutor_id_2
                }

                if 0 <= periodo_idx < 15:
                    horario_matrix[periodo_idx][dia_idx] = aula_info
                    for i in range(1, aula.duracao):
                        if (periodo_idx + i) < 15:
                            horario_matrix[periodo_idx + i][dia_idx] = 'SKIP'
            except (ValueError, IndexError):
                continue
        return horario_matrix

    @staticmethod
    def get_semana_selecionada(semana_id_str, ciclo_id):
        if semana_id_str and str(semana_id_str).isdigit():
            return db.session.get(Semana, int(semana_id_str))

        today = date.today()
        semana_atual = db.session.scalars(
            select(Semana).where(
                Semana.ciclo_id == ciclo_id,
                Semana.data_inicio <= today,
                Semana.data_fim >= today
            )
        ).first()
        if semana_atual:
            return semana_atual

        return db.session.scalars(
            select(Semana)
            .where(Semana.ciclo_id == ciclo_id)
            .order_by(Semana.data_inicio.desc())
        ).first()

    @staticmethod
    def get_datas_da_semana(semana):
        if not semana:
            return {}
        datas = {}
        dias = ['segunda', 'terca', 'quarta', 'quinta', 'sexta', 'sabado', 'domingo']
        for i, dia_nome in enumerate(dias):
            datas[dia_nome] = (semana.data_inicio + timedelta(days=i)).strftime('%d/%m')
        return datas

    @staticmethod
    def get_edit_grid_context(pelotao, semana_id, ciclo_id, user):
        horario_matrix = HorarioService.construir_matriz_horario(pelotao, semana_id, user)
        semana = db.session.get(Semana, semana_id)

        is_admin = user.is_sens or user.is_admin_escola
        school_id = UserService.get_current_school_id() # CORREÇÃO

        def get_horas_agendadas(disciplina_id, pelotao_nome):
            return (
                db.session.scalar(
                    select(func.sum(Horario.duracao)).where(
                        Horario.disciplina_id == disciplina_id,
                        Horario.pelotao == pelotao_nome,
                    )
                )
                or 0
            )

        # CORREÇÃO: Buscar turma cruzando pelo school_id
        turma_obj = db.session.scalar(select(Turma).where(Turma.nome == pelotao, Turma.school_id == school_id))
        if not turma_obj:
            return {'success': False, 'message': 'Turma não encontrada.'}

        disciplinas_disponiveis = []
        if is_admin:
            disciplinas_da_turma = db.session.scalars(
                select(Disciplina)
                .where(Disciplina.turma_id == turma_obj.id)
                .order_by(Disciplina.materia)
            ).all()
            for d in disciplinas_da_turma:
                horas_restantes = d.carga_horaria_prevista - get_horas_agendadas(d.id, pelotao)
                disciplinas_disponiveis.append(
                    {"id": d.id, "nome": d.materia, "restantes": horas_restantes}
                )
        else:
            school_id = UserService.get_current_school_id()
            # CORREÇÃO: Limitar os vínculos de instrutor do usuário apenas para a escola atual
            my_instrutor_ids = db.session.scalars(
                select(Instrutor.id).where(
                    Instrutor.user_id == user.id,
                    Instrutor.school_id == school_id
                )
            ).all()

            if my_instrutor_ids:
                disciplinas_do_instrutor = db.session.scalars(
                    select(Disciplina)
                    .join(DisciplinaTurma, Disciplina.id == DisciplinaTurma.disciplina_id)
                    .where(
                        Disciplina.turma_id == turma_obj.id,
                        or_(
                            DisciplinaTurma.instrutor_id_1.in_(my_instrutor_ids),
                            DisciplinaTurma.instrutor_id_2.in_(my_instrutor_ids),
                        ),
                    )
                    .order_by(Disciplina.materia)
                ).all()
                for d in disciplinas_do_instrutor:
                    horas_restantes = d.carga_horaria_prevista - get_horas_agendadas(d.id, pelotao)
                    disciplinas_disponiveis.append(
                        {"id": d.id, "nome": d.materia, "restantes": horas_restantes}
                    )

        instrutores_paginados = InstrutorService.get_all_instrutores_sem_paginacao(user)
        todos_instrutores = []

        lista_instrutores = (
            instrutores_paginados
            if isinstance(instrutores_paginados, list)
            else instrutores_paginados.items
        )

        for i in lista_instrutores:
            posto = i.user.posto_graduacao or ''
            nome = i.user.nome_de_guerra or i.user.username
            todos_instrutores.append({"id": i.id, "nome": f"{posto} {nome}".strip()})

        instrutor_logado_id = None
        if not is_admin:
            # Já contendo trava por school_id
            my_instrutor_ids = db.session.scalars(
                select(Instrutor.id).where(
                    Instrutor.user_id == user.id,
                    Instrutor.school_id == school_id
                )
            ).all()
            if my_instrutor_ids:
                instrutor_logado_id = my_instrutor_ids[0]

        return {
            'success': True,
            'horario_matrix': horario_matrix,
            'pelotao_selecionado': pelotao,
            'semana_selecionada': semana,
            'disciplinas_disponiveis': disciplinas_disponiveis,
            'todos_instrutores': todos_instrutores,
            'is_admin': is_admin,
            'instrutor_logado_id': instrutor_logado_id,
            'datas_semana': HorarioService.get_datas_da_semana(semana),
        }

    @staticmethod
    def save_aula(data, user):
        try:
            is_admin = user.is_sens or user.is_admin_escola

            pelotao = data['pelotao']
            semana_id = int(data.get('semana_id', 0))
            disciplina_id = int(data.get('disciplina_id', 0))
            dia = data['dia']
            periodo_inicio = int(data['periodo'])
            duracao = int(data.get('duracao', 1))
            periodo_fim = periodo_inicio + duracao - 1
            observacao = data.get('observacao', '').strip() or None

            horario_id_raw = data.get('horario_id')
            horario_id = int(horario_id_raw) if horario_id_raw else None

            semana = db.session.get(Semana, semana_id)
            if not semana:
                return False, "Semana não encontrada.", 404

            # CORREÇÃO DE SEGURANÇA: Bloqueia injeção de ID de semanas de outras escolas
            school_id = UserService.get_current_school_id()
            if semana.ciclo.school_id != school_id:
                return False, "Acesso negado à semana desta escola.", 403
                
            disciplina = db.session.get(Disciplina, disciplina_id)
            if disciplina and disciplina.turma.school_id != school_id:
                return False, "Acesso negado à disciplina de outra escola.", 403

            # ==============================================================================
            # TRAVA ANTI-COLISÃO E CLONAGEM DIRETAMENTE NA SEMANA ATUAL
            # Isso resolve o bug onde o "duplo-clique" ou arrasto gerava aulas duplicadas.
            # Usamos o semana_id diretamente para não falhar caso as datas do ciclo estejam erradas.
            # ==============================================================================
            trava_query = select(Horario).where(
                Horario.pelotao == pelotao,
                Horario.semana_id == semana_id,
                Horario.dia_semana == dia,
                Horario.periodo <= periodo_fim,
                (Horario.periodo + Horario.duracao - 1) >= periodo_inicio
            )
            
            # Se for uma edição, ignora a própria aula e o seu grupo para não dar falso positivo
            if horario_id:
                aula_edit = db.session.get(Horario, horario_id)
                if aula_edit:
                    if aula_edit.group_id:
                        trava_query = trava_query.where(Horario.group_id != aula_edit.group_id)
                    else:
                        trava_query = trava_query.where(Horario.id != horario_id)

            colisao_direta = db.session.scalar(trava_query)
            if colisao_direta:
                nome_mat = colisao_direta.disciplina.materia if colisao_direta.disciplina else 'Outra Matéria'
                return False, f"⚠️ ERRO DE MARCAÇÃO: O {colisao_direta.periodo}º período na {dia.capitalize()} já está ocupado por '{nome_mat}'. Não é possível agendar por cima.", 409
            # ==============================================================================

            # CORREÇÃO: Limita sobreposição de semanas apenas à escola ativa
            semanas_sobrepostas = select(Semana.id).join(Ciclo).where(
                Semana.data_inicio == semana.data_inicio,
                Semana.data_fim == semana.data_fim,
                Ciclo.school_id == school_id
            )

            # Trava de Segurança lendo em MAIÚSCULO para evitar as falhas que ocorreram
            if not is_admin:
                blocked_dict = {}
                try:
                    if getattr(semana, 'blocked_blocks', None):
                        raw_dict = json.loads(semana.blocked_blocks)
                        blocked_dict = {str(k).strip().upper(): v for k, v in raw_dict.items()}
                except Exception:
                    pass
                
                pelotao_key = str(pelotao).strip().upper()
                blocked_for_pelotao = blocked_dict.get(pelotao_key, {})
                blocked_periods_for_day = [str(x) for x in blocked_for_pelotao.get(dia, [])]
                
                for p in range(periodo_inicio, periodo_fim + 1):
                    if str(p) in blocked_periods_for_day:
                        return False, f"⚠️ PERÍODO BLOQUEADO: O administrador bloqueou as marcações para o {p}º período na {dia.capitalize()}.", 403

            if dia == 'sabado' and not semana.mostrar_sabado:
                return False, "⚠️ AGENDAMENTO BLOQUEADO: O Sábado não está habilitado nesta semana.", 403

            if dia == 'domingo' and not semana.mostrar_domingo:
                return False, "⚠️ AGENDAMENTO BLOQUEADO: O Domingo não está habilitado nesta semana.", 403

            for p in range(periodo_inicio, periodo_fim + 1):
                if p == 13 and not semana.mostrar_periodo_13:
                    return False, "⚠️ AGENDAMENTO BLOQUEADO: O 13º tempo não está habilitado.", 403
                if p == 14 and not semana.mostrar_periodo_14:
                    return False, "⚠️ AGENDAMENTO BLOQUEADO: O 14º tempo não está habilitado.", 403
                if p == 15 and not semana.mostrar_periodo_15:
                    return False, "⚠️ AGENDAMENTO BLOQUEADO: O 15º tempo não está habilitado.", 403

                if dia == 'sabado' and semana.periodos_sabado > 0 and p > semana.periodos_sabado:
                    return False, f"⚠️ AGENDAMENTO BLOQUEADO: Sábado vai apenas até o {semana.periodos_sabado}º tempo.", 403

                if dia == 'domingo' and semana.periodos_domingo > 0 and p > semana.periodos_domingo:
                    return False, f"⚠️ AGENDAMENTO BLOQUEADO: Domingo vai apenas até o {semana.periodos_domingo}º tempo.", 403

            if disciplina:
                total_agendado = db.session.scalar(
                    select(func.sum(Horario.duracao))
                    .where(Horario.disciplina_id == disciplina_id, Horario.pelotao == pelotao)
                ) or 0

                if horario_id:
                    aula_atual_editando = db.session.get(Horario, horario_id)
                    if aula_atual_editando:
                        if aula_atual_editando.group_id:
                            total_grupo = db.session.scalar(
                                select(func.sum(Horario.duracao))
                                .where(Horario.group_id == aula_atual_editando.group_id)
                            ) or 0
                            total_agendado -= total_grupo
                        else:
                            total_agendado -= aula_atual_editando.duracao

                is_disposicao_materia = disciplina.materia.strip().upper() == 'A DISPOSIÇÃO DO C AL /S ENS'
                if not is_disposicao_materia and (total_agendado + duracao) > disciplina.carga_horaria_prevista:
                    restante = disciplina.carga_horaria_prevista - total_agendado
                    if restante < 0:
                        restante = 0
                    return False, (
                        f"⚠️ LIMITE EXCEDIDO: Faltam apenas {restante}h. "
                        f"Você tentou agendar {duracao}h."
                    ), 400

            if semana and not is_admin:
                if getattr(semana, 'priority_active', False):
                    raw_priority = getattr(semana, 'priority_disciplines', '[]') or '[]'
                    try:
                        allowed_names = json.loads(raw_priority)
                        if not isinstance(allowed_names, list):
                            allowed_names = []
                    except:
                        allowed_names = []

                    nome_disciplina_atual = disciplina.materia if disciplina else ""

                    if allowed_names and nome_disciplina_atual not in allowed_names:
                        return False, (
                            "⚠️ AGENDAMENTO BLOQUEADO: "
                            "Apenas disciplinas prioritárias podem agendar nesta semana."
                        ), 403

            instrutor_id_1, instrutor_id_2 = None, None

            if is_admin:
                instrutor_id_from_form = data.get('instrutor_id', '')
                if not instrutor_id_from_form:
                    return False, 'Como administrador, você deve selecionar um instrutor.', 400

                if '-' in str(instrutor_id_from_form):
                    id1, id2 = instrutor_id_from_form.split('-')
                    instrutor_id_1, instrutor_id_2 = int(id1), int(id2)
                else:
                    instrutor_id_1 = int(instrutor_id_from_form)

            else:
                my_instrutor_ids = db.session.scalars(
                    select(Instrutor.id).where(
                        Instrutor.user_id == user.id,
                        Instrutor.school_id == school_id
                    )
                ).all()

                if not my_instrutor_ids:
                    return False, 'Perfil de instrutor não encontrado.', 403

                vinculo = db.session.scalar(
                    select(DisciplinaTurma).where(
                        DisciplinaTurma.disciplina_id == disciplina_id,
                        or_(
                            DisciplinaTurma.instrutor_id_1.in_(my_instrutor_ids),
                            DisciplinaTurma.instrutor_id_2.in_(my_instrutor_ids)
                        )
                    )
                )

                if not vinculo:
                    return False, 'Você não tem vínculo com esta disciplina nesta turma.', 403

                if vinculo.instrutor_id_1 in my_instrutor_ids:
                    instrutor_id_1 = vinculo.instrutor_id_1
                elif vinculo.instrutor_id_2 in my_instrutor_ids:
                    instrutor_id_1 = vinculo.instrutor_id_2
                else:
                    instrutor_id_1 = my_instrutor_ids[0]

            if not instrutor_id_1:
                return False, 'Instrutor principal não especificado.', 400

            if not instrutor_id_2:
                vinculo_dt = db.session.scalar(
                    select(DisciplinaTurma).where(
                        DisciplinaTurma.disciplina_id == disciplina_id
                    )
                )

                if vinculo_dt:
                    if vinculo_dt.instrutor_id_1 == instrutor_id_1 and vinculo_dt.instrutor_id_2:
                        instrutor_id_2 = vinculo_dt.instrutor_id_2
                    elif vinculo_dt.instrutor_id_2 == instrutor_id_1 and vinculo_dt.instrutor_id_1:
                        instrutor_id_2 = vinculo_dt.instrutor_id_1

            aula_original = db.session.get(Horario, horario_id) if horario_id else None
            group_id_original = aula_original.group_id if aula_original else None

            instructors_to_check = [i for i in [instrutor_id_1, instrutor_id_2] if i is not None]

            if instructors_to_check and (not disciplina or disciplina.materia.strip().upper() != 'A DISPOSIÇÃO DO C AL /S ENS'):
                user_ids_subq = select(Instrutor.user_id).where(Instrutor.id.in_(instructors_to_check))
                all_instrutor_ids_subq = select(Instrutor.id).where(Instrutor.user_id.in_(user_ids_subq))

                semanas_globais_subq = select(Semana.id).where(
                    Semana.data_inicio == semana.data_inicio,
                    Semana.data_fim == semana.data_fim
                )

                conflict_query = select(Horario).where(
                    Horario.semana_id.in_(semanas_globais_subq),
                    Horario.dia_semana == dia,
                    Horario.periodo <= periodo_fim,
                    (Horario.periodo + Horario.duracao - 1) >= periodo_inicio,
                    or_(
                        Horario.instrutor_id.in_(all_instrutor_ids_subq),
                        Horario.instrutor_id_2.in_(all_instrutor_ids_subq)
                    )
                )

                if group_id_original:
                    conflict_query = conflict_query.where(Horario.group_id != group_id_original)
                elif horario_id:
                    conflict_query = conflict_query.where(Horario.id != int(horario_id))

                conflict_aulas = db.session.scalars(conflict_query).all()
                if conflict_aulas:
                    conflito_school_id = school_id
                    conflito_school_name = "Outra Escola"
                    pelotao_conflito = conflict_aulas[0].pelotao
                    
                    periodos_conflito = []
                    for c_aula in conflict_aulas:
                        for p in range(c_aula.periodo, c_aula.periodo + c_aula.duracao):
                            if p not in periodos_conflito:
                                periodos_conflito.append(p)
                    periodos_conflito.sort()
                    periodos_str = ", ".join(map(str, periodos_conflito))

                    try:
                        semana_conflito = db.session.get(Semana, conflict_aulas[0].semana_id)
                        if semana_conflito and semana_conflito.ciclo_id:
                            ciclo_conflito = db.session.get(Ciclo, semana_conflito.ciclo_id)
                            if ciclo_conflito:
                                conflito_school_id = ciclo_conflito.school_id
                                if ciclo_conflito.school_id != school_id:
                                    escola_obj = db.session.get(School, ciclo_conflito.school_id)
                                    if escola_obj:
                                        conflito_school_name = getattr(escola_obj, 'nome', getattr(escola_obj, 'name', "Outra Escola"))
                    except Exception as e_school:
                        current_app.logger.warning(f"Erro ao buscar escola do conflito: {e_school}")

                    if conflito_school_id != school_id:
                        return False, (
                            f"⚠️ CONFLITO DE AGENDA: O instrutor já possui aula marcada na escola "
                            f"'{conflito_school_name}' neste dia e horário (Períodos: {periodos_str})."
                        ), 409
                    else:
                        return False, (
                            f"⚠️ CONFLITO DE AGENDA: O instrutor já está alocado na turma "
                            f"'{pelotao_conflito}' neste horário (Períodos: {periodos_str})."
                        ), 409

            periodos_solicitados = list(range(periodo_inicio, periodo_fim + 1))

            conflito_query_interno = select(Horario).where(
                Horario.pelotao == pelotao,
                Horario.semana_id.in_(semanas_sobrepostas),
                Horario.dia_semana == dia,
                Horario.periodo <= periodo_fim,
                (Horario.periodo + Horario.duracao - 1) >= periodo_inicio
            )
            
            if group_id_original:
                conflito_query_interno = conflito_query_interno.where(Horario.group_id != group_id_original)
            elif horario_id:
                conflito_query_interno = conflito_query_interno.where(Horario.id != int(horario_id))

            conflito_internos = db.session.scalars(conflito_query_interno).all()
            if conflito_internos:
                periodos_ocupados = []
                materias_ocupadas = set()
                for c_int in conflito_internos:
                    for p in range(c_int.periodo, c_int.periodo + c_int.duracao):
                        if p not in periodos_ocupados:
                            periodos_ocupados.append(p)
                    if getattr(c_int, 'disciplina', None):
                        materias_ocupadas.add(c_int.disciplina.materia)
                periodos_ocupados.sort()
                periodos_str = ", ".join(map(str, periodos_ocupados))
                materias_str = ", ".join(materias_ocupadas) if materias_ocupadas else "outra matéria"
                return False, f"⚠️ ERRO DE MARCAÇÃO DUPLA: Os períodos {periodos_str} já estão ocupados por '{materias_str}'.", 409

            if horario_id:
                if not aula_original or not HorarioService.can_edit_horario(aula_original, user):
                    return False, 'Aula não encontrada ou sem permissão para editar.', 404

                if group_id_original:
                    db.session.query(Horario).filter(Horario.group_id == group_id_original).delete()
                else:
                    db.session.delete(aula_original)

                db.session.flush() 

            # Busca intervalos para quebra de grupos
            try:
                pos_int_1 = int(float(SiteConfigService.get_config('posicao_intervalo_manha', '3', school_id=school_id)))
                pos_almoco = int(float(SiteConfigService.get_config('posicao_intervalo_almoco', '6', school_id=school_id)))
                pos_int_2 = int(float(SiteConfigService.get_config('posicao_intervalo_tarde', '9', school_id=school_id)))
            except:
                pos_int_1, pos_almoco, pos_int_2 = 3, 6, 9
                
            break_points = {pos_int_1, pos_almoco, pos_int_2}
            new_group_id = str(uuid.uuid4()) if duracao > 1 else None
            
            idx = 0
            while idx < len(periodos_solicitados):
                p_start = periodos_solicitados[idx]
                p_current = p_start
                dur_bloco = 1
                
                while (idx + 1) < len(periodos_solicitados) and \
                      periodos_solicitados[idx+1] == p_current + 1 and \
                      p_current not in break_points:
                    p_current = periodos_solicitados[idx+1]
                    dur_bloco += 1
                    idx += 1
                
                nova_aula_bloco = Horario(
                    pelotao=pelotao,
                    semana_id=semana_id,
                    dia_semana=dia,
                    periodo=p_start,
                    duracao=dur_bloco,
                    disciplina_id=disciplina_id,
                    observacao=observacao,
                    instrutor_id=instrutor_id_1,
                    instrutor_id_2=instrutor_id_2,
                    status='confirmado' if is_admin else 'pendente',
                    group_id=new_group_id,
                )
                db.session.add(nova_aula_bloco)
                idx += 1 

            if not is_admin:
                # CORREÇÃO: Pegar turma apenas se pertencer a esta escola
                turma = db.session.scalar(select(Turma).where(Turma.nome == pelotao, Turma.school_id == school_id))

                if turma and turma.school_id:
                    message = (
                        f"O instrutor {user.nome_de_guerra} agendou uma nova aula de "
                        f"{disciplina.materia} que precisa de aprovação."
                    )
                    notification_url = url_for(
                        'horario.aprovar_horarios', _external=True
                    )
                    NotificationService.create_notification_for_roles(
                        turma.school_id,
                        ['admin_escola', 'super_admin'],
                        message,
                        notification_url,
                    )

            db.session.flush()
            HorarioService._consolidar_aulas_adjacentes(pelotao, semana_id, dia)
            db.session.commit()
            return True, 'Aula salva com sucesso!', 200

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Erro ao salvar aula: {e}")
            return False, 'Erro interno do servidor ao salvar.', 500

    @staticmethod
    def _consolidar_aulas_adjacentes(pelotao, semana_id, dia):
        pass

    @staticmethod
    def remove_aula(horario_id, user):
        aula = db.session.get(Horario, int(horario_id))
        if not aula or not HorarioService.can_edit_horario(aula, user):
            return False, 'Aula não encontrada ou sem permissão.'
            
        # --- VERIFICAÇÃO PARA ALERTA URGENTE (SENS) ---
        is_instructor = getattr(user, 'role', '') == 'instrutor'
        alert_info = None
        
        if is_instructor:
            if aula.group_id:
                aulas_grupo = db.session.query(Horario).filter(Horario.group_id == aula.group_id).order_by(Horario.periodo).all()
                periodos = [str(a.periodo) for a in aulas_grupo]
                if len(periodos) > 1:
                    periodos_str = ", ".join(periodos[:-1]) + f" e {periodos[-1]}º períodos"
                elif len(periodos) == 1:
                    periodos_str = f"{periodos[0]}º período"
                else:
                    periodos_str = "períodos desconhecidos"
            else:
                periodos_str = f"{aula.periodo}º período"
                
            instrutor_nome = aula.instrutor.user.nome_de_guerra if (aula.instrutor and aula.instrutor.user) else "Desconhecido"
            turma_nome = aula.pelotao
            disciplina_nome = aula.disciplina.materia if aula.disciplina else "Desconhecida"
            
            try:
                escola_id = aula.semana.ciclo.school_id
            except AttributeError:
                escola_id = None
                
            if escola_id:
                alert_info = {
                    "instrutor": instrutor_nome,
                    "turma": turma_nome,
                    "disciplina": disciplina_nome,
                    "periodos": periodos_str,
                    "escola_id": escola_id
                }
        # ----------------------------------------------

        if aula.group_id:
            db.session.query(Horario).filter(Horario.group_id == aula.group_id).delete()
        else:
            db.session.delete(aula)

        db.session.commit()
        
        # --- DISPARO DE NOTIFICAÇÃO URGENTE PARA SENS ---
        if alert_info:
            from ..models.user import User
            from ..models.user_school import UserSchool
            from ..models.notification import Notification
            
            # Buscar todos da SENS e Comandantes
            sens_users = db.session.query(User).join(UserSchool).filter(
                UserSchool.school_id == alert_info["escola_id"],
                UserSchool.role.in_(['admin_sens', 'admin_escola'])
            ).all()
            
            mensagem_alerta = f"O instrutor {alert_info['instrutor']} acabou de desmarcar a aula de {alert_info['disciplina']} para o {alert_info['turma']} ({alert_info['periodos']})."
            
            for su in sens_users:
                notif = Notification(
                    user_id=su.id,
                    message=mensagem_alerta,
                    url="#URGENTE_SENS"
                )
                db.session.add(notif)
            db.session.commit()
        # ------------------------------------------------

        return True, 'Aula removida com sucesso!'

    @staticmethod
    def get_aulas_pendentes():
        school_id = UserService.get_current_school_id()

        query = select(Horario).options(
            joinedload(Horario.disciplina).joinedload(Disciplina.ciclo),
            joinedload(Horario.instrutor).joinedload(Instrutor.user),
            joinedload(Horario.semana),
        ).where(Horario.status == 'pendente')

        if school_id:
            query = query.join(Semana).join(Ciclo).where(
                Ciclo.school_id == school_id
            )

        return db.session.scalars(
            query.order_by(Horario.id.desc())
        ).all()

    @staticmethod
    def get_aulas_pendentes_agrupadas():
        aulas_pendentes_flat = HorarioService.get_aulas_pendentes()
        grouped_aulas = defaultdict(list)
        single_aulas = []

        for aula in aulas_pendentes_flat:
            if aula.group_id:
                grouped_aulas[aula.group_id].append(aula)
            else:
                single_aulas.append(aula)

        aulas_para_template = []

        for aula in single_aulas:
            aulas_para_template.append({
                'aula': aula,
                'periodo_str': f"{aula.periodo}º ({aula.duracao}h)",
                'id_para_acao': aula.id,
            })

        for group_id, aulas_no_grupo in grouped_aulas.items():
            if not aulas_no_grupo:
                continue

            aulas_no_grupo.sort(key=lambda a: a.periodo)
            primeira_aula = aulas_no_grupo[0]

            total_duracao = sum(a.duracao for a in aulas_no_grupo)
            periodo_min = min(a.periodo for a in aulas_no_grupo)
            periodo_max = max(
                a.periodo + a.duracao - 1 for a in aulas_no_grupo
            )

            if periodo_min != periodo_max:
                periodo_str = f"{periodo_min}º ao {periodo_max}º ({total_duracao}h)"
            else:
                periodo_str = f"{periodo_min}º ({total_duracao}h)"

            aulas_para_template.append({
                'aula': primeira_aula,
                'periodo_str': periodo_str,
                'id_para_acao': primeira_aula.id,
            })

            aulas_para_template.sort(
            key=lambda x: x['aula'].id, reverse=True
        )
        return aulas_para_template

    @staticmethod
    def aprovar_horario(horario_id, action):
        aula_representativa = db.session.get(Horario, int(horario_id))
        if not aula_representativa:
            return False, 'Aula não encontrada.'

        if aula_representativa.group_id:
            aulas_para_alterar = db.session.scalars(
                select(Horario).where(
                    Horario.group_id == aula_representativa.group_id
                )
            ).all()
        else:
            aulas_para_alterar = [aula_representativa]

        if not aulas_para_alterar:
            return False, 'Nenhuma aula encontrada para a ação.'

        instrutor_user_id = (
            aulas_para_alterar[0].instrutor.user_id
            if aulas_para_alterar[0].instrutor else None
        )
        disciplina_materia = aulas_para_alterar[0].disciplina.materia
        turma_nome = aulas_para_alterar[0].pelotao

        if action == 'aprovar':
            for aula in aulas_para_alterar:
                aula.status = 'confirmado'

            message = f'Agendamento de {disciplina_materia} aprovado.'
            
            # CORREÇÃO: Limitar pesquisa de turma à escola atual no ato de notificar
            school_id = UserService.get_current_school_id()
            turma = db.session.scalar(
                select(Turma).where(Turma.nome == turma_nome, Turma.school_id == school_id)
            )

            if turma:
                notif_url = url_for(
                    'horario.index',
                    pelotao=turma.nome,
                    semana_id=aulas_para_alterar[0].semana_id,
                    _external=True
                )

                if instrutor_user_id:
                    NotificationService.create_notification(
                        instrutor_user_id,
                        f"Seu agendamento de {disciplina_materia} "
                        f"para a turma {turma.nome} foi aprovado.",
                        notif_url
                    )

                for aluno in turma.alunos:
                    NotificationService.create_notification(
                        aluno.user_id,
                        f"Nova aula de {disciplina_materia} agendada para sua turma.",
                        notif_url
                    )

        elif action == 'negar':
            for aula in aulas_para_alterar:
                db.session.delete(aula)
            message = (
                f'Solicitação de aula de {disciplina_materia} '
                f'foi negada e removida.'
            )
        else:
            return False, 'Ação inválida.'

        db.session.commit()
        return True, message

    @staticmethod
    def aprovar_horario_parcialmente(horario_id, periodos_aprovados):
        return False, "Funcionalidade não implementada neste contexto."

    @staticmethod
    def get_aulas_painel_admin(school_id, ciclo_id, instrutor_id=None, turma_nome=None):
        hoje = date.today()
        
        query = (
            select(Horario)
            .join(Semana)
            .join(Turma, Turma.nome == Horario.pelotao)
            .options(
                joinedload(Horario.disciplina),
                joinedload(Horario.instrutor).joinedload(Instrutor.user).joinedload(User.instrutor_profile),
                joinedload(Horario.instrutor_2).joinedload(Instrutor.user).joinedload(User.instrutor_profile),
                joinedload(Horario.semana)
            )
            .where(
                Turma.school_id == school_id,
                Semana.ciclo_id == ciclo_id
            )
        )

        if instrutor_id:
            query = query.where(or_(
                Horario.instrutor_id == instrutor_id,
                Horario.instrutor_id_2 == instrutor_id
            ))
        
        if turma_nome:
            query = query.where(Horario.pelotao == turma_nome)

        aulas = db.session.scalars(
            query.order_by(Semana.data_inicio.asc(), Horario.dia_semana, Horario.periodo.asc())
        ).unique().all()

        mapa_dias = {
            'segunda': 0, 'terca': 1, 'quarta': 2,
            'quinta': 3, 'sexta': 4, 'sabado': 5, 'domingo': 6
        }

        aulas_raw = []
        for aula in aulas:
            try:
                dia_lower = str(aula.dia_semana).lower().replace('-feira', '')
                data_aula = aula.semana.data_inicio + timedelta(days=mapa_dias.get(dia_lower, 0))
            except:
                continue

            instrutores_data = []
            
            if aula.instrutor and aula.instrutor.user:
                u = aula.instrutor.user
                posto = u.posto_graduacao or ''
                nome_guerra = u.nome_de_guerra or u.username or 'U'
                
                foto_final = 'default.png'
                foto_aula = getattr(aula.instrutor, 'foto_perfil', None)
                if foto_aula and str(foto_aula).strip() not in ['', 'None', 'default.png']:
                    foto_final = str(foto_aula).strip()
                else:
                    primary_prof = getattr(u, 'instrutor_profile', None)
                    if primary_prof:
                        foto_primaria = getattr(primary_prof, 'foto_perfil', None)
                        if foto_primaria and str(foto_primaria).strip() not in ['', 'None', 'default.png']:
                            foto_final = str(foto_primaria).strip()

                instrutores_data.append({
                    'nome_exibicao': f"{posto} {nome_guerra}".strip(),
                    'nome_guerra': nome_guerra,
                    'foto': foto_final
                })
                
            if aula.instrutor_2 and aula.instrutor_2.user:
                u2 = aula.instrutor_2.user
                posto2 = u2.posto_graduacao or ''
                nome_guerra2 = u2.nome_de_guerra or u2.username or 'U'
                
                foto_final2 = 'default.png'
                foto_aula2 = getattr(aula.instrutor_2, 'foto_perfil', None)
                if foto_aula2 and str(foto_aula2).strip() not in ['', 'None', 'default.png']:
                    foto_final2 = str(foto_aula2).strip()
                else:
                    primary_prof2 = getattr(u2, 'instrutor_profile', None)
                    if primary_prof2:
                        foto_primaria2 = getattr(primary_prof2, 'foto_perfil', None)
                        if foto_primaria2 and str(foto_primaria2).strip() not in ['', 'None', 'default.png']:
                            foto_final2 = str(foto_primaria2).strip()

                instrutores_data.append({
                    'nome_exibicao': f"{posto2} {nome_guerra2}".strip(),
                    'nome_guerra': nome_guerra2,
                    'foto': foto_final2
                })

            aulas_raw.append({
                'id': aula.id,
                'data_raw': data_aula,
                'data_formatada': data_aula.strftime('%d/%m/%Y'),
                'dia_semana': str(aula.dia_semana).capitalize(),
                'semana_id': aula.semana_id, 
                'periodo_inicio': aula.periodo,
                'periodo_final': aula.periodo + aula.duracao - 1,
                'duracao': aula.duracao,
                'disciplina': aula.disciplina.materia if aula.disciplina else 'N/D',
                'disciplina_id': aula.disciplina_id,
                'instrutores_data': instrutores_data, 
                'instrutores': " / ".join([i['nome_exibicao'] for i in instrutores_data]) if instrutores_data else 'N/D',
                'instrutor_ids': f"{aula.instrutor_id}-{aula.instrutor_id_2}",
                'turma': aula.pelotao,
                'status': aula.status,
                'observacao': aula.observacao,
                'is_passada': data_aula < hoje 
            })

        aulas_raw.sort(key=lambda x: (x['data_raw'], x['turma'], x['periodo_inicio']))

        grouped_aulas = []
        for aula in aulas_raw:
            if not grouped_aulas:
                grouped_aulas.append(aula)
                continue
            
            prev = grouped_aulas[-1]
            
            is_same_context = (
                prev['data_raw'] == aula['data_raw'] and
                prev['turma'] == aula['turma'] and
                prev['disciplina_id'] == aula['disciplina_id'] and
                prev['instrutor_ids'] == aula['instrutor_ids'] and
                prev['status'] == aula['status'] and
                prev['is_passada'] == aula['is_passada']
            )
            
            is_contiguous = (aula['periodo_inicio'] == prev['periodo_final'] + 1)
            
            if is_same_context and is_contiguous:
                prev['periodo_final'] = aula['periodo_final']
                prev['duracao'] += aula['duracao']
                if aula['observacao'] and prev['observacao'] != aula['observacao']:
                    if prev['observacao']:
                        prev['observacao'] += f" | {aula['observacao']}"
                    else:
                        prev['observacao'] = aula['observacao']
            else:
                grouped_aulas.append(aula)

        horarios_inicio = {
            1: "07:45", 2: "08:35", 3: "09:40", 4: "10:30",
            5: "13:30", 6: "14:20", 7: "15:25", 8: "16:15"
        }
        horarios_fim = {
            1: "08:35", 2: "09:25", 3: "10:30", 4: "11:20",
            5: "14:20", 6: "15:10", 7: "16:15", 8: "17:05"
        }

        futuras = []
        passadas = []

        for g in grouped_aulas:
            hora_i = horarios_inicio.get(g['periodo_inicio'], f"{g['periodo_inicio']}º T")
            hora_f = horarios_fim.get(g['periodo_final'], f"{g['periodo_final']}º T")

            g['hora_str'] = f"{hora_i} Até {hora_f}"
            if g['duracao'] > 1:
                g['periodo_str'] = f"Períodos {g['periodo_inicio']}º - {g['periodo_final']}º"
            else:
                g['periodo_str'] = f"Período {g['periodo_inicio']}º"
            
            if g['is_passada']:
                passadas.append(g)
            else:
                futuras.append(g)

        futuras.sort(key=lambda x: (x['data_raw'], x['periodo_inicio']))
        passadas.sort(key=lambda x: (x['data_raw'], x['periodo_inicio']), reverse=True)

        return {
            'futuras': futuras,
            'passadas': passadas
        }
