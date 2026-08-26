# backend/controllers/recursos_controller.py

import os
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, session, g
from flask_login import login_required, current_user
from backend.models.database import db
from backend.models.recurso import ProvaRecurso, Recurso, DisciplinaHabilitada
from backend.models.disciplina import Disciplina
from backend.models.turma import Turma
from backend.models.user import User  # Necessário para listar instrutores/comandantes
from backend.services.asset_service import AssetService
from werkzeug.utils import secure_filename
import base64
import uuid
import shutil

def process_signature(user, tipo, dados, salvar_padrao=False):
    """Processa e salva assinatura para um Recurso, atualizando o User se salvar_padrao=True"""
    base_path = current_app.static_folder
    upload_folder = os.path.join(base_path, 'uploads', 'signatures')
    os.makedirs(upload_folder, exist_ok=True)
    
    filename = f"sig_recurso_{user.id}_{uuid.uuid4().hex[:8]}.jpg"
    filepath = os.path.join(upload_folder, filename)
    db_path = f"uploads/signatures/{filename}"
    
    try:
        if tipo == 'padrao':
            padrao_path = None
            if not user.assinatura_padrao_path:
                if hasattr(user, 'instrutor_profile') and user.instrutor_profile and user.instrutor_profile.assinatura_padrao_path:
                    padrao_path = user.instrutor_profile.assinatura_padrao_path
            else:
                padrao_path = user.assinatura_padrao_path
                
            if not padrao_path:
                return None
                
            full_padrao_path = os.path.join(base_path, padrao_path)
            if not os.path.exists(full_padrao_path) or os.path.getsize(full_padrao_path) < 100:
                # Assinatura corrompida ou vazia (provável resquício do bug antigo)
                return None
                
            shutil.copy2(full_padrao_path, filepath)
        elif tipo == 'canvas':
            if not dados or not isinstance(dados, str) or len(dados) < 100:
                return None
            encoded = dados.split(',', 1)[1] if ',' in dados else dados
            with open(filepath, 'wb') as f: f.write(base64.b64decode(encoded))
        elif tipo == 'upload':
            if not dados or not hasattr(dados, 'save') or not dados.filename:
                return None
            dados.save(filepath)
        else:
            return None
            
        if salvar_padrao and tipo != 'padrao':
            if user.assinatura_padrao_path:
                old_path = os.path.join(base_path, user.assinatura_padrao_path)
                if os.path.exists(old_path):
                    try: os.remove(old_path)
                    except: pass
            
            filename_padrao = f"user_padrao_{user.id}.jpg"
            filepath_padrao = os.path.join(upload_folder, filename_padrao)
            shutil.copy2(filepath, filepath_padrao)
            user.assinatura_padrao_path = f"uploads/signatures/{filename_padrao}"
            
        return db_path
    except Exception as e:
        print(f"Erro processando assinatura: {e}")
        return None

recursos_bp = Blueprint('recursos', __name__, url_prefix='/recursos')

