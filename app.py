import os
import uuid
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, abort, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_mail import Mail, Message
from PIL import Image  # Wymagane do oszczędności miejsca

app = Flask(__name__)

# --- KONFIGURACJA POCZTY ---
app.config['MAIL_SERVER'] = 'poczta.o2.pl'
app.config['MAIL_PORT'] = 465
app.config['MAIL_USE_SSL'] = True
app.config['MAIL_USERNAME'] = 'dariusztom@go2.pl'
app.config['MAIL_PASSWORD'] = '3331343Darek1983' 
app.config['MAIL_DEFAULT_SENDER'] = 'dariusztom@go2.pl'
mail = Mail(app)

# --- KONFIGURACJA APLIKACJI ---
app.secret_key = 'sekretny_klucz_gieldy_radom_2024'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///gielda.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
UPLOAD_FOLDER = 'static/uploads'
# Zmieniamy akceptowane formaty na wejściu, ale i tak skonwertujemy je do WebP
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- MODELE ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    cars = db.relationship('Car', backref='owner', lazy=True, cascade="all, delete-orphan")

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
    data_dodania = db.Column(db.DateTime, default=datetime.utcnow) # Data dla systemu 30-dniowego
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    images = db.relationship('CarImage', backref='car', lazy=True, cascade="all, delete-orphan")

class CarImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    image_path = db.Column(db.String(200), nullable=False)
    car_id = db.Column(db.Integer, db.ForeignKey('car.id'), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- POMOCNICZE: OPTYMALIZACJA ZDJĘĆ ---
def save_optimized_image(file):
    """Konwertuje zdjęcie na WebP, skaluje i zapisuje, by oszczędzać miejsce."""
    filename = f"{uuid.uuid4().hex}.webp"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    
    img = Image.open(file)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    
    # Skalowanie do HD (max 1200px), jeśli zdjęcie jest większe
    if img.width > 1200:
        w_percent = (1200 / float(img.width))
        h_size = int((float(img.height) * float(w_percent)))
        img = img.resize((1200, h_size), Image.Resampling.LANCZOS)
    
    img.save(filepath, "WEBP", quality=75)
    return filename

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- TRASY GŁÓWNE ---

@app.route('/')
def index():
    # Pokazujemy tylko ogłoszenia, które nie wygasły (nowsze niż 30 dni)
    limit_daty = datetime.utcnow() - timedelta(days=30)
    query = request.args.get('q')
    
    base_query = Car.query.filter(Car.data_dodania >= limit_daty)
    
    if query:
        search = f"%{query}%"
        cars = base_query.filter(or_(Car.marka.ilike(search), Car.model.ilike(search))).order_by(Car.id.desc()).all()
    else:
        cars = base_query.order_by(Car.id.desc()).all()
    return render_template('index.html', cars=cars, search_query=query)

@app.route('/ogloszenie/<int:car_id>')
def car_details(car_id):
    car = Car.query.get_or_404(car_id)
    return render_template('details.html', car=car, now=datetime.utcnow())


@app.route('/polityka-prywatnosci')
def polityka():
    return render_template('polityka.html')

@app.route('/regulamin')
def regulamin():
    return render_template('regulamin.html')

@app.route('/kontakt', methods=['GET', 'POST'])
def kontakt():
    if request.method == 'POST':
        name = request.form.get('name')
        email_from = request.form.get('email')
        message_body = request.form.get('message')

        msg = Message(
            subject=f"Nowa wiadomość od: {name}",
            recipients=['dariusztom@go2.pl'], 
            body=f"Nadawca: {name}\nE-mail: {email_from}\n\nTreść:\n{message_body}"
        )
        try:
            mail.send(msg)
            flash('Wiadomość została wysłana pomyślnie!', 'success')
        except Exception as e:
            flash('Błąd podczas wysyłania wiadomości.', 'danger')
        return redirect(url_for('kontakt'))
    return render_template('kontakt.html')

# --- ZARZĄDZANIE OGŁOSZENIAMI (Z OPTYMALIZACJĄ) ---

@app.route('/profil')
@login_required
def profil():
    my_cars = Car.query.filter_by(user_id=current_user.id).order_by(Car.id.desc()).all()
    # Przekazujemy 'now' do obliczenia licznika dni w HTML
    return render_template('profil.html', cars=my_cars, now=datetime.utcnow())

@app.route('/dodaj', methods=['POST'])
@login_required
def dodaj_ogloszenie():
    files = request.files.getlist('zdjecia')
    saved_paths = []

    for file in files[:10]: 
        if file and allowed_file(file.filename):
            # Optymalizacja i zapis jako WebP
            optimized_filename = save_optimized_image(file)
            img_path = url_for('static', filename='uploads/' + optimized_filename)
            saved_paths.append(img_path)

    if not saved_paths:
        main_img = 'https://placehold.co/600x400?text=Brak+Zdjecia'
    else:
        main_img = saved_paths[0]

    nowe_auto = Car(
        marka=request.form['marka'],
        model=request.form['model'],
        rok=int(request.form['rok']),
        cena=float(request.form['cena']),
        opis=request.form['opis'],
        telefon=request.form['telefon'],
        img=main_img,
        data_dodania=datetime.utcnow(), # Start licznika 30 dni
        user_id=current_user.id
    )
    db.session.add(nowe_auto)
    db.session.commit()

    for path in saved_paths:
        db.session.add(CarImage(image_path=path, car_id=nowe_auto.id))
    db.session.commit()

    flash('Ogłoszenie dodane na 30 dni!', 'success')
    return redirect(url_for('profil'))

@app.route('/odswiez/<int:car_id>', methods=['POST'])
@login_required
def odswiez_ogloszenie(car_id):
    car = Car.query.get_or_404(car_id)
    if car.user_id != current_user.id:
        abort(403)
    car.data_dodania = datetime.utcnow() # Reset licznika do 30 dni
    db.session.commit()
    flash(f'Ogłoszenie {car.marka} zostało odświeżone!', 'success')
    return redirect(url_for('profil'))

@app.route('/edytuj/<int:car_id>', methods=['GET', 'POST'])
@login_required
def edit_car(car_id):
    car = Car.query.get_or_404(car_id)
    if car.user_id != current_user.id:
        abort(403)

    if request.method == 'POST':
        car.marka = request.form['marka']
        car.model = request.form['model']
        car.rok = int(request.form['rok'])
        car.cena = float(request.form['cena'])
        car.telefon = request.form['telefon']
        car.opis = request.form['opis']

        files = request.files.getlist('zdjecia')
        for file in files:
            if file and allowed_file(file.filename):
                if len(car.images) < 10:
                    optimized_filename = save_optimized_image(file)
                    img_path = url_for('static', filename='uploads/' + optimized_filename)
                    db.session.add(CarImage(image_path=img_path, car_id=car.id))

        db.session.commit()
        flash('Zmiany zapisane!', 'success')
        return redirect(url_for('profil'))
    return render_template('edytuj.html', car=car)

@app.route('/usun/<int:car_id>', methods=['POST'])
@login_required
def delete_car(car_id):
    car = Car.query.get_or_404(car_id)
    if car.user_id != current_user.id:
        abort(403)
    
    # FIZYCZNE USUWANIE PLIKÓW Z DYSKU
    for img_record in car.images:
        filename = img_record.image_path.split('/')[-1]
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        if os.path.exists(filepath):
            os.remove(filepath)

    db.session.delete(car)
    db.session.commit()
    flash('Ogłoszenie i zdjęcia zostały usunięte.', 'success')
    return redirect(url_for('profil'))

@app.route('/usun_zdjecie/<int:image_id>', methods=['POST'])
@login_required
def usun_zdjecie(image_id):
    img = CarImage.query.get_or_404(image_id)
    if img.car.user_id != current_user.id:
        return jsonify({"success": False}), 403
    
    # Fizyczne usuwanie pojedynczego zdjęcia
    filename = img.image_path.split('/')[-1]
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if os.path.exists(filepath):
        os.remove(filepath)

    db.session.delete(img)
    db.session.commit()
    return jsonify({"success": True}), 200

# --- UŻYTKOWNICY ---

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        if User.query.filter_by(username=username).first():
            flash('Login zajęty!', 'danger')
            return redirect(url_for('register'))
        new = User(username=username, password_hash=generate_password_hash(request.form['password']))
        db.session.add(new)
        db.session.commit()
        flash('Konto założone!', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
            login_user(user)
            return redirect(url_for('profil'))
        flash('Błędne dane', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/usun_konto', methods=['POST'])
@login_required
def usun_konto():
    try:
        user = User.query.get(current_user.id)
        # Usuwamy zdjęcia wszystkich aut tego użytkownika z dysku
        for car in user.cars:
            for img in car.images:
                fname = img.image_path.split('/')[-1]
                fpath = os.path.join(app.config['UPLOAD_FOLDER'], fname)
                if os.path.exists(fpath): os.remove(fpath)
        
        db.session.delete(user)
        db.session.commit()
        logout_user()
        flash('Konto i wszystkie dane zostały usunięte.', 'success')
        return redirect(url_for('index'))
    except:
        db.session.rollback()
        return redirect(url_for('profil'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)
