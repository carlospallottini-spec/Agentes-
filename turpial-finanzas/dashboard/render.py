"""Genera el dashboard HTML autocontenido (un archivo, Canvas puro, mobile-first).

Sin dependencias externas: ni CDN, ni fuentes remotas, ni librerías de gráficos.
Todo el reporte se embebe como JSON y se dibuja con Canvas 2D en el navegador.
"""
from __future__ import annotations

import json
from pathlib import Path

from config import REPORTS_DIR


def render_html(report: dict) -> str:
    """Devuelve el HTML completo del dashboard para un reporte de riesgo."""
    payload = json.dumps(report, ensure_ascii=False, default=str)
    company = report.get("company") or report.get("ticker", "")
    return _TEMPLATE.replace("/*__REPORT__*/null", payload).replace("__TITLE__", f"{company} · Turpial Finanzas")


def write_dashboard(report: dict, out_dir: Path | None = None) -> Path:
    """Escribe el dashboard a disco y devuelve la ruta."""
    out_dir = out_dir or REPORTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    ticker = report.get("ticker", "REPORTE")
    stamp = (report.get("generated_at") or "").replace(":", "").replace("-", "")[:13]
    path = out_dir / f"{ticker}_{stamp or 'latest'}.html"
    path.write_text(render_html(report), encoding="utf-8")
    return path


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>__TITLE__</title>
<style>
  :root{
    --bg:#0b0f1a; --panel:#121a2b; --panel2:#0f1626; --line:#1f2b45;
    --txt:#e8edf7; --muted:#8a98b5; --accent:#39d98a; --accent2:#ffd166; --bad:#ff5d73;
    --ancla:#39d98a; --flex:#ffd166; --alerta:#ff5d73;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--txt);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    -webkit-font-smoothing:antialiased;line-height:1.5}
  .wrap{max-width:760px;margin:0 auto;padding:18px 16px 64px}
  header.top{display:flex;flex-direction:column;gap:4px;margin-bottom:8px}
  .brand{font-size:12px;letter-spacing:.18em;text-transform:uppercase;color:var(--accent)}
  h1{font-size:22px;margin:2px 0 0}
  .sub{color:var(--muted);font-size:13px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:16px;
    padding:16px;margin-top:14px}
  .gauge-wrap{display:flex;flex-direction:column;align-items:center;gap:6px}
  canvas{display:block;width:100%;height:auto}
  .score-band{font-size:13px;color:var(--muted)}
  .pill{display:inline-block;font-size:11px;font-weight:600;padding:2px 9px;border-radius:999px;
    border:1px solid currentColor}
  .b-Ancla{color:var(--ancla)} .b-Flex{color:var(--flex)} .b-Alerta{color:var(--alerta)}
  h2{font-size:15px;margin:0 0 10px;letter-spacing:.02em}
  .metric{display:flex;justify-content:space-between;align-items:center;gap:10px;
    padding:10px 0;border-top:1px solid var(--line)}
  .metric:first-of-type{border-top:none}
  .metric .name{font-size:13.5px}
  .metric .val{font-variant-numeric:tabular-nums;font-weight:600}
  .metric .right{display:flex;align-items:center;gap:8px}
  .bar{height:6px;border-radius:4px;background:var(--panel2);overflow:hidden;margin-top:6px}
  .bar>i{display:block;height:100%}
  .tesis{font-size:15px;line-height:1.6}
  ul.clean{margin:6px 0 0;padding-left:18px} ul.clean li{margin:6px 0;font-size:13.5px}
  .muted{color:var(--muted)} .small{font-size:12px}
  .grid2{display:grid;grid-template-columns:1fr 1fr;gap:10px}
  .kv{background:var(--panel2);border-radius:12px;padding:10px 12px}
  .kv .k{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
  .kv .v{font-size:15px;font-weight:600;font-variant-numeric:tabular-nums}
  a{color:var(--accent2)}
  .legend{display:flex;gap:14px;flex-wrap:wrap;font-size:11px;color:var(--muted);margin-top:10px}
  .legend span{display:inline-flex;align-items:center;gap:5px}
  .dot{width:9px;height:9px;border-radius:50%}
  footer{margin-top:22px;font-size:11px;color:var(--muted);text-align:center;line-height:1.7}
  .insider-buy{color:var(--accent)} .insider-sell{color:var(--bad)}
</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <div class="brand">Turpial Finanzas · Oráculo de riesgo</div>
    <h1 id="company"></h1>
    <div class="sub" id="meta"></div>
  </header>

  <section class="card gauge-wrap">
    <canvas id="gauge" width="320" height="190"></canvas>
    <div class="score-band" id="band"></div>
    <div class="small muted" id="coverage"></div>
  </section>

  <section class="card">
    <h2>Tesis de riesgo</h2>
    <div class="tesis" id="tesis"></div>
  </section>

  <section class="card">
    <h2>Tres pilares</h2>
    <canvas id="pillars" width="640" height="220"></canvas>
    <div class="legend">
      <span><i class="dot" style="background:var(--ancla)"></i>Valuación 35%</span>
      <span><i class="dot" style="background:var(--accent2)"></i>Salud Financiera 35%</span>
      <span><i class="dot" style="background:#6aa0ff"></i>Crecimiento 30%</span>
    </div>
  </section>

  <section class="card" id="metrics-card">
    <h2>Métricas clave <span class="small muted">(badge = convicción)</span></h2>
    <div id="metrics"></div>
    <div class="legend">
      <span><i class="dot" style="background:var(--ancla)"></i>Ancla · alta convicción</span>
      <span><i class="dot" style="background:var(--flex)"></i>Flex · útil pero volátil</span>
      <span><i class="dot" style="background:var(--alerta)"></i>Alerta · mirá con lupa</span>
    </div>
  </section>

  <section class="card">
    <h2>Historia financiera</h2>
    <canvas id="history" width="640" height="220"></canvas>
    <div class="small muted" id="history-note"></div>
  </section>

  <section class="card" id="insider-card">
    <h2>Insiders (Form 4 · SEC)</h2>
    <div class="grid2" id="insider-kv"></div>
    <div class="small muted" id="insider-note" style="margin-top:8px"></div>
  </section>

  <section class="card" id="tradeoffs-card">
    <h2>Trade-offs</h2>
    <ul class="clean" id="tradeoffs"></ul>
  </section>

  <section class="card" id="unknown-card">
    <h2>Lo que no se puede saber con info pública</h2>
    <ul class="clean" id="unknown"></ul>
  </section>

  <section class="card" id="filings-card">
    <h2>Filings primarios</h2>
    <ul class="clean" id="filings"></ul>
  </section>

  <footer id="footer"></footer>
</div>

<script>
const REPORT = /*__REPORT__*/null;

function fmt(v, unit){
  if(v===null||v===undefined) return "s/d";
  let n = (Math.abs(v)>=1000) ? v.toLocaleString("es",{maximumFractionDigits:0})
                              : v.toFixed(Math.abs(v)<10?2:1);
  return unit==="%" ? n+"%" : (unit==="x"? n+"×" : n);
}
function scoreColor(s){
  if(s===null||s===undefined) return "#8a98b5";
  if(s>=75) return "#39d98a"; if(s>=55) return "#9be15d";
  if(s>=30) return "#ffd166"; return "#ff5d73";
}
function bigMoney(v){
  if(v===null||v===undefined) return "s/d";
  const a=Math.abs(v);
  if(a>=1e12) return (v/1e12).toFixed(2)+" T";
  if(a>=1e9) return (v/1e9).toFixed(2)+" B";
  if(a>=1e6) return (v/1e6).toFixed(1)+" M";
  return v.toLocaleString("es");
}

function setup(){
  const r=REPORT; if(!r){document.body.innerHTML="<p style='padding:20px'>Sin datos.</p>";return;}
  document.getElementById("company").textContent = (r.company||r.ticker)+" ("+r.ticker+")";
  const p = r.price ? (r.price.price.toFixed(2)+" "+r.price.currency) : "precio s/d";
  document.getElementById("meta").textContent =
    [r.sic_description, r.exchange, p, "actualizado "+(r.generated_at||"")].filter(Boolean).join(" · ");

  const sc = r.score||{};
  drawGauge(sc.overall_score);
  const band = (r.narrative&&r.narrative.veredicto_banda) || sc.band;
  document.getElementById("band").textContent = "Banda: "+band;
  document.getElementById("coverage").textContent =
    "Cobertura de datos: "+(sc.coverage!=null?sc.coverage+"%":"s/d")+
    " · mayor puntaje = menor riesgo (0-100)";

  document.getElementById("tesis").textContent =
    (r.narrative&&r.narrative.tesis) || "Análisis determinístico sin narrativa (corré con ANTHROPIC_API_KEY para la historia completa).";

  drawPillars(sc.pillars);
  renderMetrics(sc.pillars, r.narrative);
  drawHistory(sc.raw);
  renderInsiders(r.insiders);
  renderList("tradeoffs", r.narrative&&r.narrative.trade_offs, "tradeoffs-card");
  renderList("unknown", r.narrative&&r.narrative.no_se_puede_saber, "unknown-card");
  renderFilings(r.filings);

  document.getElementById("footer").innerHTML =
    "Generado por Turpial Finanzas a partir de filings primarios de la SEC (EDGAR) y precio de mercado.<br>"+
    "No es recomendación de inversión. Verificá siempre contra los documentos originales.";
}

function drawGauge(score){
  const c=document.getElementById("gauge"), x=c.getContext("2d");
  const W=c.width,H=c.height,cx=W/2,cy=H-20,R=120;
  x.clearRect(0,0,W,H);
  x.lineCap="round";
  // arco base
  x.beginPath();x.lineWidth=16;x.strokeStyle="#1f2b45";
  x.arc(cx,cy,R,Math.PI,2*Math.PI);x.stroke();
  if(score!=null){
    const frac=Math.max(0,Math.min(1,score/100));
    x.beginPath();x.lineWidth=16;x.strokeStyle=scoreColor(score);
    x.arc(cx,cy,R,Math.PI,Math.PI+Math.PI*frac);x.stroke();
  }
  x.fillStyle="#e8edf7";x.textAlign="center";
  x.font="700 40px -apple-system,Segoe UI,Roboto,sans-serif";
  x.fillText(score!=null?score.toFixed(0):"s/d", cx, cy-14);
  x.font="12px -apple-system,Segoe UI,Roboto,sans-serif";x.fillStyle="#8a98b5";
  x.fillText("RISK SCORE", cx, cy+4);
}

function drawPillars(pillars){
  const c=document.getElementById("pillars"), x=c.getContext("2d");
  const dpr=window.devicePixelRatio||1;
  const cssW=c.parentElement.clientWidth-32; c.style.width=cssW+"px";
  c.width=cssW*dpr; c.height=200*dpr; x.scale(dpr,dpr);
  const W=cssW,H=200;
  x.clearRect(0,0,W,H);
  const items=[["Valuación",pillars&&pillars.valuacion,"#39d98a"],
               ["Salud Fin.",pillars&&pillars.salud_financiera,"#ffd166"],
               ["Crecim.",pillars&&pillars.crecimiento,"#6aa0ff"]];
  const n=items.length, gap=24, bw=(W-gap*(n+1))/n, base=H-30, maxh=H-60;
  items.forEach((it,i)=>{
    const s=it[1]&&it[1].score; const xpos=gap+i*(bw+gap);
    const h=s!=null?maxh*(s/100):0;
    x.fillStyle="#0f1626";x.fillRect(xpos,base-maxh,bw,maxh);
    x.fillStyle=it[2];x.fillRect(xpos,base-h,bw,h);
    x.fillStyle="#e8edf7";x.textAlign="center";
    x.font="700 16px -apple-system,Segoe UI,Roboto,sans-serif";
    x.fillText(s!=null?s.toFixed(0):"s/d", xpos+bw/2, base-h-8);
    x.fillStyle="#8a98b5";x.font="12px -apple-system,Segoe UI,Roboto,sans-serif";
    x.fillText(it[0], xpos+bw/2, base+18);
  });
}

function renderMetrics(pillars, narrative){
  const host=document.getElementById("metrics"); host.innerHTML="";
  const badgeOverride={};
  if(narrative&&narrative.badges){narrative.badges.forEach(b=>badgeOverride[b.metrica]=b.badge);}
  const order=["valuacion","salud_financiera","crecimiento"];
  order.forEach(k=>{
    const pil=pillars&&pillars[k]; if(!pil)return;
    pil.metrics.forEach(m=>{
      const badge=badgeOverride[m.label]||badgeOverride[m.key]||m.badge;
      const div=document.createElement("div");div.className="metric";
      div.innerHTML=
        '<div style="flex:1"><div class="name">'+m.label+'</div>'+
        '<div class="bar"><i style="width:'+(m.subscore||0)+'%;background:'+scoreColor(m.subscore)+'"></i></div></div>'+
        '<div class="right"><span class="val">'+fmt(m.value,m.unit)+'</span>'+
        '<span class="pill b-'+badge+'">'+badge+'</span></div>';
      host.appendChild(div);
    });
  });
}

function drawHistory(raw){
  const note=document.getElementById("history-note");
  const c=document.getElementById("history"), x=c.getContext("2d");
  const dpr=window.devicePixelRatio||1;
  const cssW=c.parentElement.clientWidth-32; c.style.width=cssW+"px";
  c.width=cssW*dpr; c.height=200*dpr; x.scale(dpr,dpr);
  const W=cssW,H=200; x.clearRect(0,0,W,H);
  const rev=(raw&&raw.rev_series)||[];
  if(rev.length<2){note.textContent="Sin serie de ingresos suficiente en los filings.";return;}
  note.textContent="Ingresos anuales (FY) de los últimos "+rev.length+" años, en USD.";
  const pad=36, base=H-26, top=20, plotW=W-pad*2, plotH=base-top;
  const max=Math.max.apply(null,rev), min=Math.min.apply(null,rev,0);
  const sx=i=>pad+plotW*(i/(rev.length-1));
  const sy=v=>base-plotH*((v-min)/((max-min)||1));
  // barras de ingresos
  const bw=plotW/rev.length*0.55;
  rev.forEach((v,i)=>{
    const h=base-sy(v);
    x.fillStyle="#1f6feb55";x.fillRect(sx(i)-bw/2,sy(v),bw,h);
  });
  // linea
  x.beginPath();x.lineWidth=2.5;x.strokeStyle="#39d98a";
  rev.forEach((v,i)=>{i?x.lineTo(sx(i),sy(v)):x.moveTo(sx(i),sy(v));});x.stroke();
  rev.forEach((v,i)=>{x.beginPath();x.fillStyle="#39d98a";x.arc(sx(i),sy(v),3,0,7);x.fill();});
  x.fillStyle="#8a98b5";x.textAlign="center";x.font="11px sans-serif";
  x.fillText(bigMoney(rev[0]),sx(0),base+16);
  x.fillText(bigMoney(rev[rev.length-1]),sx(rev.length-1),base+16);
}

function renderInsiders(ins){
  const kv=document.getElementById("insider-kv"), note=document.getElementById("insider-note");
  if(!ins||ins.status!=="ok"){
    document.getElementById("insider-card").style.opacity=.7;
    kv.innerHTML='<div class="kv"><div class="k">Estado</div><div class="v">s/d</div></div>';
    note.textContent=(ins&&(ins.reason||ins.senal))?("Form 4: "+(ins.reason||"sin transacciones parseables")):"Sin datos de insiders.";
    return;
  }
  const sig=ins.senal||"neutral";
  const sigTxt={compra_neta:"Compra neta",venta_neta:"Venta neta",neutral:"Neutral"}[sig]||sig;
  kv.innerHTML=
    '<div class="kv"><div class="k">Compras (aprox)</div><div class="v insider-buy">'+bigMoney(ins.buys_usd_aprox)+'</div></div>'+
    '<div class="kv"><div class="k">Ventas (aprox)</div><div class="v insider-sell">'+bigMoney(ins.sells_usd_aprox)+'</div></div>'+
    '<div class="kv"><div class="k">Neto</div><div class="v">'+bigMoney(ins.neto_usd_aprox)+'</div></div>'+
    '<div class="kv"><div class="k">Señal</div><div class="v">'+sigTxt+'</div></div>';
  note.textContent="Basado en "+(ins.filings_recientes||0)+" filings Form 3/4/5 recientes (fuente primaria SEC).";
}

function renderList(id, items, cardId){
  const host=document.getElementById(id);
  if(!items||!items.length){document.getElementById(cardId).style.display="none";return;}
  host.innerHTML=""; items.forEach(t=>{const li=document.createElement("li");li.textContent=t;host.appendChild(li);});
}

function renderFilings(fs){
  const host=document.getElementById("filings");
  if(!fs||!fs.length){document.getElementById("filings-card").style.display="none";return;}
  host.innerHTML="";
  fs.slice(0,6).forEach(f=>{
    const li=document.createElement("li");
    li.innerHTML='<a href="'+f.url+'" target="_blank" rel="noopener">'+f.form+'</a> · '+f.filed;
    host.appendChild(li);
  });
}

window.addEventListener("resize", ()=>{drawPillars((REPORT.score||{}).pillars);drawHistory((REPORT.score||{}).raw);});
setup();
</script>
</body>
</html>"""
