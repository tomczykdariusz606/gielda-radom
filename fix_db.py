import sqlite3
import os

def patch_database():
    # Szukamy bazy w głównej ścieżce lub w folderze 'instance'
    possible_paths = ['gielda.db', 'instance/gielda.db']
    db_path = None

    for path in possible_paths:
        if os.path.exists(path):
            db_path = path
            break

    if not db_path:
        print("BŁĄD: Nie znaleziono pliku gielda.db! Upewnij się, że uruchamiasz skrypt w folderze projektu.")
        return

    print(f"Znaleziono bazę: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Sprawdzamy czy tabela user w ogóle istnieje
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user'")
        if not cursor.fetchone():
            print("BŁĄD: Tabela 'user' nie istnieje w tej bazie danych!")
            return

        # 1. Próba dodania kolumny email
        try:
            cursor.execute("ALTER TABLE user ADD COLUMN email VARCHAR(120)")
            print("- Dodano kolumnę 'email'.")
        except sqlite3.OperationalError:
            print("- Kolumna 'email' już istnieje.")

        # 2. Uzupełnienie maili
        cursor.execute("UPDATE user SET email = username || '@temp.pl' WHERE email IS NULL")
        print(f"- Zaktualizowano brakujące adresy e-mail (ilość zmian: {conn.total_changes})")

        conn.commit()
        print("AKTUALIZACJA ZAKOŃCZONA SUKCESEM!")
    except Exception as e:
        print(f"Wystąpił błąd: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    patch_database()
