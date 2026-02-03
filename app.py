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
from thefuzz import process 

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
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- MODELE BAZY DANYCH ---
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
        except: return None
        return User.query.get(user_id)

class Car(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    typ = db.Column(db.String(20), default='Osobowe')
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

# --- FUNKCJE POMOCNICZE ---

def save_optimized_image(file):
    filename = f"{uuid.uuid4().hex}.webp"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    img = Image.open(file)
    if img.mode in ("RGBA", "P"): img = img.convert("RGB")
    img.thumbnail((1200, 1200))
    img.save(filepath, "WEBP", quality=75)
    return filename

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- TRASY ADMINA (DOPASOWANE DO PROFIL.HTML) ---

@app.route('/admin/backup-db')
@login_required
def backup_db():
    if current_user.id != 1: abort(403)
    # Sprawdzamy folder instance i główny
    db_path = os.path.join(app.root_path, 'instance', 'gielda.db')
    if not os.path.exists(db_path): db_path = os.path.join(app.root_path, 'gielda.db')
    
    if os.path.exists(db_path):
        return send_file(db_path, as_attachment=True, download_name=f"BAZA_RADOM_{datetime.now().strftime('%Y%m%d')}.db")
    return "Baza danych nie została znaleziona.", 404

@app.route('/admin/full-backup')
@login_required
def full_backup():
    if current_user.id != 1: abort(403)
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        db_path = os.path.join(app.root_path, 'instance', 'gielda.db')
        if not os.path.exists(db_path): db_path = os.path.join(app.root_path, 'gielda.db')
        if os.path.exists(db_path): zf.write(db_path, arcname='gielda.db')
        
        for root, dirs, files in os.walk(app.config['UPLOAD_FOLDER']):
            for file in files:
                zf.write(os.path.join(root, file), arcname=os.path.join('static/uploads', file))
    memory_file.seek(0)
    return send_file(memory_file, mimetype='application/zip', as_attachment=True, download_name="PELNY_BACKUP_SYSTEMU.zip")

@app.route('/admin/czysciciel')
@login_required
def czysciciel():
    if current_user.id != 1: abort(403)
    db_imgs = [c.img.split('/')[-1] for c in Car.query.all() if c.img]
    extra_imgs = [i.image_path.split('/')[-1] for i in CarImage.query.all()]
    all_valid = set(db_imgs + extra_imgs)
    count = 0
    for f in os.listdir(app.config['UPLOAD_FOLDER']):
        if f not in all_valid:
            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], f))
            count += 1
    flash(f'Panel Admina: Usunięto {count} osieroconych zdjęć.', 'success')
    return redirect(url_for('profil'))

# --- TRASY GŁÓWNE ---

@app.route('/')
def index():
    q = request.args.get('q', '').strip().lower()
    typ = request.args.get('typ', '')
    query = Car.query
    if q: query = query.filter(or_(Car.marka.ilike(f'%{q}%'), Car.model.ilike(f'%{q}%'), Car.opis.ilike(f'%{q}%')))
    if typ: query = query.filter(Car.typ == typ)
    cars = query.order_by(Car.id.desc()).all()
    return render_template('index.html', cars=cars, now=datetime.utcnow())

@app.route('/profil')
@login_required
def profil():
    my_cars = Car.query.filter_by(user_id=current_user.id).order_by(Car.id.desc()).all()
    
    # Dane statystyczne dla Centrum Dowodzenia Admina
    stats_data = {
        "total_users": User.query.count(),
        "total_listings": Car.query.count(),
        "users_online": 1, # Statyczna wartość dla efektu wizualnego
        "my_count": len(my_cars)
    }
    
    return render_template('profil.html', 
                           cars=my_cars, 
                           fav_cars=current_user.favorite_cars, 
                           stats=stats_data,        # To zasila sekcję "stats"
                           statystyki=stats_data,   # To zasila sekcję "statystyki"
                           now=datetime.now())

@app.route('/dodaj', methods=['POST'])
@login_required
def dodaj_ogloszenie():
    files = request.files.getlist('zdjecia')
    saved = []
    for f in files[:10]:
        if f and allowed_file(f.filename):
            saved.append(url_for('static', filename='uploads/' + save_optimized_image(f)))
    
    ai_comment = ""
    if saved:
        try:
            full_p = os.path.join(app.root_path, saved[0].lstrip('/'))
            res = model_ai.generate_content(["Zidentyfikuj to auto i opisz jego stan wizualny w jednym krótkim zdaniu.", Image.open(full_p)])
            ai_comment = f"\n\n[Analiza AI]: {res.text}"
        except: pass

    nowe = Car(
        typ=request.form.get('typ', 'Osobowe'),
        marka=request.form['marka'], model=request.form['model'],
        rok=int(request.form['rok']), cena=float(request.form['cena']),
        opis=request.form['opis'] + ai_comment, telefon=request.form['telefon'],
        przebieg=int(request.form.get('przebieg', 0)),
        skrzynia=request.form.get('skrzynia'),
        paliwo=request.form.get('paliwo'),
        nadwozie=request.form.get('nadwozie'),
        pojemnosc=request.form.get('pojemnosc'),
        img=saved[0] if saved else '', 
        user_id=current_user.id
    )
    db.session.add(nowe)
    db.session.flush()
    for s in saved: db.session.add(CarImage(image_path=s, car_id=nowe.id))
    db.session.commit()
    flash('Ogłoszenie dodane pomyślnie!', 'success')
    return redirect(url_for('profil'))

# --- POZOSTAŁE TRASY (LOGOWANIE, SEO, ITP.) ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
            login_user(user)
            return redirect(url_for('profil'))
        flash('Błędne dane.', 'danger')
    return render_template('login.html', now=datetime.now())

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/robots.txt')
def robots():
    return Response("User-agent: *\nAllow: /\nSitemap: https://gieldaradom.pl/sitemap.xml", mimetype="text/plain")

@app.route('/polityka')
def polityka(): return render_template('polityka.html')

@app.route('/regulamin')
def regulamin(): return render_template('regulamin.html')

if __name__ == '__main__':
    with app.app_context(): db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)
