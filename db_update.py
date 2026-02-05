import sqlite3
import os

# Ścieżka do Twojej bazy danych na serwerze (zazwyczaj w folderze instance)
# Jeśli masz bazę w głównym folderze, zmień na 'gielda.db'
DB_PATH = os.path.join('instance', 'gielda.db')

if not os.path.exists(DB_PATH):
    print(f"⚠️ Nie znaleziono bazy w {DB_PATH}. Szukam w katalogu głównym...")
    DB_PATH = 'gielda.db'

def update_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print(f"🔧 Aktualizuję bazę danych: {DB_PATH}")

    # 1. Tabela USER - dodajemy nowe kolumny
    try:
        cursor.execute("ALTER TABLE user ADD COLUMN lokalizacja TEXT DEFAULT 'Radom'")
        print("✅ Dodano kolumnę 'lokalizacja' do tabeli USER")
    except sqlite3.OperationalError:
        print("ℹ️ Kolumna 'lokalizacja' już istnieje")

    try:
        cursor.execute("ALTER TABLE user ADD COLUMN ai_requests_today INTEGER DEFAULT 0")
        print("✅ Dodano kolumnę 'ai_requests_today' do tabeli USER")
    except sqlite3.OperationalError:
        print("ℹ️ Kolumna 'ai_requests_today' już istnieje")

    try:
        cursor.execute("ALTER TABLE user ADD COLUMN last_ai_request_date DATE")
        print("✅ Dodano kolumnę 'last_ai_request_date' do tabeli USER")
    except sqlite3.OperationalError:
        print("ℹ️ Kolumna 'last_ai_request_date' już istnieje")

    # 2. Tabela CAR - dodajemy nowe kolumny dla AI i statystyk
    columns_to_add = [
        ("ai_label", "TEXT"),
        ("ai_valuation_data", "TEXT"),
        ("typ", "TEXT DEFAULT 'Osobowe'"),
        ("skrzynia", "TEXT"),
        ("paliwo", "TEXT"),
        ("nadwozie", "TEXT"),
        ("pojemnosc", "TEXT"),
        ("wyswietlenia", "INTEGER DEFAULT 0"),
        ("przebieg", "INTEGER DEFAULT 0")
    ]

    for col_name, col_type in columns_to_add:
        try:
            cursor.execute(f"ALTER TABLE car ADD COLUMN {col_name} {col_type}")
            print(f"✅ Dodano kolumnę '{col_name}' do tabeli CAR")
        except sqlite3.OperationalError:
            print(f"ℹ️ Kolumna '{col_name}' już istnieje")

    conn.commit()
    conn.close()
    print("\n🎉 Baza danych została zaktualizowana! Możesz wgrywać nowy kod app.py.")

if __name__ == "__main__":
    update_db()
