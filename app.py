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

# --- PEŁNA KONFIGURACJA ---
app.config.update(
    MAIL_SERVER='poczta.o2.pl',
    MAIL_PORT=465,
    MAIL_USE_SSL=True,
    MAIL_USERNAME='dariusztom@go2.pl',
    MAIL_PASSWORD=sekrety.MAIL_PWD,
    MAIL_DEFAULT_SENDER='dariusztom@go2.pl',
    SQLALCHEMY_DATABASE_URI='sqlite:///gielda.db',
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    UPLOAD_FOLDER='static/uploads',
    SECRET_KEY='sekretny_klucz_gieldy_radom_2024'
)

mail = Mail(app)
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Konfiguracja AI
genai.configure(api_key=sekrety.GEMINI_KEY)
model_ai = genai.GenerativeModel('gemini-1.5-flash')

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
        s = Serializer(app.config['SECRET_KEY'])
        return s.dumps({'user_id': self.id})

    @staticmethod
    def verify_reset_token(token):
        s = Serializer(app.config['SECRET_KEY'])
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
    data_dodania = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    skrzynia = db.Column(db.String(20))
    paliwo = db.Column(db.String(20))
    nadwozie = db.Column(db.String(30))
    pojemnosc = db.Column(db.String(20))
    przebieg = db.Column(db.Integer, default=0)
    wyswietlenia = db.Column(db.Integer, default=0)
    images = db.relationship('CarImage', backref='car', lazy=True, cascade="all, delete-orphan")

class CarImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    image_path = db.Column(db.String(200), nullable=False)
    car_id = db.Column(db.Integer, db.ForeignKey('car.id'), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- POMOCNICZE I OPTYMALIZACJA ---
def save_optimized_image(file):
    filename = f"{uuid.uuid4().hex}.webp"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    img = Image.open(file)
    if img.mode in ("RGBA", "P"): img = img.convert("RGB")
    img.thumbnail((1200, 1200))
    img.save(filepath, "WEBP", quality=75)
    return filename

# --- SEO I ADMINISTRACJA ---
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
    return Response("User-agent: *\nAllow: /\nSitemap: https://gieldaradom.pl/sitemap.xml", mimetype="text/plain")

@app.route('/admin/backup')
@login_required
def backup_db():
    if current_user.id != 1: abort(403)
    db_path = os.path.join(app.root_path, 'instance', 'gielda.db')
    if not os.path.exists(db_path): db_path = os.path.join(app.root_path, 'gielda.db')
    return send_file(db_path, as_attachment=True)

@app.route('/admin/full-backup')
@login_required
def full_backup():
    if current_user.id != 1: abort(403)
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        db_path = os.path.join(app.root_path, 'instance', 'gielda.db')
        if os.path.exists(db_path): zf.write(db_path, arcname='gielda.db')
        for root, dirs, files in os.walk(app.config['UPLOAD_FOLDER']):
            for file in files:
                zf.write(os.path.join(root, file), arcname=os.path.join('static/uploads', file))
    memory_file.seek(0)
    return send_file(memory_file, mimetype='application/zip', as_attachment=True, download_name="FULL_BACKUP.zip")

@app.route('/admin/czysciciel')
@login_required
def czysciciel():
    if current_user.id != 1: abort(403)
    db_images = [c.img.split('/')[-1] for c in Car.query.all() if c.img]
    extra_images = [i.image_path.split('/')[-1] for i in CarImage.query.all()]
    all_valid = set(db_images + extra_images)
    removed = 0
    for f in os.listdir(app.config['UPLOAD_FOLDER']):
        if f not in all_valid:
            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], f))
            removed += 1
    flash(f'Usunięto {removed} plików.', 'success')
    return redirect(url_for('profil'))

