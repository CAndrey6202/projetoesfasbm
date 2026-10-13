# backend/controllers/edicao_controller.py

from flask import Blueprint, render_template, request, flash, redirect, url_for, g, session
from flask_login import login_required, current_user
from ..models.database import db
from ..models.edicao import Edicao
from ..models.school import School
from ..services.user_service import UserService
from ..models.instrutor import Instrutor
from utils.decorators import admin_required
from datetime import datetime

edicao_bp = Blueprint('edicao', __name__, url_prefix='/edicoes')


@edicao_bp.route('/')
@login_required
@admin_required
def index():
    school_id = UserService.get_current_school_id()
    if not school_id:
        flash("Selecione uma escola primeiro.", "warning")
        return redirect(url_for('main.dashboard'))

    edicoes = Edicao.query.filter_by(school_id=school_id).order_by(Edicao.id.desc()).all()
    todos_instrutores = Instrutor.query.filter_by(school_id=school_id).all()
    return render_template('admin/edicoes.html', edicoes=edicoes, todos_instrutores=todos_instrutores)


@edicao_bp.route('/criar', methods=['POST'])
@login_required
@admin_required
def criar():
    school_id = UserService.get_current_school_id()
    if not school_id:
        flash("Selecione uma escola primeiro.", "warning")
        return redirect(url_for('main.dashboard'))

    nome = request.form.get('nome', '').strip()
    npccal_type = request.form.get('npccal_type', 'ctsp').strip().lower()
    data_formatura_str = request.form.get('data_formatura', '').strip()
    fada_inicio_str = request.form.get('fada_data_inicio', '').strip()
    fada_fim_str = request.form.get('fada_data_fim', '').strip()

    if not nome:
        flash("O nome da edição é obrigatório.", "danger")
        return redirect(url_for('edicao.index'))

    try:
        nova = Edicao(
            nome=nome,
            school_id=school_id,
            npccal_type=npccal_type,
            data_formatura=datetime.strptime(data_formatura_str, '%Y-%m-%d').date() if data_formatura_str else None,
            fada_data_inicio=datetime.strptime(fada_inicio_str, '%Y-%m-%dT%H:%M') if fada_inicio_str and npccal_type in ['cbfpm', 'cspm'] else None,
            fada_data_fim=datetime.strptime(fada_fim_str, '%Y-%m-%dT%H:%M') if fada_fim_str and npccal_type in ['cbfpm', 'cspm'] else None,
        )
        db.session.add(nova)
        db.session.commit()

        # Ativa automaticamente a edição recém-criada
        session['active_edicao_id'] = nova.id
        flash(f"Edição '{nome}' criada e ativada com sucesso!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Erro ao criar edição: {e}", "danger")

    return redirect(url_for('edicao.index'))


@edicao_bp.route('/editar/<int:edicao_id>', methods=['POST'])
@login_required
@admin_required
def editar(edicao_id):
    edicao = db.session.get(Edicao, edicao_id)
    if not edicao:
        flash("Edição não encontrada.", "danger")
        return redirect(url_for('edicao.index'))

    try:
        edicao.nome = request.form.get('nome', edicao.nome).strip()
        edicao.npccal_type = request.form.get('npccal_type', edicao.npccal_type).strip().lower()

        data_formatura_str = request.form.get('data_formatura', '').strip()
        fada_inicio_str = request.form.get('fada_data_inicio', '').strip()
        fada_fim_str = request.form.get('fada_data_fim', '').strip()

        edicao.data_formatura = datetime.strptime(data_formatura_str, '%Y-%m-%d').date() if data_formatura_str else None
        edicao.fada_data_inicio = datetime.strptime(fada_inicio_str, '%Y-%m-%dT%H:%M') if fada_inicio_str and edicao.npccal_type in ['cbfpm', 'cspm'] else None
        edicao.fada_data_fim = datetime.strptime(fada_fim_str, '%Y-%m-%dT%H:%M') if fada_fim_str and edicao.npccal_type in ['cbfpm', 'cspm'] else None

        db.session.commit()
        flash(f"Edição '{edicao.nome}' atualizada com sucesso!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Erro ao atualizar edição: {e}", "danger")

    return redirect(url_for('edicao.index'))


@edicao_bp.route('/selecionar/<int:edicao_id>', methods=['POST'])
@login_required
def selecionar(edicao_id):
    edicao = db.session.get(Edicao, edicao_id)
    if edicao:
        session['active_edicao_id'] = edicao.id
        flash(f"Edição ativa: {edicao.nome}", "success")
    else:
        flash("Edição não encontrada.", "danger")
    return redirect(request.referrer or url_for('main.dashboard'))


@edicao_bp.route('/limpar', methods=['POST'])
@login_required
def limpar_selecao():
    session.pop('active_edicao_id', None)
    flash("Filtro de edição removido.", "info")
    return redirect(request.referrer or url_for('main.dashboard'))

@edicao_bp.route('/<int:edicao_id>/instrutores', methods=['GET', 'POST'])
@login_required
@admin_required
def gerenciar_instrutores(edicao_id):
    edicao = db.session.get(Edicao, edicao_id)
    if not edicao:
        flash("Edição não encontrada.", "danger")
        return redirect(url_for('edicao.index'))
    
    school_id = UserService.get_current_school_id()
    if edicao.school_id != school_id:
        flash("Esta edição não pertence à escola atual.", "danger")
        return redirect(url_for('edicao.index'))

    if request.method == 'POST':
        # Recebe lista de instrutores do formulário
        instrutores_selecionados = request.form.getlist('instrutores')
        
        # Limpa os atuais
        edicao.instrutores.clear()
        
        if instrutores_selecionados:
            for instr_id in instrutores_selecionados:
                instrutor = db.session.get(Instrutor, int(instr_id))
                if instrutor and instrutor.school_id == school_id:
                    edicao.instrutores.append(instrutor)
        
        db.session.commit()
        flash(f"Instrutores atualizados com sucesso para a edição {edicao.nome}.", "success")
        return redirect(url_for('edicao.index'))
    
    # GET: buscar todos os instrutores da escola e quais já estão na edição
    todos_instrutores = Instrutor.query.filter_by(school_id=school_id).all()
    instrutores_da_edicao = [i.id for i in edicao.instrutores]
    
    # Pode renderizar o form direto ou um fragmento. Por enquanto renderizaremos na admin/edicoes.html usando modais.
    # Como a requisição pode vir de um modal (iframe) ou JSON, vamos retornar JSON para popular o select se for requisitado
    if request.headers.get('Accept') == 'application/json' or request.args.get('json'):
        data = [{
            'id': i.id, 
            'nome': i.user.nome_completo if i.user else 'Desconhecido',
            'matricula': i.user.matricula if i.user else '',
            'selected': i.id in instrutores_da_edicao
        } for i in todos_instrutores]
        from flask import jsonify
        return jsonify(data)
    
    # Fallback (não utilizado se for via JS puro, mas útil se criar uma view separada)
    return redirect(url_for('edicao.index'))
