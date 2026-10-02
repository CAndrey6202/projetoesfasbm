
from backend.app import create_app
from backend.models.database import db
from backend.models.user import User
import os

os.environ["DATABASE_URL"] = "sqlite:///local.db"
os.environ["FIREBASE_CREDENTIALS_JSON"] = "{}"

try:
    app = create_app()
    with app.test_request_context("/justica-e-disciplina/fada/salvar", method="POST", data={
        "aluno_id": "1",
        "notas[]": ["8.00"] * 18,
        "presidente_id": "2",
        "membro1_id": "3",
        "membro2_id": "4"
    }):
        from backend.controllers.justica_controller import salvar_fada
        from flask_login import login_user
        with app.app_context():
            # Create dummy DB if needed
            db.create_all()
            user = User(email="test@test.com", password_hash="123", role="ADMIN")
            db.session.add(user)
            db.session.commit()
            login_user(user)
            salvar_fada()
except Exception as e:
    import traceback
    traceback.print_exc()

