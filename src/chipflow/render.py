"""由 handoff.json 產出單檔 HTML 面板。

render(handoff, out_path) 產出可離線開啟的完整面板：
- Chart.js 折線圖：加權指數+外資累計、台指期未平倉、VIX
- Scorecard：各維度最後值
- AI 研判區塊（可選傳入 analysis_md）
- 觸發訊號列表
"""
from __future__ import annotations

import json

_STYLE = """
body{background:#0d0f14;color:#e8eaee;font-family:system-ui,sans-serif;margin:0;padding:16px}
h1{font-size:18px;margin:0 0 4px}
.sub{color:#94a3b8;font-size:12px;margin-bottom:16px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:640px){.grid{grid-template-columns:1fr}}
.card{background:#161a22;border:1px solid #252b36;border-radius:12px;padding:14px}
.card h2{font-size:13px;color:#94a3b8;margin:0 0 10px;font-weight:500}
.wrap{position:relative;height:220px}
.sc{display:flex;flex-wrap:wrap;gap:8px}
.sc-item{background:#1e2430;border-radius:8px;padding:8px 12px;min-width:100px}
.sc-label{font-size:11px;color:#64748b}
.sc-val{font-size:16px;font-weight:600;margin-top:2px}
.bull{color:#22c55e}.bear{color:#ef4444}.neutral{color:#94a3b8}
.sig{display:flex;gap:8px;align-items:flex-start;padding:6px 0;border-bottom:1px solid #252b36;font-size:13px}
.sig:last-child{border-bottom:none}
.sig-dir{width:48px;flex-shrink:0;font-size:11px;font-weight:600;padding:2px 6px;border-radius:4px;text-align:center}
.bull-bg{background:#15351e;color:#22c55e}.bear-bg{background:#3b1515;color:#ef4444}
.md{font-size:13px;line-height:1.7;color:#cbd5e1;white-space:pre-wrap}
a{color:#60a5fa;font-size:12px}
"""

