"""Formulário de contingência em PDF e leitura óptica assistida de círculos."""
from io import BytesIO
from math import hypot
from PIL import Image, ImageOps, UnidentifiedImageError
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

CORNERS=[(50,775),(545,775),(50,70),(545,70)]
ROWS=[
 ("A1",["correto","erro","nao_testado"],[(330,640),(430,640),(530,640)]),
 ("A2",["correto","erro","nao_testado"],[(330,602),(430,602),(530,602)]),
 ("A3",["correto","erro","nao_testado"],[(330,564),(430,564),(530,564)]),
 ("D1",["alerta","falso_aceite","sem_leitura"],[(330,526),(430,526),(530,526)]),
 ("D2",["alerta","falso_aceite","sem_leitura"],[(330,488),(430,488),(530,488)]),
 ("c1",list(range(6)),[(310+43*i,427) for i in range(6)]),
 ("c2",list(range(6)),[(310+43*i,389) for i in range(6)]),
 ("c3",list(range(6)),[(310+43*i,351) for i in range(6)]),
 ("used",[1,2],[(380,266),(470,266)])
]

def render_pdf(group_id,group_name,stand,username,judge_name):
    out=BytesIO();c=canvas.Canvas(out,pagesize=A4,pageCompression=1)
    c.setTitle("NEXT 2026 - Ficha de contingencia - grupo "+str(group_id))
    c.setFillColorRGB(.94,.07,.33);c.rect(0,809,595,33,stroke=0,fill=1)
    c.setFillColorRGB(1,1,1);c.setFont("Helvetica-Bold",16)
    c.drawString(39,819,"NEXT 2026  |  BANCA DE AVALIACAO")
    c.setFillColorRGB(0,0,0)
    for x,y in CORNERS:c.rect(x-7,y-7,14,14,stroke=0,fill=1)
    c.setFont("Helvetica-Bold",17);c.drawString(80,777,"FICHA DE CONTINGENCIA - V1")
    c.setFont("Helvetica",10);c.drawString(80,758,"Preencher no papel em caso de falha de internet ou sistema.")
    c.setFont("Helvetica-Bold",12)
    c.drawString(55,730,"GRUPO %02d: %s    ESTANDE: %s"%(group_id,group_name[:45],stand))
    c.setFont("Helvetica",11);c.drawString(55,708,"AVALIADOR: "+judge_name[:70])
    c.setFont("Helvetica",9);c.drawString(55,690,"IDENTIFICACAO: %s | G%02d | N2026-OMR1"%(username,group_id))
    c.line(55,679,540,679)
    c.setFont("Helvetica-Bold",11);c.drawString(55,662,"1. PARTICIPANTES - PREENCHA 1 BOLINHA POR LINHA")
    c.setFont("Helvetica",9)
    for x,label in [(300,"CERTO / REJEITOU"),(410,"ERRO / ACEITOU"),(511,"NAO TESTOU")]:
        c.drawCentredString(x+29,649,label)
    labels={"A1":"A1 - Autorizado","A2":"A2 - Autorizado","A3":"A3 - Autorizado",
            "D1":"D1 - Desconhecido equipe","D2":"D2 - Desconhecido plateia"}
    for k,_,points in ROWS[:5]:
        y=points[0][1];c.setStrokeColorRGB(.72,.74,.78);c.line(55,y-20,540,y-20)
        c.setFillColorRGB(0,0,0);c.setFont("Helvetica-Bold",10);c.drawString(62,y-4,labels[k])
        for x,yy in points:
            c.setStrokeColorRGB(0,0,0);c.setLineWidth(1.2);c.circle(x,yy,9,stroke=1,fill=0)
    c.setFont("Helvetica-Bold",11);c.drawString(55,453,"2. NOTAS - MARQUE 1 NUMERO POR CRITERIO")
    for k,_,points in ROWS[5:8]:
        y=points[0][1];c.setFont("Helvetica-Bold",10);c.setFillColorRGB(0,0,0)
        c.drawString(62,y-3,k.upper()+{"c1":" - Reconhecimento","c2":" - Rejeicao","c3":" - Robustez"}[k])
        for n,(x,yy) in enumerate(points):
            c.circle(x,yy,9,stroke=1,fill=0)
            c.setFont("Helvetica-Bold",8);c.drawCentredString(x,yy-20,str(n))
    c.setFont("Helvetica-Bold",11);c.drawString(55,324,"3. CAMERAS - MARQUE SOMENTE AS UTILIZADAS")
    c.setFont("Helvetica-Bold",10)
    c.drawString(62,297,"Disponibilizadas: 2 (fixas para todos os grupos)")
    for k,_,points in ROWS[8:]:
        y=points[0][1];c.setFont("Helvetica",10)
        c.drawString(62,y-4,"Utilizadas")
        for num,(x,yy) in zip((1,2),points):
            c.circle(x,yy,9,stroke=1,fill=0)
            c.setFont("Helvetica-Bold",8);c.drawCentredString(x,yy-19,str(num))
    c.setFont("Helvetica-Bold",10);c.drawString(55,226,"4. OCORRENCIAS / JUSTIFICATIVAS (erros ou notas 0 a 2)")
    c.setStrokeColorRGB(.55,.58,.64)
    for y in (204,182,160):c.line(55,y,540,y)
    c.setFillColorRGB(0,0,0);c.setFont("Helvetica",9)
    c.drawString(55,132,"Assinatura do avaliador: ____________________________________________")
    c.setFont("Helvetica-Bold",9);c.drawString(55,111,"LEITURA POR FOTO - INSTRUCOES:")
    c.setFont("Helvetica",9)
    c.drawString(55,97,"Use caneta escura. PREENCHA completamente um circulo por linha.")
    c.drawString(55,85,"Nao marque duas opcoes. Fotografe a folha inteira, em boa luz.")
    c.drawString(90,55,"A leitura e sugestao; a coordenacao deve revisar antes de salvar.")
    c.showPage();c.save()
    return out.getvalue()

