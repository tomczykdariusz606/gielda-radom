import os
import uuid
import zipfile
import io
from flask import Flask, render_template, request, redirect, url_for, flash, abort, send_from_directory, send_file
from datetime import datetime, timedelta
  jsonify, 
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from PIL import Image
from itsdangerous import URLSafeTimedSerializer as Serializer

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

# --- DODANA TABELA ASOCJACYJNA DLA ULUBIONYCH ---
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
    # Dodana relacja do ulubionych
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
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    if img.width > 1200:
        w_percent = (1200 / float(img.width))
        h_size = int((float(img.height) * float(w_percent)))
        img = img.resize((1200, h_size), Image.Resampling.LANCZOS)
    img.save(filepath, "WEBP", quality=75)
    return filename

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def send_reset_email(user):
    s = Serializer(app.secret_key)
    token = s.dumps(user.email, salt='reset-password')
    link = url_for('reset_token', token=token, _external=True)
    msg = Message('Resetowanie hasła - Giełda Radom', recipients=[user.email])
    msg.body = f"Aby zresetować hasło, kliknij w poniższy link:\n{link}\n\nJeśli to nie Ty, zignoruj tę wiadomość."
    mail.send(msg)

# --- OBSŁUGA FAVICON ---
@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')

# --- TRASY GŁÓWNE ---
@app.route('/')
def index():
    limit_daty = datetime.utcnow() - timedelta(days=30)
    query = request.args.get('q')
    base_query = Car.query.filter(Car.data_dodania >= limit_daty)
    if query:
        search = f"%{query}%"
        cars = base_query.filter(or_(Car.marka.ilike(search), Car.model.ilike(search))).order_by(Car.id.desc()).all()
    else:
        cars = base_query.order_by(Car.id.desc()).all()
    return render_template('index.html', cars=cars, search_query=query, now=datetime.utcnow())

@app.route('/ogloszenie/<int:car_id>')
def car_details(car_id):
    car = Car.query.get_or_404(car_id)
    return render_template('details.html', car=car, now=datetime.utcnow())

@app.route('/polityka-prywatnosci')
def polityka():
    return render_template('polityka.html', now=datetime.utcnow())

@app.route('/regulamin')
def regulamin():
    return render_template('regulamin.html', now=datetime.utcnow())

@app.route('/kontakt', methods=['GET', 'POST'])
def kontakt():
    if request.method == 'POST':
        msg = Message(subject=f"Kontakt: {request.form.get('name')}", 
                      recipients=['dariusztom@go2.pl'], 
                      body=f"Od: {request.form.get('name')}\nEmail: {request.form.get('email')}\n\n{request.form.get('message')}")
        try:
            mail.send(msg)
            flash('Wiadomość wysłana!', 'success')
        except:
            flash('Błąd wysyłki.', 'danger')
        return redirect(url_for('kontakt'))
    return render_template('kontakt.html', now=datetime.utcnow())

# --- DODANA FUNKCJA: OBSŁUGA ULUBIONYCH ---
@app.route('/toggle_favorite/<int:car_id>')
@login_required
def toggle_favorite(car_id):
    car = Car.query.get_or_404(car_id)
    if car in current_user.favorite_cars:
        current_user.favorite_cars.remove(car)
        flash('Usunięto z ulubionych', 'info')
    else:
        current_user.favorite_cars.append(car)
        flash('Dodano do ulubionych!', 'success')
    db.session.commit()
    return redirect(request.referrer or url_for('index'))

