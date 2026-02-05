import os
import uuid
import zipfile
import io
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from PIL import Image
from flask import Flask, render_template, request, redirect, url_for, flash, abort, jsonify, send_from_directory, send_file, Response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer as Serializer
import google.generativeai as genai

# --- PRÓBA IMPORTU KLUCZY ---
try:
    import sekrety
    GEMINI_KEY = sekrety.GEMINI_KEY
except ImportError:
    GEMINI_KEY = "BRAK_KLUCZA" 

app = Flask(__name__)
app.secret_key = 'radom_sekret_key_2026'

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

# AI CONFIG
if GEMINI_KEY != "BRAK_KLUCZA":
    genai.configure(api_key=GEMINI_KEY)
    model_ai = genai.GenerativeModel('gemini-1.5-flash')

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
    
    # Limity AI
    ai_requests_today = db.Column(db.Integer, default=0)
    last_ai_request_date = db.Column(db.Date, default=datetime.now().date())

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
    
    # AI i Promowanie
    is_promoted = db.Column(db.Boolean, default=False)
    ai_label = db.Column(db.String(500), nullable=True)
    ai_valuation_data = db.Column(db.String(50), nullable=True)
    
    # Tech
    skrzynia = db.Column(db.String(20))
    paliwo = db.Column(db.String(20))
    nadwozie = db.Column(db.String(30))
    pojemnosc = db.Column(db.String(20))
    przebieg = db.Column(db.Integer, default=0)
    
    # Statystyki
    wyswietlenia = db.Column(db.Integer, default=0)
    data_dodania = db.Column(db.DateTime, default=datetime.utcnow)
    
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    images = db.relationship('CarImage', backref='car', lazy=True, cascade="all, delete-orphan")
    favorited_by = db.relationship('Favorite', backref='target_car', cascade="all, delete-orphan")

class CarImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    image_path = db.Column(db.String(200), nullable=False)
    car_id = db.Column(db.Integer, db.ForeignKey('car.id'), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- FUNKCJE POMOCNICZE ---

def check_ai_limit():
    if not current_user.is_authenticated: return False
    today = datetime.now().date()
    if current_user.last_ai_request_date != today:
        current_user.ai_requests_today = 0
        current_user.last_ai_request_date = today
        db.session.commit()
    return current_user.ai_requests_today < 5

def save_optimized_image(file):
    filename = f"{uuid.uuid4().hex}.webp"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    img = Image.open(file)
    if img.mode in ("RGBA", "P"): img = img.convert("RGB")
    if img.width > 1200:
        w_percent = (1200 / float(img.width))
        h_size = int((float(img.height) * float(w_percent)))
        img = img.resize((1200, h_size), Image.Resampling.LANCZOS)
    img.save(filepath, "WEBP", quality=75)
    return filename

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def update_market_valuation(car):
    if GEMINI_KEY == "BRAK_KLUCZA": return
    try:
        prompt = f"""
        Jesteś analitykiem rynku aut w Polsce (Luty 2026).
        Pojazd: {car.marka} {car.model}, Rok: {car.rok}, Silnik: {car.pojemnosc} {car.paliwo}, Cena: {car.cena} PLN.
        Oceń cenę (0-100, im taniej tym więcej punktów).
        Zwróć TYLKO JSON:
        {{
            "score": 85, 
            "label": "OKAZJA / CENA RYNKOWA / DROGO", 
            "color": "success (okazja) / primary (norma) / danger (drogo)",
            "sample_size": "np. 58 ofert",
            "market_info": "Krótkie zdanie uzasadnienia"
        }}
        """
        response = model_ai.generate_content(prompt)
        clean_json = response.text.replace('```json', '').replace('```', '').strip()
        json.loads(clean_json)
        car.ai_label = clean_json
        car.ai_valuation_data = datetime.now().strftime("%Y-%m-%d")
        db.session.commit()
    except Exception as e:
        print(f"Błąd wyceny AI: {e}")

@app.template_filter('from_json')
def from_json_filter(value):
    try: return json.loads(value)
    except: return None

# --- TRASY (ROUTES) ---

@app.route('/')
def index():
    q = request.args.get('q', '').strip()
    typ = request.args.get('typ', '')
    cars_query = Car.query
    if q:
        cars_query = cars_query.filter(or_(Car.marka.icontains(q), Car.model.icontains(q)))
    if typ:
        cars_query = cars_query.filter(Car.typ == typ)
    cars = cars_query.order_by(Car.is_promoted.desc(), Car.data_dodania.desc()).all()
    return render_template('index.html', cars=cars, now=datetime.utcnow())

@app.route('/ogloszenie/<int:car_id>')
def car_details(car_id):
    car = Car.query.get_or_404(car_id)
    should_update = False
    if not car.ai_valuation_data or not car.ai_label:
        should_update = True
    else:
        try:
            last_check = datetime.strptime(car.ai_valuation_data, "%Y-%m-%d")
            if (datetime.now() - last_check).days >= 3:
                should_update = True
        except: should_update = True
    if should_update:
        update_market_valuation(car)
    car.wyswietlenia = (car.wyswietlenia or 0) + 1
    db.session.commit()
    return render_template('details.html', car=car, now=datetime.now(timezone.utc))

@app.route('/profil')
@login_required
def profil():
    cars = Car.query.filter_by(user_id=current_user.id).order_by(Car.data_dodania.desc()).all()
    favorites = Favorite.query.filter_by(user_id=current_user.id).all()
    return render_template('profil.html', cars=cars, favorites=favorites, now=datetime.now(timezone.utc))

@app.route('/dodaj', methods=['POST'])
@login_required
def dodaj_ogloszenie():
    files = request.files.getlist('zdjecia')
    saved_paths = []
    for file in files[:10]:
        if file and allowed_file(file.filename):
            path = url_for('static', filename='uploads/' + save_optimized_image(file))
            saved_paths.append(path)
    main_img = saved_paths[0] if saved_paths else 'https://placehold.co/600x400?text=Brak+Zdjecia'
    try:
        new_car = Car(
            marka=request.form.get('marka'),
            model=request.form.get('model'),
            rok=int(request.form.get('rok') or 0),
            cena=float(request.form.get('cena') or 0),
            typ=request.form.get('typ', 'Osobowe'),
            opis=request.form.get('opis', ''),
            telefon=request.form.get('telefon'),
            skrzynia=request.form.get('skrzynia'),
            paliwo=request.form.get('paliwo'),
            nadwozie=request.form.get('nadwozie'),
            pojemnosc=request.form.get('pojemnosc'),
            przebieg=int(request.form.get('przebieg') or 0),
            img=main_img,
            zrodlo=current_user.lokalizacja,
            user_id=current_user.id,
            data_dodania=datetime.now(timezone.utc)
        )
        db.session.add(new_car)
        db.session.flush()
        for p in saved_paths:
            db.session.add(CarImage(image_path=p, car_id=new_car.id))
        db.session.commit()
        flash('Ogłoszenie dodane!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Błąd: {e}', 'danger')
    return redirect(url_for('profil'))

@app.route('/api/analyze-car', methods=['POST'])
@login_required
def api_analyze_car():
    if GEMINI_KEY == "BRAK_KLUCZA": return jsonify({"error": "Brak API KEY"}), 500
    if not check_ai_limit(): return jsonify({"error": "Limit na dziś wyczerpany"}), 429
    file = request.files.get('scan_image') or request.files.get('image')
    if not file: return jsonify({"error": "Brak zdjęcia"}), 400
    prompt = """
    Jesteś ekspertem. Analizuj zdjęcie pojazdu.
    Zwróć JSON:
    {
        "marka": "String", "model": "String", 
        "typ_nadwozia": "Sedan/Kombi/SUV/Inne",
        "rok_sugestia": "np. 2015", "paliwo_sugestia": "Diesel/Benzyna",
        "kolor": "String", "opis_wizualny": "Krótki opis stanu"
    }
    """
    try:
        resp = model_ai.generate_content([prompt, {"mime_type": "image/jpeg", "data": file.read()}])
        current_user.ai_requests_today += 1
        db.session.commit()
        return jsonify(json.loads(resp.text.replace('```json','').replace('```','').strip()))
    except:
        return jsonify({"error": "Błąd analizy"}), 500

@app.route('/usun/<int:car_id>', methods=['POST'])
@login_required
def delete_car(car_id):
    car = Car.query.get_or_404(car_id)
    if car.user_id == current_user.id or current_user.id == 1:
        db.session.delete(car)
        db.session.commit()
        flash('Usunięto.', 'success')
    return redirect(url_for('profil'))

@app.route('/odswiez/<int:car_id>', methods=['POST'])
@login_required
def refresh_car(car_id):
    car = Car.query.get_or_404(car_id)
    if car.user_id == current_user.id:
        car.data_dodania = datetime.now(timezone.utc)
        db.session.commit()
        flash('Odświeżono na 30 dni!', 'success')
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
        flash('Błędny login lub hasło', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method=='POST':
        if User.query.filter_by(email=request.form['email']).first():
            flash('Email zajęty', 'warning')
            return redirect(url_for('register'))
        db.session.add(User(
            username=request.form['username'], 
            email=request.form['email'],
            password_hash=generate_password_hash(request.form['password']),
            lokalizacja=request.form.get('location', 'Radom')
        ))
        db.session.commit()
        flash('Zaloguj się', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
def logout(): logout_user(); return redirect('/')

@app.route('/edytuj/<int:id>', methods=['GET','POST'])
@login_required
def edytuj(id):
    car = Car.query.get_or_404(id)
    if car.user_id != current_user.id: return redirect('/')
    if request.method == 'POST':
        car.cena = request.form.get('cena')
        car.opis = request.form.get('opis')
        car.marka = request.form.get('marka')
        car.model = request.form.get('model')
        car.rok = request.form.get('rok')
        car.telefon = request.form.get('telefon')
        car.przebieg = request.form.get('przebieg')
        car.typ = request.form.get('typ')
        car.skrzynia = request.form.get('skrzynia')
        car.paliwo = request.form.get('paliwo')
        car.nadwozie = request.form.get('nadwozie')
        car.pojemnosc = request.form.get('pojemnosc')
        
        # Nowe zdjęcia
        files = request.files.getlist('zdjecia')
        for file in files:
            if file and allowed_file(file.filename):
                path = url_for('static', filename='uploads/' + save_optimized_image(file))
                db.session.add(CarImage(image_path=path, car_id=car.id))
        
        db.session.commit()
        flash('Zapisano zmiany!', 'success')
        return redirect('/profil')
    return render_template('edytuj.html', car=car)

@app.route('/usun_zdjecie/<int:image_id>', methods=['POST'])
@login_required
def usun_zdjecie(image_id):
    img = CarImage.query.get_or_404(image_id)
    car = Car.query.get(img.car_id)
    if car.user_id != current_user.id: return jsonify({'success': False}), 403
    if len(car.images) <= 1: return jsonify({'success': False, 'message': 'Musi zostać 1 zdjęcie'})
    
    try:
        full_path = os.path.join(app.root_path, img.image_path.lstrip('/'))
        if os.path.exists(full_path): os.remove(full_path)
        db.session.delete(img)
        if car.img == img.image_path:
             other = CarImage.query.filter(CarImage.car_id==car.id, CarImage.id!=img.id).first()
             if other: car.img = other.image_path
        db.session.commit()
        return jsonify({'success': True})
    except: return jsonify({'success': False})

# --- RESET HASŁA ---
@app.route("/reset_password", methods=['GET', 'POST'])
def reset_request():
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form.get('email')).first()
        if user:
            token = user.get_reset_token()
            print(f"LINK: {url_for('reset_token', token=token, _external=True)}")
            flash(f'Link wysłano (Sprawdź konsolę)', 'info')
            return redirect(url_for('login'))
    return render_template('reset_request.html')

@app.route("/reset_password/<token>", methods=['GET', 'POST'])
def reset_token(token):
    user = User.verify_reset_token(token)
    if not user:
        flash('Link wygasł', 'warning')
        return redirect(url_for('reset_request'))
    if request.method == 'POST':
        user.password_hash = generate_password_hash(request.form.get('password'))
        db.session.commit()
        flash('Hasło zmienione', 'success')
        return redirect(url_for('login'))
    return render_template('reset_token.html')

# --- ADMIN ---
@app.route('/admin/backup-db')
@login_required
def backup_db():
    if current_user.id != 1: abort(403)
    return send_from_directory('instance', 'gielda.db', as_attachment=True)

@app.route('/admin/full-backup')
@login_required
def full_backup():
    if current_user.id != 1: abort(403)
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        db_p = os.path.join(app.instance_path, 'gielda.db')
        if os.path.exists(db_p): zf.write(db_p, 'gielda.db')
        for root, dirs, files in os.walk(app.config['UPLOAD_FOLDER']):
            for file in files:
                zf.write(os.path.join(root, file), os.path.join('uploads', file))
    memory_file.seek(0)
    return send_file(memory_file, download_name='backup_full.zip', as_attachment=True)

if __name__ == '__main__':
    with app.app_context(): db.create_all()
    app.run(host='0.0.0.0', port=5000)
