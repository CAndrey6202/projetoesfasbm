import re

with open('templates/justica/index.html', 'r', encoding='utf-8') as f:
    text = f.read()

modal_html = '''
<!-- FADA Modal Wrapper -->
<div class="modal fade" id="fadaModal" tabindex="-1" aria-hidden="true">
    <div class="modal-dialog modal-xl modal-dialog-scrollable">
        <div class="modal-content" style="background-color: #f8f9fa;">
            <div class="modal-header bg-dark text-white">
                <h5 class="modal-title"><i class="fas fa-file-signature"></i> FADA Digital</h5>
                <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Close"></button>
            </div>
            <div class="modal-body p-0 py-4 d-flex justify-content-center">
                {% include 'justica/fada_formulario.html' %}
            </div>
        </div>
    </div>
</div>

<script>
function fecharFadaModal() {
    var myModalEl = document.getElementById('fadaModal');
    var modal = bootstrap.Modal.getInstance(myModalEl);
    if (modal) modal.hide();
}
</script>
'''

if 'id="fadaModal"' not in text:
    text = text.replace("{% include 'justica/fada_formulario.html' %}", modal_html)

with open('templates/justica/index.html', 'w', encoding='utf-8') as f:
    f.write(text)
