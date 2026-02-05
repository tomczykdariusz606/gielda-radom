import sqlite3
import os

# Ścieżka do bazy
DB_PATH = os.path.join('instance', 'gielda.db')
if not os.path.exists(DB_PATH): DB_PATH = 'gielda.db'

def add_promo_column():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    print(f"🔧 Aktualizacja bazy: {DB_PATH}")

    try:
        # Dodajemy flagę czy promowane (0 - nie, 1 - tak)
        cursor.execute("ALTER TABLE car ADD COLUMN is_promoted BOOLEAN DEFAULT 0")
        print("✅ Dodano kolumnę 'is_promoted'")
    except sqlite3.OperationalError:
        print("ℹ️ Kolumna 'is_promoted' już istnieje")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    add_promo_column()
