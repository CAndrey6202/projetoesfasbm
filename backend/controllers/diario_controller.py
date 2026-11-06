from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify, session
from flask_login import login_required, current_user
from datetime import datetime
import os
import sys

from ..services.diario_service import DiarioService
from ..services.user_service import UserService
from ..services.log_service import LogService # <--- ESPIÃO IMPORTADO AQUI
from utils.image_utils import compress_image_to_memory, allowed_file

diario_bp = Blueprint('diario', __name__, url_prefix='/diario-classe')

@diario_bp.route('/instrutor/pendentes')
@login_required
def listar_pendentes():
    school_id = UserService.get_current_school_id()
    if not school_id:
        flash("Escola não selecionada.", "warning")
        return redirect(url_for('main.dashboard'))

    status = request.args.get('status', 'pendente')
    turma_id = request.args.get('turma_id', type=int)
    disciplina_id = request.args.get('disciplina_id', type=int)
    page = request.args.get('page', 1, type=int)
    
    diarios_agrupados, pagination = DiarioService.get_diarios_agrupados(
        school_id=school_id,
        user_id=current_user.id, 
        turma_id=turma_id,
        disciplina_id=disciplina_id,
        status=status,
        page=page,
        per_page=30
    )
    
    turmas, disciplinas = DiarioService.get_filtros_disponiveis(school_id, current_user.id, turma_id)
    
    return render_template('diario/instrutor_listar.html', 
                           diarios=diarios_agrupados, 
                           pagination=pagination,
                           turmas=turmas,
                           disciplinas=disciplinas,
                           sel_status=status,
                           sel_turma=turma_id,
                           sel_disciplina=disciplina_id)

@diario_bp.route('/instrutor/assinar/<int:diario_id>', methods=['GET', 'POST'])
@login_required
def assinar(diario_id):
    from ..models.database import db
    from ..models.diario_classe import DiarioClasse
    from ..models.aluno import Aluno
    from ..models.user import User

    if request.method == 'POST':
        content_length = request.content_length
        print(f"DEBUG SISGEN: Recebendo POST para Diário {diario_id}. Tamanho total: {content_length} bytes", file=sys.stderr)
        
        if content_length and content_length > 2 * 1024 * 1024:
            print(f"ALERTA SISGEN: Requisição muito grande detectada: {content_length / 1024 / 1024:.2f} MB", file=sys.stderr)

    diario, instrutor = DiarioService.get_diario_para_assinatura(diario_id, current_user.id)
    
    if not diario:
        flash("Diário não encontrado, já assinado ou você não tem permissão para acessá-lo.", "danger")
        return redirect(url_for('diario.listar_pendentes'))

    diarios_bloco = db.session.scalars(
        db.select(DiarioClasse).where(
            DiarioClasse.data_aula == diario.data_aula,
            DiarioClasse.turma_id == diario.turma_id,
            DiarioClasse.disciplina_id == diario.disciplina_id,
            DiarioClasse.is_deleted == False,
            DiarioClasse.status == 'pendente'
        ).options(db.joinedload(DiarioClasse.frequencias))
        .order_by(DiarioClasse.periodo, DiarioClasse.id)
    ).unique().all()

    if not diarios_bloco:
        flash("Este bloco de diários já foi assinado ou não está disponível para edição.", "info")
        return redirect(url_for('diario.listar_pendentes'))

    from ..services.turma_service import TurmaService
    alunos_query = TurmaService.get_alunos_da_turma_no_ciclo(
        turma_id=diario.turma_id,
        ciclo_id=diario.disciplina.ciclo_id if diario.disciplina else None,
        diarios_bloco=diarios_bloco
    )

    freq_map = {}
    for a in alunos_query:
        freq_map[a.id] = {}
        for d in diarios_bloco:
            freq_map[a.id][d.id] = True
            
    for d in diarios_bloco:
        for f in d.frequencias:
            if f.aluno_id in freq_map:
                freq_map[f.aluno_id][d.id] = f.presente

    if request.method == 'POST':
        tipo = request.form.get('tipo_assinatura')
        salvar = request.form.get('salvar_padrao') == 'on'
        conteudo_ministrado = request.form.get('conteudo_ministrado')
        observacoes = request.form.get('observacoes')
        
        dados = None
        if tipo == 'canvas': 
            dados = request.form.get('assinatura_base64')
        elif tipo == 'upload': 
            arquivo = request.files.get('assinatura_upload')
            if arquivo and allowed_file(arquivo.filename, arquivo.stream, ['png', 'jpg', 'jpeg']):
                dados = compress_image_to_memory(arquivo, max_size=(256, 256), quality=60)
            else:
                flash("Arquivo de assinatura inválido ou não enviado.", "danger")
                return redirect(request.url)
        elif tipo == 'padrao': 
            dados = True

        frequencias_atualizadas = {}
        for d in diarios_bloco:
            frequencias_atualizadas[d.id] = {}
            for a in alunos_query:
                campo_name = f"presenca_{a.id}_{d.id}"
                frequencias_atualizadas[d.id][a.id] = (request.form.get(campo_name) == '1')

        ok, msg = DiarioService.assinar_diario(
            diario_id=diario.id, 
            user_id=current_user.id, 
            tipo_assinatura=tipo, 
            dados_assinatura=dados, 
            salvar_padrao=salvar,
            conteudo_atualizado=conteudo_ministrado,
            observacoes_atualizadas=observacoes,
            frequencias_atualizadas=frequencias_atualizadas 
        )
        
        if ok:
            # --- ESPIÃO: INSTRUTOR ASSINOU DIÁRIO ---
            school_id = UserService.get_current_school_id()
            LogService.log(
                action="Assinou Diário",
                details=f"O instrutor assinou o diário ID {diario.id} da disciplina '{diario.disciplina.materia if diario.disciplina else 'N/D'}'.",
                school_id=school_id
            )
            # ----------------------------------------
            flash(msg, "success")
            return redirect(url_for('diario.listar_pendentes', status='assinado'))
        else:
            flash(msg, "danger")

    return render_template('diario/instrutor_assinar.html', 
                           diario=diario, 
                           instrutor=instrutor, 
                           diarios_bloco=diarios_bloco, 
                           alunos_list=alunos_query, 
                           freq_map=freq_map)

