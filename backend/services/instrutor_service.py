# backend/services/instrutor_service.py

import os
import uuid
from flask import current_app
from werkzeug.utils import secure_filename
from sqlalchemy import select, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from backend.models.database import db
from backend.models.instrutor import Instrutor
from backend.models.user import User
from backend.models.user_school import UserSchool
from utils.image_utils import allowed_file, compress_image_to_memory
from utils.normalizer import normalize_matricula, normalize_name

# Importação para garantir o contexto da sessão e utilitários
from .user_service import UserService

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

def _save_profile_picture(file):
    """Valida, COMPRIME e salva a imagem de perfil."""
    if not file:
        return None, "Nenhum arquivo enviado."
    
    if not allowed_file(file.filename, file.stream, ALLOWED_EXTENSIONS):
        return None, "Tipo de arquivo de imagem não permitido."

    # COMPRESSÃO AUTOMÁTICA
    compressed_file = compress_image_to_memory(file, max_size=(256, 256), quality=60)
    
    if not compressed_file:
        return None, "Erro ao processar a imagem. O arquivo pode estar corrompido."

    try:
        filename = secure_filename(compressed_file.filename)
        ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else 'jpg'
        unique_filename = f"{uuid.uuid4()}.{ext}"
        
        upload_folder = os.path.join(current_app.static_folder, 'uploads', 'profile_pics')
        os.makedirs(upload_folder, exist_ok=True)
        file_path = os.path.join(upload_folder, unique_filename)
        
        # Salva o proxy comprimido
        compressed_file.save(file_path)
        
        return unique_filename, "Arquivo salvo com sucesso"
    except Exception as e:
        current_app.logger.error(f"Erro ao salvar foto de perfil: {e}")
        return None, "Erro ao salvar o arquivo de imagem."


