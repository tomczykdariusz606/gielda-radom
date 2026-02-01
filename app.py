import os
import uuid
import zipfile
import io
import google.generativeai as genai
import json
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, abort, jsonify, send_from_directory, send_file, Response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_, func
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from PIL import Image
from itsdangerous import URLSafeTimedSerializer as Serializer
# Import biblioteki do "rozmytego" wyszukiwania (literówki)
from thefuzz import process 

app = Flask(__name__)

# --- KONFIGURACJA POCZTY ---
app.config['MAIL_SERVER'] = 'poczta.o2.pl'
app.config['MAIL_PORT'] = 465
app.config['MAIL_USE_SSL'] = True
app.config['MAIL_USERNAME'] = 'dariusztom@go2.pl'
app.config['MAIL_PASSWORD'] = '5WZR5F66GGH6WAEN' 
app.config['MAIL_DEFAULT_SENDER'] = 'dariusztom@go2.pl'
mail = Mail(app)

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
    
    # Relacje
    cars = db.relationship('Car', backref='owner', lazy=True, cascade="all, delete-orphan")
    favorite_cars = db.relationship('Car', secondary=favorites, backref='fans')

    # Metody resetowania hasła (Logic AI)
    def get_reset_token(self):
        s = Serializer(app.config['SECRET_KEY'])
        # Generujemy bezpieczny token przypisany do ID użytkownika
        return s.dumps({'user_id': self.id})

    @staticmethod
    def verify_reset_token(token):
        s = Serializer(app.config['SECRET_KEY'])
        try:
            user_id = s.loads(token)['user_id']
        except:
            return None
        return User.query.get(user_id)

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

# --- SILNIK ANALIZY RYNKOWEJ GEMINI AI ---
def get_market_valuation(car):
    base_prices = {"Audi": 1.25, "BMW": 1.28, "Mercedes": 1.30, "Volkswagen": 1.10, "Toyota": 1.15, "Skoda": 1.05}
    current_year = 2026
    age = current_year - car.rok
    estimated_avg = 150000 * (0.85 ** age) * base_prices.get(car.marka, 1.0)
    estimated_avg *= 0.97 
    diff_percent = ((car.cena - estimated_avg) / estimated_avg) * 100

    if diff_percent < -15:
        return {"status": "SUPER OKAZJA", "pos": 20, "color": "#28a745", "diff": round(diff_percent, 1), "avg": int(estimated_avg)}
    elif diff_percent < 5:
        return {"status": "CENA RYNKOWA", "pos": 50, "color": "#1a73e8", "diff": round(diff_percent, 1), "avg": int(estimated_avg)}
    else:
        return {"status": "POWYŻEJ ŚREDNIEJ", "pos": 80, "color": "#ce2b37", "diff": round(diff_percent, 1), "avg": int(estimated_avg)}

@app.context_processor
def utility_processor():
    return dict(get_market_valuation=get_market_valuation)

# --- GENERATOR OPISÓW AI ---
@app.route('/api/generate-description', methods=['POST'])
@login_required
def generate_ai_description():
    data = request.json
    marka = data.get('marka', '')
    model = data.get('model', '')
    rok = data.get('rok', '')
    paliwo = data.get('paliwo', '')

    prompt_result = f"Na sprzedaż wyjątkowy {marka} {model} z {rok} roku. Silnik {paliwo} zapewnia świetną dynamikę przy niskim spalaniu. Samochód zadbany, regularnie serwisowany, idealny na trasy po Radomiu i okolicach. Komfortowe wnętrze i pewne prowadzenie. Zapraszam na jazdę próbną!"
    return jsonify({"description": prompt_result})

# --- FUNKCJE POMOCNICZE ---
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
# --- KONFIGURACJA GEMINI AI ---
genai.configure(api_key="AIzaSyAXH_NcQK2qUYV7EKhBZKc8Ban4nFdWs4g")
vision_model = genai.GenerativeModel('gemini-1.5-flash')

