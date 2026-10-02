# backend/controllers/justica_controller.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, g, Response, session
from flask_login import login_required, current_user
from urllib.parse import quote
from weasyprint import HTML
from sqlalchemy import select, or_
from sqlalchemy.orm import joinedload
from datetime import datetime, timedelta
import uuid
import hashlib
import logging
import json

from ..models.database import db
from ..models.processo_disciplina import ProcessoDisciplina, StatusProcesso
from ..models.elogio import Elogio
from ..models.aluno import Aluno
from ..models.user import User
from ..models.turma import Turma
from ..models.discipline_rule import DisciplineRule
from ..models.fada_avaliacao import FadaAvaliacao

from ..services.justica_service import JusticaService
from ..services.user_service import UserService
from ..services.turma_service import TurmaService
from ..services.email_service import EmailService
from ..models.background_job import BackgroundJob
from ..services.notification_service import NotificationService
from ..services.log_service import LogService

from utils.decorators import admin_or_programmer_required, can_manage_justice_required

justica_bp = Blueprint('justica', __name__, url_prefix='/justica-e-disciplina')
logger = logging.getLogger(__name__)

def sort_roman(rule):
    s = str(rule.codigo).upper().strip()
    if s.isdigit(): return int(s)
    rom_val = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}
    int_val = 0
    for i in range(len(s)):
        if s[i] not in rom_val: return 9999
        if i > 0 and rom_val.get(s[i], 0) > rom_val.get(s[i - 1], 0):
            int_val += rom_val.get(s[i], 0) - 2 * rom_val.get(s[i - 1], 0)
        else:
            int_val += rom_val.get(s[i], 0)
    return int_val

@justica_bp.route('/')
@login_required
def index():
    # Detecta a pÃ¡gina atual, a aba ativa e se hÃ¡ uma pesquisa
    page = request.args.get('page', 1, type=int)
    active_tab = request.args.get('tab', 'andamento')
    search_query = request.args.get('q', '').strip()

    school_id = UserService.get_current_school_id()

    tipo_npccal = 'ctsp'
    if g.get('active_edicao') and g.active_edicao.npccal_type:
        tipo_npccal = g.active_edicao.npccal_type.lower()

    fatos_predefinidos = db.session.scalars(
        select(DisciplineRule).where(DisciplineRule.npccal_type == tipo_npccal)
    ).all()
    fatos_predefinidos.sort(key=sort_roman)

    is_aluno_view = (str(current_user.role).lower().strip() == 'aluno') or (current_user.aluno_profile is not None and not current_user.is_staff)
    if is_aluno_view:
        if not current_user.aluno_profile or not current_user.aluno_profile.turma:
            flash("Perfil incompleto.", "danger")
            return redirect(url_for('main.dashboard'))

        school_id = current_user.aluno_profile.turma.school_id
        g.active_school = current_user.aluno_profile.turma.school
        aluno_id = current_user.aluno_profile.id

        stmt_andamento = select(ProcessoDisciplina).options(
            joinedload(ProcessoDisciplina.aluno).joinedload(Aluno.user),
            joinedload(ProcessoDisciplina.aluno).joinedload(Aluno.turma)
        ).where(
            ProcessoDisciplina.aluno_id == aluno_id,
            ProcessoDisciplina.status != StatusProcesso.FINALIZADO.value,
            ProcessoDisciplina.status != StatusProcesso.ARQUIVADO.value
        ).order_by(ProcessoDisciplina.data_ocorrencia.desc())

        stmt_finalizados = select(ProcessoDisciplina).options(
            joinedload(ProcessoDisciplina.aluno).joinedload(Aluno.user),
            joinedload(ProcessoDisciplina.aluno).joinedload(Aluno.turma)
        ).where(
            ProcessoDisciplina.aluno_id == aluno_id,
            or_(ProcessoDisciplina.status == StatusProcesso.FINALIZADO.value, ProcessoDisciplina.status == StatusProcesso.ARQUIVADO.value)
        )

        # Filtro de pesquisa para o aluno
        if search_query:
            search_filter = ProcessoDisciplina.fato_constatado.ilike(f'%{search_query}%')
            if search_query.isdigit():
                search_filter = or_(search_filter, ProcessoDisciplina.id == int(search_query))
            
            # APLICA O FILTRO NA ABA CORRETA
            if active_tab == 'andamento':
                stmt_andamento = stmt_andamento.where(search_filter)
            else:
                stmt_finalizados = stmt_finalizados.where(search_filter)

        stmt_finalizados = stmt_finalizados.order_by(ProcessoDisciplina.data_decisao.desc())
        
        fadas_aluno = db.session.scalars(
            select(FadaAvaliacao).where(
                FadaAvaliacao.aluno_id == aluno_id,
                FadaAvaliacao.status.in_(['ALUNO', 'FINALIZADO', 'RECURSO'])
            ).order_by(FadaAvaliacao.data_avaliacao.desc())
        ).all()
        fadas_comissao = []
    else:
        fadas_comissao = db.session.scalars(
            select(FadaAvaliacao).where(
                or_(
                    FadaAvaliacao.presidente_id == current_user.id,
                    FadaAvaliacao.membro1_id == current_user.id,
                    FadaAvaliacao.membro2_id == current_user.id
                ),
                FadaAvaliacao.status == 'COMISSAO'
            ).order_by(FadaAvaliacao.data_avaliacao.desc())
        ).all()
        fadas_aluno = []
        if not school_id:
            flash("Nenhuma escola selecionada.", "warning")
            return redirect(url_for('main.dashboard'))

        active_edicao = session.get('active_edicao_id')
        edicao_filter = or_(Turma.edicao_id == active_edicao, Turma.edicao_id.is_(None)) if active_edicao else True

        stmt_andamento = select(ProcessoDisciplina).join(Aluno, ProcessoDisciplina.aluno_id == Aluno.id).join(User, Aluno.user_id == User.id).join(Turma, Aluno.turma_id == Turma.id).options(
            joinedload(ProcessoDisciplina.aluno).joinedload(Aluno.user),
            joinedload(ProcessoDisciplina.aluno).joinedload(Aluno.turma)
        ).where(
            Turma.school_id == school_id,
            edicao_filter,
            ProcessoDisciplina.status != StatusProcesso.FINALIZADO.value,
            ProcessoDisciplina.status != StatusProcesso.ARQUIVADO.value
        ).order_by(ProcessoDisciplina.data_ocorrencia.desc())

        # CORREÃ‡ÃƒO CRUCIAL AQUI: Ordem exata das tabelas para o banco nÃ£o se perder
        stmt_finalizados = select(ProcessoDisciplina).join(Aluno, ProcessoDisciplina.aluno_id == Aluno.id).join(User, Aluno.user_id == User.id).join(Turma, Aluno.turma_id == Turma.id).options(
            joinedload(ProcessoDisciplina.aluno).joinedload(Aluno.user),
            joinedload(ProcessoDisciplina.aluno).joinedload(Aluno.turma)
        ).where(
            Turma.school_id == school_id,
            edicao_filter,
            or_(ProcessoDisciplina.status == StatusProcesso.FINALIZADO.value, ProcessoDisciplina.status == StatusProcesso.ARQUIVADO.value)
        )

        # Filtra em todo o banco de dados antes de criar as pÃ¡ginas
        if search_query:
            search_filter = or_(
                User.nome_completo.ilike(f'%{search_query}%'),
                ProcessoDisciplina.fato_constatado.ilike(f'%{search_query}%'),
                User.matricula.ilike(f'%{search_query}%')
            )
            # Permite buscar pelo nÃºmero exato do processo
            if search_query.isdigit():
                search_filter = or_(search_filter, ProcessoDisciplina.id == int(search_query))

            # APLICA O FILTRO NA ABA CORRETA
            if active_tab == 'andamento':
                stmt_andamento = stmt_andamento.where(search_filter)
            else:
                stmt_finalizados = stmt_finalizados.where(search_filter)

        stmt_finalizados = stmt_finalizados.order_by(ProcessoDisciplina.data_decisao.desc())

    page_andamento = request.args.get('page_andamento', 1, type=int)
    em_andamento_paginados = db.paginate(stmt_andamento, page=page_andamento, per_page=50, error_out=False)
    
    houve_alteracao = JusticaService.verificar_e_atualizar_prazos(em_andamento_paginados.items)

    if houve_alteracao:
        em_andamento_paginados = db.paginate(stmt_andamento, page=page_andamento, per_page=50, error_out=False)
        
    em_andamento = em_andamento_paginados.items

    agora_dt = datetime.now().astimezone()
    for p in em_andamento:
        p.is_atrasado = False
        if p.status == 'AGUARDANDO_CIENCIA' and p.prazo_ciencia:
            try:
                pc = JusticaService._ensure_datetime(p.prazo_ciencia)
                if agora_dt > pc:
                    p.is_atrasado = True
            except:
                pass

    # Aqui o sistema "pica" os resultados da pesquisa global em pÃ¡ginas
    finalizados_paginados = db.paginate(stmt_finalizados, page=page, per_page=50, error_out=False)

    active_edicao_id = g.active_edicao.id if g.get('active_edicao') else session.get('active_edicao_id')
    turmas = TurmaService.get_turmas_by_school(school_id, edicao_id=active_edicao_id) if school_id else []

    agora_hora = datetime.now().strftime('%H:%M')
    hoje = datetime.now().strftime('%Y-%m-%d')

    # >>> INÃCIO DA BUSCA DOS SEUS ELOGIOS <<<
    stmt_meus_elogios = select(Elogio).options(
        joinedload(Elogio.aluno).joinedload(Aluno.user),
        joinedload(Elogio.aluno).joinedload(Aluno.turma)
    ).where(
        Elogio.registrado_por_id == current_user.id
    ).order_by(Elogio.data_elogio.desc())
    
    page_elogios = request.args.get('page_elogios', 1, type=int)
    meus_elogios_paginados = db.paginate(stmt_meus_elogios, page=page_elogios, per_page=20, error_out=False)
    meus_elogios = meus_elogios_paginados.items
    # >>> FIM DA BUSCA <<<

    return render_template('justica/index.html',
                           em_andamento=em_andamento,
                           em_andamento_paginados=em_andamento_paginados,
                           finalizados=finalizados_paginados,
                           active_tab=active_tab,
                           turmas=turmas,
                           fatos_predefinidos=fatos_predefinidos,
                           agora_hora=agora_hora,
                           hoje=hoje,
                           agora=agora_dt,
                           meus_elogios=meus_elogios, is_aluno_view=is_aluno_view,
                           meus_elogios_paginados=meus_elogios_paginados,
                           fadas_aluno=locals().get('fadas_aluno', []),
                           fadas_comissao=locals().get('fadas_comissao', []))

