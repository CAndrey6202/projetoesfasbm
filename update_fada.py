import re

with open('templates/justica/fada_formulario.html', 'r', encoding='utf-8') as f:
    text = f.read()

# The replacement for formAssinarMembro
replacement = """
            <div id="areaAssinaturaMembro" style="display: none;">
                <button type="button" class="btn btn-success btn-sm fw-bold shadow-sm" onclick="abrirCaixaAssinatura()">
                    <i class="fas fa-file-signature"></i> ASSINAR DIGITALMENTE
                </button>
            </div>
            
            <div id="boxAssinatura" class="position-fixed top-50 start-50 translate-middle bg-white border rounded shadow-lg p-3 z-3" style="display: none; width: 90%; max-width: 500px;">
                <div class="d-flex justify-content-between align-items-center border-bottom pb-2 mb-3">
                    <h5 class="mb-0"><i class="fas fa-pen-nib me-2"></i>Sua Assinatura</h5>
                    <button type="button" class="btn-close" onclick="fecharCaixaAssinatura()"></button>
                </div>
                
                <form id="formAssinarMembroReal" method="POST" enctype="multipart/form-data">
                    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                    <input type="hidden" name="tipo_assinatura" id="tipo_assinatura_membro" value="padrao">
                    <input type="hidden" name="assinatura_base64" id="assinatura_base64_membro" value="">
                    
                    <ul class="nav nav-pills mb-3" role="tablist">
                        {% if current_user.assinatura_padrao_path %}
                        <li class="nav-item">
                            <button class="nav-link active" data-bs-toggle="pill" data-bs-target="#tab-saved" type="button" onclick="document.getElementById('tipo_assinatura_membro').value='padrao'">
                                <i class="fas fa-save me-1"></i> Salva
                            </button>
                        </li>
                        {% endif %}
                        <li class="nav-item">
                            <button class="nav-link {% if not current_user.assinatura_padrao_path %}active{% endif %}" data-bs-toggle="pill" data-bs-target="#tab-draw" type="button" onclick="document.getElementById('tipo_assinatura_membro').value='canvas'; setTimeout(resizeCanvasFada, 100);">
                                <i class="fas fa-pen me-1"></i> Desenhar
                            </button>
                        </li>
                        <li class="nav-item">
                            <button class="nav-link" data-bs-toggle="pill" data-bs-target="#tab-upload" type="button" onclick="document.getElementById('tipo_assinatura_membro').value='upload'">
                                <i class="fas fa-upload me-1"></i> Upload
                            </button>
                        </li>
                    </ul>
                    
                    <div class="tab-content border rounded p-2 bg-light mb-3">
                        {% if current_user.assinatura_padrao_path %}
                        <div class="tab-pane fade show active text-center py-2" id="tab-saved">
                            <p class="text-muted small fw-bold mb-2">Sua assinatura salva será utilizada:</p>
                            <img src="{{ url_for('static', filename=current_user.assinatura_padrao_path) }}?v={{ range(1, 9999) | random }}" style="max-height: 80px;" class="border bg-white p-1">
                        </div>
                        {% endif %}
                        
                        <div class="tab-pane fade {% if not current_user.assinatura_padrao_path %}show active{% endif %} text-center" id="tab-draw">
                            <p class="small text-muted mb-1">Assine na caixa abaixo. <b>Isto atualizará sua assinatura padrão.</b></p>
                            <div class="border bg-white" style="height: 150px; position: relative;">
                                <canvas id="signaturePadFada" style="position: absolute; top: 0; left: 0; width: 100%; height: 100%;"></canvas>
                            </div>
                            <button type="button" class="btn btn-sm btn-outline-secondary mt-2" onclick="signaturePadFadaObj.clear()"><i class="fas fa-eraser"></i> Limpar</button>
                        </div>
                        
                        <div class="tab-pane fade" id="tab-upload">
                            <label class="form-label small fw-bold">Selecione uma imagem (PNG/JPG):</label>
                            <input class="form-control form-control-sm" type="file" name="assinatura_upload" accept="image/png, image/jpeg, image/jpg">
                            <p class="small text-muted mt-1"><b>Isto atualizará sua assinatura padrão.</b></p>
                        </div>
                    </div>
                    
                    <button type="submit" class="btn btn-success w-100 fw-bold" onclick="prepararAssinaturaFada(event)">
                        <i class="fas fa-check-double me-1"></i> Confirmar Assinatura
                    </button>
                </form>
            </div>
            <div id="backdropAssinatura" class="position-fixed top-0 start-0 w-100 h-100 bg-dark opacity-50 z-2" style="display: none;" onclick="fecharCaixaAssinatura()"></div>
"""

