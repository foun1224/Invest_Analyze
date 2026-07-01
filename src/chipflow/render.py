"""由 handoff.json 產出單檔 HTML 面板(scaffold)。

此為最小可用版:嵌入 handoff 並畫幾張核心圖。
TODO(agent, P1):擴充為完整多區塊面板(可參考本專案既有面板設計),
含全部 series、Scorecard、以及 §9 AI 接手區塊(prompt + JSON 複製鈕)。
"""
from __future__ import annotations

import json

_TMPL = """<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>chipflow 面板 __AS_OF__</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>body{background:#0d0f14;color:#e8eaee;font-family:sans-serif;padding:16px}
.card{background:#161a22;border:1px solid #252b36;border-radius:12px;padding:12px;margin-bottom:12px}
.wrap{position:relative;height:240px}h1{font-size:18px}</style></head><body>
<h1>chipflow 籌碼面板 · __AS_OF__</h1>
<div class="card"><div class="wrap"><canvas id="a"></canvas></div></div>
<div class="card"><div class="wrap"><canvas id="b"></canvas></div></div>
<script>
const D=__DATA__;const g="#252b36",s="#98a2b3";
const xc={ticks:{color:s,maxTicksLimit:7,font:{size:9}},grid:{color:g}};
function ln(l,d,c,ax){return{type:"line",label:l,data:d,borderColor:c,borderWidth:2,pointRadius:0,tension:.15,yAxisID:ax||"y"};}
new Chart(a,{data:{labels:D.labels,datasets:[ln("加權指數",D.series.index,"#f3f4f6","yR"),
 ln("外資現貨累計",D.series.foreign_cum,"#ef4444","yL")]},
 options:{maintainAspectRatio:false,plugins:{legend:{labels:{color:"#e8eaee"}}},spanGaps:true,
 scales:{x:xc,yL:{position:"left",ticks:{color:"#ef4444"},grid:{color:g}},yR:{position:"right",ticks:{color:"#f3f4f6"},grid:{drawOnChartArea:false}}}}});
new Chart(b,{data:{labels:D.labels,datasets:[ln("外資台指期未平倉",D.series.fut_oi,"#f59e0b")]},
 options:{maintainAspectRatio:false,plugins:{legend:{labels:{color:"#e8eaee"}}},spanGaps:true,scales:{x:xc,y:{ticks:{color:s},grid:{color:g}}}}});
</script></body></html>"""


def render(handoff: dict, out_path: str) -> None:
    html = (_TMPL
            .replace("__AS_OF__", handoff.get("as_of_date", ""))
            .replace("__DATA__", json.dumps(handoff, ensure_ascii=False)))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
