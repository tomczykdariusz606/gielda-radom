import os
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
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

# --- MODELE BAZY DANYCH ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

class Car(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    marka = db.Column(db.String(50), nullable=False)
    model = db.Column(db.String(50), nullable=False)
    rok = db.Column(db.Integer, nullable=False)
    cena = db.Column(db.Float, nullable=False)
    opis = db.Column(db.Text, nullable=False)
    # img to zdjęcie główne (okładka)
    img = db.Column(db.String(200), nullable=False)
    zrodlo = db.Column(db.String(20), default='Lokalne')
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    # Relacja do dodatkowych zdjęć
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
    cars = Car.query.order_by(Car.id.desc()).all()
    return render_template('index.html', cars=cars)

# NOWY WIDOK SZCZEGÓŁÓW OGŁOSZENIA
@app.route('/ogloszenie/<int:car_id>')
def car_details(car_id):
    car = Car.query.get_or_404(car_id) # Znajdź auto lub zwróć błąd 404
    return render_template('details.html', car=car)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if User.query.filter_by(username=username).first():
            flash('Użytkownik już istnieje!', 'danger')
            return redirect(url_for('register'))
        hashed_pw = generate_password_hash(password, method='scrypt')
        new_user = User(username=username, password_hash=hashed_pw)
        db.session.add(new_user)
        db.session.commit()
        flash('Konto założone! Zaloguj się.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('index'))
        flash('Błędne dane.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/dodaj', methods=['POST'])
@login_required
def dodaj_ogloszenie():
    marka = request.form['marka']
    model = request.form['model']
    rok = request.form['rok']
    cena = request.form['cena']
    opis = request.form['opis']
    
    # Obsługa zdjęć (MULTI UPLOAD)
    files = request.files.getlist('zdjecia') # Pobiera listę plików
    saved_images = []

    # Zapisz max 10 zdjęć
    for file in files[:10]: 
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            # Unikamy dublowania nazw plików dodając losowy prefix (opcjonalnie, tu prosto)
            import uuid
            unique_filename = str(uuid.uuid4())[:8] + "_" + filename
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
            saved_images.append(url_for('static', filename='uploads/' + unique_filename))

    # Ustaw zdjęcie główne (pierwsze z listy lub domyślne)
    if saved_images:
        main_img = saved_images[0]
    else:
        main_img = 'https://placehold.co/600x400?text=Brak+Zdjecia'

    # Tworzenie auta
    nowe_auto = Car(
        marka=marka, model=model, rok=int(rok), cena=float(cena),
        opis=opis, img=main_img, user_id=current_user.id
    )
    db.session.add(nowe_auto)
    db.session.commit() # Musimy zapisać, żeby dostać ID auta

    # Dodawanie reszty zdjęć do tabeli CarImage (wszystkie, włącznie z głównym)
    for img_path in saved_images:
        new_image = CarImage(image_path=img_path, car_id=nowe_auto.id)
        db.session.add(new_image)
    
    db.session.commit()
    
    flash('Ogłoszenie dodane pomyślnie!', 'success')
    return redirect(url_for('index'))

@app.route('/import-otomoto', methods=['POST'])
@login_required
def import_otomoto():
    # ... (bez zmian - kod importu z poprzedniej wersji)
    return redirect(url_for('index'))


@app.route('/polityka-prywatnosci')
def polityka():
    return render_template('polityka.html')

@app.route('/regulamin')
def regulamin():
    return render_template('regulamin.html')


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)