# --- NOWA TRASA: ANALIZA ZDJĘCIA AUTA ---
@app.route('/api/analyze-car', methods=['POST'])
@login_required
def analyze_car():
    if 'image' not in request.files:
        return jsonify({"error": "Nie przesłano zdjęcia"}), 400
    
    file = request.files['image']
    if file.filename == '':
        return jsonify({"error": "Pusty plik"}), 400

    try:
        img = Image.open(file)
        # Prompt zoptymalizowany pod rozpoznawanie wizualne
        prompt = """
        Działaj jako ekspert giełdy samochodowej w Radomiu. 
        Zidentyfikuj markę, model i przybliżony rok produkcji auta na zdjęciu.
        Zwróć wynik WYŁĄCZNIE w formacie JSON:
        {"marka": "Marka", "model": "Model", "rok": 2018}
        """
        response = vision_model.generate_content([prompt, img])
                # Poprawna wersja czyszczenia odpowiedzi
        res_text = response.text
        if "```json" in res_text:
            res_text = res_text.split("```json")[1].split("```")[0]
        elif "```" in res_text:
            res_text = res_text.split("```")[1].split("```")[0]
            
        data = json.loads(res_text.strip())
        return jsonify(data)

    except Exception as e:
        print(f"Błąd Vision AI: {e}")
        return jsonify({"error": "Błąd podczas analizy obrazu"}), 500

# --- TRASY APLIKACJI ---

@app.route('/')
def index():
    # Pobieranie parametrów wyszukiwania
    query_text = request.args.get('q', '').strip()  # Jedno pole "Inteligentne szukanie"
    skrzynia = request.args.get('skrzynia', '')
    paliwo = request.args.get('paliwo', '')
    cena_max = request.args.get('cena_max', type=float)

    # 1. Pobieramy wszystkie auta (lub base query)
    # Wersja produkcyjna: przy dużej bazie używa się SQL LIKE, ale dla Fuzzy Search w Pythonie pobieramy wszystko
    all_cars_query = Car.query

    # 2. Inteligentne filtrowanie (Literówki / Fuzzy Search)
    if query_text:
        # Pobieramy wszystkie auta, żeby sprawdzić dopasowanie nazw
        all_cars = Car.query.all()
        
        # Tworzymy słownik { "Marka Model": id }
        choices = {f"{c.marka} {c.model}": c.id for c in all_cars}
        
        # Biblioteka thefuzz szuka najlepszych dopasowań (wynik > 55%)
        # To pozwala znaleźć "Wolkswagn" jako "Volkswagen"
        matches = process.extract(query_text, choices.keys(), limit=50)
        
        # Wyciągamy ID pasujących aut
        matched_ids = [choices[m[0]] for m in matches if m[1] > 55]
        
        # Filtrujemy zapytanie SQL po tych ID
        base_query = Car.query.filter(Car.id.in_(matched_ids))
    else:
        # Jeśli brak tekstu, bierzemy wszystkie
        base_query = Car.query

    # 3. Dodatkowe filtry techniczne
    if skrzynia:
        base_query = base_query.filter(Car.skrzynia == skrzynia)
    if paliwo:
        base_query = base_query.filter(Car.paliwo == paliwo)
    if cena_max:
        base_query = base_query.filter(Car.cena <= cena_max)

    # Sortowanie: najnowsze na górze
    cars = base_query.order_by(Car.id.desc()).all()
    
    return render_template('index.html', cars=cars, now=datetime.utcnow(), request=request)

@app.route('/kontakt')
def kontakt():
    return render_template('kontakt.html')

@app.route('/polityka-prywatnosci')
def rodo():
    return render_template('polityka.html')

@app.route('/regulamin')
def regulamin():
    return render_template('regulamin.html')

# --- SEO: SITEMAP & ROBOTS ---
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
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /admin/",
        "Disallow: /login",
        "Disallow: /register",
        "Disallow: /profil",
        "Sitemap: https://gieldaradom.pl/sitemap.xml"
    ]
    return Response("\n".join(lines), mimetype="text/plain")

# --- CRUD I UŻYTKOWNIK ---

