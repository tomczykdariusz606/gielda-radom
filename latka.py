import sqlite3
conn = sqlite3.connect('instance/gielda.db')
cursor = conn.cursor()
cursor.execute("SELECT id, username FROM user")
print(cursor.fetchall())
conn.close()
