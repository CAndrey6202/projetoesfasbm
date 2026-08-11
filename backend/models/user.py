# backend/models/user.py
from __future__ import annotations
import typing as t
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy import select
from .database import db
from flask import session, has_request_context

if t.TYPE_CHECKING:
    from .site_config import SiteConfig
    from .school import School
    from .user_school import UserSchool
    from .aluno import Aluno
    from .instrutor import Instrutor
    from .notification import Notification
    from .push_subscription import PushSubscription

class User(UserMixin, db.Model):
    __tablename__ = 'users'

    # --- CONSTANTES DE PERMISSÃO ---

    ROLE_ADMIN_ESCOLA = 'admin_escola'
    ROLE_ADMIN_CAL = 'admin_cal'
    ROLE_ADMIN_SENS = 'admin_sens'
    ROLE_INSTRUTOR = 'instrutor'
    ROLE_ALUNO = 'aluno'

    id: Mapped[int] = mapped_column(primary_key=True)
    matricula: Mapped[str] = mapped_column(db.String(20), unique=True, nullable=False)
    username: Mapped[t.Optional[str]] = mapped_column(db.String(80), unique=True, nullable=True)
    email: Mapped[t.Optional[str]] = mapped_column(db.String(120), unique=True, nullable=True)
    password_hash: Mapped[t.Optional[str]] = mapped_column(db.String(256), nullable=True)
    nome_completo: Mapped[t.Optional[str]] = mapped_column(db.String(120), nullable=True)
    nome_de_guerra: Mapped[t.Optional[str]] = mapped_column(db.String(50), nullable=True)
    posto_graduacao: Mapped[t.Optional[str]] = mapped_column(db.String(50), nullable=True)

    foto_perfil: Mapped[str] = mapped_column(db.String(255), default='default.png')
    assinatura_padrao_path: Mapped[t.Optional[str]] = mapped_column(db.String(255), nullable=True)

    role: Mapped[str] = mapped_column(db.String(20), nullable=False, default='aluno')

    is_active: Mapped[bool] = mapped_column(default=False, nullable=False)
    must_change_password: Mapped[bool] = mapped_column(default=False, nullable=False)


    totp_secret: Mapped[t.Optional[str]] = mapped_column(db.String(32), nullable=True)
    is_totp_enabled: Mapped[bool] = mapped_column(db.Boolean, default=False, server_default='0', nullable=False)

    # --- RELACIONAMENTOS ---
    # Removido uselist=False para suportar múltiplos perfis (1 por edição)
    alunos_profiles: Mapped[list['Aluno']] = relationship('Aluno', back_populates='user', cascade="all, delete-orphan")
    instrutor_profile: Mapped['Instrutor'] = relationship('Instrutor', back_populates='user', uselist=False, cascade="all, delete-orphan")
    user_schools: Mapped[list['UserSchool']] = relationship('UserSchool', back_populates='user', cascade="all, delete-orphan", lazy='selectin')

    # RELACIONAMENTO ROLES REMOVIDO PARA EVITAR ERRO DE MAPPER (Tabela inexistente)

    notifications: Mapped[list['Notification']] = relationship('Notification', back_populates='user', cascade="all, delete-orphan")
    push_subscriptions: Mapped[list['PushSubscription']] = relationship('PushSubscription', back_populates='user', cascade="all, delete-orphan")

    @property
    def aluno_profile(self) -> t.Optional['Aluno']:
        if not self.alunos_profiles:
            return None
        
        # Se estiver fora de um request (ex: CLI, tarefas cron), retorna o mais recente
        if not has_request_context():
            return sorted(self.alunos_profiles, key=lambda x: x.id, reverse=True)[0]
            
        active_edicao_id = session.get('active_edicao_id')
        if active_edicao_id:
            for profile in self.alunos_profiles:
                if profile.edicao_id == active_edicao_id:
                    return profile
                    
        # Fallback: Se não encontrou pela edição, retorna o perfil mais recente
        return sorted(self.alunos_profiles, key=lambda x: x.id, reverse=True)[0]

    @property
    def schools(self) -> list['School']:
        return [us.school for us in self.user_schools]

    site_configs_updated: Mapped[list['SiteConfig']] = relationship('SiteConfig', back_populates='updated_by_user')

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username or self.matricula}>'

    # =================================================================
    # LÓGICA DE PERMISSÕES
    # =================================================================

    def _get_active_school_id(self):
        if hasattr(self, 'temp_active_school_id'):
            return self.temp_active_school_id
        try:
            sid = session.get('active_school_id')
            return int(sid) if sid else None
        except:
            return None

    def get_role_in_school(self, school_id: int | str | None) -> str | None:
        current_global_role = str(self.role).lower().strip()

        # Superusuários só ignoram barreiras se estiverem em Modo DEC
        if current_global_role == 'super_admin' and session.get('is_dec_mode'):
            return 'super_admin'

        if not school_id:
            # Se não tem escola, e não tá em DEC, retorna a global (pode ser útil fora da escola)
            return current_global_role

        # Verifica se existe um VÍNCULO EXPLÍCITO nesta escola
        for us in self.user_schools:
            # COMPARAÇÃO ROBUSTA (STR vs STR)
            if str(us.school_id) == str(school_id):
                return str(us.role).lower().strip()

        # CORREÇÃO DO BUG GRAVE:
        # Antes retornava self.ROLE_ALUNO, permitindo que qualquer aluno entrasse em qualquer escola.
        # Agora retorna None se não encontrar vínculo explícito.
        return None

    @property
    def is_super_admin(self) -> bool:
        return str(self.role).lower().strip() == 'super_admin'

    # --- Verificadores Contextuais ---

    def is_admin_escola_in_school(self, school_id: int | None) -> bool:
        if self.is_super_admin and session.get('is_dec_mode') and school_id:
            return True
        return self.get_role_in_school(school_id) == self.ROLE_ADMIN_ESCOLA

    def is_cal_in_school(self, school_id: int | None) -> bool:
        if self.is_super_admin and session.get('is_dec_mode') and school_id:
            return True
        role = self.get_role_in_school(school_id)
        return role in [self.ROLE_ADMIN_CAL, self.ROLE_ADMIN_ESCOLA]

    def is_sens_in_school(self, school_id: int | None) -> bool:
        """SENS inclui ADMIN_SENS e ADMIN_ESCOLA (Comandante tem acesso total)"""
        if self.is_super_admin and session.get('is_dec_mode') and school_id:
            return True
        role = self.get_role_in_school(school_id)
        return role in [self.ROLE_ADMIN_SENS, self.ROLE_ADMIN_ESCOLA]

    def is_instrutor_in_school(self, school_id: int | None) -> bool:
        if self.is_super_admin and session.get('is_dec_mode') and school_id:
            return True
        role = self.get_role_in_school(school_id)
        return role == self.ROLE_INSTRUTOR

    def is_staff_in_school(self, school_id: int | None) -> bool:
        """Staff inclui SENS, CAL e Comandante"""
        if self.is_super_admin and session.get('is_dec_mode') and school_id:
            return True
        role = self.get_role_in_school(school_id)
        return role in [self.ROLE_ADMIN_SENS, self.ROLE_ADMIN_CAL, self.ROLE_ADMIN_ESCOLA]

    @property
    def is_admin_escola(self):
        sid = self._get_active_school_id()
        return self.is_admin_escola_in_school(sid)

    @property
    def is_cal(self):
        sid = self._get_active_school_id()
        return self.is_cal_in_school(sid)

    @property
    def is_sens(self):
        sid = self._get_active_school_id()
        return self.is_sens_in_school(sid)

    @property
    def is_staff(self):
        sid = self._get_active_school_id()
        return self.is_staff_in_school(sid)

    @property
    def is_chefe_turma(self) -> bool:
        """Verifica se o usuário (aluno) possui o cargo de Chefe de Turma."""
        if str(self.role).lower().strip() != self.ROLE_ALUNO:
            return False
        if not self.aluno_profile:
            return False

        try:
            # Importação local para evitar ciclo de importação
            from .turma_cargo import TurmaCargo

            stmt = select(TurmaCargo).where(
                TurmaCargo.aluno_id == self.aluno_profile.id,
                TurmaCargo.cargo_nome == TurmaCargo.ROLE_CHEFE
            )
            result = db.session.execute(stmt).scalar()
            return result is not None
        except Exception:
            return False

    @property
    def pode_enviar_questoes(self) -> bool:
        sid = self._get_active_school_id()
        if not sid: return False

        from .banco_questoes import ConfiguracaoEnvio
        from .disciplina_turma import DisciplinaTurma
        from .disciplina import Disciplina
        from .turma import Turma
        from .database import db

        try:
            configs = db.session.query(ConfiguracaoEnvio).filter_by(escola_id=sid, envio_ativo=True).all()
            if not configs:
                return False
                
            if not self.instrutor_profile:
                return False
                
            vinculos_db = db.session.query(Disciplina.materia, Turma.edicao_id)\
                .join(DisciplinaTurma, DisciplinaTurma.disciplina_id == Disciplina.id)\
                .join(Turma, Disciplina.turma_id == Turma.id)\
                .filter(
                    Turma.school_id == sid,
                    db.or_(
                        DisciplinaTurma.instrutor_id_1 == self.instrutor_profile.id,
                        DisciplinaTurma.instrutor_id_2 == self.instrutor_profile.id
                    )
                ).distinct().all()
                
            materias_vinculadas = set(vinculos_db)
            
            for c in configs:
                for v_materia, v_edicao in materias_vinculadas:
                    if v_materia == c.materia:
                        if c.edicao_id is None or c.edicao_id == v_edicao:
                            return True
            return False
        except Exception:
            return False

    @property
    def tem_delegacao_prova(self) -> bool:
        if not self.instrutor_profile: return False

        from .banco_questoes import DelegacaoProva
        from .database import db

        try:
            delegacao = db.session.query(DelegacaoProva).filter_by(instrutor_id=self.instrutor_profile.id).first()
            return delegacao is not None
        except Exception:
            return False