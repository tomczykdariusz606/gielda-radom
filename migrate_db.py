import sqlite3
import os

def migrate():
    # Ścieżka do Twojej bazy (zmień nazwę jeśli inna)
    db_path = "gielda.db" 
    
    if not os.path.exists(db_path):
        print(f"Błąd: Plik {db_path} nie istnieje!")
        return

    print(f"Rozpoczynam migrację bazy: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # --- AKTUALIZACJA TABELI USER ---
        # Sprawdzamy czy kolumna email istnieje
        cursor.execute("PRAGMA table_info(user)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'email' not in columns:
            cursor.execute("ALTER TABLE user ADD COLUMN email VARCHAR(120)")
            print("  [User] Dodano kolumnę 'email'.")
            # Wypełnienie tymczasowymi danymi, by nie było NULL
            cursor.execute("UPDATE user SET email = username || '@giełda-radom.pl' WHERE email IS NULL")
        
        # --- AKTUALIZACJA TABELI CAR ---
        cursor.execute("PRAGMA table_info(car)")
        columns = [column[1] for column in cursor.fetchall()]

        new_car_columns = [
            ("ai_label", "VARCHAR(100)"),
            ("ai_valuation_data", "TEXT"),
            ("przebieg", "INTEGER DEFAULT 0") # Ustawiamy domyślnie 0 zamiast NULL
        ]

        for col_name, col_type in new_car_columns:
            if col_name not in columns:
                cursor.execute(f"ALTER TABLE car ADD COLUMN {col_name} {col_type}")
                print(f"  [Car] Dodano kolumnę '{col_name}'.")

        conn.commit()
        print("\n--- MIGRACJA ZAKOŃCZONA SUKCESEM ---")
        print("Dane zostały zachowane, a struktura zaktualizowana.")

    except Exception as e:
        print(f"Wystąpił błąd: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
