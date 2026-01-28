import smtplib

# Konfiguracja dla Gmail
smtp_server = "smtp.gmail.com"
port = 587  # Używamy portu 587 dla lepszej stabilności na VPS
sender_email = "tomczykdariusz606@gmail.com"
password = "nujqhiivciduxddj" # Wklej kod bez spacji

message = """Subject: Test Gielda Radom

To jest test wyslany z Gmaila przez port 587."""

try:
    # Tworzymy połączenie TLS
    server = smtplib.SMTP(smtp_server, port)
    server.starttls() 
    server.login(sender_email, password)
    server.sendmail(sender_email, sender_email, message)
    server.quit()
    print("Sukces! Mail z Gmaila wysłany pomyślnie.")
except Exception as e:
    print(f"Błąd wysyłki: {e}")
