import os
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'sekretny_klucz_gieldy_radom_2024' # W produkcji użyj losowego ciągu znaków

# --- KONFIGURACJA BAZY DANYCH ---
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///gielda.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- KONFIGURACJA LOGOWANIA ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- KONFIGURACJA UPLOADU ---
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

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
    img = db.Column(db.String(200), nullable=False)
    zrodlo = db.Column(db.String(20), default='Lokalne')
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- TRASY (ROUTES) ---

@app.route('/')
def index():
    cars = Car.query.all()
    return render_template('index.html', cars=cars)

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
            flash('Zalogowano pomyślnie!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Błędny login lub hasło.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Wylogowano.', 'info')
    return redirect(url_for('index'))

@app.route('/dodaj', methods=['POST'])
@login_required
def dodaj_ogloszenie():
    marka = request.form['marka']
    model = request.form['model']
    rok = request.form['rok']
    cena = request.form['cena']
    opis = request.form['opis']
    
    image_url = 'https://placehold.co/600x400?text=Brak+Zdjecia'
    
    if 'zdjecie' in request.files:
        file = request.files['zdjecie']
        if file and file.filename != '' and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            image_url = url_for('static', filename='uploads/' + filename)

    nowe_auto = Car(
        marka=marka, model=model, rok=int(rok), cena=float(cena),
        opis=opis, img=image_url, user_id=current_user.id
    )
    db.session.add(nowe_auto)
    db.session.commit()
    flash('Ogłoszenie dodane!', 'success')
    return redirect(url_for('index'))

@app.route('/import-otomoto', methods=['POST'])
@login_required
def import_otomoto():
    link = request.form['link']
    # Symulacja importu dla bezpieczeństwa
    if "otomoto.pl" in link:
        nowe_auto = Car(
            marka='Import', model='z Otomoto', rok=2023, cena=0,
            opis=f'Import z linku: {link}', 
            img='https://placehold.co/600x400?text=Import+Otomoto',
            zrodlo='Otomoto', user_id=current_user.id
        )
        db.session.add(nowe_auto)
        db.session.commit()
        flash('Zaimportowano ogłoszenie (symulacja)!', 'info')
    else:
        flash('To nie jest prawidłowy link do Otomoto.', 'danger')
    return redirect(url_for('index'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)

