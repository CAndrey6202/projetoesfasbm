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
from .log_service import LogService

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
        from flask import session
        from flask_login import current_user
        active_school = UserService.get_current_school_id()
        instrutor = db.session.get(Instrutor, instrutor_id)
        is_dec = bool(session.get('is_dec_mode') and current_user.is_authenticated and current_user.role == 'super_admin')
        
        if instrutor and (instrutor.school_id == active_school or is_dec or not active_school):
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

    @staticmethod
    def unificar_instrutor_com_usuario_existente(source_instrutor: Instrutor, target_user: User, form_data: dict) -> tuple[bool, str]:
        """
        Unifica o cadastro de um instrutor (source_instrutor.user) em um usuário já existente (target_user),
        transferindo todos os vínculos escolares, turmas, horários, avaliações, delegações e histórico,
        mantendo apenas um usuário, senha e cadastro (target_user).
        """
        try:
            source_user = source_instrutor.user
            if not source_user or source_user.id == target_user.id:
                return False, "Usuário de origem e destino são os mesmos."

            source_id = source_user.id
            target_id = target_user.id
            source_nome = source_user.nome_completo or source_user.nome_de_guerra or source_user.matricula
            target_nome = target_user.nome_completo or target_user.nome_de_guerra or target_user.matricula
            old_matricula = source_user.matricula
            new_matricula = target_user.matricula
            school_id = source_instrutor.school_id

            # 1. Liberar e-mail, username e matrícula do source_user temporariamente para não colidir com constraints
            source_user.email = None
            source_user.username = None
            source_user.matricula = f"_del_{source_id}_{str(old_matricula)[:10]}"
            db.session.flush()

            # 2. Atualizar dados do target_user conforme preenchido no formulário
            new_email = (form_data.get('email') or '').strip().lower()
            if new_email:
                conflict_email = db.session.scalar(
                    select(User.id).where(User.email == new_email, User.id != target_id)
                )
                if not conflict_email:
                    target_user.email = new_email

            nome_completo = form_data.get('nome_completo')
            if nome_completo:
                target_user.nome_completo = nome_completo.strip()
            elif not target_user.nome_completo:
                target_user.nome_completo = source_user.nome_completo

            nome_de_guerra = form_data.get('nome_de_guerra')
            if nome_de_guerra:
                target_user.nome_de_guerra = nome_de_guerra.strip()
            elif not target_user.nome_de_guerra:
                target_user.nome_de_guerra = source_user.nome_de_guerra

            posto = form_data.get('posto_graduacao')
            if posto == 'Outro':
                posto = form_data.get('posto_graduacao_outro')
            if posto:
                target_user.posto_graduacao = posto
            elif not target_user.posto_graduacao:
                target_user.posto_graduacao = source_user.posto_graduacao

            if not target_user.is_active:
                target_user.is_active = True

            # Se o target_user tiver role 'aluno', eleva para 'instrutor'
            if target_user.role in ['aluno', None, '']:
                target_user.role = 'instrutor'

            # 3. Unificar todos os perfis de Instrutor de source_user
            from backend.models.disciplina_turma import DisciplinaTurma
            from backend.models.horario import Horario
            from backend.models.avaliacao_instrutor import RespostaAvaliacao
            from backend.models.banco_questoes import QuestaoBanco, DelegacaoProva
            from backend.models.aluno import Aluno
            from backend.models.user_school import UserSchool

            source_instrutores = db.session.scalars(
                select(Instrutor).where(Instrutor.user_id == source_id)
            ).all()

            for s_inst in source_instrutores:
                # Procura se target_user já possui perfil de instrutor na mesma escola
                t_inst = db.session.scalar(
                    select(Instrutor).where(
                        Instrutor.user_id == target_id,
                        Instrutor.school_id == s_inst.school_id
                    )
                )

                if t_inst:
                    # Migrar vínculos e referências de s_inst para t_inst
                    # A. DisciplinaTurma
                    dts = db.session.scalars(
                        select(DisciplinaTurma).where(
                            or_(
                                DisciplinaTurma.instrutor_id_1 == s_inst.id,
                                DisciplinaTurma.instrutor_id_2 == s_inst.id
                            )
                        )
                    ).all()
                    for dt in dts:
                        if dt.instrutor_id_1 == s_inst.id:
                            if dt.instrutor_id_2 == t_inst.id:
                                dt.instrutor_id_1 = t_inst.id
                                dt.instrutor_id_2 = None
                            else:
                                dt.instrutor_id_1 = t_inst.id
                        elif dt.instrutor_id_2 == s_inst.id:
                            if dt.instrutor_id_1 == t_inst.id:
                                dt.instrutor_id_2 = None
                            else:
                                dt.instrutor_id_2 = t_inst.id

                    # B. Horario
                    horarios = db.session.scalars(
                        select(Horario).where(
                            or_(
                                Horario.instrutor_id == s_inst.id,
                                Horario.instrutor_id_2 == s_inst.id
                            )
                        )
                    ).all()
                    for h in horarios:
                        if h.instrutor_id == s_inst.id:
                            if h.instrutor_id_2 == t_inst.id:
                                h.instrutor_id = t_inst.id
                                h.instrutor_id_2 = None
                            else:
                                h.instrutor_id = t_inst.id
                        elif h.instrutor_id_2 == s_inst.id:
                            if h.instrutor_id == t_inst.id:
                                h.instrutor_id_2 = None
                            else:
                                h.instrutor_id_2 = t_inst.id

                    # C. RespostaAvaliacao
                    RespostaAvaliacao.query.filter_by(instrutor_id=s_inst.id).update(
                        {RespostaAvaliacao.instrutor_id: t_inst.id}, synchronize_session=False
                    )

                    # D. DelegacaoProva
                    DelegacaoProva.query.filter_by(instrutor_id=s_inst.id).update(
                        {DelegacaoProva.instrutor_id: t_inst.id}, synchronize_session=False
                    )

                    # E. QuestaoBanco
                    QuestaoBanco.query.filter_by(instrutor_id=s_inst.id).update(
                        {QuestaoBanco.instrutor_id: t_inst.id}, synchronize_session=False
                    )

                    # Se for a escola do instrutor sendo editado, aplicar dados do form
                    if s_inst.id == source_instrutor.id:
                        tel = form_data.get('telefone')
                        if tel:
                            t_inst.telefone = tel.strip()
                        elif not t_inst.telefone:
                            t_inst.telefone = s_inst.telefone

                        is_rr_val = form_data.get('is_rr')
                        t_inst.is_rr = (is_rr_val == '1' or is_rr_val is True)
                    else:
                        if not t_inst.telefone and s_inst.telefone:
                            t_inst.telefone = s_inst.telefone

                    if not t_inst.assinatura_padrao_path and s_inst.assinatura_padrao_path:
                        t_inst.assinatura_padrao_path = s_inst.assinatura_padrao_path
                    if (not t_inst.foto_perfil or t_inst.foto_perfil == 'default.png') and s_inst.foto_perfil and s_inst.foto_perfil != 'default.png':
                        t_inst.foto_perfil = s_inst.foto_perfil

                    db.session.delete(s_inst)
                else:
                    # target_user não tem instrutor nessa escola; reaproveita o registro s_inst
                    s_inst.user_id = target_id
                    if s_inst.id == source_instrutor.id:
                        tel = form_data.get('telefone')
                        if tel:
                            s_inst.telefone = tel.strip()
                        is_rr_val = form_data.get('is_rr')
                        s_inst.is_rr = (is_rr_val == '1' or is_rr_val is True)

            # 4. Unificar vínculos escolares (UserSchool)
            source_user_schools = db.session.scalars(
                select(UserSchool).where(UserSchool.user_id == source_id)
            ).all()

            for uss in source_user_schools:
                ust = db.session.scalar(
                    select(UserSchool).where(
                        UserSchool.user_id == target_id,
                        UserSchool.school_id == uss.school_id
                    )
                )
                if ust:
                    # Eleva o role se necessário
                    if ust.role == 'aluno' and uss.role != 'aluno':
                        ust.role = uss.role
                else:
                    db.session.add(UserSchool(user_id=target_id, school_id=uss.school_id, role=uss.role))

            # Garantir vínculo na escola atual
            if school_id:
                school_link = db.session.scalar(
                    select(UserSchool).where(
                        UserSchool.user_id == target_id,
                        UserSchool.school_id == school_id
                    )
                )
                if not school_link:
                    db.session.add(UserSchool(user_id=target_id, school_id=school_id, role='instrutor'))

            # 5. Migrar dados de Aluno (se houver)
            alunos_source = db.session.scalars(
                select(Aluno).where(Aluno.user_id == source_id)
            ).all()
            for al in alunos_source:
                al.user_id = target_id

            # 6. Migrar todas as outras tabelas que referenciam users.id
            from backend.models.admin_log import AdminLog
            from backend.models.background_job import BackgroundJob
            from backend.models.chamado_suporte import ChamadoSuporte
            from backend.models.desligamento import RegistroDesligamento
            from backend.models.diario_classe import DiarioClasse
            from backend.models.elogio import Elogio
            from backend.models.fada_avaliacao import FadaAvaliacao
            from backend.models.image_asset import ImageAsset
            from backend.models.notification import Notification
            from backend.models.password_reset_token import PasswordResetToken
            from backend.models.processo_disciplina import ProcessoDisciplina
            from backend.models.push_subscription import PushSubscription
            from backend.models.recurso import Recurso
            from backend.models.resposta import Resposta
            from backend.models.site_config import SiteConfig
            
            AdminLog.query.filter_by(user_id=source_id).update({AdminLog.user_id: target_id}, synchronize_session=False)
            BackgroundJob.query.filter_by(user_id=source_id).update({BackgroundJob.user_id: target_id}, synchronize_session=False)
            ChamadoSuporte.query.filter_by(solicitante_id=source_id).update({ChamadoSuporte.solicitante_id: target_id}, synchronize_session=False)
            RegistroDesligamento.query.filter_by(admin_id=source_id).update({RegistroDesligamento.admin_id: target_id}, synchronize_session=False)
            DiarioClasse.query.filter_by(responsavel_id=source_id).update({DiarioClasse.responsavel_id: target_id}, synchronize_session=False)
            DiarioClasse.query.filter_by(instrutor_assinante_id=source_id).update({DiarioClasse.instrutor_assinante_id: target_id}, synchronize_session=False)
            Elogio.query.filter_by(registrado_por_id=source_id).update({Elogio.registrado_por_id: target_id}, synchronize_session=False)
            FadaAvaliacao.query.filter_by(lancador_id=source_id).update({FadaAvaliacao.lancador_id: target_id}, synchronize_session=False)
            FadaAvaliacao.query.filter_by(presidente_id=source_id).update({FadaAvaliacao.presidente_id: target_id}, synchronize_session=False)
            FadaAvaliacao.query.filter_by(membro1_id=source_id).update({FadaAvaliacao.membro1_id: target_id}, synchronize_session=False)
            FadaAvaliacao.query.filter_by(membro2_id=source_id).update({FadaAvaliacao.membro2_id: target_id}, synchronize_session=False)
            ImageAsset.query.filter_by(uploaded_by=source_id).update({ImageAsset.uploaded_by: target_id}, synchronize_session=False)
            Notification.query.filter_by(user_id=source_id).update({Notification.user_id: target_id}, synchronize_session=False)
            PasswordResetToken.query.filter_by(user_id=source_id).delete(synchronize_session=False)
            PasswordResetToken.query.filter_by(created_by_admin_id=source_id).update({PasswordResetToken.created_by_admin_id: target_id}, synchronize_session=False)
            ProcessoDisciplina.query.filter_by(relator_id=source_id).update({ProcessoDisciplina.relator_id: target_id}, synchronize_session=False)
            ProcessoDisciplina.query.filter_by(autoridade_recurso_id=source_id).update({ProcessoDisciplina.autoridade_recurso_id: target_id}, synchronize_session=False)
            PushSubscription.query.filter_by(user_id=source_id).delete(synchronize_session=False)
            Recurso.query.filter_by(aluno_id=source_id).update({Recurso.aluno_id: target_id}, synchronize_session=False)
            Recurso.query.filter_by(instrutor_id=source_id).update({Recurso.instrutor_id: target_id}, synchronize_session=False)
            Recurso.query.filter_by(instrutor2_id=source_id).update({Recurso.instrutor2_id: target_id}, synchronize_session=False)
            Resposta.query.filter_by(user_id=source_id).update({Resposta.user_id: target_id}, synchronize_session=False)
            SiteConfig.query.filter_by(updated_by=source_id).update({SiteConfig.updated_by: target_id}, synchronize_session=False)
            
            # 7. Desconectar relacionamentos em memória do source_user para evitar cascata indesejada do SQLAlchemy
            source_user.alunos_profiles = []
            source_user.notifications = []
            source_user.push_subscriptions = []
            source_user.instrutor_profile = None

            db.session.flush()

            # 8. Deletar o source_user
            db.session.delete(source_user)
            db.session.commit()

            # 9. Auditoria / Log
            LogService.log(
                action="Unificou Cadastros",
                details=f"O cadastro do instrutor {source_nome} (Matrícula antiga: {old_matricula}) foi unificado com sucesso ao usuário {target_nome} (Matrícula: {new_matricula}). Todas as informações e vínculos escolares foram preservados sob o mesmo usuário e senha.",
                school_id=school_id
            )

            return True, f"Cadastros unificados com sucesso! As informações e vínculos escolares foram integrados ao cadastro do usuário {target_user.nome_completo or target_user.matricula} (Matrícula {new_matricula})."

        except Exception as e:
            db.session.rollback()
            current_app.logger.exception(f"Erro ao unificar cadastros de instrutor: {e}")
            return False, f"Erro ao unificar cadastros: {str(e)}"
