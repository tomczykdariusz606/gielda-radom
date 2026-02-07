import os
import uuid
import zipfile
import io
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from PIL import Image, ImageOps
from flask import Flask, render_template, request, redirect, url_for, flash, abort, jsonify, send_from_directory, send_file, make_response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_, and_
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer as Serializer
import google.generativeai as genai
from flask_mail import Mail, Message

# --- IMPORT SEKRETÓW ---
try:
    import sekrety
    GEMINI_KEY = sekrety.GEMINI_KEY
    MAIL_PWD = sekrety.MAIL_PWD
    SECRET_KEY_APP = getattr(sekrety, 'SECRET_KEY', 'sekretny_klucz_gieldy_radom_2024')
except ImportError:
    GEMINI_KEY = None
    MAIL_PWD = None
    SECRET_KEY_APP = 'dev_key_2024'

app = Flask(__name__)
app.secret_key = SECRET_KEY_APP

# --- KONFIGURACJA ---
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///gielda.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- TŁUMACZENIA ---
TRANSLATIONS = {
    'pl': {'search_ph': 'Wpisz np. Audi A4...', 'btn_search': 'SZUKAJ', 'filters': 'Filtry', 'cat': 'Kategoria', 'fuel': 'Paliwo', 'gear': 'Skrzynia', 'year': 'Rok od', 'price': 'Cena do', 'mileage': 'Przebieg do', 'add': 'DODAJ AUTO', 'login': 'Logowanie', 'logout': 'Wyloguj', 'hero_h1': 'Znajdź auto w Radomiu', 'hero_p': 'Lokalny rynek. Weryfikacja AI.', 'all': 'Wszystkie', 'man': 'Manualna', 'auto': 'Automatyczna', 'available': 'Dostępne Oferty', 'found': 'Znaleziono'},
    'en': {'search_ph': 'E.g. Audi A4...', 'btn_search': 'SEARCH', 'filters': 'Filters', 'cat': 'Category', 'fuel': 'Fuel', 'gear': 'Gearbox', 'year': 'Year from', 'price': 'Price to', 'mileage': 'Mileage to', 'add': 'ADD CAR', 'login': 'Login', 'logout': 'Logout', 'hero_h1': 'Find car in Radom', 'hero_p': 'Local market. AI Verified.', 'all': 'All', 'man': 'Manual', 'auto': 'Automatic', 'available': 'Available Offers', 'found': 'Found'},
    'de': {'search_ph': 'Z.B. Audi A4...', 'btn_search': 'SUCHEN', 'filters': 'Filter', 'cat': 'Kategorie', 'fuel': 'Kraftstoff', 'gear': 'Getriebe', 'year': 'Baujahr ab', 'price': 'Preis bis', 'mileage': 'KM bis', 'add': 'AUTO HINZUFÜGEN', 'login': 'Anmelden', 'logout': 'Abmelden', 'hero_h1': 'Finde Auto in Radom', 'hero_p': 'Lokaler Markt. AI geprüft.', 'all': 'Alle', 'man': 'Schaltgetriebe', 'auto': 'Automatik', 'available': 'Verfügbare Angebote', 'found': 'Gefunden'}
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

# --- AI CONFIG ---
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    try: model_ai = genai.GenerativeModel('gemini-3-flash-preview')
    except: model_ai = None
else: model_ai = None

mail = Mail(app)

# --- BAZA DANYCH ---
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
    ai_requests_today = db.Column(db.Integer, default=0)
    last_ai_request_date = db.Column(db.Date, default=datetime.utcnow().date())
    cars = db.relationship('Car', backref='owner', lazy=True, cascade="all, delete-orphan")
    favorites = db.relationship('Favorite', backref='user', lazy=True, cascade="all, delete-orphan")
    def get_reset_token(self): return Serializer(app.config['SECRET_KEY']).dumps({'user_id': self.id})
    @staticmethod
    def verify_reset_token(token):
        try: return User.query.get(Serializer(app.config['SECRET_KEY']).loads(token)['user_id'])
        except: return None

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
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    is_promoted = db.Column(db.Boolean, default=False)
    ai_label = db.Column(db.String(500), nullable=True)
    ai_valuation_data = db.Column(db.String(50), nullable=True)
    skrzynia = db.Column(db.String(20))
    paliwo = db.Column(db.String(20))
    nadwozie = db.Column(db.String(30))
    pojemnosc = db.Column(db.String(20))
    przebieg = db.Column(db.Integer, default=0)
    wyswietlenia = db.Column(db.Integer, default=0)
    views = db.Column(db.Integer, default=0)
    data_dodania = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    images = db.relationship('CarImage', backref='car', lazy=True, cascade="all, delete-orphan")

class CarImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    image_path = db.Column(db.String(200), nullable=False)
    car_id = db.Column(db.Integer, db.ForeignKey('car.id'), nullable=False)

@login_manager.user_loader
def load_user(user_id): return User.query.get(int(user_id))

# --- LOGIKA ---
def check_ai_limit():
    if not current_user.is_authenticated: return False
    today = datetime.utcnow().date()
    if current_user.last_ai_request_date != today:
        current_user.ai_requests_today = 0
        current_user.last_ai_request_date = today
        db.session.commit()
    return current_user.ai_requests_today < 1000

def save_optimized_image(file):
    filename = f"{uuid.uuid4().hex}.webp"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    img = Image.open(file)
    try: img = ImageOps.exif_transpose(img)
    except: pass 
    if img.mode in ("RGBA", "P"): img = img.convert("RGB")
    if img.width > 1200:
        w_percent = (1200 / float(img.width))
        h_size = int((float(img.height) * float(w_percent)))
        img = img.resize((1200, h_size), Image.Resampling.LANCZOS)
    img.save(filepath, "WEBP", quality=80)
    return filename

def update_market_valuation(car):
    if not model_ai: return
    try:
        prompt = f"""Ekspert rynku 2026. Analiza: {car.marka} {car.model}, {car.rok}, {car.cena} PLN. Zwróć JSON: {{"score": 85, "label": "DOBRA CENA", "color": "success", "sample_size": "24 oferty", "market_info": "Cena OK."}}"""
        response = model_ai.generate_content(prompt)
        clean_json = response.text.replace('```json', '').replace('```', '').strip()
        json.loads(clean_json)
        car.ai_label = clean_json
        car.ai_valuation_data = datetime.now().strftime("%Y-%m-%d")
        db.session.commit()
    except Exception as e: print(f"AI Error: {e}")

@app.template_filter('from_json')
def from_json_filter(value):
    try: return json.loads(value)
    except: return None

# --- TRASY ---
@app.route('/')
def index():
    q = request.args.get('q', '').strip()
    query = Car.query
    if q:
        terms = q.split()
        conditions = []
        for term in terms:
            conditions.append(or_(Car.marka.icontains(term), Car.model.icontains(term), Car.paliwo.icontains(term), Car.typ.icontains(term), Car.rok.cast(db.String).icontains(term)))
        query = query.filter(and_(*conditions))
    
    # FILTRY
    cat = request.args.get('typ', '')
    if cat: query = query.filter(Car.typ == cat)
    paliwo = request.args.get('paliwo', '')
    if paliwo: query = query.filter(Car.paliwo == paliwo)
    skrzynia = request.args.get('skrzynia', '')
    if skrzynia: query = query.filter(Car.skrzynia == skrzynia)
    max_cena = request.args.get('max_cena', type=float)
    if max_cena: query = query.filter(Car.cena <= max_cena)
    min_rok = request.args.get('min_rok', type=int)
    if min_rok: query = query.filter(Car.rok >= min_rok)
    max_przebieg = request.args.get('max_przebieg', type=int)
    if max_przebieg: query = query.filter(Car.przebieg <= max_przebieg)

    cars = query.order_by(Car.is_promoted.desc(), Car.data_dodania.desc()).all()
    return render_template('index.html', cars=cars, now=datetime.utcnow())

@app.route('/ogloszenie/<int:car_id>')
def car_details(car_id):
    car = Car.query.get_or_404(car_id)
    if car.views is None: car.views = 0
    car.views += 1
    
    # LOGIKA 7 DNI DLA AI
    should_update = False
    if not car.ai_valuation_data or not car.ai_label: should_update = True
    else:
        try:
            last_check = datetime.strptime(car.ai_valuation_data, "%Y-%m-%d")
            if (datetime.now() - last_check).days >= 7: should_update = True
        except: should_update = True   
    if should_update and model_ai:
        try: update_market_valuation(car)
        except: pass
    db.session.commit()
    return render_template('details.html', car=car, now=datetime.utcnow())

@app.route('/profil')
@login_required
def profil():
    cars = Car.query.filter_by(user_id=current_user.id).order_by(Car.data_dodania.desc()).all() if current_user.username != 'admin' else Car.query.order_by(Car.data_dodania.desc()).all()
    favorites = Favorite.query.filter_by(user_id=current_user.id).all()
    return render_template('profil.html', cars=cars, favorites=favorites, now=datetime.utcnow())

@app.route('/dodaj', methods=['POST'])
@login_required
def dodaj_ogloszenie():
    files = request.files.getlist('zdjecia')
    saved_paths = []
    if 'scan_image' in request.files and request.files['scan_image'].filename != '':
        f = request.files['scan_image']
        if '.' in f.filename: saved_paths.append(url_for('static', filename='uploads/' + save_optimized_image(f)))
    for file in files[:15]:
        if '.' in file.filename: saved_paths.append(url_for('static', filename='uploads/' + save_optimized_image(file)))
    main_img = saved_paths[0] if saved_paths else 'https://placehold.co/600x400?text=Brak+Zdjecia'
    
    try: lat = float(request.form.get('lat')) 
    except: lat = None
    try: lon = float(request.form.get('lon')) 
    except: lon = None

    new_car = Car(
        marka=request.form.get('marka'), model=request.form.get('model'),
        rok=int(request.form.get('rok') or 0), cena=float(request.form.get('cena') or 0),
        typ=request.form.get('typ', 'Osobowe'), opis=request.form.get('opis', ''),
        telefon=request.form.get('telefon'), skrzynia=request.form.get('skrzynia'),
        paliwo=request.form.get('paliwo'), nadwozie=request.form.get('nadwozie'),
        pojemnosc=request.form.get('pojemnosc'), przebieg=int(request.form.get('przebieg') or 0),
        img=main_img, zrodlo=current_user.lokalizacja, user_id=current_user.id,
        latitude=lat, longitude=lon, data_dodania=datetime.utcnow()
    )
    db.session.add(new_car)
    db.session.flush()
    for p in saved_paths: db.session.add(CarImage(image_path=p, car_id=new_car.id))
    db.session.commit()
    flash('Dodano!', 'success')
    return redirect(url_for('profil'))

@app.route('/api/analyze-car', methods=['POST'])
@login_required
def api_analyze_car():
    if not model_ai: return jsonify({"error": "AI unavailable"}), 500
    if not check_ai_limit(): return jsonify({"error": "Limit"}), 429
    file = request.files.get('scan_image')
    prompt = """Rozpoznaj: Kategoria (Osobowe/Rower/Inne), Marka, Model. JSON: {"kategoria":"X","marka":"X","model":"X", "rok_sugestia":2020}"""
    resp = model_ai.generate_content([prompt, {"mime_type": file.mimetype, "data": file.read()}])
    current_user.ai_requests_today += 1
    db.session.commit()
    return jsonify(json.loads(resp.text.replace('```json','').replace('```','').strip()))

@app.route('/toggle_favorite/<int:car_id>')
@login_required
def toggle_favorite(car_id):
    fav = Favorite.query.filter_by(user_id=current_user.id, car_id=car_id).first()
    if fav: db.session.delete(fav)
    else: db.session.add(Favorite(user_id=current_user.id, car_id=car_id))
    db.session.commit()
    return redirect(request.referrer)

# --- SEO ROUTES (SITEMAP & ROBOTS) ---
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

# --- AUTH ROUTES ---
@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        u = User.query.filter_by(username=request.form['username']).first()
        if u and check_password_hash(u.password_hash, request.form['password']):
            login_user(u); return redirect(url_for('profil'))
    return render_template('login.html')

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method=='POST':
        db.session.add(User(username=request.form['username'], email=request.form['email'], password_hash=generate_password_hash(request.form['password'])))
        db.session.commit(); return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
def logout(): logout_user(); return redirect('/')

@app.route('/kontakt')
def kontakt(): return render_template('kontakt.html')
@app.route('/regulamin')
def regulamin(): return render_template('regulamin.html')
@app.route('/polityka')
def polityka(): return render_template('polityka.html')
@app.route("/reset_password", methods=['GET', 'POST'])
def reset_request(): return render_template('reset_request.html')
@app.route("/reset_password/<token>", methods=['GET', 'POST'])
def reset_token(token): return render_template('reset_token.html')
@app.route('/edytuj/<int:id>', methods=['GET','POST'])
@login_required
def edytuj(id): return redirect('/profil') # Uproszczone dla skrótu
@app.route('/usun/<int:car_id>', methods=['POST'])
@login_required
def delete_car(car_id):
    c = Car.query.get(car_id)
    if c and (c.user_id == current_user.id or current_user.username=='admin'):
        db.session.delete(c); db.session.commit()
    return redirect('/profil')
@app.route('/odswiez/<int:car_id>', methods=['POST'])
@login_required
def refresh_car(car_id):
    c = Car.query.get(car_id)
    if c: c.data_dodania = datetime.utcnow(); db.session.commit()
    return redirect('/profil')
@app.route('/admin/backup-db')
@login_required
def backup_db(): return send_from_directory('instance', 'gielda.db', as_attachment=True)
@app.route('/admin/full-backup')
@login_required
def full_backup(): return "Backup"

def update_db():
    with app.app_context():
        c = sqlite3.connect('instance/gielda.db').cursor()
        try: c.execute("ALTER TABLE car ADD COLUMN latitude FLOAT")
        except: pass
        try: c.execute("ALTER TABLE car ADD COLUMN longitude FLOAT")
        except: pass

if __name__ == '__main__':
    update_db()
    with app.app_context(): db.create_all()
    app.run(host='0.0.0.0', port=5000)
