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
    assert ok.json['adjusted_total']==14.3
    assert saved[0][1]['p_notas']==''
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
    assert 'class="banca-judge-checkbox"' in login_page


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
    assert result["recognized"]==1  # A única informação fixa é "2 disponibilizadas".
    assert result["answers"]["available"]==2
    assert all(v is None for k,v in result["answers"].items() if k!="available")


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

def test_bonus_uma_camera_respeita_teto_e_zero(module):
    from types import SimpleNamespace
    assert module.weighted_units(8,1)==88
    assert module.weighted_units(8,2)==80
    assert module.weighted_units(13,1)==143
    assert module.weighted_units(15,1)==150
    assert module.weighted_units(0,1)==0
    evaluation=SimpleNamespace(c1=3,c2=3,c3=2,cameras_used=1)
    assert module.score(evaluation)==8.8


def test_ranking_por_media_ponderada_prioriza_uma_camera(module,monkeypatch):
    teams=[{"id":1,"nome":"Datacore","estande":"A22","bloqueado":False},
           {"id":2,"nome":"OutBox","estande":"A23","bloqueado":False}]
    judges=[{"id":i,"username":"avaliador%02d"%i,"nome_exibicao":str(i)} for i in range(1,5)]
    monkeypatch.setattr(module,"select",lambda table,*args,**kwargs:
        teams if table=="banca_equipes" else judges)
    votes=[
        {"usuario_id":1,"equipe_id":1,"c1":3,"c2":3,"c3":2,"cameras_usadas":1},
        {"usuario_id":2,"equipe_id":2,"c1":3,"c2":3,"c3":2,"cameras_usadas":2},
    ]
    monkeypatch.setattr(module,"all_rows",lambda table,**kwargs:votes)
    ranking=module.build_ranking()["ranking"]
    assert [i["team_id"] for i in ranking]==[1,2]
    assert ranking[0]["average"]==8.8
    assert ranking[0]["base_average"]==8.0
    assert ranking[0]["one_camera_evaluations"]==1
    assert ranking[1]["average"]==8.0


