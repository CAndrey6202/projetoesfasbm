import re

with open('backend/controllers/justica_controller.py', 'r', encoding='utf-8') as f:
    text = f.read()

pattern = r"(@justica_bp\.route\('/fada/assinar-membro/<int:fada_id>', methods=\['POST'\]\)\s*@login_required\s*def assinar_fada_membro\(fada_id\):\s*fada = db\.session\.get\(FadaAvaliacao, fada_id\)\s*if not fada or fada\.status != 'COMISSAO':\s*flash\('Avalia.+? não encontrada ou não está na etapa da comissão\.', 'danger'\)\s*return redirect\(url_for\('justica\.fada_boletim'\)\)\s*uid = current_user\.id)"

replacement = r"""\1
    
    from flask import request, current_app
    import os, uuid, base64
    tipo_assinatura = request.form.get('tipo_assinatura', 'padrao')
    base_path = current_app.static_folder
    upload_folder = os.path.join(base_path, 'uploads', 'signatures')
    os.makedirs(upload_folder, exist_ok=True)

    if tipo_assinatura == 'padrao':
        if not current_user.assinatura_padrao_path:
            flash('Você não tem uma assinatura padrão salva.', 'warning')
            return redirect(url_for('justica.fada_boletim'))
    else:
        filename = f"padrao_{current_user.id}_{uuid.uuid4().hex[:8]}.jpg"
        filepath = os.path.join(upload_folder, filename)
        
        if tipo_assinatura == 'canvas':
            dados = request.form.get('assinatura_base64')
            if dados:
                encoded = dados.split(',', 1)[1] if ',' in dados else dados
                with open(filepath, 'wb') as f: f.write(base64.b64decode(encoded))
                current_user.assinatura_padrao_path = f"uploads/signatures/{filename}"
        elif tipo_assinatura == 'upload':
            file = request.files.get('assinatura_upload')
            if file and file.filename:
                file.save(filepath)
                current_user.assinatura_padrao_path = f"uploads/signatures/{filename}"
"""

new_text = re.sub(pattern, replacement, text)

with open('backend/controllers/justica_controller.py', 'w', encoding='utf-8') as f:
    f.write(new_text)

print('Updated justica_controller.py')
