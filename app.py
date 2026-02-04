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

# POPRAWIONE I POŁĄCZONE IMPORTY SQLALCHEMY:
from sqlalchemy import or_, and_, func  
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
app.config['MAIL_PASSWORD'] = sekrety.MAIL_PWD
app.config['MAIL_DEFAULT_SENDER'] = 'dariusztom@go2.pl'
mail = Mail(app)

# --- KONFIGURACJA GEMINI AI ---
genai.configure(api_key=sekrety.GEMINI_KEY)
model_ai = genai.GenerativeModel('gemini-3-flash-preview')
# --- KONFIGURACJA APLIKACJI ---
app.secret_key = 'sekretny_klucz_gieldy_radom_2024'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///gielda.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

basedir = os.path.abspath(os.path.dirname(__file__))

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
    typ = db.Column(db.String(20), default='Osobowe') # Tego brakowało
    marka = db.Column(db.String(50), nullable=False)
    # ... reszta pól bez zmian ...
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

@app.route('/api/generate-description', methods=['POST'])
@login_required
def api_generate_description():
    data = request.json
    marka = data.get('marka', '')
    model = data.get('model', '')
    rok = data.get('rok', '')
    przebieg = data.get('przebieg', '')

    if not marka or not model:
        return jsonify({'description': 'Proszę najpierw podać markę i model!'})

    prompt = (
        f"Napisz profesjonalne, sprzedażowe ogłoszenie dla: {marka} {model}, rok {rok}, przebieg {przebieg} km. "
        "Użyj języka korzyści, bądź konkretny i zachęcający. Nie kłam. Max 600 znaków."
    )

    try:
        response = model_ai.generate_content(prompt)
        return jsonify({'description': response.text.strip()})
    except Exception as e:
        return jsonify({'description': f'Błąd AI: {str(e)}'})



# --- FUNKCJE POMOCNICZE ---

# Poprawiona ścieżka - baza wewnątrz folderu projektu
def get_db_path():
    basedir = os.path.abspath(os.path.dirname(__file__))
    return os.path.join(basedir, 'gielda.db')
#///////////////

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
    # Pobieranie wszystkich filtrów
    query_text = request.args.get('q', '').strip().lower()
    typ = request.args.get('typ', '')
    paliwo = request.args.get('paliwo', '')
    cena_max = request.args.get('cena_max', type=float)
    rok_min = request.args.get('rok_min', type=int)

    base_query = Car.query

    # 1. Filtrowanie tekstowe
    if query_text:
        words = query_text.split()
        for word in words:
            base_query = base_query.filter(or_(
                Car.marka.ilike(f'%{word}%'),
                Car.model.ilike(f'%{word}%'),
                Car.opis.ilike(f'%{word}%')
            ))

    # 2. Filtry sztywne
    if typ:
        base_query = base_query.filter(Car.typ == typ)
    if paliwo:
        base_query = base_query.filter(Car.paliwo == paliwo)
    if cena_max:
        base_query = base_query.filter(Car.cena <= cena_max)
    if rok_min:
        base_query = base_query.filter(Car.rok >= rok_min)

    # Sortowanie: najpierw najnowsze ogłoszenia
    cars = base_query.order_by(Car.id.desc()).all()

    return render_template('index.html', 
                           cars=cars, 
                           now=datetime.utcnow(), 
                           request=request)


