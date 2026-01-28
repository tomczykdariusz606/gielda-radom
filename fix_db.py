import sqlite3
import os

def fix_everything():
    # Znajdź wszystkie pliki .db w folderze i podfolderach
    databases = []
    for root, dirs, files in os.walk("."):
        for file in files:
            if file.endswith(".db"):
                databases.append(os.path.join(root, file))

    if not databases:
        print("Nie znaleziono żadnych plików bazy danych!")
        return

    for db_path in databases:
        print(f"\nSprawdzam bazę: {db_path}")
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Sprawdź czy jest tabela user
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user'")
            if not cursor.fetchone():
                print(f"  - Pusta baza lub brak tabeli 'user'. Pomijam.")
                continue

            print(f"  - Znaleziono tabelę 'user'. Próbuję dodać email...")
            
            # Dodaj kolumnę
            try:
                cursor.execute("ALTER TABLE user ADD COLUMN email VARCHAR(120)")
                print("  - Kolumna 'email' dodana.")
            except sqlite3.OperationalError:
                print("  - Kolumna 'email' już istnieje.")

            # Uzupełnij dane
            cursor.execute("UPDATE user SET email = username || '@temp.pl' WHERE email IS NULL")
            conn.commit()
            print(f"  - Sukces! Zaktualizowano bazę: {db_path}")
            conn.close()
            
        except Exception as e:
            print(f"  - Błąd przy tej bazie: {e}")

if __name__ == "__main__":
    fix_everything()
