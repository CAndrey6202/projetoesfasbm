
with open("backend/controllers/justica_controller.py", "r", encoding="utf-8") as f:
    text = f.read()

text = text.replace(
    "      pres_id = int(pres_id) if pres_id and pres_id.isdigit() else None\n      m1_id = int(m1_id) if m1_id and m1_id.isdigit() else None\n      m2_id = int(m2_id) if m2_id and m2_id.isdigit() else None",
    "    pres_id = int(pres_id) if pres_id and pres_id.isdigit() else None\n    m1_id = int(m1_id) if m1_id and m1_id.isdigit() else None\n    m2_id = int(m2_id) if m2_id and m2_id.isdigit() else None"
)

with open("backend/controllers/justica_controller.py", "w", encoding="utf-8") as f:
    f.write(text)