def locate(img):
    w,h=img.size;width=min(w,850)
    if w!=width:img=img.resize((width,round(h*width/w)),Image.Resampling.BILINEAR)
    w,h=img.size;pix=img.load()
    table=[[0]*(w+1) for _ in range(h+1)]
    for y in range(h):
        line=table[y+1];above=table[y];running=0
        for x in range(w):
            r,g,b=pix[x,y];running+=int(r<100 and g<100 and b<100)
            line[x+1]=above[x+1]+running
    radius=max(5,round(w*.010))
    regions=[(.02,.35,.02,.29),(.65,.98,.02,.29),(.02,.35,.71,.98),(.65,.98,.71,.98)]
    corners=[]
    for xl,xh,yl,yh in regions:
        best=(-1,None)
        for y in range(max(radius,int(yl*h)),min(h-radius,int(yh*h)),max(2,radius//2)):
            for x in range(max(radius,int(xl*w)),min(w-radius,int(xh*w)),max(2,radius//2)):
                x0,x1=x-radius,x+radius;y0,y1=y-radius,y+radius
                dark=table[y1+1][x1+1]-table[y0][x1+1]-table[y1+1][x0]+table[y0][x0]
                density=dark/float((2*radius+1)**2)
                expectedx=(.084 if xl<.5 else .916)*w
                expectedy=(.080 if yl<.5 else .920)*h
                score=density-.05*hypot((x-expectedx)/w,(y-expectedy)/h)
                if score>best[0]:best=(score,(x,y,density))
        if not best[1] or best[1][2]<.55:
            raise ValueError("Nao foi possivel localizar quatro marcas pretas. Fotografe a folha inteira, de frente.")
        corners.append(best[1][:2])
    lt,rt,lb,rb=corners
    if rt[0]-lt[0]<w*.45 or rb[0]-lb[0]<w*.45 or lb[1]-lt[1]<h*.5 or rb[1]-rt[1]<h*.5:
        raise ValueError("Nao foi possivel alinhar a foto. Nao recorte os cantos.")
    return img.convert("L"),corners

def read_marks(source):
    if len(source)>8*1024*1024:raise ValueError("Foto acima de 8 MB.")
    try:
        image=Image.open(BytesIO(source));image.verify()
        image=Image.open(BytesIO(source))
        image=ImageOps.exif_transpose(image).convert("RGB")
    except (UnidentifiedImageError,OSError,ValueError):
        raise ValueError("Imagem invalida: use JPG, PNG ou WEBP.")
    if min(image.size)<550:raise ValueError("Foto pequena: minimo de 550 pixels no lado menor.")
    image,markers=locate(image)
    lt,rt,lb,rb=markers;pix=image.load()
    radius=max(3,round(min(hypot(rt[0]-lt[0],rt[1]-lt[1]),hypot(rb[0]-lb[0],rb[1]-lb[1]))*4/495))
    answers={};warnings=[];confidences={}
    for field,options,points in ROWS:
        ratios=[]
        for x,y in points:
            a=(x-50)/495;b=(775-y)/705
            px=(1-b)*((1-a)*lt[0]+a*rt[0])+b*((1-a)*lb[0]+a*rb[0])
            py=(1-b)*((1-a)*lt[1]+a*rt[1])+b*((1-a)*lb[1]+a*rb[1])
            cx,cy=round(px),round(py);dark=total=0
            for dy in range(-radius,radius+1):
                for dx in range(-radius,radius+1):
                    if dx*dx+dy*dy>radius*radius:continue
                    xx=cx+dx;yy=cy+dy
                    if 0<=xx<image.width and 0<=yy<image.height:
                        dark+=int(pix[xx,yy]<135);total+=1
            ratios.append(dark/max(1,total))
        candidates=[i for i,v in enumerate(ratios) if v>=.19]
        if len(candidates)==1:answers[field]=options[candidates[0]]
        else:
            answers[field]=None
            warnings.append(field+(": marca fraca ou ausente" if not candidates else ": multiplas marcas"))
        confidences[field]=[round(v,3) for v in ratios]
    # Disponibilizadas = 2 é constante, NÃO uma opção lida da fotografia.
    # Fichas antigas com esse campo também são interpretadas como 2.
    answers["available"] = 2
    return {"answers":answers,"warnings":warnings,
            "scores":confidences,"recognized":sum(v is not None for v in answers.values()),
            "total":len(ROWS) + 1}