@justica_bp.route('/registrar-em-massa', methods=['POST'])
@login_required
@can_manage_justice_required
def registrar_em_massa():
    tipo = request.form.get('tipo_registro')
    alunos_ids = request.form.getlist('alunos_selecionados') or request.form.getlist('alunos_selecionados[]')

    data_fato_str = request.form.get('data_fato', datetime.now().strftime('%Y-%m-%d'))
    hora_fato = request.form.get('hora_fato', '12:00')
    descricao = request.form.get('descricao')

    try:
        data_completa = datetime.strptime(f"{data_fato_str} {hora_fato}", "%Y-%m-%d %H:%M").astimezone()
    except:
        data_completa = datetime.now().astimezone()

    if not alunos_ids:
        flash("Nenhum aluno selecionado.", "warning")
        return redirect(url_for('justica.index'))

    count = 0
    processos_criados = []

    if tipo == 'infracao':
        regra_id = request.form.get('regra_id')
        observacao = request.form.get('observacao')
        origem_punicao = request.form.get('origem_punicao', 'NPCCAL')
        is_crime = (request.form.get('is_crime', 'false').lower() == 'true')
        codigo_infracao_manual = request.form.get('codigo_infracao')

        pontos_iniciais = 0.0
        codigo_final = codigo_infracao_manual

        if regra_id and origem_punicao == 'NPCCAL':
            regra = db.session.get(DisciplineRule, int(regra_id))
            if regra:
                pontos_iniciais = regra.pontos
                codigo_final = regra.codigo

        for aid in alunos_ids:
            try:
                novo_processo = ProcessoDisciplina(
                    aluno_id=int(aid),
                    relator_id=current_user.id,
                    regra_id=int(regra_id) if (regra_id and origem_punicao == 'NPCCAL') else None,
                    codigo_infracao=codigo_final,
                    fato_constatado=descricao,
                    observacao=observacao,
                    data_ocorrencia=data_completa,
                    data_registro=datetime.now().astimezone(),
                    status=StatusProcesso.AGUARDANDO_CIENCIA.value,
                    origem_punicao=origem_punicao,
                    is_crime=is_crime,
                    pontos=pontos_iniciais
                )
                db.session.add(novo_processo)
                db.session.flush()
                processos_criados.append(novo_processo)
                count += 1
            except Exception as e:
                logger.error(f"Erro ao criar processo aluno {aid}: {e}")

    elif tipo == 'elogio':
        for aid in alunos_ids:
            try:
                novo_elogio = Elogio(aluno_id=int(aid), registrado_por_id=current_user.id,
                                     data_elogio=data_completa, descricao=descricao, pontos=0.0)
                db.session.add(novo_elogio)
                count += 1
            except Exception as e:
                logger.error(f"Erro no elogio: {e}")

    db.session.commit()
    
    # --- ESPIÃƒO: REGISTRO EM MASSA ---
    school_id = UserService.get_current_school_id()
    LogService.log(
        action="Registro em Massa (JustiÃ§a)",
        details=f"O usuÃ¡rio gerou {count} registro(s) do tipo '{tipo}'.",
        school_id=school_id
    )
    # ---------------------------------
    
    flash(f"{count} registros criados.", "success")
    return redirect(url_for('justica.index'))

