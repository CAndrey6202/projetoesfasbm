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
    """Exibe a pÃ¡gina principal do mÃ³dulo de Ferramentas do Administrador."""
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
            flash('Ambos os arquivos (template e dados) sÃ£o obrigatÃ³rios.', 'danger')
            return redirect(url_for('tools.mail_merge'))

        zip_buffer, error = MailMergeService.generate_documents(template_file, data_file, output_format)

        if error:
            flash(f'Ocorreu um erro ao gerar os documentos: {error}', 'danger')
            return redirect(url_for('tools.mail_merge'))

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # --- ESPIÃƒO: MAIL MERGE ---
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
    """Gera e faz o download de um snapshot completo da ediÃ§Ã£o atual da escola em formato JSON."""
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
        
        # --- ESPIÃƒO: BACKUP DA ESCOLA ---
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
    """Exibe a pÃ¡gina com as opÃ§Ãµes de reset da escola."""
    return render_template('ferramentas/reset_escola.html')

@tools_bp.route('/limpar', methods=['POST'])
@login_required
@admin_or_programmer_required
def clear_data():
    """Processa as solicitaÃ§Ãµes de limpeza e intercepta se 'instrutores' for marcado."""
    password = request.form.get('password')
    
    if not password or not current_user.check_password(password):
        flash('Senha incorreta. Nenhuma aÃ§Ã£o foi executada.', 'danger')
        return redirect(url_for('tools.reset_escola'))

    school_id = UserService.get_current_school_id()
    if not school_id:
        flash('NÃ£o foi possÃ­vel identificar a sua escola. AÃ§Ã£o cancelada.', 'danger')
        return redirect(url_for('tools.reset_escola'))

    opcoes_selecionadas = request.form.getlist('opcoes')
    
    if not opcoes_selecionadas:
        flash('Nenhuma categoria de dados foi selecionada para exclusÃ£o.', 'warning')
        return redirect(url_for('tools.reset_escola'))

    # INTERCEPTAÃ‡ÃƒO: Se escolheu 'instrutores', pausa e manda pra tela de triagem
    if 'instrutores' in opcoes_selecionadas:
        users_escola = UserService.get_users_by_school(school_id)
        instrutores = [u for u in users_escola if u.role == 'instrutor']
        
        if instrutores:
            return render_template('ferramentas/selecionar_instrutores_reset.html',
                                   opcoes=opcoes_selecionadas,
                                   instrutores=instrutores,
                                   password=password) # Passando a senha silenciosamente para o prÃ³ximo form

    # Se nÃ£o selecionou instrutores, executa a limpeza direto
    success, message = AdminToolsService.custom_clear_school_data(school_id, opcoes_selecionadas)
    
    # --- ESPIÃƒO: RESETOU DADOS ---
    if success:
        LogService.log(
            action="Reset/Limpeza da Escola",
            details=f"O administrador realizou a exclusÃ£o em massa dos seguintes dados: {', '.join(opcoes_selecionadas)}.",
            school_id=school_id
        )
    # -----------------------------
    
    flash(message, 'success' if success else 'danger')
    return redirect(url_for('tools.reset_escola'))

