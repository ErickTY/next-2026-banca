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
        if table=="banca_equipes" else [
           {"id":10,"username":"avaliador01","nome_exibicao":"DATEN"},
           {"id":11,"username":"avaliador02","nome_exibicao":"SVATECH"},
           {"id":12,"username":"avaliador03","nome_exibicao":"Luiz"},
           {"id":13,"username":"avaliador04","nome_exibicao":"Roberto"},
           {"id":14,"username":"avaliador05","nome_exibicao":"Reserva"}])
    evaluations=[
        {"equipe_id":1,"usuario_id":10,"c1":4,"c2":4,"c3":4},
        {"equipe_id":1,"usuario_id":11,"c1":5,"c2":5,"c3":4},
        {"equipe_id":2,"usuario_id":12,"c1":5,"c2":4,"c3":4}
    ]
    monkeypatch.setattr(module,"all_rows",lambda table,**kw:evaluations)
    result=module.build_ranking()
    assert [x["rank"] for x in result["ranking"]]==[1,1,None]
    assert [x["team_id"] for x in result["ranking"]]==[1,2,3]
    assert result["ranking"][0]["average"]==13
    assert result["ranking"][0]["complete"] is False
    assert result["expected_judges"] == 4
    assert result["ranking"][1]["complete"] is False
    assert result["ranking"][2]["average"] is None
    assert result["ranking"][0]["name"]=="Datacore"

def test_reset_exclusivo_do_admin(module,monkeypatch):
    from types import SimpleNamespace
    c=module.app.test_client()
    c.get("/login")
    with c.session_transaction() as sess:
        token=sess["csrf_token"]
    user=SimpleNamespace(id=10,role="judge",username="avaliador01",active=True,display_name="Avaliador")
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
    user=SimpleNamespace(id=10,role="judge",username="avaliador01",active=True,display_name="Avaliador")
    monkeypatch.setattr(module,"get_user",lambda:user)
    c=module.app.test_client()
    assert c.get("/api/results").status_code==403
    assert c.get("/admin/results").status_code==403


def test_ajax_timer_silencioso(module,monkeypatch):
    from types import SimpleNamespace
    admin=SimpleNamespace(id=1,role='admin',active=True,display_name='Coordenação')
    monkeypatch.setattr(module,'get_user',lambda:admin)
    monkeypatch.setattr(module,'rpc',lambda name,payload:{'estado':'idle','versao':1})
    c=module.app.test_client()
    c.get('/login')
    with c.session_transaction() as sess:
        csrf=sess['csrf_token']
    for action in ('start','pause','resume','finish','reset'):
        response=c.post('/admin/timers/1/'+action,
            headers={'X-Requested-With':'XMLHttpRequest','Accept':'application/json'},
            data={'csrf_token':csrf,'reason':'Ajuste realizado pela coordenação'})
        assert response.status_code==200
        assert response.json['ok'] is True
        assert 'Location' not in response.headers
    with c.session_transaction() as sess:
        assert not sess.get('_flashes')

