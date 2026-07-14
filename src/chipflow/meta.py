"""handoff 的靜態中繼資料(慣例/欄位定義/來源/待觀察/待解/待接)。

這些內容定義了資料包的「自我描述」部分,供消費端(AI)正確解讀。
修改欄位時,務必與 schemas/handoff.schema.json 與 field_legend 保持一致。
"""

CONVENTIONS = {
    "currency": "TWD",
    "amount_unit_default": "億元 (=1e8 TWD)",
    "net_buy_sell_sign": "正=買超/淨多; 負=賣超/淨空",
    "futures_oi_unit": "口(contracts); 負=淨空",
    "cumulative": "foreign_cum/trust_cum/dealer_cum/adl 為區間內累計值",
    "valuation": "pe/pb/yd 為全體上市股票中位數,非市值加權指數本益比",
    "external_calendar": "sox/ndx/dxy/tnx/vix 為美股交易日,與台股可能小幅錯位",
    "series_alignment": "所有序列已對齊 labels(台股交易日 MM/DD);缺值以 null 表示",
    "adr_premium": "台積電ADR溢價% = (TSM/5 * USDTWD)/2330 - 1;正=ADR溢價",
    "fund_flow_regime": (
        "fund_flow_regime 為三大法人資金風險狀態(研判非下單)。"
        "stance: bullish_entry=偏多/入場可考慮; bearish_exit=偏空/出場警戒; "
        "neutral_watch=中性/觀望; data_insufficient=核心序列缺值。"
        "依多日現貨淨額轉折+外資台指期OI變化推導,不單看累計正負號。"
    ),
}

FIELD_LEGEND = {
    "index": "加權指數(收盤)", "volume": "集中市場成交金額(億元)",
    "foreign_cum": "外資及陸資 現貨累計買賣超(億元)",
    "trust_cum": "投信 現貨累計買賣超(億元)",
    "dealer_cum": "自營商 現貨累計買賣超(億元)",
    "fut_oi": "外資 台指期(TX)未平倉多空淨額(口)",
    "retail_mtx": "散戶 小型台指未平倉淨額(口);正=淨多",
    "margin_fin": "融資餘額(億元)", "margin_short": "融券餘額(張)",
    "margin_maint": "大盤融資維持率(%)=Σ(融資餘額股數×收盤價)/融資餘額金額;新倉基準166.7%",
    "sbl": "借券賣出餘額(億股)",
    "pcr": "選擇權Put/Call未平倉比(%);>150偏悲觀,<100偏樂觀",
    "pe": "全體上市 本益比 中位數", "pb": "全體上市 股價淨值比 中位數",
    "yd": "全體上市 殖利率(%) 中位數",
    "sox": "費城半導體指數", "ndx": "那斯達克指數", "dxy": "美元指數",
    "tnx": "美債10年期殖利率(%)", "vix": "美股VIX恐慌指數",
    "adr_prem": "台積電ADR溢價(%)", "otc": "櫃買(TPEx)指數",
    "fx": "美元兌台幣 USD/TWD",
    "adl": "騰落線(累計 上漲家數-下跌家數,股票)",
}

DATA_SOURCES = [
    {"name": "TWSE BFI82U", "use": "三大法人買賣金額(現貨)"},
    {"name": "TWSE FMTQIK", "use": "加權指數收盤/成交量"},
    {"name": "TWSE MI_MARGN", "use": "融資融券餘額 + 逐檔融資餘額(維持率分子)"},
    {"name": "TWSE TWT93U", "use": "借券賣出餘額(逐檔加總)"},
    {"name": "TWSE MI_INDEX", "use": "漲跌家數→ADL"},
    {"name": "TWSE BWIBBU_d", "use": "個股P/E/P/B/殖利率→中位數"},
    {"name": "TWSE T86", "use": "三大法人買賣超個股"},
    {"name": "TAIFEX futContractsDate", "use": "三大法人期貨(外資台指期/散戶小台)"},
    {"name": "TAIFEX pcRatio", "use": "選擇權Put/Call未平倉比"},
    {"name": "Yahoo Finance", "use": "SOX/Nasdaq/TSMC-ADR/2330/DXY/US10Y/VIX/USDTWD"},
]

WATCH_LIST = [
    {"signal": "費城半導體SOX", "bullish": "維持強勢/續創高", "bearish": "跌破均線/回檔", "priority": "最高"},
    {"signal": "外資現貨", "bullish": "翻買", "bearish": "恢復賣超", "priority": "高"},
    {"signal": "外資台指期OI", "bullish": "淨空收斂", "bearish": "續加深", "priority": "高"},
    {"signal": "融資餘額", "bullish": "去化", "bearish": "續增創高", "priority": "高"},
]

OPEN_QUESTIONS = [
    "外資現貨是否由賣轉買?",
    "外資台指期空單在反彈中回補還是續加?",
    "投信季底後是否延續買超?",
    "費半SOX急漲後是否過熱回檔(台股最大外部風險)?",
]

DATA_GAPS_TODO = [
    "高股息ETF資金流(規模/受益人數)—需集保/投信投顧公會",
    "M1B/M2年增—央行月頻",
    "大額交易人期貨部位—TAIFEX可再接",
    "Taiwan VIX(台指選擇權波動率指數)—TAIFEX專頁",
    "券資比/外資持股比率/當沖比重—逐檔彙整較重",
    "月營收年增—基本面動能",
]


def build_meta(generated_at: str) -> dict:
    return {
        "generated_at": generated_at,
        "conventions": CONVENTIONS,
        "field_legend": FIELD_LEGEND,
        "data_sources": DATA_SOURCES,
        "watch_list": WATCH_LIST,
        "open_questions": OPEN_QUESTIONS,
        "data_gaps_todo": DATA_GAPS_TODO,
    }
