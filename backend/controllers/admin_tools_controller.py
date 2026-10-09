# backend/controllers/admin_tools_controller.py

from flask import Blueprint, render_template, request, flash, redirect, url_for, send_file, jsonify
from flask_login import login_required, current_user
import io
import json
import uuid
import pandas as pd
from datetime import datetime, timedelta

from utils.decorators import admin_or_programmer_required, admin_escola_required
from ..services.user_service import UserService
from ..services.admin_tools_service import AdminToolsService
from ..services.mail_merge_service import MailMergeService
from ..services.log_service import LogService

tools_bp = Blueprint('tools', __name__, url_prefix='/ferramentas')

@tools_bp.route('/')
@login_required
@admin_or_programmer_required
def index():
    """Exibe a p√°gina principal do m√≥dulo de Ferramentas do Administrador."""
    return render_template('ferramentas/index.html')

@tools_bp.route('/mail-merge', methods=['GET', 'POST'])
@login_required
@admin_or_programmer_required
def mail_merge():
    if request.method == 'POST':
        template_file = request.files.get('template_file')
        data_file = request.files.get('data_file')
        output_format = request.form.get('output_format', 'docx')

        if not template_file or not data_file:
            flash('Ambos os arquivos (template e dados) s√£o obrigat√≥rios.', 'danger')
            return redirect(url_for('tools.mail_merge'))

        zip_buffer, error = MailMergeService.generate_documents(template_file, data_file, output_format)

        if error:
            flash(f'Ocorreu um erro ao gerar os documentos: {error}', 'danger')
            return redirect(url_for('tools.mail_merge'))

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # --- ESPI√ÉO: MAIL MERGE ---
        school_id = UserService.get_current_school_id()
        LogService.log(
            action="Utilizou Mail Merge",
            details=f"O administrador gerou um lote de documentos (formato: {output_format}).",
            school_id=school_id
        )
        # --------------------------
        
        return send_file(
            zip_buffer,
            as_attachment=True,
            download_name=f'certificados_gerados_{timestamp}.zip',
            mimetype='application/zip'
        )

    return render_template('ferramentas/mail_merge.html')

@tools_bp.route('/backup')
@login_required
@admin_or_programmer_required
def backup_escola():
    """Gera e faz o download de um snapshot completo da edi√ß√£o atual da escola em formato JSON."""
    school_id = UserService.get_current_school_id()
    if not school_id:
        flash("Nenhuma escola selecionada.", "warning")
        return redirect(url_for('tools.index'))

    try:
        backup_data = AdminToolsService.generate_school_backup(school_id)
        json_str = json.dumps(backup_data, ensure_ascii=False, indent=4)
        buffer = io.BytesIO(json_str.encode('utf-8'))
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"backup_escola_{school_id}_edicao_{timestamp}.json"
        
        # --- ESPI√ÉO: BACKUP DA ESCOLA ---
        LogService.log(
            action="Gerou Backup",
            details=f"Um arquivo de backup completo da escola foi gerado e baixado ({filename}).",
            school_id=school_id
        )
        # --------------------------------
        
        return send_file(
            buffer,
            as_attachment=True,
            download_name=filename,
            mimetype='application/json'
        )
    except Exception as e:
        flash(f"Ocorreu um erro ao gerar o backup da escola: {str(e)}", "danger")
        return redirect(url_for('tools.index'))

@tools_bp.route('/reset')
@login_required
@admin_or_programmer_required
def reset_escola():
    """Exibe a p√°gina com as op√ß√µes de reset da escola."""
    return render_template('ferramentas/reset_escola.html')