def _check_processo_permission(processo):
    if not processo or not processo.aluno or not processo.aluno.turma:
        return False
    if g.get('active_school') and processo.aluno.turma.school_id != g.active_school.id:
        return False
    if g.get('active_edicao') and processo.aluno.turma.edicao_id != g.active_edicao.id:
        return False
    return True

@justica_bp.route('/editar-processo/<int:pid>', methods=['POST'])
@login_required
@can_manage_justice_required
def editar_processo(pid):
    processo = db.session.get(ProcessoDisciplina, pid)
    if not _check_processo_permission(processo):
        flash("Processo nÃ£o encontrado ou pertence a outra ediÃ§Ã£o/escola.", "danger")
        return redirect(url_for('justica.index'))

    if processo and processo.status == StatusProcesso.AGUARDANDO_CIENCIA.value:
        processo.fato_constatado = request.form.get('fato_constatado', processo.fato_constatado)
        processo.observacao = request.form.get('observacao', processo.observacao)
        processo.codigo_infracao = request.form.get('codigo_infracao', processo.codigo_infracao)
        db.session.commit()
        
        # --- ESPIÃƒO: EDITOU PROCESSO ---
        school_id = UserService.get_current_school_id()
        LogService.log(
            action="Editou Processo",
            details=f"O processo disciplinar ID {pid} foi editado na origem.",
            school_id=school_id
        )
        # -------------------------------
        
        flash("Processo atualizado com sucesso.", "success")
    else:
        flash("Este processo jÃ¡ avanÃ§ou de fase e nÃ£o pode mais ser editado na origem.", "danger")
    return redirect(url_for('justica.index'))

@justica_bp.route('/cobrar-ciencia/<int:pid>', methods=['POST'])
@login_required
@can_manage_justice_required
def cobrar_ciencia(pid):
    processo = db.session.get(ProcessoDisciplina, pid)
    if not _check_processo_permission(processo):
        flash("Processo nÃ£o encontrado ou pertence a outra ediÃ§Ã£o/escola.", "danger")
        return redirect(url_for('justica.index'))

    if processo and processo.status == StatusProcesso.AGUARDANDO_CIENCIA.value:
        aluno = db.session.get(Aluno, processo.aluno_id)
        if aluno and aluno.user:
            ano = processo.data_ocorrencia.strftime('%Y') if processo.data_ocorrencia else datetime.now().strftime('%Y')
            link = url_for('justica.index', _external=True)  # nosemgrep
            msg = f"URGENTE: O Processo NÂº {processo.id}/{ano} estÃ¡ aguardando a sua ciÃªncia. Acesse o mÃ³dulo de JustiÃ§a imediatamente para regularizaÃ§Ã£o e leitura do termo."

            # 1. Notifica no painel (Sininho)
            NotificationService.create_notification(
                user_id=aluno.user.id,
                message=msg,
                url=link
            )

            # 2. DISPARO DE E-MAIL OBRIGATÃ“RIO (Plugando o Brevo)
            if aluno.user.email and '@' in aluno.user.email:
                try:
                    EmailService.send_justice_notification_email(aluno.user, processo, link)
                    flash(f"CobranÃ§a oficial enviada com sucesso no painel e para o e-mail ({aluno.user.email}).", "success")
                except Exception as e:
                    logger.error(f"Erro ao enviar email de cobranÃ§a para {aluno.user.email}: {e}")
                    flash("Painel notificado, mas ocorreu um erro no servidor de E-mail (Brevo).", "danger")
            else:
                # O sistema avisa o administrador se o aluno nÃ£o tiver e-mail
                flash(f"Aviso no painel gerado. ATENÃ‡ÃƒO: O aluno {aluno.user.nome_completo} NÃƒO possui um e-mail vÃ¡lido cadastrado!", "warning")

    return redirect(url_for('justica.index'))

@justica_bp.route('/dar-ciente/<int:processo_id>', methods=['POST'])
@login_required
def dar_ciente(processo_id):
    processo = db.session.get(ProcessoDisciplina, processo_id)
    if not processo:
        flash("Processo nÃ£o encontrado.", "error")
        return redirect(url_for('justica.index'))

    is_aluno_dono = ((str(current_user.role).lower().strip() == 'aluno' or (current_user.aluno_profile is not None and not current_user.is_staff)) and current_user.aluno_profile and current_user.aluno_profile.id == processo.aluno_id)
    can_manage = (not (str(current_user.role).lower().strip() == 'aluno' or (current_user.aluno_profile is not None and not current_user.is_staff)))

    if not (is_aluno_dono or can_manage):
        flash("PermissÃ£o negada.", "error")
        return redirect(url_for('justica.index'))

    if processo.status == StatusProcesso.AGUARDANDO_CIENCIA.value:
        agora_dt = datetime.now().astimezone()
        processo.data_ciencia = agora_dt
        processo.status = StatusProcesso.ALUNO_NOTIFICADO.value
        processo.ciente_aluno = True
        flash("CiÃªncia do processo registrada. O prazo de 24 horas para defesa foi iniciado.", "success")
    else:
        flash("Este processo nÃ£o aguarda ciÃªncia inicial.", "warning")

    db.session.commit()
    
    # --- ESPIÃƒO: CIÃŠNCIA NO PROCESSO ---
    school_id = UserService.get_current_school_id()
    if not school_id and (str(current_user.role).lower().strip() == 'aluno' or (current_user.aluno_profile is not None and not current_user.is_staff)):
        school_id = current_user.aluno_profile.turma.school_id
        
    LogService.log(
        action="CiÃªncia de Processo",
        details=f"O aluno ou administrador registrou a ciÃªncia no processo ID {processo_id}.",
        school_id=school_id
    )
    # -----------------------------------
    
    return redirect(url_for('justica.index'))

@justica_bp.route('/enviar-defesa/<int:processo_id>', methods=['POST'])
@login_required
def enviar_defesa(processo_id):
    processo = db.session.get(ProcessoDisciplina, processo_id)
    if not processo:
        flash("Processo nÃ£o encontrado.", "error")
        return redirect(url_for('justica.index'))

    is_aluno_dono = ((str(current_user.role).lower().strip() == 'aluno' or (current_user.aluno_profile is not None and not current_user.is_staff)) and current_user.aluno_profile and current_user.aluno_profile.id == processo.aluno_id)

    if not is_aluno_dono:
        flash("PermissÃ£o negada. Apenas o aluno autuado pode enviar a defesa.", "error")
        return redirect(url_for('justica.index'))

    if processo.status != StatusProcesso.ALUNO_NOTIFICADO.value:
        flash("O processo nÃ£o estÃ¡ aguardando defesa.", "warning")
        return redirect(url_for('justica.index'))

    texto_defesa = request.form.get('defesa')
    if not texto_defesa or not texto_defesa.strip():
        flash("A justificativa nÃ£o pode estar vazia.", "warning")
        return redirect(url_for('justica.index'))

    processo.defesa = texto_defesa
    processo.data_defesa = datetime.now().astimezone()
    processo.status = StatusProcesso.DEFESA_ENVIADA.value

    try:
        db.session.commit()
        
        # --- ESPIÃƒO: ALUNO ENVIOU DEFESA ---
        school_id = current_user.aluno_profile.turma.school_id
        LogService.log(
            action="Enviou Defesa",
            details=f"O aluno enviou a defesa/justificativa para o processo ID {processo_id}.",
            school_id=school_id
        )
        # -----------------------------------
        
        flash("Justificativa/Defesa enviada com sucesso.", "success")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erro ao enviar defesa: {e}")
        flash(f"Erro ao salvar defesa: {str(e)}", "danger")

    return redirect(url_for('justica.index'))

