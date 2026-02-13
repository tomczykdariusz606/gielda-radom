import sqlite3

# Połącz z bazą (upewnij się, że nazwa pliku to database.db lub gielda.db - sprawdź w folderze!)
conn = sqlite3.connect('database.db') 
cursor = conn.cursor()

try:
    # Dodajemy kolumnę na wyposażenie (tekst rozdzielony przecinkami)
    cursor.execute("ALTER TABLE car ADD COLUMN wyposazenie TEXT")
    print("SUKCES! Dodano kolumnę 'wyposazenie'.")
except sqlite3.OperationalError:
    print("INFO: Kolumna 'wyposazenie' już istnieje.")

conn.commit()
conn.close()
