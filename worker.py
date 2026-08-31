import os
import time
import logging
from datetime import datetime, timedelta
from weasyprint import HTML

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

from backend.app import create_app
from backend.models.database import db
from backend.models.background_job import BackgroundJob

app = create_app()

import json
import zipfile
import shutil
from flask import render_template

def process_certificates_zip(job):
    """Gera um PDF por aluno e empacota em um ZIP."""
    downloads_dir = os.path.join(app.root_path, '..', 'static', 'downloads')
    os.makedirs(downloads_dir, exist_ok=True)
    
    # Criar diretorio temporario para os PDFs
    temp_dir = os.path.join(downloads_dir, f"temp_{job.id}")
    os.makedirs(temp_dir, exist_ok=True)
    
    try:
        data = json.loads(job.payload)
        alunos = data.get('alunos', [])
        dados = data.get('dados', {})
        disciplinas = data.get('disciplinas', [])
        
        pdf_files = []
        for aluno in alunos:
            # Substitui barras ou caracteres invalidos no nome do aluno para nome do arquivo
            safe_name = "".join([c for c in aluno if c.isalpha() or c.isdigit() or c==' ']).rstrip()
            if not safe_name:
                safe_name = "aluno_desconhecido"
                
            pdf_filename = f"Certificado - {safe_name}.pdf"
            pdf_path = os.path.join(temp_dir, pdf_filename)
            
            with app.test_request_context():
                rendered_html = render_template(
                    'ferramentas/certificados_pdf.html',
                    dados=dados,
                    disciplinas=disciplinas,
                    alunos=[aluno]
                )
            
            logging.info(f"Gerando PDF para {aluno}")
            HTML(string=rendered_html).write_pdf(pdf_path)
            pdf_files.append((pdf_filename, pdf_path))
            
        # Criar o ZIP
        zip_filename = f"certificados_{job.id}.zip"
        zip_path = os.path.join(downloads_dir, zip_filename)
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for pdf_name, p_path in pdf_files:
                zipf.write(p_path, arcname=pdf_name)
                
        logging.info(f"ZIP gerado com sucesso em {zip_path}")
        return zip_path
        
    finally:
        # Limpar diretorio temporario
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

def process_pdf_job(job):
    """Gera o PDF usando Weasyprint a partir do HTML salvo no payload."""
    downloads_dir = os.path.join(app.root_path, '..', 'static', 'downloads')
    os.makedirs(downloads_dir, exist_ok=True)
    
    filename = f"document_{job.id}.pdf"
    file_path = os.path.join(downloads_dir, filename)
    
    logging.info(f"Gerando PDF para job {job.id} em {file_path}")
    HTML(string=job.payload).write_pdf(file_path)
    
    # Verifica se há anexos para mesclar (ex: fundamentação do recurso)
    if job.meta_data:
        import json
        try:
            meta = json.loads(job.meta_data)
            anexos = meta.get('anexos', [])
            if anexos:
                try:
                    from pypdf import PdfWriter, PdfReader
                    merger = PdfWriter()
                    merger.append(file_path) # PDF principal gerado
                    for anexo in anexos:
                        if os.path.exists(anexo) and anexo.lower().endswith('.pdf'):
                            logging.info(f"Mesclando anexo {anexo} ao job {job.id}")
                            merger.append(anexo)
                    # Sobrescreve o arquivo com a versão mesclada
                    merger.write(file_path)
                    merger.close()
                except ImportError:
                    logging.warning("pypdf não instalado. Não foi possível mesclar anexos.")
                except Exception as e:
                    logging.error(f"Erro ao mesclar anexos no job {job.id}: {e}")
        except json.JSONDecodeError:
            pass

    return file_path

def cleanup_old_jobs():
    """Remove jobs e arquivos PDF mais velhos que 24 horas."""
    cutoff_time = datetime.utcnow() - timedelta(hours=24)
    old_jobs = BackgroundJob.query.filter(BackgroundJob.created_at < cutoff_time).all()
    
    for job in old_jobs:
        if job.result_path and os.path.exists(job.result_path):
            try:
                os.remove(job.result_path)
            except Exception as e:
                logging.error(f"Erro ao deletar arquivo antigo {job.result_path}: {e}")
        db.session.delete(job)
        
    if old_jobs:
        try:
            db.session.commit()
            logging.info(f"Limpeza de rotina: {len(old_jobs)} jobs antigos removidos.")
        except Exception as e:
            db.session.rollback()
            logging.error(f"Erro ao limpar jobs antigos: {e}")

def run_worker():
    """Loop principal do worker."""
    logging.info("Iniciando Background Worker...")
    
    last_cleanup = datetime.utcnow()

    while True:
        # Colocar o context manager DENTRO do loop previne memory leaks do SQLAlchemy Identity Map.
        with app.app_context():
            # Executa a limpeza a cada 1 hora
            if (datetime.utcnow() - last_cleanup).total_seconds() > 3600:
                cleanup_old_jobs()
                last_cleanup = datetime.utcnow()

            try:
                # Busca o primeiro job pendente (FIFO)
                job = BackgroundJob.query.filter_by(status='pending').order_by(BackgroundJob.created_at.asc()).first()
                
                if job:
                    # Marca como processando
                    job.status = 'processing'
                    job.started_at = datetime.utcnow()
                    db.session.commit()
                    
                    logging.info(f"Processando Job {job.id} do tipo {job.task_type}")
                    
                    try:
                        if job.task_type == 'generate_pdf':
                            result_path = process_pdf_job(job)
                            job.result_path = result_path
                        elif job.task_type == 'generate_certificates_zip':
                            result_path = process_certificates_zip(job)
                            job.result_path = result_path
                        else:
                            raise ValueError(f"Task type desconhecido: {job.task_type}")
                            
                        # Finaliza com sucesso
                        job.status = 'completed'
                        job.finished_at = datetime.utcnow()
                        job.payload = None 
                        
                        logging.info(f"Job {job.id} concluído com sucesso!")
                        
                    except Exception as e:
                        job.status = 'failed'
                        job.error_message = str(e)
                        job.finished_at = datetime.utcnow()
                        logging.error(f"Job {job.id} falhou: {str(e)}")
                    
                    # Salva o resultado
                    db.session.commit()
                    
                else:
                    # Se não tem job, dorme um pouco
                    time.sleep(2)
            except Exception as e:
                logging.error(f"Erro no loop principal do worker: {e}")
                db.session.rollback()
                time.sleep(5) # Evita spam de logs se o banco cair

if __name__ == '__main__':
    run_worker()