@recursos_bp.route('/')
@login_required
def index():
    """
    Dashboard principal. 
    Admins veem as matérias habilitadas (agrupadas por nome).
    Instrutores veem apenas o que foi encaminhado a eles.
    """
    active_school_id = getattr(current_user, 'temp_active_school_id', None)

    if current_user.is_super_admin or current_user.is_sens:
        # Busca IDs de disciplinas habilitadas filtradas por escola e edição
        edicao_id = g.active_edicao.id if g.get('active_edicao') else None
        query = Disciplina.query.join(Turma).join(DisciplinaHabilitada).filter(
            Turma.school_id == active_school_id
        )
        if edicao_id:
            query = query.filter(Turma.edicao_id == edicao_id)
        # Agrupa por materia para não repetir
        materias_vistas = set()
        disciplinas = []
        for d in query.all():
            if d.materia not in materias_vistas:
                materias_vistas.add(d.materia)
                disciplinas.append(d)
        
        return render_template('recursos/admin_dashboard.html', disciplinas=disciplinas)
    
    # Se for instrutor, mostra apenas recursos vinculados a ele para parecer
    if current_user.role == 'instrutor':
        edicao_id = g.active_edicao.id if g.get('active_edicao') else None
        query = Recurso.query.join(ProvaRecurso).join(Disciplina).join(Turma).filter(
            Turma.school_id == active_school_id
        )
        if edicao_id:
            query = query.filter(Turma.edicao_id == edicao_id)
            
        recursos_vinculados = query.filter(db.or_(
            db.and_(Recurso.instrutor_id == current_user.id, Recurso.parecer_instrutor == None),
            db.and_(Recurso.instrutor2_id == current_user.id, Recurso.parecer_instrutor2 == None)
        )).order_by(Recurso.id.desc()).all()
        return render_template('recursos/admin_analise_lista.html', recursos=recursos_vinculados)
    
    meus_recursos = Recurso.query.options(db.joinedload(Recurso.prova)).filter_by(aluno_id=current_user.id).order_by(Recurso.created_at.desc()).all()
    return render_template('recursos/aluno_lista.html', recursos=meus_recursos)

@recursos_bp.route('/configurar-disciplinas', methods=['GET', 'POST'])
@login_required
def configurar_disciplinas():
    """Checklist baseado no NOME da matéria, mesclando todas as turmas."""
    if not (current_user.is_super_admin or current_user.is_sens):
        flash("Acesso negado.", "danger")
        return redirect(url_for('main.dashboard'))

    active_school_id = getattr(current_user, 'temp_active_school_id', None)
    
    if request.method == 'POST':
        # Recebemos os NOMES das matérias que o admin quer habilitar
        materias_selecionadas = request.form.getlist('materias_nomes[]')
        
        edicao_id = g.active_edicao.id if g.get('active_edicao') else None
        query = Disciplina.query.join(Turma).filter(Turma.school_id == active_school_id)
        if edicao_id:
            query = query.filter(Turma.edicao_id == edicao_id)
        disciplinas_escola = query.all()
        
        try:
            for d in disciplinas_escola:
                habilitada = DisciplinaHabilitada.query.filter_by(disciplina_id=d.id).first()
                
                # Se o nome da matéria desta disciplina específica está na lista de nomes selecionados
                if d.materia in materias_selecionadas:
                    if not habilitada:
                        db.session.add(DisciplinaHabilitada(disciplina_id=d.id))
                else:
                    if habilitada:
                        db.session.delete(habilitada)
            
            db.session.commit()
            flash("Matérias atualizadas com sucesso!", "success")
            return redirect(url_for('recursos.index'))
        except Exception as e:
            db.session.rollback()
            flash(f"Erro ao salvar: {str(e)}", "danger")

    # GET: Lista NOMES únicos das matérias da escola
    edicao_id = g.active_edicao.id if g.get('active_edicao') else None
    query = db.session.query(Disciplina.materia).join(Turma).filter(
        Turma.school_id == active_school_id
    )
    if edicao_id:
        query = query.filter(Turma.edicao_id == edicao_id)
    materias_unicas = query.distinct().all()
    
    # Pega os nomes das matérias que já têm pelo menos um ID habilitado
    nomes_habilitados = db.session.query(Disciplina.materia).join(DisciplinaHabilitada).distinct().all()
    lista_habilitados = [m[0] for m in nomes_habilitados]

    return render_template('recursos/configurar_disciplinas.html', 
                           materias=[m[0] for m in materias_unicas], 
                           habilitadas=lista_habilitados)

