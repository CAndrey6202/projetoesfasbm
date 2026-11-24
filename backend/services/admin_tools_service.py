# backend/services/admin_tools_service.py

from flask import current_app
from sqlalchemy import select
from datetime import datetime, date, time

from ..models.database import db
from ..models.user import User
from ..models.user_school import UserSchool
from ..models.disciplina import Disciplina
from ..models.disciplina_turma import DisciplinaTurma
from ..models.turma import Turma
from ..models.ciclo import Ciclo
from ..models.semana import Semana
from ..models.horario import Horario
from ..models.diario_classe import DiarioClasse
from ..models.frequencia import FrequenciaAluno
from ..models.turma_cargo import TurmaCargo
from ..models.questionario import Questionario
from ..models.pergunta import Pergunta
from ..models.resposta import Resposta
from ..models.banco_questoes import QuestaoBanco, RascunhoProva, DelegacaoProva
from ..models.elogio import Elogio
from ..models.fada_avaliacao import FadaAvaliacao
from ..models.processo_disciplina import ProcessoDisciplina
#from ..models.avaliacao import AvaliacaoAtitudinal
from ..models.historico import HistoricoAluno
from ..models.historico_disciplina import HistoricoDisciplina
from ..models.notification import Notification
from ..models.password_reset_token import PasswordResetToken
from ..models.push_subscription import PushSubscription
from ..models.aluno import Aluno
from ..models.instrutor import Instrutor