@justica_bp.route('/enviar-recurso/<int:pid>', methods=['POST'])
@login_required
def enviar_recurso(pid):
    processo = db.session.get(ProcessoDisciplina, pid)

    is_aluno_dono = ((str(current_user.role).lower().strip() == 'aluno' or (current_user.aluno_profile is not None and not current_user.is_staff)) and current_user.aluno_profile and current_user.aluno_profile.id == processo.aluno_id)
    if not is_aluno_dono:
        flash("Apenas o aluno pode interpor recurso.", "error"); return redirect(url_for('justica.index'))

    if processo.status != StatusProcesso.DECISAO_EMITIDA.value:
        flash("Status invÃ¡lido para recurso.", "error"); return redirect(url_for('justica.index'))

    agora = datetime.now().astimezone()
    if processo.data_decisao and processo.data_decisao.tzinfo:
        horas_passadas = (agora - processo.data_decisao).total_seconds() / 3600
        if horas_passadas > 48:
            flash("Prazo de 48h para recurso expirado.", "error"); return redirect(url_for('justica.index'))

    texto = request.form.get('texto_recurso')
    if not texto:
        flash("Escreva os argumentos do recurso.", "warning"); return redirect(url_for('justica.index'))

    processo.texto_recurso = texto
    processo.data_recurso = agora
    processo.status = StatusProcesso.EM_RECURSO.value

    db.session.commit()
    
    # --- ESPIÃƒO: ALUNO ENVIOU RECURSO ---
    school_id = current_user.aluno_profile.turma.school_id
    LogService.log(
        action="Enviou Recurso",
        details=f"O aluno interpÃ´s recurso para o processo disciplinar ID {pid}.",
        school_id=school_id
    )
    # ------------------------------------
    
    flash("Recurso enviando ao Comandante.", "success")
    return redirect(url_for('justica.index'))

@justica_bp.route('/finalizar-processo/<int:pid>', methods=['POST'])
@login_required
@can_manage_justice_required
def finalizar_processo(pid):
    processo = db.session.get(ProcessoDisciplina, pid)
    if not _check_processo_permission(processo):
        flash("Processo nÃ£o encontrado ou pertence a outra ediÃ§Ã£o/escola.", "danger")
        return redirect(url_for('justica.index'))

    if processo.status not in [StatusProcesso.DEFESA_ENVIADA.value, StatusProcesso.EM_ANALISE.value]:
        flash("O processo ainda nÃ£o estÃ¡ pronto para julgamento.", "warning")
        return redirect(url_for('justica.index'))

    decisao = request.form.get('decisao')
    fundamentacao_texto = request.form.get('observacao_decisao')
    turnos_sustacao = request.form.get('turnos_sustacao')
    novo_enquadramento_id = request.form.get('novo_enquadramento_id')

    if not decisao:
        flash("Selecione uma decisÃ£o vÃ¡lida.", "warning"); return redirect(url_for('justica.index'))

    pontos_finais = 0.0

    # LÃ³gica para Mudar o Enquadramento DinÃ¢mico sem interromper o fluxo
    if novo_enquadramento_id:
        nova_regra = db.session.get(DisciplineRule, int(novo_enquadramento_id))
        if nova_regra:
            enquadramento_antigo = processo.codigo_infracao or 'N/A'
            
            # Atualiza a regra no banco de dados para a nova escolhida
            processo.regra_id = nova_regra.id
            processo.codigo_infracao = nova_regra.codigo
            pontos_finais = nova_regra.pontos
            
            # Registra a alteraÃ§Ã£o na fundamentaÃ§Ã£o para auditoria
            fundamentacao_texto = f"[ENQUADRAMENTO ALTERADO]: O chefe reclassificou a infraÃ§Ã£o de '{enquadramento_antigo}' para '{nova_regra.codigo} - {nova_regra.descricao}'.\n\n{fundamentacao_texto}"
    else:
        # Se nÃ£o houve alteraÃ§Ã£o no enquadramento, busca a pontuaÃ§Ã£o da regra atual
        if processo.regra_id:
            regra = db.session.get(DisciplineRule, processo.regra_id)
            if regra:
                pontos_finais = regra.pontos
        elif processo.pontos:
            # Fallback caso seja uma infraÃ§Ã£o registrada manualmente
            pontos_finais = processo.pontos

    # Prossegue com o fluxo normal da decisÃ£o e finalizaÃ§Ã£o
    processo.decisao_final = decisao
    processo.data_decisao = datetime.now().astimezone()
    processo.relator_id = current_user.id

    if processo.is_revelia:
        fundamentacao_texto = f"[JULGAMENTO Ã€ REVELIA]: {fundamentacao_texto}"

    processo.fundamentacao = fundamentacao_texto
    processo.observacao_decisao = fundamentacao_texto

    tipo_npccal = 'ctsp'
    if g.get('active_edicao') and g.active_edicao.npccal_type:
        tipo_npccal = g.active_edicao.npccal_type.lower()

    if decisao == 'Justificado':
        processo.status = StatusProcesso.FINALIZADO.value
        msg_sucesso = "DecisÃ£o registrada como Justificado. O processo foi finalizado."
    elif tipo_npccal in ['cbfpm', 'ctsp', 'cspm']:
        processo.status = StatusProcesso.DECISAO_EMITIDA.value
        msg_sucesso = "DecisÃ£o registrada. O prazo de 48h para recurso jÃ¡ estÃ¡ correndo."
    else:
        processo.status = StatusProcesso.FINALIZADO.value
        msg_sucesso = "DecisÃ£o confirmada e processo finalizado."

    if decisao in ['AdvertÃªncia', 'RepreensÃ£o']:
        processo.tipo_sancao = decisao
        processo.dias_sancao = 0
        processo.detalhes_sancao = None
        processo.pontos = pontos_finais if pontos_finais > 0 else 0.0

    elif decisao == 'SustaÃ§Ã£o da Dispensa':
        processo.tipo_sancao = "SustaÃ§Ã£o da Dispensa"
        processo.detalhes_sancao = turnos_sustacao if turnos_sustacao else "Quantidade nÃ£o informada"
        processo.dias_sancao = 0
        processo.pontos = pontos_finais if pontos_finais > 0 else 0.0

    elif decisao == 'Justificado':
        processo.tipo_sancao = None
        processo.dias_sancao = 0
        processo.detalhes_sancao = None
        processo.pontos = 0.0

    try:
        db.session.commit()
        aluno = db.session.get(Aluno, processo.aluno_id)
        
        # --- ESPIÃƒO: JULGAMENTO DO PROCESSO ---
        school_id = UserService.get_current_school_id()
        LogService.log(
            action="Julgou Processo Disciplinar",
            details=f"Julgou o processo ID {processo.id} do aluno {aluno.user.nome_completo if aluno and aluno.user else 'Desconhecido'}. Veredito: {decisao}. Pontos: {processo.pontos}",
            school_id=school_id
        )
        # --------------------------------------

        if aluno and aluno.user:
            link = url_for('justica.index', _external=True)  # nosemgrep
            msg_notificacao = f"DecisÃ£o emitida no processo {processo.id}. O prazo para recurso estÃ¡ correndo."
            if decisao == 'Justificado':
                msg_notificacao = f"Processo {processo.id} finalizado como Justificado."

            # 1. Notifica no painel
            NotificationService.create_notification(
                user_id=aluno.user.id,
                message=msg_notificacao,
                url=link
            )

            # 2. DISPARO DE E-MAIL (Veredito)
            if aluno.user.email and '@' in aluno.user.email:
                try:
                    EmailService.send_justice_verdict_email(aluno.user, processo)
                except Exception as e:
                    logger.error(f"Erro ao enviar email de veredito para {aluno.user.email}: {e}")

        flash(msg_sucesso, "success")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erro ao finalizar processo {pid}: {e}")
        flash(f"Erro ao salvar: {str(e)}", "danger")

    return redirect(url_for('justica.index'))