@recursos_bp.route('/admin/provas/<int:disciplina_id>', methods=['GET', 'POST'])
@login_required
def gerenciar_provas(disciplina_id):
    if not (current_user.is_super_admin or current_user.is_sens):
        flash("Acesso negado.", "danger")
        return redirect(url_for('main.dashboard'))
        
    disciplina = Disciplina.query.get_or_404(disciplina_id)
    
    if request.method == 'POST':
        nome_prova = request.form.get('nome_prova')
        if nome_prova:
            # Como todas as turmas usam a mesma prova, vinculamos a este disciplina_id (referência da matéria)
            nova_prova = ProvaRecurso(nome=nome_prova, disciplina_id=disciplina_id)
            db.session.add(nova_prova)
            db.session.commit()
            flash(f"Prova '{nome_prova}' criada!", "success")

    provas = ProvaRecurso.query.filter_by(disciplina_id=disciplina_id).all()
    return render_template('recursos/admin_provas.html', disciplina=disciplina, provas=provas)

@recursos_bp.route('/admin/provas/editar/<int:prova_id>', methods=['POST'])
@login_required
def editar_prova(prova_id):
    if not (current_user.is_super_admin or current_user.is_sens):
        flash("Acesso negado.", "danger")
        return redirect(url_for('main.dashboard'))
        
    prova = ProvaRecurso.query.get_or_404(prova_id)
    nome_prova = request.form.get('nome_prova')
    is_active = request.form.get('is_active') == 'true'
    
    if nome_prova:
        prova.nome = nome_prova
        prova.is_active = is_active
        db.session.commit()
        flash(f"Prova atualizada com sucesso!", "success")
        
    return redirect(url_for('recursos.gerenciar_provas', disciplina_id=prova.disciplina_id))

@recursos_bp.route('/admin/provas/excluir/<int:prova_id>', methods=['POST'])
@login_required
def excluir_prova(prova_id):
    if not (current_user.is_super_admin or current_user.is_sens):
        flash("Acesso negado.", "danger")
        return redirect(url_for('main.dashboard'))
        
    prova = ProvaRecurso.query.get_or_404(prova_id)
    disciplina_id = prova.disciplina_id
    
    if prova.recursos:
        flash("Não é possível excluir esta prova pois já existem recursos associados a ela.", "warning")
    else:
        db.session.delete(prova)
        db.session.commit()
        flash("Prova excluída com sucesso!", "success")
        
    return redirect(url_for('recursos.gerenciar_provas', disciplina_id=disciplina_id))

@recursos_bp.route('/admin/analisar')
@login_required
def listar_recursos_pendentes():
    """Administrador vê tudo e gerencia encaminhamentos. Instrutor vê o que lhe cabe."""
    active_school_id = getattr(current_user, 'temp_active_school_id', None)
    
    from backend.models.disciplina_turma import DisciplinaTurma
    from backend.models.instrutor import Instrutor

    query = Recurso.query.join(ProvaRecurso).join(Disciplina).join(Turma).options(
        db.joinedload(Recurso.aluno),
        db.joinedload(Recurso.instrutor),
        db.selectinload(Recurso.prova).selectinload(ProvaRecurso.disciplina).selectinload(Disciplina.associacoes_turmas).selectinload(DisciplinaTurma.instrutor_1).selectinload(Instrutor.user),
        db.selectinload(Recurso.prova).selectinload(ProvaRecurso.disciplina).selectinload(Disciplina.associacoes_turmas).selectinload(DisciplinaTurma.instrutor_2).selectinload(Instrutor.user)
    ).filter(
        Turma.school_id == active_school_id,
        Turma.edicao_id == session.get('active_edicao_id')
    ).order_by(Recurso.id.desc())

    # Se for instrutor E NÃO for comandante nem SENS, filtra apenas o que foi destinado a ele
    is_comandante = current_user.is_admin_escola_in_school(active_school_id)
    if current_user.role == 'instrutor' and not (is_comandante or current_user.is_sens):
        recursos = query.filter(db.or_(
            db.and_(Recurso.instrutor_id == current_user.id, Recurso.parecer_instrutor == None),
            db.and_(Recurso.instrutor2_id == current_user.id, Recurso.parecer_instrutor2 == None)
        )).all()
    else:
        recursos = query.all()

    import json
    from backend.models.user_school import UserSchool

    # Filtra Comandantes apenas da escola atual
    comandantes = User.query.join(UserSchool).filter(
        UserSchool.school_id == active_school_id,
        UserSchool.role == 'admin_escola'
    ).all()
    
    # Mapeia Instrutores vinculados à disciplina do recurso
    recurso_instrutores_map = {}
    for r in recursos:
        validos = set()
        if r.prova and r.prova.disciplina and r.prova.disciplina.turma:
            disciplina_atual = r.prova.disciplina
            # Busca todas as disciplinas (turmas diferentes) da mesma matéria e mesma edição (ciclo)
            disciplinas_ciclo = Disciplina.query.join(Turma).filter(
                Disciplina.materia == disciplina_atual.materia,
                Turma.edicao_id == disciplina_atual.turma.edicao_id,
                Turma.school_id == active_school_id
            ).all()
            
            for d in disciplinas_ciclo:
                for assoc in d.associacoes_turmas:
                    if assoc.instrutor_1 and assoc.instrutor_1.user:
                        u = assoc.instrutor_1.user
                        validos.add((u.id, u.nome_completo, u.posto_graduacao))
                    if assoc.instrutor_2 and assoc.instrutor_2.user:
                        u = assoc.instrutor_2.user
                        validos.add((u.id, u.nome_completo, u.posto_graduacao))
        
        recurso_instrutores_map[r.id] = [
            {'id': v[0], 'nome': f"{v[2] or ''} {v[1]}".strip()} for v in validos
        ]

    is_instrutor = current_user.role == 'instrutor' or current_user.get_role_in_school(active_school_id) == 'instrutor'
    force_instrutor = is_instrutor and not (is_comandante or current_user.is_sens or current_user.is_super_admin)
    
    return render_template('recursos/admin_analise_lista.html', 
                           recursos=recursos, 
                           comandantes=comandantes,
                           instrutores_map=json.dumps(recurso_instrutores_map),
                           force_instrutor=force_instrutor)

