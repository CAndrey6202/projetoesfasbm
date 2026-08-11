# backend/services/site_config_service.py

from sqlalchemy import select
from cachetools import TTLCache
from backend.models.database import db
from backend.models.site_config import SiteConfig
import re


class CachedConfig:
    def __init__(self, db_obj_or_key, config_value=None, config_type='text', description=None, category='general', id=None):
        if hasattr(db_obj_or_key, 'config_key'):
            self.id = db_obj_or_key.id
            self.config_key = db_obj_or_key.config_key
            self.config_value = db_obj_or_key.config_value
            self.config_type = db_obj_or_key.config_type
            self.description = db_obj_or_key.description
            self.category = db_obj_or_key.category
        else:
            self.id = id
            self.config_key = db_obj_or_key
            self.config_value = config_value
            self.config_type = config_type
            self.description = description
            self.category = category


class SiteConfigService:
    """
    Serviço para leitura/escrita de configurações do site.
    Suporta contexto de escola via namespace de chaves.
    """

    _DEFAULT_CONFIGS = [
        # Configurações gerais
        ('site_background', '', 'image', 'Imagem de fundo do site', 'general'),
        ('site_logo', '', 'image', 'Logo principal do site', 'general'),
        ('primary_color', '#3b82f6', 'color', 'Cor primária do site', 'general'),
        ('secondary_color', '#1a232c', 'color', 'Cor secundária do site', 'general'),
        ('navbar_background_image', '', 'image', 'Imagem de fundo da barra de navegação', 'general'),
        
        # Ícones do dashboard
        ('dashboard_card_alunos_icon', '👥', 'text', 'Ícone do card Alunos', 'dashboard'),
        ('dashboard_card_instrutores_icon', '🎓', 'text', 'Ícone do card Instrutores', 'dashboard'),
        ('dashboard_card_disciplinas_icon', '📚', 'text', 'Ícone do card Disciplinas', 'dashboard'),
        ('dashboard_card_historico_icon', '📊', 'text', 'Ícone do card Histórico', 'dashboard'),
        ('dashboard_card_assets_icon', '🎨', 'text', 'Ícone do card Assets', 'dashboard'),
        
        # Imagens de fundo dos cards
        ('dashboard_card_alunos_bg', '', 'image', 'Imagem de fundo do card Alunos', 'dashboard'),
        ('dashboard_card_instrutores_bg', '', 'image', 'Imagem de fundo do card Instrutores', 'dashboard'),
        ('dashboard_card_disciplinas_bg', '', 'image', 'Imagem de fundo do card Disciplinas', 'dashboard'),
        ('dashboard_card_historico_bg', '', 'image', 'Imagem de fundo do card Histórico', 'dashboard'),
        ('dashboard_card_assets_bg', '', 'image', 'Imagem de fundo do card Assets', 'dashboard'),
        ('dashboard_card_customizer_bg', '', 'image', 'Imagem de fundo do card Customizar', 'dashboard'),
        ('dashboard_header_bg', '', 'image', 'Imagem de fundo do cabeçalho do dashboard', 'dashboard'),
        
        # Sidebar
        ('sidebar_logo', '', 'image', 'Logo da sidebar', 'sidebar'),

        # Ícones das Turmas
        ('turma_1_icon', '', 'image', 'Ícone da Turma 1', 'turmas'),
        ('turma_2_icon', '', 'image', 'Ícone da Turma 2', 'turmas'),
        ('turma_3_icon', '', 'image', 'Ícone da Turma 3', 'turmas'),
        ('turma_4_icon', '', 'image', 'Ícone da Turma 4', 'turmas'),
        ('turma_5_icon', '', 'image', 'Ícone da Turma 5', 'turmas'),
        ('turma_6_icon', '', 'image', 'Ícone da Turma 6', 'turmas'),
        ('turma_7_icon', '', 'image', 'Ícone da Turma 7', 'turmas'),
        ('turma_8_icon', '', 'image', 'Ícone da Turma 8', 'turmas'),

        # Configurações de Relatórios
        ('report_chefe_ensino_cargo', 'Chefe da Seção de Ensino', 'text', 'Cargo padrão do Chefe de Ensino em relatórios', 'reports'),
        ('report_comandante_cargo', 'Comandante da EsFAS-SM', 'text', 'Cargo padrão do Comandante em relatórios', 'reports'),
        ('report_cidade_estado', 'Santa Maria - RS', 'text', 'Cidade e Estado padrão para relatórios', 'reports'),
        ('report_valor_hora_aula', '55.19', 'number', 'Valor da hora-aula padrão usado em relatórios', 'reports'),

        # Horários dos Períodos
        ('horario_intervalo_manha', '09:45-10:00', 'text', 'Intervalo Manhã', 'horarios'),
        ('posicao_intervalo_manha', '3', 'text', 'Posição do Int. da Manhã (Após qual período?)', 'horarios'),
        
        ('horario_intervalo_almoco', '12:15-13:45', 'text', 'Intervalo Almoço', 'horarios'),
        ('posicao_intervalo_almoco', '6', 'text', 'Posição do Almoço (Após qual período?)', 'horarios'),
        
        ('horario_intervalo_tarde', '16:00-16:15', 'text', 'Intervalo Tarde', 'horarios'),
        ('posicao_intervalo_tarde', '9', 'text', 'Posição do Int. da Tarde (Após qual período?)', 'horarios'),
        
        ('horario_periodo_01', '07:30-08:15', 'text', '1º Período', 'horarios'),
        ('horario_periodo_02', '08:15-09:00', 'text', '2º Período', 'horarios'),
        ('horario_periodo_03', '09:00-09:45', 'text', '3º Período', 'horarios'),
        ('horario_periodo_04', '10:00-10:45', 'text', '4º Período', 'horarios'),
        ('horario_periodo_05', '10:45-11:30', 'text', '5º Período', 'horarios'),
        ('horario_periodo_06', '11:30-12:15', 'text', '6º Período', 'horarios'),
        ('horario_periodo_07', '13:45-14:30', 'text', '7º Período', 'horarios'),
        ('horario_periodo_08', '14:30-15:15', 'text', '8º Período', 'horarios'),
        ('horario_periodo_09', '15:15-16:00', 'text', '9º Período', 'horarios'),
        ('horario_periodo_10', '16:15-17:00', 'text', '10º Período', 'horarios'),
        ('horario_periodo_11', '17:00-17:45', 'text', '11º Período', 'horarios'),
        ('horario_periodo_12', '17:45-18:30', 'text', '12º Período', 'horarios'),
        ('horario_periodo_13', '18:30-19:15', 'text', '13º Período (Extra)', 'horarios'),
        ('horario_periodo_14', '19:15-20:00', 'text', '14º Período (Extra)', 'horarios'),
        ('horario_periodo_15', '20:00-20:45', 'text', '15º Período (Extra)', 'horarios'),
    ]

    _CONFIG_KEYS = {d[0]: {'type': d[2], 'category': d[4]} for d in _DEFAULT_CONFIGS}
    _DEFAULTS_MAP = {d[0]: d[1] for d in _DEFAULT_CONFIGS}

    _config_cache = TTLCache(maxsize=200, ttl=300)

    @staticmethod
    def get_config(key: str, default_value: str = None, school_id=None):
        """
        Busca uma configuração.
        Se school_id for fornecido, tenta buscar 'school_{id}_{key}'.
        Se não encontrar (ou não houver school_id), busca a 'key' global.
        Utiliza micro-cache em memória com teto de RAM (< 20 KB) isolado por escola.
        """
        cache_key = (school_id, key)
        if cache_key in SiteConfigService._config_cache:
            return SiteConfigService._config_cache[cache_key]

        result = None
        if school_id:
            school_key = f"school_{school_id}_{key}"
            config = db.session.execute(
                select(SiteConfig).where(SiteConfig.config_key == school_key)
            ).scalar_one_or_none()
            
            if config is not None:
                result = config.config_value

        if result is None:
            config = db.session.execute(
                select(SiteConfig).where(SiteConfig.config_key == key)
            ).scalar_one_or_none()
            
            if config is not None:
                result = config.config_value
                
        if result is None and key in SiteConfigService._DEFAULTS_MAP:
            result = SiteConfigService._DEFAULTS_MAP[key]
            
        if result is None:
            result = default_value

        SiteConfigService._config_cache[cache_key] = result
        return result

    _cache = None
    _cache_time = 0

    @staticmethod
    def get_all_configs():
        """Retorna todas as configs do banco (globais) + defaults não salvos (COM CACHE)."""
        import time
        now = time.time()
        
        # Retorna cache se válido (5 minutos)
        if SiteConfigService._cache is not None and (now - SiteConfigService._cache_time) < 300:
            return SiteConfigService._cache

        db_configs = db.session.execute(select(SiteConfig)).scalars().all()
        
        db_configs_map = {}
        for c in db_configs:
            detached_c = SiteConfig(
                config_key=c.config_key,
                config_value=c.config_value,
                config_type=c.config_type,
                description=c.description,
                category=c.category,
                updated_by=c.updated_by
            )
            detached_c.id = c.id
            db_configs_map[c.config_key] = detached_c
            
        final_configs = []
        for key, value, config_type, description, category in SiteConfigService._DEFAULT_CONFIGS:
            if key in db_configs_map:
                final_configs.append(CachedConfig(db_configs_map[key]))
            else:
                final_configs.append(CachedConfig(
                    db_obj_or_key=key, config_value=value, config_type=config_type,
                    description=description, category=category
                ))
                
        # Atualiza o cache
        SiteConfigService._cache = final_configs
        SiteConfigService._cache_time = now
        return final_configs

    @staticmethod
    def get_configs_by_category(category: str):
        all_configs = SiteConfigService.get_all_configs()
        return [c for c in all_configs if c.category == category]

    @staticmethod
    def init_default_configs():
        for key, value, config_type, description, category in SiteConfigService._DEFAULT_CONFIGS:
            existing = db.session.execute(
                select(SiteConfig).where(SiteConfig.config_key == key)
            ).scalar_one_or_none()
            if not existing:
                config = SiteConfig(
                    config_key=key,
                    config_value=value,
                    config_type=config_type,
                    description=description,
                    category=category
                )
                db.session.add(config)
        db.session.commit()
        SiteConfigService._cache = None
        SiteConfigService._config_cache.clear()
    
    @staticmethod
    def _parse_number_ptbr(value: str):
        if value is None or (isinstance(value, str) and value.strip() == ""): return None
        s = str(value).strip()
        if ',' in s and '.' in s: s = s.replace('.', '').replace(',', '.')
        elif ',' in s: s = s.replace(',', '.')
        try: return float(s)
        except Exception: raise ValueError(f"Não foi possível interpretar '{value}' como número.")
        
    @staticmethod
    def set_config(key: str, value: str, config_type: str = 'text', description: str = None, category: str = 'general', updated_by: int = None, school_id=None):
        """
        Salva uma configuração.
        Se school_id for fornecido, salva como 'school_{id}_{key}'.
        Caso contrário, sobrescreve a global.
        """
        target_key = key
        
        if school_id:
            target_key = f"school_{school_id}_{key}"
        
        if config_type == 'image':
            if value and not (value.startswith('/static/uploads/') or value.startswith('http://') or value.startswith('https://')): 
                raise ValueError(f"Valor inválido para configuração de imagem: {value}.")
        elif config_type == 'color':
            if value and not re.match(r'^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$', value): 
                raise ValueError(f"Valor inválido para cor: {value}. Esperado formato hexadecimal (#RRGGBB).")
        elif config_type == 'number':
            num = SiteConfigService._parse_number_ptbr(value)
            value = f"{num:.2f}" if num is not None else ""
            
        config = db.session.execute(select(SiteConfig).where(SiteConfig.config_key == target_key)).scalar_one_or_none()
        
        if config:
            config.config_value = value
            config.config_type = config_type
            if description: config.description = description
            if category: config.category = category
            config.updated_by = updated_by
        else:
            config = SiteConfig(
                config_key=target_key, 
                config_value=value, 
                config_type=config_type, 
                description=description or 'Configuração dinâmica', 
                category=category, 
                updated_by=updated_by
            )
            db.session.add(config)
        
        db.session.commit()
        SiteConfigService._cache = None
        SiteConfigService._config_cache.clear()
        return config

    @staticmethod
    def delete_config(key: str, school_id=None):
        target_key = key
        if school_id:
            target_key = f"school_{school_id}_{key}"
            
        db.session.query(SiteConfig).filter(SiteConfig.config_key == target_key).delete()
        db.session.commit()
        SiteConfigService._cache = None
        SiteConfigService._config_cache.clear()

    @staticmethod
    def delete_all_configs():
        db.session.query(SiteConfig).delete()
        db.session.commit()
        SiteConfigService._cache = None
        SiteConfigService._config_cache.clear()

    @staticmethod
    def get_valor_hora_aula(default: float = 55.19) -> float:
        raw = SiteConfigService.get_config('report_valor_hora_aula', None)
        if raw is None or str(raw).strip() == "": return float(default)
        try: return float(SiteConfigService._parse_number_ptbr(raw))
        except Exception: return float(default)

    @staticmethod
    def set_valor_hora_aula(value: float | str, updated_by: int = None):
        num = SiteConfigService._parse_number_ptbr(str(value))
        if num is None: raise ValueError("Valor da hora-aula não pode ser vazio.")
        return SiteConfigService.set_config(key='report_valor_hora_aula', value=f"{num:.2f}", config_type='number', description='Valor da hora-aula padrão usado em relatórios', category='reports', updated_by=updated_by)