# --- NOVA ROTA PARA PROCESSAR A TELA INTERMEDIÃRIA ---
@tools_bp.route('/limpar_confirmado', methods=['POST'])
@login_required
@admin_or_programmer_required
def clear_data_confirmado():
    """Executa a limpeza final usando a lista filtrada de instrutores."""
    password = request.form.get('password')
    if not password or not current_user.check_password(password):
        flash('SessÃ£o expirada ou senha invÃ¡lida.', 'danger')
        return redirect(url_for('tools.reset_escola'))

    school_id = UserService.get_current_school_id()
    opcoes_selecionadas = request.form.getlist('opcoes')
    
    # Pega apenas os IDs dos instrutores que PERMANECERAM marcados na tela intermediÃ¡ria
    instrutores_marcados = request.form.getlist('instrutores_to_delete')
    instrutores_to_delete_ids = [int(i) for i in instrutores_marcados]

    # Chama o service passando a lista exata de quem deve sair
    success, message = AdminToolsService.custom_clear_school_data(school_id, opcoes_selecionadas, instructors_to_delete_ids=instrutores_to_delete_ids)

    # --- ESPIÃƒO: RESETOU DADOS (COM INSTRUTORES) ---
    if success:
        LogService.log(
            action="Reset/Limpeza da Escola",
            details=f"O administrador realizou a exclusÃ£o em massa: {', '.join(opcoes_selecionadas)} (incluindo {len(instrutores_to_delete_ids)} instrutor(es) removido(s)).",
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
                flash('O arquivo enviado nÃ£o Ã© um JSON vÃ¡lido ou estÃ¡ corrompido.', 'error')
            except Exception as e:
                flash(f'Ocorreu um erro ao processar o arquivo de backup: {str(e)}', 'error')
        else:
            flash('Por favor, envie um arquivo .json vÃ¡lido.', 'error')
            
        return redirect(request.url)
        
    return render_template('ferramentas/preview_backup.html', data=None)
@tools_bp.route('/certificados', methods=['GET', 'POST'])
@login_required
@admin_or_programmer_required
def certificados():
    if request.method == 'POST':
        # Recebe os dados do formulário
        dados = {
            'nome_curso': request.form.get('nome_curso', ''),
            'nome_escola': request.form.get('nome_escola', ''),
            'data_duracao': request.form.get('data_duracao', ''),
            'carga_horaria': request.form.get('carga_horaria', ''),
            'data_local': request.form.get('data_local', ''),
            'nome_comandante': request.form.get('nome_comandante', ''),
            'nome_diretor': request.form.get('nome_diretor', ''),
            'nome_chefe_ensino': request.form.get('nome_chefe_ensino', ''),
            'ementa': request.form.get('ementa', '')
        }
        
        # Recebe as disciplinas
        disciplinas_nr = request.form.getlist('disc_nr[]')
        disciplinas_nome = request.form.getlist('disc_nome[]')
        disciplinas_ch = request.form.getlist('disc_ch[]')
        
        disciplinas = []
        for i in range(len(disciplinas_nr)):
            if disciplinas_nome[i].strip() != '':
                disciplinas.append({
                    'nr': disciplinas_nr[i],
                    'nome': disciplinas_nome[i],
                    'ch': disciplinas_ch[i] if i < len(disciplinas_ch) else ''
                })

        lista_alunos_texto = request.form.get('lista_alunos', '')
        
        if not lista_alunos_texto.strip():
            return jsonify({'success': False, 'error': 'A lista de alunos e obrigatoria.'})

        try:
            # Processa o texto separando por vírgula ou quebra de linha
            alunos_raw = lista_alunos_texto.replace('\n', ',').split(',')
            alunos = [a.strip() for a in alunos_raw if a.strip()]
            
            if not alunos:
                return jsonify({'success': False, 'error': 'Nenhum aluno encontrado na lista.'})
                
            # Cria o job para gerar um ZIP com um PDF por aluno
            from backend.models.database import db
            from backend.models.background_job import BackgroundJob
            
            job_id = str(uuid.uuid4())
            zip_filename = f"certificados_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
            
            # Guardamos os dados no payload como JSON
            payload_data = {
                'dados': dados,
                'disciplinas': disciplinas,
                'alunos': alunos
            }
            
            job = BackgroundJob(
                id=job_id,
                task_type='generate_certificates_zip',
                payload=json.dumps(payload_data),
                meta_data=json.dumps({"filename": zip_filename}),
                user_id=current_user.id
            )
            db.session.add(job)
            db.session.commit()
            
            # Log de geracao
            LogService.log(
                action="Geracao de Certificados",
                details=f"O administrador enviou uma solicitacao para gerar certificados para {len(alunos)} alunos do curso '{dados['nome_curso']}'.",
                school_id=UserService.get_current_school_id()
            )
            
            return jsonify({'success': True, 'job_id': job_id})
            
        except Exception as e:
            from backend.models.database import db
            db.session.rollback()
            return jsonify({'success': False, 'error': f'Erro ao processar a planilha: {str(e)}'})

    return render_template('ferramentas/certificados.html')
