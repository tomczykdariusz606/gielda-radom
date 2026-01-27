import os
from flask import Flask, render_template, request, redirect, url_for, flash, abort
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import uuid

app = Flask(__name__)
from flask_mail import Mail, Message

# Dodaj to zaraz po app = Flask(__name__)
app.config['MAIL_SERVER'] = 'poczta.o2.pl'
app.config['MAIL_PORT'] = 465
app.config['MAIL_USE_SSL'] = True
app.config['MAIL_USERNAME'] = 'dariusztom@go2.pl'
app.config['MAIL_PASSWORD'] = '3331343Darek1983' # Wpisz tu swoje hasło
app.config['MAIL_DEFAULT_SENDER'] = 'dariusztom@go2.pl'

mail = Mail(app)

app.secret_key = 'sekretny_klucz_gieldy_radom_2024'

# --- KONFIGURACJA ---
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///gielda.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
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
    cars = db.relationship('Car', backref='owner', lazy=True)

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
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    images = db.relationship('CarImage', backref='car', lazy=True, cascade="all, delete-orphan")

class CarImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    image_path = db.Column(db.String(200), nullable=False)
    car_id = db.Column(db.Integer, db.ForeignKey('car.id'), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- TRASY ---

@app.route('/')
def index():
    query = request.args.get('q')
    if query:
        search = f"%{query}%"
        cars = Car.query.filter(or_(Car.marka.ilike(search), Car.model.ilike(search))).order_by(Car.id.desc()).all()
    else:
        cars = Car.query.order_by(Car.id.desc()).all()
    return render_template('index.html', cars=cars, search_query=query)

@app.route('/ogloszenie/<int:car_id>')
def car_details(car_id):
    car = Car.query.get_or_404(car_id)
    return render_template('details.html', car=car)

# POPRAWIONE: Ta funkcja teraz prawidłowo ładuje Twój plik HTML
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
        
        # Tworzenie maila
        msg = Message(
            subject=f"Nowa wiadomość od: {name}",
            recipients=['dariusztom@go2.pl], # Adres, na który ma przyjść mail
            body=f"Nadawca: {name}\nE-mail: {email_from}\n\nTreść:\n{message_body}"
        )
        
        try:
            mail.send(msg)
            flash('Wiadomość została wysłana pomyślnie!', 'success')
        except Exception as e:
            print(f"Błąd wysyłki: {e}")
            flash('Błąd podczas wysyłania wiadomości. Spróbuj później.', 'danger')
            
        return redirect(url_for('kontakt'))
    
    return render_template('kontakt.html')

# --- PANEL UŻYTKOWNIKA (PROFIL) ---
@app.route('/profil')
@login_required
def profil():
    my_cars = Car.query.filter_by(user_id=current_user.id).order_by(Car.id.desc()).all()
    return render_template('profil.html', cars=my_cars)

@app.route('/usun/<int:car_id>', methods=['POST'])
@login_required
def delete_car(car_id):
    car = Car.query.get_or_404(car_id)
    if car.user_id != current_user.id:
        abort(403)
    db.session.delete(car)
    db.session.commit()
    flash('Ogłoszenie zostało usunięte.', 'success')
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
        db.session.commit()
        flash('Zapisano zmiany!', 'success')
        return redirect(url_for('profil'))
    return render_template('edytuj.html', car=car)

@app.route('/dodaj', methods=['POST'])
@login_required
def dodaj_ogloszenie():
    marka = request.form['marka']
    model = request.form['model']
    rok = request.form['rok']
    cena = request.form['cena']
    telefon = request.form['telefon']
    opis = request.form['opis']
    files = request.files.getlist('zdjecia')
    saved_images = []
    for file in files[:10]: 
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            unique_filename = str(uuid.uuid4())[:8] + "_" + filename
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
            saved_images.append(url_for('static', filename='uploads/' + unique_filename))
    main_img = saved_images[0] if saved_images else 'https://placehold.co/600x400?text=Brak+Zdjecia'
    nowe_auto = Car(marka=marka, model=model, rok=int(rok), cena=float(cena),
                    opis=opis, telefon=telefon, img=main_img, user_id=current_user.id)
    db.session.add(nowe_auto)
    db.session.commit()
    for img_path in saved_images:
        new_image = CarImage(image_path=img_path, car_id=nowe_auto.id)
        db.session.add(new_image)
    db.session.commit()
    flash('Ogłoszenie dodane pomyślnie!', 'success')
    return redirect(url_for('index'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if User.query.filter_by(username=username).first():
            flash('Login zajęty!', 'danger')
            return redirect(url_for('register'))
        new = User(username=username, password_hash=generate_password_hash(password))
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

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000)
