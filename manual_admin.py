"""Contingencia NEXT 2026: PDF offline, leitura de foto e limpeza auditavel."""
import hashlib
import io
import logging
import secrets
import zipfile
from urllib.error import HTTPError,URLError
from urllib.parse import quote
from urllib.request import Request,urlopen

from flask import Response,abort,flash,jsonify,redirect,render_template,request,url_for
from itsdangerous import URLSafeTimedSerializer,BadSignature,SignatureExpired
from PIL import Image,ImageOps,UnidentifiedImageError
from manual_forms import render_pdf,read_marks

log=logging.getLogger("next2026.manual")
BUCKET="banca-comprovantes"
PARTICIPANTS=("A1","A2","A3","D1","D2")
VALID={k:({"correto","erro","nao_testado"} if k.startswith("A") else
          {"alerta","falso_aceite","sem_leitura"}) for k in PARTICIPANTS}

def install_manual_routes(app,admin_required,one,select,rpc,get_user,base_url,secret_key,evaluator_label,judge_profiles):
    signer=URLSafeTimedSerializer(app.config["SECRET_KEY"],salt="next-2026-manual-upload-v1")
    def storage(method,path,payload=None,content_type=None):
        if not base_url or not secret_key:raise RuntimeError("Supabase indisponivel")
        headers={"apikey":secret_key}
        if secret_key.count(".")==2:headers["Authorization"]="Bearer "+secret_key
        if content_type:headers["Content-Type"]=content_type
        url=base_url.rstrip("/")+"/storage/v1/object/"+quote(path,safe="/")
        try:
            with urlopen(Request(url,data=payload,headers=headers,method=method),timeout=20) as response:
                return response.read()
        except (HTTPError,URLError,TimeoutError) as exc:
            log.error("Falha no Storage %s %s",method,path)
            raise RuntimeError("Falha no armazenamento privado do Supabase") from exc

    def judges():
        return [u for u in select("banca_usuarios",{"papel":"eq.judge","ativo":"eq.true"},order="id.asc")
                if u.get("username") in judge_profiles]
    def pair(group,judge):
        try:gid=int(group);uid=int(judge)
        except (TypeError,ValueError):abort(400)
        t=one("banca_equipes",id=gid)
        u=one("banca_usuarios",id=uid)
        if not t or not u or u.role!="judge" or not u.active or u.username not in judge_profiles:abort(404)
        return t,u

    @app.get("/admin/contingencia")
    @admin_required
    def manual_dashboard():
        return render_template("contingencia.html",
            teams=select("banca_equipes",order="id.asc"),judges=judges(),
            recent=select("banca_importacoes",order="id.desc",limit=30))

    @app.get("/admin/contingencia/formulario.pdf")
    @admin_required
    def manual_pdf():
        team,judge=pair(request.args.get("group"),request.args.get("judge"))
        pdf=render_pdf(team.id,team.name,team.stand,judge.username,evaluator_label(judge))
        return Response(pdf,mimetype="application/pdf",headers={
            "Content-Disposition":f'attachment; filename="NEXT_2026_G{team.id:02d}_{judge.username}.pdf"',
            "Cache-Control":"no-store"})

    @app.get("/admin/contingencia/formularios.zip")
    @admin_required
    def manual_all_forms():
        teams=select("banca_equipes",order="id.asc");people=judges()
        output=io.BytesIO()
        with zipfile.ZipFile(output,"w",compression=zipfile.ZIP_DEFLATED) as archive:
            for t in teams:
                for u in people:
                    pdf=render_pdf(t["id"],t["nome"],t["estande"],u["username"],evaluator_label(type("Judge",(),{"username":u["username"],"display_name":u["nome_exibicao"]})()))
                    archive.writestr(f'Grupo_{t["id"]:02d}_{u["username"]}.pdf',pdf)
        return Response(output.getvalue(),mimetype="application/zip",headers={
            "Content-Disposition":'attachment; filename="NEXT_2026_Fichas_Offline.zip"',
            "Cache-Control":"no-store"})

    @app.post("/admin/contingencia/scan")
    @admin_required
    def manual_scan():
        team,judge=pair(request.form.get("group"),request.form.get("judge"))
        photo=request.files.get("photo")
        if not photo:return jsonify(ok=False,error="Selecione uma fotografia da ficha preenchida."),400
        raw=photo.read(8*1024*1024+1)
        if len(raw)>8*1024*1024:return jsonify(ok=False,error="Foto acima do limite de 8 MB."),400
        try:
            img=Image.open(io.BytesIO(raw));img.verify()
            img=Image.open(io.BytesIO(raw))
            img=ImageOps.exif_transpose(img).convert("RGB")
            if min(img.size)<550:raise ValueError()
            img.thumbnail((2800,2800))
            buf=io.BytesIO();img.save(buf,format="JPEG",quality=88,optimize=True)
            data=buf.getvalue()
        except (UnidentifiedImageError,OSError,ValueError):
            return jsonify(ok=False,error="Imagem pequena ou invalida. Fotografe a folha inteira."),400
        digest=hashlib.sha256(data).hexdigest()
        try:marks=read_marks(data)
        except ValueError as exc:
            marks={"answers":{},"warnings":[str(exc)],"recognized":0,"total":10}
        path=f'2026/{team.id}/{secrets.token_urlsafe(15)}.jpg'
        try:storage("POST",BUCKET+"/"+path,data,"image/jpeg")
        except RuntimeError as exc:return jsonify(ok=False,error=str(exc)),503
        token=signer.dumps({"path":path,"sha256":digest,"group":team.id,"judge":judge.id})
        return jsonify(ok=True,token=token,recognized=marks["recognized"],total=marks["total"],
            warnings=marks["warnings"],answers=marks["answers"],
            group=team.name,judge=judge.display_name)

    @app.post("/admin/contingencia/confirmar")
    @admin_required
    def manual_confirm():
        try:evidence=signer.loads(request.form.get("token",""),max_age=3600)
        except (BadSignature,SignatureExpired):
            return jsonify(ok=False,error="Digitalizacao expirada. Reenvie a foto."),400
        team,judge=pair(request.form.get("group"),request.form.get("judge"))
        if team.id!=evidence["group"] or judge.id!=evidence["judge"]:
            return jsonify(ok=False,error="Avaliador, equipe e fotografia nao coincidem."),400
        if request.form.get("verified")!="on":
            return jsonify(ok=False,error="Confirme que revisou a fotografia e todas as marcacoes."),400
        obs={k:request.form.get(k) for k in PARTICIPANTS}
        if any(obs[k] not in VALID[k] for k in PARTICIPANTS):
            return jsonify(ok=False,error="Confira todos os cinco participantes."),400
        try:
            c1,c2,c3=[int(request.form.get("c"+str(i))) for i in (1,2,3)]
            available=int(request.form.get("available"))
            used=int(request.form.get("used"))
        except (ValueError,TypeError):
            return jsonify(ok=False,error="Preencha notas e quantidade de cameras."),400
        if not all(0<=x<=5 for x in (c1,c2,c3)) or not 1<=used<=available<=2:
            return jsonify(ok=False,error="Notas ou cameras invalidas."),400
        notes=request.form.get("notes","").strip()[:3000]
        replacing=request.form.get("replace")=="true"
        if replacing and request.form.get("replace_confirmation")!="SUBSTITUIR":
            return jsonify(ok=False,error="Digite SUBSTITUIR para sobrescrever a nota anterior."),400
        if one("banca_avaliacoes",equipe_id=team.id,usuario_id=judge.id) and not replacing:
            return jsonify(ok=False,error="Avaliacao existente. Marque e confirme a substituicao."),409
        try:
            rpc("banca_importar_manual",{
                "p_admin":get_user().id,"p_equipe":team.id,"p_usuario":judge.id,
                "p_c1":c1,"p_c2":c2,"p_c3":c3,"p_disponiveis":available,
                "p_usadas":used,"p_obs":obs,"p_notas":notes,
                "p_foto_path":evidence["path"],"p_foto_sha256":evidence["sha256"],
                "p_substituir":replacing})
        except Exception:
            return jsonify(ok=False,error="Supabase recusou a gravacao. Confira a migracao SQL e o bloqueio da equipe."),503
        raw=c1+c2+c3
        adjusted=min(15,raw*(1.1 if used==1 else 1))
        return jsonify(ok=True,total=raw,adjusted_total=round(adjusted,2),
                       group=team.name,judge=judge.display_name)

    @app.get("/admin/contingencia/foto/<int:import_id>")
    @admin_required
    def manual_photo(import_id):
        entry=one("banca_importacoes",id=import_id)
        if not entry:abort(404)
        try:data=storage("GET",BUCKET+"/"+entry.foto_path)
        except RuntimeError:abort(503)
        return Response(data,mimetype="image/jpeg",headers={"Cache-Control":"no-store"})

    @app.post("/admin/historico/limpar")
    @admin_required
    def manual_clear_history():
        from werkzeug.security import check_password_hash
        u=get_user()
        if not check_password_hash(u.password_hash,request.form.get("password","")):
            flash("Senha administrativa incorreta; nenhuma nota apagada.","error")
            return redirect(url_for("manual_dashboard"))
        if request.form.get("confirmation")!="APAGAR NOTAS":
            flash("Digite APAGAR NOTAS para confirmar.","error")
            return redirect(url_for("manual_dashboard"))
        try:team=None if request.form.get("group")=="all" else int(request.form.get("group"))
        except (ValueError,TypeError):abort(400)
        if team is not None and not 1<=team<=9:abort(400)
        try:result=rpc("banca_limpar_avaliacoes",{
            "p_admin":u.id,"p_equipe":team,"p_confirmacao":"APAGAR NOTAS"})
        except Exception:
            flash("Nao foi possivel limpar as notas; confira a migracao no Supabase.","error")
            return redirect(url_for("manual_dashboard"))
        flash(f'{result.get("apagadas",0)} notas removidas. Auditoria e fotografias preservadas.',"success")
        return redirect(url_for("manual_dashboard"))