@justica_bp.route('/julgar-recurso/<int:pid>', methods=['POST'])
@login_required
def julgar_recurso(pid):
    school_id = UserService.get_current_school_id()
    is_comandante = current_user.is_admin_escola_in_school(school_id)

    if not is_comandante:
        flash("Apenas o Comandante (Admin Escola) pode julgar recursos.", "error")
        return redirect(url_for('justica.index'))

    processo = db.session.get(ProcessoDisciplina, pid)

    decisao = request.form.get('decisao_recurso')
    parecer = request.form.get('fundamentacao_recurso')
    nova_sancao = request.form.get('nova_sancao')

    processo.decisao_recurso = decisao
    processo.fundamentacao_recurso = parecer
    processo.autoridade_recurso_id = current_user.id
    processo.data_julgamento_recurso = datetime.now().astimezone()

    if decisao == 'DEFERIDO':
        pontos_recurso = request.form.get('pontos_finais_recurso')
        if pontos_recurso is not None:
            try:
                pontos_recurso = float(pontos_recurso)
            except ValueError:
                pontos_recurso = processo.pontos
        else:
            pontos_recurso = processo.pontos

        if nova_sancao == 'Justificado':
            processo.tipo_sancao = None
            processo.dias_sancao = 0
            processo.detalhes_sancao = None
            processo.pontos = 0.0
            processo.decisao_final = 'Justificado'
            processo.observacao_decisao += f" | Recurso DEFERIDO. PuniÃ§Ã£o anulada (Justificado) pelo Comandante em {datetime.now().strftime('%d/%m')}."
        else:
            processo.tipo_sancao = nova_sancao
            processo.decisao_final = nova_sancao
            if nova_sancao == 'SustaÃ§Ã£o da Dispensa':
                processo.detalhes_sancao = request.form.get('turnos_sustacao_recurso')
            else:
                processo.detalhes_sancao = None

            processo.pontos = pontos_recurso
            processo.observacao_decisao += f" | Recurso DEFERIDO PARCIALMENTE. PuniÃ§Ã£o atenuada para {nova_sancao} pelo Comandante em {datetime.now().strftime('%d/%m')}."

    else:
        processo.observacao_decisao += f" | Recurso INDEFERIDO pelo Comandante em {datetime.now().strftime('%d/%m')}. DecisÃ£o mantida."

    processo.status = StatusProcesso.FINALIZADO.value

    db.session.commit()
    
    # --- ESPIÃƒO: COMANDANTE JULGOU RECURSO ---
    LogService.log(
        action="Julgou Recurso",
        details=f"O Comandante julgou o recurso do processo ID {pid}. DecisÃ£o: {decisao}.",
        school_id=school_id
    )
    # -----------------------------------------
    
    flash("Recurso julgado. Processo finalizado.", "success")
    return redirect(url_for('justica.index'))

@justica_bp.route('/arquivar-processo/<int:pid>', methods=['POST'])
@login_required
@can_manage_justice_required
def arquivar_processo(pid):
    processo = db.session.get(ProcessoDisciplina, pid)
    if not processo:
        flash("Processo nÃ£o encontrado.", "error"); return redirect(url_for('justica.index'))

    processo.status = StatusProcesso.ARQUIVADO.value
    db.session.commit()
    
    # --- ESPIÃƒO: ARQUIVOU PROCESSO ---
    school_id = UserService.get_current_school_id()
    LogService.log(
        action="Arquivou Processo",
        details=f"O processo ID {pid} foi arquivado.",
        school_id=school_id
    )
    # ---------------------------------
    
    flash("Processo arquivado.", "info")
    return redirect(url_for('justica.index'))

@justica_bp.route('/deletar-processo/<int:pid>', methods=['POST'])
@login_required
@can_manage_justice_required
def deletar_processo(pid):
    processo = db.session.get(ProcessoDisciplina, pid)
    if not processo:
        flash("Processo nÃ£o encontrado.", "danger"); return redirect(url_for('justica.index'))

    school_id = UserService.get_current_school_id()
    if processo.aluno and processo.aluno.turma and processo.aluno.turma.school_id != school_id:
         if not current_user.is_admin_escola_in_school(school_id):
             flash("Este processo pertence a outra escola.", "danger")
             return redirect(url_for('justica.index'))

    success, message = JusticaService.deletar_processo(pid)
    
    # --- ESPIÃƒO: DELETOU PROCESSO ---
    if success:
        LogService.log(
            action="Deletou Processo",
            details=f"O processo ID {pid} foi removido definitivamente do sistema.",
            school_id=school_id
        )
    # --------------------------------
    
    flash(message, 'success' if success else 'danger')
    return redirect(url_for('justica.index'))

