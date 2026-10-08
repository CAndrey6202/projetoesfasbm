# backend/controllers/super_admin_controller.py

from flask import Blueprint, render_template, request, flash, redirect, url_for, session
from flask_login import login_required, current_user, login_user
import secrets
import string
from utils.decorators import super_admin_required
from ..models.database import db
from ..models.school import School
from ..models.user import User
from ..models.user_school import UserSchool
from ..services.school_service import SchoolService
from ..services.user_service import UserService
from ..services.log_service import LogService # <--- ESPIÃO IMPORTADO AQUI
from sqlalchemy import not_, select

super_admin_bp = Blueprint('super_admin', __name__, url_prefix='/super-admin')

@super_admin_bp.route('/dashboard', methods=['GET', 'POST'])
@login_required
@super_admin_required
def dashboard():
    # --- FAXINA DE ESTADO ---
    # Se o Super Admin entrou no Painel Global, garantimos que ele 
    # não está "preso" a nenhuma escola de visualizações anteriores.
    session.pop('view_as_school_id', None)
    session.pop('view_as_school_name', None)
    session.pop('active_school_id', None)
    # ------------------------

    if request.method == 'POST':
        school_name = request.form.get('school_name')
        admin_id = request.form.get('admin_id')

        if not school_name:
            flash('O nome da escola é obrigatório.', 'danger')
        elif not admin_id:
            flash('O administrador da escola é obrigatório.', 'danger')
        else:
            success, message = SchoolService.create_school(school_name, int(admin_id))
            
            # --- ESPIÃO: CRIOU ESCOLA ---
            if success:
                LogService.log(
                    action="Criou Escola (Global)",
                    details=f"O Super Admin criou uma nova escola chamada '{school_name}'.",
                    school_id=None
                )
            # ----------------------------
            
            if success:
                flash(message, 'success')
            else:
                flash(message, 'danger')
        return redirect(url_for('super_admin.dashboard'))

    all_schools = db.session.query(School).order_by(School.nome).all()
    instrutores = db.session.scalars(
        select(User)
        .where(User.role == 'instrutor')
        .order_by(User.nome_completo)
    ).all()
    
    return render_template('super_admin/dashboard.html', all_schools=all_schools, schools=all_schools, instrutores=instrutores)

@super_admin_bp.route('/clear-school-selection')
@login_required
@super_admin_required
def clear_school_selection():
    """Remove a escola ativa da sessão e devolve o Super Admin para o Painel Global (DEC)"""
    session.pop('view_as_school_id', None)
    session.pop('view_as_school_name', None)
    session.pop('active_school_id', None) # Garante a limpeza total da sessão
    
    flash('Você retornou ao Painel Global (Modo DEC).', 'info')
    return redirect(url_for('super_admin.dashboard'))

@super_admin_bp.route('/schools/edit/<int:school_id>', methods=['POST'])
@login_required
@super_admin_required
def edit_school(school_id):
    school_name = request.form.get('school_name')

    success, message = SchoolService.update_school(school_id, school_name)
    
    # --- ESPIÃO: EDITOU NOME DA ESCOLA ---
    if success:
        LogService.log(
            action="Editou Escola (Global)",
            details=f"O Super Admin alterou o nome da escola ID {school_id} para '{school_name}'.",
            school_id=school_id
        )
    # -------------------------------------
    
    flash(message, 'success' if success else 'danger')
    return redirect(url_for('super_admin.dashboard'))

@super_admin_bp.route('/schools/delete/<int:school_id>', methods=['POST'])
@login_required
@super_admin_required
def delete_school(school_id):
    password = request.form.get('password')
    
    if not password:
        flash('A senha é obrigatória para confirmar a exclusão.', 'danger')
        return redirect(url_for('super_admin.dashboard'))

    # Salva o nome antes de apagar para o log
    escola_temp = db.session.get(School, school_id)
    escola_nome = escola_temp.nome if escola_temp else f"ID {school_id}"

    # Passa o current_user e a senha para o Service validar
    success, message = SchoolService.delete_school(school_id, current_user, password)
    
    # --- ESPIÃO: DELETOU ESCOLA ---
    if success:
        LogService.log(
            action="Excluiu Escola (Global)",
            details=f"O Super Admin apagou definitivamente a escola '{escola_nome}'.",
            school_id=None
        )
    # ------------------------------
    
    flash(message, 'success' if success else 'danger')
    return redirect(url_for('super_admin.dashboard'))

