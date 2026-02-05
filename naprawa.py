import sqlite3
from datetime import datetime

print("🚑 Rozpoczynam naprawę bazy...")
try:
    # Łączymy się z Twoją bazą
    conn = sqlite3.connect('instance/gielda.db')
    c = conn.cursor()

    # Ustawiamy dzisiejszą datę dla aut, które jej nie mają
    teraz = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    c.execute("UPDATE car SET data_dodania = ? WHERE data_dodania IS NULL", (teraz,))

    # Naprawiamy też liczniki (żeby nie było błędów przy dodawaniu)
    c.execute("UPDATE car SET wyswietlenia = 0 WHERE wyswietlenia IS NULL")
    c.execute("UPDATE car SET views = 0 WHERE views IS NULL")

    conn.commit()
    print(f"✅ SUKCES! Ustawiono datę {teraz} dla starych ogłoszeń.")
except Exception as e:
    print(f"❌ Błąd: {e}")
finally:
    if conn: conn.close()

