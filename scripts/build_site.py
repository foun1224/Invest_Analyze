"""產出 GitHub Pages 靜態站台檔案（reports.html listing 頁）。

用法: python scripts/build_site.py <YYYY-MM-DD>
"""
import json
import sys
from pathlib import Path

date_str = sys.argv[1] if len(sys.argv) > 1 else ""
out = Path("out")
out.mkdir(exist_ok=True)

# 讀研判摘要（取前 300 字）
analysis_path = out / f"analysis_{date_str}.md"
analysis_snippet = ""
if analysis_path.exists():
    text = analysis_path.read_text(encoding="utf-8")
    analysis_snippet = text[:300].replace("<", "&lt;").replace(">", "&gt;")

# 讀 handoff：資金風險狀態 + signals
handoff_path = out / f"handoff_{date_str}.json"
signals_html = ""
flow_html = ""
if handoff_path.exists():
    h = json.loads(handoff_path.read_text(encoding="utf-8"))
    fr = h.get("fund_flow_regime") or {}
    if fr.get("stance"):
        dir_ = fr.get("direction") or "neutral"
        color = (
            "#22c55e" if dir_ == "bullish"
            else "#ef4444" if dir_ == "bearish"
            else "#94a3b8"
        )
        complete = "" if fr.get("data_complete", True) else "（資料不完整）"
        triggers_rows = ""
        for t in fr.get("triggers") or []:
            td = t.get("direction") or "neutral"
            tc = (
                "#22c55e" if td == "bullish"
                else "#ef4444" if td == "bearish"
                else "#94a3b8"
            )
            triggers_rows += (
                f"<tr><td>{t.get('indicator','')}</td>"
                f"<td style='color:{tc}'>{td}</td>"
                f"<td>{t.get('reading','')}</td></tr>"
            )
        trig_table = ""
        if triggers_rows:
            trig_table = (
                "<table style='margin-top:10px'><thead><tr>"
                "<th>流向訊號</th><th>方向</th><th>讀數</th></tr></thead>"
                f"<tbody>{triggers_rows}</tbody></table>"
            )
        flow_html = f"""
<div style="border-left:4px solid {color};padding-left:12px;margin:8px 0">
  <div style="font-size:20px;font-weight:700;color:{color}">
    {fr.get('regime_label') or fr.get('stance')}
  </div>
  <div style="color:#cbd5e1;margin-top:6px">{fr.get('action_hint','')}{complete}</div>
  <div style="color:#94a3b8;font-size:13px;margin-top:8px;line-height:1.6">
    {(fr.get('summary') or '').replace('<','&lt;').replace('>','&gt;')}
  </div>
  {trig_table}
</div>
"""
        if not analysis_snippet and fr.get("summary"):
            analysis_snippet = (fr.get("summary") or "")[:300].replace("<", "&lt;").replace(">", "&gt;")

    # signals：handoff 用 indicator/reading/direction/rationale
    sigs = [
        s for s in h.get("signals", [])
        if s.get("direction") not in (None, "neutral")
    ]
    if sigs:
        rows = ""
        for s in sigs[:20]:
            d = s.get("direction", "")
            color = (
                "#ef4444" if "bear" in d
                else "#22c55e" if "bull" in d
                else "#94a3b8"
            )
            rows += (
                f"<tr><td>{s.get('indicator','')}</td>"
                f"<td style='color:{color}'>{d}</td>"
                f"<td>{s.get('reading','')}</td></tr>"
            )
        signals_html = (
            "<table><thead><tr><th>訊號</th><th>方向</th><th>讀數</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )

# 歷史面板列表
panels = sorted(out.glob("panel_*.html"), reverse=True)
hist = "".join(
    f'<li><a href="{p.name}">{p.stem.replace("panel_", "")}</a></li>'
    for p in panels[:30]
)

ellipsis = "…" if len(analysis_snippet) >= 300 else ""

html = f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>chipflow · 台股籌碼面板</title>
<style>
  body{{background:#0d0f14;color:#e8eaee;font-family:system-ui,sans-serif;max-width:900px;margin:0 auto;padding:24px}}
  h1{{font-size:22px;margin-bottom:4px}}
  h2{{font-size:15px;color:#94a3b8;font-weight:400;margin-top:0}}
  .btn{{display:inline-block;background:#3b82f6;color:#fff;padding:10px 22px;border-radius:8px;text-decoration:none;font-size:14px;margin:16px 0}}
  .card{{background:#161a22;border:1px solid #252b36;border-radius:12px;padding:16px;margin:16px 0}}
  pre{{white-space:pre-wrap;font-size:13px;color:#94a3b8;line-height:1.6}}
  table{{border-collapse:collapse;width:100%;font-size:13px}}
  th,td{{padding:6px 10px;border:1px solid #252b36;text-align:left}}
  th{{background:#1e2430;color:#94a3b8}}
  ul{{padding-left:20px;line-height:2}}
  a{{color:#60a5fa}}
  .date{{color:#94a3b8;font-size:13px}}
</style>
</head>
<body>
<h1>chipflow 台股籌碼面板</h1>
<h2>每日盤後自動分析 · 三大法人 / 期貨籌碼 / 外圍市場</h2>
<p class="date">最新日期：{date_str}</p>
<a class="btn" href="panel_{date_str}.html">開啟今日完整面板 →</a>
<a class="btn" href="index.html" style="background:#1e2430;margin-left:8px">index 面板</a>

<div class="card">
  <b>三大法人 · 資金風險狀態</b>
  {flow_html if flow_html else '<p style="color:#94a3b8">尚無 fund_flow_regime（請確認 handoff 已含此欄）</p>'}
</div>

<div class="card">
  <b>觸發訊號</b>
  {signals_html if signals_html else '<p style="color:#94a3b8">無非中性訊號</p>'}
</div>

<div class="card">
  <b>研判摘要</b>
  <pre>{analysis_snippet if analysis_snippet else "（尚無 LLM 研判；見上方資金風險狀態）"}{ellipsis}</pre>
  {"<a href='analysis_" + date_str + ".md'>完整研判 →</a>" if analysis_path.exists() else ""}
</div>

<div class="card">
  <b>歷史面板</b>
  <ul>{hist if hist else "<li style='color:#94a3b8'>尚無歷史</li>"}</ul>
</div>
</body>
</html>"""

(out / "reports.html").write_text(html, encoding="utf-8")
print(f"reports.html built for {date_str}")
