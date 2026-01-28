import smtplib
import ssl

smtp_server = "smtp.gmail.com"
port = 465
sender_email = "tomczykdariusz606@gmail.com"
password = "nujqhiivciduxddj"  # Tutaj wklej ten 16-znakowy kod

message = """Subject: Test Gielda Radom

To jest test z Gmaila na porcie 465."""

context = ssl.create_default_context()

try:
    with smtplib.SMTP_SSL(smtp_server, port, context=context) as server:
        server.login(sender_email, password)
        server.sendmail(sender_email, sender_email, message)
    print("Sukces! Mail wyslany.")
except Exception as e:
    print(f"Blad: {e}")
