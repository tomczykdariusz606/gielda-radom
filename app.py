import os
import uuid
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import or_
# --- NOWE IMPORTY DLA ZNAKU WODNEGO ---
from PIL import Image, ImageDraw, ImageFont, ImageOps

app = Flask(__name__)
app.secret_key = 'sekretny_klucz_gieldy_radom_2024_v2' # Zmień na własny

# --- KONFIGURACJA ---
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///gielda.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# Zwiększamy limit, bo przetwarzanie zdjęć w pamięci wymaga trochę miejsca
app.config['MAX_CONTENT_LENGTH'] = 128 * 1024 * 1024
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'} # Dodano webp
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- MODELE BAZY DANYCH (Bez zmian) ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    cars = db.relationship('Car', backref='seller', lazy=True) # Poprawiona relacja

class Car(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    marka = db.Column(db.String(50), nullable=False)
    model = db.Column(db.String(50), nullable=False)
    rok = db.Column(db.Integer, nullable=False)
    cena = db.Column(db.Float, nullable=False)
    opis = db.Column(db.Text, nullable=False)
    img = db.Column(db.String(200), nullable=False)
    zrodlo = db.Column(db.String(20), default='Lokalne')
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    images = db.relationship('CarImage', backref='car', lazy=True, cascade="all, delete-orphan")

class CarImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    image_path = db.Column(db.String(200), nullable=False)
    car_id = db.Column(db.Integer, db.ForeignKey('car.id'), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- NOWA FUNKCJA: ZNAK WODNY ---
def add_watermark(image_file, text="darmowa Giełda"):
    """
    Dodaje półprzezroczysty znak wodny w prawym dolnym rogu.
    """
    # Otwórz obraz
    original_image = Image.open(image_file).convert("RGBA")
    
    # Ewentualny auto-obrót na podstawie metadanych (np. zdjęcia z telefonu)
    original_image = ImageOps.exif_transpose(original_image)

    width, height = original_image.size

    # Stwórz nową warstwę dla znaku wodnego (przezroczystą)
    txt_layer = Image.new('RGBA', original_image.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(txt_layer)

    # --- Konfiguracja czcionki ---
    # Próbujemy załadować ładną czcionkę systemową, jeśli się nie uda, używamy domyślnej
    font_size = int(height / 20) # Rozmiar zależny od wysokości zdjęcia
    try:
        # Przykładowe ścieżki dla Linuxa (Ubuntu) lub Windowsa. 
        # Najlepiej wgrać plik .ttf (np. Roboto-Bold.ttf) do folderu static/fonts/
        # font = ImageFont.truetype("static/fonts/Roboto-Bold.ttf", font_size)
        font = ImageFont.truetype("arial.ttf", font_size) # Próba dla Windows
    except IOError:
         # Fallback dla Linuxa (często działa) lub domyślna brzydka czcionka
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
        except IOError:
            font = ImageFont.load_default()
            print("Nie znaleziono ładnej czcionki, używam domyślnej.")

    # --- Obliczanie pozycji tekstu ---
    # Używamy getbbox dla nowszych wersji Pillow
    text_bbox = draw.textbbox((0, 0), text, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]

    # Margines od krawędzi (prawy dolny róg)
    margin_x = int(width * 0.05)
    margin_y = int(height * 0.05)
    x = width - text_width - margin_x
    y = height - text_height - margin_y

    # --- Rysowanie tekstu ---
    # Kolor: Biały, półprzezroczysty (alpha=128)
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 128))
    
    # --- Opcjonalnie: Dodaj lekki cień dla lepszej czytelności ---
    # draw.text((x+2, y+2), text, font=font, fill=(0, 0, 0, 80))

    # Połącz oryginalny obraz z warstwą tekstu
    watermarked_image = Image.alpha_composite(original_image, txt_layer)

    # Konwertuj z powrotem do RGB, żeby zapisać jako JPG
    return watermarked_image.convert("RGB")


# --- TRASY ---
@app.route('/')
def index():
    q = request.args.get('q')
    if q:
        search = f"%{q}%"
        cars = Car.query.filter(
            or_(Car.marka.like(search), Car.model.like(search))
        ).order_by(Car.id.desc()).all()
        if not cars: flash(f'Brak wyników dla: "{q}"', 'warning')
    else:
        cars = Car.query.order_by(Car.id.desc()).all()
    return render_template('index.html', cars=cars)

@app.route('/ogloszenie/<int:car_id>')
def car_details(car_id):
    car = Car.query.get_or_404(car_id)
    return render_template('details.html', car=car)

@app.route('/dodaj', methods=['POST'])
@login_required
def dodaj_ogloszenie():
    # (Pobieranie danych tekstowych bez zmian...)
    marka = request.form.get('marka')
    model = request.form.get('model')
    rok = request.form.get('rok')
    cena = request.form.get('cena')
    opis = request.form.get('opis')

    # --- ZMODYFIKOWANA OBSŁUGA ZDJĘĆ ---
    files = request.files.getlist('zdjecia')
    saved_images = []

    for file in files[:10]:
        if file and allowed_file(file.filename):
            try:
                # 1. Przetwórz obraz (dodaj znak wodny)
                processed_img = add_watermark(file, text="darmowa Giełda")

                # 2. Wygeneruj bezpieczną nazwę
                filename = secure_filename(file.filename)
                name_part, ext = os.path.splitext(filename)
                # Zapisujemy zawsze jako .jpg dla ujednolicenia
                unique_filename = str(uuid.uuid4())[:8] + "_" + name_part + ".jpg"
                save_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                
                # 3. Zapisz przetworzony obraz (jako JPEG z wysoką jakością)
                processed_img.save(save_path, "JPEG", quality=90, optimize=True)
                
                saved_images.append(url_for('static', filename='uploads/' + unique_filename))
            except Exception as e:
                print(f"Błąd przetwarzania obrazu: {e}")
                flash('Wystąpił błąd podczas przetwarzania jednego ze zdjęć.', 'danger')

    if not saved_images:
        flash('Musisz dodać przynajmniej jedno poprawne zdjęcie!', 'danger')
        return redirect(url_for('index'))

    main_img = saved_images[0]

    # Zapis do bazy (bez zmian)
    nowe_auto = Car(
        marka=marka, model=model, rok=int(rok), cena=float(cena),
        opis=opis, img=main_img, user_id=current_user.id
    )
    db.session.add(nowe_auto)
    db.session.commit()

    for img_path in saved_images:
        new_image = CarImage(image_path=img_path, car_id=nowe_auto.id)
        db.session.add(new_image)
    
    db.session.commit()

    flash('Ogłoszenie dodane pomyślnie!', 'success')
    return redirect(url_for('index'))

# --- AUTH i Import (Bez istotnych zmian w logice) ---
# (Reszta pliku app.py pozostaje taka sama jak w poprzedniej wersji, 
#  upewnij się tylko, że masz poprawione relacje w modelach jak wyżej)
# ...
# ...

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)
