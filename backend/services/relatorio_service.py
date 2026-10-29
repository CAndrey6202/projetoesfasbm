from __future__ import annotations
import os
import json
from io import BytesIO
from typing import Any, Dict, List, Tuple
from datetime import date, timedelta, datetime
from sqlalchemy import select, or_, and_, outerjoin
from sqlalchemy.orm import aliased

# Importações seguras
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
GA_CREDENTIALS_JSON = os.environ.get("GA_CREDENTIALS_JSON")

def _get_google_credentials() -> Credentials:
    if not GA_CREDENTIALS_JSON:
        raise RuntimeError("A variável de ambiente GA_CREDENTIALS_JSON não foi configurada.")
    try:
        info = json.loads(GA_CREDENTIALS_JSON)
        return Credentials.from_service_account_info(info, scopes=SCOPES)
    except Exception as e:
        raise RuntimeError(f"Erro ao carregar credenciais do Google: {e}")

def _upload_xlsx_and_convert_to_sheet(filename: str, xlsx_bytes: bytes) -> str | None:
    try:
        creds = _get_google_credentials()
        service = build('drive', 'v3', credentials=creds)
        file_metadata = {'name': filename, 'mimeType': 'application/vnd.google-apps.spreadsheet'}
        media = MediaIoBaseUpload(BytesIO(xlsx_bytes), mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', resumable=True)
        file = service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
        permission = {'type': 'anyone', 'role': 'reader'}
        service.permissions().create(fileId=file.get('id'), body=permission).execute()
        return file.get('webViewLink')
    except HttpError as error:
        print(f"Ocorreu um erro na API do Google Drive: {error}")
        return None
    except Exception as e:
        print(f"Ocorreu um erro inesperado durante o upload para o Google Drive: {e}")
        return None

class RelatorioService:

    @staticmethod
    def _get_dia_offset(dia_semana_str: str) -> int:
        if not dia_semana_str:
            return 0
        s = dia_semana_str.lower().strip()
        if 'segunda' in s: return 0
        if 'terca' in s or 'terça' in s: return 1
        if 'quarta' in s: return 2
        if 'quinta' in s: return 3
        if 'sexta' in s: return 4
        if 'sabado' in s or 'sábado' in s: return 5
        if 'domingo' in s: return 6
        return 0

    @staticmethod
    def get_horas_aula_por_instrutor(
        data_inicio: date,
        data_fim: date,
        mode_rr: str | None, 
        instrutor_ids_filter: List[int] | None,
        ciclo_id: int | None = None,
        edicao_id: int | None = None,
        ignore_active_edicao: bool = False
    ) -> List[Dict[str, Any]]:
        
        from ..models import db, Horario, User, Instrutor, Disciplina, Semana, Ciclo, DiarioClasse, Turma, DisciplinaTurma
        from ..services.user_service import UserService
        from sqlalchemy.orm import joinedload

        school_id = UserService.get_current_school_id()
        if not school_id:
            return []

        from flask import session
        if ignore_active_edicao:
            active_edicao = edicao_id
        else:
            active_edicao = edicao_id if edicao_id is not None else session.get('active_edicao_id')

        # Se houve filtro por instrutores, mapeia tanto os IDs de Instrutor quanto os user_ids correspondentes
        # para garantir que múltiplos perfis do mesmo usuário ou vínculos entre edições sejam encontrados.
        instrutor_ids_set = set(instrutor_ids_filter) if instrutor_ids_filter else set()
        user_ids_filter_set = set()
        if instrutor_ids_set:
            matched_users = db.session.scalars(
                select(Instrutor.user_id).where(Instrutor.id.in_(instrutor_ids_set))
            ).all()
            user_ids_filter_set = {uid for uid in matched_users if uid is not None}

        # 1. PRÉ-CARREGAMENTO (BULK FETCH) para evitar N+1
        
        # 1.a Diários de Classe validados no período e anteriores (assinado)
        diarios_query = (
            select(DiarioClasse)
            .join(Turma, DiarioClasse.turma_id == Turma.id)
            .options(joinedload(DiarioClasse.instrutor_assinante))
            .filter(
                DiarioClasse.data_aula <= data_fim,
                DiarioClasse.status == 'assinado',
                Turma.school_id == school_id
            )
        )
        if active_edicao:
            diarios_query = diarios_query.filter(Turma.edicao_id == active_edicao)
            
        if ciclo_id:
            diarios_query = diarios_query.join(Disciplina, DiarioClasse.disciplina_id == Disciplina.id).filter(Disciplina.ciclo_id == ciclo_id)
            
        diarios_validos = db.session.scalars(diarios_query).all()
        diario_assinante_map = {}
        for d in diarios_validos:
            diario_assinante_map[(d.data_aula, d.periodo, d.disciplina_id)] = d.instrutor_assinante

        # 1.b Carga Horária Anterior (todas as disciplinas da escola antes da data_inicio)
        Instrutor1_ant = aliased(Instrutor)
        Instrutor2_ant = aliased(Instrutor)
        statuses_validos = ['confirmado', 'concluido', 'pendente'] if instrutor_ids_set else ['confirmado', 'concluido']
        query_ant = (
            select(
                Horario.disciplina_id, Horario.id, Horario.duracao, Semana.data_inicio, Horario.dia_semana, Horario.periodo,
                Instrutor1_ant.user_id, Instrutor2_ant.user_id, Horario.pelotao
            )
            .join(Semana, Horario.semana_id == Semana.id)
            .join(Ciclo, Semana.ciclo_id == Ciclo.id)
            .outerjoin(Instrutor1_ant, Horario.instrutor_id == Instrutor1_ant.id)
            .outerjoin(Instrutor2_ant, Horario.instrutor_id_2 == Instrutor2_ant.id)
            .filter(
                Horario.status.in_(statuses_validos),
                Ciclo.school_id == school_id
            )
        )
        if active_edicao:
            query_ant = query_ant.filter(Ciclo.edicao_id == active_edicao)
            
        if ciclo_id:
            query_ant = query_ant.filter(Ciclo.id == ciclo_id)
            
        rows_ant = db.session.execute(query_ant).all()
        
        # Mapear ch_anterior por (user_id, disciplina_id): {(user_id, disciplina_id): ch_total_anterior}
        ch_anterior_map = {}
        pelotoes_ant_map = {}
        slots_ant = set()
        for disc_id, h_id, duracao_ant_val, sem_data_inicio, dia_semana, periodo, user1_ant_id, user2_ant_id, pelotao_ant in rows_ant:
            offset_dias = RelatorioService._get_dia_offset(dia_semana)
            data_aula_ant = sem_data_inicio + timedelta(days=offset_dias)
            if data_aula_ant < data_inicio:
                chave = (data_aula_ant, periodo, h_id)
                if chave not in slots_ant:
                    slots_ant.add(chave)
                    dur = duracao_ant_val or 1
                    pel_clean = (pelotao_ant or "").strip() or "PADRAO"
                    if user1_ant_id:
                        ch_anterior_map[(user1_ant_id, disc_id)] = ch_anterior_map.get((user1_ant_id, disc_id), 0) + dur
                        pelotoes_ant_map.setdefault((user1_ant_id, disc_id), set()).add(pel_clean)
                    if user2_ant_id and user2_ant_id != user1_ant_id:
                        ch_anterior_map[(user2_ant_id, disc_id)] = ch_anterior_map.get((user2_ant_id, disc_id), 0) + dur
                        pelotoes_ant_map.setdefault((user2_ant_id, disc_id), set()).add(pel_clean)
        
        # 1.c Perfis de Instrutor da escola atual
        instrutores_escola = db.session.scalars(select(Instrutor).where(Instrutor.school_id == school_id)).all()
        instrutor_perfil_map = {inst.user_id: inst for inst in instrutores_escola}
        
        # 2. Busca base de horários confirmados
        Instrutor1 = aliased(Instrutor)
        User1 = aliased(User)
        Instrutor2 = aliased(Instrutor)
        User2 = aliased(User)

        query = (
            select(
                Horario,
                Disciplina,
                Instrutor1, User1,
                Instrutor2, User2,
                Semana
            )
            .join(Semana, Horario.semana_id == Semana.id)
            .join(Ciclo, Semana.ciclo_id == Ciclo.id)
            .join(Disciplina, Horario.disciplina_id == Disciplina.id)
            .outerjoin(Instrutor1, Horario.instrutor_id == Instrutor1.id)
            .outerjoin(User1, Instrutor1.user_id == User1.id)
            .outerjoin(Instrutor2, Horario.instrutor_id_2 == Instrutor2.id)
            .outerjoin(User2, Instrutor2.user_id == User2.id)
            .filter(
                Semana.data_inicio <= data_fim,
                Semana.data_fim >= data_inicio,
                Ciclo.school_id == school_id,
                Horario.status.in_(statuses_validos)
            )
        )
        if active_edicao:
            query = query.filter(Ciclo.edicao_id == active_edicao)
            
        if ciclo_id:
            query = query.filter(Ciclo.id == ciclo_id)

        rows = db.session.execute(query).all()

        dados_agrupados = {}
        slots_pagos = set()

        def _get_chave_agrupamento(user_obj):
            mat_clean = (getattr(user_obj, 'matricula', None) or '').strip()
            return f"{mat_clean}_{user_obj.id}"

        def _ensure_instrutor_entry(user_obj, instrutor_obj):
            chave_agrupamento = _get_chave_agrupamento(user_obj)
            if chave_agrupamento not in dados_agrupados:
                nome_resolved = (
                    (getattr(user_obj, 'nome_completo', None) or '').strip()
                    or (getattr(user_obj, 'nome_de_guerra', None) or '').strip()
                    or (getattr(user_obj, 'username', None) or '').strip()
                    or "SEM NOME"
                )
                dados_agrupados[chave_agrupamento] = {
                    "info": {
                        "instrutor_id": instrutor_obj.id,
                        "user_id": user_obj.id,
                        "user": {
                            "posto_graduacao": (getattr(user_obj, 'posto_graduacao', None) or '').strip(),
                            "matricula": (getattr(user_obj, 'matricula', None) or '').strip(),
                            "nome_completo": nome_resolved,
                            "nome_de_guerra": (getattr(user_obj, 'nome_de_guerra', None) or '').strip(),
                            "identidade": (getattr(user_obj, 'identidade', None) or '').strip(),
                            "cpf": (getattr(user_obj, 'cpf', None) or '').strip(),
                            "email": (getattr(user_obj, 'email', None) or '').strip(),
                            "telefone": (getattr(instrutor_obj, 'telefone', None) or '').strip(),
                        }
                    },
                    "disciplinas_map": {}
                }
            return chave_agrupamento

        def _ensure_disciplina_entry(chave_agrupamento, user_id, disciplina_obj, pelotao_str):
            nome_disc = (disciplina_obj.materia or "SEM DISCIPLINA").strip()
            disc_map = dados_agrupados[chave_agrupamento]["disciplinas_map"]
            if nome_disc not in disc_map:
                disc_map[nome_disc] = {
                    "nome_disciplina": nome_disc,
                    "ch_total_disciplina": 0,
                    "ch_anterior": 0.0,
                    "ch_mes": 0.0,
                    "_pelotoes_contabilizados": set(),
                    "_disciplinas_ids_contabilizados": set(),
                }

            item_disciplina = disc_map[nome_disc]
            pelotao_clean = (pelotao_str or "").strip() or "PADRAO"

            if disciplina_obj.id not in item_disciplina["_disciplinas_ids_contabilizados"]:
                item_disciplina["_disciplinas_ids_contabilizados"].add(disciplina_obj.id)
                item_disciplina["ch_anterior"] += float(ch_anterior_map.get((user_id, disciplina_obj.id), 0))

            chave_pelotao = (disciplina_obj.id, pelotao_clean)
            if chave_pelotao not in item_disciplina["_pelotoes_contabilizados"]:
                item_disciplina["ch_total_disciplina"] += (disciplina_obj.carga_horaria_prevista or 0)
                item_disciplina["_pelotoes_contabilizados"].add(chave_pelotao)

            return item_disciplina

        def processar_instrutor(user_obj, instrutor_obj, disciplina_obj, data_aula, periodo_aula, duracao, pelotao_str):
            if not user_obj or not instrutor_obj: return
            if not (data_inicio <= data_aula <= data_fim): return
            if mode_rr == 'only_rr' and not instrutor_obj.is_rr: return 
            if mode_rr == 'exclude_rr' and instrutor_obj.is_rr: return 
            if instrutor_ids_set and (instrutor_obj.id not in instrutor_ids_set and user_obj.id not in user_ids_filter_set):
                return

            chave_slot = (user_obj.id, data_aula, periodo_aula)
            if chave_slot in slots_pagos: return
            slots_pagos.add(chave_slot)

            chave_agrupamento = _ensure_instrutor_entry(user_obj, instrutor_obj)
            item_disciplina = _ensure_disciplina_entry(chave_agrupamento, user_obj.id, disciplina_obj, pelotao_str)
            item_disciplina["ch_mes"] += duracao

        for row in rows:
            horario, disciplina, inst1, usr1, inst2, usr2, semana = row
            duracao = horario.duracao or 1
            periodo = horario.periodo
            pelotao = getattr(horario, 'pelotao', '')
            offset_dias = RelatorioService._get_dia_offset(horario.dia_semana)
            data_aula = semana.data_inicio + timedelta(days=offset_dias)

            # Usa estritamente o planejamento original (Quadro Horário), ignorando diários de classe
            if inst1 and usr1:
                processar_instrutor(usr1, inst1, disciplina, data_aula, periodo, duracao, pelotao)
            if inst2 and usr2:
                if not (usr1 and usr1.id == usr2.id):
                    processar_instrutor(usr2, inst2, disciplina, data_aula, periodo, duracao, pelotao)

        # 3. Se for busca filtrada por instrutor (Por Instrutor) e algum instrutor selecionado
        # não teve aulas no período [data_inicio, data_fim], garante que seus dados cadastrais e
        # disciplinas vinculadas / CH anterior ainda sejam exibidos na revisão/exportação.
        if instrutor_ids_set:
            selected_insts = db.session.scalars(
                select(Instrutor)
                .options(joinedload(Instrutor.user))
                .where(Instrutor.id.in_(instrutor_ids_set))
            ).unique().all()

            disc_query = (
                select(Disciplina, Turma)
                .outerjoin(Turma, Disciplina.turma_id == Turma.id)
                .join(Ciclo, Disciplina.ciclo_id == Ciclo.id)
                .where(Ciclo.school_id == school_id)
            )
            if active_edicao:
                disc_query = disc_query.filter(Ciclo.edicao_id == active_edicao)
            if ciclo_id:
                disc_query = disc_query.filter(Ciclo.id == ciclo_id)
            disc_rows = db.session.execute(disc_query).all()
            disc_by_id = {d.id: (d, t) for d, t in disc_rows}

            all_selected_inst_ids = set(instrutor_ids_set)
            if user_ids_filter_set:
                extra_inst_ids = db.session.scalars(
                    select(Instrutor.id).where(Instrutor.user_id.in_(user_ids_filter_set))
                ).all()
                all_selected_inst_ids.update(extra_inst_ids)

            dt_links = db.session.scalars(
                select(DisciplinaTurma).where(
                    or_(
                        DisciplinaTurma.instrutor_id_1.in_(all_selected_inst_ids),
                        DisciplinaTurma.instrutor_id_2.in_(all_selected_inst_ids)
                    )
                )
            ).all() if all_selected_inst_ids else []

            for inst_obj in selected_insts:
                usr_obj = inst_obj.user
                if not usr_obj:
                    continue
                chave_agrupamento = _ensure_instrutor_entry(usr_obj, inst_obj)

                # Se o instrutor selecionado não teve aulas no período selecionado, puxa disciplinas com CH Anterior ou vínculo em DisciplinaTurma
                if not dados_agrupados[chave_agrupamento]["disciplinas_map"]:
                    for (u_id, d_id), ch_ant_val in ch_anterior_map.items():
                        if u_id == usr_obj.id and d_id in disc_by_id and ch_ant_val > 0:
                            d_obj, t_obj = disc_by_id[d_id]
                            pels = pelotoes_ant_map.get((u_id, d_id)) or {(t_obj.nome if t_obj else "PADRAO")}
                            for pel in pels:
                                _ensure_disciplina_entry(chave_agrupamento, usr_obj.id, d_obj, pel)

                if not dados_agrupados[chave_agrupamento]["disciplinas_map"]:
                    for dt in dt_links:
                        if dt.instrutor_id_1 == inst_obj.id or dt.instrutor_id_2 == inst_obj.id:
                            if dt.disciplina_id in disc_by_id:
                                d_obj, t_obj = disc_by_id[dt.disciplina_id]
                                pel_name = dt.pelotao or (t_obj.nome if t_obj else "PADRAO")
                                _ensure_disciplina_entry(chave_agrupamento, usr_obj.id, d_obj, pel_name)

                if not dados_agrupados[chave_agrupamento]["disciplinas_map"]:
                    dados_agrupados[chave_agrupamento]["disciplinas_map"]["SEM AULAS NO PERÍODO"] = {
                        "nome_disciplina": "Sem aulas registradas no período selecionado",
                        "ch_total_disciplina": 0,
                        "ch_anterior": 0.0,
                        "ch_mes": 0.0,
                    }

        lista_final = []
        chaves_ordenadas = sorted(dados_agrupados.keys())

        for chave in chaves_ordenadas:
            item = dados_agrupados[chave]
            lista_disciplinas = list(item["disciplinas_map"].values())
            for d in lista_disciplinas:
                d.pop("_pelotoes_contabilizados", None)
                d.pop("_disciplinas_ids_contabilizados", None)

            lista_final.append({
                "instrutor_id": item["info"]["instrutor_id"],
                "nome": item["info"]["user"]["nome_completo"] or "SEM NOME",
                "nome_de_guerra": item["info"]["user"].get("nome_de_guerra") or "",
                "posto": item["info"]["user"]["posto_graduacao"] or "",
                "matricula": item["info"]["user"]["matricula"] or "S/M",
                "identidade": item["info"]["user"]["identidade"] or "",
                "cpf": item["info"]["user"]["cpf"] or "",
                "email": item["info"]["user"].get("email") or "",
                "telefone": item["info"]["user"].get("telefone") or "",
                "disciplinas": lista_disciplinas
            })

        return lista_final

    @staticmethod
    def export_to_google_sheets(contexto: Dict[str, Any]) -> Tuple[bool, str]:
        from .xlsx_service import gerar_mapa_gratificacao_xlsx
        try:
            xlsx_bytes = gerar_mapa_gratificacao_xlsx(
                dados=contexto.get("dados"),
                valor_hora_aula=float(contexto.get("valor_hora_aula") or 0.0),
                nome_mes_ano=contexto.get("nome_mes_ano"),
                titulo_curso=contexto.get("titulo_curso"),
                opm_nome=contexto.get("opm"),
                escola_nome=contexto.get("escola_nome"),
                data_emissao=contexto.get("data_emissao"),
                telefone=contexto.get("telefone"),
                auxiliar_nome=contexto.get("auxiliar_nome"),
                comandante_nome=contexto.get("comandante_nome"),
                digitador_nome=contexto.get("digitador_nome"),
                auxiliar_funcao=contexto.get("auxiliar_funcao"),
                comandante_funcao=contexto.get("comandante_funcao"),
                data_fim=contexto.get("data_fim"),
                cidade_assinatura=contexto.get("cidade"),
            )
            nome_arquivo = f'Relatório Horas-Aula - {contexto.get("nome_mes_ano", "geral")}'
            sheet_url = _upload_xlsx_and_convert_to_sheet(nome_arquivo, xlsx_bytes)
            return (True, sheet_url) if sheet_url else (False, "Falha no upload do arquivo.")
        except Exception as e:
            return False, f"Erro ao exportar: {e}"
