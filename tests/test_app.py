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