@tools_bp.route('/limpar', methods=['POST'])
@login_required
@admin_or_programmer_required
def clear_data():
    """Processa as solicita√ß√µes de limpeza e intercepta se 'instrutores' for marcado."""
    password = request.form.get('password')
    
    if not password or not current_user.check_password(password):
        flash('Senha incorreta. Nenhuma a√ß√£o foi executada.', 'danger')
        return redirect(url_for('tools.reset_escola'))

    school_id = UserService.get_current_school_id()
    if not school_id:
        flash('N√£o foi poss√≠vel identificar a sua escola. A√ß√£o cancelada.', 'danger')
        return redirect(url_for('tools.reset_escola'))

    opcoes_selecionadas = request.form.getlist('opcoes')
    
    if not opcoes_selecionadas:
        flash('Nenhuma categoria de dados foi selecionada para exclus√£o.', 'warning')
        return redirect(url_for('tools.reset_escola'))

    # INTERCEPTA√á√ÉO: Se escolheu 'instrutores', pausa e manda pra tela de triagem
    if 'instrutores' in opcoes_selecionadas:
        users_escola = UserService.get_users_by_school(school_id)
        instrutores = [u for u in users_escola if u.role == 'instrutor']
        
        if instrutores:
            return render_template('ferramentas/selecionar_instrutores_reset.html',
                                   opcoes=opcoes_selecionadas,
                                   instrutores=instrutores,
                                   password=password) # Passando a senha silenciosamente para o pr√≥ximo form

    # Se n√£o selecionou instrutores, executa a limpeza direto
    success, message = AdminToolsService.custom_clear_school_data(school_id, opcoes_selecionadas)
    
    # --- ESPI√ÉO: RESETOU DADOS ---
    if success:
        LogService.log(
            action="Reset/Limpeza da Escola",
            details=f"O administrador realizou a exclus√£o em massa dos seguintes dados: {', '.join(opcoes_selecionadas)}.",
            school_id=school_id
        )
    # -----------------------------
    
    flash(message, 'success' if success else 'danger')
    return redirect(url_for('tools.reset_escola'))

# --- NOVA ROTA PARA PROCESSAR A TELA INTERMEDI√É¬ÅRIA ---
@tools_bp.route('/limpar_confirmado', methods=['POST'])
@login_required
@admin_or_programmer_required
def clear_data_confirmado():
    """Executa a limpeza final usando a lista filtrada de instrutores."""
    password = request.form.get('password')
    if not password or not current_user.check_password(password):
        flash('Sess√£o expirada ou senha inv√°lida.', 'danger')
        return redirect(url_for('tools.reset_escola'))

    school_id = UserService.get_current_school_id()
    opcoes_selecionadas = request.form.getlist('opcoes')
    
    # Pega apenas os IDs dos instrutores que PERMANECERAM marcados na tela intermedi√°ria
    instrutores_marcados = request.form.getlist('instrutores_to_delete')
    instrutores_to_delete_ids = [int(i) for i in instrutores_marcados]

    # Chama o service passando a lista exata de quem deve sair
    success, message = AdminToolsService.custom_clear_school_data(school_id, opcoes_selecionadas, instructors_to_delete_ids=instrutores_to_delete_ids)

    # --- ESPI√ÉO: RESETOU DADOS (COM INSTRUTORES) ---
    if success:
        LogService.log(
            action="Reset/Limpeza da Escola",
            details=f"O administrador realizou a exclus√£o em massa: {', '.join(opcoes_selecionadas)} (incluindo {len(instrutores_to_delete_ids)} instrutor(es) removido(s)).",
            school_id=school_id
        )
    # -----------------------------------------------

    flash(message, 'success' if success else 'danger')
    return redirect(url_for('tools.reset_escola'))