# --- ZARZĄDZANIE OGŁOSZENIAMI ---
@app.route('/profil')
@login_required
def profil():
    my_cars = Car.query.filter_by(user_id=current_user.id).order_by(Car.id.desc()).all()
    # Przekazanie ulubionych do profilu
    fav_cars = current_user.favorite_cars
    return render_template('profil.html', cars=my_cars, fav_cars=fav_cars, now=datetime.utcnow())

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
    nowe_auto = Car(marka=request.form['marka'], model=request.form['model'], rok=int(request.form['rok']), 
                    cena=float(request.form['cena']), opis=request.form['opis'], telefon=request.form['telefon'], 
                    img=main_img, zrodlo=current_user.lokalizacja,
 user_id=current_user.id)
    db.session.add(nowe_auto)
    db.session.commit()
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
        car.marka, car.model = request.form['marka'], request.form['model']
        car.rok, car.cena = int(request.form['rok']), float(request.form['cena'])
        car.telefon, car.opis = request.form['telefon'], request.form['opis']
        files = request.files.getlist('zdjecia')
        for file in files:
            if file and allowed_file(file.filename) and len(car.images) < 10:
                opt_name = save_optimized_image(file)
                path = url_for('static', filename='uploads/' + opt_name)
                db.session.add(CarImage(image_path=path, car_id=car.id))
        db.session.commit()
        flash('Zaktualizowano!', 'success')
        return redirect(url_for('profil'))
    return render_template('edytuj.html', car=car, now=datetime.utcnow())

@app.route('/ustaw_glowne/<int:car_id>/<int:image_id>', methods=['POST'])
@login_required
def ustaw_glowne(car_id, image_id):
    car = Car.query.get_or_404(car_id)
    img_record = CarImage.query.get_or_404(image_id)
    if car.user_id != current_user.id or img_record.car_id != car.id:
        return jsonify({"success": False}), 403
    car.img = img_record.image_path
    db.session.commit()
    return jsonify({"success": True})

@app.route('/odswiez/<int:car_id>', methods=['POST'])
@login_required
def odswiez_ogloszenie(car_id):
    car = Car.query.get_or_404(car_id)
    if car.user_id == current_user.id:
        car.data_dodania = datetime.utcnow()
        db.session.commit()
        flash('Odświeżono na 30 dni!', 'success')
    return redirect(url_for('profil'))

@app.route('/usun_zdjecie/<int:image_id>', methods=['POST'])
@login_required
def usun_zdjecie(image_id):
    img = CarImage.query.get_or_404(image_id)
    if img.car.user_id != current_user.id: return jsonify({"success": False}), 403
    fpath = os.path.join(app.config['UPLOAD_FOLDER'], img.image_path.split('/')[-1])
    if os.path.exists(fpath): os.remove(fpath)
    db.session.delete(img)
    db.session.commit()
    return jsonify({"success": True})

@app.route('/usun/<int:car_id>', methods=['POST'])
@login_required
def delete_car(car_id):
    car = Car.query.get_or_404(car_id)
    if car.user_id == current_user.id:
        for img in car.images:
            fpath = os.path.join(app.config['UPLOAD_FOLDER'], img.image_path.split('/')[-1])
            if os.path.exists(fpath): os.remove(fpath)
        db.session.delete(car)
        db.session.commit()
        flash('Usunięto ogłoszenie.', 'success')
    return redirect(url_for('profil'))

# --- RESET HASŁA ---
@app.route("/reset_password", methods=['GET', 'POST'])
def reset_request():
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        if user:
            try:
                send_reset_email(user)
                flash('Instrukcje zostały wysłane.', 'success')
            except: flash('Błąd poczty.', 'danger')
        else: flash('Nie znaleziono e-maila w bazie.', 'warning')
        return redirect(url_for('reset_request'))
    return render_template('reset_request.html', now=datetime.utcnow())

@app.route("/reset_password/<token>", methods=['GET', 'POST'])
def reset_token(token):
    s = Serializer(app.secret_key)
    try: 
        email = s.loads(token, salt='reset-password', max_age=1800)
    except:
        flash('Token wygasł lub jest nieprawidłowy.', 'danger')
        return redirect(url_for('reset_request'))

    if request.method == 'POST':
        user = User.query.filter_by(email=email).first()
        if user:
            user.password_hash = generate_password_hash(request.form.get('password'))
            db.session.commit()
            flash('Twoje hasło zostało zmienione! Możesz się teraz zalogować.', 'success')
            return redirect(url_for('login'))
    return render_template('reset_token.html', now=datetime.utcnow())

