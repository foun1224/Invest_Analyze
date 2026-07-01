# 資料來源實測手冊(已驗證可用)

> 以下端點/參數/回傳結構皆為本專案實測結果。單位與正負號慣例見 `schemas/handoff.schema.json`。

## TWSE(臺灣證券交易所)
一律 `GET` 回 JSON,`stat=="OK"` 才有資料;非交易日回錯誤或空 `data`。

### 三大法人買賣金額(現貨)BFI82U
`GET https://www.twse.com.tw/rwd/zh/fund/BFI82U?type=day&dayDate={YYYYMMDD}&response=json`
`data` 列:`[單位名稱, 買進金額, 賣出金額, 買賣差額]`(元,含千分位)。名稱含 `自營商(自行買賣)`、`自營商(避險)`、`投信`、`外資及陸資(不含外資自營商)`、`外資自營商`、`合計`。外資淨額取「外資及陸資」列買賣差額;自營商=自行買賣+避險。

### 加權指數+量 FMTQIK(單次回整月每日)
`GET https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date={YYYYMM}01&response=json`
`data` 列:`[日期(民國115/06/30), 成交股數, 成交金額, 成交筆數, 加權指數, 漲跌點數]`。指數 index4;成交金額 index2(元→億元 /1e8);日期為**民國**需轉。

### 融資融券 MI_MARGN(市場彙總)
`GET https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={YYYYMMDD}&selectType=MS&response=json`
`tables[0].data` 列 `融資(交易單位)`/`融券(交易單位)`/`融資金額(仟元)`,欄 `[項目,買進,賣出,現金券償還,前日餘額,今日餘額]`。融資餘額=`融資金額(仟元)` index5(仟元→億元 /1e5);融券張數=`融券(交易單位)` index5。

### 借券賣出 TWT93U(逐檔加總)
`GET https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U?date={YYYYMMDD}&response=json`
每列 index12=借券賣出當日餘額(股),**加總所有列**得市場總額。

### 漲跌家數→ADL MI_INDEX
`GET https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={YYYYMMDD}&type=MS&response=json`
於 `tables` 找 `title=='漲跌證券數合計'`;列 `上漲(漲停)`/`下跌(跌停)` 取「股票」欄 index2,格式 `"747(59)"`→取 747。ADL=累計(上漲-下跌)。

### 估值中位數 BWIBBU_d
`GET https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?date={YYYYMMDD}&selectType=ALL&response=json`
`data` 列 `[代號,名稱,收盤,殖利率%,股利年度,本益比,股價淨值比,財報]`。取全體中位數:本益比 index5、P/B index6、殖利率 index3(排除 '-'、0)。註:全體上市中位數,非市值加權指數本益比。

### 三大法人買賣超個股 T86
`GET https://www.twse.com.tw/rwd/zh/fund/T86?date={YYYYMMDD}&selectType=ALLBUT0999&response=json`
於 `fields` 找含「外陸資買賣超股數」欄,依該欄排序得外資買/賣超前 N 檔(股→張 /1e3)。

## TAIFEX(臺灣期貨交易所)

### 三大法人-區分各契約 futContractsDate ★用 queryDate
`POST https://www.taifex.com.tw/cht/3/futContractsDate`,Header `Referer: .../cht/3/futContractsDate`,Body `queryDate={YYYY/MM/DD}&doQuery=1`。回 HTML 用 `pandas.read_html`,取欄數≥15、列數>5 的表。欄(0-based):`0序號 1商品名稱 2身份別 3-8交易(多/空/淨:口數,金額) 9-14未平倉(多/空/淨:口數,金額)`。
- 外資台指期未平倉淨額 = 列(商品名稱=='臺股期貨' & 身份別=='外資')**index13**(口);當日交易淨=index7。
- 散戶小台 = **-(自營+投信+外資)** 之「小型臺指期貨」未平倉淨額(index13)加總。

> ⚠️ **陷阱**:`futContractsDateExcel` 帶 queryStartDate/queryEndDate 會**忽略日期、只回最新一天**。務必用 `queryDate`,並驗證不同日期回不同值。

### 選擇權 Put/Call 比 pcRatio(偶發不穩,需重試)
`POST https://www.taifex.com.tw/cht/3/pcRatioExcel`,Body `queryStartDate={YYYY/MM/DD}&queryEndDate={YYYY/MM/DD}`。取 ≥7 欄表,欄 `[日期,賣權成交量,買權成交量,買賣權成交量比率%,賣權未平倉量,買權未平倉量,買賣權未平倉量比率%]`。P/C 未平倉比=index6;>150 偏悲觀、<100 偏樂觀。偶發回無表格→重試+降級 null,勿中斷。

## Yahoo Finance(外圍)
`GET https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={rng}&interval=1d`(**須帶 User-Agent**)。解析 `chart.result[0].timestamp` 與 `indicators.quote[0].close`(過濾 null)。

| 序列 | symbol | | 序列 | symbol |
|---|---|---|---|---|
| 費城半導體 | `^SOX` | | 美元指數 | `DX-Y.NYB` |
| 那斯達克 | `^IXIC` | | 美債10Y殖利率% | `^TNX` |
| 台積電 ADR | `TSM` | | 美股 VIX | `^VIX` |
| 台積電普通股 | `2330.TW` | | 美元台幣 | `USDTWD=X` |
| 櫃買指數 | `^TWOII` | | | |

台積電 ADR 溢價% = `(TSM/5 * USDTWD)/2330 - 1`(1 ADR=5 普通股)。美股交易日與台股不完全同步,對齊後缺日以 null。

## 交易日 / 時區
時區 Asia/Taipei。交易日主軸以 BFI82U/FMTQIK 有回資料的日期為準。非交易日 API 回 `stat!='OK'` 或空 data → 跳過,**不補值**。
