# backend/services/semana_service.py

from datetime import date
from flask import current_app
from sqlalchemy import select, and_, delete, or_
from ..models.database import db

# Models
from ..models.semana import Semana
from ..models.horario import Horario
from ..models.ciclo import Ciclo
from ..models.disciplina import Disciplina
from ..models.disciplina_turma import DisciplinaTurma
from ..models.turma import Turma
from ..models.historico_disciplina import HistoricoDisciplina 

from .user_service import UserService

class SemanaService:
    
    @staticmethod
    def get_semana_selecionada(semana_id_str=None, ciclo_id=None, override_school_id=None, override_edicao_id=None):
        from flask import session
        active_school_id = override_school_id if override_school_id else UserService.get_current_school_id()
        # Se um override for passado (mesmo que seja None, indicando turmas globais/sem edição), usamos ele
        active_edicao = override_edicao_id if override_edicao_id is not None else session.get('active_edicao_id')
        
        if not active_school_id:
            return None

        if semana_id_str and str(semana_id_str).isdigit():
            semana = db.session.get(Semana, int(semana_id_str))
            if semana and semana.ciclo and semana.ciclo.school_id == active_school_id and semana.ciclo.edicao_id == active_edicao:
                return semana

        today = date.today()
        stmt = (
            select(Semana)
            .join(Ciclo)
            .where(Ciclo.school_id == active_school_id, Ciclo.edicao_id == active_edicao)
        )
        
        if ciclo_id:
            stmt = stmt.where(Semana.ciclo_id == ciclo_id)

        semana_atual = db.session.scalars(
            stmt.where(
                Semana.data_inicio <= today,
                Semana.data_fim >= today
            )
        ).first()
        
        if semana_atual:
            return semana_atual

        return db.session.scalars(
            stmt.order_by(Semana.data_inicio.desc())
        ).first()

    @staticmethod
    def add_semana(data: dict):
        nome = data.get('nome')
        data_inicio = data.get('data_inicio')
        data_fim = data.get('data_fim')
        ciclo_id = data.get('ciclo_id')

        if not all([nome, data_inicio, data_fim, ciclo_id]):
            return False, 'Todos os campos, incluindo o ciclo, são obrigatórios.'

        active_school_id = UserService.get_current_school_id()
        ciclo = db.session.get(Ciclo, ciclo_id)
        
        if not ciclo:
            return False, 'Ciclo não encontrado.'
            
        if active_school_id and ciclo.school_id != active_school_id:
            return False, 'Você não pode criar semanas em um ciclo de outra escola.'

        if data_inicio > data_fim:
            return False, 'A data de início não pode ser posterior à data de fim.'

        semana_conflitante = db.session.scalar(
            select(Semana).where(
                Semana.ciclo_id == ciclo_id,
                and_(
                    Semana.data_inicio <= data_fim,
                    Semana.data_fim >= data_inicio
                )
            ).limit(1)
        )

        if semana_conflitante:
            return False, f"Conflito de datas com a semana: '{semana_conflitante.nome}'."

        try:
            nova_semana = Semana(
                nome=nome,
                data_inicio=data_inicio,
                data_fim=data_fim,
                ciclo_id=ciclo_id,
                mostrar_periodo_13=data.get('mostrar_periodo_13', False),
                mostrar_periodo_14=data.get('mostrar_periodo_14', False),
                mostrar_periodo_15=data.get('mostrar_periodo_15', False),
                mostrar_periodo_16=data.get('mostrar_periodo_16', False),
                mostrar_periodo_17=data.get('mostrar_periodo_17', False),
                mostrar_periodo_18=data.get('mostrar_periodo_18', False),
                mostrar_sabado=data.get('mostrar_sabado', False),
                periodos_sabado=int(data.get('periodos_sabado') or 0),
                mostrar_domingo=data.get('mostrar_domingo', False),
                periodos_domingo=int(data.get('periodos_domingo') or 0)
            )
            db.session.add(nova_semana)
            db.session.commit()
            return True, 'Nova semana cadastrada com sucesso!'
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Erro ao adicionar semana: {e}")
            return False, f"Erro ao adicionar semana: {str(e)}"

    @staticmethod
    def update_semana(semana_id: int, data: dict):
        semana = db.session.get(Semana, semana_id)
        if not semana: return False, 'Semana não encontrada.'
        
        active_school = UserService.get_current_school_id()
        if active_school and semana.ciclo.school_id != active_school:
            return False, "Permissão negada: Semana pertence a outra escola."

        semana.nome = data.get('nome')
        semana.data_inicio = data.get('data_inicio')
        semana.data_fim = data.get('data_fim')
        
        novo_ciclo_id = data.get('ciclo_id')
        if novo_ciclo_id and int(novo_ciclo_id) != semana.ciclo_id:
             novo_ciclo = db.session.get(Ciclo, novo_ciclo_id)
             if novo_ciclo and novo_ciclo.school_id == active_school:
                 semana.ciclo_id = novo_ciclo_id
             else:
                 return False, "Ciclo de destino inválido ou de outra escola."
        
        # CORREÇÃO: Usar o valor contido em 'data' em vez de checar se a chave existe.
        # O controller envia explicitamente True/False nestas chaves.
        semana.mostrar_periodo_13 = bool(data.get('mostrar_periodo_13'))
        semana.mostrar_periodo_14 = bool(data.get('mostrar_periodo_14'))
        semana.mostrar_periodo_15 = bool(data.get('mostrar_periodo_15'))
        semana.mostrar_periodo_16 = bool(data.get('mostrar_periodo_16'))
        semana.mostrar_periodo_17 = bool(data.get('mostrar_periodo_17'))
        semana.mostrar_periodo_18 = bool(data.get('mostrar_periodo_18'))
        
        semana.mostrar_sabado = bool(data.get('mostrar_sabado'))
        semana.periodos_sabado = int(data.get('periodos_sabado') or 0)
        
        semana.mostrar_domingo = bool(data.get('mostrar_domingo'))
        semana.periodos_domingo = int(data.get('periodos_domingo') or 0)

        try:
            db.session.commit()
            return True, 'Semana atualizada com sucesso.'
        except Exception as e:
            db.session.rollback()
            return False, f"Erro ao atualizar: {str(e)}"

    @staticmethod
    def delete_semana(semana_id: int):
        semana = db.session.get(Semana, semana_id)
        if not semana: return False, 'Semana não encontrada.'
        
        active_school = UserService.get_current_school_id()
        if active_school and semana.ciclo.school_id != active_school:
            return False, "Permissão negada."

        try:
            db.session.query(Horario).filter_by(semana_id=semana_id).delete()
            db.session.delete(semana)
            db.session.commit()
            return True, 'Semana deletada com sucesso.'
        except Exception as e:
            db.session.rollback()
            return False, f"Erro ao deletar: {str(e)}"

    # --- DELETAR CICLO: MODO CASCATA TOTAL ---
    @staticmethod
    def deletar_ciclo(ciclo_id):
        """
        Deleta um ciclo e TODAS as suas dependências (Histórico, Semanas, Aulas, Disciplinas).
        """
        ciclo = db.session.get(Ciclo, ciclo_id)
        if not ciclo:
            return False, "Ciclo não encontrado."

        active_school_id = UserService.get_current_school_id()
        if active_school_id and ciclo.school_id != active_school_id:
             return False, "Permissão negada para excluir este ciclo."

        try:
            # 1. IDENTIFICAR IDs RELACIONADOS
            # Recupera IDs de todas as Disciplinas deste ciclo
            subquery_disciplinas = select(Disciplina.id).where(Disciplina.ciclo_id == ciclo.id)
            
            # Recupera IDs de todas as Semanas deste ciclo
            subquery_semanas = select(Semana.id).where(Semana.ciclo_id == ciclo.id)

            # 2. LIMPEZA PROFUNDA (ORDEM DE DEPENDÊNCIA)
            
            # A) Apagar HISTÓRICO DAS DISCIPLINAS (O culpado do erro anterior)
            # Como o histórico aponta para disciplinas, deve ser apagado antes delas.
            db.session.execute(
                delete(HistoricoDisciplina).where(
                    HistoricoDisciplina.disciplina_id.in_(subquery_disciplinas)
                )
            )

            # B) Apagar HORÁRIOS (Aulas)
            # Ligados às disciplinas OU semanas do ciclo
            db.session.execute(
                delete(Horario).where(
                    or_(
                        Horario.semana_id.in_(subquery_semanas),
                        Horario.disciplina_id.in_(subquery_disciplinas)
                    )
                )
            )

            # C) Apagar VÍNCULOS (DisciplinaTurma)
            db.session.execute(
                delete(DisciplinaTurma).where(
                    DisciplinaTurma.disciplina_id.in_(subquery_disciplinas)
                )
            )

            # D) Apagar SEMANAS do ciclo
            db.session.execute(
                delete(Semana).where(Semana.ciclo_id == ciclo.id)
            )

            # E) Apagar DISCIPLINAS do ciclo
            # (Agora é seguro apagar, pois o histórico foi removido no passo A)
            db.session.execute(
                delete(Disciplina).where(Disciplina.ciclo_id == ciclo.id)
            )

            # F) Apagar TURMAS do ciclo (Se o modelo Turma tiver ciclo_id)
            if hasattr(Turma, 'ciclo_id'):
                db.session.execute(
                    delete(Turma).where(Turma.ciclo_id == ciclo.id)
                )

            # 3. FINALMENTE, APAGAR O CICLO
            db.session.execute(
                delete(Ciclo).where(Ciclo.id == ciclo.id)
            )
            
            # Limpa a sessão para garantir consistência
            db.session.expire_all()
            
            db.session.commit()
            return True, "Ciclo Excluído! Todos os dados (incluindo notas e histórico) foram apagados."
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Erro fatal ao excluir ciclo: {str(e)}")
            return False, f"Erro ao excluir ciclo: {str(e)}"
