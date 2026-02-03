import os
import uuid
import zipfile
import io
import sekrety
import sqlite3
import json
import google.generativeai as genai
from datetime import datetime, timedelta, timezone
from flask import Flask, render_template, request, redirect, url_for, flash, abort, jsonify, send_from_directory, send_file, Response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_, and_, func  
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from PIL import Image
from itsdangerous import URLSafeTimedSerializer as Serializer

app = Flask(__name__)

# --- KONFIGURACJA POCZTY ---
app.config['MAIL_SERVER'] = 'poczta.o2.pl'
app.config['MAIL_PORT'] = 465
app.config['MAIL_USE_SSL'] = True
app.config['MAIL_USERNAME'] = 'dariusztom@go2.pl'
app.config['MAIL_PASSWORD'] = sekrety.MAIL_PWD
app.config['MAIL_DEFAULT_SENDER'] = 'dariusztom@go2.pl'
mail = Mail(app)

# --- KONFIGURACJA GEMINI AI ---
genai.configure(api_key=sekrety.GEMINI_KEY)
model_ai = genai.GenerativeModel('gemini-1.5-flash') # Najszybszy do analizy zdjęć

# --- KONFIGURACJA APLIKACJI ---
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
        s = Serializer(app.secret_key)
        return s.dumps({'user_id': self.id})

    @staticmethod
    def verify_reset_token(token):
        s = Serializer(app.secret_key)
        try:
            user_id = s.loads(token, max_age=1800)['user_id']
        except:
            return None
        return User.query.get(user_id)

