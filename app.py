from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date, time, timedelta
from sqlalchemy import or_, func
from dateutil.tz import gettz
from itertools import groupby
from flask_migrate import Migrate
import socket, sys, threading, os
from flask import Flask
from datetime import datetime
import tkinter as tk


BERLIN = gettz("Europe/Berlin")

app = Flask(__name__)
app.secret_key = 'dein_geheimer_schluessel'  # Bitte anpassen

def get_base_dir():
    # Bei PyInstaller liegt sys._MEIPASS im temp; wir wollen aber den echten Pfad der .exe
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)  # Ordner der .exe
    else:
        return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = get_base_dir()
DB_PATH = os.path.join(BASE_DIR, 'database.db')

app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
migrate = Migrate(app, db)

# Modelle
class Ausleiher(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    contact = db.Column(db.String(200))  # E-Mail, Telefon, Adresse
    bemerkung = db.Column(db.Text, default='')  # Neues Feld hinzufügen
    date_of_birth = db.Column(db.Date, nullable=False)
    agb_accepted = db.Column(db.Boolean, nullable=False)
    liability_accepted = db.Column(db.Boolean, nullable=False)
    signature_data = db.Column(db.Text)  # Base64-encoded Unterschrift
    vertragsdatum   = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(BERLIN))

    @property
    def name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def age(self):
        today = date.today()
        dob = self.date_of_birth
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

class Objekt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    beschreibung = db.Column(db.String(200))
    category = db.Column(
        db.String(50),
        nullable=False,
        default='Sonstiges'
    )  # Neue Spalte für Kategorie: Skateboards, Scooter, BMX, Bälle, Sonstiges

