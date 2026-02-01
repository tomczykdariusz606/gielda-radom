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
vision_model = genai.GenerativeModel('gemini-1.5-flash')

# --- KONFIGURACJA APLIKACJI ---
app.secret_key = sekrety.SECRET_KEY
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

# --- MODELE (NAPRAWIONE) ---
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
def load_user(user_id):
    return User.query.get(int(user_id))

# --- SILNIK ANALIZY ---
def get_market_valuation(car):
    base_prices = {"Audi": 1.25, "BMW": 1.28, "Mercedes": 1.30, "Volkswagen": 1.10}
    current_year = 2026
    age = max(1, current_year - car.rok)
    estimated_avg = 150000 * (0.85 ** age) * base_prices.get(car.marka, 1.0)
    diff_percent = ((car.cena - (estimated_avg * 0.97)) / (estimated_avg * 0.97)) * 100
    if diff_percent < -15:
        return {"status": "SUPER OKAZJA", "pos": 20, "color": "#28a745", "diff": round(diff_percent, 1), "avg": int(estimated_avg)}
    elif diff_percent < 5:
        return {"status": "CENA RYNKOWA", "pos": 50, "color": "#1a73e8", "diff": round(diff_percent, 1), "avg": int(estimated_avg)}
    return {"status": "POWYŻEJ ŚREDNIEJ", "pos": 80, "color": "#ce2b37", "diff": round(diff_percent, 1), "avg": int(estimated_avg)}

@app.context_processor
def utility_processor():
    return dict(get_market_valuation=get_market_valuation)

# --- POMOCNICZE ---
def save_optimized_image(file):
    filename = f"{uuid.uuid4().hex}.webp"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    img = Image.open(file)
    if img.mode in ("RGBA", "P"): img = img.convert("RGB")
    img.save(filepath, "WEBP", quality=75)
    return filename

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- TRASY (POPRAWIONE) ---

@app.route('/')
def index():
    query_text = request.args.get('q', '').strip()
    base_query = Car.query
    if query_text:
        all_cars = Car.query.all()
        choices = {f"{c.marka} {c.model}": c.id for c in all_cars}
        matches = process.extract(query_text, choices.keys(), limit=50)
        matched_ids = [choices[m[0]] for m in matches if m[1] > 55]
        base_query = base_query.filter(Car.id.in_(matched_ids))
    
    cars = base_query.order_by(Car.id.desc()).all()
    return render_template('index.html', cars=cars, now=datetime.utcnow(), request=request)

@app.route('/profil')
@login_required
def profil():
    # Zmienne my_cars i fav_cars przywrócone dla kompatybilności z Twoim HTML
    my_cars = Car.query.filter_by(user_id=current_user.id).order_by(Car.id.desc()).all()
    fav_cars = current_user.favorite_cars
    return render_template('profil.html', cars=my_cars, fav_cars=fav_cars, now=datetime.utcnow())

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
    for file in files[:10]:
        if file and allowed_file(file.filename):
            opt_name = save_optimized_image(file)
            saved_paths.append(f"/static/uploads/{opt_name}")
    
    main_img = saved_paths[0] if saved_paths else 'https://placehold.co/600x400'
    nowe_auto = Car(
        marka=request.form['marka'], model=request.form['model'],
        rok=int(request.form['rok']), cena=float(request.form['cena']),
        opis=request.form['opis'], telefon=request.form['telefon'],
        skrzynia=request.form.get('skrzynia'), paliwo=request.form.get('paliwo'),
        img=main_img, user_id=current_user.id
    )
    db.session.add(nowe_auto)
    db.session.flush()
    for path in saved_paths:
        db.session.add(CarImage(image_path=path, car_id=nowe_auto.id))
    db.session.commit()
    return redirect(url_for('profil'))

@app.route('/api/generate-description', methods=['POST'])
@login_required
def generate_ai_description():
    data = request.json
    prompt = f"Opis sprzedażowy dla {data.get('marka')} {data.get('model')} w Radomiu."
    try:
        response = vision_model.generate_content(prompt)
        return jsonify({"description": response.text})
    except:
        return jsonify({"description": "Na sprzedaż auto w dobrym stanie!"})

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
        u = User(username=request.form['username'], email=request.form['email'], 
                 password_hash=generate_password_hash(request.form['password']))
        db.session.add(u)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('register.html', now=datetime.utcnow())

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/usun/<int:car_id>', methods=['POST'])
@login_required
def delete_car(car_id):
    car = Car.query.get_or_404(car_id)
    if car.user_id == current_user.id:
        db.session.delete(car)
        db.session.commit()
    return redirect(url_for('profil'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000)
