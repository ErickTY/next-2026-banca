"""Testes básicos da aplicação sem acesso real à rede Supabase."""
import importlib
import sys
from types import SimpleNamespace

import pytest

@pytest.fixture
def module(monkeypatch):
    monkeypatch.setenv("SECRET_KEY","test-secret-key-at-least-32-characters-2026")
    monkeypatch.setenv("ADMIN_PASSWORD","temporary-strong-admin-password")
    monkeypatch.setenv("ADMIN_USERNAME","coordenacao")
    monkeypatch.delenv("SUPABASE_URL",raising=False)
    monkeypatch.delenv("SUPABASE_SECRET_KEY",raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY",raising=False)
    sys.modules.pop("app",None)
    mod=importlib.import_module("app")
    mod.app.config.update(TESTING=True)
    yield mod
    sys.modules.pop("app",None)

def test_sem_supabase_mostra_configuracao(module):
    c=module.app.test_client()
    assert c.get("/login").status_code==200
    health=c.get("/health")
    assert health.status_code==503
    assert health.json["setup_required"] is True

def test_health_usa_data_api(module,monkeypatch):
    monkeypatch.setattr(module,"SUPABASE_URL","https://iwfqmdsrourtdvrgiums.supabase.co")
    monkeypatch.setattr(module,"SUPABASE_KEY","sb_secret_test_key")
    monkeypatch.setattr(module,"select",lambda table,*args,**kw: [])
    c=module.app.test_client()
    assert c.get("/health").json == {"ok":True,"backend":"supabase-rest"}

def test_login_exige_csrf(module,monkeypatch):
    from werkzeug.security import generate_password_hash
    monkeypatch.setattr(module,"SUPABASE_URL","https://iwfqmdsrourtdvrgiums.supabase.co")
    monkeypatch.setattr(module,"SUPABASE_KEY","sb_secret_test_key")
    user=SimpleNamespace(id=1,username="coordenacao",
                         password_hash=generate_password_hash("temporary-strong-admin-password"),
                         active=True,locked_until=None,failed_attempts=0,role="admin",
                         display_name="Coordenação")
    monkeypatch.setattr(module,"init_admin",lambda:None)
    monkeypatch.setattr(module,"one",lambda table,**kw:user if table=="banca_usuarios" else None)
    monkeypatch.setattr(module,"patch",lambda *a,**kw:None)
    c=module.app.test_client()
    assert c.get("/login").status_code==200
    assert c.post("/login",data={"username":"coordenacao","password":"temporary-strong-admin-password"}).status_code==400
    with c.session_transaction() as s:
        token=s["csrf_token"]
    response=c.post("/login",data={"username":"coordenacao",
                                   "password":"temporary-strong-admin-password","csrf_token":token})
    assert response.status_code==302
    assert "/dashboard" in response.headers["Location"]


def test_ranking_mantem_empates_e_nao_classifica_equipes_sem_notas(module,monkeypatch):
    monkeypatch.setattr(module,"select",lambda table,*args,**kwargs:
        [{"id":1,"nome":"Datacore","estande":"A22","bloqueado":False},
         {"id":2,"nome":"OutBox","estande":"A23","bloqueado":False},
         {"id":3,"nome":"Auditix AI","estande":"A24","bloqueado":False}]
        if table=="banca_equipes" else [{"id":10},{"id":11}])
    evaluations=[
        {"equipe_id":1,"c1":4,"c2":4,"c3":4},
        {"equipe_id":1,"c1":5,"c2":5,"c3":4},
        {"equipe_id":2,"c1":5,"c2":4,"c3":4}
    ]
    monkeypatch.setattr(module,"all_rows",lambda table,**kw:evaluations)
    result=module.build_ranking()
    assert [x["rank"] for x in result["ranking"]]==[1,1,None]
    assert [x["team_id"] for x in result["ranking"]]==[1,2,3]
    assert result["ranking"][0]["average"]==13
    assert result["ranking"][0]["complete"] is True
    assert result["ranking"][1]["complete"] is False
    assert result["ranking"][2]["average"] is None
    assert result["ranking"][0]["name"]=="Datacore"

def test_reset_exclusivo_do_admin(module,monkeypatch):
    from types import SimpleNamespace
    c=module.app.test_client()
    c.get("/login")
    with c.session_transaction() as sess:
        token=sess["csrf_token"]
    user=SimpleNamespace(id=10,role="judge",active=True,display_name="Avaliador")
    monkeypatch.setattr(module,"get_user",lambda:user)
    monkeypatch.setattr(module,"get_team",lambda team:SimpleNamespace(id=team))
    invoked=[]
    monkeypatch.setattr(module,"rpc",lambda name,payload:invoked.append((name,payload)))
    resp=c.post("/admin/timers/1/reset",
                data={"csrf_token":token,"reason":"Reinício manual pela coordenação"})
    assert resp.status_code==403
    assert invoked==[]
    user.role="admin"
    resp=c.post("/admin/timers/1/reset",
                data={"csrf_token":token,"reason":"Reinício manual pela coordenação"})
    assert resp.status_code==302
    assert invoked and invoked[0][0]=="banca_operar_tempo"
    assert invoked[0][1]["p_usuario"]==10
    assert invoked[0][1]["p_acao"]=="reset"

def test_api_resultados_nega_avaliador(module,monkeypatch):
    from types import SimpleNamespace
    user=SimpleNamespace(id=10,role="judge",active=True,display_name="Avaliador")
    monkeypatch.setattr(module,"get_user",lambda:user)
    c=module.app.test_client()
    assert c.get("/api/results").status_code==403
    assert c.get("/admin/results").status_code==403
