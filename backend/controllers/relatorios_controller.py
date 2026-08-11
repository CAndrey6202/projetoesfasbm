# backend/controllers/relatorios_controller.py

from flask import Blueprint, render_template, request, flash, redirect, url_for, send_file, jsonify
from flask_login import login_required, current_user
from datetime import datetime
from typing import Optional
import io
import locale
import json

from weasyprint import HTML
from werkzeug.utils import secure_filename
import uuid

from ..services.relatorio_service import RelatorioService
from ..models.background_job import BackgroundJob
from ..models.database import db
from ..services.instrutor_service import InstrutorService
from ..services.site_config_service import SiteConfigService
from ..services.user_service import UserService
from ..services.xlsx_service import gerar_mapa_gratificacao_xlsx
from utils.decorators import admin_or_programmer_required

relatorios_bp = Blueprint('relatorios', __name__, url_prefix='/relatorios')


def _build_filename(prefix: str, label: Optional[str], extension: str, fallback: Optional[str] = None) -> str:
    label_component = label.strip() if isinstance(label, str) else None
    default_stub = fallback or prefix or "relatorio"
    base_name = "_".join(filter(None, (prefix, label_component))) or default_stub
    safe_with_ext = secure_filename(f"{base_name}.{extension}")
    if safe_with_ext:
        return safe_with_ext
    return secure_filename(f"{default_stub}.{extension}") or f"{default_stub}.{extension}"


@relatorios_bp.route('/')
@login_required
@admin_or_programmer_required
def index():
    school_id = UserService.get_current_school_id()
    if not school_id:
        flash('Selecione uma escola para acessar os relatórios.', 'warning')
        return redirect(url_for('main.dashboard'))

    return render_template('relatorios/index.html')


