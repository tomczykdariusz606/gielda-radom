import os
import uuid
import zipfile
import io
import google.generativeai as genai
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, abort, jsonify, send_file, Response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from PIL import Image
from itsdangerous import URLSafeTimedSerializer as Serializer
from thefuzz import process 

# Import kluczy z pliku sekrety.py (upewnij się, że plik istnieje)
try:
    import sekrety
    SECRET_KEY_VAL = getattr(sekrety, 'SECRET_KEY', 'sekret_radom_2026')
    GEMINI_API_KEY = getattr(sekrety, 'GEMINI_KEY', None)
    MAIL_PASS = getattr(sekrety, 'MAIL_PWD', '')
except ImportError:
    SECRET_KEY_VAL = 'sekret_radom_2026'
    GEMINI_API_KEY = None
    MAIL_PASS = ''

app = Flask(__name__)

# --- KONFIGURACJA ---
app.config['MAIL_SERVER'] = 'poczta.o2.pl'
app.config['MAIL_PORT'] = 465
app.config['MAIL_USE_SSL'] = True
app.config['MAIL_USERNAME'] = 'dariusztom@go2.pl'
app.config['MAIL_PASSWORD'] = MAIL_PASS
app.config['MAIL_DEFAULT_SENDER'] = 'dariusztom@go2.pl'
mail = Mail(app)

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    model_ai = genai.GenerativeModel('gemini-1.5-flash')
else:
    model_ai = None

app.secret_key = SECRET_KEY_VAL
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///gielda.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
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
    lokalizacja = db.Column(db.String(100), default='Radom')
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
    marka = db.Column(db.String(50), nullable=False)
    model = db.Column(db.String(50), nullable=False)
    rok = db.Column(db.Integer, nullable=False)
    cena = db.Column(db.Float, nullable=False)
    przebieg = db.Column(db.Integer, default=0)
    opis = db.Column(db.Text, nullable=False)
    telefon = db.Column(db.String(20), nullable=False)
    img = db.Column(db.String(200), nullable=False) 
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
    img.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
    img.save(filepath, "WEBP", quality=75)
    return url_for('static', filename='uploads/' + filename)

# --- TRASY WIDOKÓW (Zgodnie z Twoimi plikami HTML) ---

@app.route('/')
def index():
    # Pobieramy tylko te, które nie wygasły (30 dni)
    limit = datetime.utcnow() - timedelta(days=30)
    search_query = request.args.get('q', '').strip()
    
    base_query = Car.query.filter(Car.data_dodania >= limit)
    
    if search_query:
        all_cars = base_query.all()
        choices = {f"{c.marka} {c.model}": c.id for c in all_cars}
        matches = process.extract(search_query, choices.keys(), limit=20)
        matched_ids = [choices[m[0]] for m in matches if m[1] > 55]
        base_query = base_query.filter(Car.id.in_(matched_ids))

    cars = base_query.order_by(Car.id.desc()).all()
    # Przekazujemy 'now' do szablonu, aby działało: (now - car.data_dodania).days
    return render_template('index.html', cars=cars, now=datetime.utcnow(), search_query=search_query)

@app.route('/ogloszenie/<int:car_id>')
def details(car_id):
    car = Car.query.get_or_404(car_id)
    car.wyswietlenia += 1
    db.session.commit()
    return render_template('details.html', car=car, now=datetime.utcnow())

@app.route('/profil')
@login_required
def profil():
    cars = Car.query.filter_by(user_id=current_user.id).order_by(Car.id.desc()).all()
    return render_template('profil.html', cars=cars, fav_cars=current_user.favorite_cars, now=datetime.utcnow())

