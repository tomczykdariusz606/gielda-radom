import os, uuid, zipfile, io, json, sekrety
import google.generativeai as genai
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from PIL import Image

app = Flask(__name__)

# --- KONFIGURACJA (Nie zmieniać kolejności) ---
app.config['MAIL_SERVER'] = 'poczta.o2.pl'
app.config['MAIL_PORT'] = 465
app.config['MAIL_USE_SSL'] = True
app.config['MAIL_USERNAME'] = 'dariusztom@go2.pl'
app.config['MAIL_PASSWORD'] = sekrety.MAIL_PWD
mail = Mail(app)

genai.configure(api_key=sekrety.GEMINI_KEY)
model_ai = genai.GenerativeModel('gemini-1.5-flash')

app.secret_key = 'sekretny_klucz_gieldy_radom_2026'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///instance/gielda.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- MODELE BAZY DANYCH (Pełne) ---
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
    przebieg = db.Column(db.Integer, default=0)
    skrzynia = db.Column(db.String(20))
    paliwo = db.Column(db.String(20))
    nadwozie = db.Column(db.String(30))
    pojemnosc = db.Column(db.String(20))
    wyswietlenia = db.Column(db.Integer, default=0)
    ai_valuation_data = db.Column(db.Text)

@login_manager.user_loader
def load_user(user_id): return User.query.get(int(user_id))

# --- GŁÓWNE TRASY ---

@app.route('/')
def index():
    cars = Car.query.order_by(Car.id.desc()).all()
    return render_template('index.html', cars=cars, now=datetime.utcnow())

@app.route('/ogloszenie/<int:car_id>')
def details(car_id):
    car = Car.query.get_or_404(car_id)
    car.wyswietlenia += 1
    db.session.commit()
    return render_template('details.html', car=car, now=datetime.utcnow())

@app.route('/profil')
@login_required
def profil():
    my_cars = Car.query.filter_by(user_id=current_user.id).all()
    fav_cars = current_user.favorite_cars
    return render_template('profil.html', cars=my_cars, fav_cars=fav_cars, now=datetime.utcnow())

@app.route('/ulubione/toggle/<int:car_id>')
@login_required
def toggle_favorite(car_id):
    car = Car.query.get_or_404(car_id)
    if car in current_user.favorite_cars:
        current_user.favorite_cars.remove(car)
    else:
        current_user.favorite_cars.append(car)
    db.session.commit()
    return redirect(request.referrer or url_for('index'))

@app.route('/dodaj', methods=['POST'])
@login_required
def dodaj():
    files = request.files.getlist('zdjecia')
    if not files or not files[0]:
        flash("Musisz dodać zdjęcie!", "danger")
        return redirect(url_for('profil'))
    
    f = files[0]
    fname = f"{uuid.uuid4().hex}.webp"
    f.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
    
    nowe = Car(
        marka=request.form['marka'], model=request.form['model'], rok=int(request.form['rok']),
        cena=float(request.form['cena']), opis=request.form['opis'], telefon=request.form['telefon'],
        przebieg=int(request.form.get('przebieg', 0)), user_id=current_user.id,
        img=url_for('static', filename='uploads/' + fname),
        paliwo=request.form.get('paliwo'), skrzynia=request.form.get('skrzynia'),
        nadwozie=request.form.get('nadwozie'), pojemnosc=request.form.get('pojemnosc')
    )
    db.session.add(nowe)
    db.session.commit()
    flash("Dodano ogłoszenie!", "success")
    return redirect(url_for('profil'))

@app.route('/usun/<int:car_id>', methods=['POST'])
@login_required
def delete_car(car_id):
    car = Car.query.get_or_404(car_id)
    if car.user_id == current_user.id or current_user.id == 1:
        db.session.delete(car)
        db.session.commit()
    return redirect(url_for('profil'))

# --- ADMIN / BACKUP ---
@app.route('/admin/full-backup')
@login_required
def full_backup():
    if current_user.id != 1: return "Brak uprawnień", 403
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w') as zf:
        for root, dirs, files in os.walk('.'):
            for file in files:
                zf.write(os.path.join(root, file))
    memory_file.seek(0)
    return send_file(memory_file, download_name='backup.zip', as_attachment=True)

@app.route('/admin/backup-db')
@login_required
def backup_db():
    if current_user.id != 1: return "Brak uprawnień", 403
    return send_file('instance/gielda.db', as_attachment=True)

# --- API AI ---
@app.route('/api/analyze-car', methods=['POST'])
def analyze_car_api():
    if 'image' not in request.files: return jsonify({"error": "Brak zdjęcia"}), 400
    img = Image.open(request.files['image'])
    prompt = "Rozpoznaj auto: Marka, Model, Rok. Zwróć JSON: {\"marka\":\"...\",\"model\":\"...\",\"rok\":2020,\"full_label\":\"...\"}"
    response = model_ai.generate_content([prompt, img])
    return response.text.replace('```json', '').replace('```', '').strip()

@app.route('/api/generate-description', methods=['POST'])
def generate_desc():
    data = request.json
    prompt = f"Napisz ogłoszenie: {data['marka']} {data['model']}, {data['rok']}r."
    res = model_ai.generate_content(prompt)
    return jsonify({"description": res.text})

# --- LOGOWANIE ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form['email']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
            login_user(user)
            return redirect(url_for('profil'))
    return render_template('login.html', now=datetime.utcnow())

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))

if __name__ == '__main__':
    with app.app_context(): db.create_all()
    app.run(host='0.0.0.0', port=5000)
