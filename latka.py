from app import app, db
from sqlalchemy import text

def napraw_dane():
    with app.app_context():
        # Ustawiamy 0 tam, gdzie są puste wartości, aby formatowanie w HTML nie wywalało błędu
        db.session.execute(text('UPDATE car SET przebieg = 0 WHERE przebieg IS NULL'))
        db.session.execute(text('UPDATE car SET cena = 0 WHERE cena IS NULL'))
        db.session.commit()
        print("Sukces: Puste wartości zostały zastąpione zerami.")

if __name__ == "__main__":
    napraw_dane()
