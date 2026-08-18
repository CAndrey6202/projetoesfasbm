# backend/services/aluno_service.py



import os

import uuid

from datetime import datetime

from flask import current_app, session

from werkzeug.utils import secure_filename

from sqlalchemy import select, or_

from sqlalchemy.exc import IntegrityError

from sqlalchemy.orm import joinedload



from ..models.database import db

from ..models.aluno import Aluno

from ..models.user import User

from ..models.historico import HistoricoAluno

from ..models.turma import Turma

from ..models.disciplina import Disciplina

from ..models.historico_disciplina import HistoricoDisciplina

from ..models.user_school import UserSchool

from utils.image_utils import allowed_file, compress_image_to_memory

from utils.normalizer import normalize_name



# ImportaÃ§Ã£o para garantir o contexto da sessÃ£o

from .user_service import UserService



ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}





def _save_profile_picture(file):

    """Valida, COMPRIME e salva a imagem de perfil."""

    if not file:

        return None, "Nenhum arquivo enviado."

    

    # Valida extensÃ£o bÃ¡sica

    if not allowed_file(file.filename, file.stream, ALLOWED_EXTENSIONS):

        return None, "Tipo de arquivo de imagem nÃ£o permitido."

    

    # COMPRESSÃƒO AUTOMÃ�TICA (256x256, Qualidade 60, JPEG)

    compressed_file = compress_image_to_memory(file, max_size=(256, 256), quality=60)

    

    if not compressed_file:

        return None, "Erro ao processar a imagem. O arquivo pode estar corrompido."



    try:

        # Gera nome Ãºnico

        filename = secure_filename(compressed_file.filename)

        ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else 'jpg'

        unique_filename = f"{uuid.uuid4()}.{ext}"

        

        upload_folder = os.path.join(current_app.static_folder, 'uploads', 'profile_pics')

        os.makedirs(upload_folder, exist_ok=True)

        file_path = os.path.join(upload_folder, unique_filename)

        

        # Salva o arquivo COMPRIMIDO

        compressed_file.save(file_path)

        

        return unique_filename, "Arquivo salvo com sucesso"

    except Exception as e:

        current_app.logger.error(f"Erro ao salvar foto de perfil: {e}")

        return None, "Erro ao salvar o arquivo de imagem."





