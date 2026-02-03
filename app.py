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
app.config.update(
    MAIL_SERVER='poczta.o2.pl',
    MAIL_PORT=465,
    MAIL_USE_SSL=True,
    MAIL_USERNAME='dariusztom@go2.pl',
    MAIL_PASSWORD=sekrety.MAIL_PWD,
    MAIL_DEFAULT_SENDER='dariusztom@go2.pl'
)
mail = Mail(app)

# --- KONFIGURACJA GEMINI AI ---
genai.configure(api_key=sekrety.GEMINI_KEY)
model_ai = genai.GenerativeModel('gemini-1.5-flash') # Zalecany stabilny model vision

# --- KONFIGURACJA APLIKACJI ---
app.secret_key = 'sekretny_klucz_gieldy_radom_2024'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///gielda.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

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

class Car(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    typ = db.Column(db.String(20), default='Osobowe') # <--- NOWE POLE
    marka = db.Column(db.String(50), nullable=False)
    model = db.Column(db.String(50), nullable=False)
    rok = db.Column(db.Integer, nullable=False)
    cena = db.Column(db.Float, nullable=False)
    opis = db.Column(db.Text, nullable=False)
    telefon = db.Column(db.String(20), nullable=False)
    img = db.Column(db.String(200), nullable=False)
    zrodlo = db.Column(db.String(20), default='Radom')
    ai_label = db.Column(db.String(100), nullable=True)
    ai_valuation_data = db.Column(db.Text, nullable=True)
    data_dodania = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    skrzynia = db.Column(db.String(20))
    paliwo = db.Column(db.String(20))
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

# --- FUNKCJE POMOCNICZE ---
def save_optimized_image(file):
    filename = f"{uuid.uuid4().hex}.webp"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    img = Image.open(file)
    if img.mode in ("RGBA", "P"): img = img.convert("RGB")
    img.thumbnail((1200, 1200))
    img.save(filepath, "WEBP", quality=75)
    return filename

# --- TRASY API ---
@app.route('/api/analyze-car', methods=['POST'])
@login_required
def analyze_car_api():
    if 'image' not in request.files:
        return jsonify({"error": "Brak pliku"}), 400
    
    file = request.files['image']
    try:
        img = Image.open(file)
        prompt = (
            "Zidentyfikuj pojazd na zdjęciu. Zwróć dane TYLKO jako czysty JSON: "
            "{\"marka\": \"...\", \"model\": \"...\", \"rok\": 2020, \"typ\": \"Osobowe/Bus/Rower\", \"paliwo\": \"...\"}"
        )
        response = model_ai.generate_content([prompt, img])
        data = json.loads(response.text.replace('```json', '').replace('```', '').strip())
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/generate-description', methods=['POST'])
@login_required
def generate_ai_description():
    data = request.json
    prompt = f"Napisz krótki, atrakcyjny opis sprzedażowy dla: {data.get('marka')} {data.get('model')} z roku {data.get('rok')}."
    try:
        response = model_ai.generate_content(prompt)
        return jsonify({"description": response.text})
    except:
        return jsonify({"description": "Klasyk z Radomia, gotowy do jazdy!"})

# --- GŁÓWNE WIDOKI ---
@app.route('/')
def index():
    cars = Car.query.order_by(Car.id.desc()).all()
    return render_template('index.html', cars=cars, now=datetime.utcnow())

@app.route('/profil')
@login_required
def profil():
    my_cars = Car.query.filter_by(user_id=current_user.id).order_by(Car.id.desc()).all()
    fav_cars = current_user.favorite_cars
    
    stats = {
        "total_users": User.query.count(),
        "total_listings": Car.query.count(),
        "users_online": 1 # Uproszczenie
    }
    return render_template('profil.html', cars=my_cars, fav_cars=fav_cars, stats=stats, now=datetime.utcnow())

@app.route('/dodaj', methods=['POST'])
@login_required
def dodaj_ogloszenie():
    files = request.files.getlist('zdjecia')
    saved_paths = []
    for file in files[:5]:
        if file:
            name = save_optimized_image(file)
            saved_paths.append(url_for('static', filename='uploads/' + name))

    nowe_auto = Car(
        typ=request.form.get('typ', 'Osobowe'),
        marka=request.form['marka'],
        model=request.form['model'],
        rok=int(request.form['rok']),
        cena=float(request.form['cena']),
        przebieg=int(request.form.get('przebieg', 0)),
        opis=request.form['opis'],
        telefon=request.form['telefon'],
        paliwo=request.form.get('paliwo'),
        pojemnosc=request.form.get('pojemnosc'),
        img=saved_paths[0] if saved_paths else '',
        user_id=current_user.id
    )
    db.session.add(nowe_auto)
    db.session.flush()
    for p in saved_paths:
        db.session.add(CarImage(image_path=p, car_id=nowe_auto.id))
    db.session.commit()
    flash('Ogłoszenie dodane!', 'success')
    return redirect(url_for('profil'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
            login_user(user)
            return redirect(url_for('profil'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)
