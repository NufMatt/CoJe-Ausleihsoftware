from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date, time, timedelta
from sqlalchemy import or_, func
from dateutil.tz import gettz
from itertools import groupby
from flask_migrate import Migrate
import socket, sys, threading, os, shutil, glob
import tkinter as tk
from tkinter import scrolledtext

BERLIN = gettz("Europe/Berlin")

app = Flask(__name__)
app.secret_key = 'dein_geheimer_schluessel'

def get_base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = get_base_dir()
DB_PATH = os.path.join(BASE_DIR, 'database.db')
BACKUP_DIR = os.path.join(BASE_DIR, '.bak')

WEBSITE_PORT = 80

app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
migrate = Migrate(app, db)

# ── Modelle ──────────────────────────────────────────────────────────────────

class Ausleiher(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(50), nullable=False, default='')
    contact = db.Column(db.String(200))
    bemerkung = db.Column(db.Text, default='')
    date_of_birth = db.Column(db.Date, nullable=False)
    agb_accepted = db.Column(db.Boolean, nullable=False)
    liability_accepted = db.Column(db.Boolean, nullable=False)
    signature_data = db.Column(db.Text)
    vertragsdatum = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(BERLIN))

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
    category = db.Column(db.String(50), nullable=False, default='Sonstiges')

