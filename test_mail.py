import smtplib
try:
    server = smtplib.SMTP_SSL('poczta.o2.pl', 465)
    server.login('dariusztom@go2.pl', '5WZR5F66GGH6WAEN’)
    server.sendmail('dariusztom@go2.pl', 'dariusztom@go2.pl', 'Temat: Test\n\nTo jest testowa wiadomosc.')
    server.quit()
    print("Mail wysłany pomyślnie!")
except Exception as e:
    print(f"Błąd: {e}")