@diario_bp.route('/instrutor/devolver/<int:diario_id>', methods=['POST'])
@login_required
def devolver_aluno(diario_id):
    # Verifica se o usuário atual é realmente um instrutor do sistema
    instrutor = DiarioService.get_current_instrutor(current_user.id)
    if not instrutor:
        flash("Acesso negado. Apenas instrutores podem devolver diários.", "danger")
        return redirect(url_for('diario.listar_pendentes'))

    motivo = request.form.get('motivo_devolucao', 'Correção de períodos necessária.')
    
    ok, msg = DiarioService.devolver_diario_aluno(diario_id, current_user, motivo)
    
    if ok:
        # --- ESPIÃO: INSTRUTOR DEVOLVEU DIÁRIO ---
        school_id = UserService.get_current_school_id()
        LogService.log(
            action="Devolveu Diário",
            details=f"O instrutor devolveu o diário ID {diario_id} para o Chefe de Turma. Motivo: {motivo}",
            school_id=school_id
        )
        # -----------------------------------------
        flash(msg, "success")
    else:
        flash(msg, "danger")
        
    return redirect(url_for('diario.listar_pendentes'))

@diario_bp.route('/faltas-por-dia', methods=['GET'])
@login_required
def faltas_por_dia():
    from ..models.database import db
    from ..models.diario_classe import DiarioClasse
    from ..models.frequencia import FrequenciaAluno
    from ..models.aluno import Aluno
    from ..models.turma import Turma
    from ..models.user import User
    from ..models.disciplina import Disciplina

    school_id = UserService.get_current_school_id()
    if not school_id:
        return jsonify({"success": False, "message": "Escola não selecionada."}), 403

    data_str = request.args.get('data')
    if not data_str:
        return jsonify({"success": False, "message": "Data não fornecida."}), 400

    try:
        data_busca = datetime.strptime(data_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({"success": False, "message": "Formato de data inválido."}), 400

    try:
        faltas_query = db.session.query(
            FrequenciaAluno.id,
            User.nome_completo,
            User.nome_de_guerra.label('nome_guerra'),
            Aluno.num_aluno.label('numero_aluno'),
            Turma.nome.label('turma_nome'),
            DiarioClasse.periodo,
            FrequenciaAluno.justificativa,
            Disciplina.materia.label('materia_nome')
        ).select_from(FrequenciaAluno).join(
            DiarioClasse, FrequenciaAluno.diario_id == DiarioClasse.id
        ).join(
            Aluno, FrequenciaAluno.aluno_id == Aluno.id
        ).join(
            User, Aluno.user_id == User.id
        ).join(
            Turma, DiarioClasse.turma_id == Turma.id
        ).join(
            Disciplina, DiarioClasse.disciplina_id == Disciplina.id 
        ).filter(
            Turma.school_id == school_id,
            Turma.edicao_id == session.get('active_edicao_id'),
            DiarioClasse.data_aula == data_busca,
            DiarioClasse.is_deleted == False,
            FrequenciaAluno.presente == False
        ).order_by(
            Turma.nome,
            User.nome_completo
        ).all()

        resultado_agrupado = {}
        for falta in faltas_query:
            turma = falta.turma_nome
            if turma not in resultado_agrupado:
                resultado_agrupado[turma] = []
            
            resultado_agrupado[turma].append({
                "id_frequencia": falta.id,
                "numero_aluno": falta.numero_aluno,
                "nome_completo": falta.nome_completo,
                "nome_guerra": falta.nome_guerra,
                "periodo": falta.periodo,
                "justificativa": falta.justificativa,
                "materia": falta.materia_nome
            })

        return jsonify({
            "success": True, 
            "data_consulta": data_str,
            "faltas": resultado_agrupado
        })
    except Exception as e:
        return jsonify({"success": False, "message": f"Falha ao consultar banco de dados: {str(e)}"}), 500

@diario_bp.route('/admin/lixeira', methods=['GET'])
@login_required
def listar_lixeira():
    if not (current_user.is_sens or current_user.is_admin_escola):
        flash("Acesso negado.", "danger")
        return redirect(url_for('main.dashboard'))
        
    from ..models.database import db
    from ..models.diario_classe import DiarioClasse
    from ..models.turma import Turma
    
    school_id = UserService.get_current_school_id()
    if not school_id:
        flash("Escola não selecionada.", "warning")
        return redirect(url_for('main.dashboard'))

    diarios_apagados = db.session.scalars(
        db.select(DiarioClasse)
        .join(Turma, DiarioClasse.turma_id == Turma.id)
        .where(
            Turma.school_id == school_id,
            Turma.edicao_id == session.get('active_edicao_id'),
            DiarioClasse.is_deleted == True
        ).options(
            db.joinedload(DiarioClasse.turma),
            db.joinedload(DiarioClasse.disciplina)
        )
        .order_by(DiarioClasse.data_aula.desc(), DiarioClasse.turma_id, DiarioClasse.disciplina_id, DiarioClasse.periodo.asc())
    ).unique().all()
    
    grouped = []
    if diarios_apagados:
        curr_group = [diarios_apagados[0]]
        for i in range(1, len(diarios_apagados)):
            curr = diarios_apagados[i]
            prev = curr_group[-1]
            
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
                curr_group.append(curr)
            else:
                grouped.append(curr_group)
                curr_group = [curr]
                
        if curr_group:
            grouped.append(curr_group)
            
    lista_view = []
    for g in grouped:
        rep = g[0]
        first_p = g[0].periodo
        last_p = g[-1].periodo
        
        if first_p is None:
            per_str = "N/D"
        elif first_p == last_p:
            per_str = f"{first_p}º"
        else:
            per_str = f"{first_p}º a {last_p}º"
            
        lista_view.append({
            'id': rep.id,
            'data_aula': rep.data_aula,
            'turma_nome': rep.turma.nome if rep.turma else 'N/D',
            'disciplina_nome': rep.disciplina.materia if rep.disciplina else 'N/D',
            'periodos': per_str,
            'qtd_aulas': len(g)
        })

    return render_template('diario/admin_lixeira.html', lixeira=lista_view)

@diario_bp.route('/admin/restaurar/<int:diario_id>', methods=['POST'])
@login_required
def restaurar(diario_id):
    if not (current_user.is_sens or current_user.is_admin_escola):
        return jsonify({"success": False, "message": "Acesso negado"}), 403
        
    ok, msg = DiarioService.restaurar_diario_admin(diario_id, current_user)
    if ok:
        # --- ESPIÃO: ADMIN RESTAUROU DIÁRIO DA LIXEIRA ---
        school_id = UserService.get_current_school_id()
        LogService.log(
            action="Restaurou Diário",
            details=f"O administrador restaurou da lixeira o bloco contendo o diário ID {diario_id}.",
            school_id=school_id
        )
        # -------------------------------------------------
        flash(msg, "success")
    else:
        flash(msg, "danger")
    return redirect(url_for('diario.listar_lixeira'))


def _get_dia_semana_str(data_obj):
    dias = ['segunda', 'terca', 'quarta', 'quinta', 'sexta', 'sabado', 'domingo']
    return dias[data_obj.weekday()]

def _get_variacoes_nome_turma(nome_original):
    import re
    variacoes = {nome_original}
    try:
        match = re.search(r'(\d+)', nome_original or '')
        if match:
            num_str = match.group(1)
            num_int = int(num_str)
            variacoes.add(f"Turma {num_str}")
            variacoes.add(f"Turma {num_int}")
            variacoes.add(f"{num_str}º Pelotão")
            variacoes.add(f"{num_int}º Pelotão")
            variacoes.add(str(num_int))
    except Exception:
        pass
    return list(variacoes)

def _resolve_turma_horario(h, turmas_escola):
    if h.disciplina and h.disciplina.turma:
        variacoes_disc = _get_variacoes_nome_turma(h.disciplina.turma.nome)
        if not h.pelotao or h.pelotao == h.disciplina.turma.nome or h.pelotao in variacoes_disc:
            return h.disciplina.turma
    if h.pelotao and turmas_escola:
        for t in turmas_escola:
            if h.pelotao == t.nome or h.pelotao in _get_variacoes_nome_turma(t.nome):
                return t
    return h.disciplina.turma if h.disciplina else None


@diario_bp.route('/instrutor/gerar-diarios')
@login_required
def gerar_diarios():
    from sqlalchemy import select, or_
    from sqlalchemy.orm import joinedload
    from ..models.database import db
    from ..models.horario import Horario
    from ..models.diario_classe import DiarioClasse
    from ..models.semana import Semana
    from ..models.ciclo import Ciclo
    from ..models.disciplina import Disciplina
    from ..models.disciplina_turma import DisciplinaTurma
    from ..models.turma import Turma
    from ..models.instrutor import Instrutor

    school_id = UserService.get_current_school_id()
    if not school_id:
        flash("Escola não selecionada.", "warning")
        return redirect(url_for('main.dashboard'))

    try:
        aulas_agrupadas = []
        data_str = request.args.get('data')
        turma_id_filtro = request.args.get('turma_id', type=int)
        data_hoje = DiarioService.get_agora_brasilia().date()
        data_selecionada = datetime.strptime(data_str, '%Y-%m-%d').date() if data_str else data_hoje

        active_edicao = session.get('active_edicao_id')

        stmt_turmas = select(Turma).where(Turma.school_id == school_id)
        if active_edicao:
            stmt_turmas = stmt_turmas.where(or_(Turma.edicao_id == active_edicao, Turma.edicao_id.is_(None)))
        turmas_escola = db.session.scalars(stmt_turmas.order_by(Turma.nome)).all()

        instrutor_ids = DiarioService.get_current_instrutor_ids(current_user.id, school_id)
        is_admin_or_sens = (
            getattr(current_user, 'is_sens', False) or 
            getattr(current_user, 'is_admin_escola', False) or 
            getattr(current_user, 'is_super_admin', False)
        )

        if not instrutor_ids and not is_admin_or_sens:
            flash("Perfil de instrutor não encontrado para sua conta nesta escola.", "warning")
            return redirect(url_for('diario.listar_pendentes'))

        stmt_semanas = db.session.query(Semana).join(Ciclo).filter(
            Ciclo.school_id == school_id,
            Semana.data_inicio <= data_selecionada,
            Semana.data_fim >= data_selecionada
        )
        if active_edicao:
            stmt_semanas = stmt_semanas.filter(or_(Ciclo.edicao_id == active_edicao, Ciclo.edicao_id.is_(None)))
        semanas_ativas = stmt_semanas.all()

        if not semanas_ativas:
            stmt_fallback = db.session.query(Semana).join(Ciclo).filter(
                Ciclo.school_id == school_id,
                Semana.data_inicio <= data_selecionada
            )
            if active_edicao:
                stmt_fallback = stmt_fallback.filter(or_(Ciclo.edicao_id == active_edicao, Ciclo.edicao_id.is_(None)))
            fallback_semana = stmt_fallback.order_by(Semana.data_inicio.desc()).first()
            if fallback_semana:
                semanas_ativas = [fallback_semana]
            else:
                return render_template(
                    'diario/instrutor_gerar_painel.html',
                    aulas_agrupadas=[],
                    data_selecionada=data_selecionada,
                    turmas=turmas_escola,
                    sel_turma=turma_id_filtro,
                    erro_semana=True
                )

        semana_ids = [s.id for s in semanas_ativas]
        dia_str = _get_dia_semana_str(data_selecionada)

        query = db.session.query(Horario)\
            .outerjoin(Horario.disciplina)\
            .outerjoin(Disciplina.turma)\
            .options(
                joinedload(Horario.disciplina).joinedload(Disciplina.turma),
                joinedload(Horario.instrutor).joinedload(Instrutor.user),
                joinedload(Horario.instrutor_2).joinedload(Instrutor.user)
            ).filter(
                Turma.school_id == school_id,
                Horario.semana_id.in_(semana_ids),
                Horario.dia_semana.ilike(f"{dia_str}%")
            )

        if active_edicao:
            query = query.filter(or_(Turma.edicao_id == active_edicao, Turma.edicao_id.is_(None)))

        if instrutor_ids:
            disc_ids_vinculadas = [d for d in db.session.scalars(
                select(DisciplinaTurma.disciplina_id).where(
                    or_(
                        DisciplinaTurma.instrutor_id_1.in_(instrutor_ids),
                        DisciplinaTurma.instrutor_id_2.in_(instrutor_ids)
                    )
                )
            ).all() if d is not None]
            condicoes_instrutor = [
                Horario.instrutor_id.in_(instrutor_ids),
                Horario.instrutor_id_2.in_(instrutor_ids)
            ]
            if disc_ids_vinculadas:
                condicoes_instrutor.append(Horario.disciplina_id.in_(disc_ids_vinculadas))
            query = query.filter(or_(*condicoes_instrutor))

        horarios = query.order_by(Horario.periodo, Horario.id).all()

        flat_periods = []
        seen_periods = set()

        for h in horarios:
            if not h.disciplina:
                continue
            turma_obj = _resolve_turma_horario(h, turmas_escola)
            if not turma_obj:
                continue
            if turma_id_filtro and turma_obj.id != turma_id_filtro:
                continue

            dur = h.duracao if h.duracao and h.duracao > 0 else 1
            for i in range(dur):
                p = h.periodo + i
                key = f"{turma_obj.id}_{h.disciplina_id}_{p}"
                if key not in seen_periods:
                    flat_periods.append({
                        'periodo': p,
                        'obj': h,
                        'disc_id': h.disciplina_id,
                        'turma_id': turma_obj.id,
                        'turma': turma_obj,
                        'instrutor': h.instrutor
                    })
                    seen_periods.add(key)

        # Agrupa tempos consecutivos da mesma turma e mesma disciplina
        flat_periods.sort(key=lambda x: (x['turma_id'], x['disc_id'], x['periodo']))

        blocos = []
        current_block = None

        for fp in flat_periods:
            nome_instrutor = current_user.nome_de_guerra or current_user.nome_completo
            if fp['instrutor']:
                if hasattr(fp['instrutor'], 'user') and fp['instrutor'].user:
                    nome_instrutor = fp['instrutor'].user.nome_de_guerra or fp['instrutor'].user.nome_completo
                elif hasattr(fp['instrutor'], 'nome_guerra'):
                    nome_instrutor = fp['instrutor'].nome_guerra

            if not current_block:
                current_block = {
                    'disciplina': fp['obj'].disciplina,
                    'disc_id': fp['disc_id'],
                    'turma': fp['turma'],
                    'turma_id': fp['turma_id'],
                    'nome_instrutor': nome_instrutor,
                    'horarios_reais': [fp['obj']],
                    'periodos_expandidos': [fp['periodo']],
                    'status': 'pendente',
                    'primeiro_horario_id': fp['obj'].id,
                    'total_tempos': 1,
                    'last_p': fp['periodo']
                }
            else:
                if (fp['turma_id'] == current_block['turma_id'] and 
                    fp['disc_id'] == current_block['disc_id'] and 
                    fp['periodo'] == current_block['last_p'] + 1):
                    current_block['periodos_expandidos'].append(fp['periodo'])
                    current_block['last_p'] = fp['periodo']
                    if fp['obj'] not in current_block['horarios_reais']:
                        current_block['horarios_reais'].append(fp['obj'])
                    current_block['total_tempos'] += 1
                else:
                    blocos.append(current_block)
                    current_block = {
                        'disciplina': fp['obj'].disciplina,
                        'disc_id': fp['disc_id'],
                        'turma': fp['turma'],
                        'turma_id': fp['turma_id'],
                        'nome_instrutor': nome_instrutor,
                        'horarios_reais': [fp['obj']],
                        'periodos_expandidos': [fp['periodo']],
                        'status': 'pendente',
                        'primeiro_horario_id': fp['obj'].id,
                        'total_tempos': 1,
                        'last_p': fp['periodo']
                    }

        if current_block:
            blocos.append(current_block)

        turma_ids_dia = list({b['turma_id'] for b in blocos})
        diarios_hoje = []
        if turma_ids_dia:
            diarios_hoje = db.session.query(DiarioClasse).filter(
                DiarioClasse.data_aula == data_selecionada,
                DiarioClasse.turma_id.in_(turma_ids_dia),
                DiarioClasse.is_deleted == False
            ).order_by(DiarioClasse.periodo, DiarioClasse.id).all()

        aulas_concluidas_map = {}
        for d in diarios_hoje:
            if d.periodo:
                aulas_concluidas_map[f"{d.turma_id}_{d.disciplina_id}_{d.periodo}"] = d
            else:
                aulas_concluidas_map[f"{d.turma_id}_{d.disciplina_id}_legacy"] = d

        for b in blocos:
            b['periodos'] = sorted(list(set(b['periodos_expandidos'])))
            b['tempos_concluidos'] = 0
            b['diario_pendente_id'] = None
            b['todos_assinados'] = True

            for p in b['periodos']:
                key = f"{b['turma_id']}_{b['disc_id']}_{p}"
                legacy_key = f"{b['turma_id']}_{b['disc_id']}_legacy"
                d_obj = aulas_concluidas_map.get(key) or aulas_concluidas_map.get(legacy_key)
                if d_obj:
                    b['tempos_concluidos'] += 1
                    if d_obj.status == 'pendente' and not b['diario_pendente_id']:
                        b['diario_pendente_id'] = d_obj.id
                    if d_obj.status != 'assinado':
                        b['todos_assinados'] = False
                else:
                    b['todos_assinados'] = False

            if b['tempos_concluidos'] >= b['total_tempos'] and b['total_tempos'] > 0:
                b['status'] = 'concluido'

            aulas_agrupadas.append(b)

        # Ordena cronologicamente pelo primeiro período do bloco
        aulas_agrupadas.sort(key=lambda b: (b['periodos'][0] if b['periodos'] else 0, b['turma'].nome))

        return render_template(
            'diario/instrutor_gerar_painel.html',
            aulas_agrupadas=aulas_agrupadas,
            data_selecionada=data_selecionada,
            turmas=turmas_escola,
            sel_turma=turma_id_filtro,
            erro_semana=False
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        flash(f"Erro ao carregar aulas do instrutor: {str(e)}", "danger")
        return redirect(url_for('diario.listar_pendentes'))


@diario_bp.route('/instrutor/registrar/<int:primeiro_horario_id>', methods=['GET', 'POST'])
@login_required
def registrar_aula_instrutor(primeiro_horario_id):
    from sqlalchemy import select, or_
    from ..models.database import db
    from ..models.horario import Horario
    from ..models.diario_classe import DiarioClasse
    from ..models.frequencia import FrequenciaAluno
    from ..models.disciplina import Disciplina
    from ..models.disciplina_turma import DisciplinaTurma
    from ..models.turma import Turma
    from ..models.aluno import Aluno
    from ..models.user import User
    from ..services.turma_service import TurmaService

    school_id = UserService.get_current_school_id()
    if not school_id:
        flash("Escola não selecionada.", "warning")
        return redirect(url_for('main.dashboard'))

    try:
        instrutor_ids = DiarioService.get_current_instrutor_ids(current_user.id, school_id)
        is_admin_or_sens = (
            getattr(current_user, 'is_sens', False) or 
            getattr(current_user, 'is_admin_escola', False) or 
            getattr(current_user, 'is_super_admin', False)
        )

        if not instrutor_ids and not is_admin_or_sens:
            flash("Acesso restrito a instrutores.", "danger")
            return redirect(url_for('diario.listar_pendentes'))

        horario_base = db.session.query(Horario)\
            .outerjoin(Horario.disciplina)\
            .outerjoin(Disciplina.turma)\
            .filter(
                Horario.id == primeiro_horario_id,
                Turma.school_id == school_id
            ).first()

        if not horario_base:
            flash("Horário não encontrado ou não pertence à sua escola.", "danger")
            return redirect(url_for('diario.gerar_diarios'))

        # Verifica se o instrutor tem vínculo com este horário/disciplina
        if not is_admin_or_sens:
            vinculo_disc = db.session.scalars(
                select(DisciplinaTurma).where(
                    DisciplinaTurma.disciplina_id == horario_base.disciplina_id,
                    or_(
                        DisciplinaTurma.instrutor_id_1.in_(instrutor_ids),
                        DisciplinaTurma.instrutor_id_2.in_(instrutor_ids)
                    )
                )
            ).first()
            tem_permissao = (
                horario_base.instrutor_id in instrutor_ids or
                horario_base.instrutor_id_2 in instrutor_ids or
                vinculo_disc is not None
            )
            if not tem_permissao:
                flash("Você não possui vínculo como instrutor desta aula.", "danger")
                return redirect(url_for('diario.gerar_diarios'))

        data_str = request.args.get('data')
        data_hoje = DiarioService.get_agora_brasilia().date()
        data_aula = datetime.strptime(data_str, '%Y-%m-%d').date() if data_str else data_hoje

        active_edicao = session.get('active_edicao_id')
        stmt_turmas = select(Turma).where(Turma.school_id == school_id)
        if active_edicao:
            stmt_turmas = stmt_turmas.where(or_(Turma.edicao_id == active_edicao, Turma.edicao_id.is_(None)))
        turmas_escola = db.session.scalars(stmt_turmas).all()

        turma_obj = _resolve_turma_horario(horario_base, turmas_escola)
        if not turma_obj:
            flash("Turma não identificada para este horário.", "danger")
            return redirect(url_for('diario.gerar_diarios', data=data_aula))

        variacoes_nome = _get_variacoes_nome_turma(turma_obj.nome)

        horarios_db = db.session.query(Horario)\
            .outerjoin(Horario.disciplina)\
            .outerjoin(Disciplina.turma)\
            .filter(
                Turma.school_id == school_id,
                Horario.semana_id == horario_base.semana_id,
                Horario.dia_semana == horario_base.dia_semana,
                Horario.disciplina_id == horario_base.disciplina_id,
                or_(
                    Disciplina.turma_id == turma_obj.id,
                    Horario.pelotao == turma_obj.nome,
                    Horario.pelotao.in_(variacoes_nome)
                )
            ).order_by(Horario.periodo, Horario.id).all()

        flat_periods = []
        seen_p = set()
        for h in horarios_db:
            dur = h.duracao if h.duracao and h.duracao > 0 else 1
            for i in range(dur):
                p = h.periodo + i
                if p not in seen_p:
                    flat_periods.append({'periodo': p, 'obj': h})
                    seen_p.add(p)

        flat_periods.sort(key=lambda x: x['periodo'])

        blocos = []
        current_block = None
        for fp in flat_periods:
            if not current_block:
                current_block = {'horarios_reais': [fp['obj']], 'periodos_expandidos': [fp['periodo']], 'last_p': fp['periodo']}
            else:
                if fp['periodo'] == current_block['last_p'] + 1:
                    current_block['periodos_expandidos'].append(fp['periodo'])
                    current_block['last_p'] = fp['periodo']
                    if fp['obj'] not in current_block['horarios_reais']:
                        current_block['horarios_reais'].append(fp['obj'])
                else:
                    blocos.append(current_block)
                    current_block = {'horarios_reais': [fp['obj']], 'periodos_expandidos': [fp['periodo']], 'last_p': fp['periodo']}
        if current_block:
            blocos.append(current_block)

        target_block = None
        for b in blocos:
            if any(h.id == primeiro_horario_id for h in b['horarios_reais']):
                target_block = b
                break

        if not target_block:
            flash("Horário não encontrado nos blocos do dia.", "danger")
            return redirect(url_for('diario.gerar_diarios', data=data_aula))

        ultimo_periodo_real_do_bloco = target_block['last_p']

        horarios_expandidos = []
        periodos_processados = set()

        for p in target_block['periodos_expandidos']:
            horario_pai = next(h for h in target_block['horarios_reais'] if h.periodo <= p < h.periodo + (h.duracao or 1))

            existe = db.session.query(DiarioClasse).filter_by(
                data_aula=data_aula,
                turma_id=turma_obj.id,
                disciplina_id=horario_base.disciplina_id,
                periodo=p,
                is_deleted=False
            ).first()

            if not existe:
                if p not in periodos_processados:
                    horarios_expandidos.append({'periodo': p, 'horario_pai_id': horario_pai.id, 'obj': horario_pai})
                    periodos_processados.add(p)

        horarios_expandidos.sort(key=lambda x: x['periodo'])

        if not horarios_expandidos:
            flash("Todas as aulas desta disciplina já foram registradas para esta data.", "info")
            return redirect(url_for('diario.gerar_diarios', data=data_aula))

        alunos_turma = TurmaService.get_alunos_da_turma_no_ciclo(
            turma_id=turma_obj.id,
            ciclo_id=horario_base.disciplina.ciclo_id if horario_base.disciplina else None
        )
        if not alunos_turma:
            alunos_turma = db.session.query(Aluno).join(User, Aluno.user_id == User.id).filter(
                Aluno.turma_id == turma_obj.id
            ).order_by(
                Aluno.num_aluno,
                User.nome_de_guerra,
                User.nome_completo
            ).all()

        if request.method == 'POST':
            conteudo_informado = request.form.get('conteudo')
            acao_pos_salvar = request.form.get('acao_pos_salvar', 'salvar')

            ok_cont, msg_cont = DiarioService.validar_conteudo_obrigatorio(conteudo_informado)
            if not ok_cont:
                flash(msg_cont, "danger")
                return redirect(request.url)

            periodos_para_registrar = [h['periodo'] for h in horarios_expandidos]
            if periodos_para_registrar:
                ok_hora, msg_hora = DiarioService.validar_criacao_diario_aluno(data_aula, ultimo_periodo_real_do_bloco)
                if not ok_hora:
                    flash(msg_hora, "danger")
                    return redirect(request.url)

            try:
                ids_horarios_pais_atualizados = set()
                count_regs = 0
                primeiro_diario_criado_id = None

                for h_virt in horarios_expandidos:
                    periodo_atual = h_virt['periodo']
                    horario_pai = h_virt['obj']

                    ja_salvo_agora = db.session.query(DiarioClasse).filter_by(
                        data_aula=data_aula,
                        turma_id=turma_obj.id,
                        disciplina_id=horario_pai.disciplina_id,
                        periodo=periodo_atual,
                        is_deleted=False
                    ).first()

                    if ja_salvo_agora:
                        if not primeiro_diario_criado_id:
                            primeiro_diario_criado_id = ja_salvo_agora.id
                        continue

                    novo_diario = DiarioClasse(
                        data_aula=data_aula,
                        turma_id=turma_obj.id,
                        disciplina_id=horario_pai.disciplina_id,
                        responsavel_id=current_user.id,
                        observacoes=request.form.get('observacoes'),
                        conteudo_ministrado=conteudo_informado,
                        periodo=periodo_atual,
                        status='pendente'
                    )
                    db.session.add(novo_diario)
                    db.session.flush()

                    if not primeiro_diario_criado_id:
                        primeiro_diario_criado_id = novo_diario.id

                    for aluno in alunos_turma:
                        key = f"presenca_{aluno.id}_{periodo_atual}"
                        presente = request.form.get(key) == 'on'
                        db.session.add(FrequenciaAluno(diario_id=novo_diario.id, aluno_id=aluno.id, presente=presente))

                    if horario_pai.id not in ids_horarios_pais_atualizados:
                        horario_pai.status = 'concluido'
                        db.session.add(horario_pai)
                        ids_horarios_pais_atualizados.add(horario_pai.id)

                    count_regs += 1

                db.session.commit()

                if count_regs > 0:
                    LogService.log(
                        action="Registrou Frequência (Instrutor)",
                        details=f"O Instrutor salvou {count_regs} tempo(s) do diário da disciplina '{horario_base.disciplina.materia}' na turma '{turma_obj.nome}' (Data: {data_aula}).",
                        school_id=school_id
                    )

                if acao_pos_salvar == 'assinar' and primeiro_diario_criado_id:
                    flash(f"Chamada salva com sucesso ({count_regs} tempos)! Agora confira e assine o diário abaixo.", "success")
                    return redirect(url_for('diario.assinar', diario_id=primeiro_diario_criado_id))

                flash(f"Salvo com sucesso! {count_regs} tempos registrados.", "success")
                return redirect(url_for('diario.gerar_diarios', data=data_aula))
            except Exception as e:
                db.session.rollback()
                flash(f"Erro ao salvar chamada: {str(e)}", "danger")

        nome_instrutor = current_user.nome_de_guerra or current_user.nome_completo
        if horario_base.instrutor and hasattr(horario_base.instrutor, 'user') and horario_base.instrutor.user:
            nome_instrutor = horario_base.instrutor.user.nome_de_guerra or horario_base.instrutor.user.nome_completo

        return render_template(
            'diario/instrutor_registrar.html',
            horarios=horarios_expandidos,
            disciplina=horario_base.disciplina,
            turma=turma_obj,
            nome_instrutor=nome_instrutor,
            alunos=alunos_turma,
            data_aula=data_aula
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        flash(f"Erro ao abrir chamada: {str(e)}", "danger")
        return redirect(url_for('diario.gerar_diarios'))