@justica_bp.route('/imprimir-lote', methods=['POST'])
@login_required
@can_manage_justice_required
def imprimir_lote():
    ids_selecionados = request.form.getlist('processos_ids')
    num_boletim = request.form.get('numero_boletim')

    if not ids_selecionados:
        flash("Nenhum processo selecionado para impressÃ£o.", "warning")
        return redirect(url_for('justica.index'))

    processos_para_imprimir = []

    for pid in ids_selecionados:
        proc = db.session.get(ProcessoDisciplina, int(pid))
        if proc:
            if num_boletim:
                msg_pub = f" | Publicado em Boletim NÂº {num_boletim} em {datetime.now().strftime('%d/%m/%Y')}."
            else:
                msg_pub = f" | Impresso em {datetime.now().strftime('%d/%m/%Y')}."
                
            if not proc.observacao_decisao or msg_pub.strip() not in proc.observacao_decisao:
                if proc.observacao_decisao:
                    proc.observacao_decisao += msg_pub
                else:
                    proc.observacao_decisao = msg_pub
            processos_para_imprimir.append(proc)

    db.session.commit()
    
    # --- ESPIÃƒO: IMPRIMIU EM LOTE ---
    school_id = UserService.get_current_school_id()
    LogService.log(
        action="Imprimiu Lote de Processos",
        details=f"O usuÃ¡rio gerou a impressÃ£o/boletim para {len(processos_para_imprimir)} processos.",
        school_id=school_id
    )
    # --------------------------------
    
    return render_template('justica/imprimir_lote.html', processos=processos_para_imprimir, num_boletim=num_boletim)

# --- ROTAS FADA ---
@justica_bp.route('/fada/boletim')
@login_required
def fada_boletim():
    school_id = UserService.get_current_school_id()
    if not school_id and (str(current_user.role).lower().strip() == 'aluno' or (current_user.aluno_profile is not None and not current_user.is_staff)):
        school_id = current_user.aluno_profile.turma.school_id

    if not school_id:
        flash("Nenhuma escola selecionada.", "warning"); return redirect(url_for('main.dashboard'))

    turma_id = request.args.get('turma_id', type=int)

    active_edicao_id = session.get('active_edicao_id')
    query = select(Aluno).join(Turma).join(User).where(Turma.school_id == school_id)
    if active_edicao_id:
        query = query.where(Turma.edicao_id == active_edicao_id)
    if turma_id: query = query.where(Turma.id == turma_id)
    query = query.order_by(Turma.nome, User.nome_completo)
    alunos = db.session.scalars(query).all()

    turmas = TurmaService.get_turmas_by_school(school_id, edicao_id=active_edicao_id)

    query_staff = select(User).where(User.role != 'aluno').order_by(User.nome_completo)
    all_users = db.session.scalars(query_staff).all()

    staff_users = []
    for u in all_users:
        try:
            if hasattr(u, 'schools'):
                if any(str(s.id) == str(school_id) for s in u.schools):
                    if u.is_cal_in_school(school_id) or u.is_sens_in_school(school_id) or u.is_admin_escola_in_school(school_id):
                        staff_users.append(u)
        except: continue

    if current_user not in staff_users:
        staff_users.append(current_user)

    lista = []
    for aluno in alunos:
        fada_obj = db.session.scalar(select(FadaAvaliacao).where(FadaAvaliacao.aluno_id == aluno.id).order_by(FadaAvaliacao.id.desc()))
        aat, ndisc, fada_val = JusticaService.calcular_aat_final(aluno.id)

        dt_inicio, dt_limite = JusticaService.get_datas_limites(aluno.turma_id)
        punicoes = db.session.scalars(select(ProcessoDisciplina).where(ProcessoDisciplina.aluno_id == aluno.id, ProcessoDisciplina.status == StatusProcesso.FINALIZADO.value, ProcessoDisciplina.decisao_final != 'Justificado')).all()
        punicoes_validas = [p for p in punicoes if JusticaService.verificar_elegibilidade_punicao(p, dt_inicio, dt_limite)]

        lista.append({
            'id': aluno.id, 'aluno': aluno, 'turma': aluno.turma.nome,
            'ndisc': ndisc, 'fada': fada_val, 'aat': aat, 'fada_obj': fada_obj, 'punicoes_pendentes': punicoes_validas
        })

    return render_template('justica/fada_lista_alunos.html', dados=lista, turmas=turmas, avaliadores=staff_users)

@justica_bp.route('/fada/salvar', methods=['POST'])
@login_required
@can_manage_justice_required
def salvar_fada():
    aluno_id = request.form.get('aluno_id')
    notas = request.form.getlist('notas[]')
    obs = request.form.get('observacao')
    pres_id = request.form.get('presidente_id')
    m1_id = request.form.get('membro1_id')
    m2_id = request.form.get('membro2_id')
    pres_id = int(pres_id) if pres_id and pres_id.isdigit() else None
    m1_id = int(m1_id) if m1_id and m1_id.isdigit() else None
    m2_id = int(m2_id) if m2_id and m2_id.isdigit() else None

    if not aluno_id or len(notas) != 18:
        flash("Dados incompletos.", "danger"); return redirect(url_for('justica.fada_boletim'))

    processos_ativos = db.session.scalars(select(ProcessoDisciplina).where(ProcessoDisciplina.aluno_id == int(aluno_id), ProcessoDisciplina.status == StatusProcesso.FINALIZADO.value)).all()
    dt_inicio, dt_limite = JusticaService.get_datas_limites(db.session.get(Aluno, int(aluno_id)).turma_id)
    mapa_vinculos = {}

    for p in processos_ativos:
        if JusticaService.verificar_elegibilidade_punicao(p, dt_inicio, dt_limite):
            attr_idx = request.form.get(f'vinculo_infracao_{p.id}')
            if not attr_idx:
                flash(f"ERRO: A puniÃ§Ã£o (ID {p.id}) deve ser vinculada a um atributo.", "danger")
                return redirect(url_for('justica.fada_boletim'))
            mapa_vinculos[str(p.id)] = attr_idx

    limites_calculados, erro_limite = JusticaService.calcular_limites_fada(int(aluno_id), mapa_vinculos)
    if erro_limite:
        flash(f"Erro de ValidaÃ§Ã£o: {erro_limite}", "danger"); return redirect(url_for('justica.fada_boletim'))

    notas_float = []
    for i, n_str in enumerate(notas):
        try:
            val = float(n_str)
            teto = limites_calculados[i]
            if val > (teto + 0.01):
                flash(f"ERRO no Atributo {i+1}: Nota {val} excede o limite de {teto:.2f}.", "danger"); return redirect(url_for('justica.fada_boletim'))
            notas_float.append(val)
        except ValueError:
            flash("Nota invÃ¡lida.", "danger"); return redirect(url_for('justica.fada_boletim'))

    try:
        fada = db.session.scalar(select(FadaAvaliacao).where(FadaAvaliacao.aluno_id==int(aluno_id), FadaAvaliacao.status=='RASCUNHO'))
        media = sum(notas_float) / 18.0

        if fada:
            fada.media_final = media; fada.observacao = obs; fada.data_avaliacao = datetime.now().astimezone()
            fada.presidente_id = pres_id; fada.membro1_id = m1_id; fada.membro2_id = m2_id
            attrs = ['expressao', 'planejamento', 'perseveranca', 'apresentacao', 'lealdade', 'tato', 'equilibrio', 'disciplina', 'responsabilidade', 'maturidade', 'assiduidade', 'pontualidade', 'diccao', 'lideranca', 'relacionamento', 'etica', 'produtividade', 'eficiencia']
            for idx, attr in enumerate(attrs): setattr(fada, attr, notas_float[idx])
        else:
            nova = FadaAvaliacao(aluno_id=int(aluno_id), lancador_id=current_user.id, media_final=media, observacao=obs, status='RASCUNHO', presidente_id=pres_id, membro1_id=m1_id, membro2_id=m2_id)
            attrs = ['expressao', 'planejamento', 'perseveranca', 'apresentacao', 'lealdade', 'tato', 'equilibrio', 'disciplina', 'responsabilidade', 'maturidade', 'assiduidade', 'pontualidade', 'diccao', 'lideranca', 'relacionamento', 'etica', 'produtividade', 'eficiencia']
            for idx, attr in enumerate(attrs): setattr(nova, attr, notas_float[idx])
            db.session.add(nova)

        db.session.commit()
        
        # --- ESPIÃƒO: SALVOU FADA ---
        school_id = UserService.get_current_school_id()
        LogService.log(
            action="Salvou AvaliaÃ§Ã£o FADA",
            details=f"O rascunho da FADA para o aluno ID {aluno_id} foi salvo/atualizado. MÃ©dia: {media:.4f}",
            school_id=school_id
        )
        # ---------------------------
        
        flash(f"AvaliaÃ§Ã£o salva com sucesso. MÃ©dia: {media:.4f}", "success")
    except Exception as e:
        db.session.rollback(); logger.error(f"Erro ao salvar FADA: {e}"); flash(f"Erro ao salvar avaliaÃ§Ã£o: {e}", "danger")

    return redirect(url_for('justica.fada_boletim'))

