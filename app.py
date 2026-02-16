import os
import uuid
import zipfile
import io
import json
import sqlite3
import random
import string
from datetime import datetime, timezone, timedelta
from PIL import Image, ImageOps
# Importy Flask
from flask import Flask, render_template, request, redirect, url_for, flash, abort, jsonify, send_from_directory, send_file, make_response, session
# Importy Bazy i Logowania
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_, and_
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
# Importy Bezpieczeństwa
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer as Serializer
# Importy AI i Maila
import google.generativeai as genai
from flask_mail import Mail, Message
# Import Google Login
from authlib.integrations.flask_client import OAuth

# --- KONFIGURACJA I KLUCZE ---
try:
    import sekrety
    GEMINI_KEY = sekrety.GEMINI_KEY
    MAIL_PWD = sekrety.MAIL_PWD
    SECRET_KEY_APP = getattr(sekrety, 'SECRET_KEY', 'super_tajny_klucz_gieldy_radom_2026')
    # Google Keys
    GOOGLE_ID = getattr(sekrety, 'GOOGLE_CLIENT_ID', None)
    GOOGLE_SECRET = getattr(sekrety, 'GOOGLE_CLIENT_SECRET', None)
except ImportError:
    # Fallback jeśli brak pliku sekrety
    GEMINI_KEY = None
    MAIL_PWD = None
    SECRET_KEY_APP = 'dev_key_temporary'
    GOOGLE_ID = None
    GOOGLE_SECRET = None

app = Flask(__name__)
app.secret_key = SECRET_KEY_APP

# --- KONFIGURACJA OAUTH (GOOGLE) ---
oauth = OAuth(app)
if GOOGLE_ID and GOOGLE_SECRET:
    google = oauth.register(
        name='google',
        client_id=GOOGLE_ID,
        client_secret=GOOGLE_SECRET,
        access_token_url='https://oauth2.googleapis.com/token',
        access_token_params=None,
        authorize_url='https://accounts.google.com/o/oauth2/auth',
        authorize_params=None,
        api_base_url='https://www.googleapis.com/oauth2/v1/',
        userinfo_endpoint='https://openidconnect.googleapis.com/v1/userinfo',
        client_kwargs={'scope': 'openid email profile'},
        jwks_uri='https://www.googleapis.com/oauth2/v3/certs'
    )
else:
    google = None

# --- KONFIGURACJA BAZY DANYCH ---
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///gielda.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# --- KONFIGURACJA UPLOADU ---
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# --- KONFIGURACJA MAILA (O2.PL) ---
app.config['MAIL_SERVER'] = 'poczta.o2.pl'
app.config['MAIL_PORT'] = 465
app.config['MAIL_USE_SSL'] = True
app.config['MAIL_USERNAME'] = 'gieldaradom@o2.pl'
app.config['MAIL_PASSWORD'] = MAIL_PWD
app.config['MAIL_DEFAULT_SENDER'] = 'gieldaradom@o2.pl'