@tools_bp.route('/logs')
@login_required
@admin_or_programmer_required
def logs_admin():
    school_id = UserService.get_current_school_id()
    if not school_id:
        flash("Nenhuma escola selecionada.", "warning")
        return redirect(url_for('main.dashboard'))

    data_inicio_str = request.args.get('data_inicio')
    data_fim_str = request.args.get('data_fim')
    filtro_user_id = request.args.get('user_id', type=int)

    if data_inicio_str:
        data_inicio = datetime.strptime(data_inicio_str, '%Y-%m-%d')
    else:
        data_inicio = datetime.now() - timedelta(days=7)
    
    if data_fim_str:
        data_fim = datetime.strptime(data_fim_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
    else:
        data_fim = datetime.now()

    logs = LogService.get_logs(
        school_id=school_id, 
        date_start=data_inicio, 
        date_end=data_fim, 
        user_id=filtro_user_id,
        limit=200
    )

    users_escola = UserService.get_users_by_school(school_id)

    return render_template(
        'ferramentas/logs_admin.html',
        logs=logs,
        users=users_escola,
        data_inicio=data_inicio.strftime('%Y-%m-%d'),
        data_fim=data_fim.strftime('%Y-%m-%d'),
        filtro_user_id=filtro_user_id
    )

@tools_bp.route('/preview_backup', methods=['GET', 'POST'])
@login_required
@admin_or_programmer_required
def preview_backup():
    if request.method == 'POST':
        if 'backup_file' not in request.files:
            flash('Nenhum arquivo enviado.', 'error')
            return redirect(request.url)
            
        file = request.files['backup_file']
        
        if file.filename == '':
            flash('Nenhum arquivo selecionado.', 'error')
            return redirect(request.url)
            
        if file and file.filename.endswith('.json'):
            try:
                file_content = file.read().decode('utf-8')
                backup_data = json.loads(file_content)
                return render_template('ferramentas/preview_backup.html', data=backup_data, file_name=file.filename)
            except json.JSONDecodeError:
                flash('O arquivo enviado n√£o √© um JSON v√°lido ou est√° corrompido.', 'error')
            except Exception as e:
                flash(f'Ocorreu um erro ao processar o arquivo de backup: {str(e)}', 'error')
        else:
            flash('Por favor, envie um arquivo .json v√°lido.', 'error')
            
        return redirect(request.url)
        
    return render_template('ferramentas/preview_backup.html', data=None)

@admin_tools_bp.route('/fix-db-mojibake', methods=['GET'])
@login_required
@admin_required
def fix_db_mojibake():
    try:
        from backend.models.processo_disciplina import ProcessoDisciplina
        from backend.models.fada_avaliacao import FadaAvaliacao
        from backend.app import db
        
        mapping = {
            '√°': '·', '√©': 'È', '√≠': 'Ì', '√≥': 'Û', '√∫': '˙',
            '√ ': '¡', '√â': '…', '√ ': 'Õ', '√ì': '”', '√ö': '⁄',
            '√¢': '‚', '√™': 'Í', '√Æ': 'Ó', '√¥': 'Ù', '√ª': '˚',
            '√Ç': '¬', '√ä': ' ', '√é': 'Œ', '√î': '‘', '√õ': '€',
            '√£': '„', '√µ': 'ı', '√É': '√', '√ï': '’',
            '√ß': 'Á', '√á': '«',
            '√\xa0': '‡', '√®': 'Ë', '√¨': 'Ï', '√≤': 'Ú', '√π': '˘',
            '√Ä': '¿', '√à': '»', '√å': 'Ã', '√í': '“', '√ô': 'Ÿ',
            '¬∫': '∫', '¬™': '™', '¬∞': '∞', '¬ß': 'ß'
        }
        
        def fix_text(text):
            if not text: return text
            for bad, good in mapping.items():
                text = text.replace(bad, good)
            return text
            
        processos = ProcessoDisciplina.query.all()
        for p in processos:
            p.decisao_final = fix_text(p.decisao_final)
            p.tipo_sancao = fix_text(p.tipo_sancao)
            p.detalhes_sancao = fix_text(p.detalhes_sancao)
            p.fatos = fix_text(p.fatos)
            p.texto_defesa = fix_text(p.texto_defesa)
            p.texto_recurso = fix_text(p.texto_recurso)
            p.fundamentacao_recurso = fix_text(p.fundamentacao_recurso)
            p.observacao_decisao = fix_text(p.observacao_decisao)
            p.status = fix_text(p.status)
            
        fadas = FadaAvaliacao.query.all()
        for f in fadas:
            f.texto_recurso = fix_text(f.texto_recurso)
            f.justificativa_recurso = fix_text(f.justificativa_recurso)
            f.observacao = fix_text(f.observacao)
            
        db.session.commit()
        return \"<h1>Banco de dados corrigido com sucesso!</h1><p>Todos os textos corrompidos (mojibake) nos processos disciplinares e FADAs foram restaurados.</p><p><a href='/'>Voltar para o InÌcio</a></p>\"
    except Exception as e:
        db.session.rollback()
        return f\"<h1>Erro ao corrigir banco de dados</h1><p>{str(e)}</p>\"
