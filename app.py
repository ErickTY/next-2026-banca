"""NEXT 2026 • aplicação de avaliação da arena.

Configuração: ADMIN_USERNAME, ADMIN_PASSWORD, SECRET_KEY e DATABASE_URL.
Banco persistente PostgreSQL exigido em produção; SQLite só para uso local.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, Response, session, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint, func
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix

TEAMS = [
    (1, 'GAVS-5', 'A22', True),
    (2, 'OutBox', 'A23', False),
    (3, 'Auditix AI', 'A24', False),
    (4, 'Next Level', 'A25', False),
    (5, 'DataKeeper', 'A26', False),
    (6, 'Gamma', 'A27', True),
    (7, 'JPPN Tech', 'A37', False),
    (8, 'VisionAI', 'A38', False),
    (9, 'Argus', 'A39', False),
]
DEFAULT_SECONDS = 300
PARTICIPANTS = ('A1', 'A2', 'A3', 'A4', 'D1', 'D2')
VALID_OBS = {'A1': {'correto', 'erro', 'nao_testado'},
             'A2': {'correto', 'erro', 'nao_testado'},
             'A3': {'correto', 'erro', 'nao_testado'},
             'A4': {'correto', 'erro', 'nao_testado'},
             'D1': {'alerta', 'falso_aceite', 'sem_leitura'},
             'D2': {'alerta', 'falso_aceite', 'sem_leitura'}}

def now():
    return datetime.now(timezone.utc)

def utc_epoch(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp() * 1000)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', '')
prod = (os.getenv('VERCEL', '').strip().lower() in ('true', '1', 'yes') or os.getenv('RENDER', '').strip().lower() in ('true', '1', 'yes') or bool(os.getenv('RENDER_EXTERNAL_HOSTNAME')))
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=prod,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    MAX_CONTENT_LENGTH=128 * 1024,
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
)
uri = os.getenv('DATABASE_URL', 'sqlite:///local.db')
if uri.startswith('postgres://'):
    uri = 'postgresql://' + uri[len('postgres://'):]
app.config['SQLALCHEMY_DATABASE_URI'] = uri
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True}
if prod:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
if prod and not app.config['SECRET_KEY']:
    raise RuntimeError('SECRET_KEY obrigatória em produção')
if prod and uri.startswith('sqlite'):
    raise RuntimeError('DATABASE_URL precisa ser PostgreSQL persistente em produção')
if prod and (not os.getenv('ADMIN_PASSWORD') or len(os.getenv('ADMIN_PASSWORD', '')) < 12 or os.getenv('ADMIN_PASSWORD') in ('SUBSTITUIR_POR_SENHA_FORTE', 'DEFINIR_NO_VERCEL')):
    raise RuntimeError('ADMIN_PASSWORD deve ser definida como variável de ambiente protegida no Vercel')
if not app.config['SECRET_KEY']:
    app.config['SECRET_KEY'] = 'DEV-ONLY-SET-SECRET-KEY-BEFORE-DEPLOY'

db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    display_name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(10), nullable=False, default='judge')
    active = db.Column(db.Boolean, nullable=False, default=True)
    failed_attempts = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime(timezone=True))

class Team(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    stand = db.Column(db.String(8), nullable=False)
    name_pending = db.Column(db.Boolean, nullable=False, default=False)
    locked = db.Column(db.Boolean, nullable=False, default=False)

class Timer(db.Model):
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), primary_key=True)
    status = db.Column(db.String(15), nullable=False, default='idle')
    started_at = db.Column(db.DateTime(timezone=True))
    elapsed_seconds = db.Column(db.Integer, nullable=False, default=0)
    duration_seconds = db.Column(db.Integer, nullable=False, default=DEFAULT_SECONDS)
    version = db.Column(db.Integer, nullable=False, default=0)

class Evaluation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    c1 = db.Column(db.Integer, nullable=False)
    c2 = db.Column(db.Integer, nullable=False)
    c3 = db.Column(db.Integer, nullable=False)
    cameras_available = db.Column(db.Integer)
    cameras_used = db.Column(db.Integer)
    observations_json = db.Column(db.Text, nullable=False)
    notes = db.Column(db.Text, nullable=False, default='')
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False)
    __table_args__ = (UniqueConstraint('team_id', 'user_id', name='uniq_evaluation_team_judge'),)

    @property
    def total(self):
        return self.c1 + self.c2 + self.c3

    @property
    def observations(self):
        return json.loads(self.observations_json)

class Log(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'))
    event = db.Column(db.String(64), nullable=False)
    detail = db.Column(db.Text, nullable=False, default='')
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now)

def log_event(event, team_id=None, detail=''):
    db.session.add(Log(user_id=session.get('uid'), team_id=team_id, event=event, detail=detail[:2000]))

def bootstrap():
    db.create_all()
    for group, name, stand, pending in TEAMS:
        if not db.session.get(Team, group):
            db.session.add(Team(id=group, name=name, stand=stand, name_pending=pending))
        if not db.session.get(Timer, group):
            db.session.add(Timer(team_id=group))
    admin_name = os.getenv('ADMIN_USERNAME', 'coordenacao').strip().lower()
    admin_pass = os.getenv('ADMIN_PASSWORD')
    if admin_pass and not User.query.filter_by(role='admin').first():
        db.session.add(User(username=admin_name, display_name='Coordenação', role='admin', password_hash=generate_password_hash(admin_pass)))
    db.session.commit()

with app.app_context():
    bootstrap()

@app.before_request
def csrf_protection():
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
        if not token or not secrets.compare_digest(str(token), str(session.get('csrf_token', ''))):
            abort(400, description='Formulário expirado. Atualize a página.')

@app.after_request
def security_headers(resp):
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['X-Frame-Options'] = 'DENY'
    resp.headers['Referrer-Policy'] = 'same-origin'
    resp.headers['Cache-Control'] = 'no-store'
    resp.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
    return resp

@app.context_processor
def shared():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_urlsafe(32)
    return {'csrf_token': session['csrf_token'], 'current_user': db.session.get(User, session.get('uid')) if session.get('uid') else None}

def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        u = db.session.get(User, session['uid']) if session.get('uid') else None
        if not u or not u.active:
            session.clear()
            return redirect(url_for('login'))
        return fn(*args, **kwargs)
    return wrapped

def admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapped(*args, **kwargs):
        if db.session.get(User, session['uid']).role != 'admin':
            abort(403)
        return fn(*args, **kwargs)
    return wrapped

def get_team(group):
    return db.get_or_404(Team, group)

def get_timer(group):
    timer = db.session.get(Timer, group)
    if timer is None:
        abort(404)
    return timer

def consumed(timer):
    amount = timer.elapsed_seconds
    if timer.status == 'running' and timer.started_at:
        diff = (now() - (timer.started_at if timer.started_at.tzinfo else timer.started_at.replace(tzinfo=timezone.utc))).total_seconds()
        amount += max(0, int(diff))
    return amount

def timer_view(timer):
    return {'status': timer.status,
            'elapsed': timer.elapsed_seconds,
            'duration': timer.duration_seconds,
            'started_at': utc_epoch(timer.started_at),
            'server_now': utc_epoch(now()),
            'version': timer.version}

@app.get('/health')
def health():
    return jsonify(ok=True)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        name = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '')
        u = User.query.filter_by(username=name).first()
        locked = u and u.locked_until and (u.locked_until.replace(tzinfo=timezone.utc) if not u.locked_until.tzinfo else u.locked_until) > now()
        valid = u and u.active and not locked and check_password_hash(u.password_hash, password)
        if not valid:
            if u and not locked:
                u.failed_attempts += 1
                if u.failed_attempts >= 5:
                    u.locked_until = now() + timedelta(minutes=10)
                    u.failed_attempts = 0
                db.session.commit()
            flash('Credenciais inválidas ou conta temporariamente bloqueada.', 'error')
            return render_template('login.html'), 401
        u.failed_attempts = 0
        u.locked_until = None
        db.session.commit()
        session.clear()
        session['uid'] = u.id
        session['csrf_token'] = secrets.token_urlsafe(32)
        session.permanent = True
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.post('/logout')
@login_required
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.get('/')
def root():
    return redirect(url_for('dashboard') if session.get('uid') else url_for('login'))

@app.get('/dashboard')
@login_required
def dashboard():
    teams = Team.query.order_by(Team.id).all()
    rows = []
    for t in teams:
        evaluations = Evaluation.query.filter_by(team_id=t.id).all()
        scores = [e.total for e in evaluations]
        rows.append({'team': t, 'timer': timer_view(get_timer(t.id)),
                     'count': len(scores), 'average': round(sum(scores) / len(scores), 2) if scores else None,
                     'own': next((e for e in evaluations if e.user_id == session['uid']), None)})
    judges = User.query.filter_by(role='judge', active=True).order_by(User.display_name).all()
    return render_template('dashboard.html', rows=rows, judges=judges, user= db.session.get(User, session['uid']))

@app.route('/evaluate/<int:group>', methods=['GET', 'POST'])
@login_required
def evaluate(group):
    t = get_team(group)
    user = db.session.get(User, session['uid'])
    existing = Evaluation.query.filter_by(team_id=group, user_id=user.id).first()
    if request.method == 'POST':
        if t.locked:
            abort(403, description='Avaliação bloqueada pela coordenação')
        try:
            pts = [int(request.form.get(f'c{i}', '-1')) for i in (1, 2, 3)]
            available = int(request.form.get('available', '-1'))
            used = int(request.form.get('used', '-1'))
        except ValueError:
            abort(400)
        if not all(0 <= p <= 5 for p in pts) or not 1 <= used <= available <= 2:
            flash('Notas devem ser de 0 a 5; escolha uma ou duas câmeras e não mais que o disponível.', 'error')
            return redirect(url_for('evaluate', group=group))
        obs = {k: request.form.get(k, 'nao_testado' if k.startswith('A') else 'sem_leitura') for k in PARTICIPANTS}
        if any(obs[k] not in VALID_OBS[k] for k in PARTICIPANTS):
            abort(400, description='Resultado inválido de participante')
        notes = request.form.get('notes', '').strip()[:3000]
        if (any(v in ('erro','falso_aceite','sem_leitura','nao_testado') for v in obs.values()) or min(pts) <= 2) and len(notes) < 10:
            flash('Descreva as falhas ou testes não realizados em pelo menos 10 caracteres.', 'error')
            return redirect(url_for('evaluate', group=group))
        if existing is None:
            existing = Evaluation(team_id=group, user_id=user.id)
            db.session.add(existing)
        existing.c1, existing.c2, existing.c3 = pts
        existing.cameras_available, existing.cameras_used = available, used
        existing.observations_json = json.dumps(obs)
        existing.notes = notes
        existing.updated_at = now()
        log_event('evaluation_saved', group, f'c1={pts[0]};c2={pts[1]};c3={pts[2]};used={used}')
        db.session.commit()
        flash('Avaliação registrada com sucesso. É possível editá-la até o bloqueio da equipe.', 'success')
        return redirect(url_for('dashboard'))
    current_obs = existing.observations if existing else {}
    return render_template('evaluate.html', team=t, evaluation=existing, obs=current_obs, timer=timer_view(get_timer(group)), participants=PARTICIPANTS)

@app.get('/api/state')
@login_required
def api_state():
    timers = {str(t.team_id): timer_view(t) for t in Timer.query.order_by(Timer.team_id).all()}
    return jsonify(timers=timers, now=utc_epoch(now()))

@app.post('/admin/timers/<int:group>/<action>')
@admin_required
def update_timer(group, action):
    get_team(group)
    if action not in ('start', 'pause', 'resume', 'finish', 'reset', 'extend'):
        abort(404)
    # Pessimistic row lock in PostgreSQL to avoid simultaneous timer actions.
    t = db.session.query(Timer).filter_by(team_id=group).with_for_update().one()
    old = t.status
    if action == 'start' and old == 'idle':
        t.elapsed_seconds = 0
        t.started_at = now()
        t.status = 'running'
    elif action == 'resume' and old == 'paused':
        t.started_at = now()
        t.status = 'running'
    elif action == 'pause' and old == 'running':
        t.elapsed_seconds = consumed(t)
        t.started_at = None
        t.status = 'paused'
    elif action == 'finish' and old in ('running', 'paused'):
        t.elapsed_seconds = consumed(t)
        t.started_at = None
        t.status = 'finished'
    elif action == 'reset':
        reason = request.form.get('reason', '').strip()
        if len(reason) < 10:
            flash('Para zerar, informe a justificativa (mínimo 10 caracteres).', 'error')
            return redirect(url_for('dashboard'))
        t.started_at = None
        t.elapsed_seconds = 0
        t.duration_seconds = DEFAULT_SECONDS
        t.status = 'idle'
    elif action == 'extend':
        reason = request.form.get('reason', '').strip()
        if len(reason) < 10:
            flash('Justifique o minuto adicional (mínimo 10 caracteres).', 'error')
            return redirect(url_for('dashboard'))
        t.duration_seconds += 60
    else:
        flash('Ação incompatível com a etapa atual do cronômetro.', 'error')
        return redirect(url_for('dashboard'))
    t.version += 1
    log_event('timer_' + action, group, f'{old}->{t.status}; duração={t.duration_seconds}; motivo={request.form.get("reason", "")[:400]}')
    db.session.commit()
    flash(f'Cronômetro do Grupo {group}: {action}.', 'success')
    return redirect(url_for('dashboard'))

@app.post('/admin/teams/<int:group>/edit')
@admin_required
def edit_team(group):
    t = get_team(group)
    name = request.form.get('name', '').strip()
    if not 2 <= len(name) <= 120:
        abort(400)
    t.name = name
    t.name_pending = False
    log_event('team_name_confirmed', group, name)
    db.session.commit()
    flash('Nome atualizado.', 'success')
    return redirect(url_for('dashboard'))

@app.post('/admin/teams/<int:group>/lock')
@admin_required
def lock_team(group):
    t = get_team(group)
    t.locked = not t.locked
    log_event('team_lock_changed', group, f'locked={t.locked}')
    db.session.commit()
    flash('Situação de bloqueio atualizada.', 'success')
    return redirect(url_for('dashboard'))

@app.post('/admin/judges')
@admin_required
def add_judge():
    name = request.form.get('display_name', '').strip()
    username = request.form.get('username', '').strip().lower()
    if not 2 <= len(name) <= 120 or not re.fullmatch(r'[a-z0-9._-]{3,40}', username):
        flash('Informe nome e identificador de 3 a 40 caracteres (a-z, 0-9, ponto, hífen ou _).', 'error')
        return redirect(url_for('dashboard'))
    password = secrets.token_urlsafe(15)
    try:
        db.session.add(User(username=username, display_name=name, role='judge', password_hash=generate_password_hash(password)))
        log_event('judge_created', detail=username)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash('Esse identificador já está cadastrado.', 'error')
        return redirect(url_for('dashboard'))
    return render_template('judge_created.html', name=name, username=username, password=password)

@app.post('/admin/judges/<int:uid>/reset')
@admin_required
def reset_judge(uid):
    u = db.get_or_404(User, uid)
    if u.role != 'judge':
        abort(403)
    password = secrets.token_urlsafe(15)
    u.password_hash = generate_password_hash(password)
    u.failed_attempts = 0
    u.locked_until = None
    log_event('judge_password_reset', detail=u.username)
    db.session.commit()
    return render_template('judge_created.html', name=u.display_name, username=u.username, password=password)

@app.get('/admin/export.csv')
@admin_required
def export_csv():
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['grupo','equipe','estande','avaliador','usuario','c1','c2','c3','total','cameras_disponiveis','cameras_usadas','A1','A2','A3','A4','D1','D2','observacoes','atualizado_em_utc'])
    query = db.session.query(Evaluation, Team, User).join(Team, Team.id == Evaluation.team_id).join(User, User.id == Evaluation.user_id).order_by(Team.id, User.display_name)
    for e,t,u in query.all():
        obs = e.observations
        writer.writerow([t.id, t.name, t.stand, u.display_name, u.username, e.c1, e.c2, e.c3, e.total, e.cameras_available,e.cameras_used,*[obs.get(k,'') for k in PARTICIPANTS],e.notes,e.updated_at.isoformat()])
    csv_data = '\ufeff' + output.getvalue()
    return Response(csv_data, mimetype='text/csv; charset=utf-8', headers={'Content-Disposition': 'attachment; filename=NEXT_2026_Avaliacoes_Arena.csv'})

@app.get('/admin/audit.csv')
@admin_required
def audit_csv():
    output=io.StringIO()
    writer=csv.writer(output,delimiter=';')
    writer.writerow(['timestamp_utc','user_id','group_id','evento','detalhe'])
    for log in Log.query.order_by(Log.id).all():
        writer.writerow([log.created_at.isoformat(),log.user_id,log.team_id,log.event,log.detail])
    return Response('\ufeff'+output.getvalue(), mimetype='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename=NEXT_2026_Auditoria.csv'})

if __name__ == '__main__':
    app.run(debug=not prod, host='127.0.0.1', port=int(os.getenv('PORT', '5000')))