@justica_bp.route('/fada/enviar-comissao/<int:fada_id>', methods=['POST'])
@login_required
@can_manage_justice_required
def enviar_fada_comissao(fada_id):
    f = db.session.get(FadaAvaliacao, fada_id)
    # UNIFICAÃ‡ÃƒO: Apenas FADAs em 'RASCUNHO' podem ser enviadas.
    if f and f.status == 'RASCUNHO':
        aat, ndisc, _ = JusticaService.calcular_aat_final(f.aluno_id)
        f.ndisc_snapshot = ndisc
        f.aat_snapshot = aat
        # UNIFICAÃ‡ÃƒO: A mÃ¡quina de estados avanÃ§a para 'COMISSAO'
        f.status = 'COMISSAO'
        f.data_envio = datetime.now().astimezone()
        db.session.commit()
        
        # --- ESPIÃƒO: FADA PARA COMISSÃƒO ---
        school_id = UserService.get_current_school_id()
        LogService.log(
            action="Enviou FADA para ComissÃ£o",
            details=f"A avaliaÃ§Ã£o FADA ID {fada_id} foi enviada para colheita de assinaturas.",
            school_id=school_id
        )
        # ----------------------------------
        
        return jsonify({'success': True})
    return jsonify({'error': 'AvaliaÃ§Ã£o nÃ£o encontrada ou nÃ£o estÃ¡ em modo Rascunho.'}), 404

@justica_bp.route('/fada/assinar-membro/<int:fada_id>', methods=['POST'])
@login_required
def assinar_fada_membro(fada_id):
    fada = db.session.get(FadaAvaliacao, fada_id)
    if not fada or fada.status != 'COMISSAO':
        flash('AvaliaÃ§Ã£o nÃ£o encontrada ou nÃ£o estÃ¡ na etapa da comissÃ£o.', 'danger')
        return redirect(url_for('justica.fada_boletim'))

    uid = current_user.id
    import hashlib, uuid
    hash_assinatura = hashlib.sha256(f"MEMBRO-{uid}-{fada.id}-{uuid.uuid4()}".encode()).hexdigest()[:20].upper()

    agora = datetime.now().astimezone()

    assinou_algum = False
    if fada.presidente_id == uid and not fada.hash_pres:
        fada.hash_pres = hash_assinatura; fada.data_ass_pres = agora
        assinou_algum = True
    if fada.membro1_id == uid and not fada.hash_m1:
        fada.hash_m1 = hash_assinatura; fada.data_ass_m1 = agora
        assinou_algum = True
    if fada.membro2_id == uid and not fada.hash_m2:
        fada.hash_m2 = hash_assinatura; fada.data_ass_m2 = agora
        assinou_algum = True

    if not assinou_algum:
        flash("Você já assinou ou não faz parte da comissão.", "warning")
        return redirect(url_for("justica.fada_boletim"))
        fada.hash_pres = hash_assinatura; fada.data_ass_pres = agora
    elif fada.membro1_id == uid:
        if fada.hash_m1:
            flash('Membro 1 jÃ¡ assinou.', 'warning')
            return redirect(url_for('justica.fada_boletim'))
        fada.hash_m1 = hash_assinatura; fada.data_ass_m1 = agora
    elif fada.membro2_id == uid:
        if fada.hash_m2:
            flash('Membro 2 jÃ¡ assinou.', 'warning')
            return redirect(url_for('justica.fada_boletim'))
        fada.hash_m2 = hash_assinatura; fada.data_ass_m2 = agora
    else:
        flash('NÃ£o autorizado. O usuÃ¡rio nÃ£o faz parte da comissÃ£o.', 'danger')
        return redirect(url_for('justica.fada_boletim'))

    if fada.hash_pres and fada.hash_m1 and fada.hash_m2:
        fada.status = 'ALUNO'

    db.session.commit()
    
    school_id = UserService.get_current_school_id()
    LogService.log(
        action="Assinou FADA (ComissÃ£o)",
        details=f"Um membro da comissÃ£o registrou sua assinatura digital na FADA ID {fada_id}.",
        school_id=school_id
    )
    
    flash('Assinatura registrada com sucesso.', 'success')
    return redirect(url_for('justica.fada_boletim'))

