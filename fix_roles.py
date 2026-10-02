
import re
with open("backend/controllers/justica_controller.py", "r", encoding="utf-8") as f:
    text = f.read()

pattern = re.compile(r"    if fada\.presidente_id == uid:.*?return redirect\(url_for\('justica\.fada_boletim'\)\)", re.DOTALL)
match = pattern.search(text)
if match:
    new_logic = """    assinou_algum = False
    if fada.presidente_id == uid and not fada.hash_pres:
        fada.hash_pres = hash_assinatura; fada.data_ass_pres = agora
        assinou_algum = True
    if fada.membro1_id == uid and not fada.hash_m1:
        fada.hash_m1 = hash_assinatura; fada.data_ass_m1 = agora
        assinou_algum = True
    if fada.membro2_id == uid and not fada.hash_m2:
        fada.hash_m2 = hash_assinatura; fada.data_ass_m2 = agora
        assinou_algum = True

    if not assinou_algum:
        flash("Voc\u00ea j\u00e1 assinou ou n\u00e3o faz parte da comiss\u00e3o.", "warning")
        return redirect(url_for("justica.fada_boletim"))"""
    
    text = text.replace(match.group(0), new_logic)
    with open("backend/controllers/justica_controller.py", "w", encoding="utf-8") as f:
        f.write(text)
    print("Replaced")
else:
    print("Not found")