db = SQLAlchemy(app)
mail = Mail(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- KONFIGURACJA GEMINI AI ---
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    try:
        model_ai = genai.GenerativeModel('gemini-2.0-flash') # Lub 'gemini-pro' zależnie od dostępności
    except:
        model_ai = None
else:
    model_ai = None

# --- ŚLEDZENIE AKTYWNOŚCI ---
@app.before_request
def update_last_seen():
    if current_user.is_authenticated:
        current_user.last_seen = datetime.utcnow()
        try:
            db.session.commit()
        except:
            db.session.rollback()

# --- TŁUMACZENIA (Słownik) ---
TRANSLATIONS = {
    'pl': {
        'search_ph': 'Wpisz np. Audi A4, Automat...', 'btn_search': 'SZUKAJ', 'filters': 'Filtry', 
        'cat': 'Kategoria', 'fuel': 'Paliwo', 'gear': 'Skrzynia', 'year': 'Rok od', 'price': 'Cena do', 'mileage': 'Przebieg do', 
        'all': 'Wszystkie', 'man': 'Manualna', 'auto': 'Automatyczna', 'available': 'Dostępne Oferty', 'found': 'Znaleziono',
        'add': 'DODAJ OGŁOSZENIE', 'login': 'Logowanie', 'logout': 'Wyloguj', 'account': 'Konto',
        'garage': 'Twój Garaż', 'limit': 'Limit AI', 'days_left': 'dni', 'expired': 'WYGASŁO',
        'scan_cam': 'SKANUJ (APARAT)', 'scan_file': 'WGRAJ (PLIK)', 'desc_ai': 'Opis Generowany przez Eksperta AI',
        'welcome_back': 'Witaj ponownie', 'login_desc': 'Zaloguj się, aby zarządzać ofertami',
        'password': 'Hasło', 'forgot_pass': 'Zapomniałeś hasła?', 'login_btn': 'ZALOGUJ SIĘ',
        'no_acc': 'Nie masz jeszcze konta?', 'create_acc': 'ZAŁÓŻ KONTO', 'back_home': 'Wróć na stronę główną'
    },
    'en': {
        'search_ph': 'E.g. Audi A4, Automatic...', 'btn_search': 'SEARCH', 'filters': 'Filters', 
        'cat': 'Category', 'fuel': 'Fuel', 'gear': 'Transmission', 'year': 'Year from', 'price': 'Price to', 'mileage': 'Mileage to', 
        'all': 'All', 'man': 'Manual', 'auto': 'Automatic', 'available': 'Available Offers', 'found': 'Found',
        'add': 'ADD LISTING', 'login': 'Login', 'logout': 'Logout', 'account': 'Account',
        'garage': 'Your Garage', 'limit': 'AI Limit', 'days_left': 'days left', 'expired': 'EXPIRED',
        'scan_cam': 'SCAN (CAMERA)', 'scan_file': 'UPLOAD (FILE)', 'desc_ai': 'Description Generated by AI Expert',
        'welcome_back': 'Welcome Back', 'login_desc': 'Login to manage your listings',
        'password': 'Password', 'forgot_pass': 'Forgot password?', 'login_btn': 'LOGIN',
        'no_acc': 'No account yet?', 'create_acc': 'REGISTER', 'back_home': 'Back to Home'
    },
    'de': {
        'search_ph': 'Z.B. Audi A4, Automatik...', 'btn_search': 'SUCHEN', 'filters': 'Filter', 
        'cat': 'Kategorie', 'fuel': 'Kraftstoff', 'gear': 'Getriebe', 'year': 'Baujahr ab', 'price': 'Preis bis', 'mileage': 'KM bis', 
        'all': 'Alle', 'man': 'Schaltgetriebe', 'auto': 'Automatik', 'available': 'Verfügbare Angebote', 'found': 'Gefunden',
        'add': 'ANZEIGE AUFGEBEN', 'login': 'Anmelden', 'logout': 'Abmelden', 'account': 'Konto',
        'garage': 'Deine Garage', 'limit': 'AI Limit', 'days_left': 'Tage übrig', 'expired': 'ABGELAUFEN',
        'scan_cam': 'SCAN (KAMERA)', 'scan_file': 'HOCHLADEN (DATEI)', 'desc_ai': 'Beschreibung vom AI-Experten',
        'welcome_back': 'Willkommen zurück', 'login_desc': 'Einloggen um Angebote zu verwalten',
        'password': 'Passwort', 'forgot_pass': 'Passwort vergessen?', 'login_btn': 'ANMELDEN',
        'no_acc': 'Noch kein Konto?', 'create_acc': 'REGISTRIEREN', 'back_home': 'Zurück zur Startseite'
    }
}

@app.context_processor
def inject_conf_var():
    lang = request.cookies.get('lang', 'pl')
    return dict(lang=lang, t=TRANSLATIONS.get(lang, TRANSLATIONS['pl']))

@app.route('/set_lang/<lang_code>')
def set_language(lang_code):
    if lang_code not in TRANSLATIONS: lang_code = 'pl'
    resp = make_response(redirect(request.referrer or '/'))
    resp.set_cookie('lang', lang_code, max_age=60*60*24*30)
    return resp

# --- MODELE BAZY DANYCH ---
class Favorite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    car_id = db.Column(db.Integer, db.ForeignKey('car.id'), nullable=False)
    car = db.relationship('Car', backref='fav_entries')

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    lokalizacja = db.Column(db.String(100), default='Radom')
    google_id = db.Column(db.String(100), unique=True, nullable=True) # Nowe pole Google
    avatar_url = db.Column(db.String(500), nullable=True) # Nowe pole Avatar
    ai_requests_today = db.Column(db.Integer, default=0)
    last_ai_request_date = db.Column(db.Date, default=datetime.utcnow().date())
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    
    cars = db.relationship('Car', backref='owner', lazy=True, cascade="all, delete-orphan")
    favorites = db.relationship('Favorite', backref='user', lazy=True, cascade="all, delete-orphan")

    def get_reset_token(self):
        s = Serializer(app.config['SECRET_KEY'], salt='reset-salt')
        return s.dumps({'user_id': self.id})

    @staticmethod
    def verify_reset_token(token, expires_sec=1800):
        s = Serializer(app.config['SECRET_KEY'], salt='reset-salt')
        try:
            user_id = s.loads(token, max_age=expires_sec)['user_id']
        except:
            return None
        return User.query.get(user_id)

class Car(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    typ = db.Column(db.String(20), default='Osobowe')
    marka = db.Column(db.String(50), nullable=False)
    model = db.Column(db.String(50), nullable=False)
    rok = db.Column(db.Integer, nullable=False)
    cena = db.Column(db.Float, nullable=False)
    opis = db.Column(db.Text, nullable=False)
    telefon = db.Column(db.String(20), nullable=False)
    img = db.Column(db.String(200), nullable=False)
    zrodlo = db.Column(db.String(50), default='Radom')
    
    # Dane techniczne
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    vin = db.Column(db.String(20), nullable=True)
    wyposazenie = db.Column(db.Text, nullable=True)
    skrzynia = db.Column(db.String(20))
    paliwo = db.Column(db.String(20))
    nadwozie = db.Column(db.String(30))
    pojemnosc = db.Column(db.String(20))
    przebieg = db.Column(db.Integer, default=0)
    
    # --- NOWE POLA DLA AI ---
    moc = db.Column(db.Integer, nullable=True)
    kolor = db.Column(db.String(50), nullable=True)
    
    # AI i Statystyki
    is_promoted = db.Column(db.Boolean, default=False)
    ai_label = db.Column(db.String(500), nullable=True)
    ai_valuation_data = db.Column(db.String(50), nullable=True)
    views = db.Column(db.Integer, default=0)
    wyswietlenia = db.Column(db.Integer, default=0) # Legacy field
    
    data_dodania = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    images = db.relationship('CarImage', backref='car', lazy=True, cascade="all, delete-orphan")

class CarImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    image_path = db.Column(db.String(200), nullable=False)
    car_id = db.Column(db.Integer, db.ForeignKey('car.id'), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- FUNKCJE POMOCNICZE ---
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_optimized_image(file):
    filename = f"{uuid.uuid4().hex}.webp"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    
    try:
        img = Image.open(file)
        # Obsługa obrotu zdjęcia (EXIF)
        try:
            img = ImageOps.exif_transpose(img)
        except:
            pass
        
        # Konwersja kolorów
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        
        # 1. SKALOWANIE GŁÓWNEGO ZDJĘCIA
        # Jeśli większe niż 1600px, zmniejsz (oszczędność miejsca)
        base_width = 1600
        if img.width > base_width:
            w_percent = (base_width / float(img.width))
            h_size = int((float(img.height) * float(w_percent)))
            img = img.resize((base_width, h_size), Image.Resampling.LANCZOS)

        # 2. DODAWANIE ZNAKU WODNEGO
        watermark_path = 'static/watermark.png'
        if os.path.exists(watermark_path):
            try:
                # Otwórz watermark i zachowaj przezroczystość
                watermark = Image.open(watermark_path).convert("RGBA")
                
                # Oblicz wielkość znaku (np. 20% szerokości zdjęcia)
                wm_width = int(img.width * 0.20)
                wm_ratio = watermark.height / watermark.width
                wm_height = int(wm_width * wm_ratio)
                
                # Jeśli watermark wyszedł za mały (np. przy małych fotkach), ustaw minimum
                if wm_width < 100: 
                    wm_width = 100
                    wm_height = int(100 * wm_ratio)

                watermark = watermark.resize((wm_width, wm_height), Image.Resampling.LANCZOS)

                # Pozycja: Prawy dolny róg z marginesem
                margin = int(img.width * 0.02) # 2% marginesu
                position = (img.width - wm_width - margin, img.height - wm_height - margin)

                # Ponieważ główne zdjęcie to RGB, a watermark to RGBA, musimy stworzyć tymczasową warstwę
                transparent_layer = Image.new('RGBA', img.size, (0,0,0,0))
                transparent_layer.paste(watermark, position, mask=watermark)
                
                # Połącz zdjęcia
                img = img.convert("RGBA")
                img = Image.alpha_composite(img, transparent_layer)
                img = img.convert("RGB") # Wróć do RGB dla WebP
            except Exception as e:
                print(f"Błąd znaku wodnego: {e}")

        # Zapisz jako WebP (lekki i szybki)
        img.save(filepath, "WEBP", quality=85)
        
    except Exception as e:
        print(f"Błąd zapisu obrazu: {e}")
        return None

    return filename


def check_ai_limit():
    if not current_user.is_authenticated: return False
    today = datetime.utcnow().date()
    if current_user.last_ai_request_date != today:
        current_user.ai_requests_today = 0
        current_user.last_ai_request_date = today
        db.session.commit()
    return current_user.ai_requests_today < 1000

def update_market_valuation(car):
    if not model_ai: return
    try:
        # 1. KROK: Python liczy REALNE dane z Twojej bazy (Radom i okolice)
        similar_cars = Car.query.filter(
            Car.marka == car.marka,
            Car.model == car.model,
            Car.rok >= car.rok - 2,
            Car.rok <= car.rok + 2,
            Car.id != car.id
        ).all()
        
        liczba_lokalna = len(similar_cars)
        
        # Obliczamy średnią cenę w Twojej bazie (jeśli są auta)
        if liczba_lokalna > 0:
            srednia_cena = sum(c.cena for c in similar_cars) / liczba_lokalna
            info_z_bazy = f"W lokalnej bazie Giełda Radom jest {liczba_lokalna} podobnych aut. Ich średnia cena to {int(srednia_cena)} PLN."
        else:
            info_z_bazy = "W lokalnej bazie Giełda Radom to jedyny taki egzemplarz (unikat)."

        # 2. KROK: Wysyłamy te fakty do AI
        prompt = f"""
        Jesteś surowym ekspertem rynku aut używanych w województwie mazowieckim.
        Analizujesz ofertę: {car.marka} {car.model}, Rok: {car.rok}, Cena: {car.cena} PLN.
        
        FAKTY Z BAZY DANYCH: {info_z_bazy}
        
        Twoje zadanie:
        1. Jeśli cena {car.cena} jest niższa niż rynkowa -> daj wysoką ocenę (Super Cena).
        2. Jeśli jest wyższa -> napisz wprost, że drogo.
        3. W polu "sample_size" WPISZ PRAWDĘ. Jeśli baza lokalna jest pusta, napisz "Analiza ogólnopolska (Mazowieckie)". Jeśli są auta w bazie, napisz np. "Porównano z 3 ofertami w Radomiu".
        
        Zwróć TYLKO JSON:
        {{
            "score": (liczba 1-100),
            "label": (np. "SUPER OKAZJA", "UCZCIWA CENA", "POWYŻEJ ŚREDNIEJ", "DROGO"),
            "color": ("success", "warning", "info" lub "danger"),
            "sample_size": (Tutaj wpisz tekst o próbce danych),
            "market_info": (Krótkie uzasadnienie dla klienta, np. "Tańszy o 15% od średniej w regionie" lub "Unikatowy model w Radomiu")
        }}
        """
        
        response = model_ai.generate_content(prompt)
        clean_json = response.text.replace('```json', '').replace('```', '').strip()
        
        # Walidacja JSON
        data = json.loads(clean_json)
        
        car.ai_label = clean_json
        car.ai_valuation_data = datetime.now().strftime("%Y-%m-%d")
        db.session.commit()
    except Exception as e:
        print(f"AI Error: {e}")

@app.template_filter('from_json')
def from_json_filter(value):
    try: return json.loads(value)
    except: return None

def send_reset_email(user):
    token = user.get_reset_token()
    msg = Message('Reset Hasła - Giełda Radom', recipients=[user.email])
    msg.body = f'''Aby zresetować hasło, kliknij w poniższy link:
{url_for('reset_token', token=token, _external=True)}

Jeśli to nie Ty prosiłeś o reset, zignoruj tę wiadomość.
'''
    mail.send(msg)

# --- TRASY GOOGLE LOGIN ---
@app.route('/login/google')
def google_login():
    if not google:
        flash("Logowanie Google nie jest skonfigurowane (brak kluczy w sekrety.py)", "danger")
        return redirect(url_for('login'))
    return google.authorize_redirect(url_for('google_callback', _external=True))

@app.route('/login/google/callback')
def google_callback():
    if not google:
        return "Google Login Error", 500
    try:
        token = google.authorize_access_token()
        user_info = google.get('userinfo').json()
        
        email = user_info.get('email')
        google_id = user_info.get('id')
        name = user_info.get('name') or email.split('@')[0]
        picture = user_info.get('picture') 

        # Sprawdź czy użytkownik istnieje (po emailu lub google_id)
        user = User.query.filter((User.email == email) | (User.google_id == google_id)).first()

        if not user:
            # Rejestracja nowego użytkownika
            random_pass = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
            
            base_username = name.replace(' ', '')
            username = base_username
            counter = 1
            while User.query.filter_by(username=username).first():
                username = f"{base_username}{counter}"
                counter += 1

            user = User(
                username=username,
                email=email,
                google_id=google_id,
                password_hash=generate_password_hash(random_pass),
                avatar_url=picture,
                lokalizacja='Radom'
            )
            db.session.add(user)
            db.session.commit()
            flash(f'Konto utworzone pomyślnie! Witaj {username}.', 'success')
        else:
            # Linkowanie konta i aktualizacja zdjęcia
            changed = False
            if not user.google_id:
                user.google_id = google_id
                changed = True
            if picture and user.avatar_url != picture:
                user.avatar_url = picture
                changed = True
            
            if changed: db.session.commit()

        login_user(user)
        return redirect(url_for('profil'))

    except Exception as e:
        print(f"Google Login Error: {e}")
        flash('Błąd logowania przez Google. Spróbuj ponownie.', 'danger')
        return redirect(url_for('login'))

# --- GŁÓWNE TRASY APLIKACJI ---

@app.route('/')
def index():
    q = request.args.get('q', '').strip()
    query = Car.query
    
    # Wyszukiwanie
    if q:
        terms = q.split()
        conditions = []
        for term in terms:
            conditions.append(or_(
                Car.marka.icontains(term), 
                Car.model.icontains(term), 
                Car.paliwo.icontains(term), 
                Car.typ.icontains(term),
                Car.rok.cast(db.String).icontains(term)
            ))
        query = query.filter(and_(*conditions))
    
    # Filtry
    cat = request.args.get('typ', '')
    if cat: query = query.filter(Car.typ == cat)
    
    paliwo = request.args.get('paliwo', '')
    if paliwo: query = query.filter(Car.paliwo == paliwo)
    
    skrzynia = request.args.get('skrzynia', '')
    if skrzynia: query = query.filter(Car.skrzynia == skrzynia)
    
    max_cena = request.args.get('max_cena', type=float)
    if max_cena: query = query.filter(Car.cena <= max_cena)
    
    max_przebieg = request.args.get('max_przebieg', type=int)
    if max_przebieg: query = query.filter(Car.przebieg <= max_przebieg)

    # Sortowanie: Promowane pierwsze, potem najnowsze
    cars = query.order_by(Car.is_promoted.desc(), Car.data_dodania.desc()).limit(100).all()
    return render_template('index.html', cars=cars, now=datetime.utcnow())

@app.route('/szukaj')
def szukaj():
    # Pobieramy parametry
    marka = request.args.get('marka', '').strip()
    model = request.args.get('model', '').strip()
    ai_ocena = request.args.get('ai_ocena', '')
    paliwo = request.args.get('paliwo', '')
    skrzynia = request.args.get('skrzynia', '')
    nadwozie = request.args.get('nadwozie', '')
    kolor = request.args.get('kolor', '').strip() # ---✅ NOWE
    
    # Liczbowe
    cena_min = request.args.get('cena_min', type=float)
    cena_max = request.args.get('cena_max', type=float)
    rok_min = request.args.get('rok_min', type=int)
    rok_max = request.args.get('rok_max', type=int)
    moc_min = request.args.get('moc_min', type=int) # ---✅ NOWE
    
    query = Car.query

    # Filtrowanie tekstowe
    if marka: query = query.filter(Car.marka.icontains(marka))
    if model: query = query.filter(Car.model.icontains(model))
    if kolor: query = query.filter(Car.kolor.icontains(kolor)) # ---✅ NOWE
    if ai_ocena: query = query.filter(Car.ai_label.contains(ai_ocena))
    
    # Filtrowanie ścisłe (select)
    if paliwo: query = query.filter(Car.paliwo == paliwo)
    if skrzynia: query = query.filter(Car.skrzynia == skrzynia)
    if nadwozie: query = query.filter(Car.nadwozie == nadwozie)
    
    # Filtrowanie liczbowe
    if cena_min: query = query.filter(Car.cena >= cena_min)
    if cena_max: query = query.filter(Car.cena <= cena_max)
    if rok_min: query = query.filter(Car.rok >= rok_min)
    if rok_max: query = query.filter(Car.rok <= rok_max)
    if moc_min: query = query.filter(Car.moc >= moc_min) # ---✅ NOWE (Szukamy aut, które mają WIĘCEJ niż wpisana moc)
    
    # Sortowanie
    cars = query.order_by(Car.is_promoted.desc(), Car.data_dodania.desc()).limit(100).all()
    
    return render_template('szukaj.html', cars=cars, now=datetime.utcnow(), args=request.args)


@app.route('/ogloszenie/<int:car_id>')
def car_details(car_id):
    car = Car.query.get_or_404(car_id)
    
    # Licznik wyświetleń
    if car.views is None: car.views = 0
    car.views += 1
    
    # Sprawdzenie czy odświeżyć wycenę AI (co 3 dni - ZMODYFIKOWANE)
    should_update = False
    if not car.ai_valuation_data or not car.ai_label:
        should_update = True
    else:
        try:
            last_check = datetime.strptime(car.ai_valuation_data, "%Y-%m-%d")
            if (datetime.now() - last_check).days >= 3:
                should_update = True
        except:
            should_update = True
            
    if should_update and model_ai:
        try:
            update_market_valuation(car)
        except:
            pass
            
    db.session.commit()
    return render_template('details.html', car=car, now=datetime.utcnow())

@app.route('/profil')
@login_required
def profil():
    # Dane dla Admina
    user_count = 0
    online_count = 0
    total_views = 0
    all_users = []
    
    if current_user.username == 'admin' or current_user.id == 1:
        cars = Car.query.order_by(Car.data_dodania.desc()).all()
        all_users = User.query.all() 
        user_count = len(all_users)
        try:
            active_since = datetime.utcnow() - timedelta(minutes=5)
            online_count = User.query.filter(User.last_seen >= active_since).count()
        except:
            online_count = 1
        total_views = db.session.query(db.func.sum(Car.views)).scalar() or 0
    else:
        cars = Car.query.filter_by(user_id=current_user.id).order_by(Car.data_dodania.desc()).all()
        
    favorites = Favorite.query.filter_by(user_id=current_user.id).all()
    
    return render_template('profil.html', cars=cars, favorites=favorites, now=datetime.utcnow(), 
                           user_count=user_count, online_count=online_count, total_views=total_views, all_users=all_users)

@app.route('/dodaj', methods=['POST'])
@login_required
def dodaj_ogloszenie():
    files = request.files.getlist('zdjecia')
    saved_paths = []
    
    # Obsługa zdjęcia ze skanera
    if 'scan_image_cam' in request.files and request.files['scan_image_cam'].filename != '':
        saved_paths.append(url_for('static', filename='uploads/' + save_optimized_image(request.files['scan_image_cam'])))
    elif 'scan_image_file' in request.files and request.files['scan_image_file'].filename != '':
        saved_paths.append(url_for('static', filename='uploads/' + save_optimized_image(request.files['scan_image_file'])))
        
    # Obsługa zdjęć z galerii
    for file in files[:18]:
        if file and allowed_file(file.filename):
            saved_paths.append(url_for('static', filename='uploads/' + save_optimized_image(file)))
            
    main_img = saved_paths[0] if saved_paths else 'https://placehold.co/600x400?text=Brak+Zdjecia'
    
    try: lat = float(request.form.get('lat')) 
    except: lat = None
    try: lon = float(request.form.get('lon')) 
    except: lon = None
    
    wyposazenie_list = request.form.getlist('wyposazenie')
    wyposazenie_str = ",".join(wyposazenie_list)

    new_car = Car(
        marka=request.form.get('marka'),
        model=request.form.get('model'),
        rok=int(request.form.get('rok') or 0),
        cena=float(request.form.get('cena') or 0),
        typ=request.form.get('typ', 'Osobowe'),
        opis=request.form.get('opis', ''),
        vin=request.form.get('vin'),
        telefon=request.form.get('telefon'),
        skrzynia=request.form.get('skrzynia'),
        paliwo=request.form.get('paliwo'),
        nadwozie=request.form.get('nadwozie'),
        wyposazenie=wyposazenie_str,
        pojemnosc=request.form.get('pojemnosc'),
        przebieg=int(request.form.get('przebieg') or 0),
        # --- ZAPISUJEMY MOC I KOLOR ---
        moc=int(request.form.get('moc') or 0), 
        kolor=request.form.get('kolor'),
        # -----------------------------
        img=main_img,
        zrodlo=current_user.lokalizacja,
        user_id=current_user.id,
        latitude=lat,
        longitude=lon,
        data_dodania=datetime.utcnow()
    )
    db.session.add(new_car)
    db.session.flush() # Pobierz ID
    
    # Zapisz dodatkowe zdjęcia
    for p in saved_paths:
        db.session.add(CarImage(image_path=p, car_id=new_car.id))
        
    db.session.commit()
    flash('Dodano ogłoszenie!', 'success')
    return redirect(url_for('profil'))

@app.route('/api/analyze-car', methods=['POST'])
@login_required
def analyze_car():
    # Sprawdź limity
    dzisiaj = datetime.utcnow().date()
    if current_user.last_ai_request_date != dzisiaj:
        current_user.ai_requests_today = 0
        current_user.last_ai_request_date = dzisiaj
        db.session.commit()

    if current_user.username == 'admin' or current_user.id == 1:
        LIMIT = 500
    else:
        LIMIT = 6

    if current_user.ai_requests_today >= LIMIT:
        return jsonify({"error": f"Osiągnięto dzienny limit AI ({LIMIT}). Wróć jutro!"}), 429

    file = request.files.get('scan_image')
    if not file:
        return jsonify({"error": "Brak pliku"}), 400

    try:
        image_data = file.read()
        # --- ZMODYFIKOWANY PROMPT DLA AI (MOC, KOLOR, REFLEKTORY) ---
        prompt = """
        Jesteś ekspertem motoryzacyjnym. Przeanalizuj zdjęcie pojazdu.
        
        Twoje zadania:
        1. Rozpoznaj markę, model, typ nadwozia i przybliżony rok.
        2. Rozpoznaj KOLOR (np. Czarny Metalik, Biała Perła).
        3. WYGLĄD: Czy auto ma felgi aluminiowe (Alufelgi)? Czy ma reflektory soczewkowe/LED/Xenon (Światła LED)?
        4. MOC: Na podstawie modelu i wyglądu (np. wersja GTI, RS, lub zwykła) OSZACUJ typową moc (KM) dla tego auta. Wpisz najpopularniejszą wartość (np. 150).
        5. Stwórz profesjonalny opis handlowy.
        
        Zwróć TYLKO czysty JSON:
        { 
            "kategoria": "Osobowe/SUV/Minivan/Ciezarowe/Moto",
            "marka": "String", 
            "model": "String", 
            "rok_sugestia": Integer, 
            "paliwo_sugestia": "Diesel/Benzyna/LPG", 
            "typ_nadwozia": "String", 
            "kolor": "String",       
            "moc_sugestia": Integer,
            "wyposazenie_wykryte": ["Alufelgi", "Światła LED"], 
            "opis_wizualny": "String" 
        }
        Jeśli nie wykryjesz alufelg lub LED, nie wpisuj ich do listy 'wyposazenie_wykryte'.
        """
        resp = model_ai.generate_content([prompt, {"mime_type": file.mimetype, "data": image_data}])
        text_response = resp.text.replace('```json', '').replace('```', '').strip()
        data = json.loads(text_response)
        
        current_user.ai_requests_today += 1
        db.session.commit()
        return jsonify(data)
    except Exception as e:
        print(f"Błąd AI: {e}")
        return jsonify({"error": "Nie udało się przeanalizować zdjęcia."}), 500

@app.route('/api/generuj-opis', methods=['POST'])
@login_required
def generuj_opis_ai():
    if not model_ai: return jsonify({"opis": "Błąd AI"}), 500
    if not check_ai_limit(): return jsonify({"opis": "Limit wyczerpany"}), 429
    
    data = request.json
    try:
        prompt = f"Opisz przedmiot: {data}. Styl: zachęcający, profesjonalny handlarz."
        resp = model_ai.generate_content(prompt)
        current_user.ai_requests_today += 1
        db.session.commit()
        return jsonify({"opis": resp.text.strip()})
    except:
        return jsonify({"opis": "Błąd generowania"}), 500

@app.route('/usun/<int:car_id>', methods=['POST'])
@login_required
def delete_car(car_id):
    c = Car.query.get(car_id)
    if c and (c.user_id == current_user.id or current_user.username=='admin'):
        db.session.delete(c)
        db.session.commit()
    return redirect('/profil')

@app.route('/odswiez/<int:car_id>', methods=['POST'])
@login_required
def refresh_car(car_id):
    c = Car.query.get(car_id)
    if c and (c.user_id == current_user.id or current_user.username=='admin'):
        c.data_dodania = datetime.utcnow()
        db.session.commit()
    return redirect('/profil')

@app.route('/toggle_favorite/<int:car_id>')
@login_required
def toggle_favorite(car_id):
    fav = Favorite.query.filter_by(user_id=current_user.id, car_id=car_id).first()
    if fav:
        db.session.delete(fav)
    else:
        db.session.add(Favorite(user_id=current_user.id, car_id=car_id))
    db.session.commit()
    return redirect(request.referrer)

# --- REJESTRACJA I LOGOWANIE ---
@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        u = User.query.filter_by(username=request.form['username']).first()
        if u and check_password_hash(u.password_hash, request.form['password']):
            login_user(u)
            return redirect(url_for('profil'))
        flash('Błędny login lub hasło', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method=='POST':
        if User.query.filter_by(username=request.form['username']).first():
            flash('Nazwa zajęta', 'danger')
        elif User.query.filter_by(email=request.form['email']).first():
            flash('Email zajęty', 'danger')
        else:
            db.session.add(User(username=request.form['username'], email=request.form['email'], 
                                password_hash=generate_password_hash(request.form['password'])))
            db.session.commit()
            flash('Konto założone! Zaloguj się.', 'success')
            return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
def logout():
    logout_user()
    return redirect('/')

# --- RESET HASŁA ---
@app.route("/reset_password", methods=['GET', 'POST'])
def reset_request():
    if current_user.is_authenticated:
        return redirect(url_for('profil'))
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        if user:
            send_reset_email(user)
            flash('Wysłano email z instrukcją resetu.', 'info')
            return redirect(url_for('login'))
        else:
            flash('Nie ma konta z takim emailem.', 'warning')
    return render_template('reset_request.html')

@app.route("/reset_password/<token>", methods=['GET', 'POST'])
def reset_token(token):
    if current_user.is_authenticated:
        return redirect(url_for('profil'))
    user = User.verify_reset_token(token)
    if user is None:
        flash('Link jest nieprawidłowy lub wygasł.', 'warning')
        return redirect(url_for('reset_request'))
    if request.method == 'POST':
        password = request.form.get('password')
        user.password_hash = generate_password_hash(password)
        db.session.commit()
        flash('Hasło zostało zmienione! Możesz się zalogować.', 'success')
        return redirect(url_for('login'))
    return render_template('reset_token.html')

# --- STRONY STATYCZNE ---
@app.route('/kontakt')
def kontakt(): return render_template('kontakt.html')
@app.route('/regulamin')
def regulamin(): return render_template('regulamin.html')
@app.route('/polityka')
def polityka(): return render_template('polityka.html')

# --- EDYCJA OGŁOSZENIA ---
@app.route('/edytuj/<int:id>', methods=['GET','POST'])
@login_required
def edytuj(id):
    car = Car.query.get_or_404(id)
    if car.user_id != current_user.id and current_user.username != 'admin':
        flash('Brak uprawnień.', 'danger')
        return redirect('/')
        
    if request.method == 'POST':
        try:
            car.marka = request.form.get('marka')
            car.model = request.form.get('model')
            car.vin = request.form.get('vin')
            car.cena = float(request.form.get('cena') or 0)
            car.rok = int(request.form.get('rok') or 0)
            car.przebieg = int(request.form.get('przebieg') or 0)
            # --- AKTUALIZACJA MOCY I KOLORU PRZY EDYCJI ---
            car.moc = int(request.form.get('moc') or 0)
            car.kolor = request.form.get('kolor')
            # ----------------------------------------------
            car.paliwo = request.form.get('paliwo')
            car.skrzynia = request.form.get('skrzynia')
            car.typ = request.form.get('typ')
            car.pojemnosc = request.form.get('pojemnosc')
            car.nadwozie = request.form.get('nadwozie')
            car.telefon = request.form.get('telefon')
            car.opis = request.form.get('opis')
            
            wyposazenie_list = request.form.getlist('wyposazenie')
            car.wyposazenie = ",".join(wyposazenie_list)
            
            files = request.files.getlist('zdjecia')
            for file in files:
                if file and allowed_file(file.filename):
                    filename = save_optimized_image(file)
                    db.session.add(CarImage(image_path=url_for('static', filename='uploads/'+filename), car_id=car.id))
            
            db.session.commit()
            flash('Zapisano zmiany!', 'success')
            return redirect('/profil')
        except Exception as e:
            print(f"Błąd edycji: {e}")
            flash('Wystąpił błąd podczas zapisu.', 'danger')
            
    return render_template('edytuj.html', car=car)

# --- NARZĘDZIA ADMINA ---
@app.route('/admin/backup-db')
@login_required
def backup_db():
    if current_user.username != 'admin': abort(403)
    return send_from_directory('instance', 'gielda.db', as_attachment=True)

@app.route('/admin/full-backup')
@login_required
def full_backup():
    if current_user.username != 'admin': abort(403)
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        if os.path.exists('instance/gielda.db'):
            zf.write('instance/gielda.db', 'gielda.db')
        for root, dirs, files in os.walk('static/uploads'):
            for file in files:
                zf.write(os.path.join(root, file), os.path.join('uploads', file))
    memory_file.seek(0)
    return send_file(memory_file, download_name='backup_full.zip', as_attachment=True)

@app.route('/admin/usun_user/<int:user_id>', methods=['POST'])
@login_required
def admin_delete_user(user_id):
    if current_user.username != 'admin' and current_user.id != 1: return redirect('/')
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id: return redirect('/profil')
    db.session.delete(user)
    db.session.commit()
    flash(f'Usunięto użytkownika {user.username}.', 'success')
    return redirect('/profil')

@app.route('/usun_zdjecie/<int:image_id>', methods=['POST'])
@login_required
def usun_zdjecie(image_id):
    img = CarImage.query.get_or_404(image_id)
    # Sprawdzenie uprawnień
    car = Car.query.get(img.car_id)
    if car.user_id != current_user.id and current_user.username != 'admin':
        return jsonify({'success': False, 'message': 'Brak uprawnień'}), 403
        
    db.session.delete(img)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/usun_konto', methods=['POST'])
@login_required
def usun_konto():
    try:
        db.session.delete(current_user)
        db.session.commit()
        logout_user()
        flash('Konto usunięte.', 'info')
        return redirect('/')
    except:
        flash('Błąd usuwania.', 'danger')
        return redirect('/profil')

# --- SITEMAP I SEO ---
@app.route('/sitemap.xml')
def sitemap():
    base = request.url_root.rstrip('/')
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    # Statyczne
    for p in ['', 'login', 'register', 'kontakt', 'regulamin']:
        xml += f'<url><loc>{base}/{p}</loc><changefreq>weekly</changefreq></url>\n'
    # Dynamiczne (Auta)
    for car in Car.query.order_by(Car.data_dodania.desc()).all():
        xml += f'<url><loc>{base}/ogloszenie/{car.id}</loc><changefreq>daily</changefreq></url>\n'
    xml += '</urlset>'
    return make_response(xml, 200, {'Content-Type': 'application/xml'})

@app.route('/robots.txt')
def robots():
    txt = f"User-agent: *\nAllow: /\nSitemap: {request.url_root.rstrip('/')}/sitemap.xml"
    return make_response(txt, 200, {'Content-Type': 'text/plain'})

# --- INICJALIZACJA BAZY (MIGRACJE) ---
def update_db():
    with app.app_context():
        db_path = 'instance/gielda.db' 
        if not os.path.exists(db_path): db_path = 'gielda.db'
        
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        
        # Lista kolumn do sprawdzenia/dodania
        columns_to_add = [
            ("car", "latitude", "FLOAT"),
            ("car", "longitude", "FLOAT"),
            ("car", "vin", "TEXT"),
            ("car", "wyposazenie", "TEXT"),
            ("user", "last_seen", "TIMESTAMP"),
            ("user", "google_id", "TEXT"),
            ("user", "avatar_url", "TEXT"),
            ("car", "moc", "INTEGER"),   # ---✅ MOC
            ("car", "kolor", "TEXT")     # ---✅ KOLOR
        ]
        
        for table, col, dtype in columns_to_add:
            try:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {dtype}")
            except:
                pass # Kolumna już istnieje
                
        conn.commit()
        conn.close()

if __name__ == '__main__':
    update_db()
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000)