_TMPL = """<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>chipflow · __AS_OF__</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>__STYLE__</style>
</head>
<body>
<h1>chipflow 台股籌碼面板</h1>
<div class="sub">as of __AS_OF__ &nbsp;|&nbsp; <a href="reports.html">← 返回列表</a></div>

<div class="grid">
  <div class="card" style="grid-column:1/-1">
    <h2>加權指數 / 外資現貨累計</h2>
    <div class="wrap"><canvas id="cA"></canvas></div>
  </div>
  <div class="card">
    <h2>外資台指期未平倉口數</h2>
    <div class="wrap"><canvas id="cB"></canvas></div>
  </div>
  <div class="card">
    <h2>VIX / US10Y</h2>
    <div class="wrap"><canvas id="cC"></canvas></div>
  </div>
</div>

<div class="card" style="margin-top:12px">
  <h2>Scorecard（最後值）</h2>
  <div class="sc" id="scorecard"></div>
</div>

<div class="card" id="nightcard" style="margin-top:12px;display:none">
  <h2>台指期夜盤</h2>
  <div class="sc" id="nightsc"></div>
</div>

<div class="grid" style="margin-top:12px">
  <div class="card">
    <h2>觸發訊號</h2>
    <div id="signals"></div>
  </div>
  <div class="card">
    <h2>AI 研判</h2>
    <div class="md" id="analysis">__ANALYSIS__</div>
  </div>
</div>

<script>
const D = __DATA__;
const g = "#252b36", s = "#98a2b3";
const xc = {ticks:{color:s,maxTicksLimit:8,font:{size:9}},grid:{color:g}};
const yc = (color) => ({ticks:{color:color||s},grid:{color:g}});

function ln(label, data, color, yAxis) {
  return {type:"line",label,data,borderColor:color,borderWidth:2,
          pointRadius:0,tension:.15,spanGaps:true,yAxisID:yAxis||"y"};
}
function mkChart(id, datasets, scales) {
  new Chart(document.getElementById(id), {
    data:{labels:D.labels, datasets},
    options:{maintainAspectRatio:false,
             plugins:{legend:{labels:{color:"#e8eaee",font:{size:11}}}},
             scales}
  });
}

mkChart("cA",
  [ln("加權指數", D.series.index, "#f3f4f6", "yR"),
   ln("外資現貨累計(億)", D.series.foreign_cum, "#ef4444", "yL")],
  {x:xc, yL:{position:"left",...yc("#ef4444")}, yR:{position:"right",...yc("#f3f4f6"),grid:{drawOnChartArea:false}}}
);
mkChart("cB",
  [ln("外資TX未平倉", D.series.fut_oi, "#f59e0b")],
  {x:xc, y:yc("#f59e0b")}
);
mkChart("cC",
  [ln("VIX", D.series.vix, "#a78bfa", "yL"),
   ln("US10Y%", D.series.us10y, "#38bdf8", "yR")],
  {x:xc, yL:{position:"left",...yc("#a78bfa")}, yR:{position:"right",...yc("#38bdf8"),grid:{drawOnChartArea:false}}}
);

// Scorecard
const SC_KEYS = [
  {k:"index",      label:"加權指數",  unit:""},
  {k:"foreign_cum",label:"外資累計",  unit:"億"},
  {k:"fut_oi",     label:"外資TX未平倉",unit:"口"},
  {k:"margin_maint",label:"融資維持率",unit:""},
  {k:"vix",        label:"VIX",      unit:""},
  {k:"us10y",      label:"US10Y",    unit:"%"},
  {k:"usdtwd",     label:"USDTWD",   unit:""},
  {k:"adr_prem",   label:"ADR溢價",  unit:"%"},
];
const sc = document.getElementById("scorecard");
SC_KEYS.forEach(({k,label,unit}) => {
  const vals = D.series[k]||[];
  const last = [...vals].reverse().find(v => v !== null);
  if (last === undefined) return;
  const el = document.createElement("div");
  el.className = "sc-item";
  const disp = unit === "%" ? (last*100).toFixed(2)+"%" : last.toLocaleString("zh-TW",{maximumFractionDigits:1})+unit;
  el.innerHTML = `<div class="sc-label">${label}</div><div class="sc-val">${disp}</div>`;
  sc.appendChild(el);
});

// Signals
const sigEl = document.getElementById("signals");
const sigs = (D.signals||[]).filter(s => s.direction !== "neutral");
if (!sigs.length) {
  sigEl.innerHTML = '<div style="color:#64748b;font-size:13px">無觸發訊號</div>';
} else {
  sigs.forEach(s => {
    const dir = s.direction;
    const isBull = dir === "bullish" || dir === "neutral_bullish";
    const isBear = dir === "bearish" || dir === "neutral_bearish";
    const cls = isBull ? "bull-bg" : isBear ? "bear-bg" : "";
    const label = isBull ? "↑多" : isBear ? "↓空" : "→";
    sigEl.innerHTML += `<div class="sig"><span class="sig-dir ${cls}">${label}</span><span><b>${s.indicator}</b> ${s.reading}</span></div>`;
  });
}

// Overnight / 夜盤
const night = D.overnight;
if (night && night.close) {
  document.getElementById("nightcard").style.display = "";
  const nsc = document.getElementById("nightsc");
  const chgClass = night.chg > 0 ? "bull" : night.chg < 0 ? "bear" : "";
  const chgStr = night.chg !== null && night.chg !== undefined
    ? `${night.chg > 0 ? "+" : ""}${night.chg}(${night.chg_pct > 0 ? "+" : ""}${night.chg_pct}%)`
    : "—";
  nsc.innerHTML = `
    <div class="sc-item"><div class="sc-label">夜盤收盤</div><div class="sc-val">${night.close.toLocaleString("zh-TW")}</div></div>
    <div class="sc-item"><div class="sc-label">vs日盤</div><div class="sc-val ${chgClass}">${chgStr}</div></div>
    <div class="sc-item"><div class="sc-label">夜盤量(口)</div><div class="sc-val">${night.volume ? night.volume.toLocaleString("zh-TW") : "—"}</div></div>
  `;
}
</script>
</body>
</html>"""


def render(handoff: dict, out_path: str, analysis_md: str = "") -> None:
    analysis_escaped = (analysis_md or "（尚未產出研判）").replace("<", "&lt;").replace(">", "&gt;")
    html = (_TMPL
            .replace("__STYLE__", _STYLE)
            .replace("__AS_OF__", handoff.get("as_of_date", ""))
            .replace("__ANALYSIS__", analysis_escaped)
            .replace("__DATA__", json.dumps(handoff, ensure_ascii=False)))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
