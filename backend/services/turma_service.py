from flask import current_app
from sqlalchemy import select, func, or_, and_
from sqlalchemy.orm import selectinload, joinedload
from datetime import datetime
from ..models.database import db
from ..models.turma import Turma
from ..models.aluno import Aluno
from ..models.user import User
from ..models.disciplina_turma import DisciplinaTurma
from ..models.turma_cargo import TurmaCargo
from ..models.historico import HistoricoAluno 
from ..models.historico_disciplina import HistoricoDisciplina
from ..models.disciplina import Disciplina
from ..models.horario import Horario
from ..models.ciclo import Ciclo
from ..models.diario_classe import DiarioClasse
from ..models.frequencia import FrequenciaAluno
from ..models.aluno_ciclo_turma import AlunoCicloTurma

class TurmaService:

    @staticmethod
    def get_ciclos_da_escola(school_id, edicao_id=None):
        if not school_id:
            return []
        stmt = select(Ciclo).where(Ciclo.school_id == school_id)
        if edicao_id:
            stmt = stmt.where(or_(Ciclo.edicao_id == edicao_id, Ciclo.edicao_id.is_(None)))
        return db.session.scalars(stmt.order_by(Ciclo.id.asc())).all()

    @staticmethod
    def sincronizar_historico_ciclos(school_id, edicao_id=None):
        """
        Garante que todos os alunos que já tiveram diários de classe ou notas lançadas
        em ciclos anteriores tenham seu vínculo (aluno_id, ciclo_id, turma_id)
        preservado na tabela AlunoCicloTurma, mesmo que tenham mudado de turma depois.
        Também limpa matrículas sem nota geradas acidentalmente em turmas diferentes
        nos ciclos anteriores.
        """
        if not school_id:
            return
        try:
            ciclos = TurmaService.get_ciclos_da_escola(school_id, edicao_id)
            if not ciclos:
                return
            ciclo_ids = [c.id for c in ciclos]

            # 1. Carrega mapeamentos já existentes para estes ciclos
            existentes = db.session.scalars(
                select(AlunoCicloTurma).where(AlunoCicloTurma.ciclo_id.in_(ciclo_ids))
            ).all()
            mapa_existente = {(v.aluno_id, v.ciclo_id): v.turma_id for v in existentes}
            alunos_com_qualquer_ciclo = {v.aluno_id for v in existentes}
            mudou = False

            # 2. Fonte mais fiel do passado: FrequenciaAluno em DiarioClasse daquele Ciclo
            freq_rows = db.session.execute(
                select(
                    FrequenciaAluno.aluno_id,
                    Disciplina.ciclo_id,
                    DiarioClasse.turma_id,
                    func.count(FrequenciaAluno.id).label('qtd')
                )
                .join(DiarioClasse, FrequenciaAluno.diario_id == DiarioClasse.id)
                .join(Disciplina, DiarioClasse.disciplina_id == Disciplina.id)
                .join(Turma, DiarioClasse.turma_id == Turma.id)
                .where(
                    Turma.school_id == school_id,
                    DiarioClasse.is_deleted == False,
                    Disciplina.ciclo_id.in_(ciclo_ids)
                )
                .group_by(FrequenciaAluno.aluno_id, Disciplina.ciclo_id, DiarioClasse.turma_id)
                .order_by(func.count(FrequenciaAluno.id).desc())
            ).all()

            for aluno_id, cid, tid, _qtd in freq_rows:
                if (aluno_id, cid) not in mapa_existente and tid:
                    db.session.add(AlunoCicloTurma(aluno_id=aluno_id, ciclo_id=cid, turma_id=tid))
                    mapa_existente[(aluno_id, cid)] = tid
                    alunos_com_qualquer_ciclo.add(aluno_id)
                    mudou = True

            # 3. Segunda fonte: HistoricoDisciplina (priorizando disciplinas com notas lançadas e ID mais antigo)
            hist_rows = db.session.execute(
                select(
                    HistoricoDisciplina.aluno_id,
                    Disciplina.ciclo_id,
                    Disciplina.turma_id,
                    HistoricoDisciplina.nota_p1,
                    HistoricoDisciplina.nota_p2,
                    HistoricoDisciplina.nota,
                    HistoricoDisciplina.id
                )
                .join(Disciplina, HistoricoDisciplina.disciplina_id == Disciplina.id)
                .join(Turma, Disciplina.turma_id == Turma.id)
                .where(
                    Turma.school_id == school_id,
                    Disciplina.ciclo_id.in_(ciclo_ids),
                    Disciplina.turma_id.isnot(None)
                )
                .order_by(HistoricoDisciplina.id.asc())
            ).all()

            # Ordena priorizando quem tem nota lançada, depois o registro mais antigo
            hist_rows_sorted = sorted(
                hist_rows,
                key=lambda r: (0 if (r[3] is not None or r[4] is not None or r[5] is not None) else 1, r[6])
            )
            for aluno_id, cid, tid, _p1, _p2, _nota, _hid in hist_rows_sorted:
                if (aluno_id, cid) not in mapa_existente and tid:
                    db.session.add(AlunoCicloTurma(aluno_id=aluno_id, ciclo_id=cid, turma_id=tid))
                    mapa_existente[(aluno_id, cid)] = tid
                    alunos_com_qualquer_ciclo.add(aluno_id)
                    mudou = True

            # 4. Para os alunos atuais da escola/edição:
            # Se o aluno ainda não tem vínculo no ciclo mais recente (ou no 1º ciclo caso nunca tenha tido aula),
            # vincula a turma atual (Aluno.turma_id)
            stmt_alunos = select(Aluno).join(Turma, Aluno.turma_id == Turma.id).where(Turma.school_id == school_id)
            if edicao_id:
                stmt_alunos = stmt_alunos.where(Turma.edicao_id == edicao_id)
            alunos_atuais = db.session.scalars(stmt_alunos).all()

            primeiro_ciclo_id = ciclos[0].id
            ultimo_ciclo_id = ciclos[-1].id

            for a in alunos_atuais:
                if not a.turma_id:
                    continue
                if a.id not in alunos_com_qualquer_ciclo:
                    # Nunca teve histórico registrado em nenhum ciclo -> vincula ao primeiro ciclo
                    db.session.add(AlunoCicloTurma(aluno_id=a.id, ciclo_id=primeiro_ciclo_id, turma_id=a.turma_id))
                    mapa_existente[(a.id, primeiro_ciclo_id)] = a.turma_id
                    alunos_com_qualquer_ciclo.add(a.id)
                    mudou = True
                elif len(ciclos) > 1 and (a.id, ultimo_ciclo_id) not in mapa_existente:
                    # Já tinha histórico em ciclo anterior (ex: Ciclo 1 na Turma 1) e agora está na turma atual -> vincula ao último ciclo se mudou de turma
                    turmas_anteriores = {
                        mapa_existente[(a.id, c.id)]
                        for c in ciclos[:-1]
                        if (a.id, c.id) in mapa_existente
                    }
                    if a.turma_id not in turmas_anteriores:
                        db.session.add(AlunoCicloTurma(aluno_id=a.id, ciclo_id=ultimo_ciclo_id, turma_id=a.turma_id))
                        mapa_existente[(a.id, ultimo_ciclo_id)] = a.turma_id
                        mudou = True

            if mudou:
                db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.warning(f"Aviso ao sincronizar histórico de ciclos: {e}")

    @staticmethod
    def get_mapa_turma_por_ciclo_aluno(aluno_id: int) -> dict[int, int]:
        """Retorna {ciclo_id: turma_id} para um aluno específico."""
        rows = db.session.scalars(
            select(AlunoCicloTurma).where(AlunoCicloTurma.aluno_id == aluno_id)
        ).all()
        return {r.ciclo_id: r.turma_id for r in rows}

    @staticmethod
    def get_turma_id_aluno_no_ciclo(aluno_id: int, ciclo_id: int = None, default_turma_id: int = None) -> int:
        if not ciclo_id:
            return default_turma_id
        v = db.session.scalar(
            select(AlunoCicloTurma.turma_id).where(
                AlunoCicloTurma.aluno_id == aluno_id,
                AlunoCicloTurma.ciclo_id == ciclo_id
            )
        )
        return v if v is not None else default_turma_id

    @staticmethod
    def get_alunos_da_turma_no_ciclo(turma_id: int, ciclo_id: int = None, diarios_bloco=None):
        """
        Retorna a lista ordenada de Alunos que pertencem/pertenceram à `turma_id`
        no `ciclo_id` informado (ou no bloco de diários informado).
        Garante que diários, relatórios e chamadas de ciclos encerrados mantenham
        exatamente os alunos que eram daquela turma naquele ciclo.
        """
        turma = db.session.get(Turma, turma_id)
        if turma:
            TurmaService.sincronizar_historico_ciclos(turma.school_id, turma.edicao_id)

        if not ciclo_id and diarios_bloco:
            first_d = diarios_bloco[0]
            if getattr(first_d, 'disciplina', None) and first_d.disciplina.ciclo_id:
                ciclo_id = first_d.disciplina.ciclo_id

        # Se for um bloco de diários já lançado que possui registros em FrequenciaAluno,
        # preserva exatamente os alunos que têm frequência naquele bloco (+ vinculados ao ciclo/turma)
        if diarios_bloco:
            diario_ids = [d.id for d in diarios_bloco if d.id]
            if diario_ids:
                freq_aluno_ids = set(db.session.scalars(
                    select(FrequenciaAluno.aluno_id).where(FrequenciaAluno.diario_id.in_(diario_ids)).distinct()
                ).all())
                if freq_aluno_ids:
                    if ciclo_id:
                        vinculados_ciclo_turma = set(db.session.scalars(
                            select(AlunoCicloTurma.aluno_id).where(
                                AlunoCicloTurma.ciclo_id == ciclo_id,
                                AlunoCicloTurma.turma_id == turma_id
                            )
                        ).all())
                        outros_ciclo = set(db.session.scalars(
                            select(AlunoCicloTurma.aluno_id).where(
                                AlunoCicloTurma.ciclo_id == ciclo_id,
                                AlunoCicloTurma.turma_id != turma_id
                            )
                        ).all())
                        # Mantém quem tem frequência no diário (desde que não tenha sido criado por engano após mudança)
                        # ou quem é explicitamente desta turma neste ciclo
                        if vinculados_ciclo_turma:
                            target_ids = (freq_aluno_ids - outros_ciclo) | vinculados_ciclo_turma
                        else:
                            target_ids = freq_aluno_ids
                    else:
                        target_ids = freq_aluno_ids

                    if target_ids:
                        return db.session.scalars(
                            select(Aluno)
                            .join(User, Aluno.user_id == User.id)
                            .options(joinedload(Aluno.user))
                            .where(Aluno.id.in_(target_ids))
                            .order_by(Aluno.num_aluno, User.nome_de_guerra, User.nome_completo)
                        ).all()

        if ciclo_id:
            vinculados_nesta_turma = set(db.session.scalars(
                select(AlunoCicloTurma.aluno_id).where(
                    AlunoCicloTurma.ciclo_id == ciclo_id,
                    AlunoCicloTurma.turma_id == turma_id
                )
            ).all())
            vinculados_em_outra_turma = set(db.session.scalars(
                select(AlunoCicloTurma.aluno_id).where(
                    AlunoCicloTurma.ciclo_id == ciclo_id,
                    AlunoCicloTurma.turma_id != turma_id
                )
            ).all())
            atuais_sem_vinculo_no_ciclo = set(db.session.scalars(
                select(Aluno.id).where(Aluno.turma_id == turma_id)
            ).all()) - vinculados_em_outra_turma

            target_ids = vinculados_nesta_turma | atuais_sem_vinculo_no_ciclo
            if not target_ids:
                return []

            return db.session.scalars(
                select(Aluno)
                .join(User, Aluno.user_id == User.id)
                .options(joinedload(Aluno.user))
                .where(Aluno.id.in_(target_ids))
                .order_by(Aluno.num_aluno, User.nome_de_guerra, User.nome_completo)
            ).all()

        return db.session.scalars(
            select(Aluno)
            .join(User, Aluno.user_id == User.id)
            .options(joinedload(Aluno.user))
            .where(Aluno.turma_id == turma_id)
            .order_by(Aluno.num_aluno, User.nome_de_guerra, User.nome_completo)
        ).all()

    @staticmethod
    def remanejar_alunos_ciclo(school_id: int, edicao_id: int, ciclo_origem_id: int, ciclo_destino_id: int, mapeamento_aluno_turma: dict[int, int]):
        """
        Realiza o remanejamento de alunos entre turmas na transição de um ciclo para outro:
        1. Congela a turma de cada aluno no `ciclo_origem_id` (caso informado e ainda não registrado).
        2. Registra a nova turma de cada aluno no `ciclo_destino_id`.
        3. Atualiza `Aluno.turma_id` para a turma do novo ciclo.
        4. Matricula o aluno nas disciplinas da nova turma referentes ao `ciclo_destino_id` (preservando notas dos ciclos anteriores).
        5. Registra a movimentação no Histórico Funcional (`HistoricoAluno`).
        """
        if not ciclo_destino_id:
            return False, "Selecione o ciclo de destino para realizar o remanejamento."

        ciclo_destino = db.session.get(Ciclo, int(ciclo_destino_id))
        if not ciclo_destino or ciclo_destino.school_id != school_id:
            return False, "Ciclo de destino inválido."

        ciclo_origem = db.session.get(Ciclo, int(ciclo_origem_id)) if ciclo_origem_id else None

        try:
            TurmaService.sincronizar_historico_ciclos(school_id, edicao_id)

            turmas_escola = {
                t.id: t for t in db.session.scalars(select(Turma).where(Turma.school_id == school_id)).all()
            }

            total_remanejados = 0
            total_processados = 0
            agora = datetime.utcnow()

            for aluno_id, nova_turma_id in mapeamento_aluno_turma.items():
                if not nova_turma_id or nova_turma_id not in turmas_escola:
                    continue

                aluno = db.session.get(Aluno, int(aluno_id))
                if not aluno:
                    continue

                turma_atual_id = aluno.turma_id
                turma_origem_real_id = turma_atual_id

                # 1. Garante que o vínculo no ciclo de origem fique congelado
                if ciclo_origem:
                    vinculo_origem = db.session.scalar(
                        select(AlunoCicloTurma).where(
                            AlunoCicloTurma.aluno_id == aluno.id,
                            AlunoCicloTurma.ciclo_id == ciclo_origem.id
                        )
                    )
                    if not vinculo_origem and turma_atual_id:
                        vinculo_origem = AlunoCicloTurma(
                            aluno_id=aluno.id,
                            ciclo_id=ciclo_origem.id,
                            turma_id=turma_atual_id
                        )
                        db.session.add(vinculo_origem)
                        turma_origem_real_id = turma_atual_id
                    elif vinculo_origem:
                        turma_origem_real_id = vinculo_origem.turma_id

                # 2. Atualiza ou cria o vínculo no ciclo de destino
                vinculo_destino = db.session.scalar(
                    select(AlunoCicloTurma).where(
                        AlunoCicloTurma.aluno_id == aluno.id,
                        AlunoCicloTurma.ciclo_id == ciclo_destino.id
                    )
                )
                if vinculo_destino:
                    vinculo_destino.turma_id = nova_turma_id
                else:
                    db.session.add(AlunoCicloTurma(
                        aluno_id=aluno.id,
                        ciclo_id=ciclo_destino.id,
                        turma_id=nova_turma_id
                    ))

                # 3. Atualiza a turma ativa do aluno para o novo ciclo
                nova_turma = turmas_escola[nova_turma_id]
                aluno.turma_id = nova_turma_id
                if nova_turma.edicao_id:
                    aluno.edicao_id = nova_turma.edicao_id

                # 4. Ajusta as matrículas (HistoricoDisciplina) APENAS do ciclo de destino
                # Remove matrículas SEM NOTA no ciclo de destino que eram de outra turma
                matriculas_destino = db.session.scalars(
                    select(HistoricoDisciplina)
                    .join(Disciplina, HistoricoDisciplina.disciplina_id == Disciplina.id)
                    .where(
                        HistoricoDisciplina.aluno_id == aluno.id,
                        Disciplina.ciclo_id == ciclo_destino.id
                    )
                ).all()

                disc_ja_matriculadas = set()
                for m in matriculas_destino:
                    if m.disciplina.turma_id != nova_turma_id:
                        if m.nota_p1 is None and m.nota_p2 is None and m.nota_rec is None and m.nota is None:
                            db.session.delete(m)
                    else:
                        disc_ja_matriculadas.add(m.disciplina_id)

                disciplinas_nova_turma_ciclo = db.session.scalars(
                    select(Disciplina).where(
                        Disciplina.turma_id == nova_turma_id,
                        Disciplina.ciclo_id == ciclo_destino.id
                    )
                ).all()
                for d_nova in disciplinas_nova_turma_ciclo:
                    if d_nova.id not in disc_ja_matriculadas:
                        db.session.add(HistoricoDisciplina(aluno_id=aluno.id, disciplina_id=d_nova.id))

                # 5. Registra no Histórico Funcional se houve mudança de turma
                if turma_origem_real_id and turma_origem_real_id != nova_turma_id:
                    nome_antiga = turmas_escola[turma_origem_real_id].nome if turma_origem_real_id in turmas_escola else f"Turma {turma_origem_real_id}"
                    nome_nova = nova_turma.nome
                    label_origem = f" ({ciclo_origem.nome})" if ciclo_origem else ""
                    desc_evento = f"Remanejado da turma {nome_antiga}{label_origem} para a turma {nome_nova} ({ciclo_destino.nome})."

                    ja_registrado = db.session.scalar(
                        select(HistoricoAluno).where(
                            HistoricoAluno.aluno_id == aluno.id,
                            HistoricoAluno.descricao == desc_evento
                        )
                    )
                    if not ja_registrado:
                        db.session.add(HistoricoAluno(
                            aluno_id=aluno.id,
                            tipo='Mudança de Turma / Ciclo',
                            descricao=desc_evento,
                            data_inicio=agora
                        ))
                    total_remanejados += 1

                total_processados += 1

            db.session.commit()
            return True, f" Vínculos do {ciclo_destino.nome} salvos com sucesso! ({total_processados} alunos processados, {total_remanejados} mudaram de turma com histórico preservado)."
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Erro ao remanejar alunos por ciclo: {e}")
            return False, f"Erro ao remanejar alunos: {str(e)}"

    @staticmethod
    def create_turma(data, school_id, edicao_id=None):
        nome_turma = data.get('nome')
        ano = data.get('ano')
        status = data.get('status')
        alunos_ids = data.get('alunos_ids', [])

        if not all([nome_turma, ano, school_id]):
            return False, 'Nome, Ano e ID da Escola são obrigatórios.'

        # Verifica duplicidade
        if db.session.execute(select(Turma).filter_by(nome=nome_turma, school_id=school_id)).scalar_one_or_none():
            return False, f'Uma turma com o nome "{nome_turma}" já existe nesta escola.'

        try:
            nova_turma = Turma(nome=nome_turma, ano=ano, school_id=school_id, edicao_id=edicao_id)
            if status: nova_turma.status = status
            
            db.session.add(nova_turma)
            db.session.flush()
            
            if alunos_ids:
                db.session.query(Aluno).filter(Aluno.id.in_(alunos_ids)).update({"turma_id": nova_turma.id}, synchronize_session=False)
            
            db.session.commit()
            return True, "Turma cadastrada com sucesso!"
        except Exception as e:
            db.session.rollback()
            return False, f"Erro: {str(e)}"

    @staticmethod
    def update_turma(turma_id, data):
        turma = db.session.get(Turma, turma_id)
        if not turma: return False, "Turma não encontrada."
        
        # Preserva os vínculos de ciclos anteriores antes de alterar os alunos da turma
        TurmaService.sincronizar_historico_ciclos(turma.school_id, turma.edicao_id)

        # Captura o nome antigo para verificação
        old_name = turma.nome
        new_name = data.get('nome')

        try:
            # 1. Atualiza dados básicos
            turma.nome = new_name
            turma.ano = data.get('ano')
            turma.status = data.get('status')
            
            # Atualiza data de formatura se vier no form
            if data.get('data_formatura'):
                turma.data_formatura = data.get('data_formatura')

            ids_selecionados = data.get('alunos_ids')
            
            if ids_selecionados is not None:
                if not ids_selecionados:
                    db.session.query(Aluno).filter(Aluno.turma_id == turma_id).update({"turma_id": None}, synchronize_session=False)
                else:
                    db.session.query(Aluno).filter(
                        Aluno.turma_id == turma_id,
                        Aluno.id.notin_(ids_selecionados)
                    ).update({"turma_id": None}, synchronize_session=False)

                    db.session.query(Aluno).filter(
                        Aluno.id.in_(ids_selecionados)
                    ).update({"turma_id": turma_id}, synchronize_session=False)

            db.session.commit()

            # --- PROTEÇÃO CONTRA AULAS FANTASMAS ---
            if old_name != new_name:
                disciplinas_ids = db.session.scalars(
                    select(Disciplina.id).where(Disciplina.turma_id == turma_id)
                ).all()
                
                if disciplinas_ids:
                    db.session.query(Horario).filter(
                        Horario.disciplina_id.in_(disciplinas_ids)
                    ).update({Horario.pelotao: new_name}, synchronize_session=False)

                    db.session.query(DisciplinaTurma).filter(
                        DisciplinaTurma.disciplina_id.in_(disciplinas_ids)
                    ).update({DisciplinaTurma.pelotao: new_name}, synchronize_session=False)
                    
                    db.session.commit()
            # ---------------------------------------

            return True, "Turma atualizada com sucesso."
        except Exception as e:
            db.session.rollback()
            return False, str(e)

    @staticmethod
    def delete_turma(turma_id):
        turma = db.session.get(Turma, turma_id)
        if not turma: return False, 'Turma não encontrada.'
        try:
            # Remove horários vinculados
            disciplinas_ids = db.session.scalars(select(Disciplina.id).where(Disciplina.turma_id == turma_id)).all()
            if disciplinas_ids:
                db.session.query(Horario).filter(Horario.disciplina_id.in_(disciplinas_ids)).delete(synchronize_session=False)
            
            # Desvincula alunos (não apaga o aluno, só tira da turma)
            db.session.query(Aluno).filter(Aluno.turma_id == turma_id).update({"turma_id": None}, synchronize_session=False)
            
            # Remove cargos e vinculos
            db.session.query(TurmaCargo).filter_by(turma_id=turma_id).delete()
            db.session.query(DisciplinaTurma).filter_by(pelotao=turma.nome).delete()
            
            db.session.delete(turma)
            db.session.commit()
            return True, 'Turma excluída.'
        except Exception as e:
            db.session.rollback()
            return False, str(e)

    @staticmethod
    def get_turmas_by_school(school_id, edicao_id=None):
        if not school_id: return []
        query = select(Turma).options(
            selectinload(Turma.alunos),
            selectinload(Turma.disciplinas)
        ).where(Turma.school_id == school_id)
        if edicao_id:
            query = query.where(Turma.edicao_id == edicao_id)
        return db.session.scalars(query.order_by(Turma.nome)).unique().all()

    @staticmethod
    def get_cargos_da_turma(turma_id, cargos_lista):
        cargos_db = db.session.scalars(
            select(TurmaCargo).where(TurmaCargo.turma_id == turma_id)
        ).all()
        
        cargos_atuais = {cargo.cargo_nome: cargo.aluno_id for cargo in cargos_db}

        for cargo in cargos_lista:
            cargos_atuais.setdefault(cargo, None)
            
        return cargos_atuais

    @staticmethod
    def atualizar_cargos(turma_id, form_data):
        turma = db.session.get(Turma, turma_id)
        if not turma:
            return False, 'Turma não encontrada.'
        
        try:
            cargo_nome = form_data.get('cargo_nome')
            aluno_id_str = form_data.get('aluno_id')
            aluno_id = int(aluno_id_str) if aluno_id_str else None
            
            data_evento_str = form_data.get('data_evento')
            data_evento = datetime.strptime(data_evento_str, '%Y-%m-%d') if data_evento_str else datetime.utcnow()

            if cargo_nome not in TurmaCargo.get_all_roles():
                return False, f'O cargo "{cargo_nome}" não é um cargo oficial do sistema.'

            cargo_atual = db.session.scalars(
                select(TurmaCargo).where(TurmaCargo.turma_id == turma_id, TurmaCargo.cargo_nome == cargo_nome)
            ).first()

            # Lógica de Histórico
            if cargo_atual and cargo_atual.aluno_id and (cargo_atual.aluno_id != aluno_id):
                historico_antigo = db.session.scalars(select(HistoricoAluno).where(
                    HistoricoAluno.aluno_id == cargo_atual.aluno_id,
                    HistoricoAluno.descricao.like(f"%Assumiu a função de {cargo_nome}%"),
                    HistoricoAluno.data_fim.is_(None)
                ).order_by(HistoricoAluno.data_inicio.desc())).first()
                
                if historico_antigo:
                    historico_antigo.data_fim = data_evento

            if aluno_id:
                if not cargo_atual:
                    cargo_atual = TurmaCargo(turma_id=turma_id, cargo_nome=cargo_nome)
                    db.session.add(cargo_atual)
                
                if cargo_atual.aluno_id != aluno_id:
                    novo_historico = HistoricoAluno(
                        aluno_id=aluno_id,
                        tipo='Função de Turma',
                        descricao=f'Assumiu a função de {cargo_nome} na turma {turma.nome}.',
                        data_inicio=data_evento
                    )
                    db.session.add(novo_historico)
                
                cargo_atual.aluno_id = aluno_id
            
            else:
                if cargo_atual:
                    cargo_atual.aluno_id = None 

            db.session.commit()
            return True, f'Cargo "{cargo_nome}" atualizado com sucesso!'
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Erro ao salvar os cargos: {e}")
            return False, f'Erro interno: {str(e)}'