def test_ajax_reset_nega_avaliador(module,monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(module,'get_user',lambda:SimpleNamespace(id=2,role='judge',username='avaliador01',active=True))
    c=module.app.test_client()
    c.get('/login')
    with c.session_transaction() as sess:
        csrf=sess['csrf_token']
    response=c.post('/admin/timers/1/reset',
        headers={'X-Requested-With':'XMLHttpRequest'},
        data={'csrf_token':csrf,'reason':'Ajuste realizado pela coordenação'})
    assert response.status_code==403

def test_senha_rapida_tem_dez_caracteres(module):
    a=module.fast_password()
    b=module.fast_password()
    assert len(a)==10 and len(b)==10
    assert a!=b
    assert all(ch in 'abcdefghjkmnpqrstuvwxyz23456789' for ch in a)

def test_avaliacao_rapida_pede_observacao_explicita_e_salva_sem_reload(module,monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(module,'get_user',lambda:SimpleNamespace(id=7,role='judge',username='avaliador01',active=True))
    monkeypatch.setattr(module,'get_team',lambda grp:SimpleNamespace(id=grp,locked=False))
    saved=[]
    monkeypatch.setattr(module,'rpc',lambda name,payload:saved.append((name,payload)))
    c=module.app.test_client()
    c.get('/login')
    with c.session_transaction() as sess:
        csrf=sess['csrf_token']
    data={'csrf_token':csrf,'c1':'4','c2':'5','c3':'4','available':'2','used':'1',
          'A1':'correto','A2':'correto','A3':'correto','D1':'alerta'}
    headers={'X-Requested-With':'XMLHttpRequest','Accept':'application/json'}
    reject=c.post('/evaluate/1',data=data,headers=headers)
    assert reject.status_code==400
    assert saved==[]
    data['D2']='alerta'
    ok=c.post('/evaluate/1',data=data,headers=headers)
    assert ok.status_code==200 and ok.json['ok'] is True
    assert ok.json['total']==13
    assert len(saved)==1 and saved[0][1]['p_equipe']==1
    assert 'Location' not in ok.headers


def test_exatamente_tres_autorizados_e_dois_desconhecidos(module,monkeypatch):
    """A1, A2 e A3; D1 e D2. A4 não é mais obrigatório."""
    from types import SimpleNamespace
    assert module.PARTICIPANTS == ("A1", "A2", "A3", "D1", "D2")
    assert "A4" not in module.PARTICIPANTS
    monkeypatch.setattr(module, "get_user", lambda:SimpleNamespace(id=2, role="judge", username="avaliador01", active=True))
    monkeypatch.setattr(module, "get_team", lambda grp:SimpleNamespace(id=grp, locked=False))
    calls=[]
    monkeypatch.setattr(module,"rpc",lambda name,data:calls.append((name,data)))
    client=module.app.test_client()
    client.get("/login")
    with client.session_transaction() as ses:
        csrf=ses["csrf_token"]
    request_data={
        "csrf_token":csrf, "c1":"5","c2":"5","c3":"4", "available":"2","used":"1",
        "A1":"correto","A2":"correto","A3":"correto","D1":"alerta","D2":"alerta"
    }
    response=client.post("/evaluate/1", data=request_data,
                         headers={"X-Requested-With":"XMLHttpRequest"})
    assert response.status_code == 200
    assert response.json["ok"] is True
    assert list(calls[0][1]["p_obs"]) == ["A1","A2","A3","D1","D2"]
    assert "A4" not in calls[0][1]["p_obs"]

def test_identificacao_nominal_dos_avaliadores(module):
    from types import SimpleNamespace
    expected={
        'avaliador01':'Avaliador 1 — DATEN',
        'avaliador02':'Avaliador 2 — SVATECH',
        'avaliador03':'Avaliador 3 — Prof. Luiz (FIAP)',
        'avaliador04':'Avaliador 4 — Prof. Roberto (FIAP)'
    }
    for username,label in expected.items():
        assert module.evaluator_label(SimpleNamespace(
            username=username, display_name='Nome antigo'
        )) == label
    assert module.evaluator_label(SimpleNamespace(
        username='avaliador_externo',display_name='Convidado'
    )) == 'Convidado'
    login_page=module.app.test_client().get('/login').get_data(as_text=True)
    assert 'Avaliador 3 — Prof. Luiz (FIAP)' in login_page
    assert 'Avaliador 4 — Prof. Roberto (FIAP)' in login_page
    assert 'data-login-identity=' in login_page


def test_formulario_impresso_e_leitura_otica_sem_ia_externa():
    from io import BytesIO
    from PIL import Image, ImageDraw
    from manual_forms import CORNERS, ROWS, render_pdf, read_marks
    pdf=render_pdf(1, "Datacore", "A22", "avaliador01", "Avaliador 1 DATEN")
    assert pdf.startswith(b"%PDF-")
    paper=Image.new("RGB",(1190,1684),"white")
    drawing=ImageDraw.Draw(paper)
    for x,y in CORNERS:
        drawing.rectangle((2*(x-7),2*(842-y-7),2*(x+7),2*(842-y+7)),fill="black")
    expected={"A1":"correto","A2":"erro","A3":"correto","D1":"alerta",
              "D2":"falso_aceite","c1":4,"c2":3,"c3":5,"available":2,"used":1}
    for field,opts,points in ROWS:
        for i,(x,y) in enumerate(points):
            px,py=2*x,2*(842-y)
            drawing.ellipse((px-18,py-18,px+18,py+18),outline="black",width=2)
            if opts[i]==expected[field]:
                drawing.ellipse((px-10,py-10,px+10,py+10),fill="black")
    binary=BytesIO();paper.save(binary,format="JPEG",quality=90)
    result=read_marks(binary.getvalue())
    assert result["recognized"]==10
    assert result["warnings"]==[]
    assert result["answers"]==expected


def test_ficha_em_branco_nao_vira_avaliacao():
    from io import BytesIO
    from PIL import Image,ImageDraw
    from manual_forms import CORNERS,ROWS,read_marks
    paper=Image.new("RGB",(1190,1684),"white")
    drawing=ImageDraw.Draw(paper)
    for x,y in CORNERS:
        drawing.rectangle((2*(x-7),2*(842-y-7),2*(x+7),2*(842-y+7)),fill="black")
    for _,_,points in ROWS:
        for x,y in points:
            px,py=2*x,2*(842-y)
            drawing.ellipse((px-18,py-18,px+18,py+18),outline="black",width=2)
    binary=BytesIO();paper.save(binary,format="JPEG",quality=90)
    result=read_marks(binary.getvalue())
    assert result["recognized"]==0
    assert all(v is None for v in result["answers"].values())


def test_contingencia_exclusiva_para_admin(module,monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(module,"get_user",lambda:SimpleNamespace(
        id=12,username="avaliador01",role="judge",active=True,display_name="DATEN"
    ))
    c=module.app.test_client()
    assert c.get("/admin/contingencia").status_code==403
    assert c.get("/admin/contingencia/formularios.zip").status_code==403
    assert c.get("/admin/contingencia/formulario.pdf?group=1&judge=2").status_code==403
    c.get("/login")
    with c.session_transaction() as s: csrf=s["csrf_token"]
    assert c.post("/admin/historico/limpar",
         data={"csrf_token":csrf,"group":"all","confirmation":"APAGAR NOTAS",
               "password":"irrelevante"}).status_code==403


def test_rpc_antiga_com_a4_retorna_orientacao_de_migracao(module, monkeypatch):
    import io
    import json
    import pytest
    from urllib.error import HTTPError
    monkeypatch.setattr(module, "SUPABASE_URL", "https://iwfqmdsrourtdvrgiums.supabase.co")
    monkeypatch.setattr(module, "SUPABASE_KEY", "sb_secret_test")
    def fake_urlopen(request, timeout=12):
        payload=json.dumps({"code":"P0001","message":"Observação inválida: A4"}).encode()
        raise HTTPError(request.full_url,400,"RPC error",{},io.BytesIO(payload))
    monkeypatch.setattr(module, "urlopen", fake_urlopen)
    with pytest.raises(module.SupabaseError, match="A4"):
        module.rpc("banca_salvar_avaliacao",{"p_equipe":1})


def test_rpc_nao_encontrada_indica_migracao(module, monkeypatch):
    import io
    import json
    import pytest
    from urllib.error import HTTPError
    monkeypatch.setattr(module, "SUPABASE_URL", "https://iwfqmdsrourtdvrgiums.supabase.co")
    monkeypatch.setattr(module, "SUPABASE_KEY", "sb_secret_test")
    def fake_urlopen(request, timeout=12):
        payload=json.dumps({"code":"PGRST202","message":"Could not find the function public.banca_salvar_avaliacao in the schema cache"}).encode()
        raise HTTPError(request.full_url,404,"Not found",{},io.BytesIO(payload))
    monkeypatch.setattr(module, "urlopen", fake_urlopen)
    with pytest.raises(module.SupabaseError, match="migração"):
        module.rpc("banca_salvar_avaliacao",{"p_equipe":1})


def test_somente_quatro_avaliadores_oficiais_no_login(module,monkeypatch):
    assert list(module.JUDGE_IDENTITIES)==["avaliador01","avaliador02","avaliador03","avaliador04"]
    page=module.app.test_client().get("/login").get_data(as_text=True)
    assert "avaliador04" in page
    assert "avaliador05" not in page
    monkeypatch.setattr(module,"init_admin",lambda:None)
    from types import SimpleNamespace
    from werkzeug.security import generate_password_hash
    fifth=SimpleNamespace(id=5,username="avaliador05",role="judge",
        password_hash=generate_password_hash("avaliador05"),active=True,
        locked_until=None,failed_attempts=0)
    monkeypatch.setattr(module,"one",lambda table,**kw:fifth if table=="banca_usuarios" else None)
    monkeypatch.setattr(module,"patch",lambda *a,**kw:None)
    client=module.app.test_client()
    client.get("/login")
    with client.session_transaction() as ses:
        csrf=ses["csrf_token"]
    res=client.post("/login",data={"csrf_token":csrf,"username":"avaliador05","password":"avaliador05"})
    assert res.status_code == 401


def test_quinta_nota_antiga_nao_entra_no_ranking(module,monkeypatch):
    def fake_select(table,*args,**kwargs):
        if table=="banca_equipes":
            return [{"id":1,"nome":"Datacore","estande":"A22","bloqueado":False}]
        return [{"id":i,"username":"avaliador%02d"%i,"nome_exibicao":str(i)} for i in range(1,6)]
    monkeypatch.setattr(module,"select",fake_select)
    notes=[{"equipe_id":1,"usuario_id":i,"c1":4,"c2":4,"c3":4} for i in range(1,5)]
    notes.append({"equipe_id":1,"usuario_id":5,"c1":0,"c2":0,"c3":0})
    monkeypatch.setattr(module,"all_rows",lambda table,**kw:notes)
    ranking=module.build_ranking()["ranking"][0]
    assert ranking["evaluations"]==4
    assert ranking["average"]==12
    assert ranking["complete"] is True
