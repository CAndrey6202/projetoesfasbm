
with open("backend/controllers/justica_controller.py", "r", encoding="utf-8") as f:
    text = f.read()
text = text.replace(
    "except Exception as e:\n        db.session.rollback(); flash(\"Erro ao salvar avalia\xc3\xa7\xc3\xa3o.\", \"danger\")",
    "except Exception as e:\n        db.session.rollback(); logger.error(f\"Erro ao salvar FADA: {e}\"); flash(f\"Erro ao salvar avalia\xc3\xa7\xc3\xa3o: {e}\", \"danger\")"
)
with open("backend/controllers/justica_controller.py", "w", encoding="utf-8") as f:
    f.write(text)

