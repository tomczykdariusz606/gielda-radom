import os
import uuid
import zipfile
import io
import sekrety  # Upewnij się, że ten plik istnieje i zawiera klucze
import google.generativeai as genai  
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, abort, jsonify, send_file, Response
from flask_sqlalchemy import SQLAlchemy
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

app.secret_key = sekrety.SECRET_KEY 
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///gielda.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- GEMINI AI ---
genai.configure(api_key=sekrety.GEMINI_KEY)
vision_model = genai.GenerativeModel('gemini-1.5-flash')

# --- MODELE ---
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

# --- LOGIKA BIZNESOWA ---
def get_market_valuation(car):
    base_prices = {"Audi": 1.25, "BMW": 1.28, "Mercedes": 1.30, "Volkswagen": 1.10}
    current_year = 2026
    age = max(1, current_year - car.rok)
    estimated_avg = 150000 * (0.85 ** age) * base_prices.get(car.marka, 1.0)
    diff_percent = ((car.cena - estimated_avg) / estimated_avg) * 100
    if diff_percent < -15: return {"status": "SUPER OKAZJA", "color": "#28a745", "avg": int(estimated_avg)}
    return {"status": "CENA RYNKOWA", "color": "#1a73e8", "avg": int(estimated_avg)}

@app.context_processor
def utility_processor():
    return dict(get_market_valuation=get_market_valuation)

@app.route('/api/generate-description', methods=['POST'])
@login_required
def generate_ai_description():
    data = request.json
    prompt = f"Napisz krótki, chwytliwy opis auta: {data.get('marka')} {data.get('model')}. Lokalizacja: Radom."
    try:
        response = vision_model.generate_content(prompt)
        return jsonify({"description": response.text})
    except:
        return jsonify({"description": "Błąd generowania opisu."})

# --- TRASY (ROUTES) ---
@app.route('/')
def index():
    q = request.args.get('q', '').strip()
    if q:
        all_cars = Car.query.all()
        choices = {f"{c.marka} {c.model}": c.id for c in all_cars}
        matches = process.extract(q, choices.keys(), limit=20)
        matched_ids = [choices[m[0]] for m in matches if m[1] > 55]
        cars = Car.query.filter(Car.id.in_(matched_ids)).all()
    else:
        cars = Car.query.order_by(Car.id.desc()).all()
    return render_template('index.html', cars=cars, now=datetime.utcnow())

@app.route('/dodaj', methods=['POST'])
@login_required
def dodaj():
    f = request.files.get('zdjecie')
    path = "https://placehold.co/600x400"
    if f:
        fname = f"{uuid.uuid4().hex}.webp"
        f.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
        path = f"/static/uploads/{fname}"
    
    nowe = Car(
        marka=request.form['marka'], model=request.form['model'],
        rok=int(request.form['rok']), cena=float(request.form['cena']),
        opis=request.form['opis'], telefon=request.form['telefon'],
        img=path, user_id=current_user.id
    )
    db.session.add(nowe)
    db.session.commit()
    return redirect(url_for('profil'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = User.query.filter_by(username=request.form['username']).first()
        if u and check_password_hash(u.password_hash, request.form['password']):
            login_user(u)
            return redirect(url_for('profil'))
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        u = User(username=request.form['username'], email=request.form['email'], 
                 password_hash=generate_password_hash(request.form['password']))
        db.session.add(u)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/profil')
@login_required
def profil():
    cars = Car.query.filter_by(user_id=current_user.id).all()
    return render_template('profil.html', cars=cars)

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000)