def test_sem_observacoes_tecnicas_obrigatorias(module,monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(module,"get_user",lambda:SimpleNamespace(
        id=3,role="judge",username="avaliador03",active=True))
    monkeypatch.setattr(module,"get_team",lambda n:SimpleNamespace(id=n,locked=False))
    calls=[]
    monkeypatch.setattr(module,"rpc",lambda n,payload:calls.append(payload))
    client=module.app.test_client()
    with client.session_transaction() as sess:sess["csrf_token"]="known"
    data={"csrf_token":"known","c1":"1","c2":"2","c3":"3",
        "available":"2","used":"1","A1":"erro","A2":"correto","A3":"correto",
        "D1":"alerta","D2":"sem_leitura"}
    r=client.post("/evaluate/1",data=data,headers={"X-Requested-With":"XMLHttpRequest"})
    assert r.status_code==200
    assert r.json["ok"] is True
    assert calls[0]["p_notas"]==""


def test_ranking_varios_grupos_ao_vivo_sem_keyerror(module,monkeypatch):
    """Regressao do erro 500: comparar 2+ equipes nao pode ler _sum apagado."""
    from types import SimpleNamespace
    teams=[
        {"id":1,"nome":"Datacore","estande":"A22","bloqueado":False},
        {"id":2,"nome":"OutBox","estande":"A23","bloqueado":False},
        {"id":3,"nome":"Auditix AI","estande":"A24","bloqueado":False},
        {"id":4,"nome":"Next Level","estande":"A25","bloqueado":False},
        {"id":5,"nome":"DataKeeper","estande":"A26","bloqueado":False}
    ]
    judges=[{"id":i,"username":f"avaliador{i:02d}","nome_exibicao":str(i)} for i in range(1,5)]
    monkeypatch.setattr(module,"select",lambda table,*args,**kwargs:
        teams if table=="banca_equipes" else judges)
    # A/B empate com quantidades distintas; C menor pontuacao; D ainda sem notas.
    votes=[
        {"equipe_id":1,"usuario_id":1,"c1":4,"c2":4,"c3":4,"cameras_usadas":2},
        {"equipe_id":2,"usuario_id":2,"c1":4,"c2":4,"c3":4,"cameras_usadas":2},
        {"equipe_id":2,"usuario_id":3,"c1":4,"c2":4,"c3":4,"cameras_usadas":2},
        {"equipe_id":3,"usuario_id":4,"c1":2,"c2":2,"c3":2,"cameras_usadas":1},
        {"equipe_id":5,"usuario_id":1,"c1":1,"c2":1,"c3":1,"cameras_usadas":2},
    ]
    monkeypatch.setattr(module,"all_rows",lambda table,**kw:votes)
    ranking=module.build_ranking()["ranking"]
    assert [r["team_id"] for r in ranking]==[1,2,3,5,4]
    assert [r["rank"] for r in ranking]==[1,1,3,4,None]
    assert all("_sum" not in row for row in ranking)
    assert ranking[2]["average"]==6.6
    # Renderizacao da pagina completa, com mais de uma equipe pontuada.
    monkeypatch.setattr(module,"get_user",lambda:SimpleNamespace(
        id=99,username="coordenacao",role="admin",active=True,display_name="Coordenação"))
    client=module.app.test_client()
    page=client.get("/admin/results")
    assert page.status_code==200
    assert b"Ranking provis" in page.data
    api=client.get("/api/results")
    assert api.status_code==200
    assert [r["rank"] for r in api.json["ranking"]]==[1,1,3,4,None]


def test_exclusao_administrativa_sem_backup_ou_senha_extra(module,monkeypatch):
    from types import SimpleNamespace
    user=SimpleNamespace(id=1,username="coordenacao",role="admin",active=True)
    monkeypatch.setattr(module,"get_user",lambda:user)
    calls=[]
    def delete_rpc(name,payload):
        calls.append((name,payload))
        return {"apagadas":3}
    monkeypatch.setattr(module,"rpc",delete_rpc)
    client=module.app.test_client()
    with client.session_transaction() as session: session["csrf_token"]="valid-token"
    response=client.post("/admin/historico/limpar",data={
        "csrf_token":"valid-token","group":"all","confirmation":"APAGAR NOTAS"
    })
    assert response.status_code==302
    assert calls==[("banca_limpar_avaliacoes",{
        "p_admin":1,"p_equipe":None,"p_confirmacao":"APAGAR NOTAS"
    })]


def test_exclusao_exige_token_de_confirmacao_no_servidor(module,monkeypatch):
    from types import SimpleNamespace
    user=SimpleNamespace(id=1,username="coordenacao",role="admin",active=True)
    monkeypatch.setattr(module,"get_user",lambda:user)
    calls=[]
    monkeypatch.setattr(module,"rpc",lambda *args: calls.append(args))
    client=module.app.test_client()
    with client.session_transaction() as session: session["csrf_token"]="valid-token"
    response=client.post("/admin/historico/limpar",data={
        "csrf_token":"valid-token","group":"all"
    })
    assert response.status_code==302
    assert calls==[]



def test_rpc_limpar_historico_ausente_mostra_sql_correto(module,monkeypatch):
    import io
    import json
    import pytest
    from urllib.error import HTTPError
    monkeypatch.setattr(module,"SUPABASE_URL","https://iwfqmdsrourtdvrgiums.supabase.co")
    monkeypatch.setattr(module,"SUPABASE_KEY","sb_secret_test")
    def fake_urlopen(req,timeout=12):
        payload=json.dumps({"code":"PGRST202","message":"Could not find the function public.banca_limpar_avaliacoes"}).encode()
        raise HTTPError(req.full_url,404,"Not Found",{},io.BytesIO(payload))
    monkeypatch.setattr(module,"urlopen",fake_urlopen)
    with pytest.raises(module.SupabaseError,match="corrigir_limpeza_historico"):
        module.rpc("banca_limpar_avaliacoes",{
            "p_admin":1,"p_equipe":None,"p_confirmacao":"APAGAR NOTAS"
        })


def test_exclusao_erro_supabase_informa_migracao_sem_apagar(module,monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(module,"get_user",lambda:SimpleNamespace(
        id=1,username="coordenacao",role="admin",active=True))
    def broken_rpc(*args,**kwargs):
        raise module.SupabaseError(
            "A função de limpeza não existe. Execute 20261012_corrigir_limpeza_historico.sql")
    monkeypatch.setattr(module,"rpc",broken_rpc)
    client=module.app.test_client()
    with client.session_transaction() as sess:sess["csrf_token"]="token"
    response=client.post("/admin/historico/limpar",data={
        "csrf_token":"token","group":"all","confirmation":"APAGAR NOTAS"
    })
    assert response.status_code==302
    with client.session_transaction() as sess:
        alerts=sess.get("_flashes",[])
    assert any("20261012_corrigir_limpeza_historico.sql" in msg for _category,msg in alerts)


def test_erro_21000_na_limpeza_mostra_detalhe_e_orienta_diagnostico(module,monkeypatch):
    import io
    import json
    import pytest
    from urllib.error import HTTPError
    monkeypatch.setattr(module,"SUPABASE_URL","https://iwfqmdsrourtdvrgiums.supabase.co")
    monkeypatch.setattr(module,"SUPABASE_KEY","sb_secret_test")
    def fake_urlopen(req,timeout=12):
        payload=json.dumps({
            "code":"21000",
            "message":"more than one row returned by a subquery used as an expression",
            "details":"contexto de teste de cardinalidade"
        }).encode()
        raise HTTPError(req.full_url,400,"Bad Request",{},io.BytesIO(payload))
    monkeypatch.setattr(module,"urlopen",fake_urlopen)
    with pytest.raises(module.SupabaseError,match="Falha SQL 21000") as failure:
        module.rpc("banca_limpar_avaliacoes",{
            "p_admin":1,"p_equipe":None,"p_confirmacao":"APAGAR NOTAS"
        })
    assert "more than one row returned" in str(failure.value)
    assert "20261013_diagnosticar_erro_21000.sql" in str(failure.value)

def test_erro_21000_delete_sem_where_orienta_migracao_correta(module, monkeypatch):
    import io
    import json
    import pytest
    from urllib.error import HTTPError
    monkeypatch.setattr(module, "SUPABASE_URL", "https://iwfqmdsrourtdvrgiums.supabase.co")
    monkeypatch.setattr(module, "SUPABASE_KEY", "sb_secret_test")
    def fail_delete(req, timeout=12):
        response=json.dumps({"code":"21000","message":"DELETE requires a WHERE clause"}).encode()
        raise HTTPError(req.full_url,400,"Bad Request",{},io.BytesIO(response))
    monkeypatch.setattr(module,"urlopen",fail_delete)
    with pytest.raises(module.SupabaseError,match="20261013_corrigir_delete_com_where.sql"):
        module.rpc("banca_limpar_avaliacoes",{
            "p_admin":1,"p_equipe":None,"p_confirmacao":"APAGAR NOTAS"
        })



def test_disponibilizadas_sempre_duas_mesmo_se_navegador_envia_uma(module,monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(module,"get_user",lambda:SimpleNamespace(
        id=2,username="avaliador01",role="judge",active=True))
    monkeypatch.setattr(module,"get_team",lambda n:SimpleNamespace(id=n,locked=False))
    saved=[]
    monkeypatch.setattr(module,"rpc",lambda name,payload:saved.append(payload))
    client=module.app.test_client()
    with client.session_transaction() as sess:sess["csrf_token"]="valid"
    data={"csrf_token":"valid","c1":"4","c2":"3","c3":"5","available":"1","used":"2",
          "A1":"correto","A2":"correto","A3":"correto","D1":"alerta","D2":"alerta"}
    resp=client.post("/evaluate/1",data=data,headers={"X-Requested-With":"XMLHttpRequest"})
    assert resp.status_code==200
    assert saved[0]["p_disponiveis"]==2
    assert saved[0]["p_usadas"]==2
    data.pop("available")  # Campo indisponível na interface nova.
    data["used"]="1"
    resp=client.post("/evaluate/1",data=data,headers={"X-Requested-With":"XMLHttpRequest"})
    assert resp.status_code==200
    assert saved[1]["p_disponiveis"]==2
    assert saved[1]["p_usadas"]==1
    assert resp.json["bonus_percent"]==10


def test_pdf_contingencia_duas_fixas_nao_tem_bolinha_de_disponiveis():
    from manual_forms import ROWS
    assert [field for field,_,_ in ROWS if field=="available"]==[]
    assert [field for field,_,_ in ROWS if field=="used"]==["used"]

def test_creditos_do_desenvolvedor_no_rodape_de_todas_as_paginas(module):
    client=module.app.test_client()
    response=client.get("/login")
    assert response.status_code == 200
    page=response.get_data(as_text=True)
    assert "Prof. Dr. Erick T. Yamamoto" in page
    assert "SAYAMA GROUP" in page
    assert 'class="footer-credit"' in page



def test_portal_direto_areas_de_avaliador_e_coordenacao_sem_consulta_supabase(module,monkeypatch):
    def no_db(*args,**kwargs):
        raise AssertionError("As telas de entrada devem abrir sem banco")
    monkeypatch.setattr(module,"one",no_db)
    client=module.app.test_client()
    for path in ("/","/login","/avaliador","/coordenacao"):
        response=client.get(path)
        assert response.status_code==200
        page=response.get_data(as_text=True)
        assert 'type="checkbox"' in page
        assert "Scrum Master / Coordenação" in page
        assert "Avaliador 4" in page
    admin=client.get("/coordenacao").get_data(as_text=True)
    assert 'data-portal-default="coordenacao"' in admin


def test_portal_checkbox_somente_um_avaliador(module,monkeypatch):
    from types import SimpleNamespace
    selected=SimpleNamespace(id=7,username="avaliador02",role="judge",
        active=True,locked_until=None,failed_attempts=0)
    monkeypatch.setattr(module,"init_admin",lambda:None)
    monkeypatch.setattr(module,"one",lambda table,**kwargs:selected)
    monkeypatch.setattr(module,"patch",lambda *args,**kwargs:None)
    client=module.app.test_client()
    page=client.get("/").get_data(as_text=True)
    # Nenhuma senha para o avaliador, mas a coordenação conserva a própria.
    assert "banca-judge-pass" not in page
    assert "banca-admin-pass" in page
    assert "Começar a avaliar" in page
    with client.session_transaction() as sess:csrf=sess["csrf_token"]
    missing=client.post("/login",data={"csrf_token":csrf,"portal_role":"judge"})
    assert missing.status_code==400
    double=client.post("/login",data={
        "csrf_token":csrf,"portal_role":"judge",
        "username":["avaliador01","avaliador02"]
    })
    assert double.status_code==400
    valid=client.post("/login",data={
        "csrf_token":csrf,"portal_role":"judge","username":"avaliador02"
    })
    assert valid.status_code==302
    assert "/dashboard" in valid.headers["Location"]
    with client.session_transaction() as sess:
        assert sess["uid"]==7
        csrf=sess["csrf_token"]
    # Selecionar um avaliador como "admin" jamais concede acesso administrativo.
    wrong_role=client.post("/login",data={
        "csrf_token":csrf,"portal_role":"admin","username":"avaliador02"
    })
    assert wrong_role.status_code==401


def test_portal_coordenacao_preserva_senha_e_papel_admin(module,monkeypatch):
    from werkzeug.security import generate_password_hash
    from types import SimpleNamespace
    admin=SimpleNamespace(id=1,username="coordenacao",role="admin",
        password_hash=generate_password_hash("admin-test-password"),
        active=True,locked_until=None,failed_attempts=0)
    monkeypatch.setattr(module,"init_admin",lambda:None)
    monkeypatch.setattr(module,"one",lambda table,**kwargs:admin)
    monkeypatch.setattr(module,"patch",lambda *args,**kwargs:None)
    client=module.app.test_client()
    client.get("/coordenacao")
    with client.session_transaction() as sess:csrf=sess["csrf_token"]
    ok=client.post("/login",data={
        "csrf_token":csrf,"portal_role":"admin","username":"coordenacao",
        "password":"admin-test-password"
    })
    assert ok.status_code==302
    assert "/dashboard" in ok.headers["Location"]


def test_portal_sem_senha_nao_concede_admin_por_troca_de_papel(module, monkeypatch):
    from types import SimpleNamespace
    from werkzeug.security import generate_password_hash
    admin=SimpleNamespace(
        id=1, username="coordenacao", role="admin", active=True,
        password_hash=generate_password_hash("senha-administrativa-forte"),
        failed_attempts=0,locked_until=None
    )
    monkeypatch.setattr(module, "init_admin", lambda:None)
    monkeypatch.setattr(module, "one", lambda table,**kwargs:admin)
    monkeypatch.setattr(module, "patch", lambda *args,**kwargs:None)
    client=module.app.test_client()
    client.get("/")
    with client.session_transaction() as sess: csrf=sess["csrf_token"]
    # Sem senha ou no papel de avaliador, não deve aceitar a coordenação.
    assert client.post("/login",data={
        "csrf_token":csrf,"portal_role":"admin","username":"coordenacao"
    }).status_code==401
    assert client.post("/login",data={
        "csrf_token":csrf,"portal_role":"judge","username":"coordenacao"
    }).status_code==401
    assert client.post("/login",data={
        "csrf_token":csrf,"portal_role":"admin","username":"coordenacao",
        "password":"senha-administrativa-forte"
    }).status_code==302


def test_avaliador_inativo_nao_entra_sem_senha(module,monkeypatch):
    from types import SimpleNamespace
    inactive=SimpleNamespace(id=13,username="avaliador03",role="judge",
        active=False,locked_until=None,failed_attempts=0)
    monkeypatch.setattr(module,"one",lambda table,**kwargs:inactive)
    client=module.app.test_client()
    client.get("/")
    with client.session_transaction() as sess:csrf=sess["csrf_token"]
    assert client.post("/login",data={
        "csrf_token":csrf,"portal_role":"judge","username":"avaliador03"
    }).status_code==401


def test_portal_checkbox_sem_sobreposicao_e_sem_indicadores_duplicados(module):
    """Regression: avaliador possui apenas checkbox nativo e sem input full width."""
    app=module.app.test_client()
    page=app.get("/avaliador").get_data(as_text=True)
    assert page.count('class="banca-judge-checkbox"')==4
    assert 'banca-check-indicator' not in page
    assert "banca-judge-pass" not in page
    assert "banca-admin-pass" in page
    # CSS impede que input:not([type=radio]) trate checkbox como campo de texto.
    from pathlib import Path
    stylesheet=Path(__file__).resolve().parents[1] / "static" / "style.css"
    content=stylesheet.read_text(encoding="utf-8")
    assert "input:not([type=radio]):not([type=checkbox]),select,textarea{" in content
    assert "form label.banca-judge-choice input[type=checkbox].banca-judge-checkbox" in content


def test_supabase_indisponivel_orienta_reativacao_e_nao_executar_sql(module,monkeypatch):
    # Simular falha de banco em uma submissão: formulário continua com o CSS
    # local, opções dos avaliadores e alerta claro, sem renderizar página branca.
    def offline(*args,**kwargs):
        raise module.SupabaseError("Não foi possível conectar à API do Supabase")
    monkeypatch.setattr(module,"one",offline)
    client=module.app.test_client()
    portal=client.get("/login")
    assert portal.status_code==200
    with client.session_transaction() as sess: csrf=sess["csrf_token"]
    response=client.post("/login",data={
        "csrf_token":csrf,"portal_role":"judge","username":"avaliador01"
    })
    assert response.status_code==503
    html=response.get_data(as_text=True)
    assert "Supabase indisponível" in html
    assert "Não execute novamente schema.sql" in html
    assert "Quem está avaliando?" in html
    assert "static/style.css" in html
    assert 'class="banca-judge-checkbox"' in html
    assert "<style>" not in html


def test_erro_supabase_em_api_retorna_json_sem_refazer_consulta(module,monkeypatch):
    from flask import g
    # O processamento da página de resultado falhou antes da renderização.
    # A página de fallback não deve tocar no banco mais uma vez.
    def offline(*args,**kwargs):
        raise module.SupabaseError("Sem conexão ao Supabase")
    monkeypatch.setattr(module,"one",offline)
    client=module.app.test_client()
    with client.session_transaction() as sess:sess["uid"]=7
    result=client.get("/api/state",headers={"Accept":"application/json"})
    assert result.status_code==503
    assert result.is_json
    assert result.json["setup_required"] is True



def test_coordenador_curso_nao_gerencia_banca(module, monkeypatch):
    from types import SimpleNamespace
    coordinator=SimpleNamespace(id=25,username="coordenador.curso",role="course_coordinator",active=True)
    monkeypatch.setattr(module,"get_user",lambda:coordinator)
    client=module.app.test_client()
    for url in ("/dashboard","/evaluate/1","/admin/results","/admin/prenext","/api/results","/admin/contingencia"):
        assert client.get(url).status_code==403
    client.get("/coordenador-curso")
    with client.session_transaction() as sess:token=sess["csrf_token"]
    assert client.post("/admin/timers/1/reset",data={"csrf_token":token,"reason":"tentativa sem permissao"}).status_code==403


def test_ranking_pre_next_soma_somente_fichas_existentes(module,monkeypatch):
    from types import SimpleNamespace
    live={"ranking":[
      {"team_id":1,"name":"Datacore","stand":"A22","average":12,"evaluations":2,"expected":4,"complete":False},
      {"team_id":2,"name":"OutBox","stand":"A23","average":None,"evaluations":0,"expected":4,"complete":False}
    ],"expected_judges":4}
    monkeypatch.setattr(module,"build_ranking",lambda:live)
    monkeypatch.setattr(module,"select",lambda table,*args,**kwargs:[
      {"equipe_id":1,"pontos":36},{"equipe_id":2,"pontos":34}
    ] if table=="banca_prenext" else [])
    result=module.build_course_ranking()
    first=result["ranking"][0]
    second=result["ranking"][1]
    assert first["pre_score"]==36
    assert first["next_average"]==12
    assert first["total"]==48
    assert first["combined_rank"]==1
    assert first["status"]=="Arena parcial"
    assert second["total"] is None
    assert second["combined_rank"] is None
    assert result["official"] is False


def test_acesso_coordenador_exige_senha_e_segue_para_ranking(module,monkeypatch):
    from types import SimpleNamespace
    from werkzeug.security import generate_password_hash
    u=SimpleNamespace(id=22,username="coordenador.curso",role="course_coordinator",
        password_hash=generate_password_hash("senha-test-course"),active=True,
        locked_until=None,failed_attempts=0)
    monkeypatch.setattr(module,"one",lambda table,**kwargs:u)
    monkeypatch.setattr(module,"patch",lambda *args,**kwargs:None)
    client=module.app.test_client()
    page=client.get("/coordenador-curso").get_data(as_text=True)
    assert "Ranking Pré-NEXT + NEXT" in page
    with client.session_transaction() as sess:csrf=sess["csrf_token"]
    bad=client.post("/login",data={"csrf_token":csrf,"username":"coordenador.curso","portal_role":"course"})
    assert bad.status_code==401
    good=client.post("/login",data={"csrf_token":csrf,"username":"coordenador.curso",
                                  "portal_role":"course","password":"senha-test-course"})
    assert good.status_code==302
    assert "/curso/resultados" in good.headers["Location"]


def test_admin_nao_exibe_gerenciar_avaliadores(module):
    assert "Gerenciar avaliadores" not in module.app.jinja_loader.get_source(module.app.jinja_env,"dashboard.html")[0]
    assert "Coordenador de Curso" in module.app.jinja_loader.get_source(module.app.jinja_env,"dashboard.html")[0]


def test_cache_estatico_com_fichas_privadas(module):
    client=module.app.test_client()
    css=client.get("/static/style.css")
    assert css.status_code==200
    assert "public" in css.headers["Cache-Control"]
    login=client.get("/login")
    assert login.headers["Cache-Control"]=="no-store"


def test_login_com_gzip_mantem_segurança(module):
    import gzip
    client=module.app.test_client()
    res=client.get("/login",headers={"Accept-Encoding":"gzip"})
    assert res.status_code==200
    assert res.headers["Content-Encoding"]=="gzip"
    assert b"Scrum Master" in gzip.decompress(res.data)
    assert res.headers["Cache-Control"]=="no-store"


def test_dashboard_jurado_nao_baixa_notas_alheias(module,monkeypatch):
    from types import SimpleNamespace
    u=SimpleNamespace(id=11,username="avaliador01",role="judge",active=True,display_name="DATEN")
    monkeypatch.setattr(module,"get_user",lambda:u)
    queries=[]
    def fake_select(table,*args,**kwargs):
        queries.append((table,args))
        if table=="banca_equipes":
            return [{"id":1,"nome":"Datacore","estande":"A22","bloqueado":False}]
        if table=="banca_temporizadores":
            return [{"equipe_id":1,"estado":"idle","segundos_decorridos":0,
                     "duracao_segundos":300,"iniciado_em":None}]
        return []
    monkeypatch.setattr(module,"select",fake_select)
    r=module.app.test_client().get("/dashboard")
    assert r.status_code==200
    e=[q for q in queries if q[0]=="banca_avaliacoes"]
    assert len(e)==1 and e[0][1][0]["usuario_id"]=="eq.11"

def test_rascunho_equipe_identificado_sem_rede(module,monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(module,"get_user",lambda:SimpleNamespace(
        id=2,username="avaliador01",role="judge",active=True,display_name="DATEN"))
    monkeypatch.setattr(module,"get_team",lambda n:SimpleNamespace(
        id=n,name="Datacore",stand="A22",locked=False))
    monkeypatch.setattr(module,"get_timer",lambda n:SimpleNamespace(
        status="idle",elapsed_seconds=0,duration_seconds=300,started_at=None))
    monkeypatch.setattr(module,"one",lambda *args,**kwargs:None)
    response=module.app.test_client().get("/evaluate/1")
    assert response.status_code==200
    assert b'data-draft-key="avaliador01-1"' in response.data
    assert b'data-locked="false"' in response.data
