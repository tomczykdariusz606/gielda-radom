import os
import uuid
import zipfile
import io
import json
import sqlite3
from datetime import datetime, timezone
from PIL import Image
from flask import Flask, render_template, request, redirect, url_for, flash, abort, jsonify, send_from_directory, send_file
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_
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
    SECRET_KEY_APP = 'dev_key_2026'

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

# --- AI CONFIG (2026 STANDARD) ---
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    # Używamy Twojego płatnego modelu 3.0 Pro
    try:
        model_ai = genai.GenerativeModel('gemini-3-pro-preview')
    except:
        # Fallback gdyby nazwa w API była inna, ale celujemy w 3.0
        model_ai = genai.GenerativeModel('gemini-3.0')
else:
    model_ai = None

# --- MAIL CONFIG ---
app.config['MAIL_SERVER'] = 'poczta.o2.pl'
app.config['MAIL_PORT'] = 465
app.config['MAIL_USE_SSL'] = True
app.config['MAIL_USERNAME'] = 'dariusztom@go2.pl'
app.config['MAIL_PASSWORD'] = MAIL_PWD
app.config['MAIL_DEFAULT_SENDER'] = 'dariusztom@go2.pl'
mail = Mail(app)

# --- MODELE BAZY DANYCH (MUSZĄ PASOWAĆ DO FIZYCZNEJ BAZY) ---

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
    # Limity
    ai_requests_today = db.Column(db.Integer, default=0)
    last_ai_request_date = db.Column(db.Date, default=datetime.utcnow().date())
    # Relacje
    cars = db.relationship('Car', backref='owner', lazy=True, cascade="all, delete-orphan")
    favorites = db.relationship('Favorite', backref='user', lazy=True, cascade="all, delete-orphan")

    def get_reset_token(self):
        s = Serializer(app.config['SECRET_KEY'])
        return s.dumps({'user_id': self.id})

    @staticmethod
    def verify_reset_token(token):
        s = Serializer(app.config['SECRET_KEY'])
        try:
            user_id = s.loads(token)['user_id']
        except: return None
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
    
    # NOWE KOLUMNY (To one powodowały błąd w starej wersji kodu)
    is_promoted = db.Column(db.Boolean, default=False)
    ai_label = db.Column(db.String(500), nullable=True)
    ai_valuation_data = db.Column(db.String(50), nullable=True)
    
    # Tech
    skrzynia = db.Column(db.String(20))
    paliwo = db.Column(db.String(20))
    nadwozie = db.Column(db.String(30))
    pojemnosc = db.Column(db.String(20))
    przebieg = db.Column(db.Integer, default=0)
    
    # Statystyki (Obsługa obu nazw dla bezpieczeństwa)
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
def load_user(user_id):
    return User.query.get(int(user_id))

# --- POMOCNICZE ---
def check_ai_limit():
    if not current_user.is_authenticated: return False
    today = datetime.utcnow().date()
    if current_user.last_ai_request_date != today:
        current_user.ai_requests_today = 0
        current_user.last_ai_request_date = today
        db.session.commit()
    # Limit dla subskrypcji Gemini 3.0
    return current_user.ai_requests_today < 50 

def save_optimized_image(file):
    filename = f"{uuid.uuid4().hex}.webp"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    img = Image.open(file)
    if img.mode in ("RGBA", "P"): img = img.convert("RGB")
    if img.width > 1200:
        w_percent = (1200 / float(img.width))
        h_size = int((float(img.height) * float(w_percent)))
        img = img.resize((1200, h_size), Image.Resampling.LANCZOS)
    img.save(filepath, "WEBP", quality=80)
    return filename

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def update_market_valuation(car):
    if not model_ai: return
    try:
        prompt = f"""
        Jesteś ekspertem rynku automotive 2026. 
        Auto: {car.marka} {car.model}, {car.rok}, {car.cena} PLN.
        Zwróć JSON: {{"score": 80, "label": "DOBRA CENA", "color": "success", "sample_size": "Live Data", "market_info": "Analiza Gemini 3.0"}}
        """
        response = model_ai.generate_content(prompt)
        clean_json = response.text.replace('```json', '').replace('```', '').strip()
        json.loads(clean_json) 
        car.ai_label = clean_json
        car.ai_valuation_data = datetime.now().strftime("%Y-%m-%d")
        db.session.commit()
    except Exception as e:
        print(f"Gemini 3.0 Error: {e}")

@app.template_filter('from_json')
def from_json_filter(value):
    try: return json.loads(value)
    except: return None

