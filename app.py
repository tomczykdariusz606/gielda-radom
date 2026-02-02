import os
import uuid
import zipfile
import io
import sekrety  # Wymaga: GEMINI_KEY, MAIL_PWD
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
app.config['MAIL_DEFAULT_SENDER'] = 'dariusztom@go2.pl'
mail = Mail(app)

genai.configure(api_key=sekrety.GEMINI_KEY)
model_ai = genai.GenerativeModel('gemini-1.5-flash')

app.secret_key = 'sekretny_klucz_gieldy_radom_2026'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///gielda.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- TABELE I MODELE ---
favorites = db.Table('favorites',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('car_id', db.Integer, db.ForeignKey('car.id'), primary_key=True)
)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    lokalizacja = db.Column(db.String(100), nullable=True, default='Radom')
    cars = db.relationship('Car', backref='owner', lazy=True, cascade="all, delete-orphan")
    favorite_cars = db.relationship('Car', secondary=favorites, backref='fans')

class Car(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    marka = db.Column(db.String(50), nullable=False)
    model = db.Column(db.String(50), nullable=False)
    rok = db.Column(db.Integer, nullable=False)
    cena = db.Column(db.Float, nullable=False)
    przebieg = db.Column(db.Integer, default=0)
    pojemnosc = db.Column(db.String(20))
    skrzynia = db.Column(db.String(20))
    paliwo = db.Column(db.String(20))
    nadwozie = db.Column(db.String(30))
    opis = db.Column(db.Text, nullable=False)
    telefon = db.Column(db.String(20), nullable=False)
    img = db.Column(db.String(200), nullable=False) 
    zrodlo = db.Column(db.String(20), default='Radom')
    data_dodania = db.Column(db.DateTime, default=datetime.utcnow)
    wyswietlenia = db.Column(db.Integer, default=0)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    images = db.relationship('CarImage', backref='car', lazy=True, cascade="all, delete-orphan")

    @property
    def dni_do_konca(self):
        """Oblicza ile dni zostało do końca 30-dniowego cyklu."""
        wygasniecie = self.data_dodania + timedelta(days=30)
        roznica = wygasniecie - datetime.utcnow()
        return max(0, roznica.days)

class CarImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    image_path = db.Column(db.String(200), nullable=False)
    car_id = db.Column(db.Integer, db.ForeignKey('car.id'), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- LOGIKA ANALIZY RYNKOWEJ ---
def get_market_valuation(car):
    base_prices = {"Audi": 1.25, "BMW": 1.28, "Mercedes": 1.30, "Volkswagen": 1.10, "Toyota": 1.15}
    age = max(1, 2026 - car.rok)
    estimated_avg = 150000 * (0.85 ** age) * base_prices.get(car.marka, 1.0)
    if car.przebieg > (age * 20000): estimated_avg *= 0.92
    
    diff_percent = ((car.cena - estimated_avg) / estimated_avg) * 100
    if diff_percent < -15:
        return {"status": "SUPER OKAZJA", "pos": 20, "color": "#28a745", "diff": round(diff_percent, 1), "avg": int(estimated_avg)}
    elif diff_percent < 5:
        return {"status": "CENA RYNKOWA", "pos": 50, "color": "#1a73e8", "diff": round(diff_percent, 1), "avg": int(estimated_avg)}
    return {"status": "POWYŻEJ ŚREDNIEJ", "pos": 80, "color": "#ce2b37", "diff": round(diff_percent, 1), "avg": int(estimated_avg)}

@app.context_processor
def utility_processor():
    return dict(get_market_valuation=get_market_valuation)

# --- POMOCNIKI ---
def save_optimized_image(file):
    filename = f"{uuid.uuid4().hex}.webp"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    img = Image.open(file)
    if img.mode in ("RGBA", "P"): img = img.convert("RGB")
    img.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
    img.save(filepath, "WEBP", quality=75)
    return filename

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg', 'gif', 'webp'}

# --- TRASY ---
@app.route('/')
def index():
    limit_daty = datetime.utcnow() - timedelta(days=30)
    query_text = request.args.get('q', '').strip()
    base_query = Car.query.filter(Car.data_dodania >= limit_daty)

    if query_text:
        all_cars = base_query.all()
        choices = {f"{c.marka} {c.model}": c.id for c in all_cars}
        matches = process.extract(query_text, choices.keys(), limit=20)
        matched_ids = [choices[m[0]] for m in matches if m[1] > 55]
        base_query = base_query.filter(Car.id.in_(matched_ids))

    cars = base_query.order_by(Car.id.desc()).all()
    return render_template('index.html', cars=cars, now=datetime.utcnow())

@app.route('/dodaj', methods=['POST'])
@login_required
def dodaj_ogloszenie():
    files = request.files.getlist('zdjecia')
    saved_paths = [url_for('static', filename='uploads/' + save_optimized_image(f)) for f in files[:10] if f and allowed_file(f.filename)]
    main_img = saved_paths[0] if saved_paths else 'https://placehold.co/600x400?text=Brak+Zdjecia'
    
    # Analiza Vision AI
    ai_vision = ""
    if saved_paths:
        try:
            local_p = os.path.join(app.root_path, saved_paths[0].lstrip('/'))
            res = model_ai.generate_content(["Opisz krótko to auto po polsku.", Image.open(local_p)])
            ai_vision = f"\n\n[Analiza AI]: {res.text}"
        except: pass

    nowe_auto = Car(
        marka=request.form['marka'], model=request.form['model'],
        rok=int(request.form['rok']), cena=float(request.form['cena']),
        przebieg=int(request.form.get('przebieg', 0)),
        opis=request.form['opis'] + ai_vision, telefon=request.form['telefon'],
        img=main_img, user_id=current_user.id,
        skrzynia=request.form.get('skrzynia'), paliwo=request.form.get('paliwo')
    )
    db.session.add(nowe_auto)
    db.session.flush()
    for p in saved_paths: db.session.add(CarImage(image_path=p, car_id=nowe_auto.id))
    db.session.commit()
    flash('Ogłoszenie dodane!', 'success')
    return redirect(url_for('profil'))

@app.route('/api/generate-description', methods=['POST'])
@login_required
def generate_ai_description():
    data = request.json
    try:
        res = model_ai.generate_content(f"Napisz opis: {data.get('marka')} {data.get('model')}, {data.get('rok')}.")
        return jsonify({"description": res.text})
    except: return jsonify({"description": "Błąd AI."})

@app.route('/odswiez/<int:car_id>', methods=['POST'])
@login_required
def odswiez_ogloszenie(car_id):
    """Przedłuża ogłoszenie o kolejne 30 dni (podbicie na górę)."""
    car = Car.query.get_or_404(car_id)
    if car.user_id != current_user.id: abort(403)
    car.data_dodania = datetime.utcnow()
    db.session.commit()
    flash('Ogłoszenie zostało odświeżone na kolejne 30 dni!', 'success')
    return redirect(url_for('profil'))

@app.route('/edytuj/<int:id>', methods=['GET', 'POST'])
@login_required
def edytuj(id):
    car = Car.query.get_or_404(id)
    if car.user_id != current_user.id: abort(403)
    if request.method == 'POST':
        car.marka = request.form['marka']; car.model = request.form['model']
        car.cena = request.form['cena']; car.opis = request.form['opis']
        db.session.commit()
        flash('Zapisano!', 'success')
        return redirect(url_for('profil'))
    return render_template('edytuj.html', car=car)

@app.route('/profil')
@login_required
def profil():
    cars = Car.query.filter_by(user_id=current_user.id).order_by(Car.id.desc()).all()
    return render_template('profil.html', cars=cars, fav_cars=current_user.favorite_cars, now=datetime.utcnow())

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
            login_user(user); return redirect(url_for('profil'))
    return render_template('login.html', now=datetime.utcnow())

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        u = User(username=request.form['username'], email=request.form['email'], 
                 password_hash=generate_password_hash(request.form['password']))
        db.session.add(u); db.session.commit(); return redirect(url_for('login'))
    return render_template('register.html', now=datetime.utcnow())

@app.route('/logout')
def logout(): logout_user(); return redirect(url_for('index'))

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
