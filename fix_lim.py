
with open("backend/services/justica_service.py", "r", encoding="utf-8") as f:
    text = f.read()

old_lim = """                    try:
                        idx = int(attr_idx)
                        limites[idx] -= float(p.pontos)
                    except ValueError:"""

new_lim = """                    try:
                        idx = int(attr_idx)
                        limites[idx] -= float(p.pontos or 0.0)
                    except (ValueError, TypeError):"""

if old_lim in text:
    text = text.replace(old_lim, new_lim)
    with open("backend/services/justica_service.py", "w", encoding="utf-8") as f:
        f.write(text)
    print("Replaced limites")
else:
    print("Not found")