class Car(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    typ = db.Column(db.String(20), default='Osobowe') # Pole z migrowanej bazy
    marka = db.Column(db.String(50), nullable=False)
    model = db.Column(db.String(50), nullable=False)
    rok = db.Column(db.Integer, nullable=False)
    cena = db.Column(db.Float, nullable=False)
    opis = db.Column(db.Text, nullable=False)
    telefon = db.Column(db.String(20), nullable=False)
    img = db.Column(db.String(200), nullable=False)
    zrodlo = db.Column(db.String(20), default='Lokalne')
    ai_label = db.Column(db.String(100), nullable=True)
    ai_valuation_data = db.Column(db.Text, nullable=True)
    data_dodania = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    skrzynia = db.Column(db.String(20))
    paliwo = db.Column(db.String(20))
    nadwozie = db.Column(db.String(30))
    pojemnosc = db.Column(db.String(20))
    wyswietlenia = db.Column(db.Integer, default=0)
    przebieg = db.Column(db.Integer, default=0)
    images = db.relationship('CarImage', backref='car', lazy=True, cascade="all, delete-orphan")

class CarImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    image_path = db.Column(db.String(200), nullable=False)
    car_id = db.Column(db.Integer, db.ForeignKey('car.id'), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- SILNIK SEO I NARZĘDZIA ---

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
    lines = ["User-agent: *", "Allow: /", "Disallow: /admin/", "Disallow: /login", "Sitemap: https://gieldaradom.pl/sitemap.xml"]
    return Response("\n".join(lines), mimetype="text/plain")

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

# --- ANALIZA RYNKOWA AI ---

def get_market_valuation(car):
    base_prices = {"Audi": 1.25, "BMW": 1.28, "Mercedes": 1.30, "Volkswagen": 1.10, "Toyota": 1.15}
    current_year = 2026
    age = current_year - car.rok
    estimated_avg = 150000 * (0.85 ** age) * base_prices.get(car.marka, 1.0)
    diff_percent = ((car.cena - estimated_avg) / estimated_avg) * 100
    if diff_percent < -15: return {"status": "SUPER OKAZJA", "pos": 20, "color": "#28a745", "avg": int(estimated_avg)}
    elif diff_percent < 5: return {"status": "CENA RYNKOWA", "pos": 50, "color": "#1a73e8", "avg": int(estimated_avg)}
    else: return {"status": "POWYŻEJ ŚREDNIEJ", "pos": 80, "color": "#ce2b37", "avg": int(estimated_avg)}

@app.context_processor
def utility_processor():
    return dict(get_market_valuation=get_market_valuation)

# --- TRASY API (VISION I GENEROWANIE) ---

@app.route('/api/analyze-car', methods=['POST'])
@login_required
def analyze_car_api():
    if 'image' not in request.files: return jsonify({"error": "Brak pliku"}), 400
    file = request.files['image']
    try:
        img = Image.open(file.stream)
        prompt = "Zidentyfikuj pojazd na zdjęciu. Zwróć dane TYLKO jako JSON: {\"marka\": \"...\", \"model\": \"...\", \"rok\": 2020, \"typ\": \"Osobowe/Bus/Rower\", \"paliwo\": \"...\"}"
        response = model_ai.generate_content([prompt, img])
        data = json.loads(response.text.replace('```json', '').replace('```', '').strip())
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/generate-description', methods=['POST'])
@login_required
def generate_ai_description():
    data = request.json
    marka, model = data.get('marka', ''), data.get('model', '')
    prompt = f"Jako ekspert motoryzacyjny z Radomia, napisz krótki (3 zdania) opis sprzedażowy dla {marka} {model}. Podkreśl zalety."
    try:
        response = model_ai.generate_content(prompt)
        return jsonify({"description": response.text})
    except:
        return jsonify({"description": f"Na sprzedaż zadbany {marka} {model}. Stan bardzo dobry, zapraszam!"})

# --- GŁÓWNE FUNKCJE OGŁOSZEŃ ---

@app.route('/')
def index():
    q = request.args.get('q', '').lower()
    typ = request.args.get('typ', '')
    base_query = Car.query
    if q: base_query = base_query.filter(or_(Car.marka.ilike(f'%{q}%'), Car.model.ilike(f'%{q}%'), Car.opis.ilike(f'%{q}%')))
    if typ: base_query = base_query.filter(Car.typ == typ)
    cars = base_query.order_by(Car.data_dodania.desc()).all()
    return render_template('index.html', cars=cars, now=datetime.utcnow())

@app.route('/ogloszenie/<int:car_id>')
def car_details(car_id):
    car = Car.query.get_or_404(car_id)
    car.wyswietlenia = (car.wyswietlenia or 0) + 1
    db.session.commit()
    return render_template('details.html', car=car, now=datetime.now(timezone.utc))

@app.route('/dodaj', methods=['POST'])
@login_required
def dodaj_ogloszenie():
    files = request.files.getlist('zdjecia')
    saved_paths = []
    for file in files[:10]:
        if file and allowed_file(file.filename):
            name = save_optimized_image(file)
            saved_paths.append(url_for('static', filename='uploads/' + name))

    nowe_auto = Car(
        typ=request.form.get('typ', 'Osobowe'),
        marka=request.form['marka'], model=request.form['model'],
        rok=int(request.form['rok']), cena=float(request.form['cena']),
        opis=request.form['opis'], telefon=request.form['telefon'],
        skrzynia=request.form.get('skrzynia'), paliwo=request.form.get('paliwo'),
        nadwozie=request.form.get('nadwozie'), pojemnosc=request.form.get('pojemnosc'),
        przebieg=int(request.form.get('przebieg', 0)),
        img=saved_paths[0] if saved_paths else '', 
        user_id=current_user.id
    )
    db.session.add(nowe_auto)
    db.session.flush()
    for p in saved_paths: db.session.add(CarImage(image_path=p, car_id=nowe_auto.id))
    db.session.commit()
    flash('Ogłoszenie dodane pomyślnie!', 'success')
    return redirect(url_for('profil'))

@app.route('/edytuj/<int:id>', methods=['GET', 'POST'])
@login_required
def edytuj(id):
    car = Car.query.get_or_404(id)
    if car.user_id != current_user.id: abort(403)
    if request.method == 'POST':
        car.marka, car.model = request.form.get('marka'), request.form.get('model')
        car.rok, car.cena = request.form.get('rok'), request.form.get('cena')
        car.opis, car.telefon = request.form.get('opis'), request.form.get('telefon')
        car.paliwo, car.skrzynia = request.form.get('paliwo'), request.form.get('skrzynia')
        
        new_files = request.files.getlist('zdjecia')
        for file in new_files:
            if file and allowed_file(file.filename):
                name = save_optimized_image(file)
                path = url_for('static', filename='uploads/' + name)
                db.session.add(CarImage(image_path=path, car_id=car.id))
        db.session.commit()
        flash('Zaktualizowano!', 'success')
        return redirect(url_for('profil'))
    return render_template('edytuj.html', car=car)

@app.route('/usun_zdjecie/<int:image_id>', methods=['POST'])
@login_required
def usun_zdjecie(image_id):
    img = CarImage.query.get_or_404(image_id)
    if img.car.user_id != current_user.id: return jsonify({"success": False}), 403
    try:
        os.remove(os.path.join(app.root_path, img.image_path.lstrip('/')))
        db.session.delete(img)
        db.session.commit()
        return jsonify({"success": True})
    except: return jsonify({"success": False})

@app.route('/usun/<int:car_id>', methods=['POST'])
@login_required
def delete_car(car_id):
    car = Car.query.get_or_404(car_id)
    if car.user_id == current_user.id:
        db.session.delete(car)
        db.session.commit()
        flash('Usunięto ogłoszenie.', 'success')
    return redirect(url_for('profil'))

# --- PROFIL I ADMIN ---

@app.route('/profil')
@login_required
def profil():
    my_cars = Car.query.filter_by(user_id=current_user.id).order_by(Car.id.desc()).all()
    fav_cars = current_user.favorite_cars
    stats = {
        "total_users": User.query.count(),
        "total_listings": Car.query.count(),
        "users_online": 1 # Możesz rozbudować o realny licznik sesji
    }
    return render_template('profil.html', cars=my_cars, fav_cars=fav_cars, stats=stats, now=datetime.utcnow())

@app.route('/admin/full-backup')
@login_required
def full_backup():
    if current_user.id != 1: abort(403)
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        db_path = os.path.join(app.root_path, 'instance', 'gielda.db')
        if os.path.exists(db_path): zf.write(db_path, arcname='gielda.db')
        for root, dirs, files in os.walk(app.config['UPLOAD_FOLDER']):
            for file in files: zf.write(os.path.join(root, file), arcname=os.path.join('static/uploads', file))
    memory_file.seek(0)
    return send_file(memory_file, mimetype='application/zip', as_attachment=True, download_name="BACKUP_FULL.zip")

# --- AUTH I POZOSTAŁE ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
            login_user(user)
            return redirect(url_for('profil'))
        flash('Błędne dane.', 'danger')
    return render_template('login.html', now=datetime.utcnow())

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/toggle_favorite/<int:car_id>')
@login_required
def toggle_favorite(car_id):
    car = Car.query.get_or_404(car_id)
    if car in current_user.favorite_cars: current_user.favorite_cars.remove(car)
    else: current_user.favorite_cars.append(car)
    db.session.commit()
    return redirect(request.referrer or url_for('index'))

if __name__ == '__main__':
    with app.app_context(): db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)
