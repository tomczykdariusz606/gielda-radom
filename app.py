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
from threading import Thread 
from apscheduler.schedulers.background import BackgroundScheduler
import atexit
 
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
VIDEOS_360_FOLDER = os.path.join(UPLOAD_FOLDER, '360_videos') # NOWY FOLDER NA MP4
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
if not os.path.exists(VIDEOS_360_FOLDER):
    os.makedirs(VIDEOS_360_FOLDER)


# --- KONFIGURACJA MAILA (HOME.PL) ---
app.config['MAIL_SERVER'] = 'serwer2602674.home.pl'
app.config['MAIL_PORT'] = 465
app.config['MAIL_USE_SSL'] = True
app.config['MAIL_USERNAME'] = 'kontakt.serwer2602674@serwer2602674.home.pl' # <--- TYLKO TO ZMIENIAMY
app.config['MAIL_PASSWORD'] = MAIL_PWD  
app.config['MAIL_DEFAULT_SENDER'] = ('Giełda Radom', 'kontakt@gieldaradom.pl') # To zostaje, żeby klienci widzieli ładny adres!


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
        'eq_tinted': 'Przyciemniane szyby',

        'eq_led_basic': 'Światła LED',
        'eq_matrix': 'Reflektory Matrix / Laser',
        'eq_rails': 'Relingi dachowe',

        'eq_cat_basic': 'PODSTAWOWE WYPOSAŻENIE', 
        'eq_cat_comfort': 'KOMFORT & DODATKI', 
        'eq_cat_premium': 'PREMIUM & NOWE TECHNOLOGIE',

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
        'create_acc_desc': 'Wystawiaj auta za darmo i korzystaj z AI', 'reg_google': 'Zarejestruj przez Google', 'or_manual': 'LUB RĘCZNIE',
        'username_label': 'Nazwa użytkownika (Login)', 'username_ph': 'np. JanKowalski',
        'email_label': 'Adres E-mail', 'email_ph': 'np. jan@gmail.com',
        'password_label': 'Hasło (Minimum 5 znaków)', 'password_ph': '••••••••',
        'country': 'Kraj', 'city': 'Miasto', 'city_ph': 'np. Radom', 'acc_type': 'Typ konta', 'company_ph': 'np. Auto-Handel Kowalski',
        'gemini_title': 'Powered by Gemini AI', 'gemini_desc_1': 'Wyceny aut, analiza uszkodzeń ze zdjęć i generowanie opisów.', 'gemini_desc_2': 'Zyskujesz to za darmo po założeniu konta!',
        'already_have_acc': 'Masz już konto?',
        'country_pl': 'Polska', 'country_de': 'Niemcy', 'country_be': 'Belgia', 'country_nl': 'Holandia', 'country_fr': 'Francja', 'country_other': 'Inny',
        'select_multiple': 'Zaznacz kilka zdjęć na raz', 'files_ready': 'gotowych zdjęć',
        
        # WYPOSAŻENIE PREMIUM (Klucze eq_)
        'eq_safety': 'BEZPIECZEŃSTWO & ASYSTENCI', 'eq_comfort': 'KOMFORT PREMIUM', 'eq_multi': 'MULTIMEDIA & TECHNOLOGIA', 'eq_exterior': 'WYGLĄD & INNE',
        'eq_abs': 'ABS', 'eq_esp': 'ESP / ASR', 'eq_airbags': 'Poduszki powietrzne', 'eq_isofix': 'Isofix', 'eq_lane': 'Asystent pasa ruchu', 'eq_blind': 'Czujnik martwego pola',
        'eq_signs': 'Rozpoznawanie znaków', 'eq_front_assist': 'Front Assist (Hamowanie)', 'eq_night_vision': 'Night Vision',
        'eq_ac': 'Klimatyzacja manualna', 'eq_climatronic': 'Klimatronik', 'eq_4zone': 'Klimatronik 4-strefowy', 'eq_leather': 'Skórzana tapicerka', 
        'eq_heated_seats': 'Podgrzewane fotele', 'eq_vent_seats': 'Wentylowane fotele', 'eq_massage': 'Fotele z masażem', 'eq_heated_steer': 'Podgrzewana kierownica',
        'eq_heated_wind': 'Podgrzewana przednia szyba', 'eq_photochrom': 'Lusterka fotochromatyczne', 'eq_windows': 'El. szyby', 'eq_mirrors': 'El. lusterka',
        'eq_cruise': 'Tempomat', 'eq_cruise_adapt': 'Tempomat aktywny (ACC)', 'eq_keyless': 'Keyless / Bezkluczykowy', 'eq_air_susp': 'Zawieszenie pneumatyczne', 'eq_soft_close': 'Dociąganie drzwi',
        'eq_navi': 'Nawigacja', 'eq_bt': 'Bluetooth / USB', 'eq_android': 'Android Auto / CarPlay', 'eq_cam_back': 'Kamera cofania', 'eq_cam_360': 'Kamera 360', 
        'eq_sensors': 'Czujniki parkowania', 'eq_park_assist': 'Asystent parkowania', 'eq_hud': 'Head-Up Display', 'eq_wireless': 'Ładowarka indukcyjna', 'eq_sound': 'Nagłośnienie Premium',
        'eq_alloys': 'Alufelgi', 'eq_led': 'Reflektory Matrix LED / Laser', 'eq_sunroof': 'Szyberdach', 'eq_pano': 'Dach panoramiczny', 'eq_trunk': 'Elektryczna klapa bagażnika', 'eq_ambient': 'Oświetlenie Ambient', 'eq_tow': 'Hak'
    },
    
    'en': {
        'eq_tinted': 'Tinted windows',

        'eq_led_basic': 'LED Headlights',
        'eq_matrix': 'Matrix / Laser Headlights',
        'eq_rails': 'Roof Rails',

        'eq_cat_basic': 'BASIC EQUIPMENT', 
        'eq_cat_comfort': 'COMFORT & ADD-ONS', 
        'eq_cat_premium': 'PREMIUM & NEW TECH',

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
        'create_acc_desc': 'List cars for free and use AI tools', 'reg_google': 'Register with Google', 'or_manual': 'OR MANUALLY',
        'username_label': 'Username', 'username_ph': 'e.g. JohnDoe',
        'email_label': 'Email Address', 'email_ph': 'e.g. john@gmail.com',
        'password_label': 'Password (Min 5 chars)', 'password_ph': '••••••••',
        'country': 'Country', 'city': 'City', 'city_ph': 'e.g. Warsaw', 'acc_type': 'Account Type', 'company_ph': 'e.g. Auto-Trade John',
        'gemini_title': 'Powered by Gemini AI', 'gemini_desc_1': 'Car valuations, visual damage analysis and description generation.', 'gemini_desc_2': 'All this for free after registration!',
        'already_have_acc': 'Already have an account?',
        'country_pl': 'Poland', 'country_de': 'Germany', 'country_be': 'Belgium', 'country_nl': 'Netherlands', 'country_fr': 'France', 'country_other': 'Other',
        'select_multiple': 'Select multiple photos at once', 'files_ready': 'photos ready',
        
        # WYPOSAŻENIE PREMIUM
        'eq_safety': 'SAFETY & ASSISTANTS', 'eq_comfort': 'PREMIUM COMFORT', 'eq_multi': 'MULTIMEDIA & TECH', 'eq_exterior': 'EXTERIOR & OTHER',
        'eq_abs': 'ABS', 'eq_esp': 'ESP / Traction Control', 'eq_airbags': 'Airbags', 'eq_isofix': 'Isofix', 'eq_lane': 'Lane Assist', 'eq_blind': 'Blind Spot Monitor',
        'eq_signs': 'Traffic Sign Recognition', 'eq_front_assist': 'Emergency Braking', 'eq_night_vision': 'Night Vision',
        'eq_ac': 'Manual A/C', 'eq_climatronic': 'Auto Climate Control', 'eq_4zone': '4-Zone Climate Control', 'eq_leather': 'Leather Seats', 
        'eq_heated_seats': 'Heated Seats', 'eq_vent_seats': 'Ventilated Seats', 'eq_massage': 'Massage Seats', 'eq_heated_steer': 'Heated Steering Wheel',
        'eq_heated_wind': 'Heated Windshield', 'eq_photochrom': 'Auto-dimming Mirrors', 'eq_windows': 'Power Windows', 'eq_mirrors': 'Power Mirrors',
        'eq_cruise': 'Cruise Control', 'eq_cruise_adapt': 'Adaptive Cruise Control', 'eq_keyless': 'Keyless Entry', 'eq_air_susp': 'Air Suspension', 'eq_soft_close': 'Soft-Close Doors',
        'eq_navi': 'Navigation System', 'eq_bt': 'Bluetooth / USB', 'eq_android': 'Android Auto / CarPlay', 'eq_cam_back': 'Backup Camera', 'eq_cam_360': '360° Camera', 
        'eq_sensors': 'Parking Sensors', 'eq_park_assist': 'Park Assist', 'eq_hud': 'Head-Up Display', 'eq_wireless': 'Wireless Charging', 'eq_sound': 'Premium Sound System',
        'eq_alloys': 'Alloy Wheels', 'eq_led': 'Matrix LED / Laser Lights', 'eq_sunroof': 'Sunroof', 'eq_pano': 'Panoramic Roof', 'eq_trunk': 'Power Trunk', 'eq_ambient': 'Ambient Lighting', 'eq_tow': 'Tow Hook'
    },
    
    'de': {
        'eq_tinted': 'Getönte Scheiben',

        'eq_led_basic': 'LED-Scheinwerfer',
        'eq_matrix': 'Matrix / Laser-Scheinwerfer',
        'eq_rails': 'Dachreling',

        'eq_cat_basic': 'BASISAUSSTATTUNG', 
        'eq_cat_comfort': 'KOMFORT & EXTRAS', 
        'eq_cat_premium': 'PREMIUM & NEUE TECHNIK',

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
        'create_acc_desc': 'Autos kostenlos inserieren & AI nutzen', 'reg_google': 'Mit Google registrieren', 'or_manual': 'ODER MANUELL',
        'username_label': 'Benutzername', 'username_ph': 'z.B. MaxMustermann',
        'email_label': 'E-Mail Adresse', 'email_ph': 'z.B. max@gmail.com',
        'password_label': 'Passwort (Min 5 Zeichen)', 'password_ph': '••••••••',
        'country': 'Land', 'city': 'Stadt', 'city_ph': 'z.B. Berlin', 'acc_type': 'Kontotyp', 'company_ph': 'z.B. Auto-Handel Max',
        'gemini_title': 'Powered by Gemini AI', 'gemini_desc_1': 'Fahrzeugbewertungen, Schadensanalyse und Beschreibungserstellung.', 'gemini_desc_2': 'Alles kostenlos nach der Registrierung!',
        'already_have_acc': 'Haben Sie bereits ein Konto?',
        'country_pl': 'Polen', 'country_de': 'Deutschland', 'country_be': 'Belgien', 'country_nl': 'Niederlande', 'country_fr': 'Frankreich', 'country_other': 'Andere',
        'select_multiple': 'Mehrere Fotos auf einmal auswählen', 'files_ready': 'Fotos bereit',
        
        # WYPOSAŻENIE PREMIUM
        'eq_safety': 'SICHERHEIT & ASSISTENZ', 'eq_comfort': 'PREMIUM KOMFORT', 'eq_multi': 'MULTIMEDIA & TECHNIK', 'eq_exterior': 'EXTERIEUR & SONSTIGES',
        'eq_abs': 'ABS', 'eq_esp': 'ESP / ASR', 'eq_airbags': 'Airbags', 'eq_isofix': 'Isofix', 'eq_lane': 'Spurhalteassistent', 'eq_blind': 'Totwinkel-Assistent',
        'eq_signs': 'Verkehrszeichenerkennung', 'eq_front_assist': 'Notbremsassistent', 'eq_night_vision': 'Nachtsichtassistent',
        'eq_ac': 'Klimaanlage manuell', 'eq_climatronic': 'Klimaautomatik', 'eq_4zone': '4-Zonen Klimaautomatik', 'eq_leather': 'Lederausstattung', 
        'eq_heated_seats': 'Sitzheizung', 'eq_vent_seats': 'Sitzbelüftung', 'eq_massage': 'Massagesitze', 'eq_heated_steer': 'Lenkradheizung',
        'eq_heated_wind': 'Beheizbare Frontscheibe', 'eq_photochrom': 'Innenspiegel autom. abblendend', 'eq_windows': 'Elektr. Fensterheber', 'eq_mirrors': 'Elektr. Seitenspiegel',
        'eq_cruise': 'Tempomat', 'eq_cruise_adapt': 'Abstandstempomat (ACC)', 'eq_keyless': 'Schlüssellose Zentralverriegelung', 'eq_air_susp': 'Luftfederung', 'eq_soft_close': 'Soft-Close-Automatik',
        'eq_navi': 'Navigationssystem', 'eq_bt': 'Bluetooth / USB', 'eq_android': 'Android Auto / CarPlay', 'eq_cam_back': 'Rückfahrkamera', 'eq_cam_360': '360°-Kamera', 
        'eq_sensors': 'Einparkhilfe', 'eq_park_assist': 'Parklenkassistent', 'eq_hud': 'Head-Up Display', 'eq_wireless': 'Induktionsladen für Smartphones', 'eq_sound': 'Premium Soundsystem',
        'eq_alloys': 'Leichtmetallfelgen', 'eq_led': 'Matrix LED / Laserlicht', 'eq_sunroof': 'Schiebedach', 'eq_pano': 'Panoramadach', 'eq_trunk': 'Elektr. Heckklappe', 'eq_ambient': 'Ambiente-Beleuchtung', 'eq_tow': 'Anhängerkupplung'
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
    is_360_premium = db.Column(db.Boolean, default=False)
    is_reserved = db.Column(db.Boolean, default=False)
    
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

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_optimized_image(file):
    if not file or not allowed_file(file.filename):
        return None
    
    try:
        ext = 'webp' 
        filename = f"{uuid.uuid4().hex}.{ext}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        # Otwieranie obrazu przez PIL i poprawa rotacji
        image = Image.open(file)
        image = ImageOps.exif_transpose(image)
        
        # Konwersja do RGBA, jeśli oryginalny obraz to wymaga (np. PNG z przezroczystością)
        if image.mode != 'RGBA':
            image = image.convert('RGBA')

        # Skalowanie głównego obrazu
        image.thumbnail((1920, 1920), Image.Resampling.LANCZOS)
        
        # --- NAKŁADANIE ZNAKU WODNEGO ---
        watermark_path = os.path.join(app.root_path, 'static', 'watermark.png')
        if os.path.exists(watermark_path):
            watermark = Image.open(watermark_path).convert("RGBA")
            
            # Dostosowanie rozmiaru znaku wodnego (np. 20% szerokości obrazu)
            wm_width = int(image.width * 0.20)
            wm_ratio = wm_width / float(watermark.width)
            wm_height = int(float(watermark.height) * float(wm_ratio))
            watermark = watermark.resize((wm_width, wm_height), Image.Resampling.LANCZOS)
            
            # Dodanie przezroczystości do znaku wodnego (np. 50%)
            alpha = watermark.split()[3]
            alpha = alpha.point(lambda p: p * 0.5)
            watermark.putalpha(alpha)
            
            # Obliczanie pozycji (np. w prawym dolnym rogu z marginesem 20px)
            margin = 20
            position = (image.width - wm_width - margin, image.height - wm_height - margin)
            
            # Nałożenie na nowy obraz kompozytowy
            transparent = Image.new('RGBA', image.size, (0,0,0,0))
            transparent.paste(image, (0,0))
            transparent.paste(watermark, position, mask=watermark)
            image = transparent
        
        # --- ZAPIS JAKO WEBP ---
        # Dla WebP trzeba zrzucić przezroczystość na czarne lub białe tło przed kompresją
        final_image = Image.new("RGB", image.size, (255, 255, 255))
        final_image.paste(image, mask=image.split()[3])
        
        final_image.save(filepath, format='WEBP', quality=80)
        
        return filename
    except Exception as e:
        print(f"Błąd zapisu i znaku wodnego: {e}")
        return None







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

# --- WYSYŁKA MAILI (POWITANIE ONBOARDING) ---
def wyslij_email_powitalny_async(app, email, username):
    with app.app_context():
        msg = Message(
            subject="Dziękuję za zaufanie! Wspólnie zmieniamy rynek aut w Radomiu 🤝",
            recipients=[email]
        )
        msg.body = f"""Cześć {username}! 👋

Piszę do Ciebie osobiście, ponieważ właśnie dołączyłeś do platformy Giełda Radom. Chciałem Ci za to bardzo serdecznie podziękować!

Tworząc ten portal, przyświecał nam jeden cel: skończyć z nudnym, ręcznym wpisywaniem danych i ułatwić lokalny handel. Jako pierwsi w Polsce zaprzęgliśmy do pracy sztuczną inteligencję (Gemini AI), która z samego zdjęcia rozpoznaje auto, generuje profesjonalny opis i tworzy kinowe widoki 360°.

Co się u nas teraz dzieje?
* Nasza baza rośnie w błyskawicznym tempie (przekroczyliśmy już 1500 aktywnych ofert na stronie!), a ruch z całego Mazowsza bije kolejne rekordy.
* Wystartowaliśmy z silną kampanią reklamową w Google, skupioną wyłącznie na naszym regionie. Ściągamy na stronę konkretnych kupców z okolicy, by ułatwić Ci szybką sprzedaż.

Masz auto na sprzedaż?
To idealny moment, żeby je dodać. Przypominam, że nasza AI odwali za Ciebie 90% roboty – wystarczy, że zrobisz zdjęcie, a system sam uzupełni model, parametry i wyposażenie w zaledwie 3 sekundy. Wszystko całkowicie za darmo.

Zaloguj się na swoje konto i przetestuj nasz skaner AI:
https://gieldaradom.pl/login

Jeszcze raz dziękuję, że tworzysz z nami nowoczesną motoryzację na Mazowszu. W razie jakichkolwiek pytań – po prostu odpisz na tę wiadomość.

Pozdrawiam serdecznie,
Dariusz
Właściciel serwisu | ADT & AI Team
https://gieldaradom.pl
"""
        try:
            mail.send(msg)
        except Exception as e:
            print(f"Błąd wysyłania powitania na {email}: {e}")

def wyslij_powitanie(email, username):
    Thread(target=wyslij_email_powitalny_async, args=(app, email, username)).start()

# --- WYSYŁKA POTWIERDZENIA DODANIA OGŁOSZENIA ---
def wyslij_potwierdzenie_ogloszenia_async(app, email, username, marka, model):
    with app.app_context():
        msg = Message(
            subject=f"🚗 Twoje ogłoszenie: {marka} {model} jest już aktywne! - Giełda Radom",
            recipients=[email]
        )
        msg.body = f"""Cześć {username}! 👋

Twoje ogłoszenie dotyczące samochodu {marka} {model} zostało pomyślnie dodane i jest już widoczne dla kupujących na Giełdzie Radom!

Krótkie podsumowanie:
✅ Pojazd: {marka} {model}
✅ Czas trwania: Twoje ogłoszenie będzie aktywne i całkowicie darmowe przez najbliższe 30 dni.

Co dalej?
W każdej chwili możesz zaktualizować cenę, dodać nowe zdjęcia, odświeżyć ofertę lub ją usunąć. Wszystko to zrobisz z poziomu swojego Garażu:
https://gieldaradom.pl/profil

Trzymamy kciuki za szybką sprzedaż! Oby telefon dzwonił bez przerwy. 😉

Pozdrawiam serdecznie,
Dariusz
Właściciel serwisu | ADT & AI Team
https://gieldaradom.pl
"""
        try:
            mail.send(msg)
        except Exception as e:
            print(f"Błąd wysyłania potwierdzenia na {email}: {e}")

def wyslij_potwierdzenie_ogloszenia(email, username, marka, model):
    if email: # Upewniamy się, że użytkownik ma podany email
        Thread(target=wyslij_potwierdzenie_ogloszenia_async, args=(app, email, username, marka, model)).start()



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
            wyslij_powitanie(user.email, user.username) # <--- DODANO WYSYŁKĘ MAILA
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
    # Zabezpieczenie: Tylko Admin
    if current_user.username != 'admin' and current_user.id != 1:
        abort(403)

    car = Car.query.get_or_404(car_id)
    
    # Tworzymy ścieżkę do pliku MP4 z numerem ID auta
    video_filename = f"{car.id}.mp4"
    video_path = os.path.join(app.root_path, 'static', 'uploads', '360_videos', video_filename)
    
    # Zamiast odpalać skrypty, serwer po prostu patrzy, czy wgrałeś przez FTP plik wideo
    if os.path.exists(video_path):
        car.is_360_premium = True
        db.session.commit()
        flash(f"Aktywowano! Wideo 360° dla {car.marka} jest już podpięte pod ogłoszenie.", "success")
    else:
        flash(f"Brak pliku! Wgraj najpierw plik o nazwie {video_filename} do folderu static/uploads/360_videos/", "danger")

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

    page = request.args.get('page', 1, type=int)
    pagination = query.order_by(Car.is_promoted.desc(), Car.data_dodania.desc()).paginate(page=page, per_page=24, error_out=False)
    
    return render_template('index.html', cars=pagination.items, pagination=pagination, now=datetime.utcnow())



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
        
        page = request.args.get('page', 1, type=int)
        pagination = query.order_by(Car.is_promoted.desc(), Car.data_dodania.desc()).paginate(page=page, per_page=24, error_out=False)
        
        return render_template('szukaj.html', cars=pagination.items, pagination=pagination, now=datetime.utcnow(), args=request.args)

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
    
    # Zmienna odpowiedzialna za to, na której stronie jesteśmy
    page = request.args.get('page', 1, type=int)
    
    if current_user.username == 'admin' or current_user.id == 1:
        # Zmiana: paginate zamiast all()
        pagination = Car.query.order_by(Car.data_dodania.desc()).paginate(page=page, per_page=24, error_out=False)
        all_users = User.query.all() 
        user_count = len(all_users)
        try:
            active_since = datetime.utcnow() - timedelta(minutes=5)
            online_count = User.query.filter(User.last_seen >= active_since).count()
        except:
            online_count = 1
        total_views = db.session.query(db.func.sum(Car.views)).scalar() or 0
    else:
        # Zmiana: paginate zamiast all() dla zwykłego usera
        pagination = Car.query.filter_by(user_id=current_user.id).order_by(Car.data_dodania.desc()).paginate(page=page, per_page=24, error_out=False)
        
    favorites = Favorite.query.filter_by(user_id=current_user.id).all()
    
    # Dodane 'pagination=pagination' oraz 'cars=pagination.items', reszta Twoja
    return render_template('profil.html', cars=pagination.items, pagination=pagination, favorites=favorites, now=datetime.utcnow(), 
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
    try:
        files = request.files.getlist('zdjecia')
        saved_paths = []
        
        # 1. BEZPIECZNE POBIERANIE SKANÓW (Ochrona przed błędem "NoneType")
        if 'scan_image_cam' in request.files and request.files['scan_image_cam'].filename != '':
            fname = save_optimized_image(request.files['scan_image_cam'])
            if fname: saved_paths.append(url_for('static', filename='uploads/' + fname))
            
        elif 'scan_image_file' in request.files and request.files['scan_image_file'].filename != '':
            fname = save_optimized_image(request.files['scan_image_file'])
            if fname: saved_paths.append(url_for('static', filename='uploads/' + fname))
            
        for file in files[:18]:
            if file and allowed_file(file.filename):
                fname = save_optimized_image(file)
                if fname: saved_paths.append(url_for('static', filename='uploads/' + fname))
                
        main_img = saved_paths[0] if saved_paths else 'https://placehold.co/600x400?text=Brak+Zdjecia'
        
        # 2. BEZPIECZNE PARSOWANIE GPS
        try: lat = float(request.form.get('lat', ''))
        except ValueError: lat = None
        
        try: lon = float(request.form.get('lon', ''))
        except ValueError: lon = None
        
        # 3. BEZPIECZNE PARSOWANIE LICZB (Odporne na spacje, przecinki i brak danych)
        cena_str = str(request.form.get('cena', '0')).replace(',', '.').replace(' ', '').strip()
        try: cena_val = float(cena_str)
        except ValueError: cena_val = 0.0

        try: rok_val = int(str(request.form.get('rok', '0')).replace(' ', '').strip() or 0)
        except ValueError: rok_val = 0

        try: przebieg_val = int(str(request.form.get('przebieg', '0')).replace(' ', '').strip() or 0)
        except ValueError: przebieg_val = 0

        try: moc_val = int(str(request.form.get('moc', '0')).replace(' ', '').strip() or 0)
        except ValueError: moc_val = 0
        
        wyposazenie_list = request.form.getlist('wyposazenie')
        wyposazenie_str = ",".join(wyposazenie_list)

        # 4. TWORZENIE NOWEGO AUTA
        new_car = Car(
            marka=request.form.get('marka', ''),
            model=request.form.get('model', ''),
            rok=rok_val,
            cena=cena_val,
            waluta=request.form.get('waluta', 'PLN'),
            typ=request.form.get('typ', 'Osobowe'),
            opis=request.form.get('opis', ''),
            vin=request.form.get('vin', ''),
            telefon=request.form.get('telefon', ''),
            skrzynia=request.form.get('skrzynia'),
            paliwo=request.form.get('paliwo'),
            nadwozie=request.form.get('nadwozie'),
            wyposazenie=wyposazenie_str,
            pojemnosc=request.form.get('pojemnosc', ''),
            przebieg=przebieg_val,
            moc=moc_val, 
            kolor=request.form.get('kolor', ''),
            img=main_img,
            zrodlo=current_user.lokalizacja,
            user_id=current_user.id,
            latitude=lat,
            longitude=lon,
            data_dodania=datetime.utcnow()
        )
        
        # 5. ZAPIS DO BAZY
        db.session.add(new_car)
        db.session.flush() # Pobranie ID przed całkowitym zapisem
        
        for p in saved_paths:
            db.session.add(CarImage(image_path=p, car_id=new_car.id))
            
        db.session.commit()
        
        # 6. WYSYŁKA MAILA (Działa w tle)
        wyslij_potwierdzenie_ogloszenia(current_user.email, current_user.username, new_car.marka, new_car.model)
        
        flash('Dodano ogłoszenie!', 'success')
        return redirect(url_for('profil'))

    except Exception as e:
        # COFANIE ZMIAN W BAZIE W RAZIE AWARII
        db.session.rollback()
        print(f"BŁĄD PRZY DODAWANIU AUTA: {e}")
        flash(f'Wystąpił błąd przy zapisie: {str(e)}', 'danger')
        return redirect(url_for('profil'))


    except Exception as e:
        # COFANIE ZMIAN W BAZIE W RAZIE AWARII (Zapobiega zablokowaniu bazy)
        db.session.rollback()
        print(f"BŁĄD PRZY DODAWANIU AUTA: {e}")
        # Zamiast błędu 500, użytkownik zobaczy ładny komunikat z dokładną informacją, co poszło nie tak
        flash(f'Wystąpił błąd przy zapisie: {str(e)}', 'danger')
        return redirect(url_for('profil'))


@app.route('/api/analyze-car', methods=['POST'])
@login_required
def analyze_car():
    dzisiaj = datetime.utcnow().date()
    # Reset dziennego limitu zapytań
    if current_user.last_ai_request_date != dzisiaj:
        current_user.ai_requests_today = 0
        current_user.last_ai_request_date = dzisiaj
        db.session.commit()

    # Ustalanie limitów (Admin = 500, Użytkownik = 6)
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
        
        # Mózg operacji: Precyzyjny prompt dla Gemini 3.0 Flash
        prompt = """
        Jesteś ekspertem motoryzacyjnym. Przeanalizuj to zdjęcie samochodu i zwróć TYLKO czysty obiekt JSON.
        
        Twoje zadania:
        1. Rozpoznaj markę, model, sugerowany rok produkcji, kolor oraz rodzaj nadwozia (kategoria).
        2. Zaproponuj typ paliwa (sugestia na podstawie modelu).
        3. OSZACUJ typową moc (KM) dla tego auta na podstawie modelu/wersji i zapisz w 'moc_sugestia'.
        4. Napisz krótki, atrakcyjny 'opis_wizualny' zachęcający do zakupu na podstawie tego, co widzisz (np. stan lakieru, agresywna sylwetka).
        
        5. WYPOSAŻENIE (BARDZO WAŻNE): Zwróć ogromną uwagę na:
           - Dach (czy ma relingi, szyberdach lub dach panoramiczny)
           - Reflektory (czy to nowoczesne światła LED/soczewkowe)
           - Szyby (czy tylne szyby są przyciemniane)
           - Koła (czy ma felgi aluminiowe)
           
        Wykryj elementy wyposażenia, ale WYBIERAJ TYLKO Z TEJ DOKŁADNEJ LISTY:
        "Alufelgi", "Światła LED", "Relingi dachowe", "Dach panoramiczny", "Szyberdach", "Przyciemniane szyby".
        Zwróć je jako listę stringów w polu 'wyposazenie_wykryte'. Jeśli nie jesteś w 100% pewien elementu ze zdjęcia, po prostu go nie dodawaj.

        Format JSON:
        { 
            "kategoria": "Osobowe/SUV/Minivan/Ciezarowe/Moto",
            "marka": "BMW", 
            "model": "X5", 
            "rok_sugestia": 2018, 
            "paliwo_sugestia": "Diesel", 
            "typ_nadwozia": "SUV", 
            "kolor": "Czarny Metalik",       
            "moc_sugestia": 258,
            "wyposazenie_wykryte": ["Alufelgi", "Światła LED", "Relingi dachowe", "Przyciemniane szyby"], 
            "opis_wizualny": "Auto prezentuje się zjawiskowo, lakier w świetnym stanie..." 
        }
        """
        
        # Odpytanie modelu Gemini
        resp = model_ai.generate_content([prompt, {"mime_type": file.mimetype, "data": image_data}])
        
        # Czyszczenie odpowiedzi do czystego JSONa
        text_response = resp.text.replace('```json', '').replace('```', '').strip()
        data = json.loads(text_response)
        
        # --- DORZUCANIE PODSTAW NA ŚLEPO (EFEKT BOGATEGO WYPOSAŻENIA) ---
        if "wyposazenie_wykryte" not in data or not isinstance(data["wyposazenie_wykryte"], list):
            data["wyposazenie_wykryte"] = []
            
        podstawy_do_zaznaczenia = ["ABS", "ESP", "Poduszki powietrzne", "El. lusterka", "El. szyby"]
        
        for opcja in podstawy_do_zaznaczenia:
            if opcja not in data["wyposazenie_wykryte"]:
                data["wyposazenie_wykryte"].append(opcja)
        # ---------------------------------------------------------------

        # Zapisanie użycia limitu do bazy
        current_user.ai_requests_today += 1
        db.session.commit()
        
        return jsonify(data)
        
    except Exception as e:
        print(f"Błąd AI: {e}")
        return jsonify({"error": "Nie udało się przeanalizować zdjęcia."}), 500


@app.route('/api/generuj-opis', methods=['POST'])
@login_required
def generuj_opis_ai():
    if not model_ai: 
        return jsonify({"error": "Błąd połączenia z serwerami Google AI"}), 500
        
    if not check_ai_limit(): 
        return jsonify({"error": "Osiągnięto dzienny limit zapytań do AI."}), 429
    
    data = request.json
    try:
        # 1. Wyciągamy pięknie wyselekcjonowane dane z frontendu
        marka = data.get('marka', '')
        model = data.get('model', '')
        rok = data.get('rok', '')
        przebieg = data.get('przebieg', '')
        cena = data.get('cena', '')
        paliwo = data.get('paliwo', '')
        pojemnosc = data.get('pojemnosc', '')
        wyposazenie = data.get('wyposazenie', '') # Tu są nasze Matrixy i Masaże!

        # 2. Tworzymy dedykowany, precyzyjny prompt dla modelu Flash
        prompt = f"""
        Jesteś profesjonalnym copywriterem i ekspertem sprzedaży aut Premium.
        Napisz chwytliwy, rzetelny i zachęcający do zakupu opis dla tego pojazdu:
        
        Pojazd: {marka} {model}
        Rok produkcji: {rok}
        Przebieg: {przebieg} km
        Silnik: {pojemnosc}, {paliwo}
        Cena: {cena}
        
        WYPOSAŻENIE (Zwróć na to szczególną uwagę!): {wyposazenie}
        
        ZASADY:
        1. Opis ma być w języku polskim, podzielony na czytelne, krótkie akapity.
        2. Użyj estetycznych, nienachalnych emotikon (np. ✅, 💎, 🚀).
        3. NIE WYMIENIAJ wyposażenia po przecinku! Zamiast tego zgrabnie wpleć opcje (np. z sekcji Wyposażenie) w tekst, opisując, jak podnoszą one prestiż, komfort i bezpieczeństwo. Niech klient poczuje, że kupuje luksus.
        4. Zachowaj ton profesjonalnego salonu samochodowego – bez sztucznego lania wody, konkretnie i z klasą.
        """
        
        resp = model_ai.generate_content(prompt)
        
        current_user.ai_requests_today += 1
        db.session.commit()
        
        return jsonify({"opis": resp.text.strip()})
    except Exception as e:
        print(f"Błąd generowania opisu: {e}")
        return jsonify({"error": "Wystąpił błąd podczas generowania opisu."}), 500


@app.route('/rezerwacja/<int:car_id>', methods=['POST'])
@login_required
def toggle_rezerwacja(car_id):
    c = Car.query.get_or_404(car_id)
    if c.user_id == current_user.id or current_user.username == 'admin':
        c.is_reserved = not c.is_reserved
        db.session.commit()
        flash('Status rezerwacji został zmieniony!', 'success')
    return redirect(request.referrer or url_for('profil'))


@app.route('/usun/<int:car_id>', methods=['POST'])
@login_required
def delete_car(car_id):
    try:
        c = Car.query.get(car_id)
        if c and (c.user_id == current_user.id or current_user.username == 'admin'):
            
            # 1. Usuwanie folderu ze zdjęciami 360 (jeśli auto miało status premium)
            render_path = os.path.join(app.root_path, 'static', 'uploads', '360_renders', str(car_id))
            if os.path.exists(render_path):
                import shutil
                shutil.rmtree(render_path, ignore_errors=True)
            
            # 2. Usuwanie pliku wideo 360 (jeśli istnieje)
            video_path = os.path.join(app.root_path, 'static', 'uploads', '360_videos', f"{car_id}.mp4")
            if os.path.exists(video_path):
                os.remove(video_path)

            # 3. Usuwanie zwykłych zdjęć z serwera (żeby nie zapchać dysku)
            for img in c.images:
                # Oczyszczanie ścieżki (np. usuwanie początkowego slasha, by os.path.join zadziałał)
                img_relative_path = img.image_path.lstrip('/') 
                img_full_path = os.path.join(app.root_path, img_relative_path)
                
                # Nie usuwamy systemowych placeholderów ani znaków wodnych
                if os.path.exists(img_full_path) and 'placehold' not in img_full_path and 'watermark' not in img_full_path:
                    try:
                        os.remove(img_full_path)
                    except Exception as e:
                        print(f"Nie udało się usunąć fizycznego zdjęcia {img_full_path}: {e}")

            # 4. Usunięcie rekordu z bazy (Cascade automatycznie usunie powiązane CarImage z bazy SQL)
            db.session.delete(c)
            db.session.commit()
            flash('Ogłoszenie zostało pomyślnie usunięte.', 'success')
        else:
            flash('Brak uprawnień do usunięcia tego ogłoszenia.', 'danger')
            
    except Exception as e:
        db.session.rollback()
        print(f"BŁĄD PRZY USUWANIU AUTA: {e}")
        flash(f'Wystąpił błąd podczas usuwania: {str(e)}', 'danger')
        
    return redirect(url_for('profil'))



@app.route('/odswiez/<int:car_id>', methods=['POST'])
@login_required
def refresh_car(car_id):
    c = Car.query.get_or_404(car_id)
    
    if c.user_id == current_user.id or current_user.username == 'admin' or current_user.id == 1:
        now = datetime.utcnow()
        
        # --- LIMIT PODBIJANIA CO 3 DNI (Dla zwykłych użytkowników) ---
        if current_user.username != 'admin' and current_user.id != 1:
            roznica = now - c.data_dodania
            if roznica < timedelta(days=3):
                pozostalo_h = int(72 - (roznica.total_seconds() / 3600))
                flash(f'Ogłoszenie można podbijać co 3 dni. Spróbuj ponownie za ok. {pozostalo_h} godz.', 'warning')
                return redirect(request.referrer or url_for('profil'))
        # -------------------------------------------------------------
        
        c.data_dodania = now
        if current_user.username == 'admin' or current_user.id == 1:
            c.ai_valuation_data = None 
            
        db.session.commit()
        flash('Ogłoszenie zaktualizowane i podbite na samą górę!', 'success')
        
    return redirect(request.referrer or url_for('profil'))



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
            
            wyslij_powitanie(request.form['email'], request.form['username']) # <--- DODANO WYSYŁKĘ MAILA
            
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
# --- FUNKCJA WYSYŁAJĄCA MAIL W TLE ---
def wyslij_wiadomosc_z_formularza(app, imie, email_nadawcy, wiadomosc):
    with app.app_context():
        try:
            msg = Message(
                subject=f"Nowa wiadomość z Giełda Radom od: {imie}",
                recipients=['kontakt@gieldaradom.pl'], 
                body=f"Otrzymałeś nową wiadomość z formularza kontaktowego.\n\nOd: {imie} ({email_nadawcy})\n\nTreść wiadomości:\n{wiadomosc}",
                reply_to=email_nadawcy 
            )
            mail.send(msg)
        except Exception as e:
            print(f"Błąd wysyłania formularza kontaktowego w tle: {e}")

# --- ODBIÓR DANYCH ZE STRONY ---
@app.route('/kontakt', methods=['GET', 'POST'])
def kontakt():
    # 1. Logika tłumaczeń
    lang = request.cookies.get('lang', 'pl')
    path = os.path.join(app.root_path, 'translations', 'legal.json')
    try:
        with open(path, encoding='utf-8') as f:
            all_texts = json.load(f)
        current_texts = all_texts.get(lang, all_texts.get('pl'))
    except Exception as e:
        print(f"Błąd wczytywania tłumaczeń: {e}")
        current_texts = {}

    sukces = False # Flaga oznaczająca udane wysłanie
    
    # 2. Reakcja na kliknięcie "Wyślij"
    if request.method == 'POST':
        imie = request.form.get('imie')
        email_nadawcy = request.form.get('email')
        wiadomosc = request.form.get('wiadomosc')
        
        # Odpalamy maila w tle (strona odświeży się natychmiast, zero czekania!)
        Thread(target=wyslij_wiadomosc_z_formularza, args=(app, imie, email_nadawcy, wiadomosc)).start()
        
        sukces = True # Zmieniamy flagę, żeby HTML wiedział, co pokazać

    # 3. Zwracamy widok (przekazując bezpośrednio flagę 'sukces')
    return render_template('kontakt.html', legal=current_texts, lang=lang, sukces=sukces)


    # --- 3. ZWROT SZABLONU DLA ZWYKŁEGO WEJŚCIA (GET) ---
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
    
                        # ... (tutaj masz inne rzeczy jak car.opis, car.pojemnosc) ...
            
            # --- ZAPIS GPS TYLKO DLA ADMINA ---
            if current_user.username == 'admin' or current_user.id == 1:
                try:
                    lat_str = request.form.get('lat', '').replace(',', '.')
                    car.latitude = float(lat_str) if lat_str else None
                    
                    lon_str = request.form.get('lon', '').replace(',', '.')
                    car.longitude = float(lon_str) if lon_str else None
                except ValueError:
                    pass # Jeśli admin wpisze bzdury (np. litery), system to zignoruje
            # ----------------------------------

            

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

@app.route('/admin/edytuj_user/<int:user_id>', methods=['POST'])
@login_required
def admin_edytuj_user(user_id):
    if current_user.username != 'admin' and current_user.id != 1: 
        abort(403)
        
    user = User.query.get_or_404(user_id)
    
    # Podmieniamy dane na te przesłane przez admina
    user.kraj = request.form.get('kraj', user.kraj)
    user.adres = request.form.get('adres', user.adres)
    user.lokalizacja = request.form.get('lokalizacja', user.lokalizacja)
    user.company_name = request.form.get('company_name', user.company_name)
    user.nip = request.form.get('nip', user.nip)
    
    db.session.commit()
    flash(f'Zaktualizowano dane adresowe/firmowe dla: {user.username}.', 'success')
    return redirect('/profil')


@app.route('/admin/wyslij_powitania', methods=['POST'])
@login_required
def admin_wyslij_powitania():
    if current_user.username != 'admin' and current_user.id != 1:
        flash('Brak uprawnień.', 'danger')
        return redirect(url_for('profil'))

    users = User.query.all()
    wyslane = 0

    with mail.connect() as conn:
        for u in users:
            if u.email:
                msg = Message(
                    subject="Dziękuję za zaufanie! Wspólnie zmieniamy rynek aut w Radomiu 🤝",
                    recipients=[u.email]
                )
                msg.body = f"""Cześć {u.username}! 👋

Piszę do Ciebie osobiście, ponieważ właśnie dołączyłeś do platformy Giełda Radom. Chciałem Ci za to bardzo serdecznie podziękować!

Przy okazji chciałbym Cię gorąco przeprosić za wszelkie utrudnienia, na które mogłeś natrafić w ostatnich dniach (np. podczas dodawania ogłoszeń). Cały czas intensywnie pracujemy nad rozbudową platformy i na bieżąco usuwamy usterki, by wszystko działało perfekcyjnie.

Tworząc ten portal, przyświecał nam jeden cel: skończyć z nudnym, ręcznym wpisywaniem danych i ułatwić lokalny handel. Jako pierwsi w Polsce zaprzęgliśmy do pracy sztuczną inteligencję (Gemini AI), która z samego zdjęcia rozpoznaje auto, generuje profesjonalny opis i tworzy kinowe widoki 360°.

Co się u nas teraz dzieje?
* Nasza baza rośnie w błyskawicznym tempie (przekroczyliśmy już 1500 aktywnych ofert na stronie!), a ruch z całego Mazowsza bije kolejne rekordy.
* Wystartowaliśmy z silną kampanią reklamową w Google, skupioną wyłącznie na naszym regionie. Ściągamy na stronę konkretnych kupców z okolicy, by ułatwić Ci szybką sprzedaż.

Masz auto na sprzedaż?
To idealny moment, żeby je dodać. Przypominam, że nasza AI odwali za Ciebie 90% roboty – wystarczy, że zrobisz zdjęcie, a system sam uzupełni model, parametry i wyposażenie w zaledwie 3 sekundy. Wszystko całkowicie za darmo.

Zaloguj się na swoje konto i przetestuj nasz skaner AI:
https://gieldaradom.pl/login

Jeszcze raz dziękuję, że tworzysz z nami nowoczesną motoryzację na Mazowszu. W razie jakichkolwiek pytań – po prostu odpisz na tę wiadomość.

Pozdrawiam serdecznie,
Dariusz
Właściciel serwisu | ADT & AI Team
https://gieldaradom.pl
"""
                try:
                    conn.send(msg)
                    wyslane += 1
                except Exception as e:
                    print(f"Błąd wysyłania do {u.email}: {e}")

    flash(f'Sukces! Wysłano powitalnego e-maila do {wyslane} użytkowników.', 'success')
    return redirect(url_for('profil'))


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
            ("car", "is_360_premium", "BOOLEAN DEFAULT 0"),
            ("car", "is_reserved", "BOOLEAN DEFAULT 0") # <--- TO DODAJ (pamiętaj o przecinku w linijce wyżej!)
        ]
        
        for table, col, dtype in columns_to_add:
            try:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {dtype}")
            except:
                pass # Kolumna już istnieje
                
        conn.commit()
        conn.close()
# --- WYSYŁKA PRZYPOMNIENIA O WYGAŚNIĘCIU (2 DNI DO KOŃCA) ---
def wyslij_przypomnienie_async(app, email, username, marka, model):
    with app.app_context():
        msg = Message(
            subject=f"⏰ Twoje ogłoszenie {marka} {model} niedługo wygasa! Nie poddawaj się!",
            recipients=[email]
        )
        msg.body = f"""Cześć {username}! 👋

Piszę, by przypomnieć Ci, że Twoje ogłoszenie dotyczące {marka} {model} jest u nas już od 28 dni i za 2 dni straci ważność.

Jeśli auto jeszcze nie znalazło nowego właściciela – absolutnie się nie martw! Sprzedaż samochodu to czasem kwestia trafienia na odpowiednią osobę w odpowiednim momencie. Prawdziwy kupiec na pewno się znajdzie, więc nie ma co się poddawać! 💪

Zaloguj się do swojego Garażu i kliknij zielony przycisk "Odśwież" (ikona strzałek) przy swoim ogłoszeniu. Dzięki temu auto znów powędruje na samą górę listy wyszukiwania i zyska kolejne 30 dni ważności. Wszystko oczywiście całkowicie za darmo.

👉 https://gieldaradom.pl/profil

Trzymam kciuki za udaną transakcję! W razie pytań, jestem do dyspozycji.

Pozdrawiam serdecznie,
Dariusz
Właściciel serwisu | ADT & AI Team
https://gieldaradom.pl
"""
        try:
            mail.send(msg)
        except Exception as e:
            print(f"Błąd wysyłania przypomnienia na {email}: {e}")

def wyslij_przypomnienia(email, username, marka, model):
    if email:
        Thread(target=wyslij_przypomnienie_async, args=(app, email, username, marka, model)).start()
# --- WYSYŁKA PRZYPOMNIENIA O WYGAŚNIĘCIU (2 DNI DO KOŃCA) ---
def wyslij_przypomnienie_async(app, email, username, marka, model):
    with app.app_context():
        msg = Message(
            subject=f"⏰ Twoje ogłoszenie {marka} {model} niedługo wygasa! Nie poddawaj się!",
            recipients=[email]
        )
        msg.body = f"""Cześć {username}! 👋

Piszę, by przypomnieć Ci, że Twoje ogłoszenie dotyczące {marka} {model} jest u nas już od 28 dni i za 2 dni straci ważność.

Jeśli auto jeszcze nie znalazło nowego właściciela – absolutnie się nie martw! Sprzedaż samochodu to czasem kwestia trafienia na odpowiednią osobę w odpowiednim momencie. Prawdziwy kupiec na pewno się znajdzie, więc nie ma co się poddawać! 💪

Zaloguj się do swojego Garażu i kliknij zielony przycisk "Odśwież" (ikona strzałek) przy swoim ogłoszeniu. Dzięki temu auto znów powędruje na samą górę listy wyszukiwania i zyska kolejne 30 dni ważności. Wszystko oczywiście całkowicie za darmo.

👉 https://gieldaradom.pl/profil

Trzymam kciuki za udaną transakcję! W razie pytań, jestem do dyspozycji.

Pozdrawiam serdecznie,
Dariusz
Właściciel serwisu | ADT & AI Team
https://gieldaradom.pl
"""
        try:
            mail.send(msg)
        except Exception as e:
            print(f"Błąd wysyłania przypomnienia na {email}: {e}")



# ==========================================
# --- AUTOMATYZACJA W TLE (APSCHEDULER) ---
# ==========================================
def automatyczne_sprawdzanie_wygasajacych():
    """Funkcja odpalana automatycznie przez harmonogram."""
    with app.app_context():
        now = datetime.utcnow()
        # Szukamy aut dodanych między 28 a 29 dni temu
        start_date = now - timedelta(days=29)
        end_date = now - timedelta(days=28)
        
        wygasajace_auta = Car.query.filter(and_(Car.data_dodania >= start_date, Car.data_dodania <= end_date)).all()
        
        wyslane = 0
        for car in wygasajace_auta:
            wlasciciel = User.query.get(car.user_id)
            if wlasciciel and wlasciciel.email:
                wyslij_przypomnienia(wlasciciel.email, wlasciciel.username, car.marka, car.model)
                wyslane += 1
                
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] AUTO-CRON: Wysłano {wyslane} przypomnień o wygasaniu ogłoszeń.")

# Uruchamiamy harmonogram
scheduler = BackgroundScheduler(daemon=True)
# Ustawiamy, aby system sam wysyłał maile CODZIENNIE rano o 10:00
scheduler.add_job(automatyczne_sprawdzanie_wygasajacych, 'cron', hour=10, minute=0)
scheduler.start()

# Zabezpieczenie: grzeczne zamykanie harmonogramu przy restarcie aplikacji
atexit.register(lambda: scheduler.shutdown())
# ==========================================

if __name__ == '__main__':
    update_db()
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000)
