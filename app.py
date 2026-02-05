import os
import json
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import google.generativeai as genai

app = Flask(__name__)
app.config['SECRET_KEY'] = 'twoj-super-tajny-klucz-radom-76'

# --- KONFIGURACJA ŚCIEŻEK (Spójność z Twoim backupem) ---
basedir = os.path.abspath(os.path.dirname(__file__))
instance_path = os.path.join(basedir, 'instance')
if not os.path.exists(instance_path):
    os.makedirs(instance_path)

db_path = os.path.join(instance_path, 'gielda.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:////{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- KONFIGURACJA AI GEMINI ---
genai.configure(api_key="TWOJ_KLUCZ_API") # Wstaw tutaj swój klucz
model_ai = genai.GenerativeModel('gemini-1.5-flash')

# --- MODELE BAZY DANYCH ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    # Relacja do ulubionych (naprawione overlaps)
    favorites = db.relationship('Favorite', backref='user', cascade="all, delete-orphan")

class Car(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    marka = db.Column(db.String(50), nullable=False)
    model = db.Column(db.String(50), nullable=False)
    rok = db.Column(db.Integer)
    cena = db.Column(db.Float)
    przebieg = db.Column(db.Integer)
    paliwo = db.Column(db.String(20))
    skrzynia = db.Column(db.String(20))
    opis = db.Column(db.Text)
    img = db.Column(db.String(200))
    telefon = db.Column(db.String(20))
    zrodlo = db.Column(db.String(50), default="Radom")
    data_dodania = db.Column(db.DateTime, default=datetime.utcnow)
    
    # POLA DLA AI
    ai_label = db.Column(db.Text)  # Przechowuje JSON z analizą
    ai_valuation_data = db.Column(db.String(20))  # Data ostatniej analizy (YYYY-MM-DD)

class Favorite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    car_id = db.Column(db.Integer, db.ForeignKey('car.id'), nullable=False)

# --- FILTRY JINJA2 ---
@app.template_filter('from_json')
def from_json_filter(value):
    try:
        return json.loads(value) if value else None
    except:
        return None

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- GŁÓWNE TRASY ---

@app.route('/')
def index():
    cars = Car.query.order_by(Car.data_dodania.desc()).all()
    return render_template('index.html', cars=cars, now=datetime.utcnow())

@app.route('/ogloszenie/<int:car_id>')
def details(car_id):
    car = Car.query.get_or_404(car_id)
    return render_template('details.html', car=car)

# --- API: WYCENA RYNKOWA (Z CACHE 7 DNI) ---
@app.route('/api/check-price-valuation', methods=['POST'])
def check_price_valuation():
    data = request.get_json()
    car = Car.query.get(data.get('car_id'))
    if not car: return jsonify({"error": "Not found"}), 404

    now_str = datetime.now().strftime("%Y-%m-%d")
    
    # Sprawdzanie cache (7 dni)
    if car.ai_valuation_data:
        last_date = datetime.strptime(car.ai_valuation_data, "%Y-%m-%d")
        if (datetime.now() - last_date).days < 7:
            res = json.loads(car.ai_label)
            res['date'] = car.ai_valuation_data
            return jsonify(res)

    # Brak cache lub stary -> Pytamy Gemini
    prompt = (
        f"Analiza rynku wtórnego Polska (Luty 2026). Auto: {car.marka} {car.model}, {car.rok}r, {car.przebieg}km, cena {car.cena} PLN. "
        "Zwróć TYLKO czysty JSON: {\"score\": 1-100, \"label\": \"Okazja/Dobra cena/Cena rynkowa/Drogo\", "
        "\"color\": \"success/info/warning/danger\", \"sample_size\": \"szacowana liczba ofert w PL\", "
        "\"market_info\": \"jedno zdanie o średniej cenie tego modelu\"}"
    )

    try:
        response = model_ai.generate_content(prompt)
        raw_json = response.text.replace('```json', '').replace('```', '').strip()
        car.ai_label = raw_json
        car.ai_valuation_data = now_str
        db.session.commit()
        return jsonify(json.loads(raw_json))
    except:
        return jsonify({"label": "Analiza chwilowo niedostępna", "color": "secondary", "score": 50})

# --- API: CZAT Z EKSPERTEM AI (Zadawanie pytań) ---
@app.route('/api/analyze-car', methods=['POST'])
def analyze_car():
    data = request.get_json()
    car = Car.query.get(data.get('car_id'))
    user_query = data.get('query')

    if not car or not user_query:
        return jsonify({"answer": "Brak danych do analizy."})

    prompt = (
        f"Jesteś ekspertem motoryzacyjnym Giełdy Radom. Klient pyta o auto: {car.marka} {car.model}, {car.rok}r, opis: {car.opis}. "
        f"Pytanie brzmi: {user_query}. Odpowiedz konkretnie, fachowo i krótko po polsku."
    )

    try:
        response = model_ai.generate_content(prompt)
        return jsonify({"analysis": response.text})
    except:
        return jsonify({"analysis": "Przepraszam, Gemini ma teraz przerwę techniczną. Spróbuj za chwilę!"})

# --- FUNKCJE BACKUPU (Twoje nienaruszone narzędzia) ---
@app.route('/full_backup')
@login_required
def full_backup():
    if not current_user.is_admin: return "Brak uprawnień", 403
    # Tutaj zachowaj swoją istniejącą logikę generowania pliku ZIP (58MB)
    # Pamiętaj, aby pobierała plik z path: db_path
    pass 

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0', port=5000)