class InstrutorService:
    
    @staticmethod
    def _repair_missing_profiles(school_id: int):
        """
        AUTO-CORREÇÃO (SELF-HEALING) - VERSÃO BLINDADA
        Identifica usuários que têm ACESSO à escola (UserSchool) mas não têm PERFIL (Instrutor).
        Corrige um por um para garantir que erros individuais não travem o processo.
        """
        if not school_id:
            return

        try:
            # 1. Quem DEVERIA estar lá? (Todos vinculados que NÃO são alunos)
            # Isso pega Instrutores, Admins, Programadores, etc.
            stmt_staff_users = (
                select(UserSchool.user_id)
                .where(
                    UserSchool.school_id == school_id,
                    UserSchool.role != 'aluno'
                )
            )
            users_should_have_profile = set(db.session.scalars(stmt_staff_users).all())

            # 2. Quem REALMENTE está lá?
            stmt_existing_profiles = (
                select(Instrutor.user_id)
                .where(Instrutor.school_id == school_id)
            )
            users_actually_have_profile = set(db.session.scalars(stmt_existing_profiles).all())

            # 3. Quem está faltando?
            missing_ids = users_should_have_profile - users_actually_have_profile
            
            if missing_ids:
                current_app.logger.warning(f"[AUTO-REPAIR] Escola {school_id}: Reparando {len(missing_ids)} perfis faltantes...")
                
                for uid in missing_ids:
                    try:
                        # Verifica novamente para evitar Race Condition
                        exists = db.session.scalar(
                            select(Instrutor).where(Instrutor.user_id == uid, Instrutor.school_id == school_id)
                        )
                        if not exists:
                            # Tenta copiar dados (foto/telefone) de outro perfil desse usuário (outra escola)
                            # para não começar "pelado"
                            existing_data = db.session.execute(
                                select(Instrutor)
                                .where(Instrutor.user_id == uid)
                                .limit(1)
                            ).scalar_one_or_none()

                            foto = existing_data.foto_perfil if existing_data else 'default.png'
                            telefone = existing_data.telefone if existing_data else None
                            is_rr = existing_data.is_rr if existing_data else False

                            new_prof = Instrutor(
                                user_id=uid,
                                school_id=school_id,
                                foto_perfil=foto,
                                telefone=telefone,
                                is_rr=is_rr
                            )
                            db.session.add(new_prof)
                            db.session.commit() # Commit INDIVIDUAL para garantir que salve
                            current_app.logger.info(f"[AUTO-REPAIR] Perfil criado para User ID {uid} na escola {school_id}.")
                    except Exception as loop_e:
                        db.session.rollback()
                        current_app.logger.error(f"[AUTO-REPAIR] Falha ao corrigir User ID {uid}: {loop_e}")

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Erro CRÍTICO no processo de auto-repair: {e}")

    @staticmethod
    def get_all_instrutores(user=None, search_term=None, page=1, per_page=15):
        active_school_id = UserService.get_current_school_id()
        
        if not active_school_id:
            return db.paginate(select(Instrutor).where(db.false()), page=page, per_page=per_page)

        # Dispara a correção antes de listar
        InstrutorService._repair_missing_profiles(active_school_id)

        stmt = (
            select(Instrutor)
            .join(User, Instrutor.user_id == User.id)
            .where(
                User.is_active.is_(True),
                Instrutor.school_id == active_school_id
            )
            .options(joinedload(Instrutor.user))
            .order_by(User.nome_completo, User.matricula)
        )

        if search_term:
            like_term = f"%{search_term}%"
            stmt = stmt.where(
                or_(
                    User.nome_completo.ilike(like_term),
                    User.matricula.ilike(like_term),
                    User.nome_de_guerra.ilike(like_term)
                )
            )

        return db.paginate(stmt, page=page, per_page=per_page, error_out=False)

    @staticmethod
    def get_all_instrutores_sem_paginacao(user=None):
        active_school_id = UserService.get_current_school_id()
        if not active_school_id:
            return []
            
        # Dispara a correção antes de listar (Essencial para dropdowns de Vinculos)
        InstrutorService._repair_missing_profiles(active_school_id)

        stmt = (
            select(Instrutor)
            .join(User, Instrutor.user_id == User.id)
            .where(
                User.is_active.is_(True),
                Instrutor.school_id == active_school_id
            )
            .options(joinedload(Instrutor.user))
            .order_by(User.nome_completo)
        )
        
        return db.session.scalars(stmt).unique().all()
    
    @staticmethod
    def update_profile_picture(instrutor_id: int, file):
        instrutor = db.session.get(Instrutor, instrutor_id)
        if not instrutor:
            return False, "Instrutor não encontrado."

        if file:
            if instrutor.foto_perfil and instrutor.foto_perfil != 'default.png':
                old_path = os.path.join(current_app.static_folder, 'uploads', 'profile_pics', instrutor.foto_perfil)
                if os.path.exists(old_path):
                    try:
                        os.remove(old_path)
                    except Exception as e:
                        current_app.logger.error(f"Não foi possível remover a foto antiga: {e}")

            filename, msg = _save_profile_picture(file)
            if filename:
                instrutor.foto_perfil = filename
                return True, "Foto de perfil atualizada com sucesso."
            else:
                return False, msg
        return False, "Nenhum arquivo de imagem fornecido."

    @staticmethod
    def _find_user_by_email_or_username(email: str):
        email = (email or '').strip()
        if not email:
            return None
        return db.session.scalar(select(User).where(User.email == email))

    @staticmethod
    def _ensure_user_school(user_id: int, school_id: int, role: str = 'instrutor'):
        if not school_id:
            return
        exists = db.session.scalar(
            select(UserSchool.id).where(
                UserSchool.user_id == user_id,
                UserSchool.school_id == school_id
            )
        )
        if not exists:
            db.session.add(UserSchool(user_id=user_id, school_id=school_id, role=role))

    @staticmethod
    def create_full_instrutor(data, school_id):
        try:
            matricula = normalize_matricula(data.get('matricula'))
            email = (data.get('email') or '').strip().lower()
            password = (data.get('password') or '').strip()
            nome_completo = normalize_name(data.get('nome_completo'))
            nome_de_guerra = normalize_name(data.get('nome_de_guerra'))
            
            posto = data.get('posto_graduacao')
            if posto == 'Outro':
                posto = data.get('posto_graduacao_outro')

            telefone = (data.get('telefone') or '').strip() or None
            is_rr = data.get('is_rr', False)

            if not matricula:
                return False, "Matrícula inválida."
            if not email:
                return False, "O campo E-mail é obrigatório."
            if not password:
                return False, "O campo Senha é obrigatório."

            existing_user = db.session.scalar(select(User).where(User.matricula == matricula))
            
            if existing_user:
                if existing_user.email and existing_user.email != email:
                    return False, f"A Matrícula '{matricula}' já existe, mas o e-mail não confere."

                existing_profile = db.session.scalar(select(Instrutor).where(
                    Instrutor.user_id == existing_user.id,
                    Instrutor.school_id == school_id
                ))

                if not existing_profile:
                    new_profile = Instrutor(
                        user_id=existing_user.id,
                        school_id=school_id,
                        telefone=telefone,
                        is_rr=is_rr
                    )
                    db.session.add(new_profile)
                
                InstrutorService._ensure_user_school(existing_user.id, int(school_id), role='instrutor')
                
                db.session.commit()
                return True, f"Instrutor {existing_user.nome_completo} vinculado à esta escola com sucesso!"
            
            if db.session.scalar(select(User.id).where(User.email == email)):
                return False, f"O e-mail '{email}' já está em uso."

            user = User(
                email=email,
                username=email,
                role='instrutor',
                nome_completo=nome_completo or None,
                nome_de_guerra=nome_de_guerra or None,
                matricula=matricula,
                posto_graduacao=posto,
                is_active=True
            )
            user.set_password(password)
            db.session.add(user)
            db.session.flush()

            instrutor = Instrutor(
                user_id=user.id,
                school_id=school_id,
                telefone=telefone,
                is_rr=is_rr
            )
            db.session.add(instrutor)

            if school_id:
                InstrutorService._ensure_user_school(user.id, int(school_id), role='instrutor')

            db.session.commit()
            return True, "Instrutor cadastrado com sucesso!"

        except IntegrityError as e:
            db.session.rollback()
            current_app.logger.error(f"Erro de Integridade: {e}")
            return False, "Erro de integridade (dados duplicados)."
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception("Erro ao criar instrutor")
            return False, "Erro inesperado ao criar instrutor."

    @staticmethod
    def create_profile_for_user(user_id: int, data: dict):
        school_id = UserService.get_current_school_id()
        if not school_id:
            return False, "Escola não selecionada na sessão."

        user = db.session.get(User, user_id)
        if not user:
            return False, "Usuário não encontrado."
        
        existing = db.session.scalar(select(Instrutor).where(
            Instrutor.user_id == user_id, 
            Instrutor.school_id == school_id
        ))
        if existing:
            return False, "Este usuário já possui um perfil de instrutor nesta escola."

        try:
            posto = data.get('posto_graduacao')
            if posto == 'Outro':
                posto = data.get('posto_graduacao_outro')
            
            telefone = (data.get('telefone') or '').strip() or None
            is_rr = data.get('is_rr', False)

            user.posto_graduacao = posto

            new_profile = Instrutor(
                user_id=user_id,
                school_id=school_id,
                telefone=telefone,
                is_rr=is_rr
            )
            db.session.add(new_profile)
            
            InstrutorService._ensure_user_school(user_id, school_id)
            
            db.session.commit()
            return True, "Perfil de instrutor criado com sucesso."

        except Exception:
            db.session.rollback()
            current_app.logger.exception("Erro ao criar perfil de instrutor")
            return False, "Erro ao salvar o perfil."

    @staticmethod
    def get_instrutor_by_id(instrutor_id: int):
        active_school = UserService.get_current_school_id()
        instrutor = db.session.get(Instrutor, instrutor_id)
        
        if instrutor and instrutor.school_id == active_school:
            return instrutor
        return None

    @staticmethod
    def update_instrutor(instrutor_id: int, data: dict):
        instrutor = db.session.get(Instrutor, instrutor_id)
        if not instrutor:
            return False, "Instrutor não encontrado."
        
        if instrutor.school_id != UserService.get_current_school_id():
            return False, "Permissão negada: Este instrutor pertence a outra escola."

        try:
            nome_completo = normalize_name(data.get('nome_completo'))
            nome_de_guerra = normalize_name(data.get('nome_de_guerra'))
            
            email = (data.get('email') or '').strip().lower()
            telefone = (data.get('telefone') or '').strip()

            posto = data.get('posto_graduacao')
            if posto == 'Outro':
                posto = data.get('posto_graduacao_outro')

            is_rr = data.get('is_rr', False)

            user = db.session.get(User, instrutor.user_id)
            if user:
                if nome_completo: user.nome_completo = nome_completo
                if nome_de_guerra: user.nome_de_guerra = nome_de_guerra
                if email and user.email != email:
                    exists = db.session.scalar(select(User.id).where(User.email == email, User.id != user.id))
                    if exists:
                        raise IntegrityError("E-mail em uso.", params=None, orig=None)
                    user.email = email
                if posto:
                    user.posto_graduacao = posto

            instrutor.telefone = (telefone or None)
            instrutor.is_rr = is_rr

            db.session.commit()
            return True, "Instrutor atualizado com sucesso."
        except IntegrityError as e:
            db.session.rollback()
            return False, "O e-mail fornecido já está em uso."
        except Exception as e:
            db.session.rollback()
            return False, f"Erro ao atualizar: {str(e)}"

    @staticmethod
    def delete_instrutor(instrutor_id: int):
        instrutor = db.session.get(Instrutor, instrutor_id)
        if not instrutor:
            return False, "Instrutor não encontrado."
        
        from flask_login import current_user
        current_school = UserService.get_current_school_id()
        is_admin_global = getattr(current_user, 'role', '') in ['super_admin', 'programador'] or getattr(current_user, 'is_sens', False)
        
        if not is_admin_global and current_school and instrutor.school_id != current_school:
            return False, "Permissão negada: Este instrutor pertence a outra escola."

        try:
            from backend.models.disciplina_turma import DisciplinaTurma
            from backend.models.horario import Horario
            from backend.models.aluno import Aluno

            user_id = instrutor.user_id
            school_id = instrutor.school_id
            user = db.session.get(User, user_id)

            # 1. Desvincula o instrutor das turmas/disciplinas da escola
            dts = DisciplinaTurma.query.filter(
                (DisciplinaTurma.instrutor_id_1 == instrutor.id) | 
                (DisciplinaTurma.instrutor_id_2 == instrutor.id)
            ).all()
            for dt in dts:
                if dt.instrutor_id_1 == instrutor.id:
                    dt.instrutor_id_1 = None
                if dt.instrutor_id_2 == instrutor.id:
                    dt.instrutor_id_2 = None

            # 2. Trata horários agendados
            horarios_1 = Horario.query.filter_by(instrutor_id=instrutor.id).all()
            for h in horarios_1:
                # Se havia 2º instrutor no horário, promove o 2º instrutor para titular
                if h.instrutor_id_2:
                    h.instrutor_id = h.instrutor_id_2
                    h.instrutor_id_2 = None
                else:
                    db.session.delete(h)

            horarios_2 = Horario.query.filter_by(instrutor_id_2=instrutor.id).all()
            for h in horarios_2:
                h.instrutor_id_2 = None

            # 3. Trata avaliações de campanha vinculadas ao perfil de instrutor
            try:
                from backend.models.avaliacao_instrutor import RespostaAvaliacao
                RespostaAvaliacao.query.filter_by(instrutor_id=instrutor.id).delete(synchronize_session=False)
            except Exception:
                pass

            # 4. Trata delegações de prova
            try:
                from backend.models.banco_questoes import DelegacaoProva, RascunhoProva, QuestaoBanco
                delegacoes = DelegacaoProva.query.filter_by(instrutor_id=instrutor.id).all()
                for d in delegacoes:
                    RascunhoProva.query.filter_by(delegacao_id=d.id).delete(synchronize_session=False)
                    db.session.delete(d)

                # Reatribui questões cadastradas para não corromper o banco de questões
                questoes_banco = QuestaoBanco.query.filter_by(instrutor_id=instrutor.id).all()
                if questoes_banco:
                    outro_inst = Instrutor.query.filter(Instrutor.school_id == school_id, Instrutor.id != instrutor.id).first()
                    if outro_inst:
                        for q in questoes_banco:
                            q.instrutor_id = outro_inst.id
                    else:
                        for q in questoes_banco:
                            db.session.delete(q)
            except Exception:
                pass

            # 5. Flush das alterações nos filhos para desvincular chaves estrangeiras no PostgreSQL
            db.session.flush()

            # 6. Remove o perfil de instrutor e o vínculo da escola
            db.session.delete(instrutor)
            
            links = UserSchool.query.filter_by(user_id=user_id, school_id=school_id).all()
            for l in links:
                db.session.delete(l)

            # 7. Flush da remoção do instrutor
            db.session.flush()

            # 8. Se o usuário não tem nenhuma outra escola nem outro perfil e não é admin, remove o usuário órfão
            if user and user.role == 'instrutor':
                outros_instrutores = Instrutor.query.filter(Instrutor.user_id == user_id, Instrutor.id != instrutor.id).count()
                outras_escolas = UserSchool.query.filter(UserSchool.user_id == user_id, UserSchool.school_id != school_id).count()
                aluno_profile = db.session.scalar(select(Aluno).filter_by(user_id=user_id))
                
                if outros_instrutores == 0 and outras_escolas == 0 and not aluno_profile:
                    db.session.delete(user)
            
            db.session.commit()
            return True, "Instrutor e seus vínculos foram removidos com sucesso."
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Erro ao excluir instrutor {instrutor_id}: {str(e)}")
            return False, f"Erro ao excluir: {str(e)}"
