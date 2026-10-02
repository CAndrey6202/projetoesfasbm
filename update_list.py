import re

with open("templates/justica/fada_lista_alunos.html", "r", encoding="utf-8") as f:
    text = f.read()

pattern = r"'hash_pres': item\.fada_obj\.hash_pres if item\.fada_obj else '',"
replacement = r"""'hash_pres': item.fada_obj.hash_pres if item.fada_obj else '',
                          'ass_img_pres': item.fada_obj.presidente.assinatura_padrao_path if (item.fada_obj and item.fada_obj.presidente) else '',
                          'ass_img_m1': item.fada_obj.membro1.assinatura_padrao_path if (item.fada_obj and item.fada_obj.membro1) else '',
                          'ass_img_m2': item.fada_obj.membro2.assinatura_padrao_path if (item.fada_obj and item.fada_obj.membro2) else '','""\"

new_text = re.sub(pattern, replacement, text)

# Remove the trailing '""\"' that was accidentally left in the replacement
new_text = new_text.replace("''", "''").replace(",'\"\"\"", ",")

with open("templates/justica/fada_lista_alunos.html", "w", encoding="utf-8") as f:
    f.write(new_text)

print("Updated fada_lista_alunos.html")
