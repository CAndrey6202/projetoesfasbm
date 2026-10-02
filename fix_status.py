
with open("templates/justica/fada_lista_alunos.html", "r", encoding="utf-8") as f:
    text = f.read()

text = text.replace("item.fada_obj.etapa_atual", "item.fada_obj.status")

with open("templates/justica/fada_lista_alunos.html", "w", encoding="utf-8") as f:
    f.write(text)
print("Replaced etapa_atual with status")

