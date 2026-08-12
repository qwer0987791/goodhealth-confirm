import os, csv, io, secrets
from datetime import datetime, timezone, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, send_file, flash, Response
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))

database_url = os.environ.get('DATABASE_URL', 'sqlite:///confirm.db')
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

TZ = timezone(timedelta(hours=8))

def now_tw():
    return datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')

class Recipient(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), default='')
    note = db.Column(db.String(255), default='')
    token = db.Column(db.String(80), unique=True, nullable=False)
    confirmed = db.Column(db.Boolean, default=False, nullable=False)
    confirmed_at = db.Column(db.String(40))
    created_at = db.Column(db.String(40), nullable=False)

def check_auth(username, password):
    return username == os.environ.get('ADMIN_USER', 'admin') and password == os.environ.get('ADMIN_PASSWORD', 'change-me-now')

def authenticate():
    return Response('需要管理員登入', 401, {'WWW-Authenticate': 'Basic realm="Goodhealth Confirm Admin"'})

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return fn(*args, **kwargs)
    return wrapper

@app.before_request
def create_tables():
    db.create_all()

@app.route('/')
def home():
    return redirect(url_for('admin'))

@app.route('/admin')
@admin_required
def admin():
    rows = Recipient.query.order_by(Recipient.id.desc()).all()
    confirmed = sum(1 for r in rows if r.confirmed)
    return render_template('admin.html', rows=rows, total=len(rows), confirmed=confirmed, pending=len(rows)-confirmed)

@app.route('/add', methods=['POST'])
@admin_required
def add():
    name = request.form.get('name','').strip()
    if not name:
        flash('姓名不可空白')
        return redirect(url_for('admin'))
    person = Recipient(name=name, email=request.form.get('email','').strip(), note=request.form.get('note','').strip(), token=secrets.token_urlsafe(12), created_at=now_tw())
    db.session.add(person); db.session.commit()
    return redirect(url_for('admin'))

@app.route('/import', methods=['POST'])
@admin_required
def import_csv():
    file = request.files.get('file')
    if not file:
        flash('請選擇 CSV 檔案'); return redirect(url_for('admin'))
    content = file.stream.read().decode('utf-8-sig')
    reader = csv.DictReader(io.StringIO(content)); count = 0
    for row in reader:
        name = (row.get('name') or row.get('姓名') or '').strip()
        if not name: continue
        db.session.add(Recipient(name=name, email=(row.get('email') or row.get('Email') or row.get('信箱') or '').strip(), note=(row.get('note') or row.get('備註') or '').strip(), token=secrets.token_urlsafe(12), created_at=now_tw()))
        count += 1
    db.session.commit(); flash(f'已匯入 {count} 筆名單')
    return redirect(url_for('admin'))

@app.route('/c/<token>', methods=['GET','POST'])
def confirm(token):
    person = Recipient.query.filter_by(token=token).first_or_404()
    if request.method == 'POST' and not person.confirmed:
        person.confirmed = True; person.confirmed_at = now_tw(); db.session.commit()
    return render_template('confirm.html', person=person)

@app.route('/reset/<int:recipient_id>', methods=['POST'])
@admin_required
def reset(recipient_id):
    person = db.session.get(Recipient, recipient_id)
    if person:
        person.confirmed=False; person.confirmed_at=None; db.session.commit()
    return redirect(url_for('admin'))

@app.route('/delete/<int:recipient_id>', methods=['POST'])
@admin_required
def delete(recipient_id):
    person = db.session.get(Recipient, recipient_id)
    if person:
        db.session.delete(person); db.session.commit()
    return redirect(url_for('admin'))

@app.route('/export')
@admin_required
def export_csv():
    rows = Recipient.query.order_by(Recipient.id.asc()).all()
    output=io.StringIO(); w=csv.writer(output)
    w.writerow(['姓名','Email','備註','狀態','確認時間','專屬連結'])
    base=request.url_root.rstrip('/')
    for r in rows:
        w.writerow([r.name,r.email,r.note,'已確認' if r.confirmed else '未確認',r.confirmed_at or '',f'{base}/c/{r.token}'])
    data=io.BytesIO(output.getvalue().encode('utf-8-sig')); data.seek(0)
    return send_file(data,mimetype='text/csv',as_attachment=True,download_name='確認狀態.csv')

@app.route('/health')
def health(): return 'ok', 200

if __name__ == '__main__':
    with app.app_context(): db.create_all()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT',5000)))
