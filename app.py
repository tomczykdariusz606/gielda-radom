import os
import uuid
import zipfile
import io
import sekrety  # Upewnij się, że masz ten plik z kluczami GEMINI_KEY i MAIL_PWD
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
app.secret_key = 'sekretny_klucz_gieldy_radom_2026'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///gielda.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

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

class CarImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    image_path = db.Column(db.String(200), nullable=False)
    car_id = db.Column(db.Integer, db.ForeignKey('car.id'), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- POMOCNIKI ---
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

# --- TRASY GŁÓWNE (Z CZYŚCICIELEM I SEO) ---
@app.route('/')
def index():
    # Czyściciel: Pokazuj tylko ogłoszenia z ostatnich 30 dni
    limit_daty = datetime.utcnow() - timedelta(days=30)
    query_text = request.args.get('q', '').strip()
    
    base_query = Car.query.filter(Car.data_dodania >= limit_daty)

    if query_text:
        all_cars = base_query.all()
        choices = {f"{c.marka} {c.model}": c.id for c in all_cars}
        matches = process.extract(query_text, choices.keys(), limit=50)
        matched_ids = [choices[m[0]] for m in matches if m[1] > 55]
        base_query = base_query.filter(Car.id.in_(matched_ids))

    cars = base_query.order_by(Car.id.desc()).all()
    return render_template('index.html', cars=cars, now=datetime.utcnow())

@app.route('/ogloszenie/<int:car_id>')
def car_details(car_id):
    car = Car.query.get_or_404(car_id)
    car.wyswietlenia += 1
    db.session.commit()
    return render_template('details.html', car=car, now=datetime.utcnow())

# --- DODAWANIE I EDYCJA (Z PRZEBIEGIEM I AI) ---
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
    
    # Analiza wizualna AI (opcjonalnie)
    ai_comment = ""
    if saved_paths:
        try:
            img_path = os.path.join(app.root_path, saved_paths[0].lstrip('/'))
            img_to_analyze = Image.open(img_path)
            vision_res = model_ai.generate_content(["Opisz krótko ten samochód po polsku (stan, kolor).", img_to_analyze])
            ai_comment = f"\n\n[Analiza AI]: {vision_res.text}"
        except: ai_comment = ""

    nowe_auto = Car(
        marka=request.form['marka'], model=request.form['model'],
        rok=int(request.form['rok']), cena=float(request.form['cena']),
        przebieg=int(request.form.get('przebieg', 0)),
        pojemnosc=request.form.get('pojemnosc'),
        skrzynia=request.form.get('skrzynia'),
        paliwo=request.form.get('paliwo'),
        nadwozie=request.form.get('nadwozie'),
        opis=request.form['opis'] + ai_comment,
        telefon=request.form['telefon'],
        img=main_img, user_id=current_user.id
    )
    db.session.add(nowe_auto)
    db.session.flush()
    for path in saved_paths:
        db.session.add(CarImage(image_path=path, car_id=nowe_auto.id))
    db.session.commit()
    flash('Ogłoszenie dodane!', 'success')
    return redirect(url_for('profil'))

@app.route('/edytuj/<int:car_id>', methods=['GET', 'POST'])
@login_required
def edit_car(car_id):
    car = Car.query.get_or_404(car_id)
    if car.user_id != current_user.id: abort(403)
    
    if request.method == 'POST':
        car.marka = request.form['marka']
        car.model = request.form['model']
        car.rok = int(request.form['rok'])
        car.cena = float(request.form['cena'])
        car.przebieg = int(request.form.get('przebieg', 0))
        car.pojemnosc = request.form.get('pojemnosc')
        car.telefon = request.form['telefon']
        car.opis = request.form['opis']
        
        # Nowe zdjęcia
        files = request.files.getlist('zdjecia')
        for file in files:
            if file and allowed_file(file.filename):
                opt_name = save_optimized_image(file)
                path = url_for('static', filename='uploads/' + opt_name)
                db.session.add(CarImage(image_path=path, car_id=car.id))
        
        db.session.commit()
        flash('Zaktualizowano!', 'success')
        return redirect(url_for('profil'))
    
    return render_template('edytuj.html', car=car, now=datetime.utcnow())

# --- ZDJĘCIA (USUWANIE AJAX) ---
@app.route('/usun_zdjecie/<int:image_id>', methods=['POST'])
@login_required
def usun_zdjecie(image_id):
    img = CarImage.query.get_or_404(image_id)
    if img.car.user_id != current_user.id: return jsonify({"success": False}), 403
    
    # Usuń plik
    try:
        fpath = os.path.join(app.root_path, img.image_path.lstrip('/'))
        if os.path.exists(fpath): os.remove(fpath)
    except: pass

    db.session.delete(img)
    db.session.commit()
    return jsonify({"success": True})

# --- ULUBIONE ---
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

# --- SEO & BACKUP ---
@app.route('/sitemap.xml')
def sitemap():
    base_url = "https://gieldaradom.pl"
    cars = Car.query.all()
    xml = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    xml += f'<url><loc>{base_url}/</loc><priority>1.0</priority></url>'
    for car in cars:
        xml += f'<url><loc>{base_url}/ogloszenie/{car.id}</loc><priority>0.8</priority></url>'
    xml += '</urlset>'
    return Response(xml, mimetype='application/xml')

@app.route('/robots.txt')
def robots():
    return Response("User-agent: *\nDisallow: /login\nDisallow: /profil\nSitemap: https://gieldaradom.pl/sitemap.xml", mimetype="text/plain")

@app.route('/admin/full-backup')
@login_required
def full_backup():
    if current_user.id != 1: abort(403)
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        db_path = os.path.join(app.root_path, 'instance', 'gielda.db')
        if os.path.exists(db_path): zf.write(db_path, arcname='gielda.db')
        # Dodaj zdjęcia do backupu
        for root, _, files in os.walk(UPLOAD_FOLDER):
            for f in files: zf.write(os.path.join(root, f), arcname=os.path.join('uploads', f))
    memory_file.seek(0)
    return send_file(memory_file, mimetype='application/zip', as_attachment=True, download_name="backup_full.zip")

# --- RESZTA (PROFIL, LOGIN, REJESTRACJA) ---
@app.route('/profil')
@login_required
def profil():
    my_cars = Car.query.filter_by(user_id=current_user.id).order_by(Car.id.desc()).all()
    return render_template('profil.html', cars=my_cars, fav_cars=current_user.favorite_cars, now=datetime.utcnow())

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
        pw_hash = generate_password_hash(request.form['password'])
        new_user = User(username=request.form['username'], email=request.form['email'], password_hash=pw_hash)
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('register.html', now=datetime.utcnow())

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)
