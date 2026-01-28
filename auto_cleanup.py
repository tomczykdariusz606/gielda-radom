import os
from datetime import datetime, timedelta
from app import app, db, Car, CarImage

def run_maintenance():
    """Główna funkcja sprzątająca serwer."""
    with app.app_context():
        # Ustalamy granicę 30 dni
        limit_daty = datetime.utcnow() - timedelta(days=30)
        
        # Szukamy wygasłych ogłoszeń
        expired_cars = Car.query.filter(Car.data_dodania < limit_daty).all()
        
        if not expired_cars:
            print(f"[{datetime.now()}] Brak ogłoszeń do usunięcia.")
            return

        deleted_count = 0
        files_removed = 0

        for car in expired_cars:
            # 1. Usuwanie plików zdjęć z dysku
            for img_record in car.images:
                # Wyciągamy nazwę pliku ze ścieżki (np. /static/uploads/foto.webp -> foto.webp)
                filename = img_record.image_path.split('/')[-1]
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                
                if os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                        files_removed += 1
                    except Exception as e:
                        print(f"Błąd usuwania pliku {filename}: {e}")

            # 2. Usuwanie rekordu z bazy danych
            try:
                db.session.delete(car)
                deleted_count += 1
            except Exception as e:
                print(f"Błąd usuwania rekordu ID {car.id}: {e}")

        db.session.commit()
        print(f"[{datetime.now()}] SUKCES: Usunięto {deleted_count} ogłoszeń i {files_removed} plików zdjęć.")

if __name__ == "__main__":
    run_maintenance()