pattern = r'<form id="formAssinarMembro" method="POST" style="display: none;">\s*<input type="hidden" name="csrf_token" value="{{ csrf_token\(\) }}">\s*<button type="submit" class="btn btn-success btn-sm fw-bold shadow-sm">\s*<i class="fas fa-file-signature"></i> ASSINAR DIGITALMENTE\s*</button>\s*</form>'

text = re.sub(pattern, replacement, text)

# Update Javascript: "const formAss = document.getElementById('formAssinarMembro');"
text = text.replace(
    "const formAss = document.getElementById('formAssinarMembro');\n                formAss.style.display = 'inline-block';\n                formAss.action = `/justica-e-disciplina/fada/assinar-membro/${fadaId}`;",
    "const formAss = document.getElementById('areaAssinaturaMembro');\n                formAss.style.display = 'inline-block';\n                document.getElementById('formAssinarMembroReal').action = `/justica-e-disciplina/fada/assinar-membro/${fadaId}`;"
)

# Insert the script for SignaturePadFada
script_js = """
<script src="https://cdn.jsdelivr.net/npm/signature_pad@4.1.5/dist/signature_pad.umd.min.js"></script>
<script>
    var signaturePadFadaObj = null;

    function abrirCaixaAssinatura() {
        document.getElementById('boxAssinatura').style.display = 'block';
        document.getElementById('backdropAssinatura').style.display = 'block';
        
        if (!signaturePadFadaObj) {
            var canvas = document.getElementById('signaturePadFada');
            signaturePadFadaObj = new SignaturePad(canvas, { backgroundColor: 'rgb(255, 255, 255)' });
        }
        
        const isCanvasActive = document.getElementById('tipo_assinatura_membro').value === 'canvas';
        if (isCanvasActive) {
            setTimeout(resizeCanvasFada, 100);
        }
    }

    function fecharCaixaAssinatura() {
        document.getElementById('boxAssinatura').style.display = 'none';
        document.getElementById('backdropAssinatura').style.display = 'none';
    }

    function resizeCanvasFada() {
        var canvas = document.getElementById('signaturePadFada');
        var ratio =  Math.max(window.devicePixelRatio || 1, 1);
        canvas.width = canvas.offsetWidth * ratio;
        canvas.height = canvas.offsetHeight * ratio;
        canvas.getContext("2d").scale(ratio, ratio);
        if (signaturePadFadaObj) signaturePadFadaObj.clear(); 
    }

    window.addEventListener("resize", resizeCanvasFada);

    function prepararAssinaturaFada(e) {
        var tipo = document.getElementById('tipo_assinatura_membro').value;
        if (tipo === 'canvas') {
            if (signaturePadFadaObj.isEmpty()) {
                e.preventDefault();
                alert('Por favor, faça sua assinatura.');
                return;
            }
            document.getElementById('assinatura_base64_membro').value = document.getElementById('signaturePadFada').toDataURL('image/jpeg', 0.7);
        } 
        else if (tipo === 'upload') {
            var fileInput = document.querySelector('input[name="assinatura_upload"]');
            if (!fileInput.files.length) {
                e.preventDefault();
                alert('Selecione um arquivo.');
                return;
            }
        }
    }
</script>
"""

if "signaturePadFadaObj" not in text:
    text = text.replace("</body>", script_js + "\n</body>")

with open('templates/justica/fada_formulario.html', 'w', encoding='utf-8') as f:
    f.write(text)

print('Updated fada_formulario.html')