# --- TRASY (ROUTES) ---

@app.route('/')
def index():
    q = request.args.get('q', '').strip()
    cars_query = Car.query
    if q: cars_query = cars_query.filter(or_(Car.marka.icontains(q), Car.model.icontains(q)))
    cars = cars_query.order_by(Car.is_promoted.desc(), Car.data_dodania.desc()).all()
    return render_template('index.html', cars=cars, now=datetime.utcnow())

@app.route('/ogloszenie/<int:car_id>')
def car_details(car_id):
    car = Car.query.get_or_404(car_id)
    # Obsługa licznika (zabezpieczenie przed NULL)
    if car.views is None: car.views = 0
    car.views += 1
    car.wyswietlenia = (car.wyswietlenia or 0) + 1
    
    # Auto-Wycena Gemini 3.0 (co 24h)
    should_update = False
    if not car.ai_valuation_data or not car.ai_label:
        should_update = True
    else:
        try:
            last_check = datetime.strptime(car.ai_valuation_data, "%Y-%m-%d")
            if (datetime.now() - last_check).days >= 1: should_update = True
        except: should_update = True
            
    if should_update and model_ai:
        try: update_market_valuation(car)
        except: pass

    db.session.commit()
    return render_template('details.html', car=car, now=datetime.utcnow())

@app.route('/profil')
@login_required
def profil():
    if current_user.username == 'admin':
        cars = Car.query.order_by(Car.data_dodania.desc()).all()
        # Statystyki Admina
        user_count = User.query.count()
        total_views = db.session.query(db.func.sum(Car.views)).scalar() or 0
    else:
        cars = Car.query.filter_by(user_id=current_user.id).order_by(Car.data_dodania.desc()).all()
        user_count = 0
        total_views = 0
        
    favorites = Favorite.query.filter_by(user_id=current_user.id).all()
    return render_template('profil.html', cars=cars, favorites=favorites, user_count=user_count, total_views=total_views, now=datetime.utcnow())

@app.route('/dodaj', methods=['POST'])
@login_required
def dodaj_ogloszenie():
    files = request.files.getlist('zdjecia')
    saved_paths = []
    
    # Obsługa Skanera (jeśli wysłano plik ze skanera)
    if 'scan_image' in request.files and request.files['scan_image'].filename != '':
        f = request.files['scan_image']
        if allowed_file(f.filename): 
            saved_paths.append(url_for('static', filename='uploads/' + save_optimized_image(f)))

    # Obsługa Galerii
    for file in files[:15]:
        if file and allowed_file(file.filename):
            saved_paths.append(url_for('static', filename='uploads/' + save_optimized_image(file)))
            
    main_img = saved_paths[0] if saved_paths else 'https://placehold.co/600x400?text=Brak+Zdjecia'
    
    try:
        new_car = Car(
            marka=request.form.get('marka'), model=request.form.get('model'),
            rok=int(request.form.get('rok') or 0), cena=float(request.form.get('cena') or 0),
            typ=request.form.get('typ', 'Osobowe'), opis=request.form.get('opis', ''),
            telefon=request.form.get('telefon'), skrzynia=request.form.get('skrzynia'),
            paliwo=request.form.get('paliwo'), nadwozie=request.form.get('nadwozie'),
            pojemnosc=request.form.get('pojemnosc'), przebieg=int(request.form.get('przebieg') or 0),
            img=main_img, zrodlo=current_user.lokalizacja, user_id=current_user.id,
            data_dodania=datetime.utcnow(),
            is_promoted=False,
            views=0, wyswietlenia=0 # Inicjalizacja liczników
        )
        db.session.add(new_car)
        db.session.flush()
        for p in saved_paths: db.session.add(CarImage(image_path=p, car_id=new_car.id))
        db.session.commit()
        flash('Ogłoszenie dodane pomyślnie!', 'success')
    except Exception as e:
        print(f"DB Error: {e}")
        flash('Błąd zapisu do bazy.', 'danger')
    return redirect(url_for('profil'))

