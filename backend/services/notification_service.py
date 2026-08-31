# backend/services/notification_service.py
from sqlalchemy import select, func, update
from firebase_admin import messaging
from ..models.database import db
from ..models.notification import Notification
from ..models.user import User
from ..models.user_school import UserSchool
from ..models.push_subscription import PushSubscription
from cachetools import cached, TTLCache
import time

# Cache que expira a cada 6 horas (21600 segundos) para economizar queries de JS
dropdown_cache = TTLCache(maxsize=2000, ttl=21600)


class NotificationService:

    @staticmethod
    def _trigger_push_notification(user_id: int, title: str, body: str, url: str):
        """Dispara notificações push via FCM para todas as inscrições de um usuário."""
        subscriptions = db.session.query(PushSubscription).filter_by(user_id=user_id).all()
        if not subscriptions:
            return
        
        tokens = [sub.fcm_token for sub in subscriptions]

        # Monta a notificação
        notification_payload = messaging.Notification(title=title, body=body)
        
        # Prepara a mensagem para múltiplos dispositivos
        message = messaging.MulticastMessage(
            notification=notification_payload,
            tokens=tokens,
            data={'url': url or '/'} # Envia a URL como dado adicional
        )

        try:
            # Envia a mensagem
            response = messaging.send_multicast(message)
            # Opcional: Lidar com tokens que falharam ou que não são mais válidos
            if response.failure_count > 0:
                responses = response.responses
                failed_tokens = []
                for idx, resp in enumerate(responses):
                    if not resp.success:
                        failed_tokens.append(tokens[idx])
                
                # Deleta os tokens inválidos do banco de dados
                if failed_tokens:
                    db.session.query(PushSubscription).filter(PushSubscription.fcm_token.in_(failed_tokens)).delete(synchronize_session=False)
                    db.session.commit()

        except Exception as e:
            # Em um ambiente de produção, logar este erro é crucial
            print(f"Erro ao enviar notificação push para user_id {user_id}: {e}")


    @staticmethod
    def create_notification(user_id: int, message: str, url: str = None):
        """Cria uma notificação no banco e dispara um push."""
        if not user_id:
            return
            
        import traceback
        import sys
        if url == '#URGENTE_SENS':
            print("====================================", file=sys.stderr)
            print(f"URGENTE_SENS CRIADO: {message}", file=sys.stderr)
            traceback.print_stack(file=sys.stderr)
            print("====================================", file=sys.stderr)
            
        notification = Notification(user_id=user_id, message=message, url=url)
        db.session.add(notification)
        
        # Dispara a notificação push
        NotificationService._trigger_push_notification(
            user_id=user_id,
            title="Nova Notificação - EsFAS",
            body=message,
            url=url
        )

    @staticmethod
    def create_notification_for_roles(school_id: int, roles: list[str], message: str, url: str = None):
        """Cria notificações para todos os usuários com certas funções em uma escola."""
        if not school_id or not roles:
            return

        user_ids_query = (
            select(User.id)
            .join(UserSchool)
            .where(
                UserSchool.school_id == school_id,
                UserSchool.role.in_(roles)
            )
        )
        user_ids = db.session.scalars(user_ids_query).all()

        for user_id in user_ids:
            NotificationService.create_notification(user_id, message, url)
        
        db.session.flush()

    @staticmethod
    @cached(cache=dropdown_cache)
    def get_notifications_for_dropdown(user_id: int, limit: int = 7):
        """Busca as notificações mais recentes e a contagem de não lidas."""
        unread_count_query = (
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id, Notification.is_read == False)
        )
        unread_count = db.session.scalar(unread_count_query)

        recent_notifications_query = (
            select(Notification)
            .where(Notification.user_id == user_id)
            .order_by(Notification.created_at.desc())
            .limit(limit)
        )
        recent_notifications = db.session.scalars(recent_notifications_query).all()
        
        return unread_count, recent_notifications

    @staticmethod
    def get_all_notifications(user_id: int, page: int = 1, per_page: int = 20):
        """Busca todas as notificações de um usuário de forma paginada."""
        stmt = (
            select(Notification)
            .where(Notification.user_id == user_id)
            .order_by(Notification.created_at.desc())
        )
        return db.paginate(stmt, page=page, per_page=per_page, error_out=False)

    @staticmethod
    def mark_as_read(notification_id: int, user_id: int):
        """Marca uma notificação específica como lida, verificando a propriedade."""
        notification = db.session.get(Notification, notification_id)
        if notification:
            notification.is_read = True
            return True
        return False

    @staticmethod
    def mark_all_as_read(user_id: int):
        """Marca todas as notificações não lidas de um usuário como lidas."""
        stmt = (
            update(Notification)
            .where(Notification.user_id == user_id, Notification.is_read == False)
            .values(is_read=True)
        )
        result = db.session.execute(stmt)
        return result.rowcount > 0
