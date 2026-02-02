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
model_ai = genai.GenerativeModel('gemini-1.5-flash')

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

# --- MODELE (Z DODANYM POLEM ANALIZY) ---

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
        try:
            user_id = s.loads(token)['user_id']
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
    
    # NOWE POLA NA ANALIZĘ AI
    ai_label = db.Column(db.String(100)) # Rozpoznana marka/model ze zdjęcia
    ai_valuation_data = db.Column(db.Text) # Wynik analizy ceny w formacie JSON lub tekst
    
    images = db.relationship('CarImage', backref='car', lazy=True, cascade="all, delete-orphan")

class CarImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    image_path = db.Column(db.String(200), nullable=False)
    car_id = db.Column(db.Integer, db.ForeignKey('car.id'), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- SILNIK ANALIZY RYNKOWEJ (TERAZ KORZYSTA Z DANYCH ZAPISANYCH PRZEZ AI) ---
def get_market_valuation(car):
    # Jeśli AI zapisało analizę, używamy jej
    if car.ai_valuation_data and "status" in car.ai_valuation_data:
        import json
        try:
            return json.loads(car.ai_valuation_data)
        except:
            pass
            
    # Prosty fallback, gdyby AI nie odpowiedziało
    return {"status": "W TRAKCIE ANALIZY", "pos": 50, "color": "#6c757d", "diff": 0, "avg": int(car.cena)}

@app.context_processor
def utility_processor():
    return dict(get_market_valuation=get_market_valuation)

# --- POMOCNICZE ---
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

# --- TRASY APLIKACJI ---

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

@app.route('/dodaj', methods=['POST'])
@login_required
def dodaj_ogloszenie():
    files = request.files.getlist('zdjecia')
    saved_paths = []
    for file in files[:10]:
        if file and allowed_file(file.filename):
            opt_name = save_optimized_image(file)
            path = url_for('static', filename='uploads/' + opt_name)
            saved_paths.append(path)
            
    main_img = saved_paths[0] if saved_paths else 'https://placehold.co/600x400?text=Brak+Zdjecia'
    
    # DANE Z FORMULARZA
    marka_uzytkownika = request.form['marka']
    model_uzytkownika = request.form['model']
    cena = float(request.form['cena'])
    rok = int(request.form['rok'])
    paliwo = request.form.get('paliwo', 'Benzyna')

    ai_marka_model = "Nie rozpoznano"
    ai_valuation_json = "{}"

    # --- ANALIZA GEMINI VISION (ROZPOZNAWANIE I CENA) ---
    if saved_paths:
        try:
            img_path = os.path.join(app.root_path, saved_paths[0].lstrip('/'))
            img_to_analyze = Image.open(img_path)
            
            # Prompt 1: Rozpoznawanie auta
            prompt_vision = f"Co to za samochód na zdjęciu? Podaj tylko Markę i Model. Użytkownik twierdzi, że to {marka_uzytkownika} {model_uzytkownika}. Jeśli to prawda, potwierdź. Jeśli nie, napisz co widzisz."
            vision_response = model_ai.generate_content([prompt_vision, img_to_analyze])
            ai_marka_model = vision_response.text.strip()

            # Prompt 2: Analiza ceny (prawdziwa, nie z algorytmu)
            prompt_price = f"""Jesteś ekspertem rynku wtórnego aut w Polsce. 
            Oceń cenę {cena} PLN za samochód {marka_uzytkownika} {model_uzytkownika} z {rok} roku (paliwo: {paliwo}). 
            Zwróć TYLKO kod JSON: 
            {{"status": "SUPER OKAZJA" lub "CENA RYNKOWA" lub "POWYŻEJ ŚREDNIEJ", 
              "pos": liczba od 0 do 100 gdzie 20 to okazja a 80 to drogo, 
              "color": kod hex koloru, 
              "diff": o ile procent różni się od średniej, 
              "avg": szacowana cena rynkowa}}"""
            
            price_response = model_ai.generate_content(prompt_price)
            # Próba wyłuskania czystego JSONa
            import json
            raw_text = price_response.text.replace('```json', '').replace('```', '').strip()
            ai_valuation_json = raw_text
        except Exception as e:
            print(f"Błąd AI: {e}")

    nowe_auto = Car(
        marka=marka_uzytkownika, model=model_uzytkownika,
        rok=rok, cena=cena,
        opis=request.form['opis'], telefon=request.form['telefon'],
        skrzynia=request.form.get('skrzynia'), paliwo=paliwo,
        img=main_img, user_id=current_user.id,
        ai_label=ai_marka_model,
        ai_valuation_data=ai_valuation_json
    )
    db.session.add(nowe_auto)
    db.session.flush()
    for path in saved_paths:
        db.session.add(CarImage(image_path=path, car_id=nowe_auto.id))
    db.session.commit()
    flash(f'Dodano! AI rozpoznało: {ai_marka_model}', 'success')
    return redirect(url_for('profil'))

# --- POZOSTAŁE FUNKCJE (BEZ ZMIAN NAZW) ---

@app.route('/profil')
@login_required
def profil():
    my_cars = Car.query.filter_by(user_id=current_user.id).order_by(Car.id.desc()).all()
    fav_cars = current_user.favorite_cars
    return render_template('profil.html', cars=my_cars, fav_cars=fav_cars, now=datetime.utcnow())

@app.route('/ogloszenie/<int:car_id>')
def car_details(car_id):
    car = Car.query.get_or_404(car_id)
    car.wyswietlenia = (car.wyswietlenia or 0) + 1
    db.session.commit()
    return render_template('details.html', car=car, now=datetime.utcnow())

@app.route('/api/generate-description', methods=['POST'])
@login_required
def generate_ai_description():
    data = request.json
    prompt = f"Opis sprzedażowy dla {data.get('marka')} {data.get('model')} z {data.get('rok')}r."
    try:
        response = model_ai.generate_content(prompt)
        return jsonify({"description": response.text})
    except:
        return jsonify({"description": "Auto w świetnym stanie!"})

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

@app.route('/odswiez/<int:car_id>', methods=['POST'])
@login_required
def refresh_car(car_id):
    car = Car.query.get_or_404(car_id)
    if car.user_id == current_user.id:
        car.data_dodania = datetime.utcnow()
        db.session.commit()
    return redirect(url_for('profil'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)
