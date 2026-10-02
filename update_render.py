import re

with open("templates/justica/fada_formulario.html", "r", encoding="utf-8") as f:
    text = f.read()

text = text.replace("renderHash('box_ass_pres', dadosFada?.hash_pres);", "renderHash('box_ass_pres', dadosFada?.hash_pres, dadosFada?.ass_img_pres);")
text = text.replace("renderHash('box_ass_m1', dadosFada?.hash_m1);", "renderHash('box_ass_m1', dadosFada?.hash_m1, dadosFada?.ass_img_m1);")
text = text.replace("renderHash('box_ass_m2', dadosFada?.hash_m2);", "renderHash('box_ass_m2', dadosFada?.hash_m2, dadosFada?.ass_img_m2);")

old_render = """function renderHash(elId, hash) {
    if(hash) document.getElementById(elId).innerHTML = `<span class="text-success fw-bold" style="font-size: 0.6rem;">ASSINADO DIGITALMENTE<br>${hash.substring(0,10)}...</span>`;
    else document.getElementById(elId).innerHTML = "";
}"""

new_render = """function renderHash(elId, hash, imgPath) {
    const el = document.getElementById(elId);
    if(imgPath && hash) {
        el.innerHTML = `<img src="/static/${imgPath}" style="max-height:40px;"><br><span style="font-size: 0.5rem; color: #aaa;">${hash.substring(0,10)}</span>`;
    } else if(hash) {
        el.innerHTML = `<span class="text-success fw-bold" style="font-size: 0.6rem;">ASSINADO DIGITALMENTE<br>${hash.substring(0,10)}...</span>`;
    } else {
        el.innerHTML = "";
    }
}"""

text = text.replace(old_render, new_render)

with open("templates/justica/fada_formulario.html", "w", encoding="utf-8") as f:
    f.write(text)

print("Updated renderHash")
