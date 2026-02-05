import sqlite3

try:
    conn = sqlite3.connect('instance/gielda.db')
    c = conn.cursor()
    # Dodajemy kolumnę dla liczby wyświetleń
    c.execute("ALTER TABLE car ADD COLUMN views INTEGER DEFAULT 0")
    print("✅ Dodano licznik wyświetleń do bazy!")
    conn.commit()
except Exception as e:
    print("ℹ️ Licznik już chyba istnieje (to dobrze).")
finally:
    conn.close()
