
from backend.app import create_app
from backend.models.database import db
from backend.models.user import User

app = create_app()
with app.app_context():
    admin = db.session.query(User).filter_by(email="admin@admin.com").first()
    print("Admin:", admin)