@recursos_bp.route('/admin/encaminhar/<int:recurso_id>', methods=['POST'])
@login_required
def encaminhar_recurso(recurso_id):
    """Administrador encaminha o processo para o próximo nível."""
    if not (current_user.is_super_admin or current_user.is_sens):
        flash("Acesso negado.", "danger")
        return redirect(url_for('main.dashboard'))

    recurso = Recurso.query.get_or_404(recurso_id)
    destinos = request.form.getlist('usuario_destino_id')
    tipo_tramite = request.form.get('tipo_tramite') # 'instrutor' ou 'comandante'
    
    try:
        recurso.instrutor_id = destinos[0] if len(destinos) > 0 else None
        recurso.instrutor2_id = destinos[1] if len(destinos) > 1 else None
        
        if tipo_tramite == 'instrutor':
            recurso.status = "Com Instrutor"
        else:
            recurso.status = "Com Comandante"
            
        db.session.commit()
        flash("Recurso encaminhado com sucesso!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Erro ao encaminhar: {str(e)}", "danger")
        
    return redirect(url_for('recursos.listar_recursos_pendentes'))

@recursos_bp.route('/admin/detalhes/<int:recurso_id>')
@login_required
def detalhes_recurso(recurso_id):
    """Página dedicada para visualização e redação técnica do parecer/decisão."""
    from flask import session
    school_id = session.get('active_school_id')
    is_comandante = current_user.is_admin_escola_in_school(school_id)
    
    if not (current_user.is_super_admin or current_user.is_sens or current_user.role == 'instrutor' or is_comandante):
        flash("Acesso negado.", "danger")
        return redirect(url_for('main.dashboard'))
        
    recurso = Recurso.query.get_or_404(recurso_id)
    
    is_instrutor = current_user.role == 'instrutor' or current_user.get_role_in_school(school_id) == 'instrutor'
    force_instrutor = is_instrutor and not (is_comandante or current_user.is_super_admin or current_user.is_sens)
    
    return render_template('recursos/admin_detalhes_analise.html', r=recurso, is_comandante=is_comandante, force_instrutor=force_instrutor)

