
with open("templates/justica/fada_formulario.html", "r", encoding="utf-8") as f:
    text = f.read()

old_btn = """<button type="submit" class="btn btn-primary fw-bold px-4" id="btn-salvar-fada" onclick="document.getElementById('fadaActionButtons').style.setProperty('display', 'none', 'important'); document.getElementById('loadingContainerFada').style.setProperty('display', 'flex', 'important');">Salvar Rascunho</button>"""

new_btn = """<button type="submit" class="btn btn-primary fw-bold px-4" id="btn-salvar-fada" onclick="if(document.getElementById('formFada').checkValidity()) { document.getElementById('fadaActionButtons').style.setProperty('display', 'none', 'important'); document.getElementById('loadingContainerFada').style.setProperty('display', 'flex', 'important'); }">Salvar Rascunho</button>"""

text = text.replace(old_btn, new_btn)

with open("templates/justica/fada_formulario.html", "w", encoding="utf-8") as f:
    f.write(text)

