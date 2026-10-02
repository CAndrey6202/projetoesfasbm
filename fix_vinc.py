
with open("templates/justica/fada_lista_alunos.html", "r", encoding="utf-8") as f:
    text = f.read()

old_vinc = "'vinculos': item.fada_obj.vinculos if item.fada_obj else {}"
new_vinc = "'vinculos': {}"

if old_vinc in text:
    text = text.replace(old_vinc, new_vinc)
    with open("templates/justica/fada_lista_alunos.html", "w", encoding="utf-8") as f:
        f.write(text)
    print("Replaced vinculos")
else:
    print("Not found")