@recursos_bp.route('/admin/salvar_parecer/<int:recurso_id>', methods=['POST'])
@login_required
def salvar_parecer(recurso_id):
    """Lógica para salvar Parecer do Instrutor ou Decisão do Comandante com Assinatura."""
    recurso = Recurso.query.get_or_404(recurso_id)
    tipo_acao = request.form.get('tipo_acao') # 'parecer_instrutor' ou 'decisao_cmt'
    
    # Processa Assinatura
    tipo_assinatura = request.form.get('tipo_assinatura', 'padrao')
    dados_assinatura = None
    if tipo_assinatura == 'canvas':
        dados_assinatura = request.form.get('assinatura_base64')
    elif tipo_assinatura == 'upload':
        arquivo_ass = request.files.get('assinatura_upload')
        if arquivo_ass and arquivo_ass.filename:
            dados_assinatura = arquivo_ass
    
    salvar_padrao = request.form.get('salvar_assinatura_padrao') == 'on'
    assinatura_path = process_signature(current_user, tipo_assinatura, dados_assinatura, salvar_padrao)
    
    if not assinatura_path:
        flash("Assinatura inválida ou ausente.", "danger")
        return redirect(request.url)

    try:
        if tipo_acao == 'parecer_instrutor':
            if current_user.id == recurso.instrutor_id:
                recurso.parecer_instrutor = request.form.get('conteudo_texto')
                recurso.assinatura_instrutor = assinatura_path
            elif current_user.id == recurso.instrutor2_id:
                recurso.parecer_instrutor2 = request.form.get('conteudo_texto')
                # Por simplicidade o segundo instrutor também pode salvar aqui se não houver um campo assinatura_instrutor2 (só sobrescreve ou ignora)
                # Assumindo que a principal é do instrutor_id, se for o 2 a gente poderia salvar em um assinatura_instrutor2. Como não existe, vamos salvar na mesma se estiver vazia
                if not recurso.assinatura_instrutor:
                    recurso.assinatura_instrutor = assinatura_path
            
            # Verifica se ainda falta algum instrutor dar o parecer
            falta_1 = recurso.instrutor_id is not None and not recurso.parecer_instrutor
            falta_2 = recurso.instrutor2_id is not None and not recurso.parecer_instrutor2
            
            if not falta_1 and not falta_2:
                recurso.status = "Retornado ao Admin (Parecer)"
            else:
                recurso.status = "Com Instrutor"
        else:
            recurso.decisao_comandante = request.form.get('conteudo_texto')
            recurso.assinatura_comandante = assinatura_path
            recurso.status = request.form.get('status_final')
            # A resposta final que o aluno vê na lista dele
            recurso.resposta_admin = recurso.decisao_comandante
            
            # TODO: Add Notification for student here?
        
        db.session.commit()
        flash("Documento processado, assinado e retornado ao controle administrativo!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Erro ao processar documento: {str(e)}", "danger")
        
    return redirect(url_for('recursos.index'))