@app.route('/api/analyze-car', methods=['POST'])
@login_required
def api_analyze_car():
    if not model_ai: return jsonify({"error": "Gemini 3.0 niedostępne"}), 500
    if not check_ai_limit(): return jsonify({"error": "Limit subskrypcji wyczerpany"}), 429
    
    file = request.files.get('scan_image')
    if not file: return jsonify({"error": "Brak pliku"}), 400
    try:
        # Prompt dla Gemini 3.0
        prompt = """
        Przeanalizuj zdjęcie pojazdu. 
        Zwróć czysty JSON: {"marka": "Marka", "model": "Model", "rok_sugestia": 2024, "paliwo_sugestia": "Typ", "typ_nadwozia": "Typ", "kolor": "Kolor", "opis_wizualny": "Szczegółowy opis stanu"}
        """
        resp = model_ai.generate_content([prompt, {"mime_type": file.mimetype, "data": file.read()}])
        current_user.ai_requests_today += 1
        db.session.commit()
        txt = resp.text.replace('```json','').replace('```','').strip()
        return jsonify(json.loads(txt))
    except Exception as e: 
        print(f"Scan Error: {e}")
        return jsonify({"error": "Błąd analizy obrazu"}), 500

@app.route('/api/generuj-opis', methods=['POST'])
@login_required
def generuj_opis_ai():
    if not model_ai: return jsonify({"opis": "Gemini 3.0 error"}), 500
    if not check_ai_limit(): return jsonify({"opis": "Limit wyczerpany"}), 429
    
    data = request.json
    try:
        prompt = f"Stwórz opis sprzedaży auta premium. Dane: {data}. Styl: Profesjonalny dealer."
        resp = model_ai.generate_content(prompt)
        current_user.ai_requests_today += 1
        db.session.commit()
        return jsonify({"opis": resp.text.strip()})
    except Exception as e:
        return jsonify({"opis": f"Błąd: {str(e)}"}), 500

@app.route('/usun/<int:car_id>', methods=['POST'])
@login_required
def delete_car(car_id):
    car = Car.query.get_or_404(car_id)
    if car.user_id == current_user.id or current_user.username == 'admin':
        db.session.delete(car)
        db.session.commit()
    return redirect(url_for('profil'))

@app.route('/odswiez/<int:car_id>', methods=['POST'])
@login_required
def refresh_car(car_id):
    car = Car.query.get_or_404(car_id)
    if car.user_id == current_user.id or current_user.username == 'admin':
        car.data_dodania = datetime.utcnow()
        db.session.commit()
    return redirect(url_for('profil'))

@app.route('/toggle_favorite/<int:car_id>')
@login_required
def toggle_favorite(car_id):
    fav = Favorite.query.filter_by(user_id=current_user.id, car_id=car_id).first()
    if fav: db.session.delete(fav)
    else: db.session.add(Favorite(user_id=current_user.id, car_id=car_id))
    db.session.commit()
    return redirect(request.referrer)

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        u = User.query.filter_by(username=request.form['username']).first()
        if u and check_password_hash(u.password_hash, request.form['password']):
            login_user(u)
            return redirect(url_for('profil'))
        flash('Błędne dane.', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method=='POST':
        if User.query.filter_by(email=request.form['email']).first(): return redirect(url_for('register'))
        db.session.add(User(username=request.form['username'], email=request.form['email'], password_hash=generate_password_hash(request.form['password']), lokalizacja=request.form.get('location', 'Radom')))
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
def logout(): logout_user(); return redirect('/')

@app.route('/edytuj/<int:id>', methods=['GET','POST'])
@login_required
def edytuj(id):
    car = Car.query.get_or_404(id)
    if car.user_id != current_user.id and current_user.username != 'admin': return redirect('/')
    if request.method == 'POST':
        car.cena = request.form.get('cena')
        car.opis = request.form.get('opis')
        car.marka = request.form.get('marka')
        car.model = request.form.get('model')
        car.rok = request.form.get('rok')
        car.telefon = request.form.get('telefon')
        car.przebieg = request.form.get('przebieg')
        car.paliwo = request.form.get('paliwo')
        car.skrzynia = request.form.get('skrzynia')
        db.session.commit()
        return redirect('/profil')
    return render_template('edytuj.html', car=car)

# Admin / Stopka / Backup
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
        if os.path.exists('instance/gielda.db'): zf.write('instance/gielda.db', 'gielda.db')
        for root, dirs, files in os.walk('static/uploads'):
            for file in files: zf.write(os.path.join(root, file), os.path.join('uploads', file))
    memory_file.seek(0)
    return send_file(memory_file, download_name='backup_full.zip', as_attachment=True)

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
@app.route('/usun_zdjecie/<int:image_id>', methods=['POST'])
@login_required
def usun_zdjecie(image_id):
    img = CarImage.query.get_or_404(image_id)
    db.session.delete(img)
    db.session.commit()
    return jsonify({'success': True})

if __name__ == '__main__':
    with app.app_context(): db.create_all()
    app.run(host='0.0.0.0', port=5000)