@super_admin_bp.route('/delete-user/<int:user_id>', methods=['POST'])
@login_required
@super_admin_required
def delete_user(user_id):
    role_filter = request.args.get('filter')
    
    user_temp = db.session.get(User, user_id)
    user_nome = user_temp.nome_completo if user_temp else f"ID {user_id}"
    
    success, message = UserService.delete_user_by_id(user_id)
    
    # --- ESPIÃO: DELETOU USUÁRIO GLOBAL ---
    if success:
        LogService.log(
            action="Excluiu Usuário (Global)",
            details=f"O Super Admin deletou o usuário '{user_nome}' do sistema.",
            school_id=None
        )
    # --------------------------------------
    
    flash(message, 'success' if success else 'danger')
    return redirect(request.referrer or url_for('user.gerenciar_usuarios'))

@super_admin_bp.route('/reset-user-password', methods=['POST'])
@login_required
@super_admin_required
def reset_user_password():
    user_id = request.form.get('user_id')
    if not user_id:
        flash('Nenhum usuário selecionado.', 'danger')
        return redirect(request.referrer or url_for('user.gerenciar_usuarios'))

    user = db.session.get(User, int(user_id))
    if not user:
        flash('Usuário não encontrado.', 'danger')
        return redirect(request.referrer or url_for('user.gerenciar_usuarios'))
    
    if user.role == 'super_admin':
        flash('Não é permitido resetar a senha de um Super Admin por este método.', 'warning')
        return redirect(request.referrer or url_for('user.gerenciar_usuarios'))

    alphabet = string.ascii_letters + string.digits + '!@#$%^&*'
    temp_password = ''.join(secrets.choice(alphabet) for i in range(12))

    try:
        user.set_password(temp_password)
        user.must_change_password = True
        db.session.commit()
        
        # --- ESPIÃO: RESETOU SENHA GLOBAL ---
        LogService.log(
            action="Resetou Senha de Usuário (Global)",
            details=f"O Super Admin resetou a senha do usuário '{user.nome_completo}'.",
            school_id=None
        )
        # ------------------------------------
        
        flash(f'Senha para o usuário "{user.nome_completo or user.username}" resetada com sucesso! Nova senha temporária: {temp_password}', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ocorreu um erro ao resetar a senha: {e}', 'danger')

    return redirect(request.referrer or url_for('user.gerenciar_usuarios'))

@super_admin_bp.route('/select-school')
@login_required
@super_admin_required
def select_school():
    """Página para o Super Admin selecionar a escola ativa."""
    schools = db.session.scalars(select(School).order_by(School.nome)).all()
    return render_template('select_school.html', schools=schools)


@super_admin_bp.route('/set-active-school/<int:school_id>')
@login_required
@super_admin_required
def set_active_school(school_id):
    """Define a escola ativa para o Super Admin na sessão."""
    school = db.session.get(School, school_id)
    if school:
        session['view_as_school_id'] = school.id
        session['view_as_school_name'] = school.nome
        session['active_school_id'] = school.id # Injeta para que os menus funcionem perfeitamente
        flash(f'Você entrou no modo de intervenção da escola: {school.nome}.', 'success')
    else:
        flash('Escola não encontrada.', 'danger')
    
    return redirect(url_for('main.dashboard'))

# --- GESTÃO DE ACESSOS DEC (SUPER ADMINS) ---
@super_admin_bp.route('/gestores-dec', methods=['GET', 'POST'])
@login_required
@super_admin_required
def manage_gestores():
    if request.method == 'POST':
        action = request.form.get('action')
        
        # --- PROMOVER USUÁRIO ---
        if action == 'add':
            matricula = request.form.get('matricula')
            novo_papel = request.form.get('papel', 'super_admin')
            # Importação local para evitar erro circular
            from utils.normalizer import normalize_matricula
            mat_norm = normalize_matricula(matricula)
            
            user = db.session.execute(select(User).where(User.matricula == mat_norm)).scalar_one_or_none()
            if user:
                if user.role == novo_papel:
                    flash(f'O usuário {user.nome_de_guerra or user.nome_completo} já tem este perfil.', 'warning')
                else:
                    user.role = novo_papel
                    db.session.commit()
                    
                    # --- ESPIÃO: PROMOVEU GESTOR DEC ---
                    LogService.log(
                        action="Promoveu Gestor DEC (Global)",
                        details=f"O usuário '{user.nome_completo}' foi promovido para '{novo_papel}'.",
                        school_id=None
                    )
                    # -----------------------------------
                    
                    flash(f'{user.nome_de_guerra or user.nome_completo} foi promovido para {novo_papel} com sucesso!', 'success')
            else:
                flash('Nenhum usuário encontrado com essa matrícula.', 'danger')
                
        # --- REBAIXAR USUÁRIO ---
        elif action == 'remove':
            user_id = request.form.get('user_id')
            user = db.session.get(User, int(user_id))
            
            if user:
                if user.id == current_user.id:
                    flash('Você não pode remover seus próprios privilégios por aqui. Isso evita que o sistema fique sem administrador.', 'danger')
                else:
                    user.role = 'instrutor' # Rebaixa para instrutor por padrão
                    db.session.commit()
                    
                    # --- ESPIÃO: REBAIXOU GESTOR DEC ---
                    LogService.log(
                        action="Rebaixou Gestor DEC (Global)",
                        details=f"Os privilégios de DEC foram removidos do usuário '{user.nome_completo}'.",
                        school_id=None
                    )
                    # -----------------------------------
                    
                    flash(f'Privilégios de DEC removidos de {user.nome_de_guerra or user.nome_completo}.', 'info')
                    
        return redirect(url_for('super_admin.manage_gestores'))
        
    gestores = db.session.scalars(select(User).where(User.role.in_(['super_admin', 'coordenador_provas'])).order_by(User.nome_completo)).all()
    
    return render_template('super_admin/gestores_dec.html', gestores=gestores)


@super_admin_bp.route('/usuarios-globais', methods=['GET'])
@login_required
@super_admin_required
def global_users():
    """Painel global para o SuperAdmin visualizar e gerenciar TODOS os usuários de todas as escolas."""
    # Buscar todos os usuários do sistema, exceto super_admins (que são geridos na aba gestores-dec)
    query = select(User).where(User.role != 'super_admin').order_by(User.nome_completo)
    usuarios = db.session.scalars(query).all()
    escolas = db.session.scalars(select(School).order_by(School.nome)).all()
    return render_template('super_admin/global_users.html', usuarios=usuarios, escolas=escolas)

@super_admin_bp.route('/atribuir-papel-global', methods=['POST'])
@login_required
@super_admin_required
def atribuir_papel_global():
    user_id = request.form.get('user_id')
    school_id = request.form.get('school_id')
    role = request.form.get('role')
    
    if not all([user_id, school_id, role]):
        flash("Todos os campos são obrigatórios.", "danger")
        return redirect(url_for('super_admin.global_users'))
        
    success, message = UserService.assign_school_role(int(user_id), int(school_id), role)
    
    # --- ESPIÃO: VINCULOU GLOBALMENTE ---
    if success:
        user_temp = db.session.get(User, int(user_id))
        nome = user_temp.nome_completo if user_temp else f"ID {user_id}"
        LogService.log(
            action="Atribuiu Vínculo/Papel Global",
            details=f"O Super Admin vinculou o usuário '{nome}' à escola ID {school_id} com o papel de '{role.upper()}'.",
            school_id=int(school_id)
        )
    # ------------------------------------
    
    flash(message, 'success' if success else 'danger')
    return redirect(url_for('super_admin.global_users'))
    
@super_admin_bp.route('/remover-vinculo-global', methods=['POST'])
@login_required
@super_admin_required
def remover_vinculo_global():
    user_id = request.form.get('user_id')
    school_id = request.form.get('school_id')
    
    if not all([user_id, school_id]):
        flash("Usuário ou escola não informados.", "danger")
        return redirect(url_for('super_admin.global_users'))
        
    user_school = db.session.execute(
        select(UserSchool).where(UserSchool.user_id == int(user_id), UserSchool.school_id == int(school_id))
    ).scalar_one_or_none()
    
    if user_school:
        user_temp = db.session.get(User, int(user_id))
        nome = user_temp.nome_completo if user_temp else f"ID {user_id}"
        
        db.session.delete(user_school)
        db.session.commit()
        
        # --- ESPIÃO: REMOVEU VINCULO GLOBAL ---
        LogService.log(
            action="Removeu Vínculo Global",
            details=f"O Super Admin desvinculou o usuário '{nome}' da escola ID {school_id}.",
            school_id=int(school_id)
        )
        # --------------------------------------
        
        flash("Vínculo removido com sucesso.", "success")
    else:
        flash("Vínculo não encontrado.", "danger")
        
    return redirect(url_for('super_admin.global_users'))

# =========================================================================
# LÓGICA DE PERSONIFICAÇÃO ("LOGAR COMO")
# =========================================================================

@super_admin_bp.route('/logar-como/<int:user_id>')
@login_required
def logar_como(user_id):
    """ Coloca o disfarce e assume o controle da conta alvo """
    
    if current_user.role != 'super_admin':
        flash("Acesso negado.", "danger")
        return redirect(url_for('main.dashboard'))

    alvo = db.session.get(User, user_id)
    if not alvo:
        flash("Usuário alvo não encontrado.", "danger")
        return redirect(request.referrer or url_for('super_admin.dashboard'))

    # 1. Guarda o seu ID original e a ESCOLA ATUAL antes de trocar de roupa
    admin_id = current_user.id
    escola_id = session.get('view_as_school_id') or session.get('active_school_id')
    escola_nome = session.get('view_as_school_name')
    
    # --- ESPIÃO: LOGAR COMO (INICIO) ---
    LogService.log(
        action="Personificação de Conta (Início)",
        details=f"ALERTA: O Super Admin (ID {admin_id}) assumiu controle da conta do usuário '{alvo.nome_completo}' (ID {alvo.id}).",
        school_id=escola_id
    )
    # -----------------------------------
    
    # 2. Faz o login forçado (sem senha)
    login_user(alvo)
    
    # 3. Salva o rastro na memória (DEPOIS do login para não ser apagado)
    session['impersonator_id'] = admin_id
    if escola_id:
        session['impersonator_return_school_id'] = escola_id
    if escola_nome:
        session['impersonator_return_school_name'] = escola_nome

    # Limpa a visão do DEC para o disfarce ser perfeito
    session.pop('is_dec_mode', None)
    session.pop('active_school_id', None)
    session.pop('view_as_school_id', None)
    session.pop('view_as_school_name', None)
    
    flash(f"Modo Espião: Você assumiu a conta de {alvo.nome_completo or alvo.username}.", "warning")
    return redirect(url_for('main.selecionar_escola'))


@super_admin_bp.route('/voltar-admin')
@login_required
def voltar_admin():
    """ Tira o disfarce e devolve para a Escola ou Painel do DEC """
    
    admin_id = session.get('impersonator_id')
    if not admin_id:
        flash("Nenhum disfarce ativo encontrado.", "danger")
        return redirect(url_for('main.dashboard'))

    admin_user = db.session.get(User, admin_id)
    if admin_user:
        # Recupera as coordenadas da escola antes de limpar o disfarce
        retorno_escola_id = session.get('impersonator_return_school_id')
        retorno_escola_nome = session.get('impersonator_return_school_name')

        # --- ESPIÃO: LOGAR COMO (FIM) ---
        LogService.log(
            action="Personificação de Conta (Fim)",
            details=f"O Super Admin encerrou a personificação e retornou ao seu próprio acesso.",
            school_id=retorno_escola_id
        )
        # --------------------------------

        # 1. Faz o login de volta como Super Admin
        login_user(admin_user)
        
        # 2. Limpa o lixo da personificação
        session.pop('impersonator_id', None)
        session.pop('impersonator_return_school_id', None)
        session.pop('impersonator_return_school_name', None)
        
        # 3. Devolve o chapéu do DEC
        session['is_dec_mode'] = True
        
        # 4. O RETORNO ESCALONADO: Se tinha uma escola salva, volta para ela!
        if retorno_escola_id:
            session['view_as_school_id'] = retorno_escola_id
            session['active_school_id'] = retorno_escola_id
            if retorno_escola_nome:
                session['view_as_school_name'] = retorno_escola_nome
            
            flash("Disfarce removido. Você retornou à gestão da escola.", "success")
            return redirect(url_for('main.dashboard'))
        else:
            flash("Disfarce removido. Controle Super Admin restaurado.", "success")
            return redirect(url_for('super_admin.dashboard'))
        
    return redirect(url_for('auth.logout'))

# =========================================================================
# LÓGICA DE TRANSFERÊNCIA DE ALUNOS
# =========================================================================

@super_admin_bp.route('/buscar-aluno-transferencia', methods=['GET'])
@login_required
@super_admin_required
def buscar_aluno_transferencia():
    from flask import jsonify
    from sqlalchemy import or_, select
    from ..models.aluno import Aluno
    from ..models.turma import Turma
    from ..models.school import School
    from ..models.user import User

    termo = request.args.get('q', '').strip()
    
    if len(termo) < 3:
        return jsonify({"success": False, "message": "Digite pelo menos 3 caracteres para buscar."})

    try:
        # Busca o Aluno verificando correspondência no Nome, Matrícula ou Nome de Guerra
        query = select(Aluno).join(User).where(
            or_(
                User.nome_completo.ilike(f"%{termo}%"),
                User.matricula.ilike(f"%{termo}%"),
                User.nome_de_guerra.ilike(f"%{termo}%")
            )
        )
        alunos_encontrados = db.session.scalars(query).all()

        resultados = []
        for aluno in alunos_encontrados:
            escola_atual = "Sem Escola"
            turma_atual = "Sem Turma"
            
            if aluno.turma:
                turma_atual = aluno.turma.nome
                escola_obj = db.session.get(School, aluno.turma.school_id)
                escola_atual = escola_obj.nome if escola_obj else "Desconhecida"

            resultados.append({
                "aluno_id": aluno.id,
                "nome": aluno.user.nome_completo or aluno.user.username,
                "matricula": aluno.user.matricula,
                "turma_atual": turma_atual,
                "escola_atual": escola_atual
            })

        # Busca todas as escolas para preencher o formulário de destino
        escolas_db = db.session.scalars(select(School).order_by(School.nome)).all()
        escolas_disponiveis = [{"id": e.id, "nome": e.nome} for e in escolas_db]

        return jsonify({
            "success": True,
            "alunos": resultados,
            "escolas": escolas_disponiveis
        })

    except Exception as e:
        return jsonify({"success": False, "message": f"Erro na busca: {str(e)}"})


@super_admin_bp.route('/efetivar-transferencia', methods=['POST'])
@login_required
@super_admin_required
def efetivar_transferencia():
    aluno_id = request.form.get('aluno_id')
    nova_escola_id = request.form.get('nova_escola_id')

    if not aluno_id or not nova_escola_id:
        flash("Dados incompletos para efetivar a transferência.", "danger")
        return redirect(url_for('super_admin.dashboard'))

    try:
        from ..models.aluno import Aluno
        from ..models.school import School
        
        aluno = db.session.get(Aluno, int(aluno_id))
        nova_escola = db.session.get(School, int(nova_escola_id))

        if not aluno or not nova_escola:
            flash("Aluno ou Escola não encontrados.", "danger")
            return redirect(url_for('super_admin.dashboard'))

        user = aluno.user
        escola_origem_nome = aluno.turma.school.nome if aluno.turma and aluno.turma.school else "Sem Escola Anterior"

        # 1. Remover acessos antigos de todas as outras escolas
        vinculos_antigos = db.session.execute(
            select(UserSchool).where(UserSchool.user_id == user.id, UserSchool.school_id != nova_escola.id)
        ).scalars().all()
        
        for v in vinculos_antigos:
            db.session.delete(v)

        # 2. Adicionar o acesso global para a nova escola (se já não existir)
        vinculo_novo = db.session.execute(
            select(UserSchool).where(UserSchool.user_id == user.id, UserSchool.school_id == nova_escola.id)
        ).scalar_one_or_none()

        if not vinculo_novo:
            novo_link = UserSchool(user_id=user.id, school_id=nova_escola.id, role='aluno')
            db.session.add(novo_link)

        # 3. LIMPEZA DOS VÍNCULOS ACADÊMICOS
        # Aqui está a correção: desvinculamos o aluno tanto da Turma quanto da Edição antigas.
        aluno.turma_id = None
        aluno.edicao_id = None

        db.session.commit()
        
        # --- ESPIÃO: TRANSFERÊNCIA DE ALUNO ---
        LogService.log(
            action="Transferência de Escola (Aluno)",
            details=f"O Super Admin transferiu o aluno '{user.nome_completo}' da escola '{escola_origem_nome}' para a escola '{nova_escola.nome}'.",
            school_id=nova_escola.id
        )
        # --------------------------------------
        
        flash(f"Transferência concluída com sucesso! O aluno {user.nome_completo or user.matricula} foi movido para a {nova_escola.nome}. O administrador da escola deverá alocá-lo em uma Edição e Turma local.", "success")

    except Exception as e:
        db.session.rollback()
        flash(f"Erro ao efetivar transferência: {str(e)}", "danger")

    return redirect(url_for('super_admin.dashboard'))
