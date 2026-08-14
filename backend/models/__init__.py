from .database import db
from .user import User
from .school import School
from .user_school import UserSchool
from .turma import Turma
from .aluno import Aluno
from .disciplina import Disciplina
from .historico import HistoricoAluno
from .historico_disciplina import HistoricoDisciplina
from .turma_cargo import TurmaCargo
from .semana import Semana
from .horario import Horario
from .instrutor import Instrutor
from .disciplina_turma import DisciplinaTurma
from .processo_disciplina import ProcessoDisciplina
from .discipline_rule import DisciplineRule
from .notification import Notification
from .site_config import SiteConfig
from .password_reset_token import PasswordResetToken
from .push_subscription import PushSubscription
from .image_asset import ImageAsset
from .diario_classe import DiarioClasse
from .frequencia import FrequenciaAluno
from .fada_avaliacao import FadaAvaliacao
from .ciclo import Ciclo
from .questionario import Questionario
from .pergunta import Pergunta
from .opcao_resposta import OpcaoResposta
from .resposta import Resposta
from .elogio import Elogio

# --- NOVO MÓDULO: BANCO DE QUESTÕES E PROVAS ---
# CORREÇÃO AQUI: Adicionado ConfiguracaoEnvio
from .banco_questoes import QuestaoBanco, DelegacaoProva, RascunhoProva, ConfiguracaoEnvio

# --- NOVO MÓDULO: RECURSOS ---
from .recurso import ProvaRecurso, Recurso, DisciplinaHabilitada

# --- SUPORTE ---
from .chamado_suporte import ChamadoSuporte

# --- AVALIAÇÃO DE INSTRUTORES ---
from .avaliacao_instrutor import CampanhaAvaliacao, RespostaAvaliacao

__all__ = [
    "db", "User", "School", "UserSchool", "Turma", "Aluno", "Disciplina",
    "HistoricoAluno", "HistoricoDisciplina", "TurmaCargo", "Semana", "Horario",
    "Instrutor", "DisciplinaTurma", "ProcessoDisciplina", "DisciplineRule",
    "AvaliacaoAtitudinal", "Notification", "SiteConfig", "PasswordResetToken",
    "PushSubscription", "ImageAsset", "DiarioClasse", "FrequenciaAluno",
    "FadaAvaliacao", "Ciclo", "Questionario", "Pergunta", "OpcaoResposta",
    "Resposta", "Elogio", 
    # CORREÇÃO AQUI: Adicionado ConfiguracaoEnvio
    "QuestaoBanco", "DelegacaoProva", "RascunhoProva", "ConfiguracaoEnvio",
    # MÓDULO DE RECURSOS
    "ProvaRecurso", "Recurso", "DisciplinaHabilitada",
    "ChamadoSuporte",
    # AVALIAÇÃO DE INSTRUTORES
    "CampanhaAvaliacao", "RespostaAvaliacao"
]