@app.route('/dodaj', methods=['POST'])
@login_required
def dodaj():
    files = request.files.getlist('zdjecia')
    paths = [save_optimized_image(f) for f in files[:10] if f]
    main_img = paths[0] if paths else 'https://placehold.co/600x400?text=Brak+Zdjecia'
    
    # Analiza wizualna AI
    ai_desc = ""
    if model_ai and paths:
        try:
            full_p = os.path.join(app.root_path, paths[0].lstrip('/'))
            res = model_ai.generate_content(["Opisz krótko to auto po polsku.", Image.open(full_p)])
            ai_desc = f"\n\n[Analiza AI]: {res.text}"
        except: pass

    new_car = Car(
        marka=request.form['marka'], model=request.form['model'],
        rok=int(request.form['rok']), cena=float(request.form['cena']),
        przebieg=int(request.form.get('przebieg', 0)),
        opis=request.form['opis'] + ai_desc, telefon=request.form['telefon'],
        img=main_img, user_id=current_user.id
    )
    db.session.add(new_car)
    db.session.flush()
    for p in paths: db.session.add(CarImage(image_path=p, car_id=new_car.id))
    db.session.commit()
    flash('Ogłoszenie dodane!', 'success')
    return redirect(url_for('profil'))

@app.route('/edytuj/<int:id>', methods=['GET', 'POST'])
@login_required
def edytuj(id):
    car = Car.query.get_or_404(id)
    if car.user_id != current_user.id: abort(403)
    if request.method == 'POST':
        car.marka = request.form['marka']; car.model = request.form['model']
        car.cena = request.form['cena']; car.opis = request.form['opis']
        db.session.commit()
        flash('Zmiany zapisane.', 'success')
        return redirect(url_for('profil'))
    return render_template('edytuj.html', car=car)

@app.route('/odswiez/<int:car_id>', methods=['POST'])
@login_required
def odswiez(car_id):
    car = Car.query.get_or_404(car_id)
    if car.user_id == current_user.id:
        car.data_dodania = datetime.utcnow() # Reset licznika 30 dni
        db.session.commit()
        flash('Ogłoszenie odświeżone!', 'success')
    return redirect(url_for('profil'))

@app.route('/toggle_favorite/<int:car_id>')
@login_required
def toggle_favorite(car_id):
    car = Car.query.get_or_404(car_id)
    if car in current_user.favorite_cars: current_user.favorite_cars.remove(car)
    else: current_user.favorite_cars.append(car)
    db.session.commit()
    return redirect(request.referrer or url_for('index'))
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
# --- STRONY STATYCZNE ---
@app.route('/kontakt')
def kontakt(): return render_template('kontakt.html')

@app.route('/polityka-prywatnosci')
def polityka(): return render_template('polityka.html')

@app.route('/regulamin')
def regulamin(): return render_template('regulamin.html')

# --- AUTH & RESET ---
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
        h = generate_password_hash(request.form['password'])
        db.session.add(User(username=request.form['username'], email=request.form['email'], password_hash=h))
        db.session.commit(); return redirect(url_for('login'))
    return render_template('register.html', now=datetime.utcnow())

@app.route('/logout')
def logout(): logout_user(); return redirect(url_for('index'))

@app.route('/reset_request', methods=['GET', 'POST'])
def reset_request():
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form['email']).first()
        if user:
            token = user.get_reset_token()
            msg = Message('Reset Hasła - Giełda Radom', recipients=[user.email])
            msg.body = f"Link do resetu: {url_for('reset_token', token=token, _external=True)}"
            mail.send(msg)
            flash('Email wysłany.', 'info')
        return redirect(url_for('login'))
    return render_template('reset_request.html')

@app.route('/reset_token/<token>', methods=['GET', 'POST'])
def reset_token(token):
    user = User.verify_reset_token(token)
    if not user: flash('Nieprawidłowy token', 'warning'); return redirect(url_for('reset_request'))
    if request.method == 'POST':
        user.password_hash = generate_password_hash(request.form['password'])
        db.session.commit(); flash('Hasło zmienione!', 'success')
        return redirect(url_for('login'))
    return render_template('reset_token.html')

# --- SEO ---
@app.route('/sitemap.xml')
def sitemap():
    xml = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    xml += f'<url><loc>{request.url_root}</loc><priority>1.0</priority></url>'
    for c in Car.query.all():
        xml += f'<url><loc>{request.url_root}ogloszenie/{c.id}</loc><priority>0.8</priority></url>'
    xml += '</urlset>'
    return Response(xml, mimetype='application/xml')

if __name__ == '__main__':
    with app.app_context(): db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)
