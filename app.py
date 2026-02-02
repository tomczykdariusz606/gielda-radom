import os
import uuid
import google.generativeai as genai
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, abort, jsonify, Response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from PIL import Image
from thefuzz import process 

# Konfiguracja kluczy (jeśli nie masz sekrety.py, wpisz klucze tutaj)
try:
    import sekrety
    GEMINI_KEY = getattr(sekrety, 'GEMINI_KEY', '')
    MAIL_PASS = getattr(sekrety, 'MAIL_PWD', '')
except ImportError:
    GEMINI_KEY = ''
    MAIL_PASS = ''

app = Flask(__name__)
app.secret_key = 'gielda_radom_2026_key'
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
    favorite_cars = db.relationship('Car', secondary=favorites, backref='fans')

class Car(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    marka = db.Column(db.String(50), nullable=False)
    model = db.Column(db.String(50), nullable=False)
    rok = db.Column(db.Integer, nullable=False)
    cena = db.Column(db.Float, nullable=False)
    przebieg = db.Column(db.Integer, default=0)
    skrzynia = db.Column(db.String(20))
    paliwo = db.Column(db.String(20))
    opis = db.Column(db.Text, nullable=False)
    telefon = db.Column(db.String(20), nullable=False)
    img = db.Column(db.String(200), nullable=False) 
    data_dodania = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- LOGIKA INDEXU (WYSZUKIWARKA) ---
@app.route('/')
def index():
    now = datetime.utcnow()
    limit_daty = now - timedelta(days=30)
    
    # Pobieranie filtrów
    q = request.args.get('q', '').strip()
    skrzynia = request.args.get('skrzynia')
    paliwo = request.args.get('paliwo')
    cena_max = request.args.get('cena_max')
    przebieg_max = request.args.get('przebieg_max')

    # Podstawowe zapytanie (tylko aktywne ogłoszenia)
    query = Car.query.filter(Car.data_dodania >= limit_daty)

    # Filtracja techniczna
    if skrzynia: query = query.filter(Car.skrzynia == skrzynia)
    if paliwo: query = query.filter(Car.paliwo == paliwo)
    if cena_max:
        try: query = query.filter(Car.cena <= float(cena_max))
        except: pass
    if przebieg_max:
        try: query = query.filter(Car.przebieg <= int(przebieg_max))
        except: pass

    # Inteligentne wyszukiwanie AI (Fuzzy)
    if q:
        all_cars = query.all()
        choices = {f"{c.marka} {c.model}": c.id for c in all_cars}
        matches = process.extract(q, choices.keys(), limit=50)
        matched_ids = [choices[m[0]] for m in matches if m[1] > 55]
        query = query.filter(Car.id.in_(matched_ids))

    cars = query.order_by(Car.id.desc()).all()
    return render_template('index.html', cars=cars, now=now)

@app.route('/toggle_favorite/<int:car_id>')
@login_required
def toggle_favorite(car_id):
    car = Car.query.get_or_404(car_id)
    if car in current_user.favorite_cars:
        current_user.favorite_cars.remove(car)
    else:
        current_user.favorite_cars.append(car)
    db.session.commit()
    return redirect(request.referrer or url_for('index'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)
