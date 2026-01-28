import smtplib
import ssl

# Dane dla Gmail
smtp_server = "smtp.gmail.com"
port = 465  # Dla SSL
sender_email = "tomczykdariusz606@gmail.com"
password = "ngldaqatnibxzvpy" # Tutaj wklej kod od Google

message = """Subject: Test Gielda Radom

To jest wiadomosc testowa wyslana prosto z serwera Ubuntu."""

context = ssl.create_default_context()

try:
    with smtplib.SMTP_SSL(smtp_server, port, context=context) as server:
        server.login(sender_email, password)
        server.sendmail(sender_email, sender_email, message)
    print("Sukces! Mail zostal wyslany pomyslnie.")
except Exception as e:
    print(f"Blad: {e}")