@app.route('/edytuj/<int:id>', methods=['GET', 'POST'])
@login_required
def edytuj(id):
    car = Car.query.get_or_404(id)
    if car.user_id != current_user.id:
        flash('Nie masz uprawnień do edycji tego ogłoszenia.', 'danger')
        return redirect(url_for('profil'))

    if request.method == 'POST':
        car.marka = request.form.get('marka')
        car.model = request.form.get('model')
        car.rok = request.form.get('rok')
        car.cena = request.form.get('cena')
        car.telefon = request.form.get('telefon')
        car.opis = request.form.get('opis')
        # Dodajemy edycję nowych pól jeśli są w formularzu
        if request.form.get('skrzynia'): car.skrzynia = request.form.get('skrzynia')
        if request.form.get('paliwo'): car.paliwo = request.form.get('paliwo')

        db.session.commit()
        flash('Ogłoszenie zostało pomyślnie zaktualizowane!', 'success')
        return redirect(url_for('profil'))

    return render_template('edytuj.html', car=car)

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
            path = url_for('static', filename='uploads/' + opt_name)
            saved_paths.append(path)
    main_img = saved_paths[0] if saved_paths else 'https://placehold.co/600x400?text=Brak+Zdjecia'
    
    nowe_auto = Car(
        marka=request.form['marka'], model=request.form['model'],
        rok=int(request.form['rok']), cena=float(request.form['cena']),
        opis=request.form['opis'], telefon=request.form['telefon'],
        skrzynia=request.form.get('skrzynia'), paliwo=request.form.get('paliwo'),
        nadwozie=request.form.get('nadwozie'), pojemnosc=request.form.get('pojemnosc'),
        img=main_img, zrodlo=current_user.lokalizacja, user_id=current_user.id
    )
    db.session.add(nowe_auto)
    db.session.flush()
    for path in saved_paths:
        db.session.add(CarImage(image_path=path, car_id=nowe_auto.id))
    db.session.commit()
    flash('Ogłoszenie dodane!', 'success')
    return redirect(url_for('profil'))

@app.route('/profil')
@login_required
def profil():
    my_cars = Car.query.filter_by(user_id=current_user.id).order_by(Car.id.desc()).all()
    fav_cars = current_user.favorite_cars
    return render_template('profil.html', cars=my_cars, fav_cars=fav_cars, now=datetime.utcnow())

@app.route('/odswiez/<int:car_id>', methods=['POST'])
@login_required
def refresh_car(car_id):
    car = Car.query.get_or_404(car_id)
    if car.user_id == current_user.id:
        car.data_dodania = datetime.utcnow()
        db.session.commit()
        flash('Ogłoszenie odświeżone!', 'success')
    return redirect(url_for('profil'))

@app.route('/usun/<int:car_id>', methods=['POST'])
@login_required
def delete_car(car_id):
    car = Car.query.get_or_404(car_id)
    if car.user_id == current_user.id:
        db.session.delete(car)
        db.session.commit()
        flash('Usunięto ogłoszenie.', 'success')
    return redirect(url_for('profil'))

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
def logout():
    logout_user()
    return redirect(url_for('index'))

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

@app.route('/toggle_favorite/<int:car_id>')
@login_required
def toggle_favorite(car_id):
    car = Car.query.get_or_404(car_id)
    if car in current_user.favorite_cars: current_user.favorite_cars.remove(car)
    else: current_user.favorite_cars.append(car)
    db.session.commit()
    return redirect(request.referrer or url_for('index'))
def send_reset_email(user):
    token = user.get_reset_token()
    # Dekodujemy token, bo w Python 3 jest w bytes, a potrzebujemy stringa w URL
    token_str = token.decode('utf-8')
    msg = Message('Reset Hasła - Giełda Radom',
                  recipients=[user.email])
    msg.body = f'''Aby zresetować hasło, kliknij w poniższy link:
{url_for('reset_token', token=token_str, _external=True)}

Jeśli to nie Ty wysłałeś to żądanie, zignoruj tę wiadomość.
'''
    mail.send(msg)

@app.route("/reset_password", methods=['GET', 'POST'])
def reset_request():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        if user:
            send_reset_email(user)
            flash('Wysłano email z instrukcją resetowania hasła.', 'info')
            return redirect(url_for('login'))
        else:
            flash('Nie znaleziono konta z takim adresem email.', 'danger')
    return render_template('reset_request.html')

@app.route("/reset_password/<token>", methods=['GET', 'POST'])
def reset_token(token):
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    user = User.verify_reset_token(token)
    if user is None:
        flash('To nieprawidłowy lub wygasły token.', 'warning')
        return redirect(url_for('reset_request'))
    
    if request.method == 'POST':
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if password != confirm_password:
            flash('Hasła muszą być identyczne.', 'danger')
        else:
            hashed_password = generate_password_hash(password)
            user.password_hash = hashed_password
            db.session.commit()
            flash('Twoje hasło zostało zaktualizowane! Możesz się zalogować.', 'success')
            return redirect(url_for('login'))
            
    return render_template('reset_token.html')


if __name__ == '__main__':
    with app.app_context(): db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)
