import os
from datetime import datetime, timedelta, timezone
from app import app, db, Car

def run_maintenance():
    """Główna funkcja sprzątająca serwer z wygasłych ogłoszeń i osieroconych plików."""
    with app.app_context():
        # 1. Używamy timezone-aware datetime (nowoczesny standard)
        # To zapobiega błędom, jeśli serwer i baza mają inne strefy czasowe
        limit_daty = datetime.now(timezone.utc) - timedelta(days=30)

        # 2. Pobieramy wygasłe ogłoszenia
        expired_cars = Car.query.filter(Car.data_dodania < limit_daty).all()

        if not expired_cars:
            print(f"[{datetime.now()}] Skanowanie zakończone: Brak ogłoszeń do usunięcia.")
            return

        deleted_count = 0
        files_removed = 0

        print(f"[{datetime.now()}] Rozpoczynam czyszczenie {len(expired_cars)} ogłoszeń...")

        for car in expired_cars:
            try:
                # 3. Usuwanie plików powiązanych z ogłoszeniem
                # Zakładamy, że masz relację do zdjęć (car.images)
                if hasattr(car, 'images'):
                    for img_record in car.images:
                        # Używamy os.path.basename dla bezpieczeństwa między systemami
                        filename = os.path.basename(img_record.image_path)
                        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)

                        if os.path.exists(filepath):
                            os.remove(filepath)
                            files_removed += 1
                
                # Jeśli Twoje zdjęcia są zapisane bezpośrednio w polu car.img:
                elif car.img and not car.img.startswith('http'):
                    filename = os.path.basename(car.img)
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    if os.path.exists(filepath):
                        os.remove(filepath)
                        files_removed += 1

                # 4. Usuwanie rekordu z bazy
                # Dzięki Twojej kaskadzie (cascade="all, delete-orphan"), 
                # polubienia i inne relacje zostaną usunięte automatycznie!
                db.session.delete(car)
                deleted_count += 1

            except Exception as e:
                print(f"⚠️ Błąd podczas przetwarzania ogłoszenia ID {car.id}: {str(e)}")
                db.session.rollback() # Wycofujemy zmiany dla tego konkretnego rekordu przy błędzie

        # 5. Finalne zatwierdzenie zmian
        try:
            db.session.commit()
            print(f"✅ SUKCES: Usunięto {deleted_count} ogłoszeń i {files_removed} plików.")
        except Exception as e:
            print(f"❌ Krytyczny błąd bazy danych: {e}")
            db.session.rollback()

if __name__ == "__main__":
    run_maintenance()