# --- UŻYTKOWNICY ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        user = request.form['username']
        email = request.form['email']
        loc = request.form.get('location', 'Radom') 
        if User.query.filter((User.username == user) | (User.email == email)).first():
            flash('Użytkownik/Email istnieje!', 'danger')
            return redirect(url_for('register'))
        new_user = User(username=user, email=email,
lokalizacja=loc,  password_hash=generate_password_hash(request.form['password']))
        db.session.add(new_user)
        db.session.commit()
        flash('Zarejestrowano!', 'success')
        return redirect(url_for('login'))
    return render_template('register.html', now=datetime.utcnow())

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
            login_user(user)
            return redirect(url_for('profil'))
        flash('Błąd logowania.', 'danger')
    return render_template('login.html', now=datetime.utcnow())

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/usun_konto', methods=['POST'])
@login_required
def usun_konto():
    user = User.query.get(current_user.id)
    for car in user.cars:
        for img in car.images:
            fpath = os.path.join(app.config['UPLOAD_FOLDER'], img.image_path.split('/')[-1])
            if os.path.exists(fpath): os.remove(fpath)
    db.session.delete(user)
    db.session.commit()
    logout_user()
    flash('Konto usunięte.', 'info')
    return redirect(url_for('index'))

# --- SITEMAP I ROBOTS ---
@app.route('/sitemap.xml')
def sitemap():
    pages = []
    today = datetime.utcnow().strftime('%Y-%m-%d')
    pages.append({'url': url_for('index', _external=True), 'lastmod': today, 'freq': 'daily', 'priority': '1.0'})
    pages.append({'url': url_for('regulamin', _external=True), 'lastmod': today, 'freq': 'monthly', 'priority': '0.3'})
    pages.append({'url': url_for('polityka', _external=True), 'lastmod': today, 'freq': 'monthly', 'priority': '0.3'})
    cars = Car.query.all()
    for car in cars:
        pages.append({
            'url': url_for('car_details', car_id=car.id, _external=True),
            'lastmod': car.data_dodania.strftime('%Y-%m-%d'),
            'freq': 'weekly',
            'priority': '0.8'
        })
    return render_template('sitemap_xml.html', pages=pages), 200, {'Content-Type': 'application/xml'}

@app.route('/robots.txt')
def robots():
    lines = [
        "User-agent: *",
        "Disallow: /profil",
        "Disallow: /edytuj/",
        "Disallow: /usun/",
        "Disallow: /login",
        "Disallow: /register",
        f"Sitemap: {url_for('sitemap', _external=True)}"
    ]
    return "\n".join(lines), 200, {'Content-Type': 'text/plain'}
# --- TRASY ADMINISTRACYJNE I BACKUP ---
@app.route('/admin/backup-db')
@login_required
def backup_db():
    if current_user.id != 1:
        abort(403)
    try:
        instance_path = os.path.join(app.root_path, 'instance')
        return send_from_directory(directory=instance_path, path='gielda.db', as_attachment=True,
                                 download_name=f"backup_gielda_{datetime.now().strftime('%Y%m%d_%H%M')}.db")
    except Exception as e:
        return f"Błąd: {str(e)}", 500

@app.route('/admin/full-backup')
@login_required
def full_backup():
    if current_user.id != 1:
        abort(403)
    
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Pakowanie bazy
        db_path = os.path.join(app.root_path, 'instance', 'gielda.db')
        if os.path.exists(db_path):
            zf.write(db_path, arcname='gielda.db')
        
        # Pakowanie zdjęć
        upload_path = app.config['UPLOAD_FOLDER']
        for root, dirs, files in os.walk(upload_path):
            for file in files:
                file_path = os.path.join(root, file)
                zf.write(file_path, arcname=os.path.join('static/uploads', file))
    
    memory_file.seek(0)
    return send_file(memory_file, mimetype='application/zip', as_attachment=True,
                     download_name=f"PELNY_BACKUP_{datetime.now().strftime('%Y%m%d')}.zip")

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)
