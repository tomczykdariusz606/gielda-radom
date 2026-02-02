import os
import uuid
import zipfile
import io
import sekrety
import google.generativeai as genai
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, abort, jsonify, send_from_directory, send_file, Response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_, func
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from PIL import Image
from itsdangerous import URLSafeTimedSerializer as Serializer
from thefuzz import process 

app = Flask(__name__)

# --- KONFIGURACJA ---
app.config['MAIL_SERVER'] = 'poczta.o2.pl'
app.config['MAIL_PORT'] = 465
app.config['MAIL_USE_SSL'] = True
app.config['MAIL_USERNAME'] = 'dariusztom@go2.pl'
app.config['MAIL_PASSWORD'] = sekrety.MAIL_PWD
app.config['MAIL_DEFAULT_SENDER'] = 'darius_ztom@go2.pl'
mail = Mail(app)

# Konfiguracja Gemini AI
genai.configure(api_key=sekrety.GEMINI_KEY)
model_ai = genai.GenerativeModel('gemini-1.5-flash')

app.secret_key = 'sekretny_klucz_gieldy_radom_2024'
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

# --- TABELA ULUBIONYCH ---
favorites = db.Table('favorites',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('car_id', db.Integer, db.ForeignKey('car.id'), primary_key=True)
)

# --- MODELE ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    lokalizacja = db.Column(db.String(100), nullable=True, default='Radom')
    cars = db.relationship('Car', backref='owner', lazy=True, cascade="all, delete-orphan")
    favorite_cars = db.relationship('Car', secondary=favorites, backref='fans')

    def get_reset_token(self):
        s = Serializer(app.config['SECRET_KEY'])
        return s.dumps({'user_id': self.id})

    @staticmethod
    def verify_reset_token(token):
        s = Serializer(app.config['SECRET_KEY'])
        try: user_id = s.loads(token)['user_id']
        except: return None
        return User.query.get(user_id)