class AlunoService:

    @staticmethod

    def get_all_alunos(user, nome_turma=None, search_term=None, page=1, per_page=15):

        active_school_id = UserService.get_current_school_id()



        if not active_school_id:

            return db.paginate(select(Aluno).where(db.false()), page=page, per_page=per_page)



        stmt = (

            select(Aluno)

            .join(User, Aluno.user_id == User.id)

            .join(Turma, Aluno.turma_id == Turma.id)

            .join(UserSchool, User.id == UserSchool.user_id)

            .where(

                User.is_active.is_(True),

                UserSchool.role == 'aluno',

                UserSchool.school_id == active_school_id,

                Turma.school_id == active_school_id

            )

            .options(

                joinedload(Aluno.user),

                joinedload(Aluno.turma),

            )

            .order_by(User.nome_completo, User.matricula)

        )



        if nome_turma:

            stmt = stmt.where(Turma.nome == nome_turma)

        

        if search_term:

            like_term = f"%{search_term}%"

            stmt = stmt.where(

                or_(

                    User.nome_completo.ilike(like_term),

                    User.matricula.ilike(like_term),

                    User.nome_de_guerra.ilike(like_term)

                )

            )



        alunos_paginados = db.paginate(stmt, page=page, per_page=per_page, error_out=False)

        return alunos_paginados



    @staticmethod

    def get_aluno_by_id(aluno_id: int):

        active_school = UserService.get_current_school_id()

        aluno = db.session.get(Aluno, aluno_id)

        

        if aluno and aluno.turma and aluno.turma.school_id == active_school:

            return aluno

        return None

        

    @staticmethod

    def update_profile_picture(aluno_id: int, file):

        aluno = AlunoService.get_aluno_by_id(aluno_id)

        if not aluno:

            return False, "Aluno nÃ£o encontrado ou pertence a outra escola."



        if file:

            # Remove a foto antiga

            if aluno.foto_perfil and aluno.foto_perfil != 'default.png':

                old_path = os.path.join(current_app.static_folder, 'uploads', 'profile_pics', aluno.foto_perfil)

                if os.path.exists(old_path):

                    try:

                        os.remove(old_path)

                    except Exception as e:

                        current_app.logger.error(f"NÃ£o foi possÃ­vel remover a foto antiga: {e}")



            # Salva a nova foto jÃ¡ comprimida

            filename, msg = _save_profile_picture(file)

            if filename:

                aluno.foto_perfil = filename

                return True, "Foto de perfil atualizada com sucesso."

            else:

                return False, msg

        return False, "Nenhum arquivo de imagem fornecido."



    @staticmethod

    def update_aluno(aluno_id: int, data: dict):

        aluno = AlunoService.get_aluno_by_id(aluno_id)

        if not aluno:

            return False, "Aluno nÃ£o encontrado."



        nome_completo = normalize_name(data.get('nome_completo'))

        email_novo = (data.get('email') or '').strip()

        opm = (data.get('opm') or '').strip()

        turma_id_val = data.get('turma_id')



        if not all([nome_completo, opm, email_novo, turma_id_val]):

            return False, "Todos os campos de dados bÃ¡sicos sÃ£o obrigatÃ³rios."



        try:

            new_turma = db.session.get(Turma, turma_id_val)

            if not new_turma or new_turma.school_id != UserService.get_current_school_id():

                return False, "Turma invÃ¡lida ou de outra escola."



            if aluno.user and aluno.user.email != email_novo:

                if db.session.scalar(select(User).where(User.email == email_novo, User.id != aluno.user.id)):

                    return False, "O e-mail fornecido jÃ¡ estÃ¡ em uso por outra conta."



            if aluno.user:

                aluno.user.nome_completo = nome_completo

                aluno.user.email = email_novo

                posto_selecionado = data.get('posto_graduacao')

                if posto_selecionado == 'Outro':

                    aluno.user.posto_graduacao = data.get('posto_graduacao_outro')

                else:

                    aluno.user.posto_graduacao = posto_selecionado



            aluno.opm = opm

            aluno.turma_id = int(turma_id_val)



            db.session.commit()

            return True, "Perfil do aluno atualizado com sucesso!"



        except Exception as e:

            db.session.rollback()

            current_app.logger.error(f"Erro inesperado ao atualizar aluno: {e}")

            return False, f"Ocorreu um erro inesperado ao atualizar o perfil. Detalhes: {str(e)}"

            

    @staticmethod

    def update_funcao_aluno(aluno_id: int, form_data: dict):

        aluno = AlunoService.get_aluno_by_id(aluno_id)

        if not aluno:

            return False, "Aluno nÃ£o encontrado."

        

        try:

            funcao_nova = form_data.get('funcao_atual')

            data_evento_str = form_data.get('data_evento')

            data_evento = datetime.strptime(data_evento_str, '%Y-%m-%d') if data_evento_str else datetime.utcnow()

            

            funcao_antiga = aluno.funcao_atual



            if funcao_antiga and funcao_antiga != funcao_nova:

                historico_antigo = db.session.scalars(select(HistoricoAluno).where(

                    HistoricoAluno.aluno_id == aluno_id,

                    HistoricoAluno.tipo == 'FunÃ§Ã£o de Escola',

                    HistoricoAluno.descricao.like(f"%Assumiu a funÃ§Ã£o de {funcao_antiga}%"),

                    HistoricoAluno.data_fim.is_(None)

                ).order_by(HistoricoAluno.data_inicio.desc())).first()

                if historico_antigo:

                    historico_antigo.data_fim = data_evento



            if funcao_nova and funcao_nova != funcao_antiga:

                novo_historico = HistoricoAluno(

                    aluno_id=aluno_id,

                    tipo='FunÃ§Ã£o de Escola',

                    descricao=f'Assumiu a funÃ§Ã£o de {funcao_nova}.',

                    data_inicio=data_evento

                )

                db.session.add(novo_historico)



            aluno.funcao_atual = funcao_nova if funcao_nova else None

            

            db.session.commit()

            return True, "FunÃ§Ã£o do aluno atualizada com sucesso!"

        except Exception as e:

            db.session.rollback()

            current_app.logger.error(f"Erro ao atualizar funÃ§Ã£o do aluno: {e}")

            return False, "Ocorreu um erro ao atualizar a funÃ§Ã£o."



    @staticmethod

    def delete_aluno(aluno_id: int):

        aluno = AlunoService.get_aluno_by_id(aluno_id)

        if not aluno:

            return False, "Aluno nÃ£o encontrado."



        try:

            user_a_deletar = aluno.user

            if user_a_deletar:

                db.session.delete(user_a_deletar)

                db.session.commit()

                return True, "Aluno e todos os seus registros foram excluÃ­dos com sucesso!"

            else:

                db.session.delete(aluno)

                db.session.commit()

                return True, "Perfil de aluno Ã³rfÃ£o removido com sucesso."

        except Exception as e:

            db.session.rollback()

            current_app.logger.error(f"Erro ao excluir aluno: {e}")

            return False, f"Erro ao excluir aluno: {str(e)}"



    @staticmethod

    def check_pending_mandatory_evaluations(user):

        """

        Verifica se um usuÃ¡rio (Aluno) tem alguma CampanhaAvaliacao obrigatÃ³ria ativa e pendente.

        Retorna (bloqueio: bool, campanha_id: int ou None)

        """




        aluno = getattr(user, 'aluno_profile', None)

        if not aluno or not aluno.turma:

            return False, None



        from ..models.avaliacao_instrutor import CampanhaAvaliacao, RespostaAvaliacao

        from ..models.horario import Horario

        from ..models.instrutor import Instrutor

        from ..models.disciplina_turma import DisciplinaTurma

        from flask import session



        active_edicao_id = session.get('active_edicao_id')



        # Buscar campanhas obrigatÃ³rias e ativas para a escola do aluno

        campanhas = db.session.query(CampanhaAvaliacao).filter_by(

            school_id=aluno.turma.school_id,

            is_ativa=True,

            is_obrigatoria=True

        ).filter(

            (CampanhaAvaliacao.edicao_id == active_edicao_id) | (CampanhaAvaliacao.edicao_id.is_(None))

        ).all()



        if not campanhas:

            return False, None



        # Identificar instrutores vÃ¡lidos da turma (ignorando 'C Al / S Ens')

        instrutores_ids = set()

        vinculos = db.session.query(DisciplinaTurma).filter_by(pelotao=aluno.turma.nome).all()

        for v in vinculos:

            if v.instrutor_id_1: instrutores_ids.add(v.instrutor_id_1)

            if v.instrutor_id_2: instrutores_ids.add(v.instrutor_id_2)



        horarios = db.session.query(Horario).filter_by(pelotao=aluno.turma.nome).all()

        for h in horarios:

            if h.instrutor_id: instrutores_ids.add(h.instrutor_id)



        if not instrutores_ids:

            return False, None



        instrutores_banco = db.session.query(Instrutor).filter(

            Instrutor.id.in_(instrutores_ids),

            Instrutor.school_id == aluno.turma.school_id

        ).all()



        valid_instrutores_count = 0

        for inst in instrutores_banco:

            u = inst.user

            nome_guerra = (u.nome_de_guerra or "").lower()

            nome_completo = (u.nome_completo or "").lower()

            if "c al" in nome_guerra or "s ens" in nome_guerra or "sens" in nome_guerra or "c al" in nome_completo or "s ens" in nome_completo:

                continue

            valid_instrutores_count += 1



        if valid_instrutores_count == 0:

            return False, None



        # Verificar se o aluno jÃ¡ respondeu para TODOS os instrutores vÃ¡lidos nestas campanhas

        for campanha in campanhas:

            respostas_dadas = db.session.query(RespostaAvaliacao).filter_by(

                campanha_id=campanha.id,

                aluno_id=aluno.id

            ).count()

            if respostas_dadas < valid_instrutores_count:
                # Há pendência! Bloqueia imediatamente.
                return True, campanha.id

        return False, None