@justica_bp.route('/fada/assinar-aluno/<int:fada_id>', methods=['POST'])
@login_required
def assinar_fada_aluno(fada_id):
    f = db.session.get(FadaAvaliacao, fada_id)
    # UNIFICAÃ‡ÃƒO: A verificaÃ§Ã£o agora Ã© feita na coluna 'status'
    if f.status != 'ALUNO':
        return jsonify({'error': 'Esta avaliaÃ§Ã£o nÃ£o estÃ¡ aguardando sua assinatura.'}), 400

    if request.form.get('acao') == 'assinar':
        f.status = 'FINALIZADO'
        f.data_assinatura = datetime.now().astimezone(); f.ip_assinatura = request.remote_addr
        f.hash_integridade = hashlib.sha256(f"FINAL-{f.id}-{uuid.uuid4()}".encode()).hexdigest()[:20].upper()
        
        # --- INTEGRAÃ‡ÃƒO COM O BOLETIM ---
        try:
            # Importa os modelos necessÃ¡rios aqui para evitar import circular, se for o caso
            from backend.models.disciplina import Disciplina
            from backend.models.historico_disciplina import HistoricoDisciplina
            from backend.models.aluno import Aluno
            
            aluno_obj = db.session.get(Aluno, f.aluno_id)
            if aluno_obj:
                # Procura a disciplina "AvaliaÃ§Ã£o Atitudinal" vinculada Ã  turma deste aluno
                disciplina_aat = db.session.scalar(
                    select(Disciplina).where(
                        Disciplina.turma_id == aluno_obj.turma_id,
                        Disciplina.materia == 'AvaliaÃ§Ã£o Atitudinal'
                    )
                )
                
                if disciplina_aat:
                    # Verifica se o aluno jÃ¡ tem um histÃ³rico para essa disciplina
                    hist = db.session.scalar(
                        select(HistoricoDisciplina).where(
                            HistoricoDisciplina.aluno_id == aluno_obj.id,
                            HistoricoDisciplina.disciplina_id == disciplina_aat.id
                        )
                    )
                    
                    if hist:
                        hist.nota_final = f.aat_snapshot
                    else:
                        novo_hist = HistoricoDisciplina(
                            aluno_id=aluno_obj.id,
                            disciplina_id=disciplina_aat.id,
                            nota_final=f.aat_snapshot
                        )
                        db.session.add(novo_hist)
        except Exception as e:
            logger.error(f"Erro ao injetar nota da FADA no boletim: {e}")
        # --------------------------------
        
        flash("Assinado com sucesso. Nota lanÃ§ada no boletim (se a disciplina estiver cadastrada).", "success")
    else:
        f.status = 'RECURSO'
        f.texto_recurso = request.form.get('motivo_recurso')
        f.data_assinatura = datetime.now().astimezone()
        flash("Recurso enviado.", "warning")

    db.session.commit()
    
    # --- ESPIÃƒO: ALUNO AÃ‡ÃƒO FADA ---
    school_id = UserService.get_current_school_id()
    if not school_id and (str(current_user.role).lower().strip() == 'aluno' or (current_user.aluno_profile is not None and not current_user.is_staff)):
        school_id = current_user.aluno_profile.turma.school_id
        
    LogService.log(
        action="Assinou/Recorreu FADA",
        details=f"O aluno interagiu com a FADA ID {fada_id}. Novo Status: {f.status}",
        school_id=school_id
    )
    # -------------------------------
    
    return redirect(url_for('justica.index'))

@justica_bp.route('/api/infracoes-pendentes/<int:aluno_id>')
@login_required
def api_infracoes_pendentes(aluno_id):
    aluno = db.session.get(Aluno, aluno_id)
    dt_inicio, dt_limite = JusticaService.get_datas_limites(aluno.turma_id)
    processos = db.session.scalars(select(ProcessoDisciplina).where(ProcessoDisciplina.aluno_id==aluno_id, ProcessoDisciplina.status==StatusProcesso.FINALIZADO.value, ProcessoDisciplina.decisao_final != 'Justificado')).all()
    res = []
    for p in processos:
        if JusticaService.verificar_elegibilidade_punicao(p, dt_inicio, dt_limite):
            res.append({'id': p.id, 'descricao': p.codigo_infracao, 'pontos': p.pontos})
    return jsonify(res)

@justica_bp.route('/api/alunos-por-turma/<int:turma_id>')
@login_required
def get_alunos_turma(turma_id):
    alunos = db.session.scalars(select(Aluno).join(User).where(Aluno.turma_id==turma_id).order_by(User.nome_completo)).all()
    return jsonify([{'id': a.id, 'nome': a.user.nome_completo, 'graduacao': a.user.posto_graduacao or ''} for a in alunos])

@justica_bp.route('/api/aluno-details/<int:aluno_id>')
@login_required
def get_aluno_details(aluno_id):
    a = db.session.get(Aluno, aluno_id)
    return jsonify({'nome_completo': a.user.nome_completo, 'matricula': a.user.matricula, 'posto_graduacao': a.user.posto_graduacao}) if a else jsonify({})

@justica_bp.route('/anular-processo/<int:pid>', methods=['POST'])
@login_required
@can_manage_justice_required
def anular_processo(pid):
    processo = db.session.get(ProcessoDisciplina, pid)
    if not processo:
        flash("Processo nÃ£o encontrado.", "error")
        return redirect(url_for('justica.index'))

    motivo = request.form.get('motivo_anulacao')
    if not motivo or len(motivo.strip()) < 10:
        flash("A motivaÃ§Ã£o da anulaÃ§Ã£o deve ter no mÃ­nimo 10 caracteres.", "warning")
        return redirect(url_for('justica.index'))

    # Cria o carimbo de auditoria
    data_atual = datetime.now().strftime('%d/%m/%Y %H:%M')
    nota_anulacao = f"\n\n[PROCESSO EXCLUÃDO/ANULADO NO SISTEMA]\nData: {data_atual}\nResponsÃ¡vel: {current_user.nome_completo}\nMotivo da AnulaÃ§Ã£o: {motivo.strip()}"

    if processo.observacao_decisao and processo.observacao_decisao != 'None':
        processo.observacao_decisao += nota_anulacao
    else:
        processo.observacao_decisao = nota_anulacao

    # Zera as puniÃ§Ãµes, devolve pontos e muda o status
    processo.status = StatusProcesso.ARQUIVADO.value
    processo.decisao_final = 'EXCLUIDO_ANULADO'
    processo.tipo_sancao = None
    processo.detalhes_sancao = None
    processo.pontos = 0.0

    db.session.commit()
    
    # --- ESPIÃƒO: ANULAR PROCESSO ---
    school_id = UserService.get_current_school_id()
    LogService.log(
        action="Anulou Processo Disciplinar",
        details=f"O administrador anulou o processo ID {processo.id}. Motivo: {motivo.strip()}",
        school_id=school_id
    )
    # -------------------------------

    flash(f"Processo NÂº {processo.id} anulado com sucesso. O registro foi salvo no histÃ³rico.", "success")
    return redirect(url_for('justica.index'))

@justica_bp.route('/fada/exportar-pdf/<int:fada_id>')
@login_required
def exportar_fada_pdf(fada_id):
    fada = db.session.get(FadaAvaliacao, fada_id)
    if not fada:
        flash("AvaliaÃ§Ã£o nÃ£o encontrada.", "danger")
        return redirect(url_for('justica.fada_boletim'))
        
    if fada.status != 'FINALIZADO':
        flash("O PDF sÃ³ pode ser gerado apÃ³s o documento ser FINALIZADO (Assinado por todos).", "warning")
        return redirect(url_for('justica.fada_boletim'))
        
    aluno = db.session.get(Aluno, fada.aluno_id)
    escola = aluno.turma.school if aluno.turma else None
    
    html = render_template(
        'justica/fada_pdf.html',
        fada=fada,
        aluno=aluno,
        escola=escola,
        now=datetime.now().astimezone()
    )
    
    # Em vez de write_pdf() diretamente, mandamos pra fila
    pdf_name = f"fada_{fada_id}.pdf"
    job_id = str(uuid.uuid4())
    job = BackgroundJob(
        id=job_id,
        task_type='generate_pdf',
        payload=html,
        meta_data=json.dumps({"filename": pdf_name}),
        user_id=current_user.id
    )
    db.session.add(job)
    db.session.commit()
    
    return jsonify({'success': True, 'job_id': job_id})