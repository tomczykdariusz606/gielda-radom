import os
import uuid
import zipfile
import io
import sekrety
import json
import google.generativeai as genai
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, abort, jsonify, send_file, Response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from PIL import Image
from itsdangerous import URLSafeTimedSerializer as Serializer

app = Flask(__name__)

# --- KONFIGURACJA ---
app.config['MAIL_SERVER'] = 'poczta.o2.pl'
app.config['MAIL_PORT'] = 465
app.config['MAIL_USE_SSL'] = True
app.config['MAIL_USERNAME'] = 'dariusztom@go2.pl'
app.config['MAIL_PASSWORD'] = sekrety.MAIL_PWD
app.config['MAIL_DEFAULT_SENDER'] = 'dariusztom@go2.pl'
mail = Mail(app)

genai.configure(api_key=sekrety.GEMINI_KEY)
model_ai = genai.GenerativeModel('gemini-1.5-flash')

app.secret_key = 'sekretny_klucz_gieldy_radom_2024'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///gielda.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

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
    lokalizacja = db.Column(db.String(100), default='Radom')
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
    data_dodania = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    # Pola dodatkowe (wymagają aktualizacji bazy)
    przebieg = db.Column(db.Integer, default=0)
    skrzynia = db.Column(db.String(20))
    paliwo = db.Column(db.String(20))
    nadwozie = db.Column(db.String(30))
    pojemnosc = db.Column(db.String(20))
    wyswietlenia = db.Column(db.Integer, default=0)
    zrodlo = db.Column(db.String(50), default='Lokalne')
    images = db.relationship('CarImage', backref='car', lazy=True, cascade="all, delete-orphan")

class CarImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    image_path = db.Column(db.String(200), nullable=False)
    car_id = db.Column(db.Integer, db.ForeignKey('car.id'), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- ANALIZA RYNKOWA ---
def get_market_valuation(car):
    base = {"Audi": 1.2, "BMW": 1.2, "Mercedes": 1.3, "Toyota": 1.1}
    age = max(1, 2026 - (car.rok or 2015))
    avg = 100000 * (0.88 ** age) * base.get(car.marka, 1.0)
    diff = ((car.cena - avg) / avg) * 100
    return {"status": "OKAZJA" if diff < -10 else "RYNKOWA", "color": "#28a745" if diff < -10 else "#1a73e8", "avg": int(avg)}

@app.context_processor
def utility_processor():
    return dict(get_market_valuation=get_market_valuation)

# --- TRASY API (AI) ---
@app.route('/api/analyze-car', methods=['POST'])
@login_required
def analyze_car():
    file = request.files.get('image')
    if file:
        img = Image.open(file)
        res = model_ai.generate_content(['Zwróć JSON: {"marka": "X", "model": "Y", "rok": "Z"}', img])
        return jsonify(json.loads(res.text.replace('```json', '').replace('```', '').strip()))
    return jsonify({"error": "Brak pliku"}), 400

# --- TRASY GŁÓWNE ---
@app.route('/')
def index():
    cars = Car.query.order_by(Car.id.desc()).all()
    return render_template('index.html', cars=cars, now=datetime.utcnow())

@app.route('/profil')
@login_required
def profil():
    cars = Car.query.filter_by(user_id=current_user.id).all()
    return render_template('profil.html', cars=cars, fav_cars=current_user.favorite_cars, now=datetime.utcnow())

@app.route('/dodaj', methods=['POST'])
@login_required
def dodaj_ogloszenie():
    files = request.files.getlist('zdjecia')
    paths = []
    for f in files[:10]:
        if f:
            name = f"{uuid.uuid4().hex}.webp"
            f.save(os.path.join(app.config['UPLOAD_FOLDER'], name))
            paths.append(url_for('static', filename='uploads/' + name))
    
    ai_desc = ""
    if paths:
        try:
            p = os.path.join(app.root_path, paths[0].lstrip('/'))
            res = model_ai.generate_content(["Opisz auto po polsku.", Image.open(p)])
            ai_desc = f"\n\n[AI]: {res.text}"
        except: pass

    nowe = Car(
        marka=request.form.get('marka'), model=request.form.get('model'),
        rok=int(request.form.get('rok', 0)), cena=float(request.form.get('cena', 0)),
        przebieg=int(request.form.get('przebieg', 0)), opis=request.form.get('opis', '') + ai_desc,
        telefon=request.form.get('telefon'), skrzynia=request.form.get('skrzynia'),
        paliwo=request.form.get('paliwo'), nadwozie=request.form.get('nadwozie'),
        pojemnosc=request.form.get('pojemnosc'), img=paths[0] if paths else "",
        user_id=current_user.id
    )
    db.session.add(nowe)
    db.session.flush()
    for p in paths: db.session.add(CarImage(image_path=p, car_id=nowe.id))
    db.session.commit()
    return redirect(url_for('profil'))

@app.route('/toggle_favorite/<int:car_id>')
@login_required
def toggle_favorite(car_id):
    car = Car.query.get_or_404(car_id)
    if car in current_user.favorite_cars: current_user.favorite_cars.remove(car)
    else: current_user.favorite_cars.append(car)
    db.session.commit()
    return redirect(request.referrer or url_for('index'))

@app.route('/ogloszenie/<int:car_id>')
def car_details(car_id):
    c = Car.query.get_or_404(car_id)
    c.wyswietlenia += 1
    db.session.commit()
    return render_template('details.html', car=c, now=datetime.utcnow())

# --- SEO & BACKUP ---
@app.route('/sitemap.xml')
def sitemap():
    xml = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    xml += f'<url><loc>{request.url_root}</loc></url>'
    for c in Car.query.all(): xml += f'<url><loc>{request.url_root}ogloszenie/{c.id}</loc></url>'
    return Response(xml + '</urlset>', mimetype='application/xml')

@app.route('/robots.txt')
def robots():
    return Response("User-agent: *\nAllow: /", mimetype="text/plain")

@app.route('/admin/full-backup')
@login_required
def full_backup():
    if current_user.id != 1: abort(403)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.write('gielda.db')
    buf.seek(0)
    return send_file(buf, mimetype='application/zip', as_attachment=True, download_name="backup.zip")

# --- AUTH ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = User.query.filter_by(username=request.form['username']).first()
        if u and check_password_hash(u.password_hash, request.form['password']):
            login_user(u); return redirect(url_for('profil'))
    return render_template('login.html', now=datetime.utcnow())

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        u = User(username=request.form['username'], email=request.form['email'], 
                 password_hash=generate_password_hash(request.form['password']))
        db.session.add(u); db.session.commit()
        return redirect(url_for('login'))
    return render_template('register.html', now=datetime.utcnow())

@app.route('/logout')
def logout(): logout_user(); return redirect(url_for('index'))

if __name__ == '__main__':
    with app.app_context(): db.create_all()
    app.run(host='0.0.0.0', port=5000)
