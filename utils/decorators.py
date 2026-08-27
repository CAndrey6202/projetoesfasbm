# utils/decorators.py

from functools import wraps
from flask import abort, flash, redirect, url_for
from flask_login import current_user
from backend.services.user_service import UserService

def sens_required(f):
    """Admin de Ensino (Alunos, Turmas, Horários, Notas) - Verificação Contextual"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        
        school_id = UserService.get_current_school_id()
        if not current_user.is_sens_in_school(school_id):
            flash("Acesso restrito à Chefia de Ensino nesta escola.", "danger")
            return redirect(url_for('main.dashboard'))
            
        return f(*args, **kwargs)
    return decorated_function

def cal_required(f):
    """Admin de Justiça (Punições, Questionários) - Verificação Contextual"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
            
        school_id = UserService.get_current_school_id()
        if not current_user.is_cal_in_school(school_id):
            flash("Acesso restrito ao Corpo de Alunos nesta escola.", "danger")
            return redirect(url_for('main.dashboard'))
            
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """Admin Geral da Escola (Comandante)"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
            
        school_id = UserService.get_current_school_id()
        if not current_user.is_admin_escola_in_school(school_id):
             abort(403)
        return f(*args, **kwargs)
    return decorated_function

# Alias para compatibilidade
admin_escola_required = admin_required

def can_schedule_classes_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
            
        school_id = UserService.get_current_school_id()
        
        is_instrutor = current_user.is_instrutor_in_school(school_id)
        is_sens = current_user.is_sens_in_school(school_id)
        is_admin = current_user.is_admin_escola_in_school(school_id)
        
        has_instrutor_profile = getattr(current_user, 'instrutor_profile', None) is not None

        if (is_instrutor or is_sens or is_admin or has_instrutor_profile):
            return f(*args, **kwargs)
            
        return redirect(url_for('main.dashboard'))
    return decorated_function

def admin_or_programmer_required(f):
    """
    Usado em admin_tools e áreas genéricas.
    Permite acesso se for Admin da Escola ou Staff (SENS/CAL).
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        
        school_id = UserService.get_current_school_id()
        if current_user.is_staff_in_school(school_id):
            return f(*args, **kwargs)
            
        abort(403)
        return f(*args, **kwargs)
    return decorated_function

def school_admin_or_programmer_required(f):
    """
    Permite acesso ao SENS ou Admin da Escola (Comandante).
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
            
        school_id = UserService.get_current_school_id()
        
        if (current_user.is_admin_escola_in_school(school_id) or 
            current_user.is_sens_in_school(school_id)):
            return f(*args, **kwargs)

        flash('Permissão insuficiente para gerenciar dados escolares.', 'danger')
        return redirect(url_for('main.dashboard'))
    return decorated_function

def sens_or_admin_or_programmer_required(f):
    """
    NOVO DECORATOR (CORREÇÃO VÍNCULOS):
    Permite acesso SOMENTE para:
    - Admin da Escola (Comandante)
    - Chefe da SENS
    
    EXCLUI explicitamente: CAL, Instrutores e Alunos.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))

        school_id = UserService.get_current_school_id()

        # Verifica permissões específicas para Vínculos (SENS ou Admin)
        if (
            current_user.is_admin_escola_in_school(school_id) or
            current_user.is_sens_in_school(school_id)
        ):
            return f(*args, **kwargs)

        flash("A edição de vínculos é exclusiva da SENS e da Administração.", "danger")
        return redirect(url_for('main.dashboard'))

    return decorated_function

def super_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or getattr(current_user, 'role', '') != 'super_admin':
            abort(403)
        return f(*args, **kwargs)
    return decorated_function



def can_view_management_pages_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

def aluno_profile_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated: return redirect(url_for('auth.login'))
        if current_user.role == 'aluno' and not (hasattr(current_user, 'aluno_profile') and current_user.aluno_profile):
            return redirect(url_for('aluno.completar_cadastro'))
        return f(*args, **kwargs)
    return decorated_function

# --- NOVO DECORATOR ESSENCIAL PARA JUSTIÇA ---
def can_manage_justice_required(f):
    """
    Permite acesso aos gestores de justiça:
    - Admin da Escola
    - SENS (Chefia de Ensino)
    - CAL (Corpo de Alunos)
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(403)
            
        school_id = UserService.get_current_school_id()
        
        # Admin Global
        if getattr(current_user, 'role', '') == 'super_admin':
            return f(*args, **kwargs)
            
        # Admin da Escola, SENS ou CAL
        if school_id:
            if (current_user.is_admin_escola_in_school(school_id) or 
                current_user.is_sens_in_school(school_id) or
                current_user.is_cal_in_school(school_id)):
                return f(*args, **kwargs)
                
        flash("Acesso restrito ao Corpo de Alunos ou SENS.", "danger")
        return redirect(url_for('main.dashboard'))
    return decorated_function