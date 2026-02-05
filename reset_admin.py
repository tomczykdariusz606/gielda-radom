import sqlite3
import os
from werkzeug.security import generate_password_hash

# 1. Szukamy bazy danych
DB_PATH = os.path.join('instance', 'gielda.db')
if not os.path.exists(DB_PATH):
    DB_PATH = 'gielda.db'

print(f"🔧 Naprawiam konto admina w bazie: {DB_PATH}")

def fix_admin():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Nowe hasło: "radom76"
    new_pass = generate_password_hash("radom76")

    try:
        # Sprawdzamy czy user istnieje
        cursor.execute("SELECT id FROM user WHERE username = 'admin'")
        data = cursor.fetchone()

        if data:
            # Aktualizujemy hasło istniejącego admina
            cursor.execute("UPDATE user SET password_hash = ? WHERE username = 'admin'", (new_pass,))
            print("✅ Hasło dla użytkownika 'admin' zostało zresetowane na: radom76")
        else:
            # Tworzymy nowego admina, jeśli go nie ma
            # Upewniamy się, że podajemy wartości dla nowych kolumn (lokalizacja, limity)
            cursor.execute("""
                INSERT INTO user (username, email, password_hash, lokalizacja, ai_requests_today, last_ai_request_date)
                VALUES ('admin', 'admin@gielda.pl', ?, 'Radom - Centrum', 0, DATE('now'))
            """, (new_pass,))
            print("✅ Utworzono nowe konto: admin / hasło: radom76")

        conn.commit()
    except Exception as e:
        print(f"❌ Błąd: {e}")
        print("Upewnij się, że baza danych ma zaktualizowaną strukturę (uruchom db_promo.py i db_update.py)")
    finally:
        conn.close()

if __name__ == "__main__":
    fix_admin()
