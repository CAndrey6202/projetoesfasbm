from backend.app import create_app
from backend.extensions import db
from backend.models.user import User

app = create_app()
with app.app_context():
    u = db.session.execute(db.select(User).filter_by(matricula='4522788')).scalar_one_or_none()
    if u:
        print(f"Name: {u.nome_completo}")
        print(f"Global Role: {repr(u.role)}")
        print(f"Aluno Profile: {u.aluno_profile is not None}")
        print(f"Is Chefe Turma: {u.is_chefe_turma}")
    else:
        print("User not found")