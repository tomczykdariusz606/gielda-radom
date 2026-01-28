import sqlite3

def patch_database():
    conn = sqlite3.connect('gielda.db')
    cursor = conn.cursor()

    print("Rozpoczynam aktualizację bazy danych...")

    try:
        # 1. Próba dodania kolumny email (jeśli już jest, SQLite rzuci błąd, który przechwycimy)
        cursor.execute("ALTER TABLE user ADD COLUMN email VARCHAR(120)")
        print("- Dodano kolumnę 'email' do tabeli 'user'.")
    except sqlite3.OperationalError:
        print("- Kolumna 'email' już istnieje lub wystąpił błąd struktury.")

    # 2. Uzupełnienie pustych maili, aby nie było błędów przy logowaniu/rejestracji
    cursor.execute("SELECT id, username FROM user WHERE email IS NULL")
    users_without_email = cursor.fetchall()

    for user in users_without_email:
        user_id = user[0]
        temp_email = f"{user[1]}@temp.pl"
        cursor.execute("UPDATE user SET email = ? WHERE id = ?", (temp_email, user_id))
        print(f"  > Przypisano tymczasowy mail: {temp_email} dla ID: {user_id}")

    conn.commit()
    conn.close()
    print("Aktualizacja zakończona pomyślnie!")

if __name__ == "__main__":
    patch_database()