@relatorios_bp.route('/gerar', methods=['GET', 'POST'])
@login_required
@admin_or_programmer_required
def gerar_relatorio_horas_aula():
    school_id = UserService.get_current_school_id()
    if not school_id:
        flash('Selecione uma escola para gerar relatórios.', 'warning')
        return redirect(url_for('main.dashboard'))

    report_type = request.args.get('tipo', 'mensal')
    tipo_relatorio_titulo = report_type.replace("_", " ").title()

    todos_instrutores = []
    if report_type == 'por_instrutor':
        todos_instrutores = InstrutorService.get_all_instrutores_sem_paginacao(current_user)

    report_defaults = {
        "curso_nome": "Curso Técnico em Segurança Pública",
        "opm": "Escola de Formação e Aperfeiçoamento de Sargentos",
        "escola_nome": "Escola de Formação e Aperfeiçoamento de Sargentos",
        "telefone": "(55) 3220-6462",
        "cidade": SiteConfigService.get_config('report_cidade_estado', 'Santa Maria - RS') or 'Santa Maria - RS',
        "comandante_funcao": SiteConfigService.get_config('report_comandante_cargo', 'Comandante da EsFAS-SM') or 'Comandante da EsFAS-SM',
        "auxiliar_funcao": SiteConfigService.get_config('report_chefe_ensino_cargo', 'Chefe da Seção de Ensino') or 'Chefe da Seção de Ensino',
    }

    if request.method == 'POST':
        # Se vier da tela de edição final (Ação de exportação confirmada)
        if request.form.get('is_final_export') == 'true':
            return processar_exportacao_final(request.form)

        data_inicio_str = request.form.get('data_inicio')
        data_fim_str = request.form.get('data_fim')
        action = request.form.get('action')
        ciclo_id_str = request.form.get('ciclo_id')
        ciclo_id = int(ciclo_id_str) if (ciclo_id_str and ciclo_id_str.isdigit()) else None

        try:
            data_inicio = datetime.strptime(data_inicio_str, '%Y-%m-%d').date()
            data_fim = datetime.strptime(data_fim_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            flash('Formato de data inválido. Use AAAA-MM-DD.', 'danger')
            return redirect(url_for('relatorios.gerar_relatorio_horas_aula', tipo=report_type))

        mode_rr = None
        if report_type == 'mensal':
            mode_rr = 'exclude_rr'
        elif report_type == 'efetivo_rr':
            mode_rr = 'only_rr'

        instrutor_ids_filter = None
        if report_type == 'por_instrutor':
            instrutor_ids_raw = request.form.getlist('instrutor_ids')
            instrutor_ids_filter = [int(_id) for _id in instrutor_ids_raw if _id.isdigit()]

        dados_relatorio = RelatorioService.get_horas_aula_por_instrutor(
            data_inicio, data_fim, mode_rr, instrutor_ids_filter, ciclo_id
        )

        meses = ("Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
                 "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro")
        
        contexto = {
            "dados": dados_relatorio,
            "data_inicio": data_inicio_str,
            "data_fim": data_fim_str,
            "nome_mes_ano": f"{meses[data_inicio.month - 1]} de {data_inicio.year}",
            "data_assinatura": f"{data_fim.day} de {meses[data_fim.month - 1]} de {data_fim.year}",
            "titulo_curso": (request.form.get('curso_nome') or report_defaults["curso_nome"]),
            "opm": (request.form.get('opm') or report_defaults["opm"]),
            "escola_nome": (request.form.get('escola_nome') or report_defaults["escola_nome"]),
            "cidade": (request.form.get('cidade') or report_defaults["cidade"]),
            "comandante_nome": request.form.get('comandante_nome'),
            "comandante_funcao": (request.form.get('comandante_funcao') or report_defaults["comandante_funcao"]),
            "auxiliar_nome": request.form.get('auxiliar_nome'),
            "auxiliar_funcao": (request.form.get('auxiliar_funcao') or report_defaults["auxiliar_funcao"]),
            "telefone": (request.form.get('telefone') or report_defaults["telefone"]),
            "valor_hora_aula": SiteConfigService.get_valor_hora_aula(),
            "report_type": report_type,
            "ciclo_id": ciclo_id_str or ""
        }

        # Preview gera direto com o HTML do PDF
        if action == 'preview':
            return render_template('relatorios/pdf_template.html', **contexto)
        
        # Download (XLSX ou PDF) vai para a tela de EDIÇÃO
        return render_template('relatorios/editar_mapa_horas.html', **contexto)

    from flask import session
    from ..models.ciclo import Ciclo
    from sqlalchemy import select, or_

    active_edicao = session.get('active_edicao_id')
    ciclos = db.session.scalars(
        select(Ciclo).where(
            Ciclo.school_id == school_id,
            or_(Ciclo.edicao_id == active_edicao, Ciclo.edicao_id == None)
        ).order_by(Ciclo.nome)
    ).all()

    return render_template(
        'relatorios/horas_aula_form.html',
        tipo_relatorio=tipo_relatorio_titulo,
        todos_instrutores=todos_instrutores,
        form_defaults=report_defaults,
        ciclos=ciclos,
    )


def processar_exportacao_final(form_data):
    """Lógica para receber os dados editados e gerar os arquivos finais"""
    try:
        # Função de segurança para impedir que strings vazias ou com vírgula quebrem a exportação
        def safe_float(val):
            if not val:
                return 0.0
            try:
                return float(str(val).replace(',', '.'))
            except ValueError:
                return 0.0

        action = form_data.get('action')
        dados_editados = []
        instrutor_indices = form_data.getlist('instrutor_index')
        
        for idx in instrutor_indices:
            instrutor_item = {
                "nome": str(form_data.get(f"instrutor_nome_{idx}") or "").strip() or "SEM NOME",
                "posto": str(form_data.get(f"instrutor_posto_{idx}") or "").strip(),
                "matricula": str(form_data.get(f"instrutor_matricula_{idx}") or "").strip() or "S/M",
                "identidade": str(form_data.get(f"instrutor_identidade_{idx}") or "").strip(),
                "cpf": str(form_data.get(f"instrutor_cpf_{idx}") or "").strip(),
                "disciplinas": []
            }
            
            disc_indices = form_data.getlist(f"disciplina_index_{idx}")
            for d_idx in disc_indices:
                instrutor_item["disciplinas"].append({
                    "nome_disciplina": str(form_data.get(f"disc_nome_{idx}_{d_idx}") or "").strip(),
                    "ch_anterior": safe_float(form_data.get(f"ch_anterior_{idx}_{d_idx}")),
                    "ch_mes": safe_float(form_data.get(f"ch_mes_{idx}_{d_idx}")),
                    "ch_total_disciplina": safe_float(form_data.get(f"ch_total_{idx}_{d_idx}"))
                })
            dados_editados.append(instrutor_item)

        # Ordena em Python de forma segura e garantida por matrícula
        dados_editados.sort(key=lambda x: str(x.get("matricula") or ""))

        data_fim_str = form_data.get('data_fim')
        try:
            data_fim = datetime.strptime(data_fim_str, '%Y-%m-%d').date() if data_fim_str else datetime.now().date()
        except (ValueError, TypeError):
            data_fim = datetime.now().date()

        valor_hora_aula = safe_float(SiteConfigService.get_valor_hora_aula())

        contexto = {
            "dados": dados_editados,
            "titulo_curso": str(form_data.get('titulo_curso') or ""),
            "nome_mes_ano": str(form_data.get('nome_mes_ano') or ""),
            "data_assinatura": f"{data_fim.day} de {form_data.get('nome_mes_ano') or ''}",
            "comandante_nome": str(form_data.get('comandante_nome') or ""),
            "comandante_funcao": str(form_data.get('comandante_funcao') or ""),
            "auxiliar_nome": str(form_data.get('auxiliar_nome') or ""),
            "auxiliar_funcao": str(form_data.get('auxiliar_funcao') or ""),
            "valor_hora_aula": valor_hora_aula,
            "opm": str(form_data.get('opm') or ""),
            "telefone": str(form_data.get('telefone') or ""),
            "cidade": str(form_data.get('cidade') or ""),
            "escola_nome": str(form_data.get('escola_nome') or ""),
        }

        if action == 'download':
            rendered_html = render_template('relatorios/pdf_template.html', **contexto)
            
            # Cria o Job na fila
            pdf_name = _build_filename('relatorio_horas_aula', contexto.get("nome_mes_ano"), 'pdf')
            job_id = str(uuid.uuid4())
            job = BackgroundJob(
                id=job_id,
                task_type='generate_pdf',
                payload=rendered_html,
                meta_data=json.dumps({"filename": pdf_name}),
                user_id=current_user.id
            )
            db.session.add(job)
            db.session.commit()
            
            # Retorna JSON para a tela indicando sucesso e o ID do job
            return jsonify({'success': True, 'job_id': job_id})

        elif action == 'download_xlsx':
            try:
                xlsx_bytes = gerar_mapa_gratificacao_xlsx(
                    dados=dados_editados, 
                    valor_hora_aula=valor_hora_aula, 
                    nome_mes_ano=contexto["nome_mes_ano"] or '',
                    titulo_curso=contexto["titulo_curso"] or '',
                    opm_nome=contexto["opm"] or '',
                    escola_nome=contexto["escola_nome"] or '',
                    data_emissao=data_fim,
                    telefone=contexto["telefone"] or '',
                    auxiliar_nome=contexto["auxiliar_nome"] or '',
                    comandante_nome=contexto["comandante_nome"] or '',
                    digitador_nome=(getattr(current_user, 'nome_completo', None) or current_user.username),
                    auxiliar_funcao=contexto["auxiliar_funcao"] or '',
                    comandante_funcao=contexto["comandante_funcao"] or '',
                    data_fim=data_fim,
                    cidade_assinatura=contexto["cidade"] or 'Santa Maria'
                )
            except Exception as e:
                flash(f'Erro ao gerar XLSX: {str(e)}', 'danger')
                return redirect(url_for('relatorios.index'))

            xlsx_name = _build_filename('relatorio_horas_aula', contexto.get("nome_mes_ano"), 'xlsx')
            return send_file(io.BytesIO(xlsx_bytes), as_attachment=True, download_name=xlsx_name, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

        return render_template('relatorios/editar_mapa_horas.html', **contexto)
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

    return redirect(url_for('relatorios.index'))