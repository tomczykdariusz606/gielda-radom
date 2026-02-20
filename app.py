import os
import uuid
import zipfile
import io
import json
import sqlite3
import random
import string
import shutil
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
RENDERS_360_FOLDER = os.path.join(UPLOAD_FOLDER, '360_renders')
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
    try: model_ai = genai.GenerativeModel('gemini-3-flash-preview') # Lub 'gemini-pro' zależnie od dostępności
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

# --- TŁUMACZENIA (Słownik Rozbudowany) ---
TRANSLATIONS = {
    'pl': {
        'search_ph': 'Wpisz np. Audi A4, Automat...', 'btn_search': 'SZUKAJ', 'filters': 'Filtry', 
        'cat': 'Kategoria', 'fuel': 'Paliwo', 'gear': 'Skrzynia', 'year': 'Rok od', 'price': 'Cena do', 'mileage': 'Przebieg do', 
        'all': 'Wszystkie', 'man': 'Manualna', 'auto': 'Automatyczna', 'available': 'Dostępne Oferty', 'found': 'Znaleziono',
        'add': 'WYSTAW OGŁOSZENIE', 'login': 'LOGOWANIE', 'logout': 'Wyloguj', 'account': 'Konto',
        'garage': 'Twój Garaż', 'limit': 'Limit AI', 'days_left': 'dni', 'expired': 'WYGASŁO',
        'scan_cam': 'SKANUJ (APARAT)', 'scan_file': 'WGRAJ (PLIK)', 'desc_ai': 'Opis Generowany przez Eksperta AI',
        'welcome_back': 'Witaj ponownie', 'login_desc': 'Zaloguj się, aby zarządzać ofertami',
        'password': 'Hasło', 'forgot_pass': 'Zapomniałeś hasła?', 'login_btn': 'ZALOGUJ SIĘ',
        'no_acc': 'Nie masz jeszcze konta?', 'create_acc': 'ZAŁÓŻ KONTO', 'back_home': 'Wróć na stronę główną',
        'private_person': 'Osoba Prywatna', 'company': 'Firma', 'company_name': 'Nazwa Firmy',
        'your_ads': 'TWOJE OGŁOSZENIA', 'observed': 'OBSERWOWANE OFERTY', 'empty_garage': 'Garaż jest pusty',
        'no_favorites': 'Nie obserwujesz jeszcze żadnych ogłoszeń.', 'see_details': 'ZOBACZ',
        'contact': 'Kontakt', 'search': 'Szukaj', 'add_car': 'DODAJ SWOJE AUTO',
        'car_passenger': 'Osobowe', 'car_suv': 'SUV', 'car_minivan': 'Minivan', 'car_bus': 'Bus/Dostawcze', 'car_moto': 'Moto/Rower', 'car_other': 'Inne',
        'photos': 'ZDJĘCIA', 'max': 'MAX', 'brand': 'Marka', 'model': 'Model', 'vin': 'VIN', 'year_prod': 'Rok produkcji', 'price_ad': 'Cena', 'mileage_ad': 'Przebieg',
        'power': 'Moc (KM)', 'color': 'Kolor', 'engine_cap': 'Pojemność', 'phone': 'Telefon', 'desc': 'Opis',
        'equip': 'WYPOSAŻENIE (Zaznacz opcje)', 'petrol': 'Benzyna', 'diesel': 'Diesel', 'hybrid': 'Hybryda', 'electric': 'Elektryczny', 'lpg': 'LPG',
        # --- NOWE DO REJESTRACJI ---
        'create_acc_desc': 'Wystawiaj auta za darmo i korzystaj z AI', 'reg_google': 'Zarejestruj przez Google', 'or_manual': 'LUB RĘCZNIE',
        'username_label': 'Nazwa użytkownika (Login)', 'username_ph': 'np. JanKowalski',
        'email_label': 'Adres E-mail', 'email_ph': 'np. jan@gmail.com',
        'password_label': 'Hasło (Minimum 5 znaków)', 'password_ph': '••••••••',
        'country': 'Kraj', 'city': 'Miasto', 'city_ph': 'np. Radom', 'acc_type': 'Typ konta', 'company_ph': 'np. Auto-Handel Kowalski',
        'gemini_title': 'Powered by Gemini AI', 'gemini_desc_1': 'Wyceny aut, analiza uszkodzeń ze zdjęć i generowanie opisów.', 'gemini_desc_2': 'Zyskujesz to za darmo po założeniu konta!',
        'already_have_acc': 'Masz już konto?',
        'country_pl': 'Polska', 'country_de': 'Niemcy', 'country_be': 'Belgia', 'country_nl': 'Holandia', 'country_fr': 'Francja', 'country_other': 'Inny'
    },
    'en': {
        'search_ph': 'E.g. Audi A4, Automatic...', 'btn_search': 'SEARCH', 'filters': 'Filters', 
        'cat': 'Category', 'fuel': 'Fuel', 'gear': 'Transmission', 'year': 'Year from', 'price': 'Price to', 'mileage': 'Mileage to', 
        'all': 'All', 'man': 'Manual', 'auto': 'Automatic', 'available': 'Available Offers', 'found': 'Found',
        'add': 'POST AN AD', 'login': 'LOGIN', 'logout': 'Logout', 'account': 'Account',
        'garage': 'Your Garage', 'limit': 'AI Limit', 'days_left': 'days left', 'expired': 'EXPIRED',
        'scan_cam': 'SCAN (CAMERA)', 'scan_file': 'UPLOAD (FILE)', 'desc_ai': 'Description Generated by AI Expert',
        'welcome_back': 'Welcome Back', 'login_desc': 'Login to manage your listings',
        'password': 'Password', 'forgot_pass': 'Forgot password?', 'login_btn': 'LOGIN',
        'no_acc': 'No account yet?', 'create_acc': 'REGISTER', 'back_home': 'Back to Home',
        'private_person': 'Private Person', 'company': 'Company', 'company_name': 'Company Name',
        'your_ads': 'YOUR ADS', 'observed': 'WATCHLIST', 'empty_garage': 'Garage is empty',
        'no_favorites': 'You are not watching any ads yet.', 'see_details': 'VIEW',
        'contact': 'Contact', 'search': 'Search', 'add_car': 'ADD YOUR CAR',
        'car_passenger': 'Passenger', 'car_suv': 'SUV', 'car_minivan': 'Minivan', 'car_bus': 'Van', 'car_moto': 'Moto/Bike', 'car_other': 'Other',
        'photos': 'PHOTOS', 'max': 'MAX', 'brand': 'Brand', 'model': 'Model', 'vin': 'VIN', 'year_prod': 'Year', 'price_ad': 'Price', 'mileage_ad': 'Mileage',
        'power': 'Power (HP)', 'color': 'Color', 'engine_cap': 'Engine (CC)', 'phone': 'Phone', 'desc': 'Description',
        'equip': 'EQUIPMENT (Check options)', 'petrol': 'Petrol', 'diesel': 'Diesel', 'hybrid': 'Hybrid', 'electric': 'Electric', 'lpg': 'LPG',
        # --- NOWE DO REJESTRACJI ---
        'create_acc_desc': 'List cars for free and use AI tools', 'reg_google': 'Register with Google', 'or_manual': 'OR MANUALLY',
        'username_label': 'Username', 'username_ph': 'e.g. JohnDoe',
        'email_label': 'Email Address', 'email_ph': 'e.g. john@gmail.com',
        'password_label': 'Password (Min 5 chars)', 'password_ph': '••••••••',
        'country': 'Country', 'city': 'City', 'city_ph': 'e.g. Warsaw', 'acc_type': 'Account Type', 'company_ph': 'e.g. Auto-Trade John',
        'gemini_title': 'Powered by Gemini AI', 'gemini_desc_1': 'Car valuations, visual damage analysis and description generation.', 'gemini_desc_2': 'All this for free after registration!',
        'already_have_acc': 'Already have an account?',
        'country_pl': 'Poland', 'country_de': 'Germany', 'country_be': 'Belgium', 'country_nl': 'Netherlands', 'country_fr': 'France', 'country_other': 'Other'
    },
    'de': {
        'search_ph': 'Z.B. Audi A4, Automatik...', 'btn_search': 'SUCHEN', 'filters': 'Filter', 
        'cat': 'Kategorie', 'fuel': 'Kraftstoff', 'gear': 'Getriebe', 'year': 'Baujahr ab', 'price': 'Preis bis', 'mileage': 'KM bis', 
        'all': 'Alle', 'man': 'Schaltgetriebe', 'auto': 'Automatik', 'available': 'Verfügbare Angebote', 'found': 'Gefunden',
        'add': 'ANZEIGE AUFGEBEN', 'login': 'ANMELDEN', 'logout': 'Abmelden', 'account': 'Konto',
        'garage': 'Deine Garage', 'limit': 'AI Limit', 'days_left': 'Tage übrig', 'expired': 'ABGELAUFEN',
        'scan_cam': 'SCAN (KAMERA)', 'scan_file': 'HOCHLADEN (DATEI)', 'desc_ai': 'Beschreibung vom AI-Experten',
        'welcome_back': 'Willkommen zurück', 'login_desc': 'Einloggen um Angebote zu verwalten',
        'password': 'Passwort', 'forgot_pass': 'Passwort vergessen?', 'login_btn': 'ANMELDEN',
        'no_acc': 'Noch kein Konto?', 'create_acc': 'REGISTRIEREN', 'back_home': 'Zurück zur Startseite',
        'private_person': 'Privatperson', 'company': 'Firma', 'company_name': 'Firmenname',
        'your_ads': 'DEINE ANZEIGEN', 'observed': 'BEOBACHTET', 'empty_garage': 'Garage ist leer',
        'no_favorites': 'Sie beobachten noch keine Anzeigen.', 'see_details': 'ANSEHEN',
        'contact': 'Kontakt', 'search': 'Suchen', 'add_car': 'AUTO HINZUFÜGEN',
        'car_passenger': 'PKW', 'car_suv': 'SUV', 'car_minivan': 'Minivan', 'car_bus': 'Transporter', 'car_moto': 'Motorrad', 'car_other': 'Andere',
        'photos': 'FOTOS', 'max': 'MAX', 'brand': 'Marke', 'model': 'Modell', 'vin': 'FIN', 'year_prod': 'Baujahr', 'price_ad': 'Preis', 'mileage_ad': 'Kilometer',
        'power': 'Leistung (PS)', 'color': 'Farbe', 'engine_cap': 'Hubraum', 'phone': 'Telefon', 'desc': 'Beschreibung',
        'equip': 'AUSSTATTUNG', 'petrol': 'Benzin', 'diesel': 'Diesel', 'hybrid': 'Hybrid', 'electric': 'Elektro', 'lpg': 'Autogas (LPG)',
        # --- NOWE DO REJESTRACJI ---
        'create_acc_desc': 'Autos kostenlos inserieren & AI nutzen', 'reg_google': 'Mit Google registrieren', 'or_manual': 'ODER MANUELL',
        'username_label': 'Benutzername', 'username_ph': 'z.B. MaxMustermann',
        'email_label': 'E-Mail Adresse', 'email_ph': 'z.B. max@gmail.com',
        'password_label': 'Passwort (Min 5 Zeichen)', 'password_ph': '••••••••',
        'country': 'Land', 'city': 'Stadt', 'city_ph': 'z.B. Berlin', 'acc_type': 'Kontotyp', 'company_ph': 'z.B. Auto-Handel Max',
        'gemini_title': 'Powered by Gemini AI', 'gemini_desc_1': 'Fahrzeugbewertungen, Schadensanalyse und Beschreibungserstellung.', 'gemini_desc_2': 'Alles kostenlos nach der Registrierung!',
        'already_have_acc': 'Haben Sie bereits ein Konto?',
        'country_pl': 'Polen', 'country_de': 'Deutschland', 'country_be': 'Belgien', 'country_nl': 'Niederlande', 'country_fr': 'Frankreich', 'country_other': 'Andere'
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
    google_id = db.Column(db.String(100), unique=True, nullable=True)
    avatar_url = db.Column(db.String(500), nullable=True)
    
    # --- NOWE: DANE FIRMOWE I KRAJ ---
    account_type = db.Column(db.String(20), default='private') 
    company_name = db.Column(db.String(100), nullable=True)
    kraj = db.Column(db.String(50), default='Polska')
    nip = db.Column(db.String(20), nullable=True)
    adres = db.Column(db.String(200), nullable=True)
    opis_firmy = db.Column(db.Text, nullable=True)
    
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
    
    # --- NOWE: WALUTA (PLN/EUR) ---
    waluta = db.Column(db.String(10), default='PLN')
    
    opis = db.Column(db.Text, nullable=False)
    telefon = db.Column(db.String(20), nullable=False)
    img = db.Column(db.String(200), nullable=False)
    zrodlo = db.Column(db.String(50), default='Radom')
    is_360_premium = db.Column(db.Boolean, default=False) # Dodaj to tutaj!

    
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

def stabilize_360_images_premium(car_id):
    car = Car.query.get(car_id)
    # Sprawdzamy czy auto istnieje, czy model AI jest gotowy i czy są min. 6 zdjęć
    if not car or not model_ai or len(car.images) < 6:
        return False

    # Używamy Twojej konfiguracji z linii 70: static/uploads/360_renders/
    # Tworzymy podfolder dla konkretnego ID auta
    car_render_dir = os.path.join(app.config['RENDERS_360_FOLDER'], str(car_id))
    
    if not os.path.exists(car_render_dir):
        os.makedirs(car_render_dir)

    frames = car.images[:12] # Analizujemy do 12 klatek dla płynności
    
    # 1. Analiza Gemini 3 Flash Preview
    images_for_ai = []
    for f in frames:
        p = f.image_path.replace('/static/', 'static/')
        if os.path.exists(p):
            images_for_ai.append(Image.open(p))

    prompt = "Przeanalizuj te zdjęcia auta. Podaj współrzędne środka geometrycznego pojazdu dla idealnej rotacji 360."
    
    try:
        # Wykorzystujemy Twój płatny model Gemini 3
        model_ai.generate_content([prompt] + images_for_ai)
    except Exception as e:
        print(f"AI Error: {e}")

    # 2. Przetwarzanie i centrowanie zdjęć (Smart Crop 4:3)
    for idx, img_obj in enumerate(frames):
        path = img_obj.image_path.replace('/static/', 'static/')
        try:
            with Image.open(path) as img:
                img = img.convert("RGB")
                w, h = img.size
                target_w = h * (4/3)
                left = (w - target_w) / 2
                
                # Używamy najwyższej jakości skalowania (LANCZOS) i formatu WebP
                processed = img.crop((left, 0, w - left, h)).resize((1200, 900), Image.Resampling.LANCZOS)
                
                # Zapisujemy klatkę dokładnie tam, gdzie utworzyłeś folder na serwerze
                save_path = os.path.join(car_render_dir, f"frame_{idx}.webp")
                processed.save(save_path, "WEBP", quality=90)
        except Exception as e:
            print(f"Błąd przetwarzania klatki {idx}: {e}")
            continue

    # Oznaczamy w bazie, że widok 360 jest gotowy do wyświetlenia
    car.ai_valuation_data = '360_READY'
    db.session.commit()
    return True





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

    img_path = car.img
    if 'static/' in img_path:
        img_path = img_path.replace(url_for('static', filename=''), 'static/')
        if img_path.startswith('/'): img_path = img_path[1:] 
    
    image_file = None
    try:
        if os.path.exists(img_path):
            image_file = Image.open(img_path)
    except Exception as e:
        print(f"Błąd zdjęcia dla AI: {e}")

    prompt = f"""
    Jesteś rzeczoznawcą samochodowym na rynku Polskim.
    Analizujesz: {car.marka} {car.model}, Rok: {car.rok}, {car.przebieg} km, Cena: {car.cena} {car.waluta}.
    
    ZADANIA:
    1. Rynkowa Wycena (PL): Podaj realne widełki cenowe (Min-Max) i Średnią dla tego modelu w Polsce.
    2. Stan Wizualny (ze zdjęcia): Oceń stan lakieru/blacharki (1-10).
    3. Werdykt: Porównaj cenę sprzedawcy ({car.cena} {car.waluta}) do Rynku.
    
    Zwróć TYLKO JSON:
    {{
        "score": (liczba 1-100),
        "label": (np. "SUPER OKAZJA", "DOBRA CENA", "DROGO"),
        "color": ("success", "warning", "info", "danger"),
        "pl_min": (liczba - dolna granica ceny w PL),
        "pl_avg": (liczba - średnia cena w PL),
        "pl_max": (liczba - górna granica ceny w PL),
        "paint_score": (liczba 1-10),
        "paint_status": (krótki opis np. "Lakier zadbany", "Widoczne rysy"),
        "expert_comment": (Krótkie podsumowanie dla kupującego)
    }}
    """

    try:
        content = [prompt]
        if image_file: content.append(image_file)

        response = model_ai.generate_content(content)
        clean_json = response.text.replace('```json', '').replace('```', '').strip()
        
        json.loads(clean_json) 
        
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

        user = User.query.filter((User.email == email) | (User.google_id == google_id)).first()

        if not user:
            random_pass = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
            base_username = name.replace(' ', '')
            username = base_username
            counter = 1
            while User.query.filter_by(username=username).first():
                username = f"{base_username}{counter}"
                counter += 1

            # Przy logowaniu z Google domyślnie to konto prywatne
            user = User(
                username=username,
                email=email,
                google_id=google_id,
                password_hash=generate_password_hash(random_pass),
                avatar_url=picture,
                lokalizacja='Radom',
                account_type='private'
            )
            db.session.add(user)
            db.session.commit()
            flash(f'Konto utworzone pomyślnie! Witaj {username}.', 'success')
        else:
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


@app.route('/generate_360/<int:car_id>')
@login_required
def generate_360_trigger(car_id):
    # Zabezpieczenie: Tylko Ty jako Admin masz do tego dostęp
    if current_user.username != 'admin' and current_user.id != 1:
        abort(403)

    # Pobieramy ogłoszenie z bazy
    car = Car.query.get_or_404(car_id)

    # Uruchamiamy Twoją funkcję stabilizacji AI
    if stabilize_360_images_premium(car.id):
        # Oznaczamy w bazie, że status 360 jest gotowy (używając dedykowanej kolumny)
        car.is_360_premium = True
        db.session.commit()
        flash(f"Sukces! Widok 360° dla {car.marka} został wygenerowany.", "success")
    else:
        flash("Błąd: Za mało zdjęć (wymagane min. 6) lub problem z modelem AI.", "danger")

    # Powrót do profilu (garażu) po zakończeniu pracy AI
    return redirect(url_for('profil'))





@app.route('/')
def index():
    q = request.args.get('q', '').strip()
    query = Car.query
    
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

    cars = query.order_by(Car.is_promoted.desc(), Car.data_dodania.desc()).limit(100).all()
    return render_template('index.html', cars=cars, now=datetime.utcnow())

@app.route('/szukaj')
def szukaj():
    try:
        marka = request.args.get('marka', '').strip()
        model = request.args.get('model', '').strip()
        kolor = request.args.get('kolor', '').strip()
        ai_ocena = request.args.get('ai_ocena', '')
        
        paliwo = request.args.get('paliwo', '')
        skrzynia = request.args.get('skrzynia', '')
        nadwozie = request.args.get('nadwozie', '')
        
        def get_int(key):
            val = request.args.get(key)
            return int(val) if val and val.isdigit() else None
            
        def get_float(key):
            val = request.args.get(key)
            try: return float(val) if val else None
            except: return None

        cena_min = get_float('cena_min')
        cena_max = get_float('cena_max')
        rok_min = get_int('rok_min')
        rok_max = get_int('rok_max')
        moc_min = get_int('moc_min')
        przebieg_min = get_int('przebieg_min')
        przebieg_max = get_int('przebieg_max')

        query = Car.query

        if marka: query = query.filter(Car.marka.ilike(f'%{marka}%'))
        if model: query = query.filter(Car.model.ilike(f'%{model}%'))
        if kolor: query = query.filter(Car.kolor.ilike(f'%{kolor}%'))
        if ai_ocena: query = query.filter(Car.ai_label.contains(ai_ocena))
        
        if paliwo: query = query.filter(Car.paliwo == paliwo)
        if skrzynia: query = query.filter(Car.skrzynia == skrzynia)
        if nadwozie: query = query.filter(Car.nadwozie == nadwozie)
        
        if cena_min is not None: query = query.filter(Car.cena >= cena_min)
        if cena_max is not None: query = query.filter(Car.cena <= cena_max)
        if rok_min is not None: query = query.filter(Car.rok >= rok_min)
        if rok_max is not None: query = query.filter(Car.rok <= rok_max)
        
        if przebieg_min is not None: query = query.filter(Car.przebieg >= przebieg_min)
        if przebieg_max is not None: query = query.filter(Car.przebieg <= przebieg_max)
        
        if moc_min is not None: 
            query = query.filter(and_(Car.moc.isnot(None), Car.moc >= moc_min))
        
        cars = query.order_by(Car.is_promoted.desc(), Car.data_dodania.desc()).limit(100).all()
        
        return render_template('szukaj.html', cars=cars, now=datetime.utcnow(), args=request.args)

    except Exception as e:
        return f"<h1 style='color:red;padding:20px;'>BŁĄD WYSZUKIWARKI: {str(e)}</h1>"

# --- TRASA DLA PROFILU SPRZEDAWCY ---
@app.route('/sprzedawca/<int:user_id>')
def sprzedawca_oferty(user_id):
    sprzedawca = User.query.get_or_404(user_id)
    # Pobieramy auta tylko tego użytkownika
    cars = Car.query.filter_by(user_id=user_id).order_by(Car.is_promoted.desc(), Car.data_dodania.desc()).all()
    
    return render_template('sprzedawca.html', sprzedawca=sprzedawca, cars=cars, now=datetime.utcnow())
# --- NOWA TRASA ZMIANY MINIATURKI ---
@app.route('/zmien_avatar', methods=['POST'])
@login_required
def zmien_avatar():
    if 'avatar' in request.files:
        file = request.files['avatar']
        if file and allowed_file(file.filename):
            # Zapisuje obraz używając Twojej funkcji optymalizującej (WebP + Znak wodny)
            filename = save_optimized_image(file)
            if filename:
                current_user.avatar_url = url_for('static', filename='uploads/' + filename)
                db.session.commit()
                flash('Miniaturka została zaktualizowana!', 'success')
            else:
                flash('Wystąpił błąd podczas przetwarzania obrazu.', 'danger')
        else:
            flash('Nieprawidłowy format pliku.', 'warning')
    return redirect('/profil')


@app.route('/ogloszenie/<int:car_id>')
def car_details(car_id):
    car = Car.query.get_or_404(car_id)
    
    if car.views is None: car.views = 0
    car.views += 1
    
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

# --- USTAWIENIA PROFILU Z ZAPISEM DANYCH (NIP, KRAJ, ADRES) ---
@app.route('/ustawienia_profilu', methods=['POST'])
@login_required
def ustawienia_profilu():
    current_user.account_type = request.form.get('account_type', 'private')
    current_user.company_name = request.form.get('company_name', '')
    current_user.nip = request.form.get('nip', '')
    current_user.adres = request.form.get('adres', '')
    current_user.opis_firmy = request.form.get('opis_firmy', '')
    current_user.lokalizacja = request.form.get('lokalizacja', 'Radom')
    current_user.kraj = request.form.get('kraj', 'Polska')
    db.session.commit()
    flash('Dane profilu zostały zapisane!', 'success')
    return redirect('/profil')

@app.route('/dodaj', methods=['POST'])
@login_required
def dodaj_ogloszenie():
    files = request.files.getlist('zdjecia')
    saved_paths = []
    
    if 'scan_image_cam' in request.files and request.files['scan_image_cam'].filename != '':
        saved_paths.append(url_for('static', filename='uploads/' + save_optimized_image(request.files['scan_image_cam'])))
    elif 'scan_image_file' in request.files and request.files['scan_image_file'].filename != '':
        saved_paths.append(url_for('static', filename='uploads/' + save_optimized_image(request.files['scan_image_file'])))
        
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
        waluta=request.form.get('waluta', 'PLN'), # --- ZAPISYWANIE WALUTY
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
        moc=int(request.form.get('moc') or 0), 
        kolor=request.form.get('kolor'),
        img=main_img,
        zrodlo=current_user.lokalizacja,
        user_id=current_user.id,
        latitude=lat,
        longitude=lon,
        data_dodania=datetime.utcnow()
    )
    db.session.add(new_car)
    db.session.flush() 
    
    for p in saved_paths:
        db.session.add(CarImage(image_path=p, car_id=new_car.id))
        
    db.session.commit()
    flash('Dodano ogłoszenie!', 'success')
    return redirect(url_for('profil'))

@app.route('/api/analyze-car', methods=['POST'])
@login_required
def analyze_car():
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
    if c and (c.user_id == current_user.id or current_user.username == 'admin'):
        # --- USUNIĘCIE FOLDERU 360° Z SERWERA ---
        # Tworzymy ścieżkę do folderu: static/uploads/360_renders/[ID_AUTA]
        render_path = os.path.join(app.config['RENDERS_360_FOLDER'], str(car_id))
        
        try:
            if os.path.exists(render_path):
                import shutil
                shutil.rmtree(render_path) # Kasuje folder i wszystkie klatki w środku
        except Exception as e:
            print(f"Błąd usuwania folderu 360: {e}")

        db.session.delete(c)
        db.session.commit()
    return redirect('/profil')


@app.route('/odswiez/<int:car_id>', methods=['POST'])
@login_required
def refresh_car(car_id):
    c = Car.query.get(car_id)
    if c and (c.user_id == current_user.id or current_user.username == 'admin'):
        c.data_dodania = datetime.utcnow()
        if current_user.username == 'admin' or current_user.id == 1:
            c.ai_valuation_data = None 
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
            acc_type = request.form.get('account_type', 'private')
            comp_name = request.form.get('company_name', '') if acc_type == 'company' else None
            user_kraj = request.form.get('kraj', 'Polska')
            user_lokal = request.form.get('lokalizacja', 'Radom')
            
            db.session.add(User(
                username=request.form['username'], 
                email=request.form['email'], 
                password_hash=generate_password_hash(request.form['password']),
                account_type=acc_type,
                company_name=comp_name,
                kraj=user_kraj,          # Zapisywanie kraju
                lokalizacja=user_lokal   # Zapisywanie miejscowości
            ))
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
def kontakt():
    # Pobieramy język z ciasteczek (domyślnie 'pl')
    lang = request.cookies.get('lang', 'pl')
    
    # Ścieżka do pliku z tłumaczeniami
    path = os.path.join(app.root_path, 'translations', 'legal.json')
    
    try:
        with open(path, encoding='utf-8') as f:
            all_texts = json.load(f)
        # Pobieramy sekcję dla danego języka
        current_texts = all_texts.get(lang, all_texts.get('pl'))
    except Exception as e:
        print(f"Błąd wczytywania tłumaczeń: {e}")
        current_texts = {}

    # Zwracamy szablon z odpowiednimi danymi
    return render_template('kontakt.html', legal=current_texts, lang=lang)

@app.route('/regulamin')
def regulamin():
    lang = request.cookies.get('lang', 'pl')
    path = os.path.join(app.root_path, 'translations', 'legal.json')
    try:
        with open(path, encoding='utf-8') as f:
            all_texts = json.load(f)
        current_reg = all_texts.get(lang, all_texts.get('pl'))
    except:
        current_reg = {"reg_title": "Regulamin"} # Fallback

    return render_template('regulamin.html', reg=current_reg, lang=lang)

@app.route('/polityka')
def polityka_privacy():
    # Pobieramy język z ciasteczka (tak jak robisz to w inject_conf_var)
    lang = request.cookies.get('lang', 'pl')
    
    # Ścieżka do Twojego pliku z tłumaczeniami
    # Zakładamy strukturę: /twoj_projekt/translations/legal.json
    path = os.path.join(app.root_path, 'translations', 'legal.json')
    
    try:
        with open(path, encoding='utf-8') as f:
            all_texts = json.load(f)
        
        # Pobieramy sekcję dla danego języka, jeśli brak - fallback na polski
        current_legal = all_texts.get(lang, all_texts.get('pl'))
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Błąd ładowania legal.json: {e}")
        # Prosty fallback, żeby strona nie wywaliła błędu 500
        current_legal = {"title": "Polityka Prywatności", "intro": "Błąd ładowania treści."}

    return render_template('polityka.html', legal=current_legal, lang=lang)

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
            car.waluta = request.form.get('waluta', 'PLN') # --- ZAPISYWANIE WALUTY
            car.rok = int(request.form.get('rok') or 0)
            car.przebieg = int(request.form.get('przebieg') or 0)
            car.moc = int(request.form.get('moc') or 0)
            car.kolor = request.form.get('kolor')
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
    for p in ['', 'login', 'register', 'kontakt', 'regulamin']:
        xml += f'<url><loc>{base}/{p}</loc><changefreq>weekly</changefreq></url>\n'
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
        
        # --- ZAKTUALIZOWANA LISTA KOLUMN (DODANO 360 PREMIUM) ---
        columns_to_add = [
            ("car", "latitude", "FLOAT"),
            ("car", "longitude", "FLOAT"),
            ("car", "vin", "TEXT"),
            ("car", "wyposazenie", "TEXT"),
            ("user", "last_seen", "TIMESTAMP"),
            ("user", "google_id", "TEXT"),
            ("user", "avatar_url", "TEXT"),
            ("car", "moc", "INTEGER"),   
            ("car", "kolor", "TEXT"),
            ("user", "account_type", "TEXT DEFAULT 'private'"),
            ("user", "company_name", "TEXT"),
            ("car", "waluta", "TEXT DEFAULT 'PLN'"),
            ("user", "nip", "TEXT"),
            ("user", "adres", "TEXT"),
            ("user", "opis_firmy", "TEXT"),
            ("user", "kraj", "TEXT DEFAULT 'Polska'"),
            # --- NOWA KOLUMNA DLA FUNKCJI 360 ---
            ("car", "is_360_premium", "BOOLEAN DEFAULT 0") 
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
