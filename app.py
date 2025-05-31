from flask import Flask, render_template, request, redirect, url_for, session, flash, make_response
import sqlite3, os, json, base64
import qrcode
from io import BytesIO
from openpyxl import Workbook
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['DATABASE'] = 'award_data.db'

# ---------- Database Setup ----------
def get_db():
    db = sqlite3.connect(app.config['DATABASE'])
    db.row_factory = sqlite3.Row
    return db

def init_db():
    with app.app_context():
        db = get_db()
        cursor = db.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS awards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                award_name TEXT NOT NULL,
                place TEXT NOT NULL,
                date TEXT NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS award_types (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                form_fields TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        if not cursor.execute("SELECT * FROM admin WHERE username='admin'").fetchone():
            hashed_pw = generate_password_hash('admin123')
            cursor.execute("INSERT INTO admin (username, password) VALUES (?, ?)", ('admin', hashed_pw))

        db.commit()
        db.close()

# ---------- Admin Login Required Decorator ----------
def admin_required(f):
    def wrap(*args, **kwargs):
        if 'admin_logged_in' not in session:
            flash("Please log in as admin", "warning")
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    wrap.__name__ = f.__name__
    return wrap

# ---------- Routes ----------
@app.route('/')
def index():
    return redirect(url_for('admin_login'))

@app.route('/thank-you')
def thank_you():
    return "Thank you! Your submission was successful."

# ---------- Admin ----------
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db = get_db()
        admin = db.execute("SELECT * FROM admin WHERE username = ?", (username,)).fetchone()
        db.close()
        if admin and check_password_hash(admin['password'], password):
            session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        flash("Invalid credentials", "danger")
    return render_template("admin_login.html")

@app.route('/admin/logout')
def admin_logout():
    session.clear()
    return redirect(url_for('admin_login'))

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    db = get_db()
    award_types = db.execute("SELECT * FROM award_types").fetchall()
    awards_data = []

    for award_type in award_types:
        submissions = db.execute(
            "SELECT * FROM awards WHERE award_name = ? ORDER BY created_at DESC",
            (award_type['name'],)
        ).fetchall()

        qr = qrcode.QRCode(box_size=6, border=2)
        submission_url = f"{request.url_root}submit/{award_type['id']}"
        qr.add_data(submission_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        img_io = BytesIO()
        img.save(img_io, 'PNG')
        img_io.seek(0)
        qr_base64 = base64.b64encode(img_io.read()).decode()

        awards_data.append({
            'award_type': award_type,
            'submissions': submissions,
            'qr_code': qr_base64,
            'submission_url': submission_url
        })

    db.close()
    return render_template('admin.html', awards_data=awards_data)

@app.route('/admin/award-types/create', methods=['GET', 'POST'])
@admin_required
def create_award_type():
    if request.method == 'POST':
        name = request.form['name']
        fields = []
        for i in range(len(request.form.getlist('field_name[]'))):
            fields.append({
                'name': request.form.getlist('field_name[]')[i],
                'type': request.form.getlist('field_type[]')[i],
                'required': request.form.getlist('field_required[]')[i] == 'on'
            })
        db = get_db()
        db.execute("INSERT INTO award_types (name, form_fields) VALUES (?, ?)", (name, json.dumps(fields)))
        db.commit()
        db.close()
        flash("Award type created successfully", "success")
        return redirect(url_for('admin_dashboard'))
    return render_template("create_award_type.html")

@app.route('/submit/<int:award_type_id>', methods=['GET', 'POST'])
def submit_award_type(award_type_id):
    db = get_db()
    award_type = db.execute("SELECT * FROM award_types WHERE id = ?", (award_type_id,)).fetchone()
    if not award_type:
        return "Award Type Not Found", 404

    fields = json.loads(award_type['form_fields'])

    if request.method == 'POST':
        data = {field['name']: request.form.get(field['name']) for field in fields}
        db.execute('''
            INSERT INTO awards (name, award_name, place, date, description)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            data.get('name', ''),
            award_type['name'],
            data.get('place', ''),
            data.get('date', ''),
            data.get('description', '')
        ))
        db.commit()
        db.close()
        return redirect(url_for('thank_you'))

    db.close()
    return render_template('dynamic_submit.html', award_type=award_type, fields=fields)

@app.route('/admin/export')
@admin_required
def export_data():
    db = get_db()
    awards = db.execute("SELECT * FROM awards").fetchall()
    db.close()

    wb = Workbook()
    ws = wb.active
    ws.title = "Award Winners"
    ws.append(["ID", "Name", "Award Name", "Place", "Date", "Description", "Submitted At"])

    for a in awards:
        ws.append([
            a['id'], a['name'], a['award_name'], a['place'], a['date'], a['description'], a['created_at']
        ])

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    response = make_response(output.read())
    response.headers["Content-Disposition"] = "attachment; filename=awards.xlsx"
    response.headers["Content-type"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return response

# ---------- Run ----------
if __name__ == "__main__":
    init_db()
    app.run(debug=True)
