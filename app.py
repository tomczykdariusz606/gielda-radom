import os
import uuid
import logging
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import or_
# PIL imports
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFile, UnidentifiedImageError, DecompressionBombError

# Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")  # production: set SECRET_KEY env var

# CONFIG
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///gielda.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 128 * 1024 * 1024
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# PIL safe settings
ImageFile.LOAD_TRUNCATED_IMAGES = True
# Optionally set Image.MAX_IMAGE_PIXELS to avoid decompression bombs if needed:
# Image.MAX_IMAGE_PIXELS = 20000 * 20000

# logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# MODELS
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    cars = db.relationship('Car', backref='seller', lazy=True)

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

# WATERMARK FUNCTION
def add_watermark(image_file, text="darmowa Giełda"):
    """
    Dodaje półprzezroczysty znak wodny w prawym dolnym rogu.
    Przyjmuje FileStorage lub ścieżkę; zwraca PIL.Image w trybie RGB.
    """
    try:
        original_image = Image.open(image_file)
    except UnidentifiedImageError:
        logger.exception("Plik nie jest rozpoznawanym obrazem.")
        raise
    except DecompressionBombError:
        logger.exception("Plik obrazu potencjalnie zbyt duży (DecompressionBomb).")
        raise
    except Exception:
        logger.exception("Nieoczekiwany błąd przy otwieraniu obrazu.")
        raise

    # Autoorientacja i konwersja do RGBA (żeby obsłużyć alpha)
    original_image = ImageOps.exif_transpose(original_image).convert("RGBA")
    width, height = original_image.size

    # Warstwa tekstu
    txt_layer = Image.new('RGBA', original_image.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(txt_layer)

    font_size = max(12, int(height / 20))
    try:
        font = ImageFont.truetype("static/fonts/Roboto-Bold.ttf", font_size)
    except Exception:
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()
            logger.info("Używam domyślnej czcionki PIL")

    # Oblicz rozmiar tekstu z fallbackem
    try:
        text_bbox = draw.textbbox((0, 0), text, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
    except AttributeError:
        text_width, text_height = draw.textsize(text, font=font)

    margin_x = int(width * 0.05)
    margin_y = int(height * 0.05)
    x = max(0, width - text_width - margin_x)
    y = max(0, height - text_height - margin_y)

    # Rysuj półprzezroczysty tekst
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 160))

    # Połącz warstwy
    try:
        watermarked = Image.alpha_composite(original_image, txt_layer)
    except Exception:
        logger.exception("Błąd podczas składania warstw obrazu")
        raise

    # Zamień przezroczystość na białe tło przed zapisem jako JPEG
    if watermarked.mode == 'RGBA':
        background = Image.new("RGB", watermarked.size, (255, 255, 255))
        alpha = watermarked.split()[3]
        background.paste(watermarked.convert('RGB'), mask=alpha)
        final_img = background
    else:
        final_img = watermarked.convert("RGB")

    return final_img

# ROUTES
@app.context_processor
def inject_common():
    return {
        'current_year': datetime.utcnow().year,
        'now_date': datetime.utcnow().strftime("%Y-%m-%d")
    }

@app.route('/')
def index():
    q = request.args.get('q')
    if q:
        search = f"%{q}%"
        cars = Car.query.filter(
            or_(Car.marka.like(search), Car.model.like(search))
        ).order_by(Car.id.desc()).all()
        if not cars:
            flash(f'Brak wyników dla: "{q}"', 'warning')
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
    marka = request.form.get('marka')
    model = request.form.get('model')
    rok = request.form.get('rok')
    cena = request.form.get('cena')
    opis = request.form.get('opis')

    # Walidacja rok/cena
    try:
        rok_i = int(rok)
        cena_f = float(cena)
    except (ValueError, TypeError):
        flash("Podaj poprawny rok i cenę.", "danger")
        return redirect(url_for('index'))

    files = request.files.getlist('zdjecia')
    saved_images = []

    for file in files[:10]:
        if file and allowed_file(file.filename):
            # Sprawdź MIME
            if not file.mimetype or not file.mimetype.startswith('image/'):
                flash("Przesłany plik nie jest obrazem.", "danger")
                continue
            try:
                processed_img = add_watermark(file, text="darmowa Giełda")

                filename = secure_filename(file.filename)
                name_part, ext = os.path.splitext(filename)
                unique_filename = str(uuid.uuid4())[:8] + "_" + name_part + ".jpg"
                save_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)

                processed_img.save(save_path, "JPEG", quality=90, optimize=True)
                saved_images.append(url_for('static', filename='uploads/' + unique_filename))
            except Exception:
                logger.exception("Błąd przetwarzania obrazu")
                flash('Wystąpił błąd podczas przetwarzania jednego ze zdjęć.', 'danger')

    if not saved_images:
        flash('Musisz dodać przynajmniej jedno poprawne zdjęcie!', 'danger')
        return redirect(url_for('index'))

    main_img = saved_images[0]

    try:
        nowe_auto = Car(
            marka=marka, model=model, rok=rok_i, cena=cena_f,
            opis=opis, img=main_img, user_id=current_user.id
        )
        db.session.add(nowe_auto)
        db.session.flush()  # uzyskaj nowe_auto.id bez commitu
        for img_path in saved_images:
            new_image = CarImage(image_path=img_path, car_id=nowe_auto.id)
            db.session.add(new_image)
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("Błąd zapisu ogłoszenia do bazy")
        flash('Wystąpił błąd przy zapisie ogłoszenia.', 'danger')
        return redirect(url_for('index'))

    flash('Ogłoszenie dodane pomyślnie!', 'success')
    return redirect(url_for('index'))

@app.route('/privacy')
def privacy():
    return render_template('privacy.html')

# Placeholders for auth routes (login/register) - ensure these exist in your app
# @app.route('/login', methods=['GET','POST'])
# def login(): ...
# @app.route('/register', methods=['GET','POST'])
# def register(): ...

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)