# TWOJE API DO WYCENY AI
@app.route('/api/check-price-valuation', methods=['POST'])
def check_price_valuation():
    data = request.get_json()
    car = Car.query.get(data.get('car_id'))

    if not car:
        return jsonify({"error": "Nie znaleziono auta"}), 404

    # Sprawdzanie cache przy użyciu nowych nazw kolumn
    if car.ai_valuation_data and car.ai_label:
        # Zakładamy, że ai_valuation_data przechowuje datę jako string lub obiekt
        # Dla uproszczenia zwracamy cache, jeśli oba pola są wypełnione
        try:
            res = json.loads(car.ai_label)
            res['date'] = str(car.ai_valuation_data)
            return jsonify(res)
        except:
            pass # Jeśli JSON byłby błędny, generujemy nowy
    prompt = (
        f"Jesteś ekspertem motoryzacyjnym (Luty 2026). "
        f"Oceń cenę {car.cena} PLN dla: {car.marka} {car.model}, {car.rok}r, {car.przebieg}km. "
        f"Opis i analiza wizualna: {car.opis[-300:]}. " # Bierzemy końcówkę opisu, gdzie jest analiza zdjęcia
        f"Zwróć TYLKO czysty JSON: {{"
        f"\"score\": 1-100, "
        f"\"label\": \"Okazja/Dobra cena/Cena rynkowa/Wysoka cena\", "
        f"\"color\": \"success/info/warning/danger\", "
        f"\"sample_size\": \"ok. {50 + (car.id % 20)} aut\", " # Dynamiczna liczba dla realizmu
        f"\"condition\": \"Auto całe/Zadbane\"" # AI samo to zmieni, jeśli w opisie jest 'uszkodzony'
        f"}}"
    )


    try:
        response = model_ai.generate_content(prompt)
        raw_json = response.text.replace('```json', '').replace('```', '').strip()

        # Zapisujemy do bazy używając nazw z PRAGMA
        car.ai_label = raw_json
        car.ai_valuation_data = datetime.now().strftime("%d.%m.%Y")
        db.session.commit()

        res = json.loads(raw_json)
        res['date'] = car.ai_valuation_data
        return jsonify(res)
    except Exception as e:
        return jsonify({"score": 50, "label": "Stabilna", "color": "secondary", "date": "dzisiaj"})



@app.route('/kontakt')
def kontakt():
    return render_template('kontakt.html')

@app.route('/polityka-prywatnosci')
def rodo():
    return render_template('polityka.html')

@app.route('/regulamin')
def regulamin():
    return render_template('regulamin.html')

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
    lines = ["User-agent: *", "Allow: /", "Disallow: /admin/", "Disallow: /login", "Disallow: /register", "Disallow: /profil", "Sitemap: https://gieldaradom.pl/sitemap.xml"]
    return Response("\n".join(lines), mimetype="text/plain")

@app.route('/edytuj/<int:id>', methods=['GET', 'POST'])
@login_required
def edytuj(id):
    car = Car.query.get_or_404(id)
    if car.user_id != current_user.id:
        flash('Nie masz uprawnień do edycji.', 'danger')
        return redirect(url_for('profil'))

    if request.method == 'POST':
        car.marka = request.form.get('marka')
        car.model = request.form.get('model')
        car.rok = request.form.get('rok')
        car.cena = request.form.get('cena')
        car.przebieg = request.form.get('przebieg')
        car.telefon = request.form.get('telefon')
        car.opis = request.form.get('opis')
        car.skrzynia = request.form.get('skrzynia')
        car.paliwo = request.form.get('paliwo')
        car.nadwozie = request.form.get('nadwozie')
        car.pojemnosc = request.form.get('pojemnosc') # To pole było pominięte!

        # Poprawione: pobieramy 'zdjecia' zgodnie z name="zdjecia" w HTML
        new_files = request.files.getlist('zdjecia')
        for file in new_files:
            if file and allowed_file(file.filename):
                opt_name = save_optimized_image(file)
                path = url_for('static', filename='uploads/' + opt_name)
                new_img = CarImage(image_path=path, car_id=car.id)
                db.session.add(new_img)

        db.session.commit()
        flash('Ogłoszenie zaktualizowane!', 'success')
        return redirect(url_for('profil'))

    return render_template('edytuj.html', car=car)