class Verleihung(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ausleiher_id = db.Column(db.Integer, db.ForeignKey('ausleiher.id'), nullable=False)
    objekt_id = db.Column(db.Integer, db.ForeignKey('objekt.id'), nullable=False)
    start_time = db.Column(db.DateTime(timezone=True), nullable=False)  # von DateTime zu DateTime(timezone=True)
    planned_duration = db.Column(db.Float, nullable=False)
    actual_duration = db.Column(db.Float)
    end_time = db.Column(db.DateTime(timezone=True), nullable=False) 
    status = db.Column(db.String(20), default="Ausgeliehen")
    return_time     = db.Column(db.DateTime(timezone=True))
    pfand_text = db.Column(db.Text)
    pfand_euro = db.Column(db.Float)
    helm_status = db.Column(db.String(20))
    helm_other = db.Column(db.String(200))
    return_note = db.Column(db.Text)

    ausleiher = db.relationship('Ausleiher', backref=db.backref('verleihungen', lazy=True))
    objekt = db.relationship('Objekt', backref=db.backref('verleihungen', lazy=True))

with app.app_context():
    db.create_all()

# Routen
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/registrierung', methods=['GET', 'POST'])
def registrierung():
    if request.method == 'POST':
        first_name   = request.form['first_name']
        last_name    = request.form['last_name']
        contact      = request.form['contact']
        dob_str      = request.form['date_of_birth']
        agb          = 'agb' in request.form
        liability    = 'liability' in request.form
        signature    = request.form.get('signature_data')
        bemerkung    = request.form.get('bemerkung', '')  # Korrekt geholt

        try:
            date_of_birth = datetime.strptime(dob_str, "%Y-%m-%d").date()
        except ValueError:
            flash('Ungültiges Geburtsdatum!', 'danger')
            return redirect(url_for('registrierung'))

        if Ausleiher.query.filter_by(first_name=first_name, last_name=last_name).first():
            flash('Dieser Ausleiher ist bereits registriert!', 'warning')
            return redirect(url_for('registrierung'))

        # KORREKTE ERSTELLUNG DES AUSLEIHERS:
        neuer_ausleiher = Ausleiher(
            first_name=first_name,
            last_name=last_name,
            contact=contact,
            date_of_birth=date_of_birth,
            agb_accepted=agb,
            liability_accepted=liability,
            signature_data=signature,
            bemerkung=bemerkung  # Hier eingefügt
        )
        
        db.session.add(neuer_ausleiher)
        db.session.commit()
        flash('Ausleiher erfolgreich registriert!', 'success')
        return redirect(url_for('index'))
    
    return render_template('registrierung.html')

@app.route('/ausleiher_list', methods=['GET'])
def ausleiher_list():
    search = request.args.get('search', '')
    if search:
        users = Ausleiher.query.filter(
            or_(Ausleiher.first_name.ilike(f'%{search}%'), Ausleiher.last_name.ilike(f'%{search}%'))
        ).order_by(Ausleiher.last_name).all()
    else:
        users = Ausleiher.query.order_by(Ausleiher.last_name).all()
    return render_template('ausleiher_list.html', ausleiher=users, search_query=search)

@app.route('/delete_ausleiher/<int:ausleiher_id>', methods=['POST'])
def delete_ausleiher(ausleiher_id):
    a = Ausleiher.query.get_or_404(ausleiher_id)
    db.session.delete(a)
    db.session.commit()
    flash('Ausleiher gelöscht!', 'success')
    return redirect(url_for('ausleiher_list'))

@app.route('/edit_ausleiher/<int:ausleiher_id>', methods=['GET', 'POST'])
def edit_ausleiher(ausleiher_id):
    a = Ausleiher.query.get_or_404(ausleiher_id)
    if request.method == 'POST':
        a.contact = request.form['contact']
        dob_str = request.form['date_of_birth']
        a.date_of_birth = datetime.strptime(dob_str, "%Y-%m-%d").date()
        a.agb_accepted = 'agb' in request.form
        a.liability_accepted = 'liability' in request.form
        a.signature_data = request.form.get('signature_data')
        a.bemerkung = request.form.get('bemerkung', '')
        db.session.commit()
        flash('Ausleiher erfolgreich aktualisiert!', 'success')
        return redirect(url_for('ausleiher_list'))
    return render_template('edit_ausleiher.html', ausleiher=a)

@app.route('/objekte', methods=['GET', 'POST'])
def objekte():
    if request.method == 'POST':
        name = request.form['name']
        desc = request.form.get('beschreibung', '')
        if Objekt.query.filter_by(name=name).first():
            flash('Objekt existiert bereits!', 'warning')
        else:
            o = Objekt(name=name, beschreibung=desc)
            db.session.add(o)
            db.session.commit()
            flash('Objekt hinzugefügt!', 'success')
        return redirect(url_for('objekte'))
    objs = Objekt.query.order_by(Objekt.name).all()
    return render_template('objekte.html', objekte=objs)

@app.route('/delete_objekt/<int:objekt_id>', methods=['POST'])
def delete_objekt(objekt_id):
    obj = Objekt.query.get_or_404(objekt_id)
    db.session.delete(obj)
    db.session.commit()
    flash('Objekt gelöscht!', 'success')
    return redirect(url_for('objekte'))

@app.route('/ausleihen', methods=['GET', 'POST'])
def ausleihen():
    # Ausleiher laden und Verfügbarkeit prüfen
    all_users = Ausleiher.query.order_by(Ausleiher.last_name).all()
    ausleiher_list = []
    for a in all_users:
        aktiv = Verleihung.query.filter_by(ausleiher_id=a.id, status='Ausgeliehen').first()
        a.verfuegbar = not bool(aktiv)
        ausleiher_list.append(a)

    # Objekte laden und Verfügbarkeit prüfen
    objs = Objekt.query.order_by(Objekt.name).all()

    if request.method == 'POST':
        user_id = request.form['ausleiher']
        start_str = request.form['start_time']
        return_input = request.form['return_time']
        try:
            start_dt = datetime.strptime(start_str, "%Y-%m-%dT%H:%M").replace(tzinfo=BERLIN)
        except ValueError:
            flash('Ungültige Startzeit!', 'danger')
            return redirect(url_for('ausleihen'))
        # Rückgabezeit: entweder HH:MM oder vollständiges datetime-local
        if len(return_input) == 5:
            hr, mi = map(int, return_input.split(':'))
            return_dt = datetime.combine(start_dt.date(), time(hr, mi)).replace(tzinfo=BERLIN)
            if return_dt <= start_dt:
                return_dt = return_dt.replace(day=start_dt.day + 1)
        else:
            try:
                return_dt = datetime.strptime(return_input, "%Y-%m-%dT%H:%M").replace(tzinfo=BERLIN)
            except ValueError:
                flash('Ungültige Rückgabezeit!', 'danger')
                return redirect(url_for('ausleihen'))

        # Prüfen ob Objekt bereits ausgeliehen ist
        objekt = Objekt.query.filter_by(name=request.form['objekt']).first()
        if Verleihung.query.filter_by(objekt_id=objekt.id, status='Ausgeliehen').first():
            flash('Dieses Objekt ist bereits ausgeliehen!', 'danger')
            return redirect(url_for('ausleihen'))

        duration = (return_dt - start_dt).total_seconds() / 3600
        if duration < 0:
            flash('Rückgabezeit muss nach Startzeit liegen!', 'danger')
            return redirect(url_for('ausleihen'))

        pfand_text = request.form.get('pfand_text')
        pfand_euro = float(request.form.get('pfand_euro') or 0)
        helm_status = request.form.get('helm_status')
        helm_other = request.form.get('helm_other')

        rental = Verleihung(
            ausleiher_id=user_id,
            objekt_id=objekt.id,
            start_time=start_dt,
            planned_duration=duration,
            end_time=return_dt,
            pfand_text=pfand_text,
            pfand_euro=pfand_euro,
            helm_status=helm_status,
            helm_other=helm_other
        )
        db.session.add(rental)
        db.session.commit()
        flash('Verleihung erfolgreich hinzugefügt!', 'success')
        return redirect(url_for('dashboard'))

    # Verfügbare Objekte ermitteln
    verfuegbare_objekte = []
    for obj in objs:
        aktiv_verliehen = Verleihung.query.filter_by(objekt_id=obj.id, status='Ausgeliehen').first()
        obj.verfuegbar = not bool(aktiv_verliehen)
        verfuegbare_objekte.append(obj)

    return render_template('ausleihen.html',
                           ausleiher_list=ausleiher_list,
                           objekte_list=verfuegbare_objekte)

# In app.py, passe die Dashboard-Route so an:

from datetime import datetime, date
from sqlalchemy import func

@app.route('/dashboard')
def dashboard():
    today = date.today()
    now = datetime.now(BERLIN)

    active = Verleihung.query.filter_by(status='Ausgeliehen').all()
    returned = (Verleihung.query
                .filter(Verleihung.status=='Zurückgegeben',
                        func.date(Verleihung.return_time)==today)
                .order_by(Verleihung.return_time.desc())
                .all())

    return render_template('dashboard.html',
                           active=active,
                           returned=returned,
                           now=now)

@app.route('/zurueckgeben/<int:verleih_id>', methods=['POST'])
def zurueckgeben(verleih_id):
    r = Verleihung.query.get_or_404(verleih_id)
    if r.status != 'Zurückgegeben':
        # Aktuelle Zeit in der gleichen Timezone wie start_time
        if r.start_time.tzinfo is not None:
            now = datetime.now(r.start_time.tzinfo)
        else:
            # Falls start_time keine Timezone hat, nehmen wir Berlin
            now = datetime.now(BERLIN)
            # Wir machen auch start_time timezone-aware
            r.start_time = r.start_time.replace(tzinfo=BERLIN)
        
        r.status = 'Zurückgegeben'
        r.return_time = now
        r.actual_duration = (now - r.start_time).total_seconds() / 3600
        db.session.commit()
        flash('Verleihung als zurückgegeben markiert!', 'success')
    else:
        flash('Bereits zurückgegeben!', 'info')
    return redirect(url_for('dashboard'))

@app.route('/zurueckgeben_form/<int:verleih_id>', methods=['GET', 'POST'])
def zurueckgeben_form(verleih_id):
    r = Verleihung.query.get_or_404(verleih_id)
    if request.method == 'POST':
        # Status und Rückgabezeit setzen (Berlin‑Timezone)
        r.status = 'Zurückgegeben'
        now_berlin = datetime.now(BERLIN)
        r.return_time = now_berlin

        # Wenn start_time tz‑naiv ist, setzen wir dieselbe Zone:
        start = r.start_time
        if start.tzinfo is None:
            start = start.replace(tzinfo=BERLIN)
            r.start_time = start  # optional, um in DB auch tz‑aware zu haben

        # Dauer berechnen
        r.actual_duration = (now_berlin - start).total_seconds() / 3600

        # Rückgabemerkung
        r.return_note = request.form.get('return_note')

        db.session.commit()
        flash('Rückgabe abgeschlossen!', 'success')
        return redirect(url_for('dashboard'))

    return render_template('zurueckgeben.html', rental=r)

@app.route('/historie')
def historie():
    # Alle Einträge absteigend nach Startzeit
    history = Verleihung.query.order_by(Verleihung.start_time.desc()).all()
    # Nach Datum der start_time gruppieren
    grouped = {
        day: list(items)
        for day, items in groupby(history, key=lambda r: r.start_time.date())
    }
    return render_template('historie.html', grouped_history=grouped)

@app.route('/edit_objekt/<int:objekt_id>', methods=['GET', 'POST'])
def edit_objekt(objekt_id):
    obj = Objekt.query.get_or_404(objekt_id)
    if request.method == 'POST':
        obj.name = request.form['name']
        obj.beschreibung = request.form['beschreibung']
        db.session.commit()
        flash('Objekt aktualisiert!', 'success')
        return redirect(url_for('objekte'))
    return render_template('edit_objekt.html', objekt=obj)

@app.route('/statistik')
def statistik():
    # 1. Parameter aus Query-String
    granularity = request.args.get('granularity', 'year')  # 'year','month','week','day'
    year  = request.args.get('year',  datetime.now(BERLIN).year, type=int)
    month = request.args.get('month', None, type=int)
    week  = request.args.get('week', None, type=int)
    day   = request.args.get('day', None)  # im Format 'YYYY-MM-DD'
    
    # 2. Zeitraum berechnen
    if granularity == 'year':
        start = date(year, 1, 1)
        end   = date(year+1, 1, 1)
    elif granularity == 'month' and month:
        start = date(year, month, 1)
        # nächsten Monat berechnen
        if month == 12:
            end = date(year+1, 1, 1)
        else:
            end = date(year, month+1, 1)
    elif granularity == 'week' and week:
        # ISO Woche: Monday ist Tag 1
        iso = date.fromisocalendar(year, week, 1)
        start = iso
        end   = iso + timedelta(days=7)
    elif granularity == 'day' and day:
        start = datetime.strptime(day, "%Y-%m-%d").date()
        end   = start + timedelta(days=1)
    else:
        # Fallback: aktuelles Jahr
        start = date(datetime.now(BERLIN).year, 1, 1)
        end   = date(datetime.now(BERLIN).year+1, 1, 1)

    # 3. Basis-Statistiken
    period_loans = Verleihung.query.filter(
        Verleihung.start_time >= start,
        Verleihung.start_time <  end
    )
    total_verleihungen = period_loans.count()
    total_hours = (
        db.session.query(func.sum(Verleihung.actual_duration))
        .filter(
            Verleihung.actual_duration != None,
            Verleihung.start_time >= start,
            Verleihung.start_time <  end
        )
        .scalar() or 0
    )
    
    # 4. Kategorie-Statistik
    # Zähle Loans pro Objekt und filter auf gewählte Kategorie (optional)
    cat = request.args.get('category', 'Alle')
    cat_filter = [] if cat=='Alle' else [Objekt.category == cat]
    data = (
      db.session.query(
        Objekt.name,
        func.count(Verleihung.id).label('count')
      )
      .join(Verleihung, Verleihung.objekt_id==Objekt.id)
      .filter(
        Verleihung.start_time >= start,
        Verleihung.start_time <  end,
        *cat_filter
      )
      .group_by(Objekt.id)
      .all()
    )
    labels = [row.name for row in data]
    counts = [row.count for row in data]
    
    # 5. Top-Ausleiher (nach Anzahl)
    top_users = (
      db.session.query(
        Ausleiher.first_name, Ausleiher.last_name,
        func.count(Verleihung.id).label('loan_count')
      )
      .join(Verleihung, Verleihung.ausleiher_id==Ausleiher.id)
      .filter(Verleihung.start_time >= start, Verleihung.start_time < end)
      .group_by(Ausleiher.id)
      .order_by(func.count(Verleihung.id).desc())
      .limit(10)
      .all()
    )
    
    # 6. Liste aller Jahre, Wochen, Monate für UI
    years = [y[0] for y in db.session
             .query(func.strftime('%Y', Verleihung.start_time))
             .distinct().order_by(func.strftime('%Y', Verleihung.start_time))
             .all()]
    
    return render_template('statistik.html',
        granularity=granularity, year=year, month=month, week=week, day=day,
        total_verleihungen=total_verleihungen,
        total_hours=round(total_hours,2),
        labels=labels, counts=counts,
        top_users=top_users,
        years=years,
        categories=['Alle','Skateboards','Scooter','BMX','Bälle','Sonstiges'],
        selected_cat=cat
    )

@app.route('/objekt_status')
def objekt_status():
    # Get all objects
    objekte = Objekt.query.order_by(Objekt.name).all()
    
    # Add status information
    for obj in objekte:
        # Check for active loans
        active_loan = Verleihung.query.filter_by(
            objekt_id=obj.id, 
            status='Ausgeliehen'
        ).first()
        
        if active_loan:
            obj.status = "Ausgeliehen"
            obj.current_loan = active_loan
        else:
            obj.status = "Verfügbar"
            obj.current_loan = None
    
    return render_template('objekt_status.html', objekte=objekte)

@app.route('/undo_rueckgabe/<int:verleih_id>', methods=['POST'])
def undo_rueckgabe(verleih_id):
    r = Verleihung.query.get_or_404(verleih_id)
    if r.status == 'Zurückgegeben':
        r.status = 'Ausgeliehen'
        r.return_time = None
        r.actual_duration = None
        r.return_note = None
        db.session.commit()
        flash('Rückgabe erfolgreich rückgängig gemacht!', 'success')
    else:
        flash('Diese Verleihung ist nicht zurückgegeben!', 'warning')
    return redirect(url_for('dashboard'))

@app.template_filter('format_duration')
def format_duration_filter(value):
    try:
        decimal_hours = float(value)
    except (TypeError, ValueError):
        return value

    total_minutes = int(round(decimal_hours * 60))
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{hours}h {minutes}min"

# Ändere diese Route
@app.route('/zurueckgeben_prompt/<int:verleih_id>', methods=['POST'])  # Nur POST erlauben
def zurueckgeben_prompt(verleih_id):
    r = Verleihung.query.get_or_404(verleih_id)
    if r.status != 'Zurückgegeben':
        # Korrekte Zeitzone-Handling
        now_berlin = datetime.now(BERLIN)
        
        # Stelle sicher, dass start_time timezone-aware ist
        if r.start_time.tzinfo is None:
            r.start_time = r.start_time.replace(tzinfo=BERLIN)
        
        r.status = 'Zurückgegeben'
        r.return_time = now_berlin
        r.actual_duration = (now_berlin - r.start_time).total_seconds() / 3600
        
        db.session.commit()
        flash('Verleihung als zurückgegeben markiert!', 'success')
    else:
        flash('Bereits zurückgegeben!', 'info')
    
    return redirect(url_for('dashboard'))

def get_local_ips():
    """Get all local IPv4 addresses (excluding localhost)"""
    ips = []
    hostname = socket.gethostname()
    try:
        all_ips = socket.getaddrinfo(hostname, None, socket.AF_INET)
        for addr in all_ips:
            ip = addr[4][0]
            if ip != '127.0.0.1':
                ips.append(ip)
    except Exception as e:
        print(f"Error getting IPs: {e}")
    return ips if ips else ["127.0.0.1"]  # Fallback to localhost

def create_gui(ips, port):
    """Create a simple GUI window with server information"""
    root = tk.Tk()
    root.title("Verleihsoftware")
    root.configure(bg='white')
    
    try:
        if getattr(sys, 'frozen', False):
            icon_path = os.path.join(sys._MEIPASS, "icon.ico")
        else:
            icon_path = os.path.join(BASE_DIR, "icon.ico")
        root.iconbitmap(icon_path)
    except Exception as e:
        print(f"Icon konnte nicht gesetzt werden: {e}")
    
    # Make window stay on top
    root.attributes('-topmost', True)
    
    # Create and pack widgets
    label = tk.Label(root, 
                    text="Die Verleihsoftware läuft im Hintergrund.",
                    bg='white', fg='black')
    label.pack(pady=10)
    
    ip_label = tk.Label(root, 
                       text=f"Die IP ist: {', '.join(ips)}",
                       bg='white', fg='black')
    ip_label.pack(pady=10)
    
    # Close button
    close_button = tk.Button(root, 
                           text="Beenden", 
                           command=root.destroy)
    close_button.pack(pady=10)
    
    root.mainloop()

# definiere Berlin‑Zone
@app.context_processor
def inject_now():
    # macht in Jinja das Aufrufen von now() möglich
    return {'now': lambda: datetime.now(BERLIN)}


def run_flask_app():
    """Startet die Flask-App (Ihr bestehender Code)"""
    from app import app  # Importieren Sie Ihre Flask-App
    app.run(host='0.0.0.0', port=80, debug=False, use_reloader=False)

if __name__ == '__main__':
    port = 5000  # Gleicher Port wie in Ihrer Flask-App
    ips = get_local_ips()

    # Starten Sie Flask in einem separaten Thread
    flask_thread = threading.Thread(target=run_flask_app, daemon=True)
    flask_thread.start()

    # Zeigen Sie das GUI an
    create_gui(ips, port)