class Car(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    marka = db.Column(db.String(50), nullable=False)
    model = db.Column(db.String(50), nullable=False)
    rok = db.Column(db.Integer, nullable=False)
    cena = db.Column(db.Float, nullable=False)
    opis = db.Column(db.Text, nullable=False)
    telefon = db.Column(db.String(20), nullable=False)
    img = db.Column(db.String(200), nullable=False) 
    zrodlo = db.Column(db.String(20), default='Lokalne')
    data_dodania = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    przebieg = db.Column(db.Integer, default=0)
    skrzynia = db.Column(db.String(20))
    paliwo = db.Column(db.String(20))
    nadwozie = db.Column(db.String(30))
    pojemnosc = db.Column(db.String(20))
    wyswietlenia = db.Column(db.Integer, default=0)
    images = db.relationship('CarImage', backref='car', lazy=True, cascade="all, delete-orphan")

class CarImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    image_path = db.Column(db.String(200), nullable=False)
    car_id = db.Column(db.Integer, db.ForeignKey('car.id'), nullable=False)

@login_manager.user_loader
def load_user(user_id): return User.query.get(int(user_id))

# --- SILNIK ANALIZY ---
def get_market_valuation(car):
    base_prices = {"Audi": 1.25, "BMW": 1.28, "Mercedes": 1.30, "Volkswagen": 1.10, "Toyota": 1.15, "Skoda": 1.05}
    age = 2026 - car.rok
    estimated = 150000 * (0.85 ** age) * base_prices.get(car.marka, 1.0) * 0.97
    diff = ((car.cena - estimated) / estimated) * 100
    if diff < -15: return {"status": "SUPER OKAZJA", "color": "#28a745", "diff": round(diff, 1), "avg": int(estimated)}
    elif diff < 5: return {"status": "CENA RYNKOWA", "color": "#1a73e8", "diff": round(diff, 1), "avg": int(estimated)}
    else: return {"status": "POWYŻEJ ŚREDNIEJ", "color": "#ce2b37", "diff": round(diff, 1), "avg": int(estimated)}

@app.context_processor
def utility_processor(): return dict(get_market_valuation=get_market_valuation)

# --- TRASY ---

@app.route('/')
def index():
    query_text = request.args.get('q', '').strip()
    skrzynia = request.args.get('skrzynia', '')
    paliwo = request.args.get('paliwo', '')
    cena_max = request.args.get('cena_max', type=float)
    base_query = Car.query
    if query_text:
        all_cars = Car.query.all()
        choices = {f"{c.marka} {c.model}": c.id for c in all_cars}
        matches = process.extract(query_text, choices.keys(), limit=50)
        matched_ids = [choices[m[0]] for m in matches if m[1] > 55]
        base_query = Car.query.filter(Car.id.in_(matched_ids))
    if skrzynia: base_query = base_query.filter(Car.skrzynia == skrzynia)
    if paliwo: base_query = base_query.filter(Car.paliwo == paliwo)
    if cena_max: base_query = base_query.filter(Car.cena <= cena_max)
    cars = base_query.order_by(Car.id.desc()).all()
    return render_template('index.html', cars=cars, now=datetime.utcnow(), request=request)

@app.route('/ogloszenie/<int:car_id>')
def car_details(car_id):
    car = Car.query.get_or_404(car_id)
    car.wyswietlenia = (car.wyswietlenia or 0) + 1
    db.session.commit()
    return render_template('details.html', car=car, now=datetime.utcnow())

@app.route('/dodaj', methods=['POST'])
@login_required
def dodaj_ogloszenie():
    files = request.files.getlist('zdjecia')
    saved_paths = []
    
    # Zapis zdjęć
    for file in files[:10]:
        if file and '.' in file.filename:
            fname = f"{uuid.uuid4().hex}.webp"
            img = Image.open(file)
            if img.mode != "RGB": img = img.convert("RGB")
            if img.width > 1200:
                ratio = 1200 / float(img.width)
                img = img.resize((1200, int(float(img.height)*ratio)), Image.Resampling.LANCZOS)
            
            # Zapisujemy fizycznie na dysku
            full_path = os.path.join(app.config['UPLOAD_FOLDER'], fname)
            img.save(full_path, "WEBP", quality=75)
            
            # Dodajemy do listy URL-i
            saved_paths.append(url_for('static', filename='uploads/' + fname))

    main_img = saved_paths[0] if saved_paths else 'https://placehold.co/600x400?text=Brak+Zdjecia'
    
    # --- AI ANALIZA (Naprawiona) ---
    ai_analysis = ""
    if saved_paths:
        try:
            # Używamy ścieżki systemowej do pliku, który przed chwilą zapisaliśmy
            # saved_paths[0] to np. "/static/uploads/plik.webp"
            # Musimy to zamienić na pełną ścieżkę systemową
            filename_only = saved_paths[0].split('/')[-1]
            system_path = os.path.join(app.root_path, app.config['UPLOAD_FOLDER'], filename_only)
            
            img_to_analyze = Image.open(system_path)
            prompt = "Jesteś ekspertem motoryzacyjnym. Opisz krótko w 2-3 zdaniach stan wizualny tego auta, jego kolor i widoczne cechy (np. felgi, stan blacharski)."
            res = model_ai.generate_content([prompt, img_to_analyze])
            ai_analysis = f"\n\n[Analiza AI]: {res.text}"
        except Exception as e:
            print(f"BŁĄD AI: {e}")
            ai_analysis = ""

    nowe = Car(
        marka=request.form['marka'], model=request.form['model'],
        rok=int(request.form['rok']), cena=float(request.form['cena']),
        przebieg=int(request.form.get('przebieg', 0)),
        opis=request.form['opis'] + ai_analysis,
        telefon=request.form['telefon'], skrzynia=request.form.get('skrzynia'),
        paliwo=request.form.get('paliwo'), nadwozie=request.form.get('nadwozie'),
        pojemnosc=request.form.get('pojemnosc'), img=main_img,
        zrodlo=current_user.lokalizacja, user_id=current_user.id
    )
    db.session.add(nowe)
    db.session.flush()
    for p in saved_paths: db.session.add(CarImage(image_path=p, car_id=nowe.id))
    db.session.commit()
    flash('Dodano ogłoszenie z analizą AI!', 'success')
    return redirect(url_for('profil'))

# --- NAPRAWIONA FUNKCJA USUWANIA DLA TWOJEGO SKRYPTU JS ---
@app.route('/usun_zdjecie/<int:img_id>', methods=['POST'])
@login_required
def delete_image(img_id):
    img = CarImage.query.get_or_404(img_id)
    
    # Sprawdzamy czy to auto użytkownika
    if img.car.user_id != current_user.id:
        return jsonify({'success': False, 'error': 'Brak uprawnień'}), 403
    
    # Usuwamy plik fizycznie
    try:
        # Konwersja URL na ścieżkę systemową
        filename = img.image_path.split('/')[-1]
        path = os.path.join(app.root_path, app.config['UPLOAD_FOLDER'], filename)
        if os.path.exists(path): os.remove(path)
    except Exception as e:
        print(f"Błąd usuwania pliku: {e}")

    db.session.delete(img)
    db.session.commit()
    
    # ZWRACAMY JSON - Tego oczekuje Twój skrypt "fetch"
    return jsonify({'success': True})

@app.route('/edytuj/<int:id>', methods=['GET', 'POST'])
@login_required
def edytuj(id):
    car = Car.query.get_or_404(id)
    if car.user_id != current_user.id: return redirect(url_for('profil'))
    
    if request.method == 'POST':
        car.marka = request.form['marka']
        car.model = request.form['model']
        car.rok = request.form['rok']
        car.cena = request.form['cena']
        # Bezpieczne pobieranie przebiegu (domyślnie 0 jeśli pusty)
        try: car.przebieg = int(request.form.get('przebieg', 0))
        except: car.przebieg = 0
            
        car.opis = request.form['opis']
        car.telefon = request.form['telefon']
        car.skrzynia = request.form.get('skrzynia')
        car.paliwo = request.form.get('paliwo')
        car.nadwozie = request.form.get('nadwozie')
        car.pojemnosc = request.form.get('pojemnosc')
        
        # Dodawanie nowych zdjęć przy edycji
        files = request.files.getlist('zdjecia')
        for file in files:
            if file and '.' in file.filename:
                fname = f"{uuid.uuid4().hex}.webp"
                path = os.path.join(app.config['UPLOAD_FOLDER'], fname)
                file.save(path)
                db_path = url_for('static', filename='uploads/' + fname)
                db.session.add(CarImage(image_path=db_path, car_id=car.id))
                
                # Jeśli auto nie miało zdjęcia głównego, ustaw to nowe
                if 'placehold' in car.img or not car.img:
                    car.img = db_path

        db.session.commit()
        flash('Zapisano zmiany!', 'success')
        return redirect(url_for('profil'))
        
    return render_template('edytuj.html', car=car)

# --- RESZTA TRAS ---
@app.route('/profil')
@login_required
def profil():
    my_cars = Car.query.filter_by(user_id=current_user.id).order_by(Car.id.desc()).all()
    fav_cars = current_user.favorite_cars
    return render_template('profil.html', cars=my_cars, fav_cars=fav_cars, now=datetime.utcnow())

@app.route('/usun/<int:car_id>', methods=['POST'])
@login_required
def delete_car(car_id):
    car = Car.query.get_or_404(car_id)
    if car.user_id == current_user.id:
        db.session.delete(car)
        db.session.commit()
    return redirect(url_for('profil'))

@app.route('/toggle_favorite/<int:car_id>')
@login_required
def toggle_favorite(car_id):
    car = Car.query.get_or_404(car_id)
    if car in current_user.favorite_cars: current_user.favorite_cars.remove(car)
    else: current_user.favorite_cars.append(car)
    db.session.commit()
    return redirect(request.referrer or url_for('index'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
            login_user(user)
            return redirect(url_for('profil'))
    return render_template('login.html', now=datetime.utcnow())

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        new_user = User(username=request.form['username'], email=request.form['email'], 
                        password_hash=generate_password_hash(request.form['password']))
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('register.html', now=datetime.utcnow())

@app.route('/logout')
def logout(): logout_user(); return redirect(url_for('index'))

# Generator opisów AI (Endpoint API)
@app.route('/api/generate-description', methods=['POST'])
@login_required
def generate_ai_description():
    data = request.json
    marka = data.get('marka', '')
    model = data.get('model', '')
    rok = data.get('rok', '')
    paliwo = data.get('paliwo', '')
    prompt = f"Napisz krótki, zachęcający opis samochodu {marka} {model} z roku {rok}, silnik {paliwo}."
    try:
        response = model_ai.generate_content(prompt)
        return jsonify({"description": response.text})
    except:
        return jsonify({"description": f"Sprzedam {marka} {model}."})

# Funkcje Admina
@app.route('/admin/full-backup')
@login_required
def full_backup():
    if current_user.id != 1: abort(403)
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        db_path = os.path.join(app.root_path, 'instance', 'gielda.db')
        if os.path.exists(db_path): zf.write(db_path, arcname='gielda.db')
    memory_file.seek(0)
    return send_file(memory_file, mimetype='application/zip', as_attachment=True, download_name="backup.zip")

@app.route('/admin/backup-db')
@login_required
def backup_db():
    if current_user.id != 1: abort(403)
    db_path = os.path.join(app.root_path, 'instance', 'gielda.db')
    return send_file(db_path, as_attachment=True)

# Trasy techniczne (Sitemap, Robots)
@app.route('/sitemap.xml')
def sitemap():
    base_url = "https://gieldaradom.pl"
    cars = Car.query.all()
    xml = f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    xml += f'  <url><loc>{base_url}/</loc><priority>1.0</priority></url>\n'
    for car in cars:
        xml += f'  <url><loc>{base_url}/ogloszenie/{car.id}</loc><priority>0.8</priority></url>\n'
    xml += f'</urlset>'
    return Response(xml, mimetype='application/xml')

@app.route('/robots.txt')
def robots():
    lines = ["User-agent: *", "Allow: /", "Disallow: /admin/", "Sitemap: https://gieldaradom.pl/sitemap.xml"]
    return Response("\n".join(lines), mimetype="text/plain")

def send_reset_email(user):
    token = user.get_reset_token()
    token_str = token.decode('utf-8') if isinstance(token, bytes) else token
    msg = Message('Reset Hasła', recipients=[user.email])
    msg.body = f"Link: {url_for('reset_token', token=token_str, _external=True)}"
    mail.send(msg)

@app.route("/reset_password", methods=['GET', 'POST'])
def reset_request():
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form.get('email')).first()
        if user: send_reset_email(user); flash('Email wysłany.', 'info'); return redirect(url_for('login'))
    return render_template('reset_request.html')

@app.route("/reset_password/<token>", methods=['GET', 'POST'])
def reset_token(token):
    user = User.verify_reset_token(token)
    if user is None: return redirect(url_for('reset_request'))
    if request.method == 'POST':
        user.password_hash = generate_password_hash(request.form.get('password'))
        db.session.commit()
        flash('Hasło zmienione!', 'success')
        return redirect(url_for('login'))
    return render_template('reset_token.html')

if __name__ == '__main__':
    with app.app_context(): db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)
