# backend/services/diario_service.py
import os
import base64
import uuid
import shutil
import re
from datetime import datetime, time, timedelta
import pytz
from flask import current_app, session
from ..models.database import db
from ..models.diario_classe import DiarioClasse
from ..models.horario import Horario
from ..models.instrutor import Instrutor
from ..models.turma import Turma
from ..models.disciplina import Disciplina
from ..models.disciplina_turma import DisciplinaTurma
from ..models.frequencia import FrequenciaAluno
from sqlalchemy import select, and_, or_, distinct

# IMPORTAÇÃO PARA LER OS HORÁRIOS DINÂMICOS DA ESCOLA
from .site_config_service import SiteConfigService

class DiarioService:
    
    @staticmethod
    def get_agora_brasilia():
        """Garante que o horário retornado seja estritamente o de Brasília, ignorando o fuso do servidor."""
        try:
            tz = pytz.timezone('America/Sao_Paulo')
            return datetime.now(tz)
        except Exception:
            # Fallback de segurança infalível: Pega a hora universal exata e subtrai 3 horas
            return datetime.utcnow() - timedelta(hours=3)

    @staticmethod
    def validar_criacao_diario_aluno(data_aula_str, periodo_final):
        """ Validação rigorosa: O aluno SÓ PODE criar o diário DURANTE/APÓS o último período daquela disciplina """
        try:
            agora = DiarioService.get_agora_brasilia()
            
            if isinstance(data_aula_str, str):
                data_aula = datetime.strptime(data_aula_str, '%Y-%m-%d').date()
            else:
                data_aula = data_aula_str
                
            if data_aula > agora.date():
                return False, "⚠️ Bloqueado: Não é possível criar diários para datas futuras."
                
            if data_aula < agora.date():
                return True, "" # Aulas de dias anteriores estão sempre liberadas
                
            # BUSCA DINÂMICA: Lê a configuração real da escola para aquele período específico
            school_id = session.get('active_school_id')
            periodo_key = f"horario_periodo_{int(periodo_final):02d}"
            time_str = SiteConfigService.get_config(periodo_key, 'N/D', school_id=school_id)

            if not time_str or time_str in ['N/D', '-']:
                return True, "" # Fallback de segurança: libera se não houver horário cadastrado na escola

            # Extrai os horários cadastrados (Ex: de "09:00-09:45" extrai ["09:00", "09:45"])
            times = re.findall(r'\d{2}:\d{2}', str(time_str))
            if not times:
                return True, ""
            
            # Pega o horário de INÍCIO do último período da disciplina para liberar o diário *durante* a aula
            hora_inicio_str = times[0]
            h, m = map(int, hora_inicio_str.split(':'))
            hora_liberacao = time(h, m)
            
            if agora.time() < hora_liberacao:
                return False, f"⚠️ O diário só será liberado durante o último período desta disciplina (a partir das {hora_inicio_str} no horário de Brasília)."
                
            return True, ""
        except Exception as e:
            return False, f"Erro interno de validação de horário: {str(e)}"

    @staticmethod
    def validar_conteudo_obrigatorio(conteudo):
        if not conteudo or str(conteudo).strip() == "":
            return False, "⚠️ O campo 'Conteúdo Ministrado' é obrigatório. Preencha o resumo da aula."
        return True, ""

    @staticmethod
    def get_current_instrutor(user_id):
        school_id = session.get('active_school_id')
        query = select(Instrutor).where(Instrutor.user_id == user_id)
        if school_id:
            try:
                query = query.where(Instrutor.school_id == int(school_id))
            except (ValueError, TypeError):
                pass
        return db.session.scalars(query).first()

    @staticmethod
    def get_diarios_pendentes(school_id, user_id=None, turma_id=None, disciplina_id=None, status=None, data_aula=None, page=1, per_page=30):
        # --- ALTERAÇÃO REALIZADA AQUI: Captura da edição ---
        active_edicao = session.get('active_edicao_id')
        
        stmt = (
            select(DiarioClasse)
            .join(Turma, DiarioClasse.turma_id == Turma.id)
            .options(
                db.joinedload(DiarioClasse.turma),
                db.joinedload(DiarioClasse.disciplina)
                .selectinload(Disciplina.associacoes_turmas)
                .joinedload(DisciplinaTurma.instrutor_1)
                .joinedload(Instrutor.user),
                db.joinedload(DiarioClasse.disciplina)
                .selectinload(Disciplina.associacoes_turmas)
                .joinedload(DisciplinaTurma.instrutor_2)
                .joinedload(Instrutor.user),
                db.joinedload(DiarioClasse.instrutor_assinante)
            )
            .where(
                Turma.school_id == school_id,
                Turma.edicao_id == active_edicao, # --- ALTERAÇÃO REALIZADA AQUI: Filtro da edição ---
                DiarioClasse.is_deleted == False
            )
        )

        if status:
            stmt = stmt.where(DiarioClasse.status == status)

        if data_aula:
            stmt = stmt.where(DiarioClasse.data_aula == data_aula)

        if user_id:
            instrutor = DiarioService.get_current_instrutor(user_id)
            if instrutor:
                subquery_vinculos = select(DisciplinaTurma.disciplina_id).where(
                    or_(
                        DisciplinaTurma.instrutor_id_1 == instrutor.id,
                        DisciplinaTurma.instrutor_id_2 == instrutor.id
                    )
                )
                stmt = stmt.where(DiarioClasse.disciplina_id.in_(subquery_vinculos))
            else:
                class EmptyPagination:
                    items = []
                    has_prev = False
                    has_next = False
                    page = 1
                    pages = 0
                    total = 0
                    def iter_pages(self): return []
                return EmptyPagination()

        if turma_id: stmt = stmt.where(DiarioClasse.turma_id == turma_id)
        if disciplina_id: stmt = stmt.where(DiarioClasse.disciplina_id == disciplina_id)

        # ORDENAÇÃO RIGOROSA PARA AGRUPAMENTO
        stmt = stmt.order_by(
            DiarioClasse.data_aula.desc(), 
            DiarioClasse.turma_id, 
            DiarioClasse.disciplina_id, 
            DiarioClasse.periodo.asc()
        )
        return db.paginate(stmt, page=page, per_page=per_page, error_out=False)

    @staticmethod
    def get_diarios_agrupados(school_id, user_id=None, turma_id=None, disciplina_id=None, status=None, page=1, per_page=30):
        pagination = DiarioService.get_diarios_pendentes(school_id, user_id, turma_id, disciplina_id, status, data_aula=None, page=page, per_page=per_page)
        raw_diarios = pagination.items
        
        if not raw_diarios: return [], pagination

        grouped_diarios = []
        current_group = [raw_diarios[0]]

        for i in range(1, len(raw_diarios)):
            curr = raw_diarios[i]
            prev = current_group[-1]

            is_same_context = (
                curr.data_aula == prev.data_aula and 
                curr.turma_id == prev.turma_id and 
                curr.disciplina_id == prev.disciplina_id
            )

            is_consecutive = False
            if curr.periodo is not None and prev.periodo is not None:
                is_consecutive = (curr.periodo == prev.periodo + 1) or (curr.periodo == prev.periodo)
            elif curr.periodo is None and prev.periodo is None:
                is_consecutive = True
            
            if is_same_context and is_consecutive:
                current_group.append(curr)
            else:
                grouped_diarios.append(DiarioService._criar_representante_grupo(current_group))
                current_group = [curr]
        
        if current_group:
            grouped_diarios.append(DiarioService._criar_representante_grupo(current_group))

        return grouped_diarios, pagination

    @staticmethod
    def _criar_representante_grupo(group_items):
        rep = group_items[0] 
        first_p = group_items[0].periodo
        last_p = group_items[-1].periodo
        
        if first_p is None: rep.periodo_resumo = "N/D"
        elif first_p == last_p: rep.periodo_resumo = f"{first_p}º Período"
        else: rep.periodo_resumo = f"{first_p}º a {last_p}º Período"
            
        rep.total_aulas_bloco = len(group_items)

        if rep.status == 'assinado' and getattr(rep, 'instrutor_assinante', None):
            u = rep.instrutor_assinante
            posto = u.posto_graduacao or ""
            guerra = u.nome_de_guerra or u.nome_completo or ""
            rep.instrutor_nome_exibicao = f"{posto} {guerra}".strip()
        else:
            vinculo = db.session.scalar(
                select(DisciplinaTurma).where(DisciplinaTurma.disciplina_id == rep.disciplina_id)
            )
            if vinculo:
                if getattr(vinculo, 'instrutor_1', None) and getattr(vinculo.instrutor_1, 'user', None):
                    u = vinculo.instrutor_1.user
                    posto = u.posto_graduacao or ""
                    guerra = u.nome_de_guerra or u.nome_completo or ""
                    rep.instrutor_nome_exibicao = f"{posto} {guerra} (Vinculado)".strip()
                elif getattr(vinculo, 'instrutor_2', None) and getattr(vinculo.instrutor_2, 'user', None):
                    u = vinculo.instrutor_2.user
                    posto = u.posto_graduacao or ""
                    guerra = u.nome_de_guerra or u.nome_completo or ""
                    rep.instrutor_nome_exibicao = f"{posto} {guerra} (Auxiliar Vinculado)".strip()
                else:
                    rep.instrutor_nome_exibicao = "Sem Vínculo de Instrutor"
            else:
                rep.instrutor_nome_exibicao = "Sem Vínculo de Instrutor"

        return rep

    @staticmethod
    def get_filtros_disponiveis(school_id, user_id=None, turma_selected_id=None):
        instrutor = DiarioService.get_current_instrutor(user_id) if user_id else None
        active_edicao = session.get('active_edicao_id')
        
        stmt_turmas = select(Turma).where(
            Turma.school_id == school_id,
            Turma.edicao_id == active_edicao
        ).order_by(Turma.nome)
        turmas = db.session.scalars(stmt_turmas).all()

        stmt_disc = select(Disciplina).join(Turma).where(
            Turma.school_id == school_id,
            Turma.edicao_id == active_edicao
        )
        if turma_selected_id:
            stmt_disc = stmt_disc.where(Disciplina.turma_id == turma_selected_id)
            
        if instrutor:
            vinculos = select(DisciplinaTurma.disciplina_id).where(
                or_(DisciplinaTurma.instrutor_id_1 == instrutor.id, 
                    DisciplinaTurma.instrutor_id_2 == instrutor.id)
            )
            stmt_disc = stmt_disc.where(Disciplina.id.in_(vinculos))

        disciplinas = db.session.scalars(stmt_disc.distinct()).all()
        unique_disciplinas = sorted({d.materia: d for d in disciplinas}.values(), key=lambda x: x.materia)

        return turmas, unique_disciplinas

    @staticmethod
    def get_diario_para_assinatura(diario_id, user_id):
        instrutor = DiarioService.get_current_instrutor(user_id)
        if not instrutor: return None, None
        
        diario = db.session.get(DiarioClasse, diario_id)
        if not diario or diario.is_deleted: return None, None

        vinculo = db.session.scalars(
            select(DisciplinaTurma).where(
                DisciplinaTurma.disciplina_id == diario.disciplina_id,
                or_(DisciplinaTurma.instrutor_id_1 == instrutor.id, 
                    DisciplinaTurma.instrutor_id_2 == instrutor.id)
            )
        ).first()

        if vinculo:
            return diario, instrutor
            
        return None, None

    @staticmethod
    def assinar_diario(diario_id, user_id, tipo_assinatura, dados_assinatura=None, salvar_padrao=False, conteudo_atualizado=None, observacoes_atualizadas=None, frequencias_atualizadas=None):
        diario_pai, instrutor = DiarioService.get_diario_para_assinatura(diario_id, user_id)
        if not diario_pai:
            return False, "Permissão negada."

        base_path = current_app.static_folder
        upload_folder = os.path.join(base_path, 'uploads', 'signatures')
        os.makedirs(upload_folder, exist_ok=True)
        
        filename = f"sig_diario_{diario_pai.id}_{uuid.uuid4().hex[:8]}.jpg"
        filepath = os.path.join(upload_folder, filename)
        db_path = f"uploads/signatures/{filename}"

        try:
            if tipo_assinatura == 'padrao':
                if not instrutor.assinatura_padrao_path: return False, "Sem assinatura padrão."
                shutil.copy2(os.path.join(base_path, instrutor.assinatura_padrao_path), filepath)
            elif tipo_assinatura == 'canvas':
                encoded = dados_assinatura.split(',', 1)[1] if ',' in dados_assinatura else dados_assinatura
                with open(filepath, 'wb') as f: f.write(base64.b64decode(encoded))
            elif tipo_assinatura == 'upload':
                if hasattr(dados_assinatura, 'save'):
                    dados_assinatura.save(filepath)
                else:
                    with open(filepath, 'wb') as f: f.write(dados_assinatura)

            if salvar_padrao and tipo_assinatura != 'padrao':
                if instrutor.assinatura_padrao_path:
                    old_path = os.path.join(base_path, instrutor.assinatura_padrao_path)
                    if os.path.exists(old_path):
                        try: os.remove(old_path)
                        except: pass
                
                filename_padrao = f"instrutor_padrao_{instrutor.id}.jpg"
                filepath_padrao = os.path.join(upload_folder, filename_padrao)
                shutil.copy2(filepath, filepath_padrao)
                instrutor.assinatura_padrao_path = f"uploads/signatures/{filename_padrao}"

            bloco_completo = db.session.scalars(
                select(DiarioClasse).where(
                    DiarioClasse.data_aula == diario_pai.data_aula,
                    DiarioClasse.turma_id == diario_pai.turma_id,
                    DiarioClasse.disciplina_id == diario_pai.disciplina_id,
                    DiarioClasse.is_deleted == False
                )
            ).all()

            if frequencias_atualizadas:
                for d in bloco_completo:
                    if d.id in frequencias_atualizadas:
                        for aluno_id, presente_bool in frequencias_atualizadas[d.id].items():
                            freq = db.session.scalar(
                                select(FrequenciaAluno).where(
                                    FrequenciaAluno.diario_id == d.id,
                                    FrequenciaAluno.aluno_id == int(aluno_id)
                                )
                            )
                            if not freq:
                                freq = FrequenciaAluno(diario_id=d.id, aluno_id=int(aluno_id))
                                db.session.add(freq)
                            freq.presente = presente_bool
                            if freq.presente: freq.justificativa = None

            timestamp = DiarioService.get_agora_brasilia()
            for d in bloco_completo:
                if d.status == 'pendente':
                    d.assinatura_path = db_path
                    d.status = 'assinado'
                    d.data_assinatura = timestamp
                    d.instrutor_assinante_id = user_id
                    if conteudo_atualizado: d.conteudo_ministrado = conteudo_atualizado
                    if observacoes_atualizadas is not None: d.observacoes = observacoes_atualizadas

            db.session.commit()
            return True, f"Sucesso! {len(bloco_completo)} aulas validadas."
        except Exception as e:
            db.session.rollback()
            return False, str(e)

    @staticmethod
    def retornar_diario_admin(diario_id, admin_user, motivo_devolucao):
        diario = db.session.get(DiarioClasse, diario_id)
        if not diario: return False, "Não encontrado."
        try:
            siblings = db.session.scalars(select(DiarioClasse).where(
                DiarioClasse.data_aula == diario.data_aula,
                DiarioClasse.turma_id == diario.turma_id,
                DiarioClasse.disciplina_id == diario.disciplina_id,
                DiarioClasse.is_deleted == False
            )).all()
            for d in siblings:
                d.status = 'pendente'
                d.assinatura_path = None
                d.data_assinatura = None
                d.instrutor_assinante_id = None
                d.observacoes = (d.observacoes or "") + f"\n[DEVOLVIDO]: {motivo_devolucao}"
            db.session.commit()
            return True, "Aulas devolvidas."
        except Exception as e:
            db.session.rollback()
            return False, str(e)

    @staticmethod
    def atualizar_conteudo_admin(diario_id, novo_conteudo, novas_obs):
        diario = db.session.get(DiarioClasse, diario_id)
        if not diario: return False, "Não encontrado."
        try:
            siblings = db.session.scalars(select(DiarioClasse).where(
                DiarioClasse.data_aula == diario.data_aula,
                DiarioClasse.turma_id == diario.turma_id,
                DiarioClasse.disciplina_id == diario.disciplina_id,
                DiarioClasse.is_deleted == False
            )).all()
            for d in siblings:
                d.conteudo_ministrado = novo_conteudo
                d.observacoes = novas_obs
            db.session.commit()
            return True, "Atualizado."
        except Exception as e:
            db.session.rollback()
            return False, str(e)

    @staticmethod
    def excluir_diario_admin(diario_id, admin_user):
        diario = db.session.get(DiarioClasse, diario_id)
        if not diario: 
            return False, "Diário não encontrado."
        try:
            siblings = db.session.scalars(select(DiarioClasse).where(
                DiarioClasse.data_aula == diario.data_aula,
                DiarioClasse.turma_id == diario.turma_id,
                DiarioClasse.disciplina_id == diario.disciplina_id,
                DiarioClasse.is_deleted == False
            )).all()
            total_apagados = 0
            for d in siblings:
                d.is_deleted = True 
                total_apagados += 1
            db.session.commit()
            return True, f"Sucesso: {total_apagados} aula(s) foram movidas para a Lixeira do Admin."
        except Exception as e:
            db.session.rollback()
            return False, f"Erro ao enviar para a lixeira: {str(e)}"

    @staticmethod
    def restaurar_diario_admin(diario_id, admin_user):
        diario = db.session.get(DiarioClasse, diario_id)
        if not diario: 
            return False, "Diário não encontrado na lixeira."
        try:
            siblings = db.session.scalars(select(DiarioClasse).where(
                DiarioClasse.data_aula == diario.data_aula,
                DiarioClasse.turma_id == diario.turma_id,
                DiarioClasse.disciplina_id == diario.disciplina_id,
                DiarioClasse.is_deleted == True
            )).all()
            total_restaurados = 0
            for d in siblings:
                d.is_deleted = False 
                total_restaurados += 1
            db.session.commit()
            return True, f"Sucesso: {total_restaurados} aula(s) foram restauradas."
        except Exception as e:
            db.session.rollback()
            return False, f"Erro ao restaurar: {str(e)}"

    @staticmethod
    def devolver_diario_aluno(diario_id, instrutor_user, motivo_devolucao):
        """
        Função para o Instrutor REJEITAR/DEVOLVER o diário ao aluno.
        """
        diario = db.session.get(DiarioClasse, diario_id)
        if not diario: 
            return False, "Diário não encontrado."
        
        try:
            # Pega todos os diários daquele mesmo bloco quebrado
            siblings = db.session.scalars(select(DiarioClasse).where(
                DiarioClasse.data_aula == diario.data_aula,
                DiarioClasse.turma_id == diario.turma_id,
                DiarioClasse.disciplina_id == diario.disciplina_id,
                DiarioClasse.is_deleted == False
            )).all()
            
            total_apagados = 0
            for d in siblings:
                d.is_deleted = True # Remove da visão ativa (Soft Delete)
                d.observacoes = (d.observacoes or "") + f"\n[DEVOLVIDO AO ALUNO PELO INSTRUTOR]: {motivo_devolucao}"
                total_apagados += 1
                
            db.session.commit()
            return True, f"Diário devolvido/rejeitado com sucesso! O período foi liberado para o aluno refazer."
        except Exception as e:
            db.session.rollback()
            return False, f"Erro ao devolver diário: {str(e)}"

    @staticmethod
    def forcar_criacao_diario_manual(school_id, admin_id, turma_id, disciplina_id, data_aula_str, periodos):
        """
        MODO MASTER: Força a criação de diários ignorando qualquer regra de horário automático.
        Isso cria o diário em branco para que ele entre no fluxo do aluno.
        """
        try:
            if isinstance(data_aula_str, str):
                data_aula = datetime.strptime(data_aula_str, '%Y-%m-%d').date()
            else:
                data_aula = data_aula_str
                
            criados = 0
            ignorados = 0

            for periodo in periodos:
                # Verifica se JÁ EXISTE um diário para não duplicar acidentalmente
                existe = db.session.scalar(
                    select(DiarioClasse).where(
                        DiarioClasse.data_aula == data_aula,
                        DiarioClasse.turma_id == int(turma_id),
                        DiarioClasse.disciplina_id == int(disciplina_id),
                        DiarioClasse.periodo == int(periodo),
                        DiarioClasse.is_deleted == False
                    )
                )

                if existe:
                    ignorados += 1
                    continue

                # CORREÇÃO: responsavel_id é None para que o aluno (Chefe de Turma) assuma a autoria ao preencher
                novo_diario = DiarioClasse(
                    data_aula=data_aula,
                    periodo=int(periodo),
                    turma_id=int(turma_id),
                    disciplina_id=int(disciplina_id),
                    responsavel_id=None, 
                    status='pendente'
                )
                db.session.add(novo_diario)
                criados += 1

            db.session.commit()
            
            if criados > 0:
                return True, f"SUCESSO: {criados} período(s) criado(s) manualmente. ({ignorados} ignorados por já existirem)."
            else:
                return False, "Nenhum diário criado. Provavelmente eles já existem para esta data e períodos."

        except Exception as e:
            db.session.rollback()
            return False, f"ERRO CRÍTICO ao forçar criação: {str(e)}"
