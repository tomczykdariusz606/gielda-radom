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

# --- KONFIGURACJA POCZTY (O2) ---
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
    typ = db.Column(db.String(20), default='Osobowe') # Pole dodane migracją
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

# --- NARZĘDZIA, SEO I CZYŚCICIEL ---

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
    lines = ["User-agent: *", "Allow: /", "Disallow: /admin/", "Disallow: /login", "Sitemap: https://gieldaradom.pl/sitemap.xml"]
    return Response("\n".join(lines), mimetype="text/plain")

@app.route('/admin/czysciciel')
@login_required
def czysciciel():
    if current_user.id != 1: abort(403)
    db_images = [c.img.split('/')[-1] for c in Car.query.all() if c.img]
    additional_images = [i.image_path.split('/')[-1] for i in CarImage.query.all()]
    all_valid_files = set(db_images + additional_images)
    count = 0
    for filename in os.listdir(app.config['UPLOAD_FOLDER']):
        if filename not in all_valid_files:
            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            count += 1
    flash(f'Usunięto {count} niepotrzebnych plików.', 'success')
    return redirect(url_for('profil'))

# --- AI I ANALIZA ---

@app.route('/api/analyze-car', methods=['POST'])
@login_required
def analyze_car_api():
    if 'image' not in request.files: return jsonify({"error": "Brak zdjęcia"}), 400
    file = request.files['image']
    try:
        img = Image.open(file.stream)
        prompt = "Zidentyfikuj pojazd na zdjęciu. Zwróć dane TYLKO w formacie JSON: {\"marka\": \"...\", \"model\": \"...\", \"rok\": 2020, \"typ\": \"Osobowe/Bus/Rower\", \"paliwo\": \"...\"}"
        response = model_ai.generate_content([prompt, img])
        data = json.loads(response.text.replace('```json', '').replace('```', '').strip())
        return jsonify(data)
    except Exception as e: return jsonify({"error": str(e)}), 500

# --- TRASY GŁÓWNE ---

@app.route('/')
def index():
    q = request.args.get('q', '').strip()
    typ = request.args.get('typ', '')
    base_query = Car.query
    if q: base_query = base_query.filter(or_(Car.marka.ilike(f'%{q}%'), Car.model.ilike(f'%{q}%'), Car.opis.ilike(f'%{q}%')))
    if typ: base_query = base_query.filter(Car.typ == typ)
    cars = base_query.order_by(Car.data_dodania.desc()).all()
    return render_template('index.html', cars=cars, now=datetime.utcnow())

@app.route('/profil')
@login_required
def profil():
    my_cars = Car.query.filter_by(user_id=current_user.id).order_by(Car.id.desc()).all()
    fav_cars = current_user.favorite_cars
    stats = {
        "total_users": User.query.count(),
        "total_listings": Car.query.count(),
        "users_online": 1
    }
    return render_template('profil.html', cars=my_cars, fav_cars=fav_cars, stats=stats, now=datetime.utcnow())

# --- BACKUPY (PRZYWRÓCONE) ---

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
            for file in files: zf.write(os.path.join(root, file), arcname=os.path.join('static/uploads', file))
    memory_file.seek(0)
    return send_file(memory_file, mimetype='application/zip', as_attachment=True, download_name="GIELDA_FULL_BACKUP.zip")

# --- EDYCJA I USUWANIE ---

@app.route('/edytuj/<int:id>', methods=['GET', 'POST'])
@login_required
def edytuj(id):
    car = Car.query.get_or_404(id)
    if car.user_id != current_user.id and current_user.id != 1: abort(403)
    if request.method == 'POST':
        car.typ = request.form.get('typ', car.typ)
        car.marka = request.form.get('marka')
        car.model = request.form.get('model')
        car.rok = request.form.get('rok')
        car.cena = request.form.get('cena')
        car.opis = request.form.get('opis')
        car.telefon = request.form.get('telefon')
        db.session.commit()
        flash('Zaktualizowano ogłoszenie!', 'success')
        return redirect(url_for('profil'))
    return render_template('edytuj.html', car=car)

@app.route('/usun/<int:id>', methods=['POST'])
@login_required
def delete_car(id):
    car = Car.query.get_or_404(id)
    if car.user_id == current_user.id or current_user.id == 1:
        db.session.delete(car)
        db.session.commit()
        flash('Ogłoszenie usunięte.', 'success')
    return redirect(url_for('profil'))

# --- POZOSTAŁE (AUTH, DODAJ) ---
# ... (Tutaj dodaj resztę swoich tras logowania i rejestracji, aby zachować 600 linii) ...

if __name__ == '__main__':
    with app.app_context(): db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)
