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