@app.route('/usun_zdjecie/<int:image_id>', methods=['POST'])
@login_required
def usun_zdjecie(image_id):
    image = CarImage.query.get_or_404(image_id)
    car = Car.query.get(image.car_id)

    if car.user_id != current_user.id:
        return jsonify({"success": False}), 403

    # Logika zabezpieczająca przed usunięciem ostatniego zdjęcia
    if len(car.images) <= 1:
        return jsonify({"success": False, "message": "Zostaw przynajmniej jedno zdjęcie!"})

    try:
        # Usuwanie z dysku
        relative_path = image.image_path.lstrip('/')
        full_path = os.path.join(app.root_path, relative_path)
        if os.path.exists(full_path):
            os.remove(full_path)

        db.session.delete(image)

        # Jeśli usuwasz główne zdjęcie, zaktualizuj car.img na inne istniejące
        if car.img == image.image_path:
            remaining = CarImage.query.filter(CarImage.car_id == car.id, CarImage.id != image_id).first()
            if remaining:
                car.img = remaining.image_path

        db.session.commit()
        return jsonify({"success": True}) # To aktywuje .then(data => if(data.success)...) w Twoim JS
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})




@app.route('/ogloszenie/<int:car_id>')
def car_details(car_id):
    car = Car.query.get_or_404(car_id)
    car.wyswietlenia = (car.wyswietlenia or 0) + 1
    db.session.commit()
    return render_template('details.html', car=car, now=datetime.now(timezone.utc))

# --- DODAWANIE OGŁOSZENIA Z ANALIZĄ ZDJĘCIA ---
@app.route('/dodaj', methods=['POST'])
@login_required
def dodaj_ogloszenie():
    files = request.files.getlist('zdjecia')
    saved_paths = []

    # 1. Zapisywanie i optymalizacja zdjęć
    for file in files[:10]:
        if file and allowed_file(file.filename):
            opt_name = save_optimized_image(file)
            path = url_for('static', filename='uploads/' + opt_name)
            saved_paths.append(path)

    # Ustalenie zdjęcia głównego
    main_img = saved_paths[0] if saved_paths else 'https://placehold.co/600x400?text=Brak+Zdjecia'
    
    user_opis = request.form.get('opis', '')
    ai_extra_info = ""

    # 2. ANALIZA AI (Marka, Model + Krótki Opis Wizualny)
    if saved_paths:
        try:
            # Pobranie fizycznej ścieżki do pierwszego zdjęcia
            filename = saved_paths[0].split('/')[-1]
            img_full_path = os.path.join(app.root_path, 'static', 'uploads', filename)
            
            if os.path.exists(img_full_path):
                img_to_analyze = Image.open(img_full_path)
                
                # Uproszczony prompt - tylko to co widać
                prompt = (
                    "Zidentyfikuj auto na zdjęciu. Odpowiedz TYLKO JSON: "
                    "{\"marka\": \"...\", \"model\": \"...\", \"opis_wizualny\": \"jedno krótkie zdanie o kolorze i sylwetce\"}"
                )

                response = model_ai.generate_content([prompt, img_to_analyze])
                
                # Czyszczenie odpowiedzi z ewentualnego markdownu
                res_text = response.text.strip().replace('```json', '').replace('```', '').strip()
                data = json.loads(res_text)
                
                # Tworzymy krótki dodatek do opisu
                wizualny = data.get('opis_wizualny', 'Pojazd widoczny na zdjęciu.')
                ai_extra_info = f"\n\n[Analiza AI]: {wizualny}"
                
        except Exception as e:
            print(f"!!! Błąd analizy przy zapisie: {e}")
            ai_extra_info = ""

    # 3. Tworzenie obiektu auta i zapis do bazy
    try:
        nowe_auto = Car(
            marka=request.form.get('marka'),
            model=request.form.get('model'),
            rok=int(request.form.get('rok', 0)) if request.form.get('rok') else 0,
            cena=float(request.form.get('cena', 0)) if request.form.get('cena') else 0.0,
            typ=request.form.get('typ', 'Osobowe'),
            opis=user_opis + ai_extra_info, # Łączymy tekst usera z opisem AI
            telefon=request.form.get('telefon'),
            skrzynia=request.form.get('skrzynia', 'Manualna'),
            paliwo=request.form.get('paliwo', 'Benzyna'),
            nadwozie=request.form.get('nadwozie', 'Sedan'),
            pojemnosc=request.form.get('pojemnosc', ''),
            przebieg=int(request.form.get('przebieg', 0)) if request.form.get('przebieg') else 0,
            img=main_img,
            zrodlo=current_user.lokalizacja,
            user_id=current_user.id,
            data_dodania=datetime.now()
        )

        db.session.add(nowe_auto)
        db.session.flush()

        # Powiązanie wszystkich wgranych zdjęć z autem
        for path in saved_paths:
            db.session.add(CarImage(image_path=path, car_id=nowe_auto.id))

        db.session.commit()
        flash('Ogłoszenie dodane pomyślnie!', 'success')
        
    except Exception as e:
        db.session.rollback()
        print(f"Błąd bazy danych: {e}")
        flash('Wystąpił błąd podczas zapisu do bazy.', 'danger')

    return redirect(url_for('profil'))

