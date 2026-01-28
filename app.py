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
from PIL import Image

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
    img = db.Column(db.String(200), nullable=False) # Ścieżka do zdjęcia głównego
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

# --- OPTYMALIZACJA ZDJĘĆ ---
def save_optimized_image(file):
    """Konwertuje zdjęcie na WebP i skaluje do HD, co wspiera pasek postępu."""
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
        msg = Message(subject=f"Kontakt: {name}", recipients=['dariusztom@go2.pl'], 
                      body=f"Od: {name}\nEmail: {email_from}\n\n{message_body}")
        try:
            mail.send(msg)
            flash('Wiadomość wysłana!', 'success')
        except:
            flash('Błąd wysyłki.', 'danger')
        return redirect(url_for('kontakt'))
    return render_template('kontakt.html')

# --- ZARZĄDZANIE OGŁOSZENIAMI ---

@app.route('/profil')
@login_required
def profil():
    my_cars = Car.query.filter_by(user_id=current_user.id).order_by(Car.id.desc()).all()
    return render_template('profil.html', cars=my_cars, now=datetime.utcnow())

@app.route('/dodaj', methods=['POST'])
@login_required
def dodaj_ogloszenie():
    files = request.files.getlist('zdjecia')
    saved_paths = []
    # Pasek postępu na froncie będzie widoczny, dopóki ta pętla się nie skończy
    for file in files[:10]: 
        if file and allowed_file(file.filename):
            optimized_filename = save_optimized_image(file)
            img_path = url_for('static', filename='uploads/' + optimized_filename)
            saved_paths.append(img_path)

    # Wybór pierwszego zdjęcia jako główne przy dodawaniu
    main_img = saved_paths[0] if saved_paths else 'https://placehold.co/600x400?text=Brak+Zdjecia'

    nowe_auto = Car(
        marka=request.form['marka'], model=request.form['model'],
        rok=int(request.form['rok']), cena=float(request.form['cena']),
        opis=request.form['opis'], telefon=request.form['telefon'],
        img=main_img, data_dodania=datetime.utcnow(), user_id=current_user.id
    )
    db.session.add(nowe_auto)
    db.session.commit()

    for path in saved_paths:
        db.session.add(CarImage(image_path=path, car_id=nowe_auto.id))
    db.session.commit()
    flash('Ogłoszenie dodane pomyślnie!', 'success')
    return redirect(url_for('profil'))

@app.route('/ustaw_glowne/<int:car_id>/<int:image_id>', methods=['POST'])
@login_required
def ustaw_glowne(car_id, image_id):
    """Pozwala wybrać, które zdjęcie ma być miniaturką na stronie głównej."""
    car = Car.query.get_or_404(car_id)
    img_record = CarImage.query.get_or_404(image_id)
    if car.user_id != current_user.id or img_record.car_id != car.id:
        return jsonify({"success": False, "message": "Brak uprawnień"}), 403
    car.img = img_record.image_path
    db.session.commit()
    return jsonify({"success": True}), 200

@app.route('/edytuj/<int:car_id>', methods=['GET', 'POST'])
@login_required
def edit_car(car_id):
    car = Car.query.get_or_404(car_id)
    if car.user_id != current_user.id:
        abort(403)
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
        flash('Ogłoszenie zaktualizowane!', 'success')
        return redirect(url_for('profil'))
    return render_template('edytuj.html', car=car)

@app.route('/odswiez/<int:car_id>', methods=['POST'])
@login_required
def odswiez_ogloszenie(car_id):
    car = Car.query.get_or_404(car_id)
    if car.user_id == current_user.id:
        car.data_dodania = datetime.utcnow()
        db.session.commit()
        flash('Ogłoszenie odświeżone na 30 dni!', 'success')
    return redirect(url_for('profil'))

@app.route('/usun/<int:car_id>', methods=['POST'])
@login_required
def delete_car(car_id):
    car = Car.query.get_or_404(car_id)
    if car.user_id != current_user.id: abort(403)
    for img_record in car.images:
        fpath = os.path.join(app.config['UPLOAD_FOLDER'], img_record.image_path.split('/')[-1])
        if os.path.exists(fpath): os.remove(fpath)
    db.session.delete(car)
    db.session.commit()
    flash('Ogłoszenie usunięte.', 'success')
    return redirect(url_for('profil'))

@app.route('/usun_zdjecie/<int:image_id>', methods=['POST'])
@login_required
def usun_zdjecie(image_id):
    img = CarImage.query.get_or_404(image_id)
    car = img.car
    if car.user_id != current_user.id: return jsonify({"success": False}), 403
    
    fpath = os.path.join(app.config['UPLOAD_FOLDER'], img.image_path.split('/')[-1])
    if os.path.exists(fpath): os.remove(fpath)
    
    db.session.delete(img)
    db.session.commit()

    # Jeśli usunięto zdjęcie główne, przypisz pierwsze lepsze pozostałe
    if car.img == img.image_path:
        any_img = CarImage.query.filter_by(car_id=car.id).first()
        car.img = any_img.image_path if any_img else 'https://placehold.co/600x400?text=Brak+Zdjecia'
        db.session.commit()
    
    return jsonify({"success": True}), 200

# --- UŻYTKOWNICY ---

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        user = request.form['username']
        if User.query.filter_by(username=user).first():
            flash('Użytkownik istnieje!', 'danger')
            return redirect(url_for('register'))
        new_user = User(username=user, password_hash=generate_password_hash(request.form['password']))
        db.session.add(new_user)
        db.session.commit()
        flash('Konto gotowe!', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
            login_user(user)
            return redirect(url_for('profil'))
        flash('Błąd logowania.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
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
    flash('Twoje konto zostało całkowicie usunięte.', 'info')
    return redirect(url_for('index'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)