# --- AI API ---
@app.route('/api/analyze-car', methods=['POST'])
@login_required
def analyze_car_api():
    if 'image' not in request.files: return jsonify({"error": "Brak zdjęcia"}), 400
    file = request.files['image']
    try:
        img = Image.open(file.stream)
        prompt = "Zidentyfikuj pojazd (marka, model, rok, typ: Osobowe/Bus/Rower). Zwróć tylko JSON."
        response = model_ai.generate_content([prompt, img])
        return jsonify(json.loads(response.text.replace('```json', '').replace('```', '').strip()))
    except Exception as e: return jsonify({"error": str(e)}), 500

# --- OBSŁUGA OGŁOSZEŃ (INDEX, DODAJ, EDYTUJ) ---
@app.route('/')
def index():
    q = request.args.get('q', '').lower()
    typ = request.args.get('typ', '')
    query = Car.query
    if q: query = query.filter(or_(Car.marka.ilike(f'%{q}%'), Car.model.ilike(f'%{q}%')))
    if typ: query = query.filter(Car.typ == typ)
    cars = query.order_by(Car.data_dodania.desc()).all()
    return render_template('index.html', cars=cars, now=datetime.utcnow())

@app.route('/ogloszenie/<int:car_id>')
def car_details(car_id):
    car = Car.query.get_or_404(car_id)
    car.wyswietlenia += 1
    db.session.commit()
    return render_template('details.html', car=car)

@app.route('/dodaj', methods=['POST'])
@login_required
def dodaj():
    files = request.files.getlist('zdjecia')
    saved = []
    for f in files[:10]:
        if f: saved.append(url_for('static', filename='uploads/' + save_optimized_image(f)))
    
    new_car = Car(
        typ=request.form.get('typ', 'Osobowe'),
        marka=request.form['marka'], model=request.form['model'],
        rok=int(request.form['rok']), cena=float(request.form['cena']),
        opis=request.form['opis'], telefon=request.form['telefon'],
        skrzynia=request.form.get('skrzynia'), paliwo=request.form.get('paliwo'),
        przebieg=int(request.form.get('przebieg', 0)),
        img=saved[0] if saved else '', user_id=current_user.id
    )
    db.session.add(new_car)
    db.session.flush()
    for s in saved: db.session.add(CarImage(image_path=s, car_id=new_car.id))
    db.session.commit()
    return redirect(url_for('profil'))

@app.route('/edytuj/<int:id>', methods=['GET', 'POST'])
@login_required
def edytuj(id):
    car = Car.query.get_or_404(id)
    if car.user_id != current_user.id and current_user.id != 1: abort(403)
    if request.method == 'POST':
        car.typ = request.form.get('typ')
        car.marka = request.form.get('marka')
        car.model = request.form.get('model')
        car.cena = request.form.get('cena')
        car.opis = request.form.get('opis')
        db.session.commit()
        return redirect(url_for('profil'))
    return render_template('edytuj.html', car=car)

@app.route('/usun/<int:id>', methods=['POST'])
@login_required
def usun(id):
    car = Car.query.get_or_404(id)
    if car.user_id == current_user.id or current_user.id == 1:
        db.session.delete(car)
        db.session.commit()
    return redirect(url_for('profil'))

# --- UŻYTKOWNIK I PROFIL ---
@app.route('/profil')
@login_required
def profil():
    cars = Car.query.filter_by(user_id=current_user.id).all()
    stats = {"total_users": User.query.count(), "total_listings": Car.query.count()}
    return render_template('profil.html', cars=cars, fav_cars=current_user.favorite_cars, stats=stats)

@app.route('/rejestracja', methods=['GET', 'POST'])
def rejestracja():
    if request.method == 'POST':
        hashed_pw = generate_password_hash(request.form['password'])
        new_user = User(username=request.form['username'], email=request.form['email'], password_hash=hashed_pw)
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('rejestracja.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = User.query.filter_by(username=request.form['username']).first()
        if u and check_password_hash(u.password_hash, request.form['password']):
            login_user(u)
            return redirect(url_for('profil'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))

if __name__ == '__main__':
    with app.app_context(): db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)
