"""NEXT 2026 • Banca avaliadora via Supabase Data API (sem DATABASE_URL).
As chaves Supabase ficam EXCLUSIVAMENTE no servidor Vercel.
As tabelas e funções são criadas pelo script supabase/schema.sql.
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps
from concurrent.futures import ThreadPoolExecutor
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
JUDGE_IDENTITIES = {
    "avaliador01": "Avaliador 1 — DATEN",
    "avaliador02": "Avaliador 2 — SVATECH",
    "avaliador03": "Avaliador 3 — Prof. Luiz (FIAP)",
    "avaliador04": "Avaliador 4 — Prof. Roberto (FIAP)",
}

def official_judges():
    """Quatro perfis oficiais: todos os demais ficam fora do ranking e das fichas."""
    return [record(u) for u in select(
        "banca_usuarios",
        {"papel": "eq.judge", "ativo": "eq.true"},
        order="username.asc"
    ) if u.get("username") in JUDGE_IDENTITIES]

def evaluator_label(user):
    """Identificação conferível pelo login autenticado, não por dado enviado no formulário."""
    if not user:
        return ""
    return JUDGE_IDENTITIES.get(user.username, user.display_name)

PARTICIPANTS = ("A1", "A2", "A3", "D1", "D2")
VALID_OBS = {
    **{x: {"correto", "erro", "nao_testado"} for x in PARTICIPANTS[:3]},
    **{x: {"alerta", "falso_aceite", "sem_leitura"} for x in PARTICIPANTS[3:]}
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

def raw_score(ev):
    """Nota tecnica de 0 a 15, sem ajuste."""
    return int(ev.c1) + int(ev.c2) + int(ev.c3)


def weighted_units(raw, cameras_used):
    """Pontuacao em decimos: 1 camera recebe +10%, com teto 15/15."""
    return min(150, int(raw) * (11 if int(cameras_used) == 1 else 10))


def score(ev):
    """Nota final de 0 a 15 (com bonus de 10% para uma camera)."""
    used = getattr(ev, "cameras_used", 2)
    return weighted_units(raw_score(ev), used) / 10.0


def row_weighted_units(row):
    return weighted_units(row["c1"] + row["c2"] + row["c3"],
                          row.get("cameras_usadas", 2))


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
        # Supabase/PostgREST devolve SQLSTATE e uma mensagem específica.
        # Identificamos problemas comuns sem enviar detalhes do banco aos alunos.
        detail = {}
        try:
            parsed = json.loads(exc.read().decode("utf-8", "replace"))
            if isinstance(parsed, dict):
                detail = parsed
        except (ValueError, TypeError, UnicodeDecodeError):
            pass
        code = str(detail.get("code") or "")
        backend_message = str(detail.get("message") or "")
        normalized = backend_message.lower()
        log.error(
            "Supabase REST falhou: method=%s endpoint=%s http=%s sqlstate=%s message=%s",
            method, path, exc.code, code, backend_message[:180]
        )
        if code == "21000" and "banca_limpar_avaliacoes" in path and "delete requires a where clause" in normalized:
            raise SupabaseError(
                "O Supabase bloqueou a limpeza sem filtro WHERE. "
                "Execute a migração 20261013_corrigir_delete_com_where.sql "
                "no SQL Editor do NEXT 2026 e tente novamente."
            )
        if code == "21000" and "banca_limpar_avaliacoes" in path:
            # Apresentar a mensagem PostgreSQL SOMENTE neste fluxo admin.
            # SQLSTATE 21000 não é falha de login nem função ausente:
            # requer investigar função e possíveis gatilhos/consultas internas.
            details = str(detail.get("details") or "").strip()
            message = backend_message.strip()[:280] or "violação de cardinalidade"
            extra = (" Detalhe: " + details[:240]) if details else ""
            log.error("Falha 21000 na exclusão: %s; detalhe=%s",
                      message, details[:600])
            raise SupabaseError(
                "Falha SQL 21000 na limpeza do histórico: " + message + extra +
                " Nenhuma alteração foi confirmada; execute o diagnóstico "
                "20261013_diagnosticar_erro_21000.sql."
            )
        if exc.code in (401, 403):
            raise SupabaseError("Acesso ao Supabase não autorizado. A coordenação deve conferir a chave privada no Vercel.")
        if (code == "PGRST202" or "could not find the function" in normalized):
            if "banca_limpar_avaliacoes" in path:
                raise SupabaseError(
                    "A função de limpeza do histórico não foi encontrada no Supabase. "
                    "Execute o SQL 20261012_corrigir_limpeza_historico.sql."
                )
            raise SupabaseError(
                "A função de avaliação não foi encontrada no Supabase. "
                "A coordenação deve executar a migração dos cinco participantes."
            )
        if "a4" in normalized and ("inválida" in normalized or "invalida" in normalized
                                 or "invalid" in normalized or "observation" in normalized):
            raise SupabaseError(
                "O Supabase ainda exige A4, mas a ficha atual possui cinco participantes. "
                "Execute a migração 20261012_cinco_participantes.sql no Supabase."
            )
        if "observação inválida" in normalized or "observacao invalida" in normalized:
            raise SupabaseError(
                "A função de avaliação no Supabase está desatualizada. "
                "A coordenação deve executar a migração dos cinco participantes."
            )
        if "bloqueada" in normalized or "bloqueado" in normalized:
            raise SupabaseError("A avaliação desta equipe está bloqueada pela coordenação.")
        if "justifique" in normalized or "justificativa" in normalized:
            raise SupabaseError("A função de avaliação no Supabase ainda exige justificativa. Execute a nova migração de avaliação rápida.")
        if code in ("42P01", "PGRST205") or exc.code == 404:
            raise SupabaseError("Estrutura de avaliação ausente no Supabase. A coordenação deve conferir as migrações.")
        if code == "42501" or "permission denied" in normalized:
            raise SupabaseError("Permissão insuficiente no Supabase. A coordenação deve conferir a chave de servidor.")
        if exc.code == 409:
            raise SupabaseError("Conflito ao gravar a avaliação. Atualize a ficha e tente novamente.", 409)
        raise SupabaseError(
            "Supabase recusou a gravação (código %s). Avise a coordenação." %
            (code or str(exc.code))
        )
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
    MAX_CONTENT_LENGTH=10 * 1024 * 1024
)
if PROD:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

@app.errorhandler(SupabaseError)
def api_error(exc):
    """Mostrar falha de conexão com a mesma interface visual do sistema.

    Um erro na consulta de usuários pode acontecer durante o processamento
    da própria página. Limpar o usuário em cache impede uma segunda consulta
    ao Supabase enquanto apresentamos a mensagem ao avaliador.
    """
    log.error("Falha do serviço da banca na rota %s: %s", request.path, exc)
    g._next_user = None
    message = (
        "Supabase indisponível: a conexão com o banco da banca não pôde "
        "ser concluída. A coordenação deve verificar se o projeto "
        "NEXT 2026 está ativo. Não execute novamente schema.sql."
    )
    if request.path.startswith("/api/") or (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.accept_mimetypes.best == "application/json"
    ):
        return jsonify(ok=False, setup_required=True, error=message), 503

    # Reusar os estilos próprios do portal em vez de CSS inline, que é
    # proibido pelo Content-Security-Policy de produção.
    flash(message, "error")
    section = "coordenacao" if (
        request.path.startswith("/coordenacao")
        or request.form.get("portal_role") == "admin"
    ) else "avaliador"
    return render_template("login.html", portal_section=section), 503

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
    if request.path.startswith("/static/"):
        # Assets públicos versionados ficam no cache do navegador.
        res.headers["Cache-Control"] = "public, max-age=86400, stale-while-revalidate=604800"
    else:
        res.headers["Cache-Control"] = "no-store"
    # HTML/JSON menores para 4G/5G e Wi-Fi congestionado.
    if (request.method != "HEAD" and res.status_code in (200,400,503)
        and not res.direct_passthrough
        and res.mimetype in ("text/html","application/json")
        and "gzip" in request.headers.get("Accept-Encoding","").lower()
        and not res.headers.get("Content-Encoding")):
        body=res.get_data()
        if len(body)>1500:
            compressed=gzip.compress(body,compresslevel=5,mtime=0)
            if len(compressed)<len(body):
                res.set_data(compressed)
                res.headers["Content-Encoding"]="gzip"
                res.headers["Vary"]="Accept-Encoding"
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
    # A tela inicial e suas rotas publicas devem abrir mesmo se o
    # Supabase estiver temporariamente pausado. So consultar a identidade
    # nas rotas que realmente exigem autenticacao.
    public_portal = request.endpoint in ("root", "login", "portal_evaluator", "portal_coordinator", "portal_course")
    user = None if public_portal else get_user()
    return {"csrf_token": session["csrf_token"],
            "current_user": user,
            "current_user_label": evaluator_label(user),
            "judge_profiles": JUDGE_IDENTITIES,
            "evaluator_label": evaluator_label}

def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        u = get_user()
        if not u or not u.active or (u.role == "judge" and getattr(u, "username", None) not in JUDGE_IDENTITIES):
            session.clear()
            return redirect(url_for("login"))
        # Perfil somente-leitura: nenhum outro endpoint nem formulário é
        # acessível, mesmo que alguém tente chamá-lo diretamente pela URL.
        if u.role == "course_coordinator" and request.endpoint not in (
            "course_results_dashboard", "api_course_results", "logout"
        ):
            abort(403)
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
        usernames = request.form.getlist("username")
        portal_role = request.form.get("portal_role", "")
        is_admin_portal = portal_role in ("admin", "")
        is_course_portal = portal_role == "course"
        section = "curso" if is_course_portal else ("coordenacao" if is_admin_portal else "avaliador")
        if len(usernames) != 1 or not usernames[0].strip():
            flash("Selecione somente um avaliador.", "error")
            return render_template("login.html", portal_section=section), 400
        username = usernames[0].strip().lower()

        # Avaliadores: acesso direto por seleção, SEM senha.
        # Scrum Master/Coordenação: segue exigindo senha e validação de papel.
        if is_admin_portal:
            init_admin()
        u = one("banca_usuarios", username=username)
        is_judge = bool(
            portal_role == "judge" and username in JUDGE_IDENTITIES and
            u and u.username == username and u.role == "judge"
        )
        is_admin = bool(
            is_admin_portal and u and u.username == username and u.role == "admin"
        )
        is_course = bool(
            is_course_portal and u and u.username == "coordenador.curso"
            and username == "coordenador.curso" and u.role == "course_coordinator"
        )
        protected_role = is_admin or is_course
        locked = bool(protected_role and u.locked_until and u.locked_until > now())
        valid = bool(
            u and u.active and not locked and (
                is_judge or (
                    protected_role and check_password_hash(
                        u.password_hash, request.form.get("password", "")
                    )
                )
            )
        )
        if not valid:
            if protected_role and not locked:
                fail = int(u.failed_attempts) + 1
                values = {"falhas_login": 0, "bloqueado_ate": (now()+timedelta(minutes=10)).isoformat()} if fail >= 5 else {"falhas_login": fail}
                patch("banca_usuarios", values, id=u.id)
            flash(
                "Avaliador indisponível. Confira a seleção ou contate a coordenação."
                if not (is_admin_portal or is_course_portal) else
                "Senha inválida ou conta temporariamente bloqueada.",
                "error"
            )
            return render_template("login.html", portal_section=section), 401

        # Ao desativar senha para avaliadores, também limpamos bloqueios
        # antigos por senha. Nenhuma permissão administrativa é concedida.
        if u.failed_attempts or u.locked_until:
            patch("banca_usuarios", {"falhas_login": 0, "bloqueado_ate": None}, id=u.id)
        session.clear()
        session["uid"] = u.id
        session["csrf_token"] = secrets.token_urlsafe(32)
        session.permanent = True
        return redirect(url_for("course_results_dashboard") if is_course else url_for("dashboard"))
    return render_template("login.html", portal_section="avaliador")

@app.get("/coordenador-curso")
def portal_course():
    return render_template("login.html", portal_section="curso")

@app.get("/avaliador")
def portal_evaluator():
    return render_template("login.html", portal_section="avaliador")

@app.get("/coordenacao")
def portal_coordinator():
    return render_template("login.html", portal_section="coordenacao")

@app.post("/logout")
@login_required
def logout():
    session.clear()
    return redirect(url_for("root"))

@app.get("/")
def root():
    # Abrir diretamente a area do avaliador, sem tela anterior de login.
    return render_template("login.html", portal_section="avaliador")

@app.get("/dashboard")
@login_required
def dashboard():
    user = get_user()
    admin = user.role == "admin"
    # Chamada única ao painel: dados independentes em paralelo.
    # Jurados buscam só suas fichas, nunca notas de outros avaliadores.
    with ThreadPoolExecutor(max_workers=4 if admin else 3) as pool:
        team_future = pool.submit(select, "banca_equipes", order="id.asc")
        timer_future = pool.submit(select, "banca_temporizadores")
        judge_future = pool.submit(official_judges) if admin else None
        evaluation_future = (pool.submit(all_rows, "banca_avaliacoes") if admin else
            pool.submit(select,"banca_avaliacoes",{"usuario_id":"eq."+str(user.id)}))
        teams = [record(x) for x in team_future.result()]
        timers = {x["equipe_id"]:record(x) for x in timer_future.result()}
        judges = judge_future.result() if judge_future else list(JUDGE_IDENTITIES)
        allowed = {u.id for u in judges} if admin else {user.id}
        evaluations = [record(x) for x in evaluation_future.result()
                       if x["usuario_id"] in allowed]

    by_team={}
    own_by_team={}
    for entry in evaluations:
        by_team.setdefault(entry.team_id,[]).append(entry)
        if entry.user_id==user.id:
            own_by_team[entry.team_id]=entry

    rows=[]
    for team in teams:
        group=by_team.get(team.id,[])
        own=own_by_team.get(team.id)
        if own:
            own.total=raw_score(own)
            own.adjusted_total=score(own)
        values=[score(e) for e in group] if admin else []
        rows.append({"team":team,"timer":timer_view(timers[team.id]),
                     "count":len(group),
                     "average":round(sum(values)/len(values),2) if values else None,
                     "own":own})
    return render_template("dashboard.html",rows=rows,judges=judges,user=user)

def build_ranking():
    """Classificação provisória por média PONDERADA / 15, com empates reais.

    Equipes sem avaliações ficam no fim, sem posição. Grupos empatados
    recebem a mesma posição; sem critério de desempate artificial.
    """
    teams = [record(t) for t in select("banca_equipes", order="id.asc")]
    active_judges = official_judges()
    allowed_ids = {u.id for u in active_judges}
    evaluations = [e for e in all_rows("banca_avaliacoes") if e["usuario_id"] in allowed_ids]
    expected = len(JUDGE_IDENTITIES)
    votes = {}
    for e in evaluations:
        votes.setdefault(e["equipe_id"], []).append(e)

    rows = []
    for t in teams:
        group = votes.get(t.id, [])
        count = len(group)
        raw_total = sum(e["c1"] + e["c2"] + e["c3"] for e in group)
        weighted_total_units = sum(row_weighted_units(e) for e in group)
        one_camera = sum(1 for e in group if e.get("cameras_usadas", 2) == 1)
        sums = [sum(e[f"c{i}"] for e in group) for i in (1, 2, 3)]
        rows.append({
            "team_id": t.id, "name": t.name, "stand": t.stand,
            "rank": None,
            "evaluations": count,
            "expected": expected,
            "average": round(weighted_total_units / (10 * count), 2) if count else None,
            "base_average": round(raw_total / count, 2) if count else None,
            "one_camera_evaluations": one_camera,
            "c1_average": round(sums[0] / count, 2) if count else None,
            "c2_average": round(sums[1] / count, 2) if count else None,
            "c3_average": round(sums[2] / count, 2) if count else None,
            "locked": bool(t.locked),
            "complete": count > 0 and (expected > 0 and count >= expected),
            "_sum": weighted_total_units
        })

    # Comparison by cross-multiplication below avoids floating point ties.
    rows.sort(key=lambda r: (not bool(r["evaluations"]),
                            -(r["_sum"] / r["evaluations"]) if r["evaluations"] else 0,
                            r["team_id"]))
    last_sum = None
    last_count = None
    last_rank = None
    for position, row in enumerate(rows, 1):
        count = row["evaluations"]
        if count:
            current_sum = row["_sum"]
            # Guardar os totais da equipe anterior ANTES de remover o campo
            # temporário. O código anterior acessava last_scored["_sum"]
            # depois do "del", causando KeyError e HTTP 500 com >=2 equipes.
            if last_sum is None or current_sum * last_count != last_sum * count:
                last_rank = position
            row["rank"] = last_rank
            last_sum, last_count = current_sum, count
        del row["_sum"]

    return {"ranking": rows, "expected_judges": expected,
            "updated_at": now().isoformat()}

def build_course_ranking():
    """Somar até 40 pontos do Pré-NEXT à média até 15 da arena.

    A projeção 40+15 é EXPLÍCITA e PROVISÓRIA; a homologação depende
    da coordenação. Nenhuma nota ausente é inventada.
    """
    live = build_ranking()
    preliminary = {
        int(v["equipe_id"]): Decimal(str(v["pontos"]))
        for v in select("banca_prenext")
    }
    ordered_pre = sorted(preliminary.items(), key=lambda pair: (-pair[1], pair[0]))
    preliminary_ranks = {}
    last_points = None
    current_pre_rank = None
    for position, (team_id, points) in enumerate(ordered_pre, 1):
        if last_points != points:
            current_pre_rank = position
        preliminary_ranks[team_id] = current_pre_rank
        last_points = points
    rows = []
    for item in live["ranking"]:
        base = preliminary.get(item["team_id"])
        arena = item["average"]
        total = (base + Decimal(str(arena))) if base is not None and arena is not None else None
        rows.append({
            "team_id": item["team_id"], "name": item["name"], "stand": item["stand"],
            "pre_score": float(base) if base is not None else None,
            "pre_rank": preliminary_ranks.get(item["team_id"]),
            "next_average": arena,
            "evaluation_count": item["evaluations"], "expected": item["expected"],
            "complete": item["complete"], "total": float(total) if total is not None else None,
            "combined_rank": None,
            "status": "Aguardando arena" if arena is None else (
                "4 fichas recebidas" if item["complete"] else "Arena parcial"
            )
        })
    # Classificação total calculada somente para equipes que já receberam
    # pelo menos uma avaliação do NEXT. Fichas pendentes ficam sem rank total.
    rows.sort(key=lambda r: (r["total"] is None,
                             -r["total"] if r["total"] is not None else 0,
                             r["pre_rank"] or 999, r["team_id"]))
    previous_total = None
    previous_rank = None
    for position, item in enumerate(rows, 1):
        if item["total"] is not None:
            if previous_total != item["total"]:
                previous_rank = position
            item["combined_rank"] = previous_rank
            previous_total = item["total"]
    return {"ranking": rows, "expected_judges": live["expected_judges"],
            "updated_at": now().isoformat(), "max_pre":40, "max_next":15,
            "max_total":55, "official":False}


def course_view_required(fn):
    @wraps(fn)
    @login_required
    def wrapped(*args, **kwargs):
        if get_user().role not in ("admin", "course_coordinator"):
            abort(403)
        return fn(*args, **kwargs)
    return wrapped


@app.get("/curso/resultados")
@course_view_required
def course_results_dashboard():
    return render_template("course_results.html", **build_course_ranking())


@app.get("/api/curso/resultados")
@course_view_required
def api_course_results():
    response = jsonify(build_course_ranking())
    response.headers["Cache-Control"] = "no-store, private"
    return response


@app.post("/admin/curso/acesso")
@admin_required
def manage_course_access():
    """Criar ou redefinir senha do perfil somente-leitura, sem afetar jurados."""
    username = "coordenador.curso"
    existing = one("banca_usuarios", username=username)
    if existing and existing.role != "course_coordinator":
        abort(409, "Este identificador já está ocupado por outro perfil.")
    password = secrets.token_urlsafe(18)
    values = {
        "senha_hash":generate_password_hash(password),
        "falhas_login":0, "bloqueado_ate":None, "ativo":True
    }
    if existing:
        patch("banca_usuarios", values, id=existing.id)
        log_event("course_coordinator_password_reset",detail=username)
    else:
        created = insert("banca_usuarios", {
            **values, "username":username, "nome_exibicao":"Coordenador de Curso",
            "papel":"course_coordinator"
        })
        log_event("course_coordinator_created",detail=username)
    return render_template("course_access_created.html", username=username, password=password)


@app.get("/admin/prenext")
@admin_required
def admin_prenext():
    teams = [record(t) for t in select("banca_equipes",order="id.asc")]
    scores = {int(row["equipe_id"]):row["pontos"] for row in select("banca_prenext")}
    return render_template("admin_prenext.html", teams=teams, scores=scores)


@app.post("/admin/prenext/<int:team_id>")
@admin_required
def admin_update_prenext(team_id):
    if team_id not in range(1,10):
        abort(404)
    try:
        points = Decimal(request.form.get("points","").replace(",","."))
        if not points.is_finite() or points < 0 or points > 40 or points.as_tuple().exponent < -2:
            raise InvalidOperation()
    except (InvalidOperation, ValueError):
        flash("Pontuação inválida. Informe um valor entre 0 e 40, com até duas casas.", "error")
        return redirect(url_for("admin_prenext"))
    if not one("banca_prenext",equipe_id=team_id):
        insert("banca_prenext",{"equipe_id":team_id,"pontos":float(points)})
    else:
        patch("banca_prenext",{"pontos":float(points),"atualizado_em":now().isoformat()},equipe_id=team_id)
    log_event("prenext_score_updated", team_id=team_id, detail=f"Novo valor: {points}/40")
    flash("Nota do Pré-NEXT atualizada.", "success")
    return redirect(url_for("admin_prenext"))


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
    user = get_user()
    # Ficha, cronômetro e equipe usam três consultas independentes.
    if request.method == "GET":
        with ThreadPoolExecutor(max_workers=3) as pool:
            team_future=pool.submit(get_team,group)
            own_future=pool.submit(one,"banca_avaliacoes",
                                   equipe_id=group,usuario_id=user.id)
            timer_future=pool.submit(get_timer,group)
            t=team_future.result()
            existing=own_future.result()
            timer=timer_future.result()
        if existing:
            existing.total=raw_score(existing)
            existing.adjusted_total=score(existing)
        return render_template("evaluate.html",team=t,evaluation=existing,
                               obs=existing.observations if existing else {},
                               timer=timer_view(timer),participants=PARTICIPANTS)
    t=get_team(group)
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
            # Duas câmeras são fornecidas a TODAS as equipes.
            # Não confiar no campo 'available' enviado pelo navegador.
            available = 2
            used = int(request.form.get("used", "-1"))
        except (ValueError, TypeError):
            return invalid("Preencha as três notas e a quantidade de câmeras.")
        if not all(0 <= x <= 5 for x in scores):
            return invalid("Cada nota deve estar entre 0 e 5.")
        if used not in (1, 2):
            return invalid("Selecione uma ou duas câmeras utilizadas.")

        # Não presumir detecção correta nem teste concluído: cada resultado
        # deve ser selecionado explicitamente pelo avaliador.
        obs = {k: request.form.get(k) for k in PARTICIPANTS}
        if any(obs[k] not in VALID_OBS[k] for k in PARTICIPANTS):
            return invalid("Marque o resultado dos cinco participantes.")

        # Sem caixa de observacoes na ficha rapida. O campo historico segue
        # no banco por compatibilidade com registros antigos e contingencia.
        notes = ""

        try:
            rpc("banca_salvar_avaliacao", {
                "p_equipe": group, "p_usuario": user.id, "p_c1": scores[0],
                "p_c2": scores[1], "p_c3": scores[2], "p_disponiveis": available,
                "p_usadas": used, "p_obs": obs, "p_notas": notes
            })
        except SupabaseError as exc:
            if async_request:
                return jsonify(ok=False, error=str(exc)), exc.status
            raise

        if async_request:
            return jsonify(ok=True, team=group, total=sum(scores),
                           adjusted_total=weighted_units(sum(scores), used) / 10,
                           bonus_percent=10 if used == 1 else 0,
                           saved_at=now().isoformat())
        flash("Avaliação registrada.", "success")
        return redirect(url_for("dashboard"))

    return redirect(url_for("dashboard"))


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
    username = request.form.get("username", "").strip().lower()
    if username not in JUDGE_IDENTITIES:
        flash("A banca possui somente quatro avaliadores oficiais.", "error")
        return redirect(url_for("dashboard"))
    if one("banca_usuarios", username=username):
        flash("Este avaliador já está cadastrado.", "error")
        return redirect(url_for("dashboard"))
    name = JUDGE_IDENTITIES[username]
    password = fast_password()
    try:
        insert("banca_usuarios", {
            "username": username, "nome_exibicao": name, "papel": "judge",
            "senha_hash": generate_password_hash(password)
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
    if u.role != "judge" or u.username not in JUDGE_IDENTITIES:
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
                    "total_bruto","total_ponderado","bonus_uma_camera_pct",
                    "cameras_disponiveis","cameras_usadas","A1","A2","A3",
                    "D1","D2","observacoes_legadas","atualizado_em_utc"])
    teams = {t["id"]:t for t in all_rows("banca_equipes")}
    users = {u["id"]:u for u in all_rows("banca_usuarios")}
    for e in all_rows("banca_avaliacoes", order="equipe_id.asc,usuario_id.asc"):
        t=teams[e["equipe_id"]]; u=users[e["usuario_id"]]; obs=e["observacoes"]
        writer.writerow([t["id"], t["nome"], t["estande"], evaluator_label(record(u)),u["username"],
                         e["c1"],e["c2"],e["c3"],e["c1"]+e["c2"]+e["c3"],
                         row_weighted_units(e)/10,
                         10 if e.get("cameras_usadas",2)==1 else 0,
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

from manual_admin import install_manual_routes
install_manual_routes(app,admin_required,one,select,rpc,get_user,SUPABASE_URL,SUPABASE_KEY,evaluator_label,JUDGE_IDENTITIES,SupabaseError)

if __name__=="__main__":
    app.run(debug=not PROD, host="127.0.0.1",port=int(os.getenv("PORT","5000")))