@recursos_bp.route('/enviar', methods=['GET', 'POST'])
@login_required
def novo_recurso():
    """Aluno vê a matéria unificada e assina o envio."""
    if request.method == 'POST':
        prova_id = request.form.get('prova_id')
        questoes = request.form.getlist('questao_texto[]')
        argumentacoes = request.form.getlist('argumentacao_texto[]')
        arquivos = request.files.getlist('arquivo_anexo[]')
        
        # Processa Assinatura
        tipo_assinatura = request.form.get('tipo_assinatura', 'padrao')
        dados_assinatura = None
        if tipo_assinatura == 'canvas':
            dados_assinatura = request.form.get('assinatura_base64')
        elif tipo_assinatura == 'upload':
            arquivo_ass = request.files.get('assinatura_upload')
            if arquivo_ass and arquivo_ass.filename:
                dados_assinatura = arquivo_ass
        
        salvar_padrao = request.form.get('salvar_assinatura_padrao') == 'on'
        assinatura_path = process_signature(current_user, tipo_assinatura, dados_assinatura, salvar_padrao)
        
        if not assinatura_path:
            flash("Assinatura inválida ou ausente.", "danger")
            return redirect(request.url)

        try:
            for i in range(len(questoes)):
                novo = Recurso(
                    prova_id=prova_id,
                    aluno_id=current_user.id,
                    questao_texto=questoes[i],
                    argumentacao_texto=argumentacoes[i] if i < len(argumentacoes) else "",
                    assinatura_aluno=assinatura_path
                )
                if i < len(arquivos) and arquivos[i].filename != '':
                    filename = AssetService.save_file(arquivos[i], folder='recursos_anexos')
                    novo.arquivo_anexo = filename
                db.session.add(novo)
            db.session.commit()
            flash("Recurso enviado e assinado com sucesso!", "success")
            return redirect(url_for('recursos.index'))
        except Exception as e:
            db.session.rollback()
            flash(f"Erro: {str(e)}", "danger")

    active_school_id = current_user._get_active_school_id()
    aluno_edicao_id = None
    
    if str(current_user.role).lower().strip() == 'aluno':
        aluno_prof = current_user.aluno_profile
        if aluno_prof and getattr(aluno_prof, 'turma', None):
            if not active_school_id:
                active_school_id = aluno_prof.turma.school_id
            aluno_edicao_id = aluno_prof.turma.edicao_id

    if not aluno_edicao_id:
        aluno_edicao_id = session.get('active_edicao_id')

    # Forma mais segura e tolerante a falhas estruturais nos dados de teste:
    # 1. Busca todas as provas ativas
    query = ProvaRecurso.query.filter_by(is_active=True).join(Disciplina).join(Turma).options(
        db.contains_eager(ProvaRecurso.disciplina)
    )
    
    # 2. Filtra pela escola
    if active_school_id:
        query = query.filter(Turma.school_id == active_school_id)
        
    if aluno_edicao_id:
        query = query.filter(Turma.edicao_id == aluno_edicao_id)
        
    provas_ativas = query.all()
    
    # 3. Agrupa por nome da matéria e verifica se está habilitada
    disciplinas_unicas = {}
    for p in provas_ativas:
        d = p.disciplina
        if d.habilitacao_recurso: # Verifica se a admin marcou como habilitada
            if d.materia not in disciplinas_unicas:
                disciplinas_unicas[d.materia] = d
                
    disciplinas_com_prova = list(disciplinas_unicas.values())
    
    return render_template('recursos/aluno_form.html', disciplinas=disciplinas_com_prova)

@recursos_bp.route('/api/get_provas/<int:disciplina_id>')
@login_required
def api_get_provas(disciplina_id):
    # Lógica importante: busca provas pelo nome da matéria da disciplina selecionada
    d_aluno = Disciplina.query.get_or_404(disciplina_id)
    active_school_id = current_user._get_active_school_id()
    aluno_edicao_id = None
    
    if str(current_user.role).lower().strip() == 'aluno':
        aluno_prof = current_user.aluno_profile
        if aluno_prof and getattr(aluno_prof, 'turma', None):
            if not active_school_id:
                active_school_id = aluno_prof.turma.school_id
            aluno_edicao_id = aluno_prof.turma.edicao_id
            
    if not aluno_edicao_id:
        aluno_edicao_id = session.get('active_edicao_id')
    
    query = ProvaRecurso.query.join(Disciplina).join(Turma).filter(
        Disciplina.materia == d_aluno.materia,
        ProvaRecurso.is_active == True
    )
    
    if active_school_id:
        query = query.filter(Turma.school_id == active_school_id)
        
    if aluno_edicao_id:
        query = query.filter(Turma.edicao_id == aluno_edicao_id)
        
    provas = query.all()
    provas = query.all()
    
    return jsonify([{'id': p.id, 'nome': p.nome} for p in provas])

