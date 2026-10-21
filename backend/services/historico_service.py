# backend/services/historico_service.py

from datetime import datetime, timezone
from ..models.database import db
from ..models.aluno import Aluno
from ..models.disciplina import Disciplina
from ..models.historico_disciplina import HistoricoDisciplina
from ..models.historico import HistoricoAluno
from ..models.processo_disciplina import ProcessoDisciplina
from sqlalchemy import select, and_
from flask import current_app
from itertools import chain

class HistoricoService:

    @staticmethod
    def get_unified_historico_for_aluno(aluno_id: int):
        """Busca e unifica todos os registros de histórico para um aluno, incluindo funções e processos."""
        
        # 1. Busca histórico de atividades (funções, etc.)
        atividades = db.session.scalars(
            select(HistoricoAluno).where(HistoricoAluno.aluno_id == aluno_id)
        ).all()

        # 2. Busca histórico de processos disciplinares
        processos = db.session.scalars(
            select(ProcessoDisciplina).where(ProcessoDisciplina.aluno_id == aluno_id)
        ).all()
        
        # 3. Formata os processos para um formato unificado
        eventos_processos = []
        for p in processos:
            eventos_processos.append({
                'tipo': 'Processo Disciplinar',
                'descricao': f"Abertura de processo: {p.fato_constatado}",
                'data_inicio': p.data_ocorrencia,
                'data_fim': p.data_decisao
            })

        # Função auxiliar para padronizar datas (transformar naive em aware) para ordenação segura
        def padronizar_data(item):
            dt = getattr(item, 'data_inicio', None) if not isinstance(item, dict) else item.get('data_inicio')
            
            # Se a data for nula ou inválida, joga para o final da lista
            if not isinstance(dt, datetime):
                return datetime.min.replace(tzinfo=timezone.utc)
            
            # Se a data for "naive" (sem fuso), injetamos UTC para permitir a comparação
            if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
                return dt.replace(tzinfo=timezone.utc)
            
            return dt

        # 4. Unifica e ordena todos os eventos pela data de início usando a função padronizadora
        todos_eventos = sorted(
            chain(atividades, eventos_processos),
            key=padronizar_data,
            reverse=True
        )
        
        return todos_eventos

    @staticmethod
    def get_historico_disciplinas_for_aluno(aluno_id: int):
        """Busca todos os registros de disciplinas (matrículas) para um aluno específico."""
        from sqlalchemy.orm import joinedload
        stmt = (
            select(HistoricoDisciplina)
            .options(
                joinedload(HistoricoDisciplina.disciplina).joinedload(Disciplina.ciclo),
                joinedload(HistoricoDisciplina.disciplina).joinedload(Disciplina.turma),
            )
            .where(HistoricoDisciplina.aluno_id == aluno_id)
            .order_by(HistoricoDisciplina.id)
        )
        return db.session.scalars(stmt).all()

    @staticmethod
    def avaliar_aluno(historico_id: int, form_data: dict, from_admin: bool = False):
        """Lança ou atualiza as notas de um aluno em uma disciplina e calcula a média final."""
        registro = db.session.get(HistoricoDisciplina, historico_id)
        if not registro:
            return False, "Registro de matrícula não encontrado.", None

        try:
            nota_p1 = float(form_data.get('nota_p1')) if form_data.get('nota_p1') else None
            nota_p2 = float(form_data.get('nota_p2')) if form_data.get('nota_p2') else None
            
            nota_rec = None
            if from_admin:
                nota_rec = float(form_data.get('nota_rec')) if form_data.get('nota_rec') else None
                registro.nota_rec = nota_rec

            registro.nota_p1 = nota_p1
            registro.nota_p2 = nota_p2

            if nota_p1 is not None and nota_p2 is not None:
                mpd = (nota_p1 + nota_p2) / 2
                if from_admin and mpd < 7.0 and nota_rec is not None:
                    mfd = (nota_p1 + nota_p2 + nota_rec) / 3
                    registro.nota = round(mfd, 3)
                else:
                    registro.nota = round(mpd, 3)
            else:
                registro.nota = None

            db.session.commit()
            return True, "Avaliação salva com sucesso.", registro.aluno_id
        except (ValueError, TypeError):
            db.session.rollback()
            return False, "As notas devem ser números válidos.", registro.aluno_id
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Erro ao salvar avaliação: {e}")
            return False, "Ocorreu um erro ao salvar a avaliação.", registro.aluno_id
