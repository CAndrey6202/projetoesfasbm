
with open("backend/controllers/justica_controller.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if "pres_id = request.form.get(\"presidente_id\")" in line or "pres_id = request.form.get('presidente_id')" in line:
        if "pres_id = int" not in lines[i+3]:
            lines.insert(i+3, "      pres_id = int(pres_id) if pres_id and pres_id.isdigit() else None\n")
            lines.insert(i+4, "      m1_id = int(m1_id) if m1_id and m1_id.isdigit() else None\n")
            lines.insert(i+5, "      m2_id = int(m2_id) if m2_id and m2_id.isdigit() else None\n")
        break

with open("backend/controllers/justica_controller.py", "w", encoding="utf-8") as f:
    f.writelines(lines)