class Verleihung(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ausleiher_id = db.Column(db.Integer, db.ForeignKey('ausleiher.id'), nullable=False)
    objekt_id = db.Column(db.Integer, db.ForeignKey('objekt.id'), nullable=False)
    start_time = db.Column(db.DateTime(timezone=True), nullable=False)
    planned_duration = db.Column(db.Float, nullable=False)
    actual_duration = db.Column(db.Float)
    end_time = db.Column(db.DateTime(timezone=True), nullable=False)
    status = db.Column(db.String(20), default="Ausgeliehen")
    return_time = db.Column(db.DateTime(timezone=True))
    pfand_text = db.Column(db.Text)
    pfand_euro = db.Column(db.Float)
    helm_status = db.Column(db.String(20))
    helm_other = db.Column(db.String(200))
    return_note = db.Column(db.Text)

    ausleiher = db.relationship('Ausleiher', backref=db.backref('verleihungen', lazy=True))
    objekt = db.relationship('Objekt', backref=db.backref('verleihungen', lazy=True))

with app.app_context():
    db.create_all()

# ── Selbsttest ────────────────────────────────────────────────────────────────

def run_selftest():
    """Führt einen Selbsttest durch und gibt Liste von (status, nachricht) zurück."""
    results = []

    # 1. Datenbankdatei vorhanden?
    if os.path.exists(DB_PATH):
        results.append(('OK', f'Datenbankdatei gefunden: {DB_PATH}'))
    else:
        results.append(('INFO', f'Datenbankdatei nicht gefunden – wird neu erstellt: {DB_PATH}'))

    # 2. Datenbankverbindung und Tabellen
    try:
        with app.app_context():
            db.create_all()
            ausleiher_count = Ausleiher.query.count()
            objekt_count = Objekt.query.count()
            verleihung_count = Verleihung.query.count()
        results.append(('OK', 'Datenbankverbindung erfolgreich'))
        results.append(('OK', f'Tabelle "ausleiher": {ausleiher_count} Einträge'))
        results.append(('OK', f'Tabelle "objekt": {objekt_count} Einträge'))
        results.append(('OK', f'Tabelle "verleihung": {verleihung_count} Einträge'))
    except Exception as e:
        results.append(('FEHLER', f'Datenbankfehler: {e}'))

    # 3. Backup-Ordner
    if os.path.exists(BACKUP_DIR):
        backups = glob.glob(os.path.join(BACKUP_DIR, '*.db'))
        results.append(('OK', f'Backup-Ordner vorhanden, {len(backups)} Backup(s) gefunden'))
    else:
        results.append(('INFO', f'Backup-Ordner noch nicht vorhanden (wird beim ersten Backup erstellt)'))

    # 4. IP ermitteln
    ips = get_local_ips()
    results.append(('OK', f'Netzwerk-IP(s): {", ".join(ips)}'))

    return results

# ── Template-Filter ───────────────────────────────────────────────────────────

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

@app.context_processor
def inject_now():
    return {'now': lambda: datetime.now(BERLIN)}

# ── Routen ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/registrierung', methods=['GET', 'POST'])
def registrierung():
    if request.method == 'POST':
        name       = request.form['name']
        first_name = name  # ganzer Name im first_name-Feld
        last_name  = ''
        contact    = request.form['contact']
        agb        = 'agb' in request.form
        liability  = 'liability' in request.form
        signature  = request.form.get('signature_data')
        bemerkung  = request.form.get('bemerkung', '')

        age_input  = request.form.get('age', '').strip()
        year_input = request.form.get('birth_year', '').strip()

        try:
            if year_input:
                birth_year = int(year_input)
                date_of_birth = date(birth_year, 1, 1)
            elif age_input:
                age = int(age_input)
                today = date.today()
                date_of_birth = date(today.year - age, today.month, today.day)
            else:
                flash('Bitte Alter oder Geburtsjahr angeben!', 'danger')
                return redirect(url_for('registrierung'))
        except ValueError:
            flash('Ungültige Alters- oder Jahresangabe!', 'danger')
            return redirect(url_for('registrierung'))

        if Ausleiher.query.filter_by(first_name=name, last_name='').first():
            flash('Dieser Ausleiher ist bereits registriert!', 'warning')
            return redirect(url_for('registrierung'))

        neuer_ausleiher = Ausleiher(
            first_name=first_name, last_name=last_name, contact=contact,
            date_of_birth=date_of_birth, agb_accepted=agb,
            liability_accepted=liability, signature_data=signature,
            bemerkung=bemerkung
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
            or_(Ausleiher.first_name.ilike(f'%{search}%'),
                Ausleiher.last_name.ilike(f'%{search}%'))
        ).order_by(Ausleiher.last_name).all()
    else:
        users = Ausleiher.query.order_by(Ausleiher.last_name).all()
    return render_template('ausleiher_list.html', ausleiher=users, search_query=search)

@app.route('/delete_ausleiher/<int:ausleiher_id>', methods=['POST'])
def delete_ausleiher(ausleiher_id):
    a = Ausleiher.query.get_or_404(ausleiher_id)
    # Zuerst alle zugehörigen Verleihungen löschen
    Verleihung.query.filter_by(ausleiher_id=ausleiher_id).delete()
    db.session.delete(a)
    db.session.commit()
    flash('Ausleiher und zugehörige Verleihungen gelöscht!', 'success')
    return redirect(url_for('ausleiher_list'))

@app.route('/edit_ausleiher/<int:ausleiher_id>', methods=['GET', 'POST'])
def edit_ausleiher(ausleiher_id):
    a = Ausleiher.query.get_or_404(ausleiher_id)
    if request.method == 'POST':
        a.contact = request.form['contact']
        age_input  = request.form.get('age', '').strip()
        year_input = request.form.get('birth_year', '').strip()
        try:
            if year_input:
                a.date_of_birth = date(int(year_input), 1, 1)
            elif age_input:
                today = date.today()
                a.date_of_birth = date(today.year - int(age_input), today.month, today.day)
        except ValueError:
            flash('Ungültige Alters- oder Jahresangabe!', 'danger')
            return redirect(url_for('edit_ausleiher', ausleiher_id=ausleiher_id))
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

@app.route('/ausleihen', methods=['GET', 'POST'])
def ausleihen():
    all_users = Ausleiher.query.order_by(Ausleiher.last_name).all()
    ausleiher_list_data = []
    for a in all_users:
        aktiv = Verleihung.query.filter_by(ausleiher_id=a.id, status='Ausgeliehen').first()
        a.verfuegbar = not bool(aktiv)
        ausleiher_list_data.append(a)

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

        objekt = Objekt.query.filter_by(name=request.form['objekt']).first()
        if Verleihung.query.filter_by(objekt_id=objekt.id, status='Ausgeliehen').first():
            flash('Dieses Objekt ist bereits ausgeliehen!', 'danger')
            return redirect(url_for('ausleihen'))

        duration = (return_dt - start_dt).total_seconds() / 3600
        if duration < 0:
            flash('Rückgabezeit muss nach Startzeit liegen!', 'danger')
            return redirect(url_for('ausleihen'))

        pfand_chip = request.form.get('pfand_text', '').strip()
        pfand_text = f'Chipnummer {pfand_chip}' if pfand_chip else ''
        pfand_euro = float(request.form.get('pfand_euro') or 0)
        helm_status = request.form.get('helm_status')
        helm_other = request.form.get('helm_other')

        rental = Verleihung(
            ausleiher_id=user_id, objekt_id=objekt.id,
            start_time=start_dt, planned_duration=duration,
            end_time=return_dt, pfand_text=pfand_text,
            pfand_euro=pfand_euro, helm_status=helm_status,
            helm_other=helm_other
        )
        db.session.add(rental)
        db.session.commit()
        flash('Verleihung erfolgreich hinzugefügt!', 'success')
        return redirect(url_for('dashboard'))

    verfuegbare_objekte = []
    for obj in objs:
        aktiv_verliehen = Verleihung.query.filter_by(objekt_id=obj.id, status='Ausgeliehen').first()
        obj.verfuegbar = not bool(aktiv_verliehen)
        verfuegbare_objekte.append(obj)

    return render_template('ausleihen.html',
                           ausleiher_list=ausleiher_list_data,
                           objekte_list=verfuegbare_objekte)

@app.route('/dashboard')
def dashboard():
    today = date.today()
    now = datetime.now(BERLIN)
    is_friday = now.weekday() == 4  # 4 = Freitag

    active = Verleihung.query.filter_by(status='Ausgeliehen').all()
    returned = (Verleihung.query
                .filter(Verleihung.status == 'Zurückgegeben',
                        func.date(Verleihung.return_time) == today)
                .order_by(Verleihung.return_time.desc())
                .all())

    return render_template('dashboard.html',
                           active=active,
                           returned=returned,
                           now=now,
                           is_friday=is_friday)

@app.route('/zurueckgeben/<int:verleih_id>', methods=['POST'])
def zurueckgeben(verleih_id):
    r = Verleihung.query.get_or_404(verleih_id)
    if r.status != 'Zurückgegeben':
        if r.start_time.tzinfo is not None:
            now = datetime.now(r.start_time.tzinfo)
        else:
            now = datetime.now(BERLIN)
            r.start_time = r.start_time.replace(tzinfo=BERLIN)
        r.status = 'Zurückgegeben'
        r.return_time = now
        r.actual_duration = (now - r.start_time).total_seconds() / 3600
        db.session.commit()
        flash('Verleihung als zurückgegeben markiert!', 'success')
    else:
        flash('Bereits zurückgegeben!', 'info')
    return redirect(url_for('dashboard'))

@app.route('/zurueckgeben_prompt/<int:verleih_id>', methods=['POST'])
def zurueckgeben_prompt(verleih_id):
    r = Verleihung.query.get_or_404(verleih_id)
    if r.status != 'Zurückgegeben':
        now_berlin = datetime.now(BERLIN)
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

@app.route('/zurueckgeben_form/<int:verleih_id>', methods=['GET', 'POST'])
def zurueckgeben_form(verleih_id):
    r = Verleihung.query.get_or_404(verleih_id)
    if request.method == 'POST':
        r.status = 'Zurückgegeben'
        now_berlin = datetime.now(BERLIN)
        r.return_time = now_berlin
        start = r.start_time
        if start.tzinfo is None:
            start = start.replace(tzinfo=BERLIN)
            r.start_time = start
        r.actual_duration = (now_berlin - start).total_seconds() / 3600
        r.return_note = request.form.get('return_note')
        db.session.commit()
        flash('Rückgabe abgeschlossen!', 'success')
        return redirect(url_for('dashboard'))
    return render_template('zurueckgeben.html', rental=r)

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

@app.route('/historie')
def historie():
    search_user = request.args.get('search_user', '').strip()
    search_objekt = request.args.get('search_objekt', '').strip()

    query = Verleihung.query.join(Ausleiher).join(Objekt)

    if search_user:
        query = query.filter(
            or_(
                Ausleiher.first_name.ilike(f'%{search_user}%'),
                Ausleiher.last_name.ilike(f'%{search_user}%'),
                func.lower(Ausleiher.first_name + ' ' + Ausleiher.last_name).contains(search_user.lower())
            )
        )
    if search_objekt:
        query = query.filter(Objekt.name == search_objekt)

    history = query.order_by(Verleihung.start_time.desc()).all()
    grouped = {}
    for day_key, items in groupby(history, key=lambda r: r.start_time.date()):
        grouped[day_key] = list(items)

    alle_objekte = Objekt.query.order_by(Objekt.name).all()
    alle_ausleiher = Ausleiher.query.order_by(Ausleiher.last_name).all()

    return render_template('historie.html',
                           grouped_history=grouped,
                           alle_objekte=alle_objekte,
                           alle_ausleiher=alle_ausleiher,
                           search_user=search_user,
                           search_objekt=search_objekt)

@app.route('/statistik')
def statistik():
    granularity = request.args.get('granularity', 'year')
    year  = request.args.get('year',  datetime.now(BERLIN).year, type=int)
    month = request.args.get('month', None, type=int)
    week  = request.args.get('week',  None, type=int)
    day   = request.args.get('day',   None)

    if granularity == 'year':
        start = date(year, 1, 1)
        end   = date(year + 1, 1, 1)
    elif granularity == 'month' and month:
        start = date(year, month, 1)
        end   = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    elif granularity == 'week' and week:
        iso   = date.fromisocalendar(year, week, 1)
        start = iso
        end   = iso + timedelta(days=7)
    elif granularity == 'day' and day:
        start = datetime.strptime(day, "%Y-%m-%d").date()
        end   = start + timedelta(days=1)
    else:
        start = date(datetime.now(BERLIN).year, 1, 1)
        end   = date(datetime.now(BERLIN).year + 1, 1, 1)

    period_loans = Verleihung.query.filter(
        Verleihung.start_time >= start,
        Verleihung.start_time < end
    )
    total_verleihungen = period_loans.count()
    total_hours = (
        db.session.query(func.sum(Verleihung.actual_duration))
        .filter(
            Verleihung.actual_duration != None,
            Verleihung.start_time >= start,
            Verleihung.start_time < end
        ).scalar() or 0
    )

    data = (
        db.session.query(Objekt.name, func.count(Verleihung.id).label('count'))
        .join(Verleihung, Verleihung.objekt_id == Objekt.id)
        .filter(Verleihung.start_time >= start, Verleihung.start_time < end)
        .group_by(Objekt.id).all()
    )
    labels = [row.name for row in data]
    counts = [row.count for row in data]

    top_users = (
        db.session.query(
            Ausleiher.first_name, Ausleiher.last_name,
            func.count(Verleihung.id).label('loan_count')
        )
        .join(Verleihung, Verleihung.ausleiher_id == Ausleiher.id)
        .filter(Verleihung.start_time >= start, Verleihung.start_time < end)
        .group_by(Ausleiher.id)
        .order_by(func.count(Verleihung.id).desc())
        .limit(10).all()
    )

    years = [y[0] for y in db.session
             .query(func.strftime('%Y', Verleihung.start_time))
             .distinct().order_by(func.strftime('%Y', Verleihung.start_time))
             .all()]
    if not years:
        years = [str(datetime.now(BERLIN).year)]

    # Default month/week/day für die UI
    if granularity == 'month' and not month:
        month = datetime.now(BERLIN).month
    if granularity == 'week' and not week:
        week = datetime.now(BERLIN).isocalendar()[1]
    if granularity == 'day' and not day:
        day = datetime.now(BERLIN).strftime('%Y-%m-%d')

    return render_template('statistik.html',
                           granularity=granularity, year=year, month=month,
                           week=week, day=day,
                           total_verleihungen=total_verleihungen,
                           total_hours=round(total_hours, 2),
                           labels=labels, counts=counts,
                           top_users=top_users,
                           years=years)

@app.route('/objekt_status')
def objekt_status():
    objekte = Objekt.query.order_by(Objekt.name).all()
    for obj in objekte:
        active_loan = Verleihung.query.filter_by(objekt_id=obj.id, status='Ausgeliehen').first()
        if active_loan:
            obj.status = "Ausgeliehen"
            obj.current_loan = active_loan
        else:
            obj.status = "Verfügbar"
            obj.current_loan = None
    return render_template('objekt_status.html', objekte=objekte)

# ── Debug / Backup ────────────────────────────────────────────────────────────

@app.route('/debug')
def debug():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    backups = sorted(
        glob.glob(os.path.join(BACKUP_DIR, '*.db')),
        key=os.path.getmtime
    )
    backup_names = [os.path.basename(b) for b in backups]
    return render_template('debug.html', backups=backup_names)

@app.route('/debug/backup', methods=['POST'])
def do_backup():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.now(BERLIN).strftime('%Y-%m-%d')
    dest = os.path.join(BACKUP_DIR, f'{timestamp} Backup Datenbank.db')
    try:
        shutil.copy2(DB_PATH, dest)
        flash(f'Backup erstellt: {os.path.basename(dest)}', 'success')
    except Exception as e:
        flash(f'Backup fehlgeschlagen: {e}', 'danger')
    return redirect(url_for('debug'))

@app.route('/debug/delete_oldest', methods=['POST'])
def delete_oldest_backup():
    backups = sorted(
        glob.glob(os.path.join(BACKUP_DIR, '*.db')),
        key=os.path.getmtime
    )
    if backups:
        try:
            os.remove(backups[0])
            flash(f'Ältestes Backup gelöscht: {os.path.basename(backups[0])}', 'success')
        except Exception as e:
            flash(f'Löschen fehlgeschlagen: {e}', 'danger')
    else:
        flash('Keine Backups vorhanden.', 'info')
    return redirect(url_for('debug'))

# ── Netzwerk / GUI ────────────────────────────────────────────────────────────

def get_local_ips():
    ips = []
    hostname = socket.gethostname()
    try:
        all_ips = socket.getaddrinfo(hostname, None, socket.AF_INET)
        for addr in all_ips:
            ip = addr[4][0]
            if ip != '127.0.0.1' and ip not in ips:
                ips.append(ip)
    except Exception as e:
        print(f"Error getting IPs: {e}")
    return ips if ips else ["127.0.0.1"]

def create_gui(ips, port):
    root = tk.Tk()
    root.title("Verleihsoftware – Selbsttest")
    root.configure(bg='white')
    root.geometry("520x420")

    try:
        if getattr(sys, 'frozen', False):
            icon_path = os.path.join(sys._MEIPASS, "icon.ico")
        else:
            icon_path = os.path.join(BASE_DIR, "icon.ico")
        root.iconbitmap(icon_path)
    except Exception:
        pass

    root.attributes('-topmost', True)

    tk.Label(root, text="Verleihsoftware – Systemcheck",
             font=("Segoe UI", 13, "bold"), bg='white').pack(pady=(16, 4))

    log = scrolledtext.ScrolledText(root, width=60, height=14,
                                    font=("Consolas", 9), state='disabled',
                                    bg='#f8f8f8', relief='flat', bd=1)
    log.pack(padx=16, pady=8, fill='both', expand=True)

    def append(color, text):
        log.config(state='normal')
        log.insert('end', text + '\n', color)
        log.tag_config('OK',    foreground='#2a7a2a')
        log.tag_config('INFO',  foreground='#0055aa')
        log.tag_config('FEHLER', foreground='#cc0000')
        log.see('end')
        log.config(state='disabled')

    results = run_selftest()
    all_ok = all(r[0] != 'FEHLER' for r in results)

    for status, msg in results:
        prefix = '✓' if status == 'OK' else ('ℹ' if status == 'INFO' else '✗')
        append(status, f"  {prefix}  {msg}")

    if all_ok:
        status_text = "✓  Alle Tests bestanden – System bereit"
        status_color = '#2a7a2a'
        ip_str = f"Erreichbar unter:  {', '.join(ips)}:{WEBSITE_PORT}"
    else:
        status_text = "✗  Es gab Fehler – bitte prüfen"
        status_color = '#cc0000'
        ip_str = ""

    if ip_str:
        tk.Label(root, text=ip_str, font=("Segoe UI", 9),
                 bg='white', fg='#555').pack(pady=2)

    btn_frame = tk.Frame(root, bg='white')
    btn_frame.pack(pady=12)

    def open_browser():
        import webbrowser
        webbrowser.open(f"http://{ips[0]}:{WEBSITE_PORT}")

    tk.Button(btn_frame, text="🌐 Webseite öffnen", command=open_browser,
              font=("Segoe UI", 10), padx=16, pady=6, bg='#0055aa', fg='white').pack(side='left', padx=6)

    tk.Button(btn_frame, text="Schließen", command=root.destroy,
              font=("Segoe UI", 10), padx=16, pady=6).pack(side='left', padx=6)

    root.mainloop()

    root.mainloop()

def run_flask_app():
    app.run(host='0.0.0.0', port=WEBSITE_PORT, debug=False, use_reloader=False)

if __name__ == '__main__':
    ips = get_local_ips()

    flask_thread = threading.Thread(target=run_flask_app, daemon=True)
    flask_thread.start()

    create_gui(ips, WEBSITE_PORT)