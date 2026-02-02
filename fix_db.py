import sqlite3
import os

def fix_everything():
    # Znajdź wszystkie pliki .db
    databases = []
    for root, dirs, files in os.walk("."):
        for file in files:
            if file.endswith(".db"):
                databases.append(os.path.join(root, file))

    if not databases:
        print("Nie znaleziono żadnych plików bazy danych!")
        return

    for db_path in databases:
        if os.path.getsize(db_path) == 0:
            print(f"\nPomijam pusty plik: {db_path}")
            continue

        print(f"\nSprawdzam bazę: {db_path} ({os.path.getsize(db_path)} bajtów)")
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # --- TABELA USER ---
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user'")
            if cursor.fetchone():
                try:
                    cursor.execute("ALTER TABLE user ADD COLUMN email VARCHAR(120)")
                    print("  [User] Kolumna 'email' dodana.")
                except sqlite3.OperationalError:
                    print("  [User] Kolumna 'email' już istnieje.")
                
                cursor.execute("UPDATE user SET email = username || '@temp.pl' WHERE email IS NULL")

            # --- TABELA CAR ---
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='car'")
            if cursor.fetchone():
                print("  - Znaleziono tabelę 'car'. Aktualizuję strukturę...")
                
                # Słownik kolumn do dodania: (Nazwa, Typ)
                columns_to_add = [
                    ("ai_label", "VARCHAR(100)"),
                    ("ai_valuation_data", "TEXT"),
                    ("przebieg", "INTEGER") # Nowa zmienna na przebieg
                ]

                for col_name, col_type in columns_to_add:
                    try:
                        cursor.execute(f"ALTER TABLE car ADD COLUMN {col_name} {col_type}")
                        print(f"  [Car] Kolumna '{col_name}' dodana.")
                    except sqlite3.OperationalError:
                        print(f"  [Car] Kolumna '{col_name}' już istnieje.")

            conn.commit()
            print(f"  - Sukces! Baza {db_path} została zaktualizowana.")
            conn.close()

        except Exception as e:
            print(f"  - Błąd przy tej bazie: {e}")

if __name__ == "__main__":
    fix_everything()

