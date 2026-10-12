"""NEXT 2026 • Banca avaliadora via Supabase Data API (sem DATABASE_URL).
As chaves Supabase ficam EXCLUSIVAMENTE no servidor Vercel.
As tabelas e funções são criadas pelo script supabase/schema.sql.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import Flask, Response, abort, flash, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix

log = logging.getLogger("next2026")

TEAMS = [(1, "Datacore", "A22", False), (2, "OutBox", "A23", False),
         (3, "Auditix AI", "A24", False), (4, "Next Level", "A25", False),
         (5, "DataKeeper", "A26", False), (6, "Gamma", "A27", True),
         (7, "JPPN Tech", "A37", False), (8, "VisionAI", "A38", False),
         (9, "Argus", "A39", False)]
PARTICIPANTS = ("A1", "A2", "A3", "A4", "D1", "D2")
VALID_OBS = {
    **{x: {"correto", "erro", "nao_testado"} for x in PARTICIPANTS[:4]},
    **{x: {"alerta", "falso_aceite", "sem_leitura"} for x in PARTICIPANTS[4:]}
}

def now():
    return datetime.now(timezone.utc)

def parse_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    value = str(value).replace("Z", "+00:00")
    d = datetime.fromisoformat(value)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)

def milliseconds(value):
    d = parse_dt(value)
    return int(d.timestamp() * 1000) if d else None

def record(row):
    if row is None:
        return None
    obj = dict(row)
    if "observacoes" in obj:
        obj["observations"] = obj.pop("observacoes")
    if "updated_at" in obj:
        obj["updated_at"] = parse_dt(obj["updated_at"])
    if "cameras_disponiveis" in obj:
        obj["cameras_available"] = obj["cameras_disponiveis"]
    if "cameras_usadas" in obj:
        obj["cameras_used"] = obj["cameras_usadas"]
    if "name_pending" not in obj and "nome_pendente" in obj:
        obj["name_pending"] = obj["nome_pendente"]
    if "locked" not in obj and "bloqueado" in obj:
        obj["locked"] = obj["bloqueado"]
    if "name" not in obj and "nome" in obj:
        obj["name"] = obj["nome"]
    if "stand" not in obj and "estande" in obj:
        obj["stand"] = obj["estande"]
    if "display_name" not in obj and "nome_exibicao" in obj:
        obj["display_name"] = obj["nome_exibicao"]
    if "password_hash" not in obj and "senha_hash" in obj:
        obj["password_hash"] = obj["senha_hash"]
    if "role" not in obj and "papel" in obj:
        obj["role"] = obj["papel"]
    if "active" not in obj and "ativo" in obj:
        obj["active"] = obj["ativo"]
    if "failed_attempts" not in obj and "falhas_login" in obj:
        obj["failed_attempts"] = obj["falhas_login"]
    if "locked_until" not in obj and "bloqueado_ate" in obj:
        obj["locked_until"] = parse_dt(obj["bloqueado_ate"])
    if "team_id" not in obj and "equipe_id" in obj:
        obj["team_id"] = obj["equipe_id"]
    if "user_id" not in obj and "usuario_id" in obj:
        obj["user_id"] = obj["usuario_id"]
    if "started_at" not in obj and "iniciado_em" in obj:
        obj["started_at"] = obj["iniciado_em"]
    if "elapsed_seconds" not in obj and "segundos_decorridos" in obj:
        obj["elapsed_seconds"] = obj["segundos_decorridos"]
    if "duration_seconds" not in obj and "duracao_segundos" in obj:
        obj["duration_seconds"] = obj["duracao_segundos"]
    if "status" not in obj and "estado" in obj:
        obj["status"] = obj["estado"]
    if "version" not in obj and "versao" in obj:
        obj["version"] = obj["versao"]
    return SimpleNamespace(**obj)

def score(ev):
    return ev.c1 + ev.c2 + ev.c3

class SupabaseError(Exception):
    def __init__(self, message, status=503):
        super().__init__(message)
        self.status = status

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_KEY = (os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()

def config_issue():
    if not SUPABASE_URL.startswith("https://") or not SUPABASE_URL.endswith(".supabase.co"):
        return "SUPABASE_URL não configurada corretamente"
    if not SUPABASE_KEY:
        return "SUPABASE_SECRET_KEY não configurada"
    if len(os.getenv("SECRET_KEY", "")) < 32:
        return "SECRET_KEY deve ter pelo menos 32 caracteres"
    # ADMIN_PASSWORD é usada apenas para criar a primeira conta; senhas já
    # cadastradas são validadas exclusivamente pelo hash salvo no Supabase.
    return None

def call(method, path, params=None, payload=None, prefer=None):
    """Chamadas privadas à Data API; nunca entregue a chave ao navegador."""
    issue = config_issue()
    if issue:
        raise SupabaseError("Configuração incompleta: " + issue)
    url = SUPABASE_URL + "/rest/v1/" + path
    if params:
        url += "?" + urlencode(params, doseq=True)
    headers = {"apikey": SUPABASE_KEY, "Accept": "application/json"}
    if SUPABASE_KEY.count(".") == 2:  # service_role JWT legado
        headers["Authorization"] = "Bearer " + SUPABASE_KEY
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if prefer:
        headers["Prefer"] = prefer
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = Request(url, data=body, method=method, headers=headers)
    try:
        with urlopen(req, timeout=12) as res:
            raw = res.read()
            return json.loads(raw) if raw else None
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8", "replace"))
            code = detail.get("code", "") if isinstance(detail, dict) else ""
        except Exception:
            code = ""
        log.error("Supabase REST %s %s: HTTP %s code=%s", method, path, exc.code, code)
        if exc.code in (401, 403):
            raise SupabaseError("Chave Supabase inválida ou sem permissão")
        if exc.code == 404 or code in ("42P01", "PGRST205", "PGRST202"):
            raise SupabaseError("Estrutura Supabase ausente: execute supabase/schema.sql no SQL Editor")
        if exc.code == 409:
            raise SupabaseError("Registro em conflito", 409)
        raise SupabaseError("Falha no acesso ao Supabase (HTTP %d; %s)" % (exc.code, code))
    except (URLError, TimeoutError) as exc:
        log.error("Conexão Supabase indisponível: %s", type(exc).__name__)
        raise SupabaseError("Não foi possível conectar à API do Supabase")

def select(table, filters=None, order=None, limit=1000, offset=0):
    p = {"select": "*", "limit": str(limit), "offset": str(offset)}
    p.update(filters or {})
    if order:
        p["order"] = order
    return call("GET", table, params=p) or []

def all_rows(table, order=None):
    rows = []
    while True:
        batch = select(table, order=order, offset=len(rows))
        rows.extend(batch)
        if len(batch) < 1000:
            return rows

def one(table, **filters):
    p = {k: "eq." + str(v) for k, v in filters.items()}
    items = select(table, p, limit=1)
    return record(items[0]) if items else None

def insert(table, values, on_conflict=None):
    params = {"on_conflict": on_conflict} if on_conflict else None
    pref = "resolution=merge-duplicates,return=representation" if on_conflict else "return=representation"
    data = call("POST", table, params=params, payload=values, prefer=pref)
    return record(data[0]) if isinstance(data, list) and data else None

def patch(table, values, **filters):
    return call("PATCH", table, params={k: "eq." + str(v) for k,v in filters.items()}, payload=values, prefer="return=minimal")

def rpc(name, payload):
    return call("POST", "rpc/" + name, payload=payload)

def log_event(event, team_id=None, detail=""):
    insert("banca_auditoria", {
        "usuario_id": session.get("uid"),
        "equipe_id": team_id,
        "evento": event,
        "detalhe": detail[:2000]
    })

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY") or secrets.token_hex(32)
PROD = os.getenv("VERCEL", "").lower() in ("1", "true", "yes")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=PROD, PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    MAX_CONTENT_LENGTH=128 * 1024
)
if PROD:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

@app.errorhandler(SupabaseError)
def api_error(exc):
    log.error("Falha do serviço da banca: %s", exc)
    return (
        '<!doctype html><html lang="pt-BR"><meta charset="utf-8">'
        '<title>Configuração NEXT 2026</title><body style="font:16px sans-serif;max-width:700px;margin:10vh auto">'
        '<h1>O sistema da banca ainda não está pronto</h1>'
        '<p>Verifique as variáveis do Vercel e execute o arquivo <code>supabase/schema.sql</code> '
        'no SQL Editor do projeto Supabase.</p>'
        '<p>Detalhe: %s</p></body></html>' % __import__("html").escape(str(exc)), 503
    )

@app.before_request
def csrf_protection():
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        if not token or not secrets.compare_digest(str(token), str(session.get("csrf_token", ""))):
            abort(400, description="Formulário expirado. Atualize a página.")

@app.after_request
def security_headers(res):
    res.headers["X-Content-Type-Options"] = "nosniff"
    res.headers["X-Frame-Options"] = "DENY"
    res.headers["Referrer-Policy"] = "same-origin"
    res.headers["Cache-Control"] = "no-store"
    res.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; "
        "script-src 'self'; connect-src 'self'; base-uri 'self'; "
        "form-action 'self'; frame-ancestors 'none'"
    )
    return res

def get_user():
    # Consulta apenas uma vez por requisição, evitando atrasos nos comandos.
    if not hasattr(g, "_next_user"):
        uid = session.get("uid")
        g._next_user = one("banca_usuarios", id=uid) if uid else None
    return g._next_user

@app.context_processor
def shared():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return {"csrf_token": session["csrf_token"], "current_user": get_user()}

def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        u = get_user()
        if not u or not u.active:
            session.clear()
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapped

def admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapped(*args, **kwargs):
        if get_user().role != "admin":
            abort(403)
        return fn(*args, **kwargs)
    return wrapped

def get_team(group):
    team = one("banca_equipes", id=group)
    if not team:
        abort(404)
    return team

def get_timer(group):
    timer = one("banca_temporizadores", equipe_id=group)
    if not timer:
        abort(404)
    return timer

def timer_view(t):
    return {"status": t.status, "elapsed": t.elapsed_seconds,
            "duration": t.duration_seconds, "started_at": milliseconds(t.started_at),
            "server_now": milliseconds(now()), "version": t.version}

def fast_password(length=10):
    """Senha individual fácil de digitar: 10 caracteres, sem símbolos ambíguos.

    Alfabeto de 30 caracteres, aproximadamente 49 bits de entropia e
    bloqueio temporário após cinco tentativas de login malsucedidas.
    """
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))

def init_admin():
    if one("banca_usuarios", papel="admin"):
        return
    username = os.getenv("ADMIN_USERNAME", "coordenacao").strip().lower()
    password = os.getenv("ADMIN_PASSWORD", "")
    if len(password) < 12:
        raise SupabaseError("ADMIN_PASSWORD deve ter pelo menos 12 caracteres")
    try:
        insert("banca_usuarios", {
            "username": username, "nome_exibicao": "Coordenação", "papel": "admin",
            "senha_hash": generate_password_hash(password)
        })
    except SupabaseError as exc:
        if exc.status != 409 or not one("banca_usuarios", papel="admin"):
            raise

@app.get("/health")
def health():
    issue = config_issue()
    if issue:
        return jsonify(ok=False, setup_required=True, reason=issue), 503
    try:
        select("banca_equipes", limit=1)
        return jsonify(ok=True, backend="supabase-rest")
    except SupabaseError as exc:
        return jsonify(ok=False, setup_required=True, reason=str(exc)), 503

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        init_admin()
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        u = one("banca_usuarios", username=username)
        locked = u and u.locked_until and u.locked_until > now()
        valid = u and u.active and not locked and check_password_hash(u.password_hash, password)
        if not valid:
            if u and not locked:
                fail = int(u.failed_attempts) + 1
                values = {"falhas_login": 0, "bloqueado_ate": (now()+timedelta(minutes=10)).isoformat()} if fail>=5 else {"falhas_login": fail}
                patch("banca_usuarios", values, id=u.id)
            flash("Credenciais inválidas ou conta temporariamente bloqueada.", "error")
            return render_template("login.html"), 401
        patch("banca_usuarios", {"falhas_login": 0, "bloqueado_ate": None}, id=u.id)
        session.clear()
        session["uid"] = u.id
        session["csrf_token"] = secrets.token_urlsafe(32)
        session.permanent = True
        return redirect(url_for("dashboard"))
    return render_template("login.html")

@app.post("/logout")
@login_required
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.get("/")
def root():
    return redirect(url_for("dashboard") if session.get("uid") else url_for("login"))

@app.get("/dashboard")
@login_required
def dashboard():
    user = get_user()
    teams = [record(x) for x in select("banca_equipes", order="id.asc")]
    timers = {x["equipe_id"]: record(x) for x in select("banca_temporizadores")}
    evaluations = [record(x) for x in all_rows("banca_avaliacoes")]
    judges = [record(x) for x in select("banca_usuarios", {"papel":"eq.judge","ativo":"eq.true"}, order="nome_exibicao.asc")]
    rows = []
    for t in teams:
        scores = [score(e) for e in evaluations if e.team_id == t.id]
        own = next((e for e in evaluations if e.team_id == t.id and e.user_id == user.id), None)
        if own:
            own.total = score(own)
        rows.append({"team":t, "timer":timer_view(timers[t.id]), "count":len(scores),
                     "average": round(sum(scores)/len(scores),2) if scores else None, "own":own})
    return render_template("dashboard.html", rows=rows, judges=judges, user=user)


def build_ranking():
    """Classificação provisória por média total / 15, com empates reais.

    Equipes sem avaliações ficam no fim, sem posição. Grupos empatados
    recebem a mesma posição; sem critério de desempate artificial.
    """
    teams = [record(t) for t in select("banca_equipes", order="id.asc")]
    evaluations = all_rows("banca_avaliacoes")
    active_judges = select("banca_usuarios", {"papel": "eq.judge", "ativo": "eq.true"})
    expected = len(active_judges)
    votes = {}
    for e in evaluations:
        votes.setdefault(e["equipe_id"], []).append(e)

    rows = []
    for t in teams:
        group = votes.get(t.id, [])
        count = len(group)
        total = sum(e["c1"] + e["c2"] + e["c3"] for e in group)
        sums = [sum(e[f"c{i}"] for e in group) for i in (1, 2, 3)]
        rows.append({
            "team_id": t.id, "name": t.name, "stand": t.stand,
            "rank": None,
            "evaluations": count,
            "expected": expected,
            "average": round(total / count, 2) if count else None,
            "c1_average": round(sums[0] / count, 2) if count else None,
            "c2_average": round(sums[1] / count, 2) if count else None,
            "c3_average": round(sums[2] / count, 2) if count else None,
            "locked": bool(t.locked),
            "complete": count > 0 and (expected > 0 and count >= expected),
            "_sum": total
        })

    # Comparison by cross-multiplication below avoids floating point ties.
    rows.sort(key=lambda r: (not bool(r["evaluations"]),
                            -(r["_sum"] / r["evaluations"]) if r["evaluations"] else 0,
                            r["team_id"]))
    last_scored = None
    last_rank = None
    for position, row in enumerate(rows, 1):
        if row["evaluations"]:
            if last_scored is None or row["_sum"] * last_scored["evaluations"] != last_scored["_sum"] * row["evaluations"]:
                last_rank = position
            row["rank"] = last_rank
            last_scored = row
        del row["_sum"]

    return {"ranking": rows, "expected_judges": expected,
            "updated_at": now().isoformat()}

@app.get("/admin/results")
@admin_required
def results_dashboard():
    return render_template("results.html", **build_ranking())

@app.get("/api/results")
@admin_required
def api_results():
    result = build_ranking()
    response = jsonify(result)
    response.headers["Cache-Control"] = "no-store, private"
    return response

@app.route("/evaluate/<int:group>", methods=["GET", "POST"])
@login_required
def evaluate(group):
    t = get_team(group)
    user = get_user()
    async_request = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    def invalid(message):
        if async_request:
            return jsonify(ok=False, error=message), 400
        flash(message, "error")
        return redirect(url_for("evaluate", group=group))

    if request.method == "POST":
        if t.locked:
            return invalid("Edição bloqueada pela coordenação.")
        try:
            scores = [int(request.form.get("c%d" % i, "-1")) for i in (1, 2, 3)]
            available = int(request.form.get("available", "-1"))
            used = int(request.form.get("used", "-1"))
        except (ValueError, TypeError):
            return invalid("Preencha as três notas e a quantidade de câmeras.")
        if not all(0 <= x <= 5 for x in scores):
            return invalid("Cada nota deve estar entre 0 e 5.")
        if not (1 <= used <= available <= 2):
            return invalid("As câmeras utilizadas não podem exceder as disponíveis.")

        # Não presumir detecção correta nem teste concluído: cada resultado
        # deve ser selecionado explicitamente pelo avaliador.
        obs = {k: request.form.get(k) for k in PARTICIPANTS}
        if any(obs[k] not in VALID_OBS[k] for k in PARTICIPANTS):
            return invalid("Marque o resultado de todos os seis participantes.")

        notes = request.form.get("notes", "").strip()[:3000]
        problems = any(
            v in ("erro", "falso_aceite", "sem_leitura", "nao_testado")
            for v in obs.values()
        ) or min(scores) <= 2
        if problems and len(notes) < 10:
            return invalid("Explique em pelo menos 10 caracteres as falhas ou testes não realizados.")

        try:
            rpc("banca_salvar_avaliacao", {
                "p_equipe": group, "p_usuario": user.id, "p_c1": scores[0],
                "p_c2": scores[1], "p_c3": scores[2], "p_disponiveis": available,
                "p_usadas": used, "p_obs": obs, "p_notas": notes
            })
        except SupabaseError:
            if async_request:
                return jsonify(ok=False, error="Não foi possível registrar a nota no Supabase. Tente novamente."), 503
            raise

        if async_request:
            return jsonify(ok=True, team=group, total=sum(scores),
                           saved_at=now().isoformat())
        flash("Avaliação registrada.", "success")
        return redirect(url_for("dashboard"))

    existing = one("banca_avaliacoes", equipe_id=group, usuario_id=user.id)
    if existing:
        existing.total = score(existing)
    return render_template("evaluate.html", team=t, evaluation=existing,
                           obs=existing.observations if existing else {},
                           timer=timer_view(get_timer(group)), participants=PARTICIPANTS)


@app.get("/api/state")
@login_required
def api_state():
    timers = {str(row["equipe_id"]):timer_view(record(row)) for row in select("banca_temporizadores")}
    return jsonify(timers=timers, now=milliseconds(now()))

@app.post("/admin/timers/<int:group>/<action>")
@admin_required
def update_timer(group, action):
    # Evita a consulta remota de equipe: a RPC valida e bloqueia a linha
    # no banco, e a competição tem precisamente os nove grupos.
    if group not in range(1, 10) or action not in ("start", "pause", "resume", "finish", "reset", "extend"):
        abort(404)
    async_request = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    reason = request.form.get("reason", "").strip()
    if action in ("reset", "extend") and len(reason) < 10:
        if async_request:
            return jsonify(ok=False, error="Motivo obrigatório (mínimo 10 caracteres)."), 400
        return redirect(url_for("dashboard"))
    try:
        result = rpc("banca_operar_tempo", {
            "p_equipe": group, "p_acao": action, "p_usuario": get_user().id,
            "p_motivo": reason[:400]
        })
    except SupabaseError as exc:
        if async_request:
            return jsonify(ok=False, error="Falha ao sincronizar o cronômetro. Tente novamente."), 503
        return redirect(url_for("dashboard"))
    if async_request:
        return jsonify(ok=True, team=group, action=action, result=result)
    return redirect(url_for("dashboard"))

@app.post("/admin/teams/<int:group>/edit")
@admin_required
def edit_team(group):
    get_team(group)
    name = request.form.get("name","").strip()
    if not 2 <= len(name) <= 120:
        abort(400)
    patch("banca_equipes", {"nome":name,"nome_pendente":False}, id=group)
    log_event("team_name_confirmed", group, name)
    flash("Nome oficial atualizado.", "success")
    return redirect(url_for("dashboard"))

@app.post("/admin/teams/<int:group>/lock")
@admin_required
def lock_team(group):
    t = get_team(group)
    patch("banca_equipes", {"bloqueado":not t.locked}, id=group)
    log_event("team_lock_changed", group, "locked=%s" % (not t.locked))
    flash("Bloqueio de fichas atualizado.", "success")
    return redirect(url_for("dashboard"))

@app.post("/admin/judges")
@admin_required
def add_judge():
    name = request.form.get("display_name","").strip()
    username = request.form.get("username","").strip().lower()
    if not 2 <= len(name) <= 120 or not re.fullmatch(r"[a-z0-9._-]{3,40}", username):
        flash("Identificador deve conter de 3 a 40 caracteres simples.", "error")
        return redirect(url_for("dashboard"))
    password = fast_password()
    try:
        insert("banca_usuarios", {
            "username":username, "nome_exibicao":name, "papel":"judge",
            "senha_hash":generate_password_hash(password)
        })
        log_event("judge_created", detail=username)
    except SupabaseError as exc:
        flash("Não foi possível criar acesso: " + str(exc), "error")
        return redirect(url_for("dashboard"))
    return render_template("judge_created.html", name=name, username=username, password=password)

@app.post("/admin/judges/<int:uid>/reset")
@admin_required
def reset_judge(uid):
    u = one("banca_usuarios", id=uid)
    if not u:
        abort(404)
    if u.role!="judge":
        abort(403)
    password = fast_password()
    patch("banca_usuarios", {"senha_hash":generate_password_hash(password),
                          "falhas_login":0,"bloqueado_ate":None}, id=uid)
    log_event("judge_password_reset", detail=u.username)
    return render_template("judge_created.html", name=u.display_name, username=u.username, password=password)

@app.get("/admin/export.csv")
@admin_required
def export_csv():
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["grupo","equipe","estande","avaliador","usuario","c1","c2","c3",
                    "total","cameras_disponiveis","cameras_usadas","A1","A2","A3","A4",
                    "D1","D2","observacoes","atualizado_em_utc"])
    teams = {t["id"]:t for t in all_rows("banca_equipes")}
    users = {u["id"]:u for u in all_rows("banca_usuarios")}
    for e in all_rows("banca_avaliacoes", order="equipe_id.asc,usuario_id.asc"):
        t=teams[e["equipe_id"]]; u=users[e["usuario_id"]]; obs=e["observacoes"]
        writer.writerow([t["id"], t["nome"], t["estande"], u["nome_exibicao"],u["username"],
                         e["c1"],e["c2"],e["c3"],e["c1"]+e["c2"]+e["c3"],
                         e["cameras_disponiveis"],e["cameras_usadas"],
                         *[obs.get(k,"") for k in PARTICIPANTS],e["notes"],e["updated_at"]])
    return Response("\ufeff"+output.getvalue(),mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition":"attachment; filename=NEXT_2026_Avaliacoes_Arena.csv"})

@app.get("/admin/audit.csv")
@admin_required
def audit_csv():
    output=io.StringIO()
    writer=csv.writer(output,delimiter=";")
    writer.writerow(["timestamp_utc","user_id","group_id","evento","detalhe"])
    for a in all_rows("banca_auditoria", order="id.asc"):
        writer.writerow([a["created_at"],a["usuario_id"],a["equipe_id"],a["evento"],a["detalhe"]])
    return Response("\ufeff"+output.getvalue(),mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition":"attachment; filename=NEXT_2026_Auditoria.csv"})

if __name__=="__main__":
    app.run(debug=not PROD, host="127.0.0.1",port=int(os.getenv("PORT","5000")))
