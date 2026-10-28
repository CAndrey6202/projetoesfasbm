from datetime import date, timedelta
from flask import current_app
from sqlalchemy import select, or_
from sqlalchemy.orm import joinedload

from ..models.database import db
from ..models.disciplina_turma import DisciplinaTurma
from ..models.turma import Turma
from ..models.instrutor import Instrutor
from ..models.disciplina import Disciplina
# Adicionado para podermos alterar os agendamentos futuros
from ..models.horario import Horario
from ..models.semana import Semana
from ..models.diario_classe import DiarioClasse


class VinculoService:
    @staticmethod
    def get_all_vinculos(turma_filtrada_id: int = None, school_id: int = None, edicao_id: int = None, ciclo_id: int = None):
        """
        Busca vínculos.
        - Se turma_filtrada_id for fornecido, filtra por ela.
        - Se school_id for fornecido, garante que só traga vínculos dessa escola (segurança/filtro geral).
        - Se edicao_id for fornecido, filtra turmas pertencentes a essa edição.
        - Se ciclo_id for fornecido, filtra disciplinas pertencentes a esse ciclo.
        """
        query = db.select(DisciplinaTurma).options(
            joinedload(DisciplinaTurma.instrutor_1).joinedload(Instrutor.user),
            joinedload(DisciplinaTurma.instrutor_2).joinedload(Instrutor.user),
            joinedload(DisciplinaTurma.disciplina).joinedload(Disciplina.ciclo),
            joinedload(DisciplinaTurma.disciplina).joinedload(Disciplina.turma)
        )

        query = query.join(DisciplinaTurma.disciplina).join(Disciplina.turma)

        if turma_filtrada_id:
            query = query.where(Turma.id == turma_filtrada_id)

        if school_id:
            query = query.where(Turma.school_id == school_id)

        if edicao_id:
            query = query.where(Turma.edicao_id == edicao_id)

        if ciclo_id:
            query = query.where(Disciplina.ciclo_id == ciclo_id)

        query = query.order_by(DisciplinaTurma.id.desc())
        return db.session.scalars(query).all()

    @staticmethod
    def add_vinculo(data: dict):
        disciplina_id = data.get('disciplina_id')
        instrutor_id_1 = data.get('instrutor_id_1')
        instrutor_id_2 = data.get('instrutor_id_2')

        if not disciplina_id:
            return False, 'A disciplina é obrigatória.'

        if not instrutor_id_1 and not instrutor_id_2:
            return False, 'Pelo menos um instrutor deve ser selecionado.'

        instrutor_1 = int(instrutor_id_1) if instrutor_id_1 else 0
        instrutor_2 = int(instrutor_id_2) if instrutor_id_2 else 0

        if instrutor_1 > 0 and instrutor_1 == instrutor_2:
            return False, 'Os instrutores 1 e 2 não podem ser a mesma pessoa.'

        disciplina = db.session.get(Disciplina, disciplina_id)
        if not disciplina or not disciplina.turma:
            return False, 'Disciplina ou turma associada não encontrada.'

        pelotao_nome = disciplina.turma.nome

        vinculo_existente = db.session.scalars(select(DisciplinaTurma).filter_by(
            disciplina_id=disciplina_id,
            pelotao=pelotao_nome
        )).first()

        try:
            if vinculo_existente:
                return False, 'Já existe um vínculo para esta disciplina nesta turma. Edite o vínculo existente na lista.'
            else:
                novo_vinculo = DisciplinaTurma(
                    pelotao=pelotao_nome,
                    disciplina_id=disciplina_id,
                    instrutor_id_1=instrutor_1 if instrutor_1 > 0 else None,
                    instrutor_id_2=instrutor_2 if instrutor_2 > 0 else None
                )
                db.session.add(novo_vinculo)
                message = 'Vínculo criado com sucesso!'

            db.session.commit()
            return True, message
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Erro ao adicionar vínculo: {e}")
            return False, f"Erro ao adicionar vínculo: {str(e)}"

    @staticmethod
    def edit_vinculo(vinculo_id: int, data: dict):
        vinculo = db.session.get(DisciplinaTurma, vinculo_id)
        if not vinculo:
            return False, 'Vínculo não encontrado.'

        # Salva o id antigo da disciplina para procurar os horários correspondentes
        old_disciplina_id = vinculo.disciplina_id
        old_pelotao = vinculo.pelotao

        disciplina_id = data.get('disciplina_id')
        instrutor_id_1 = data.get('instrutor_id_1')
        instrutor_id_2 = data.get('instrutor_id_2')

        if not disciplina_id:
            return False, 'A disciplina é obrigatória.'

        if not instrutor_id_1 and not instrutor_id_2:
            return False, 'Pelo menos um instrutor deve ser selecionado.'

        instrutor_1 = int(instrutor_id_1) if instrutor_id_1 else 0
        instrutor_2 = int(instrutor_id_2) if instrutor_id_2 else 0

        if instrutor_1 > 0 and instrutor_1 == instrutor_2:
            return False, 'Os instrutores 1 e 2 não podem ser a mesma pessoa.'

        disciplina = db.session.get(Disciplina, disciplina_id)
        if not disciplina or not disciplina.turma:
            return False, 'Disciplina ou turma associada não encontrada.'

        pelotao_nome = disciplina.turma.nome

        try:
            # 1. Atualiza o Vínculo Central
            vinculo.pelotao = pelotao_nome
            vinculo.disciplina_id = disciplina_id
            vinculo.instrutor_id_1 = instrutor_1 if instrutor_1 > 0 else None
            vinculo.instrutor_id_2 = instrutor_2 if instrutor_2 > 0 else None

            # 2. REGRA AJUSTADA: Altera apenas os horários FUTUROS e SEM DIÁRIO para o novo instrutor.
            # Garante absolutamente que aulas passadas (data_aula < hoje) ou que já foram ministradas/concluídas/assinadas permaneçam intocadas!
            dias_map = {'segunda': 0, 'terca': 1, 'quarta': 2, 'quinta': 3, 'sexta': 4, 'sabado': 5, 'domingo': 6}
            horarios_alvo = db.session.scalars(
                select(Horario)
                .join(Semana, Horario.semana_id == Semana.id)
                .where(
                    Horario.disciplina_id == old_disciplina_id,
                    Horario.pelotao == old_pelotao
                )
            ).all()

            hoje = date.today()
            for horario in horarios_alvo:
                if horario.status == 'concluido':
                    continue

                semana_obj = db.session.get(Semana, horario.semana_id)
                if not semana_obj:
                    continue

                offset = dias_map.get(horario.dia_semana, 0)
                data_aula = semana_obj.data_inicio + timedelta(days=offset)

                # Se a aula já é do passado (data_aula < hoje), NUNCA atualizar o instrutor, independentemente de estar como pendente ou confirmado
                if data_aula < hoje:
                    continue

                # Se existe diário de classe preenchido/assinado/concluído/validado para esta aula, NUNCA atualizar
                diario_existente = db.session.scalar(
                    select(DiarioClasse).where(
                        DiarioClasse.data_aula == data_aula,
                        DiarioClasse.disciplina_id == old_disciplina_id,
                        DiarioClasse.status.in_(['assinado', 'concluido', 'validado']),
                        DiarioClasse.is_deleted == False
                    ).limit(1)
                )
                if diario_existente:
                    continue

                # Apenas aulas pendentes/confirmadas que ainda não aconteceram e não têm diário serão alteradas
                horario.disciplina_id = disciplina_id
                horario.pelotao = pelotao_nome
                if instrutor_1 > 0:
                    horario.instrutor_id = instrutor_1
                elif instrutor_2 > 0:
                    horario.instrutor_id = instrutor_2
                horario.instrutor_id_2 = instrutor_2 if instrutor_2 > 0 else None

            db.session.commit()
            return True, 'Vínculo atualizado! Os próximos agendamentos da disciplina já estão com o novo instrutor.'
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Erro ao editar vínculo: {e}")
            return False, f"Erro ao editar vínculo: {str(e)}"

    @staticmethod
    def delete_vinculo(vinculo_id: int):
        vinculo = db.session.get(DisciplinaTurma, vinculo_id)
        if not vinculo:
            return False, 'Vínculo não encontrado.'

        try:
            db.session.delete(vinculo)
            db.session.commit()
            return True, 'Vínculo excluído com sucesso!'
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Erro ao excluir vínculo: {e}")
            return False, f"Erro ao excluir vínculo: {str(e)}"