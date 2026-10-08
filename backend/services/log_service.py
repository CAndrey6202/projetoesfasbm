# backend/services/log_service.py
from flask import request, has_request_context
from flask_login import current_user
from ..models.database import db
from ..models.admin_log import AdminLog
from ..models.user import User
from .user_service import UserService
from sqlalchemy import select, desc
import json
from datetime import datetime

class LogService:
    
    @staticmethod
    def log(action, details=None, user=None, school_id=None, parent_id=None, commit=True):
        """
        Registra uma ação no sistema.
        :param action: Nome curto da ação (ex: 'Editar Turma')
        :param details: Texto ou Dicionário com detalhes
        :param user: Objeto User (opcional, usa current_user se None)
        :param school_id: ID da escola (opcional, detecta auto)
        :param parent_id: ID de um log pai, se esta for uma sub-ação
        """
        try:
            # 1. Resolver Usuário
            if not user and has_request_context() and current_user.is_authenticated:
                user_id = current_user.id
            elif user:
                user_id = user.id
            else:
                user_id = None

            # 2. Resolver Escola
            if not school_id:
                school_id = UserService.get_current_school_id()

            # 3. Resolver IP
            ip = None
            if has_request_context():
                ip = request.headers.get('X-Forwarded-For', request.remote_addr)

            # 4. Tratar Detalhes (se for dict, vira JSON string)
            if isinstance(details, (dict, list)):
                try:
                    details = json.dumps(details, ensure_ascii=False, indent=2)
                except:
                    details = str(details)
            
            new_log = AdminLog(
                school_id=school_id,
                user_id=user_id,
                action=action,
                details=details,
                ip_address=ip,
                parent_id=parent_id,
                timestamp=datetime.now()
            )
            
            try:
                with db.session.begin_nested():
                    db.session.add(new_log)
                    db.session.flush()
            except Exception as e:
                print(f"ERRO AO INSERIR LOG: {e}")
                return None
                
            if commit:
                db.session.commit()
            
            return new_log
        except Exception as e:
            # Falha silenciosa no log não deve parar o sistema principal
            print(f"ERRO AO GERAR LOG: {e}")
            return None

    @staticmethod
    def get_logs(school_id, date_start=None, date_end=None, user_id=None, limit=100):
        query = select(AdminLog).where(AdminLog.school_id == school_id)
        
        # Filtros Opcionais
        if date_start:
            query = query.where(AdminLog.timestamp >= date_start)
        if date_end:
            query = query.where(AdminLog.timestamp <= date_end)
        if user_id:
            query = query.where(AdminLog.user_id == user_id)
            
        # Ordenação e Limite
        query = query.order_by(desc(AdminLog.timestamp)).limit(limit)
        
        return db.session.scalars(query).all()