class AdminToolsService:
    
    @staticmethod
    def generate_school_backup_to_file(school_id: int, file_path: str) -> None:
        """
        Gera o snapshot completo da escola gravando diretamente em disco (streaming JSON por seções e lotes),
        mantendo o consumo de memória RAM abaixo de ~15MB para evitar OOM Kill (erro 503) no container de 512MB do Render.
        """
        import gc
        import json
        from decimal import Decimal
        from enum import Enum
        from sqlalchemy import or_
        from ..models.school import School
        from ..models.edicao import Edicao
        from ..models.turma import Turma
        from ..models.ciclo import Ciclo
        from ..models.semana import Semana
        from ..models.horario import Horario
        from ..models.diario_classe import DiarioClasse
        from ..models.frequencia import FrequenciaAluno
        from ..models.historico import HistoricoAluno
        from ..models.processo_disciplina import ProcessoDisciplina
        from ..models.elogio import Elogio
        from ..models.fada_avaliacao import FadaAvaliacao
        from ..models.user_school import UserSchool
        from ..models.user import User
        from ..models.aluno import Aluno
        from ..models.instrutor import Instrutor
        from ..models.turma_cargo import TurmaCargo
        from ..models.discipline_rule import DisciplineRule
        from ..models.banco_questoes import QuestaoBanco, DelegacaoProva, RascunhoProva, ConfiguracaoEnvio
        from ..models.questionario import Questionario
        from ..models.pergunta import Pergunta
        from ..models.opcao_resposta import OpcaoResposta
        from ..models.resposta import Resposta
        from ..models.disciplina import Disciplina
        from ..models.disciplina_turma import DisciplinaTurma
        from ..models.admin_log import AdminLog
        from ..models.image_asset import ImageAsset
        from ..models.curso_video import CursoVideo

        EXCLUDE_COLS = {'password_hash', 'reset_token', 'reset_token_expiration'}

        def serialize_mapping(row_map):
            data = {}
            for k, val in row_map.items():
                if k in EXCLUDE_COLS:
                    continue
                if isinstance(val, (datetime, date, time)):
                    data[k] = val.isoformat()
                elif isinstance(val, Decimal):
                    data[k] = float(val)
                elif isinstance(val, Enum):
                    data[k] = val.value
                else:
                    data[k] = val
            return data

        def fetch_rows(model_cls, where_clause=None, limit_rows=None, order_col=None):
            stmt = select(model_cls.__table__)
            if where_clause is not None:
                stmt = stmt.where(where_clause)
            if order_col is not None:
                stmt = stmt.order_by(order_col)
            if limit_rows is not None:
                stmt = stmt.limit(limit_rows)
            res = db.session.execute(stmt).mappings()
            return [serialize_mapping(r) for r in res]

        def dump_val(val):
            return json.dumps(val, ensure_ascii=False, separators=(',', ':'))

        def write_key_list(fp, key_name, rows_iterable, is_first=False):
            if not is_first:
                fp.write(',')
            fp.write(f'"{key_name}":[')
            first_item = True
            for item in rows_iterable:
                if not first_item:
                    fp.write(',')
                fp.write(dump_val(item))
                first_item = False
            fp.write(']')

        db.session.expunge_all()

        with open(file_path, 'w', encoding='utf-8') as fp:
            fp.write('{')
            # meta
            fp.write('"meta":' + dump_val({
                "generated_at": datetime.now().isoformat(),
                "school_id": school_id
            }))

            # 1. escola e edicoes
            escola_rows = fetch_rows(School, School.id == school_id)
            fp.write(',"escola":' + dump_val(escola_rows[0] if escola_rows else {}))
            del escola_rows

            edicoes_rows = fetch_rows(Edicao, Edicao.school_id == school_id)
            write_key_list(fp, "edicoes", edicoes_rows)
            del edicoes_rows

            # 2. turmas
            turmas_rows = fetch_rows(Turma, Turma.school_id == school_id)
            turma_ids = [t["id"] for t in turmas_rows]
            turmas_cache = {t["id"]: t.get("nome") or "Desconhecida" for t in turmas_rows}
            write_key_list(fp, "turmas", turmas_rows)
            del turmas_rows

            # 3. ciclos, semanas, horarios
            ciclos_rows = fetch_rows(Ciclo, Ciclo.school_id == school_id)
            ciclo_ids = [c["id"] for c in ciclos_rows]
            write_key_list(fp, "ciclos", ciclos_rows)
            del ciclos_rows

            semana_ids = []
            if ciclo_ids:
                semanas_rows = fetch_rows(Semana, Semana.ciclo_id.in_(ciclo_ids))
                semana_ids = [s["id"] for s in semanas_rows]
                write_key_list(fp, "semanas", semanas_rows)
                del semanas_rows
            else:
                write_key_list(fp, "semanas", [])

            if semana_ids:
                horarios_rows = fetch_rows(Horario, Horario.semana_id.in_(semana_ids))
                write_key_list(fp, "horarios", horarios_rows)
                del horarios_rows
            else:
                write_key_list(fp, "horarios", [])

            # 4. users_schools, instrutores, alunos, usuarios
            us_rows = fetch_rows(UserSchool, UserSchool.school_id == school_id)
            user_ids_set = {us["user_id"] for us in us_rows if us.get("user_id")}
            write_key_list(fp, "users_schools", us_rows)
            del us_rows

            instrutores_rows = fetch_rows(Instrutor, Instrutor.school_id == school_id)
            for inst in instrutores_rows:
                if inst.get("user_id"):
                    user_ids_set.add(inst["user_id"])
            write_key_list(fp, "instrutores", instrutores_rows)
            del instrutores_rows

            conds_alunos = []
            if user_ids_set:
                conds_alunos.append(Aluno.user_id.in_(list(user_ids_set)))
            if turma_ids:
                conds_alunos.append(Aluno.turma_id.in_(turma_ids))

            alunos_rows = fetch_rows(Aluno, or_(*conds_alunos)) if conds_alunos else []
            for a in alunos_rows:
                if a.get("user_id"):
                    user_ids_set.add(a["user_id"])
            write_key_list(fp, "alunos", alunos_rows)

            users_cache = {}
            user_ids = list(user_ids_set)
            if user_ids:
                usuarios_rows = fetch_rows(User, User.id.in_(user_ids))
                for u in usuarios_rows:
                    users_cache[u["id"]] = {
                        "nome": u.get("nome_completo") or u.get("nome_de_guerra") or u.get("username") or "Sem Nome",
                        "matricula": u.get("matricula") or "Nao informada"
                    }
                write_key_list(fp, "usuarios", usuarios_rows)
                del usuarios_rows
            else:
                write_key_list(fp, "usuarios", [])

            alunos_cache = {}
            for a in alunos_rows:
                u_info = users_cache.get(a.get("user_id"), {})
                alunos_cache[a["id"]] = {
                    "nome": u_info.get("nome", "Desconhecido"),
                    "matricula": u_info.get("matricula", "N/A"),
                    "user_id": a.get("user_id")
                }
            aluno_ids = list(alunos_cache.keys())
            del alunos_rows

            # 5. disciplinas e vinculos_disciplinas
            disc_ids = []
            disciplinas_cache = {}
            if turma_ids:
                disc_rows = fetch_rows(Disciplina, Disciplina.turma_id.in_(turma_ids))
                for d in disc_rows:
                    disciplinas_cache[d["id"]] = d.get("materia") or "Desconhecida"
                    disc_ids.append(d["id"])
                write_key_list(fp, "disciplinas", disc_rows)
                del disc_rows
            else:
                write_key_list(fp, "disciplinas", [])

            if disc_ids:
                vinc_rows = fetch_rows(DisciplinaTurma, DisciplinaTurma.disciplina_id.in_(disc_ids))
                write_key_list(fp, "vinculos_disciplinas", vinc_rows)
                del vinc_rows
            else:
                write_key_list(fp, "vinculos_disciplinas", [])

            # 6. diarios_classe (streaming linha a linha)
            diario_ids = []
            fp.write(',"diarios_classe":[')
            if turma_ids:
                first_d = True
                stmt_diarios = select(DiarioClasse.__table__).where(DiarioClasse.turma_id.in_(turma_ids))
                for r in db.session.execute(stmt_diarios).mappings():
                    d_data = serialize_mapping(r)
                    d_data["injected_turma_nome"] = turmas_cache.get(d_data.get("turma_id"), "Desconhecida")
                    d_data["injected_disciplina_nome"] = disciplinas_cache.get(d_data.get("disciplina_id"), "Desconhecida")
                    diario_ids.append(d_data["id"])
                    if not first_d:
                        fp.write(',')
                    fp.write(dump_val(d_data))
                    first_d = False
            fp.write(']')

            # 7. frequencias (streaming em lotes de 400 diarios para nunca acumular na RAM)
            fp.write(',"frequencias":[')
            if diario_ids:
                first_f = True
                batch_size = 400
                for idx in range(0, len(diario_ids), batch_size):
                    batch_d_ids = diario_ids[idx:idx + batch_size]
                    stmt_freq = select(FrequenciaAluno.__table__).where(FrequenciaAluno.diario_id.in_(batch_d_ids))
                    for f in db.session.execute(stmt_freq).mappings():
                        a_info = alunos_cache.get(f["aluno_id"], {})
                        f_item = {
                            "id": f["id"],
                            "diario_id": f["diario_id"],
                            "aluno_id": f["aluno_id"],
                            "presente": f["presente"],
                            "justificativa": f["justificativa"],
                            "injected_aluno_nome": a_info.get("nome", "Desconhecido"),
                            "injected_aluno_matricula": a_info.get("matricula", "N/A"),
                        }
                        if not first_f:
                            fp.write(',')
                        fp.write(dump_val(f_item))
                        first_f = False
            fp.write(']')
            del diario_ids
            gc.collect()

            # 8. historicos e turma_cargos
            if aluno_ids:
                hist_rows = fetch_rows(HistoricoAluno, HistoricoAluno.aluno_id.in_(aluno_ids))
                write_key_list(fp, "historicos", hist_rows)
                del hist_rows
            else:
                write_key_list(fp, "historicos", [])

            if turma_ids:
                cargos_rows = fetch_rows(TurmaCargo, TurmaCargo.turma_id.in_(turma_ids))
                write_key_list(fp, "turma_cargos", cargos_rows)
                del cargos_rows
            else:
                write_key_list(fp, "turma_cargos", [])

            # 9. tabelas globais e logs (com try/except e limite seguro)
            try:
                regras_rows = fetch_rows(DisciplineRule)
            except Exception:
                db.session.rollback()
                regras_rows = []
            write_key_list(fp, "regras_npccal", regras_rows)
            del regras_rows

            # 10. banco de questoes
            try:
                bq_rows = fetch_rows(QuestaoBanco, QuestaoBanco.escola_id == school_id)
                del_rows = fetch_rows(DelegacaoProva, DelegacaoProva.escola_gestora_id == school_id)
                del_ids = [d["id"] for d in del_rows]
                rasc_rows = fetch_rows(RascunhoProva, RascunhoProva.delegacao_id.in_(del_ids)) if del_ids else []
                env_rows = fetch_rows(ConfiguracaoEnvio, ConfiguracaoEnvio.escola_id == school_id)
            except Exception:
                db.session.rollback()
                bq_rows, del_rows, rasc_rows, env_rows = [], [], [], []
            write_key_list(fp, "banco_questoes", bq_rows)
            write_key_list(fp, "delegacoes_prova", del_rows)
            write_key_list(fp, "rascunhos_prova", rasc_rows)
            write_key_list(fp, "configuracoes_envio", env_rows)
            del bq_rows, del_rows, rasc_rows, env_rows

            # 11. questionarios
            try:
                q_rows = fetch_rows(Questionario, Questionario.school_id == school_id)
                q_ids = [q["id"] for q in q_rows]
                p_rows = fetch_rows(Pergunta, Pergunta.questionario_id.in_(q_ids)) if q_ids else []
                p_ids = [p["id"] for p in p_rows]
                op_rows = fetch_rows(OpcaoResposta, OpcaoResposta.pergunta_id.in_(p_ids)) if p_ids else []
                resp_rows = fetch_rows(Resposta, Resposta.pergunta_id.in_(p_ids)) if p_ids else []
            except Exception:
                db.session.rollback()
                q_rows, p_rows, op_rows, resp_rows = [], [], [], []
            write_key_list(fp, "questionarios", q_rows)
            write_key_list(fp, "perguntas", p_rows)
            write_key_list(fp, "opcoes_resposta", op_rows)
            write_key_list(fp, "respostas", resp_rows)
            del q_rows, p_rows, op_rows, resp_rows

            # 12. logs, assets, videos
            try:
                logs_rows = fetch_rows(AdminLog, AdminLog.school_id == school_id, limit_rows=2000, order_col=AdminLog.id.desc())
            except Exception:
                db.session.rollback()
                logs_rows = []
            write_key_list(fp, "admin_logs", logs_rows)
            del logs_rows

            try:
                img_rows = fetch_rows(ImageAsset)
            except Exception:
                db.session.rollback()
                img_rows = []
            write_key_list(fp, "image_assets", img_rows)
            del img_rows

            try:
                vid_rows = fetch_rows(CursoVideo)
            except Exception:
                db.session.rollback()
                vid_rows = []
            write_key_list(fp, "cursos_video", vid_rows)
            del vid_rows

            # 13. justica
            processos_list = []
            elogios_list = []
            fadas_list = []
            if aluno_ids:
                for p_data in fetch_rows(ProcessoDisciplina, ProcessoDisciplina.aluno_id.in_(aluno_ids)):
                    a_info = alunos_cache.get(p_data.get("aluno_id"), {})
                    p_data["injected_aluno_nome"] = a_info.get("nome", "Desconhecido")
                    p_data["injected_aluno_matricula"] = a_info.get("matricula", "N/A")
                    p_data["injected_user_id"] = a_info.get("user_id")
                    rel_id = p_data.get("relator_id")
                    relator_info = users_cache.get(rel_id, {}) if rel_id else {}
                    p_data["injected_relator_nome"] = relator_info.get("nome", "N/A")
                    processos_list.append(p_data)

                for e_data in fetch_rows(Elogio, Elogio.aluno_id.in_(aluno_ids)):
                    a_info = alunos_cache.get(e_data.get("aluno_id"), {})
                    e_data["injected_aluno_nome"] = a_info.get("nome", "Desconhecido")
                    e_data["injected_aluno_matricula"] = a_info.get("matricula", "N/A")
                    e_data["injected_user_id"] = a_info.get("user_id")
                    elogios_list.append(e_data)

                fadas_list = fetch_rows(FadaAvaliacao, FadaAvaliacao.aluno_id.in_(aluno_ids))

            fp.write(',"justica":' + dump_val({
                "processos": processos_list,
                "elogios": elogios_list,
                "fadas": fadas_list
            }))
            fp.write('}')

        gc.collect()

    @staticmethod
    def generate_school_backup(school_id: int) -> dict:
        """
        Coleta TODOS os dados da escola/edição atual e os estrutura num dicionário
        que será exportado como um snapshot JSON.
        Os dados sensíveis (senhas e tokens) são removidos ativamente na serialização.
        Injeta os nomes reais para evitar problemas de undefined no front-end.
        """
        from ..models.school import School
        from ..models.edicao import Edicao
        from ..models.turma import Turma
        from ..models.ciclo import Ciclo
        from ..models.semana import Semana
        from ..models.horario import Horario
        from ..models.diario_classe import DiarioClasse
        from ..models.frequencia import FrequenciaAluno
        from ..models.historico import HistoricoAluno
        from ..models.processo_disciplina import ProcessoDisciplina
        from ..models.elogio import Elogio
        from ..models.fada_avaliacao import FadaAvaliacao
        from ..models.user_school import UserSchool
        from ..models.user import User
        from ..models.aluno import Aluno
        from ..models.instrutor import Instrutor
        from ..models.turma_cargo import TurmaCargo
        from ..models.discipline_rule import DisciplineRule
        from ..models.banco_questoes import QuestaoBanco, DelegacaoProva, RascunhoProva, ConfiguracaoEnvio
        from ..models.questionario import Questionario
        from ..models.pergunta import Pergunta
        from ..models.opcao_resposta import OpcaoResposta
        from ..models.resposta import Resposta
        from ..models.disciplina import Disciplina
        from ..models.disciplina_turma import DisciplinaTurma
        from ..models.admin_log import AdminLog
        from ..models.image_asset import ImageAsset
        from ..models.curso_video import CursoVideo
        from sqlalchemy import or_

        from decimal import Decimal
        from enum import Enum

        EXCLUDE_COLS = {'password_hash', 'reset_token', 'reset_token_expiration'}

        def serialize_mapping(row_map):
            data = {}
            for k, val in row_map.items():
                if k in EXCLUDE_COLS:
                    continue
                if isinstance(val, (datetime, date, time)):
                    data[k] = val.isoformat()
                elif isinstance(val, Decimal):
                    data[k] = float(val)
                elif isinstance(val, Enum):
                    data[k] = val.value
                else:
                    data[k] = val
            return data

        def fetch_table_rows(model_cls, where_clause=None, limit_rows=None, order_col=None):
            stmt = select(model_cls.__table__)
            if where_clause is not None:
                stmt = stmt.where(where_clause)
            if order_col is not None:
                stmt = stmt.order_by(order_col)
            if limit_rows is not None:
                stmt = stmt.limit(limit_rows)
            res = db.session.execute(stmt).mappings()
            return [serialize_mapping(r) for r in res]

        backup = {
            "meta": {
                "generated_at": datetime.now().isoformat(),
                "school_id": school_id
            },
            "escola": {},
            "edicoes": [],
            "turmas": [],
            "ciclos": [],
            "semanas": [],
            "horarios": [],
            "usuarios": [],
            "users_schools": [],
            "alunos": [],
            "instrutores": [],
            "disciplinas": [],
            "vinculos_disciplinas": [],
            "diarios_classe": [],
            "frequencias": [],
            "historicos": [],
            "turma_cargos": [],
            "regras_npccal": [],
            "banco_questoes": [],
            "delegacoes_prova": [],
            "rascunhos_prova": [],
            "configuracoes_envio": [],
            "questionarios": [],
            "perguntas": [],
            "opcoes_resposta": [],
            "respostas": [],
            "admin_logs": [],
            "image_assets": [],
            "cursos_video": [],
            "justica": {
                "processos": [],
                "elogios": [],
                "fadas": []
            }
        }

        try:
            # 1. Escola e Edicoes
            escola_rows = fetch_table_rows(School, School.id == school_id)
            if escola_rows:
                backup["escola"] = escola_rows[0]

            backup["edicoes"] = fetch_table_rows(Edicao, Edicao.school_id == school_id)

            # 2. Configuracoes Globais (Isoladas com try/except para nunca travar o backup)
            try:
                backup["regras_npccal"] = fetch_table_rows(DisciplineRule)
            except Exception as e_reg:
                current_app.logger.warning(f"Aviso ao extrair regras_npccal no backup: {e_reg}")
                db.session.rollback()

            try:
                backup["admin_logs"] = fetch_table_rows(
                    AdminLog,
                    AdminLog.school_id == school_id,
                    limit_rows=5000,
                    order_col=AdminLog.id.desc()
                )
            except Exception as e_log:
                current_app.logger.warning(f"Aviso ao extrair admin_logs no backup: {e_log}")
                db.session.rollback()

            try:
                backup["image_assets"] = fetch_table_rows(ImageAsset)
            except Exception as e_img:
                current_app.logger.warning(f"Aviso ao extrair image_assets no backup: {e_img}")
                db.session.rollback()

            try:
                backup["cursos_video"] = fetch_table_rows(CursoVideo)
            except Exception as e_vid:
                current_app.logger.warning(f"Aviso ao extrair cursos_video no backup: {e_vid}")
                db.session.rollback()

            # 3. Usuarios e Vinculos (UserSchool)
            backup["users_schools"] = fetch_table_rows(UserSchool, UserSchool.school_id == school_id)
            user_ids_set = {us["user_id"] for us in backup["users_schools"] if us.get("user_id")}

            # 4. Instrutores (Tabela Real)
            backup["instrutores"] = fetch_table_rows(Instrutor, Instrutor.school_id == school_id)
            for inst in backup["instrutores"]:
                if inst.get("user_id"):
                    user_ids_set.add(inst["user_id"])

            # 5. Turmas
            backup["turmas"] = fetch_table_rows(Turma, Turma.school_id == school_id)
            turma_ids = [t["id"] for t in backup["turmas"]]
            turmas_cache = {t["id"]: t.get("nome") or "Desconhecida" for t in backup["turmas"]}

            # 6. Alunos (Inclui vinculados via UserSchool ou via Turma da escola)
            conds_alunos = []
            if user_ids_set:
                conds_alunos.append(Aluno.user_id.in_(list(user_ids_set)))
            if turma_ids:
                conds_alunos.append(Aluno.turma_id.in_(turma_ids))

            if conds_alunos:
                backup["alunos"] = fetch_table_rows(Aluno, or_(*conds_alunos))
                for a in backup["alunos"]:
                    if a.get("user_id"):
                        user_ids_set.add(a["user_id"])

            # Carrega todos os usuarios referenciados (UserSchool + Alunos + Instrutores)
            users_cache = {}
            user_ids = list(user_ids_set)
            if user_ids:
                backup["usuarios"] = fetch_table_rows(User, User.id.in_(user_ids))
                for u in backup["usuarios"]:
                    uid = u["id"]
                    users_cache[uid] = {
                        "nome": u.get("nome_completo") or u.get("nome_de_guerra") or u.get("username") or "Sem Nome",
                        "matricula": u.get("matricula") or "Nao informada"
                    }

            alunos_cache = {}
            for a in backup["alunos"]:
                u_info = users_cache.get(a.get("user_id"), {})
                alunos_cache[a["id"]] = {
                    "nome": u_info.get("nome", "Desconhecido"),
                    "matricula": u_info.get("matricula", "N/A"),
                    "user_id": a.get("user_id")
                }
            aluno_ids = list(alunos_cache.keys())

            # 7. Cargos de Turma
            if turma_ids:
                backup["turma_cargos"] = fetch_table_rows(TurmaCargo, TurmaCargo.turma_id.in_(turma_ids))

            # 8. Disciplinas Globais
            disc_ids = []
            disciplinas_cache = {}
            if turma_ids:
                backup["disciplinas"] = fetch_table_rows(Disciplina, Disciplina.turma_id.in_(turma_ids))
                for d in backup["disciplinas"]:
                    disciplinas_cache[d["id"]] = d.get("materia") or "Desconhecida"
                    disc_ids.append(d["id"])

                if disc_ids:
                    backup["vinculos_disciplinas"] = fetch_table_rows(
                        DisciplinaTurma,
                        DisciplinaTurma.disciplina_id.in_(disc_ids)
                    )

            # 9. Ciclos, Semanas e Horarios
            backup["ciclos"] = fetch_table_rows(Ciclo, Ciclo.school_id == school_id)
            ciclo_ids = [c["id"] for c in backup["ciclos"]]

            if ciclo_ids:
                backup["semanas"] = fetch_table_rows(Semana, Semana.ciclo_id.in_(ciclo_ids))
                semana_ids = [s["id"] for s in backup["semanas"]]

                if semana_ids:
                    backup["horarios"] = fetch_table_rows(Horario, Horario.semana_id.in_(semana_ids))

            # 10. Diarios e Frequencias (Otimizado via JOIN SQL Core sem instanciar centenas de milhares de objetos ORM)
            if turma_ids:
                diarios_rows = fetch_table_rows(DiarioClasse, DiarioClasse.turma_id.in_(turma_ids))
                for d_data in diarios_rows:
                    d_data["injected_turma_nome"] = turmas_cache.get(d_data.get("turma_id"), "Desconhecida")
                    d_data["injected_disciplina_nome"] = disciplinas_cache.get(d_data.get("disciplina_id"), "Desconhecida")
                    backup["diarios_classe"].append(d_data)

                if diarios_rows:
                    stmt_freq = (
                        select(FrequenciaAluno.__table__)
                        .select_from(
                            FrequenciaAluno.__table__.join(
                                DiarioClasse.__table__,
                                FrequenciaAluno.diario_id == DiarioClasse.id
                            )
                        )
                        .where(DiarioClasse.turma_id.in_(turma_ids))
                    )
                    freq_result = db.session.execute(stmt_freq).mappings()
                    frequencias_list = backup["frequencias"]
                    for f in freq_result:
                        a_info = alunos_cache.get(f["aluno_id"], {})
                        frequencias_list.append({
                            "id": f["id"],
                            "diario_id": f["diario_id"],
                            "aluno_id": f["aluno_id"],
                            "presente": f["presente"],
                            "justificativa": f["justificativa"],
                            "injected_aluno_nome": a_info.get("nome", "Desconhecido"),
                            "injected_aluno_matricula": a_info.get("matricula", "N/A"),
                        })

            # 11. Historicos e Justica (CORRECAO CRITICA DO ALUNO_ID)
            if aluno_ids:
                backup["historicos"] = fetch_table_rows(HistoricoAluno, HistoricoAluno.aluno_id.in_(aluno_ids))

                processos_rows = fetch_table_rows(ProcessoDisciplina, ProcessoDisciplina.aluno_id.in_(aluno_ids))
                for p_data in processos_rows:
                    a_info = alunos_cache.get(p_data.get("aluno_id"), {})
                    p_data["injected_aluno_nome"] = a_info.get("nome", "Desconhecido")
                    p_data["injected_aluno_matricula"] = a_info.get("matricula", "N/A")
                    p_data["injected_user_id"] = a_info.get("user_id")
                    rel_id = p_data.get("relator_id")
                    relator_info = users_cache.get(rel_id, {}) if rel_id else {}
                    p_data["injected_relator_nome"] = relator_info.get("nome", "N/A")
                    backup["justica"]["processos"].append(p_data)

                elogios_rows = fetch_table_rows(Elogio, Elogio.aluno_id.in_(aluno_ids))
                for e_data in elogios_rows:
                    a_info = alunos_cache.get(e_data.get("aluno_id"), {})
                    e_data["injected_aluno_nome"] = a_info.get("nome", "Desconhecido")
                    e_data["injected_aluno_matricula"] = a_info.get("matricula", "N/A")
                    e_data["injected_user_id"] = a_info.get("user_id")
                    backup["justica"]["elogios"].append(e_data)

                backup["justica"]["fadas"] = fetch_table_rows(FadaAvaliacao, FadaAvaliacao.aluno_id.in_(aluno_ids))

            # 12. Banco de Questoes e Avaliacoes
            try:
                backup["banco_questoes"] = fetch_table_rows(QuestaoBanco, QuestaoBanco.escola_id == school_id)
                backup["delegacoes_prova"] = fetch_table_rows(DelegacaoProva, DelegacaoProva.escola_gestora_id == school_id)

                del_ids = [d["id"] for d in backup["delegacoes_prova"]]
                if del_ids:
                    backup["rascunhos_prova"] = fetch_table_rows(RascunhoProva, RascunhoProva.delegacao_id.in_(del_ids))
                else:
                    backup["rascunhos_prova"] = []

                backup["configuracoes_envio"] = fetch_table_rows(ConfiguracaoEnvio, ConfiguracaoEnvio.escola_id == school_id)
            except Exception as e_bq:
                current_app.logger.warning(f"Aviso ao extrair banco de questoes no backup: {e_bq}")
                db.session.rollback()

            # 13. Questionarios de Avaliacao
            try:
                backup["questionarios"] = fetch_table_rows(Questionario, Questionario.school_id == school_id)
                q_ids = [q["id"] for q in backup["questionarios"]]

                if q_ids:
                    backup["perguntas"] = fetch_table_rows(Pergunta, Pergunta.questionario_id.in_(q_ids))
                    p_ids = [p["id"] for p in backup["perguntas"]]

                    if p_ids:
                        backup["opcoes_resposta"] = fetch_table_rows(OpcaoResposta, OpcaoResposta.pergunta_id.in_(p_ids))
                        backup["respostas"] = fetch_table_rows(Resposta, Resposta.pergunta_id.in_(p_ids))
            except Exception as e_quest:
                current_app.logger.warning(f"Aviso ao extrair questionarios no backup: {e_quest}")
                db.session.rollback()

            return backup

        except Exception as e:
            current_app.logger.error(f"Falha ao gerar backup completo da escola {school_id}: {e}")
            raise e

    @staticmethod
    def custom_clear_school_data(school_id: int, options: list, instructors_to_delete_ids: list = None):
        """
        Processa as opções selecionadas via checkbox e as limpa em lote, lidando 
        com as dependências do banco ativamente para evitar erros de Integridade Referencial.
        Recebe opcionalmente uma lista refinada de instrutores para desvincular da escola atual.
        """
        try:
            if 'turmas' in options:
                options.extend(['disciplinas', 'diarios', 'questionarios', 'vinculos'])
            if 'disciplinas' in options:
                options.extend(['diarios', 'vinculos'])
            if 'ciclos' in options:
                options.extend(['semanas', 'horarios'])

            options = list(set(options)) # Remove duplicatas

            # 1. Coletar IDs Básicos de Usuário
            all_users = db.session.scalars(select(User).join(UserSchool).where(UserSchool.school_id == school_id)).all()
            student_ids = [u.id for u in all_users if u.role == 'aluno']
            
            # Se a lista de instrutores foi enviada pela tela de confirmação, usamos ela.
            if instructors_to_delete_ids is not None:
                instructor_ids = [u.id for u in all_users if u.role == 'instrutor' and u.id in instructors_to_delete_ids]
            else:
                instructor_ids = []

            alunos_db = db.session.scalars(select(Aluno).where(Aluno.user_id.in_(student_ids))).all() if student_ids else []
            aluno_ids = [a.id for a in alunos_db] if alunos_db else []

            turmas = db.session.scalars(select(Turma).where(Turma.school_id == school_id)).all()
            turma_ids = [t.id for t in turmas] if turmas else []

            ciclos = db.session.scalars(select(Ciclo).where(Ciclo.school_id == school_id)).all()
            ciclo_ids = [c.id for c in ciclos] if ciclos else []

            # LIMPEZA DAS DEPENDÊNCIAS MENORES (Cascata Forçada) ==================

            # Justiça
            if 'justica' in options and aluno_ids:
                db.session.query(ProcessoDisciplina).filter(ProcessoDisciplina.aluno_id.in_(aluno_ids)).delete(synchronize_session=False)
                db.session.query(Elogio).filter(Elogio.aluno_id.in_(aluno_ids)).delete(synchronize_session=False)
                db.session.query(FadaAvaliacao).filter(FadaAvaliacao.aluno_id.in_(aluno_ids)).delete(synchronize_session=False)
                #db.session.query(AvaliacaoAtitudinal).filter(AvaliacaoAtitudinal.aluno_id.in_(aluno_ids)).delete(synchronize_session=False)

            # Questionários (e respostas)
            if 'questionarios' in options:
                questoes = db.session.scalars(select(Questionario).where(Questionario.school_id == school_id)).all()
                for q in questoes:
                    db.session.query(Resposta).filter(Resposta.pergunta_id.in_(
                        select(Pergunta.id).where(Pergunta.questionario_id == q.id)
                    )).delete(synchronize_session=False)
                    db.session.delete(q)

            # Diários de Classe (e frequências)
            if 'diarios' in options and turma_ids:
                diarios = db.session.scalars(select(DiarioClasse).where(DiarioClasse.turma_id.in_(turma_ids))).all()
                diario_ids = [d.id for d in diarios] if diarios else []
                if diario_ids:
                    db.session.query(FrequenciaAluno).filter(FrequenciaAluno.diario_id.in_(diario_ids)).delete(synchronize_session=False)
                    db.session.query(DiarioClasse).filter(DiarioClasse.id.in_(diario_ids)).delete(synchronize_session=False)

            # Vínculos Disciplina-Instrutor
            if 'vinculos' in options and turma_ids:
                disciplinas = db.session.scalars(select(Disciplina).where(Disciplina.turma_id.in_(turma_ids))).all()
                disc_ids = [d.id for d in disciplinas] if disciplinas else []
                if disc_ids:
                    db.session.query(DisciplinaTurma).filter(DisciplinaTurma.disciplina_id.in_(disc_ids)).delete(synchronize_session=False)

            # Disciplinas (e horários, históricos)
            if 'disciplinas' in options and turma_ids:
                disciplinas = db.session.scalars(select(Disciplina).where(Disciplina.turma_id.in_(turma_ids))).all()
                disc_ids = [d.id for d in disciplinas] if disciplinas else []
                if disc_ids:
                    db.session.query(HistoricoDisciplina).filter(HistoricoDisciplina.disciplina_id.in_(disc_ids)).delete(synchronize_session=False)
                    db.session.query(Horario).filter(Horario.disciplina_id.in_(disc_ids)).delete(synchronize_session=False)
                    db.session.query(Disciplina).filter(Disciplina.id.in_(disc_ids)).delete(synchronize_session=False)

            # Ciclos (e semanas, horários)
            if 'ciclos' in options and ciclo_ids:
                semanas = db.session.scalars(select(Semana).where(Semana.ciclo_id.in_(ciclo_ids))).all()
                semana_ids = [s.id for s in semanas] if semanas else []
                if semana_ids:
                    db.session.query(Horario).filter(Horario.semana_id.in_(semana_ids)).delete(synchronize_session=False)
                    db.session.query(Semana).filter(Semana.id.in_(semana_ids)).delete(synchronize_session=False)
                db.session.query(Ciclo).filter(Ciclo.id.in_(ciclo_ids)).delete(synchronize_session=False)

            # Turmas
            if 'turmas' in options and turma_ids:
                db.session.query(TurmaCargo).filter(TurmaCargo.turma_id.in_(turma_ids)).delete(synchronize_session=False)
                db.session.query(Turma).filter(Turma.id.in_(turma_ids)).delete(synchronize_session=False)

            # LIMPEZA DE USUÁRIOS ==================================================
            
            # Alunos
            if 'alunos' in options and student_ids:
                if aluno_ids:
                    db.session.query(FrequenciaAluno).filter(FrequenciaAluno.aluno_id.in_(aluno_ids)).delete(synchronize_session=False)
                    db.session.query(HistoricoDisciplina).filter(HistoricoDisciplina.aluno_id.in_(aluno_ids)).delete(synchronize_session=False)
                    db.session.query(HistoricoAluno).filter(HistoricoAluno.aluno_id.in_(aluno_ids)).delete(synchronize_session=False)
                    db.session.query(ProcessoDisciplina).filter(ProcessoDisciplina.aluno_id.in_(aluno_ids)).delete(synchronize_session=False)
                    db.session.query(Elogio).filter(Elogio.aluno_id.in_(aluno_ids)).delete(synchronize_session=False)
                    db.session.query(FadaAvaliacao).filter(FadaAvaliacao.aluno_id.in_(aluno_ids)).delete(synchronize_session=False)
                    #db.session.query(AvaliacaoAtitudinal).filter(AvaliacaoAtitudinal.aluno_id.in_(aluno_ids)).delete(synchronize_session=False)

                # --- LIMPEZA DE CARGOS E VÍNCULOS PERDIDOS DOS ALUNOS ---
                # Como o aluno pode ser Chefe de Turma, limpamos o TurmaCargo com segurança dinâmica
                if hasattr(TurmaCargo, 'aluno_id') and aluno_ids:
                    db.session.query(TurmaCargo).filter(TurmaCargo.aluno_id.in_(aluno_ids)).delete(synchronize_session=False)
                elif hasattr(TurmaCargo, 'user_id'):
                    db.session.query(TurmaCargo).filter(TurmaCargo.user_id.in_(student_ids)).delete(synchronize_session=False)

                if hasattr(DisciplinaTurma, 'aluno_id') and aluno_ids:
                    db.session.query(DisciplinaTurma).filter(DisciplinaTurma.aluno_id.in_(aluno_ids)).delete(synchronize_session=False)
                elif hasattr(DisciplinaTurma, 'user_id'):
                    db.session.query(DisciplinaTurma).filter(DisciplinaTurma.user_id.in_(student_ids)).delete(synchronize_session=False)
                # --------------------------------------------------------

                db.session.query(Resposta).filter(Resposta.user_id.in_(student_ids)).delete(synchronize_session=False)
                
                # --- CAÇA-FANTASMAS DE INSTRUTORES RESIDUAIS ---
                # Verifica se há perfis na tabela 'instrutores' ligados a estes alunos (perfis fantasmas)
                instrutores_fantasma = db.session.scalars(select(Instrutor).where(Instrutor.user_id.in_(student_ids))).all()
                if instrutores_fantasma:
                    inst_ids = [i.id for i in instrutores_fantasma]
                    # Limpar as dependências desse instrutor fantasma usando hasattr para evitar AttributeError
                    delegacoes_fantasma = db.session.scalars(select(DelegacaoProva).where(DelegacaoProva.instrutor_id.in_(inst_ids))).all()
                    if delegacoes_fantasma:
                        del_ids = [d.id for d in delegacoes_fantasma]
                        db.session.query(RascunhoProva).filter(RascunhoProva.delegacao_id.in_(del_ids)).delete(synchronize_session=False)
                        db.session.query(DelegacaoProva).filter(DelegacaoProva.instrutor_id.in_(inst_ids)).delete(synchronize_session=False)
                    
                    if hasattr(QuestaoBanco, 'instrutor_id'):
                        db.session.query(QuestaoBanco).filter(QuestaoBanco.instrutor_id.in_(inst_ids)).delete(synchronize_session=False)
                        
                    if hasattr(DisciplinaTurma, 'instrutor_id'):
                        db.session.query(DisciplinaTurma).filter(DisciplinaTurma.instrutor_id.in_(inst_ids)).delete(synchronize_session=False)
                        
                    # Deleta o perfil instrutor fantasma
                    db.session.query(Instrutor).filter(Instrutor.user_id.in_(student_ids)).delete(synchronize_session=False)
                # ------------------------------------------------
                
                # Exclusão total e definitiva das configurações do aluno (referenciam User.id)
                db.session.query(Notification).filter(Notification.user_id.in_(student_ids)).delete(synchronize_session=False)
                db.session.query(PasswordResetToken).filter(PasswordResetToken.user_id.in_(student_ids)).delete(synchronize_session=False)
                db.session.query(PushSubscription).filter(PushSubscription.user_id.in_(student_ids)).delete(synchronize_session=False)
                db.session.query(UserSchool).filter(UserSchool.user_id.in_(student_ids)).delete(synchronize_session=False)
                
                # Deleta a tabela filha `alunos` antes da tabela pai `users`
                db.session.query(Aluno).filter(Aluno.user_id.in_(student_ids)).delete(synchronize_session=False)
                db.session.query(User).filter(User.id.in_(student_ids)).delete(synchronize_session=False)

            # Instrutores (COMPORTAMENTO SEGURO APLICADO E INTERATIVO)
            if 'instrutores' in options and instructor_ids:
                # 1. Obter IDs da tabela instrutores reais
                instrutores_db = db.session.scalars(select(Instrutor).where(Instrutor.user_id.in_(instructor_ids))).all()
                inst_ids_reais = [i.id for i in instrutores_db] if instrutores_db else []

                # 2. Deleta as associações que esse instrutor tem com a Escola atual (Rascunhos antigos, Delegações...)
                if inst_ids_reais:
                    delegacoes = db.session.scalars(select(DelegacaoProva).where(DelegacaoProva.instrutor_id.in_(inst_ids_reais))).all()
                    delegacao_ids = [d.id for d in delegacoes] if delegacoes else []
                    if delegacao_ids:
                        db.session.query(RascunhoProva).filter(RascunhoProva.delegacao_id.in_(delegacao_ids)).delete(synchronize_session=False)
                        
                    db.session.query(DelegacaoProva).filter(DelegacaoProva.instrutor_id.in_(inst_ids_reais)).delete(synchronize_session=False)

                # 3. REGRA DE OURO PARA PROTEGER MÚLTIPLAS ESCOLAS:
                # O instrutor NUNCA é apagado da tabela `users` nem perde suas configurações globais (Banco de Questões).
                # Apenas removemos o vínculo dele com a SUA ESCOLA.
                db.session.query(UserSchool).filter(UserSchool.user_id.in_(instructor_ids), UserSchool.school_id == school_id).delete(synchronize_session=False)

            db.session.commit()
            return True, "Os registros selecionados foram analisados e excluídos com sucesso do banco de dados."

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Erro crítico no reset customizado da escola: {e}")
            return False, f"Ocorreu um erro ao processar a limpeza: {str(e)}"