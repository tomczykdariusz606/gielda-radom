from PIL import Image
import os

# Ścieżka do Twojego logo (tego, które już wgrałeś)
img_path = 'static/watermark.png'
save_path = 'static/favicon.ico'

if os.path.exists(img_path):
    img = Image.open(img_path)
    
    # Jeśli obrazek nie jest kwadratem, zróbmy go kwadratowym (centrowanie)
    # Żeby "G" się nie spłaszczyło
    if img.size[0] != img.size[1]:
        size = max(img.size)
        new_img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        
        # Oblicz pozycję środka
        left = (size - img.size[0]) // 2
        top = (size - img.size[1]) // 2
        
        new_img.paste(img, (left, top))
        img = new_img

    # Generujemy plik ICO zawierający WIELE rozmiarów w jednym pliku
    # To jest standard PRO - przeglądarka sama wybierze najlepszy rozmiar
    img.save(save_path, format='ICO', sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (256, 256)])
    
    print(f"✅ Sukces! Utworzono profesjonalny static/favicon.ico (Multi-Size)")
else:
    print("❌ Błąd: Nie widzę pliku static/watermark.png")