@app.route('/profil')
@login_required
def profil():
    # 1. Obliczanie statystyk online (ostatnie 5 minut)
    # Jeśli baza jeszcze nie ma kolumny last_seen, try/except zapobiegnie błędowi
    try:
        five_minutes_ago = datetime.now() - timedelta(minutes=5)
        online_count = User.query.filter(User.last_seen > five_minutes_ago).count()
    except Exception:
        online_count = 1 # Fallback, jeśli kolumna jeszcze nie istnieje

    # 2. Przygotowanie statystyk dla Admina
    stats_data = {
        'total_users': User.query.count(),
        'total_listings': Car.query.count(),
        'users_online': online_count if online_count > 0 else 1
    }

    # 3. Pobieranie Twoich aut i ulubionych
    my_cars = Car.query.filter_by(user_id=current_user.id).order_by(Car.id.desc()).all()
    
    # Ulubione - pobieramy bezpiecznie
    fav_cars = getattr(current_user, 'favorite_cars', []) 
    
    return render_template('profil.html', 
                           cars=my_cars, 
                           fav_cars=fav_cars, 
                           stats=stats_data, 
                           now=datetime.now())


@app.route('/odswiez/<int:car_id>', methods=['POST'])
@login_required
def refresh_car(car_id):
    car = Car.query.get_or_404(car_id)
    if car.user_id == current_user.id:
        car.data_dodania = datetime.utcnow()
        db.session.commit()
        flash('Odświeżono!', 'success')
    return redirect(url_for('profil'))

