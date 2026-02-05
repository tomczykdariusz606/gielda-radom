import os
import json
import zipfile
from datetime import datetime, date
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_mail import Mail, Message
import google.generativeai as genai

app = Flask(__name__)

# --- 1. KONFIGURACJA SERWERA ---
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'tajny-klucz-radom-76')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///instance/gielda.db' # Ścieżka do Twojej bazy 58MB
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Konfiguracja uploadu zdjęć
UPLOAD_FOLDER = os.path.join('static', 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Konfiguracja Mail (Reset hasła)
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USER')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASS')

# Konfiguracja Gemini AI
genai.configure(api_key=os.environ.get('GEMINI_KEY'))
model_ai = genai.GenerativeModel('gemini-1.5-flash')

db = SQLAlchemy(app)
mail = Mail(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- 2. MODELE BAZY DANYCH ---

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    lokalizacja = db.Column(db.String(100), default="Radom") # Nowe pole z formularza rejestracji
    
    # Limity AI
    ai_requests_today = db.Column(db.Integer, default=0)
    last_ai_request = db.Column(db.Date, default=date.today())

    # Relacje
    cars = db.relationship('Car', backref='author', lazy=True)
    favorites = db.relationship('Favorite', backref='user', lazy=True)

class Car(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    marka = db.Column(db.String(50), nullable=False)
    model = db.Column(db.String(50), nullable=False)
    rok = db.Column(db.Integer)
    cena = db.Column(db.Float)
    przebieg = db.Column(db.Integer)
    paliwo = db.Column(db.String(20))
    skrzynia = db.Column(db.String(20))
    nadwozie = db.Column(db.String(30))
    pojemnosc = db.Column(db.String(20))
    opis = db.Column(db.Text)
    telefon = db.Column(db.String(20))
    zrodlo = db.Column(db.String(50)) # Typ: Osobowe, Bus, Rower
    
    # Główne zdjęcie (miniaturka)
    img = db.Column(db.String(200)) 
    
    data_dodania = db.Column(db.DateTime, default=datetime.utcnow)
    wyswietlenia = db.Column(db.Integer, default=0)
    
    # Cache dla AI (Wycena)
    ai_label = db.Column(db.Text) 
    ai_valuation_data = db.Column(db.String(20))

    # Relacja do galerii zdjęć
    images = db.relationship('CarImage', backref='car', lazy=True, cascade="all, delete-orphan")

class CarImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    car_id = db.Column(db.Integer, db.ForeignKey('car.id'), nullable=False)
    image_path = db.Column(db.String(200), nullable=False)

class Favorite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    car_id = db.Column(db.Integer, db.ForeignKey('car.id'), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- 3. LOGIKA AI & POMOCNICZA ---

def check_ai_limit():
    """Sprawdza i resetuje dzienny limit zapytań AI"""
    if current_user.last_ai_request != date.today():
        current_user.ai_requests_today = 0
        current_user.last_ai_request = date.today()
        db.session.commit()
    
    if current_user.ai_requests_today >= 5: # Limit dzienny
        return False
    return True

# --- 4. TRASY AUTORYZACJI ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter((User.username == request.form.get('username')) | (User.email == request.form.get('username'))).first()
        if user and check_password_hash(user.password, request.form.get('password')):
            login_user(user)
            return redirect(url_for('profil'))
        flash('Błędny login lub hasło.', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        # Logika z Twojego nowego formularza
        username = request.form.get('username')
        email = request.form.get('email')
        location = request.form.get('location') # Dzielnica!
        password = request.form.get('password')

        if User.query.filter_by(email=email).first():
            flash('Email już istnieje.', 'warning')
            return redirect(url_for('register'))

        hashed_pw = generate_password_hash(password)
        new_user = User(username=username, email=email, lokalizacja=location, password=hashed_pw)
        
        db.session.add(new_user)
        db.session.commit()
        flash('Konto założone! Zaloguj się.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/reset_password', methods=['GET', 'POST'])
def reset_request():
    # Tu wstawisz logikę wysyłania maila (standard Flask-Mail)
    return render_template('reset_request.html')

# --- 5. GŁÓWNE TRASY APLIKACJI ---

@app.route('/')
def index():
    # Wyszukiwarka
    q = request.args.get('q', '')
    typ = request.args.get('typ', '')
    
    query = Car.query
    if q: query = query.filter(db.or_(Car.marka.icontains(q), Car.model.icontains(q)))
    if typ: query = query.filter(Car.zrodlo == typ)
    
    cars = query.order_by(Car.data_dodania.desc()).all()
    return render_template('index.html', cars=cars, now=datetime.utcnow())

@app.route('/profil')
@login_required
def profil():
    # Odśwież limit przy wejściu na profil
    check_ai_limit()
    
    user_cars = Car.query.filter_by(user_id=current_user.id).all()
    favorites = Favorite.query.filter_by(user_id=current_user.id).all()
    
    # Statystyki dla Admina
    stats = {}
    if current_user.id == 1:
        stats = {
            "users_online": 3, 
            "total_users": User.query.count(),
            "ai_errors": 0,
            "logs": ["System OK", "Baza podpięta"]
        }
        
    return render_template('profil.html', cars=user_cars, favorites=favorites, stats=stats, now=datetime.utcnow())

@app.route('/dodaj', methods=['POST'])
@login_required
def dodaj():
    # Pobieranie danych z modalu "Nowe Ogłoszenie AI"
    img_file = request.files.get('zdjecia') # Główne zdjęcie
    img_path = ''
    
    if img_file:
        filename = secure_filename(img_file.filename)
        img_path = os.path.join('static/uploads', filename)
        img_file.save(os.path.join(app.root_path, img_path))

    new_car = Car(
        user_id=current_user.id,
        marka=request.form.get('marka'),
        model=request.form.get('model'),
        rok=request.form.get('rok'),
        przebieg=request.form.get('przebieg'),
        cena=request.form.get('cena'),
        paliwo=request.form.get('paliwo'),
        skrzynia=request.form.get('skrzynia'),
        nadwozie=request.form.get('nadwozie'),
        pojemnosc=request.form.get('pojemnosc'),
        telefon=request.form.get('telefon'),
        opis=request.form.get('opis'),
        zrodlo=request.form.get('typ'),
        img=img_path
    )
    db.session.add(new_car)
    db.session.commit()
    flash('Ogłoszenie dodane!', 'success')
    return redirect(url_for('profil'))

@app.route('/edytuj/<int:car_id>', methods=['GET', 'POST'])
@login_required
def edit_car(car_id):
    car = Car.query.get_or_404(car_id)
    if car.user_id != current_user.id and not current_user.is_admin:
        return redirect(url_for('profil'))

    if request.method == 'POST':
        car.marka = request.form.get('marka')
        car.model = request.form.get('model')
        car.cena = request.form.get('cena')
        car.rok = request.form.get('rok')
        car.przebieg = request.form.get('przebieg')
        car.paliwo = request.form.get('paliwo')
        car.skrzynia = request.form.get('skrzynia')
        car.nadwozie = request.form.get('nadwozie')
        car.pojemnosc = request.form.get('pojemnosc')
        car.telefon = request.form.get('telefon')
        car.opis = request.form.get('opis')
        
        # Obsługa dodawania nowych zdjęć do galerii
        files = request.files.getlist('zdjecia')
        for file in files:
            if file and file.filename != '':
                fname = secure_filename(file.filename)
                fpath = os.path.join('static/uploads', fname)
                file.save(os.path.join(app.root_path, fpath))
                new_img = CarImage(car_id=car.id, image_path=fpath)
                db.session.add(new_img)

        db.session.commit()
        flash('Zaktualizowano!', 'success')
        return redirect(url_for('profil'))

    return render_template('edit.html', car=car)

@app.route('/usun_zdjecie/<int:photo_id>', methods=['POST'])
@login_required
def delete_photo(photo_id):
    photo = CarImage.query.get_or_404(photo_id)
    if photo.car.user_id != current_user.id:
        return jsonify({"success": False}), 403
    
    # Usuń plik
    try:
        full_path = os.path.join(app.root_path, photo.image_path)
        if os.path.exists(full_path):
            os.remove(full_path)
    except: pass

    db.session.delete(photo)
    db.session.commit()
    return jsonify({"success": True})

# --- 6. API AI (GEMINI) ---

@app.route('/api/analyze-car', methods=['POST'])
@login_required
def api_analyze_car():
    """Analiza zdjęcia dla formularza 'Dodaj Ogłoszenie'"""
    if not check_ai_limit():
        return jsonify({"error": "Limit wyczerpany"}), 429

    file = request.files.get('image')
    if not file: return jsonify({"error": "Brak pliku"}), 400

    img_data = file.read()
    prompt = """Rozpoznaj samochód na zdjęciu. 
    Zwróć TYLKO JSON: {"marka": "...", "model": "...", "sugestia": "krótka, 1-zdanionwa zachęta dla kupującego"}"""
    
    try:
        response = model_ai.generate_content([prompt, {"mime_type": "image/jpeg", "data": img_data}])
        current_user.ai_requests_today += 1
        db.session.commit()
        
        clean_json = response.text.replace('```json', '').replace('```', '').strip()
        return jsonify(json.loads(clean_json))
    except Exception as e:
        return jsonify({"marka": "", "model": "", "sugestia": "Wpisz dane ręcznie"}), 500

@app.route('/api/generate-description', methods=['POST'])
@login_required
def api_gen_desc():
    """Generowanie/Poprawa opisu w edycji"""
    data = request.get_json()
    marka = data.get('marka')
    model = data.get('model')
    info = data.get('current_text', '')
    
    prompt = f"Jesteś handlarzem aut. Napisz profesjonalny opis sprzedaży dla {marka} {model}. Uwzględnij te informacje: {info}. Użyj emoji."
    
    try:
        response = model_ai.generate_content(prompt)
        return jsonify({"description": response.text})
    except:
        return jsonify({"description": info})

# --- 7. SEO & ADMIN ---

@app.route('/robots.txt')
def robots():
    return send_from_directory('static', 'robots.txt')

@app.route('/sitemap.xml')
def sitemap():
    cars = Car.query.all()
    return render_template('sitemap.xml', cars=cars, now=date.today())

@app.route('/admin/full_backup')
@login_required
def full_backup():
    if not current_user.is_admin: return "Brak uprawnień", 403
    
    fname = f"backup_radom_{datetime.now().strftime('%Y%m%d')}.zip"
    with zipfile.ZipFile(fname, 'w') as z:
        z.write('instance/gielda.db')
        # Opcjonalnie dodaj folder uploads
    return send_from_directory('.', fname, as_attachment=True)

if __name__ == '__main__':
    with app.app_context():
        # Uruchom to RAZ, aby zaktualizować bazę o nowe kolumny,
        # jeśli baza jest stara i nie ma np. kolumny 'lokalizacja'.
        # db.create_all() nie nadpisuje istniejących tabel, więc jest bezpieczne,
        # ale nie doda kolumn do istniejącej tabeli (trzeba migracji lub usunięcia pliku db).
        db.create_all() 
    app.run(debug=True, host='0.0.0.0', port=5000)
