from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify, session
from flask_login import login_required, current_user
from backend.services.site_config_service import SiteConfigService
from backend.services.user_service import UserService
from backend.models.database import db
from backend.models.site_config import SiteConfig
# CORREÇÃO: Importando utils direto da raiz, pois não está dentro de backend
from utils.decorators import admin_or_programmer_required

customizer_bp = Blueprint('customizer', __name__, url_prefix='/customizer')

@customizer_bp.route('/debug')
@login_required
def debug_screen():
    """
    Rota de diagnóstico para entender por que as configurações falham.
    """
    output = []
    output.append("<h1>Diagnóstico do Personalizador (Customizer)</h1>")
    
    try:
        # 1. Identificar Escola Ativa
        school_id = session.get('active_school_id') or UserService.get_current_school_id()
            
        output.append(f"<h3>1. Contexto de Execução</h3>")
        if school_id:
            output.append(f"<p style='color:green'>Escola Ativa ID: <strong>{school_id}</strong></p>")
        else:
            output.append("<p style='color:red'>ALERTA: Nenhuma escola selecionada na sessão. O sistema pode estar tentando salvar como GLOBAL.</p>")

        # 2. Listar Configurações Base (Permitidas)
        output.append(f"<h3>2. Chaves Permitidas (Base)</h3>")
        output.append("<p>O sistema só aceita atualizar chaves que já existam na lista abaixo:</p>")
        
        all_configs = SiteConfig.query.all()
        # Filtra apenas as que não são de escola específica
        base_keys = set()
        
        output.append("<ul>")
        for c in all_configs:
            if not c.config_key.startswith('school_'):
                base_keys.add(c.config_key)
                output.append(f"<li><strong>{c.config_key}</strong> (Tipo: {c.config_type})</li>")
        output.append("</ul>")
        
        # 3. Simulação de Recebimento
        output.append("<h3>3. O que acontece ao Salvar?</h3>")
        if school_id:
            output.append(f"<p>Para cada chave 'X', ele tentará salvar/buscar: <strong>school_{school_id}_X</strong></p>")
        else:
            output.append("<p>Ele tentará salvar na chave global 'X'.</p>")

        output.append("<h3>4. Configurações Já Salvas para esta Escola</h3>")
        if school_id:
            configs_escola = SiteConfig.query.filter(SiteConfig.config_key.like(f'school_{school_id}_%')).all()
            if configs_escola:
                output.append("<ul>")
                for c in configs_escola:
                    output.append(f"<li>{c.config_key}: {c.config_value}</li>")
                output.append("</ul>")
            else:
                output.append("<p>Nenhuma configuração específica encontrada para esta escola ainda.</p>")
        
    except Exception as e:
        import traceback
        output.append(f"<pre style='color:red'>{traceback.format_exc()}</pre>")

    return "<br>".join(output)

@customizer_bp.route('/', methods=['GET'])
@login_required
@admin_or_programmer_required
def index():
    # Obtém a escola ativa
    school_id = session.get('active_school_id') or UserService.get_current_school_id()

    # Busca tipos de curso (npccal_type) existentes nas edições desta escola
    from backend.models.edicao import Edicao
    edicoes_escola = []
    if school_id:
        edicoes_escola = Edicao.query.filter_by(school_id=school_id).order_by(Edicao.id.desc()).all()

    tipos_curso_map = {}
    tipos_curso = []
    for ed in edicoes_escola:
        t_code = (ed.npccal_type or 'outros').strip().lower()
        if t_code not in tipos_curso_map:
            item = {
                'code': t_code,
                'label': t_code.upper(),
                'edicoes': [ed.nome]
            }
            tipos_curso_map[t_code] = item
            tipos_curso.append(item)
        else:
            tipos_curso_map[t_code]['edicoes'].append(ed.nome)

    if not tipos_curso:
        tipos_curso.append({'code': 'padrao', 'label': 'PADRÃO', 'edicoes': []})

    selected_course_type = (request.args.get('course_type') or '').strip().lower()
    valid_codes = [t['code'] for t in tipos_curso]
    if selected_course_type not in valid_codes:
        active_ed_id = session.get('active_edicao_id')
        matched = False
        if active_ed_id:
            for ed in edicoes_escola:
                if str(ed.id) == str(active_ed_id):
                    c = (ed.npccal_type or 'outros').strip().lower()
                    if c in valid_codes:
                        selected_course_type = c
                        matched = True
                    break
        if not matched:
            selected_course_type = tipos_curso[0]['code']

    # Obtém todas as configurações base
    all_base_configs = SiteConfigService.get_all_configs()
    
    configs_by_category = {}
    horarios_por_tipo = {t['code']: {} for t in tipos_curso}
    
    for config in all_base_configs:
        if config.config_key.startswith('school_'):
            continue

        category = config.category or 'general'

        if category == 'horarios':
            for t in tipos_curso:
                horarios_por_tipo[t['code']][config.config_key] = SiteConfigService.get_config(
                    config.config_key,
                    config.config_value,
                    school_id=school_id,
                    course_type=t['code']
                )
            real_value = horarios_por_tipo[selected_course_type].get(config.config_key, config.config_value)
        else:
            # Busca valor contextualizado (escola ou global)
            real_value = SiteConfigService.get_config(config.config_key, config.config_value, school_id=school_id)
        
        config_display = {
            'config_key': config.config_key,
            'config_value': real_value,
            'config_type': config.config_type,
            'description': config.description,
            'category': config.category
        }
        
        if category not in configs_by_category:
            configs_by_category[category] = []
        configs_by_category[category].append(config_display)

    # Passa assets para os seletores de imagem
    from backend.models.image_asset import ImageAsset
    assets = ImageAsset.query.limit(200).all()

    return render_template(
        'customizer/index.html',
        configs_by_category=configs_by_category,
        assets=assets,
        tipos_curso=tipos_curso,
        selected_course_type=selected_course_type,
        horarios_por_tipo=horarios_por_tipo
    )

