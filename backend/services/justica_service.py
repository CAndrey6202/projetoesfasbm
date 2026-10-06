# backend/services/justica_service.py
import logging
from datetime import datetime, date, timedelta
from sqlalchemy import select, and_, or_, func
from sqlalchemy.orm import joinedload

from ..models.database import db
from ..models.aluno import Aluno
from ..models.turma import Turma
from ..models.ciclo import Ciclo
from ..models.school import School
from ..models.processo_disciplina import ProcessoDisciplina, StatusProcesso
from ..models.fada_avaliacao import FadaAvaliacao
from ..models.discipline_rule import DisciplineRule
from ..models.elogio import Elogio

logger = logging.getLogger(__name__)


class JusticaService:
    FADA_BASE = 8.0
    FADA_MAX_ABSOLUTO = 10.0
    NDISC_BASE = 20.0

    DESC_FADA_LEVE = 0.25
    DESC_FADA_MEDIA = 0.50
    DESC_FADA_GRAVE = 1.00
    DESC_FADA_RDBM = 2.00
    DESC_FADA_CRIME = 3.00
    BONUS_ELOGIO = 0.00

    @staticmethod
    def _ensure_datetime(dt_input):
        if dt_input is None:
            return datetime.now().astimezone()
        if isinstance(dt_input, datetime):
            if dt_input.tzinfo is None:
                return dt_input.astimezone()
            return dt_input
        if isinstance(dt_input, date):
            return datetime.combine(dt_input, datetime.min.time()).astimezone()
        if isinstance(dt_input, str):
            try:
                return datetime.strptime(dt_input, "%Y-%m-%d %H:%M").astimezone()
            except:
                pass
            try:
                return datetime.strptime(dt_input, "%Y-%m-%d").astimezone()
            except:
                pass
        return datetime.now().astimezone()

    @staticmethod
    def _get_safe_far_future():
        return datetime(3000, 1, 1).astimezone()

    @staticmethod
    def _is_curso_pontuado(aluno_id=None, school=None, turma=None, edicao=None):
        try:
            tipo = None
            if edicao:
                tipo = edicao.npccal_type
            elif turma and turma.edicao:
                tipo = turma.edicao.npccal_type
            elif aluno_id:
                aluno = db.session.get(Aluno, aluno_id)
                if aluno and aluno.turma and aluno.turma.edicao:
                    tipo = aluno.turma.edicao.npccal_type

            tipo = str(tipo).lower().strip() if tipo else ""
            return tipo in ["cbfpm", "cspm"]
        except:
            return False

    @staticmethod
    def get_data_inicio_2_ciclo(turma_id):
        try:
            turma = db.session.get(Turma, turma_id)
            if not turma or not turma.school_id:
                return None
            ciclos = db.session.scalars(
                select(Ciclo)
                .where(Ciclo.school_id == turma.school_id)
                .order_by(Ciclo.data_inicio)
            ).all()
            if len(ciclos) >= 2:
                return JusticaService._ensure_datetime(ciclos[1].data_inicio)
            ciclo2 = next((c for c in ciclos if "2" in c.nome or "II" in c.nome), None)
            if ciclo2:
                return JusticaService._ensure_datetime(ciclo2.data_inicio)
            return None
        except:
            return None

    @staticmethod
    def get_datas_limites(turma_id):
        turma = db.session.get(Turma, turma_id)
        if not turma or not turma.edicao:
            return None, None

        # 1. Verificação Customizada (FADA na Edição)
        if turma.edicao.fada_data_inicio or turma.edicao.fada_data_fim:
            dt_inicio = (
                JusticaService._ensure_datetime(turma.edicao.fada_data_inicio)
                if turma.edicao.fada_data_inicio
                else None
            )
            dt_fim = (
                JusticaService._ensure_datetime(turma.edicao.fada_data_fim)
                if turma.edicao.fada_data_fim
                else JusticaService._get_safe_far_future()
            )
            return dt_inicio, dt_fim

        # 2. Fallback Automático (Regra Antiga via Ciclo/Formatura)
        dt_inicio_2_ciclo = JusticaService.get_data_inicio_2_ciclo(turma_id)
        dt_limite = JusticaService._get_safe_far_future()
        if turma.edicao.data_formatura:
            dt_form = JusticaService._ensure_datetime(turma.edicao.data_formatura)
            dt_limite = dt_form - timedelta(days=40)
        return dt_inicio_2_ciclo, dt_limite

    @staticmethod
    def verificar_elegibilidade_punicao(
        processo, dt_inicio_2_ciclo, dt_limite_atitudinal
    ):
        data_fato = JusticaService._ensure_datetime(processo.data_ocorrencia)
        if not data_fato:
            return False
        if dt_limite_atitudinal:
            dt_limite = JusticaService._ensure_datetime(dt_limite_atitudinal)
            if data_fato > dt_limite:
                return False
        if processo.is_crime or processo.origem_punicao == "RDBM":
            return True
        if dt_inicio_2_ciclo:
            dt_inicio_safe = JusticaService._ensure_datetime(dt_inicio_2_ciclo)
            if data_fato < dt_inicio_safe:
                return False
        else:
            return False
        return True

    @staticmethod
    def calcular_limites_fada(aluno_id, mapa_vinculos=None):
        limites = [JusticaService.FADA_MAX_ABSOLUTO] * 18
        aluno = db.session.get(Aluno, aluno_id)
        if not aluno:
            return limites, None
        dt_inicio, dt_limite = JusticaService.get_datas_limites(aluno.turma_id)
        stmt = select(ProcessoDisciplina).where(
            ProcessoDisciplina.aluno_id == aluno_id,
            ProcessoDisciplina.status == StatusProcesso.FINALIZADO.value,
        )
        processos = db.session.scalars(stmt).all()
        if mapa_vinculos is None:
            mapa_vinculos = {}

        for p in processos:
            if JusticaService.verificar_elegibilidade_punicao(p, dt_inicio, dt_limite):
                desconto = 0.0
                if p.is_crime:
                    desconto = JusticaService.DESC_FADA_CRIME
                elif p.origem_punicao == "RDBM":
                    desconto = JusticaService.DESC_FADA_RDBM
                elif p.pontos:
                    if p.pontos >= 1.0:
                        desconto = JusticaService.DESC_FADA_GRAVE
                    elif p.pontos >= 0.5:
                        desconto = JusticaService.DESC_FADA_MEDIA
                    else:
                        desconto = JusticaService.DESC_FADA_LEVE

                if desconto > 0:
                    str_pid = str(p.id)
                    if str_pid not in mapa_vinculos or not mapa_vinculos[str_pid]:
                        return (
                            limites,
                            f"A infração (ID {p.id}) de {desconto} pontos não foi vinculada a nenhum atributo.",
                        )
                    try:
                        idx_atributo = int(mapa_vinculos[str_pid])
                        if idx_atributo < 1 or idx_atributo > 18:
                            raise ValueError()
                    except:
                        return limites, f"Vínculo inválido para a infração ID {p.id}."
                    limites[idx_atributo - 1] -= desconto
        limites = [max(0.0, l) for l in limites]
        return limites, None

    @staticmethod
    def calcular_ndisc_aluno(aluno_id, aluno_obj=None, processos_list=None):
        aluno = aluno_obj or db.session.get(Aluno, aluno_id)
        if not aluno:
            return 0.0
        if not JusticaService._is_curso_pontuado(turma=aluno.turma):
            return 10.0

        dt_inicio, dt_limite = JusticaService.get_datas_limites(aluno.turma_id)
        if processos_list is None:
            query = select(ProcessoDisciplina).where(
                ProcessoDisciplina.aluno_id == aluno_id,
                ProcessoDisciplina.status == StatusProcesso.FINALIZADO.value,
                ProcessoDisciplina.decisao_final != 'Justificado'
            )
            processos = db.session.scalars(query).all()
        else:
            processos = [
                p for p in processos_list if p.status == StatusProcesso.FINALIZADO.value and p.decisao_final != 'Justificado'
            ]

        pontos_perdidos = 0.0
        for p in processos:
            if JusticaService.verificar_elegibilidade_punicao(p, dt_inicio, dt_limite):
                if p.origem_punicao == "NPCCAL" and p.pontos:
                    pontos_perdidos += p.pontos
        ndisc = (JusticaService.NDISC_BASE - pontos_perdidos) / 2.0
        return max(0.0, min(10.0, ndisc))

    @staticmethod
    def calcular_fada_estimada(aluno_id, aluno_obj=None, processos_list=None):
        aluno = aluno_obj or db.session.get(Aluno, aluno_id)
        if not aluno:
            return 0.0
        if not JusticaService._is_curso_pontuado(turma=aluno.turma):
            return 10.0

        dt_inicio, dt_limite = JusticaService.get_datas_limites(aluno.turma_id)
        if processos_list is None:
            query_proc = select(ProcessoDisciplina).where(
                ProcessoDisciplina.aluno_id == aluno_id,
                ProcessoDisciplina.status == StatusProcesso.FINALIZADO.value,
                ProcessoDisciplina.decisao_final != 'Justificado'
            )
            processos = db.session.scalars(query_proc).all()
        else:
            processos = [
                p for p in processos_list if p.status == StatusProcesso.FINALIZADO.value and p.decisao_final != 'Justificado'
            ]

        query_elogios = select(Elogio).where(Elogio.aluno_id == aluno_id)
        elogios = db.session.scalars(query_elogios).all()

        descontos_totais_pontos = 0.0
        for p in processos:
            if not JusticaService.verificar_elegibilidade_punicao(
                p, dt_inicio, dt_limite
            ):
                continue
            val = 0.0
            if p.is_crime:
                val = JusticaService.DESC_FADA_CRIME
            elif p.origem_punicao == "RDBM":
                val = JusticaService.DESC_FADA_RDBM
            elif p.pontos:
                if p.pontos >= 1.0:
                    val = JusticaService.DESC_FADA_GRAVE
                elif p.pontos >= 0.5:
                    val = JusticaService.DESC_FADA_MEDIA
                else:
                    val = JusticaService.DESC_FADA_LEVE
            descontos_totais_pontos += val

        bonus_total = min(len(elogios), 2) * JusticaService.BONUS_ELOGIO

        media_calculada = (
            18.0 * JusticaService.FADA_BASE - descontos_totais_pontos + bonus_total
        ) / 18.0
        media_final = max(0.0, min(10.0, media_calculada))

        return media_final

    @staticmethod
    def calcular_aat_final(aluno_id):
        aluno = db.session.scalar(
            select(Aluno)
            .options(joinedload(Aluno.turma).joinedload(Turma.edicao))
            .where(Aluno.id == aluno_id)
        )
        if not aluno:
            return None, None, None
        if not JusticaService._is_curso_pontuado(turma=aluno.turma):
            return None, None, None

        query_proc = select(ProcessoDisciplina).where(
            ProcessoDisciplina.aluno_id == aluno_id,
            ProcessoDisciplina.status == StatusProcesso.FINALIZADO.value,
        )
        processos = db.session.scalars(query_proc).all()

        ndisc = JusticaService.calcular_ndisc_aluno(
            aluno_id, aluno_obj=aluno, processos_list=processos
        )
        fada_oficial = db.session.scalar(
            select(FadaAvaliacao)
            .where(FadaAvaliacao.aluno_id == aluno_id)
            .order_by(FadaAvaliacao.data_avaliacao.desc())
        )

        if fada_oficial:
            nota_fada = fada_oficial.media_final
            aat = (ndisc + nota_fada) / 2.0
            return round(aat, 2), round(ndisc, 2), round(nota_fada, 4)
        else:
            return None, round(ndisc, 2), None

    @staticmethod
    def get_processos_para_usuario(user, school_id_override=None):
        query = (
            select(ProcessoDisciplina)
            .join(ProcessoDisciplina.aluno)
            .outerjoin(Aluno.turma)
        )
        if getattr(user, "role", "") == "aluno":
            if not getattr(user, "aluno_profile", None):
                return []
            query = query.where(ProcessoDisciplina.aluno_id == user.aluno_profile.id)

        query = query.options(
            joinedload(ProcessoDisciplina.aluno).joinedload(Aluno.user),
            joinedload(ProcessoDisciplina.regra),
        )
        todos_processos = db.session.scalars(
            query.order_by(ProcessoDisciplina.data_ocorrencia.desc())
        ).all()

        if school_id_override:
            processos_filtrados = []
            for p in todos_processos:
                if p.aluno.turma and p.aluno.turma.school_id == school_id_override:
                    processos_filtrados.append(p)
                elif not p.aluno.turma:
                    processos_filtrados.append(p)
            return processos_filtrados

        return todos_processos

    @staticmethod
    def criar_processo(
        descricao,
        observacao,
        aluno_id,
        autor_id,
        pontos=0.0,
        codigo_infracao=None,
        regra_id=None,
        data_ocorrencia=None,
    ):
        try:
            if not JusticaService._is_curso_pontuado(aluno_id=aluno_id):
                pontos = 0.0
            dt = JusticaService._ensure_datetime(data_ocorrencia)
            regra = db.session.get(DisciplineRule, regra_id) if regra_id else None
            cod = regra.codigo if regra else codigo_infracao
            novo = ProcessoDisciplina(
                aluno_id=aluno_id,
                relator_id=autor_id,
                fato_constatado=descricao,
                observacao=observacao,
                pontos=pontos,
                codigo_infracao=cod,
                regra_id=regra_id,
                status=StatusProcesso.AGUARDANDO_CIENCIA.value,
                data_ocorrencia=dt,
                origem_punicao="NPCCAL",
            )
            db.session.add(novo)
            db.session.commit()
            return True, "Sucesso"
        except Exception as e:
            db.session.rollback()
            return False, str(e)

    @staticmethod
    def get_pontuacao_config(school):
        if not school:
            return False, 0.0
        return JusticaService._is_curso_pontuado(
            school=school
        ), JusticaService.BONUS_ELOGIO

    @staticmethod
    def finalizar_processo(
        pid,
        decisao,
        fundamentacao,
        detalhes,
        is_crime=False,
        tipo_sancao=None,
        dias_sancao=None,
        origem="NPCCAL",
    ):
        try:
            p = db.session.get(ProcessoDisciplina, pid)
            if not p:
                return False, "Processo não encontrado."
            p.status = StatusProcesso.FINALIZADO.value
            p.decisao_final = decisao
            p.fundamentacao = fundamentacao
            p.detalhes_sancao = detalhes
            p.is_crime = is_crime
            p.tipo_sancao = tipo_sancao
            p.dias_sancao = dias_sancao if dias_sancao else 0
            p.origem_punicao = origem
            if decisao in ["IMPROCEDENTE", "ANULADO", "ARQUIVADO"]:
                p.pontos = 0.0
            p.data_decisao = datetime.now().astimezone()
            db.session.commit()
            return True, "Processo finalizado."
        except Exception as e:
            db.session.rollback()
            return False, str(e)

    @staticmethod
    def verificar_e_atualizar_prazos(processos):
        agora = datetime.now().astimezone()
        alterado = False

        for p in processos:
            # 1. Fase Inicial (AGUARDANDO_CIENCIA)
            # A nova doutrina não aplica mais revelia automática aqui.
            # O processo aguardará o Chefe clicar em "Punir Atraso" (via Frontend).

            # 2. Prazo de Defesa do Aluno (24h após ter dado o Ciente)
            if p.status == StatusProcesso.ALUNO_NOTIFICADO.value and p.prazo_defesa:
                prazo_seguro = JusticaService._ensure_datetime(p.prazo_defesa)
                if agora > prazo_seguro:
                    # CORREÇÃO: Aluno notificado que não envia defesa vai para EM_ANALISE (e não DEFESA_ENVIADA)
                    p.status = StatusProcesso.EM_ANALISE.value
                    p.is_revelia = True
                    msg = "\n[SISTEMA]: Prazo de 24h para defesa expirou sem manifestação. Julgamento à revelia."
                    p.observacao = (p.observacao or "") + msg
                    alterado = True

            # 3. Prazo de Recurso do Aluno (48h após a decisão do Chefe)
            elif p.status == StatusProcesso.DECISAO_EMITIDA.value and p.prazo_recurso:
                prazo_seguro = JusticaService._ensure_datetime(p.prazo_recurso)
                if agora > prazo_seguro:
                    p.status = StatusProcesso.FINALIZADO.value
                    msg = "\n[SISTEMA]: TRÂNSITO EM JULGADO: Prazo de recurso de 48h expirou."
                    p.observacao_decisao = (p.observacao_decisao or "") + msg
                    alterado = True

        if alterado:
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                logger.error(f"Erro ao verificar prazos: {e}")

        return alterado

    @staticmethod
    def registrar_ciente(pid, user):
        try:
            p = db.session.get(ProcessoDisciplina, pid)
            p.status = StatusProcesso.ALUNO_NOTIFICADO.value
            p.ciente_aluno = True
            p.data_ciente = datetime.now().astimezone()
            db.session.commit()
            return True, "Ciente"
        except:
            db.session.rollback()
            return False, "Erro"

    @staticmethod
    def enviar_defesa(pid, texto, user):
        try:
            p = db.session.get(ProcessoDisciplina, pid)
            p.status = StatusProcesso.DEFESA_ENVIADA.value
            p.defesa = texto
            p.data_defesa = datetime.now().astimezone()
            db.session.commit()
            return True, "Enviado"
        except:
            db.session.rollback()
            return False, "Erro"

    @staticmethod
    def deletar_processo(pid):
        try:
            p = db.session.get(ProcessoDisciplina, pid)
            db.session.delete(p)
            db.session.commit()
            return True, "Ok"
        except:
            return False, "Erro"
