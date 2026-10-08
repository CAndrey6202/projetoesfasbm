from flask import Blueprint, jsonify, send_file, abort
from flask_login import login_required, current_user
import os
import json

from backend.models.database import db
from backend.models.background_job import BackgroundJob

jobs_bp = Blueprint('jobs', __name__, url_prefix='/api/jobs')

@jobs_bp.route('/<string:job_id>/status', methods=['GET'])
@login_required
def get_job_status(job_id):
    job = BackgroundJob.query.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
        
    # Security: Ensure the user requesting the job is the one who created it (or admin)
    if job.user_id != current_user.id and current_user.role not in ['super_admin', 'admin_escola']:
        return jsonify({'error': 'Acesso negado'}), 403

    return jsonify(job.to_dict())

@jobs_bp.route('/<string:job_id>/download', methods=['GET'])
@login_required
def download_job_result(job_id):
    job = BackgroundJob.query.get(job_id)
    if not job:
        return abort(404, description="Job not found")
        
    if job.user_id != current_user.id and current_user.role not in ['super_admin', 'admin_escola']:
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