@recursos_bp.route('/admin/exportar-pdf/<int:recurso_id>')
@login_required
def exportar_recurso_pdf(recurso_id):
    if not (current_user.is_super_admin or current_user.is_sens):
        flash("Acesso negado.", "danger")
        return redirect(url_for('main.dashboard'))
        
    recurso = Recurso.query.get_or_404(recurso_id)
    
    from datetime import datetime
    import json
    import uuid
    from backend.models.background_job import BackgroundJob
    
    html = render_template(
        'recursos/recurso_pdf.html',
        r=recurso,
        now=datetime.now().astimezone()
    )
    
    pdf_name = f"recurso_{recurso_id}.pdf"
    
    meta_data = {"filename": pdf_name, "anexos": []}
    if recurso.arquivo_anexo:
        import os
        from flask import current_app
        anexo_path = os.path.join(current_app.root_path, '..', 'static', 'uploads', 'recursos_anexos', recurso.arquivo_anexo)
        if anexo_path.lower().endswith('.pdf'):
            meta_data["anexos"].append(anexo_path)
            
    job_id = str(uuid.uuid4())
    job = BackgroundJob(
        id=job_id,
        task_type='generate_pdf',
        payload=html,
        meta_data=json.dumps(meta_data),
        user_id=current_user.id
    )
    db.session.add(job)
    db.session.commit()
    
    return jsonify({'success': True, 'job_id': job_id})

@recursos_bp.route('/aluno/excluir/<int:recurso_id>', methods=['POST'])
@login_required
def excluir_recurso_aluno(recurso_id):
    recurso = Recurso.query.get_or_404(recurso_id)
    
    if str(current_user.role).lower().strip() == 'aluno' and recurso.aluno_id != current_user.id:
        flash("Acesso negado.", "danger")
        return redirect(url_for('recursos.index'))
        
    if recurso.status != "Em Análise" and recurso.status != "Pendente":
        flash("Não é possível excluir um recurso que já foi processado ou está em andamento avançado.", "warning")
        return redirect(url_for('recursos.index'))
        
    try:
        db.session.delete(recurso)
        db.session.commit()
        flash("Recurso excluído com sucesso.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Erro ao excluir recurso: {str(e)}", "danger")
        
    return redirect(url_for('recursos.index'))

@recursos_bp.route('/admin/excluir/<int:recurso_id>', methods=['POST'])
@login_required
def excluir_recurso_admin(recurso_id):
    active_school_id = session.get('active_school_id') or getattr(current_user, 'escola_id', None)
    is_comandante = current_user.is_admin_escola_in_school(active_school_id)
    
    if not (current_user.is_super_admin or current_user.is_sens or is_comandante):
        flash("Acesso negado. Apenas administradores, chefe da SENS ou comandantes podem excluir recursos nesta etapa.", "danger")
        return redirect(url_for('recursos.listar_recursos_pendentes'))
        
    recurso = Recurso.query.get_or_404(recurso_id)
    
    try:
        db.session.delete(recurso)
        db.session.commit()
        flash(f"Recurso #{recurso.id} excluído com sucesso.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Erro ao excluir recurso: {str(e)}", "danger")
        
    return redirect(url_for('recursos.listar_recursos_pendentes'))

@recursos_bp.route('/aluno/ciente/<int:recurso_id>', methods=['POST'])
@login_required
def dar_ciente(recurso_id):
    """Registra a ciência do aluno sobre a decisão do recurso."""
    recurso = Recurso.query.get_or_404(recurso_id)
    
    if str(current_user.role).lower().strip() == 'aluno' and recurso.aluno_id != current_user.id:
        return jsonify({'success': False, 'message': 'Acesso negado'}), 403
        
    if recurso.status not in ['Deferido', 'Indeferido']:
        return jsonify({'success': False, 'message': 'Recurso ainda não foi finalizado'}), 400
        
    try:
        from datetime import datetime
        recurso.aluno_ciente = True
        recurso.aluno_ciente_data = datetime.now()
        # Captura o IP (considera proxy reverso caso exista)
        recurso.aluno_ciente_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