@customizer_bp.route('/update', methods=['POST'])
@login_required
@admin_or_programmer_required
def update():
    """
    Atualiza configurações.
    Aceita tanto o formato do JS {config_key: 'X', config_value: 'Y', course_type: 'Z'} 
    quanto o formato de Formulário {X: Y}.
    """
    school_id = session.get('active_school_id') or UserService.get_current_school_id()
    
    if not school_id:
         return jsonify({'success': False, 'message': 'Erro: Nenhuma escola selecionada.'}), 400

    try:
        # Lista de chaves válidas
        all_configs = SiteConfigService.get_all_configs()
        valid_keys = set()
        for c in all_configs:
            if not c.config_key.startswith('school_'):
                valid_keys.add(c.config_key)
        
        course_type = request.form.get('course_type')

        # LÓGICA DE CORREÇÃO:
        # Verifica se veio do Javascript (fetch) que envia chaves 'config_key' e 'config_value'
        key_param = request.form.get('config_key')
        if key_param:
            val_param = request.form.get('config_value')
            
            if key_param in valid_keys:
                SiteConfigService.set_config(key_param, val_param, school_id=school_id, course_type=course_type)
                return jsonify({'success': True, 'message': 'Configuração atualizada com sucesso.'})
            else:
                return jsonify({'success': False, 'message': f'Chave inválida: {key_param}'}), 400

        # Verifica se veio de um Formulário tradicional (vários campos de uma vez)
        updated_count = 0
        for key, value in request.form.items():
            if key in valid_keys:
                SiteConfigService.set_config(key, value, school_id=school_id, course_type=course_type)
                updated_count += 1
        
        if updated_count == 0:
             return jsonify({
                 'success': False, 
                 'message': 'Nenhuma configuração válida identificada no formulário.'
             }), 400

        return jsonify({'success': True, 'message': 'Configurações atualizadas com sucesso!'})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Erro interno: {str(e)}'}), 500

@customizer_bp.route('/reset', methods=['POST'])
@login_required
@admin_or_programmer_required
def reset_configs():
    """
    Reseta as configurações da escola atual.
    """
    school_id = session.get('active_school_id') or UserService.get_current_school_id()
    
    try:
        if not school_id:
             return jsonify({'success': False, 'message': 'Nenhuma escola selecionada.'}), 400

        target_prefix = f"school_{school_id}_"
        
        # Deleta configurações da escola
        deleted = SiteConfig.query.filter(SiteConfig.config_key.like(f'{target_prefix}%')).delete(synchronize_session=False)
        db.session.commit()
            
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accept_mimetypes.accept_json:
             return jsonify({'success': True, 'message': f'{deleted} configurações resetadas.'})
        
        flash(f'{deleted} configurações resetadas.', 'success')
        return redirect(url_for('customizer.index'))

    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro ao resetar: {str(e)}'}), 500

@customizer_bp.route('/preview')
@login_required
@admin_or_programmer_required
def preview():
    school_id = session.get('active_school_id') or UserService.get_current_school_id()
    
    configs = {
        'horario_periodo_01': SiteConfigService.get_config('horario_periodo_01', '08:00', school_id=school_id),
        'horario_intervalo_manha': SiteConfigService.get_config('horario_intervalo_manha', '09:40 - 10:00', school_id=school_id),
    }
    return render_template('customizer/preview.html', configs=configs)