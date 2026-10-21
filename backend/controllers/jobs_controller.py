from flask import Blueprint, jsonify, send_file, abort, current_app
from flask_login import login_required, current_user
from datetime import datetime
import os
import json
import logging

from backend.models.database import db
from backend.models.background_job import BackgroundJob

logger = logging.getLogger(__name__)
jobs_bp = Blueprint('jobs', __name__, url_prefix='/api/jobs')

def _process_pdf_inline(job_id, payload_html, meta_raw):
    """Fallback síncrono para gerar o PDF caso o worker em background ainda não tenha processado."""
    import re
    from weasyprint import HTML
    project_root = os.path.abspath(os.path.join(current_app.root_path, '..'))
    downloads_dir = os.path.join(project_root, 'static', 'downloads')
    os.makedirs(downloads_dir, exist_ok=True)

    filename = f"document_{job_id}.pdf"
    file_path = os.path.join(downloads_dir, filename)

    proj_uri = ('/' + project_root.replace('\\', '/')) if os.name == 'nt' else project_root
    html_fixed = re.sub(r'https?://[^/]+', f'file://{proj_uri}', payload_html)

    HTML(string=html_fixed, base_url=project_root).write_pdf(file_path)

    if meta_raw:
        try:
            meta = json.loads(meta_raw)
            anexos = meta.get('anexos', [])
            if anexos:
                from pypdf import PdfWriter
                merger = PdfWriter()
                merger.append(file_path)
                for anexo in anexos:
                    if os.path.exists(anexo) and anexo.lower().endswith('.pdf'):
                        merger.append(anexo)
                merger.write(file_path)
                merger.close()
        except Exception as e:
            logger.warning(f"Aviso ao mesclar anexos no job {job_id}: {e}")

    return file_path

@jobs_bp.route('/<string:job_id>/status', methods=['GET'])
@login_required
def get_job_status(job_id):
    job = db.session.get(BackgroundJob, job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
        
    # Security: Ensure the user requesting the job is the one who created it (or admin)
    if job.user_id != current_user.id and not (current_user.is_super_admin or current_user.is_admin_escola):
        return jsonify({'error': 'Acesso negado'}), 403

    # Fallback imediato: se o job de PDF ainda estiver 'pending', processa na hora para nunca travar na tela
    if job.status == 'pending' and job.task_type == 'generate_pdf' and job.payload:
        try:
            payload_html = job.payload
            meta_raw = job.meta_data
            job.status = 'processing'
            job.started_at = datetime.utcnow()
            db.session.commit()

            result_path = _process_pdf_inline(job_id, payload_html, meta_raw)
            job.result_path = result_path
            job.status = 'completed'
            job.finished_at = datetime.utcnow()
            job.payload = None
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao gerar PDF inline para job {job_id}: {e}")
            job = db.session.get(BackgroundJob, job_id)
            if job:
                job.status = 'failed'
                job.error_message = str(e)
                job.finished_at = datetime.utcnow()
                db.session.commit()

    return jsonify(job.to_dict())

@jobs_bp.route('/<string:job_id>/download', methods=['GET'])
@login_required
def download_job_result(job_id):
    job = db.session.get(BackgroundJob, job_id)
    if not job:
        return abort(404, description="Job not found")
        
    if job.user_id != current_user.id and not (current_user.is_super_admin or current_user.is_admin_escola):
        return abort(403, description="Acesso negado")

    if job.status != 'completed' or not job.result_path:
        return abort(400, description="Job not completed yet or missing result")

    if not os.path.exists(job.result_path):
        return abort(404, description="File not found on disk")

    download_filename = os.path.basename(job.result_path)
    if job.meta_data:
        try:
            meta = json.loads(job.meta_data)
            if isinstance(meta, dict) and meta.get('filename'):
                download_filename = meta['filename']
        except Exception:
            pass

    mimetype = 'application/zip' if download_filename.endswith('.zip') else 'application/pdf'

    return send_file(
        job.result_path,
        as_attachment=True,
        download_name=download_filename,
        mimetype=mimetype
    )

@jobs_bp.route('/debug/worker-log', methods=['GET'])
def debug_worker_log():
    try:
        log_path = '/opt/render/project/src/worker.log'
        if not os.path.exists(log_path):
            return "O arquivo worker.log não existe ainda."
        with open(log_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return f"<pre>{content}</pre>"
    except Exception as e:
        return f"Erro ao ler log: {e}"