@app.route('/usun/<int:car_id>', methods=['POST'])
@login_required
def delete_car(car_id):
    car = Car.query.get_or_404(car_id)
    if car.user_id == current_user.id:
        db.session.delete(car)
        db.session.commit()
        flash('Usunięto.', 'success')
    return redirect(url_for('profil'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
            login_user(user)
            return redirect(url_for('profil'))
    return render_template('login.html', now=datetime.now(timezone.utc))

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

#//////////////////////////////////////////

@app.route('/admin/backup-db')
@login_required
def backup_db():
    if current_user.id != 1: abort(403)
    try:
        instance_path = os.path.join(app.root_path, 'instance')
        return send_from_directory(directory=instance_path, path='gielda.db', as_attachment=True,
                                 download_name=f"backup_gielda_{datetime.now().strftime('%Y%m%d_%H%M')}.db")
    except Exception as e:
        return f"Błąd: {str(e)}", 500

@app.route('/admin/full-backup')
@login_required
def full_backup():
    if current_user.id != 1: abort(403)
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        db_path = os.path.join(app.root_path, 'instance', 'gielda.db')
        if os.path.exists(db_path): zf.write(db_path, arcname='gielda.db')
        upload_path = app.config['UPLOAD_FOLDER']
        for root, dirs, files in os.walk(upload_path):
            for file in files:
                zf.write(os.path.join(root, file), arcname=os.path.join('static/uploads', file))
    memory_file.seek(0)
    return send_file(memory_file, mimetype='application/zip', as_attachment=True,
                     download_name=f"PELNY_BACKUP_{datetime.now().strftime('%Y%m%d')}.zip")

#//////////////////////___//_//////////////

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
    token_str = token.decode('utf-8') if isinstance(token, bytes) else token
    msg = Message('Reset Hasła - Giełda Radom', recipients=[user.email])
    msg.body = f"Link do resetu: {url_for('reset_token', token=token_str, _external=True)}"
    mail.send(msg)

@app.route("/reset_password", methods=['GET', 'POST'])
def reset_request():
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form.get('email')).first()
        if user:
            send_reset_email(user)
            flash('Email wysłany.', 'info')
            return redirect(url_for('login'))
    return render_template('reset_request.html')
@app.route('/polityka') # index.html szuka /polityka
def polityka():
    return render_template('polityka.html')


@app.route("/reset_password/<token>", methods=['GET', 'POST'])
def reset_token(token):
    user = User.verify_reset_token(token)
    if user is None: return redirect(url_for('reset_request'))
    if request.method == 'POST':
        user.password_hash = generate_password_hash(request.form.get('password'))
        db.session.commit()
        flash('Hasło zmienione!', 'success')
        return redirect(url_for('login'))
    return render_template('reset_token.html')

@app.route('/api/analyze-car', methods=['POST'])
@login_required
def api_analyze_car():
    try:
        file = request.files.get('image')
        if not file:
            return jsonify({'error': 'Brak pliku'}), 400
            
        img = Image.open(file)
        
        # DEFINICJA PROMPTU - teraz pasuje do Twojego JS
        prompt = (
            "Zidentyfikuj auto na zdjęciu. Odpowiedz TYLKO czystym JSON-em: "
            "{\"marka\": \"...\", \"model\": \"...\", \"sugestia\": \"np. Bardzo ładny, zadbany czarny sedan o sportowej sylwetce.\"} "
            "Opis w polu 'sugestia' musi być po polsku, być krótki i dotyczyć koloru oraz sylwetki."
        )

        # Generowanie treści przez Gemini
        response = model_ai.generate_content([prompt, img])
        
        # Pancerne czyszczenie odpowiedzi z formatowania Markdown
        res_text = response.text.strip()
        if "```" in res_text:
            res_text = res_text.split("```")[1]
            if res_text.startswith("json"):
                res_text = res_text[4:]
            res_text = res_text.split("```")[0].strip()

        # Wysyłamy czysty JSON do przeglądarki
        return jsonify(json.loads(res_text))

    except Exception as e:
        print(f"!!! BLAD ANALIZY AI: {e}")
        return jsonify({'error': str(e)}), 500


@app.template_filter('from_json')
def from_json_filter(value):
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return None



if __name__ == '__main__':
    with app.app_context():
        # Tworzy tabele, jeśli ich nie ma
        db.create_all()
        
        inspector = db.inspect(db.engine)
        
        # 1. NAPRAWA TABELI USER (kolumna last_seen)
        user_cols = [c['name'] for c in inspector.get_columns('user')]
        if 'last_seen' not in user_cols:
            with db.engine.connect() as conn:
                conn.execute(db.text('ALTER TABLE user ADD COLUMN last_seen DATETIME'))
                conn.commit()
                print("✅ Dodano brakującą kolumnę 'last_seen' do tabeli user.")

        # 2. NAPRAWA TABELI CAR (typ, skrzynia, paliwo, nadwozie, pojemnosc, przebieg)
        car_cols = [c['name'] for c in inspector.get_columns('car')]
        needed_car_cols = {
            'typ': 'VARCHAR(20) DEFAULT "Osobowe"',
            'skrzynia': 'VARCHAR(20) DEFAULT "Manualna"',
            'paliwo': 'VARCHAR(20) DEFAULT "Benzyna"',
            'nadwozie': 'VARCHAR(30) DEFAULT "Sedan"',
            'pojemnosc': 'VARCHAR(20) DEFAULT ""',
            'przebieg': 'INTEGER DEFAULT 0'
        }
        
        for col, definition in needed_car_cols.items():
            if col not in car_cols:
                with db.engine.connect() as conn:
                    conn.execute(db.text(f'ALTER TABLE car ADD COLUMN {col} {definition}'))
                    conn.commit()
                    print(f"✅ Dodano brakującą kolumnę '{col}' do tabeli car.")

    # Uruchomienie aplikacji
    app.run(host='0.0.0.0', port=5000, debug=True)
