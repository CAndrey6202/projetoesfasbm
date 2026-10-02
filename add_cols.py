
from backend.app import create_app
from backend.extensions import db
from sqlalchemy import text

app = create_app()
with app.app_context():
    try:
        db.session.execute(text("ALTER TABLE fada_avaliacao ADD COLUMN ass_pres_path VARCHAR(255)"))
        db.session.execute(text("ALTER TABLE fada_avaliacao ADD COLUMN ass_m1_path VARCHAR(255)"))
        db.session.execute(text("ALTER TABLE fada_avaliacao ADD COLUMN ass_m2_path VARCHAR(255)"))
        db.session.commit()
        print("Columns added successfully!")
    except Exception as e:
        print(f"Error: {e}")

