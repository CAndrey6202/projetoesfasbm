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
    """Exibe a página principal do módulo de Ferramentas do Administrador."""
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
            flash('Ambos os arquivos (template e dados) são obrigatórios.', 'danger')
            return redirect(url_for('tools.mail_merge'))

        zip_buffer, error = MailMergeService.generate_documents(template_file, data_file, output_format)

        if error:
            flash(f'Ocorreu um erro ao gerar os documentos: {error}', 'danger')
            return redirect(url_for('tools.mail_merge'))

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # --- ESPIÃO: MAIL MERGE ---
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
    """Gera e faz o download de um snapshot completo da edição atual da escola em formato JSON."""
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
        
        # --- ESPIÃO: BACKUP DA ESCOLA ---
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
    """Exibe a página com as opções de reset da escola."""
    return render_template('ferramentas/reset_escola.html')

@tools_bp.route('/limpar', methods=['POST'])
@login_required
@admin_or_programmer_required
def clear_data():
    """Processa as solicitações de limpeza e intercepta se 'instrutores' for marcado."""
    password = request.form.get('password')
    
    if not password or not current_user.check_password(password):
        flash('Senha incorreta. Nenhuma ação foi executada.', 'danger')
        return redirect(url_for('tools.reset_escola'))

    school_id = UserService.get_current_school_id()
    if not school_id:
        flash('Não foi possível identificar a sua escola. Ação cancelada.', 'danger')
        return redirect(url_for('tools.reset_escola'))

    opcoes_selecionadas = request.form.getlist('opcoes')
    
    if not opcoes_selecionadas:
        flash('Nenhuma categoria de dados foi selecionada para exclusão.', 'warning')
        return redirect(url_for('tools.reset_escola'))

    # INTERCEPTAÇÃO: Se escolheu 'instrutores', pausa e manda pra tela de triagem
    if 'instrutores' in opcoes_selecionadas:
        users_escola = UserService.get_users_by_school(school_id)
        instrutores = [u for u in users_escola if u.role == 'instrutor']
        
        if instrutores:
            return render_template('ferramentas/selecionar_instrutores_reset.html',
                                   opcoes=opcoes_selecionadas,
                                   instrutores=instrutores,
                                   password=password) # Passando a senha silenciosamente para o próximo form

    # Se não selecionou instrutores, executa a limpeza direto
    success, message = AdminToolsService.custom_clear_school_data(school_id, opcoes_selecionadas)
    
    # --- ESPIÃO: RESETOU DADOS ---
    if success:
        LogService.log(
            action="Reset/Limpeza da Escola",
            details=f"O administrador realizou a exclusão em massa dos seguintes dados: {', '.join(opcoes_selecionadas)}.",
            school_id=school_id
        )
    # -----------------------------
    
    flash(message, 'success' if success else 'danger')
    return redirect(url_for('tools.reset_escola'))

# --- NOVA ROTA PARA PROCESSAR A TELA INTERMEDIÁRIA ---
@tools_bp.route('/limpar_confirmado', methods=['POST'])
@login_required
@admin_or_programmer_required
def clear_data_confirmado():
    """Executa a limpeza final usando a lista filtrada de instrutores."""
    password = request.form.get('password')
    if not password or not current_user.check_password(password):
        flash('Sessão expirada ou senha inválida.', 'danger')
        return redirect(url_for('tools.reset_escola'))

    school_id = UserService.get_current_school_id()
    opcoes_selecionadas = request.form.getlist('opcoes')
    
    # Pega apenas os IDs dos instrutores que PERMANECERAM marcados na tela intermediária
    instrutores_marcados = request.form.getlist('instrutores_to_delete')
    instrutores_to_delete_ids = [int(i) for i in instrutores_marcados]

    # Chama o service passando a lista exata de quem deve sair
    success, message = AdminToolsService.custom_clear_school_data(school_id, opcoes_selecionadas, instructors_to_delete_ids=instrutores_to_delete_ids)

    # --- ESPIÃO: RESETOU DADOS (COM INSTRUTORES) ---
    if success:
        LogService.log(
            action="Reset/Limpeza da Escola",
            details=f"O administrador realizou a exclusão em massa: {', '.join(opcoes_selecionadas)} (incluindo {len(instrutores_to_delete_ids)} instrutor(es) removido(s)).",
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
                flash('O arquivo enviado não é um JSON válido ou está corrompido.', 'error')
            except Exception as e:
                flash(f'Ocorreu um erro ao processar o arquivo de backup: {str(e)}', 'error')
        else:
            flash('Por favor, envie um arquivo .json válido.', 'error')
            
        return redirect(request.url)
        
    return render_template('ferramentas/preview_backup.html', data=None)
@tools_bp.route('/certificados', methods=['GET', 'POST'])
@login_required
@admin_or_programmer_required
def certificados():
    if request.method == 'POST':
        # Recebe os dados do formul�rio
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
        disciplinas_leg = request.form.getlist('disc_leg[]')
        
        disciplinas = []
        for i in range(len(disciplinas_nr)):
            if disciplinas_nome[i].strip() != '':
                disciplinas.append({
                    'nr': disciplinas_nr[i],
                    'nome': disciplinas_nome[i],
                    'ch': disciplinas_ch[i] if i < len(disciplinas_ch) else '',
                    'leg': disciplinas_leg[i] if i < len(disciplinas_leg) else ''
                })

        planilha_alunos = request.files.get('planilha_alunos')
        
        if not planilha_alunos:
            return jsonify({'success': False, 'error': 'A planilha de alunos � obrigat�ria.'})

        try:
            # L� a planilha de alunos (assumindo que a primeira coluna tem os nomes)
            df = pd.read_excel(planilha_alunos)
            
            # Se a planilha tiver uma coluna espec�fica, pode ser procurada, sen�o pega a primeira
            if 'Nome do Aluno' in df.columns:
                alunos = df['Nome do Aluno'].dropna().astype(str).tolist()
            elif 'Nome' in df.columns:
                alunos = df['Nome'].dropna().astype(str).tolist()
            elif 'Aluno' in df.columns:
                alunos = df['Aluno'].dropna().astype(str).tolist()
            else:
                alunos = df.iloc[:, 0].dropna().astype(str).tolist()
                
            if not alunos:
                return jsonify({'success': False, 'error': 'Nenhum aluno encontrado na planilha.'})
                
            # Renderiza o HTML com todos os certificados
            rendered_html = render_template(
                'ferramentas/certificados_pdf.html',
                dados=dados,
                disciplinas=disciplinas,
                alunos=alunos
            )
            
            # Cria o job
            from backend.models.database import db
            from backend.models.background_job import BackgroundJob
            
            job_id = str(uuid.uuid4())
            pdf_filename = f"certificados_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            
            job = BackgroundJob(
                id=job_id,
                task_type='generate_pdf',
                payload=rendered_html,
                meta_data=json.dumps({"filename": pdf_filename}),
                user_id=current_user.id
            )
            db.session.add(job)
            db.session.commit()
            
            # Log de gera��o
            LogService.log(
                action="Gera��o de Certificados",
                details=f"O administrador enviou uma solicita��o para gerar certificados para {len(alunos)} alunos do curso '{dados['nome_curso']}'.",
                school_id=UserService.get_current_school_id()
            )
            
            return jsonify({'success': True, 'job_id': job_id})
            
        except Exception as e:
            from backend.models.database import db
            db.session.rollback()
            return jsonify({'success': False, 'error': f'Erro ao processar a planilha: {str(e)}'})

    return render_template('ferramentas/certificados.html')
