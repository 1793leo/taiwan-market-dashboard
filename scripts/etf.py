"""
ETF 每日紀錄（各投信官網）

  元大 0050 / 0056 / 00631L：申購買回清單頁 https://www.yuantaetfs.com/tradeInfo/pcf/<代號>
        頁面內嵌的 pcfData 同時包含基金概況、完整持股權重（股票／期貨）、實物申購買回清單
  群益 00919：https://www.capitalfund.com.tw/CFWeb/api/etf/buyback（JSON，含持股與 PCF）
  富邦 006208：Assets.aspx（持股表格）＋ Pcf.aspx（現金申購買回清單文字）
  統一 00981A：ezmoney Info 頁內嵌 DataAsset（持股）＋ /ETF/Transaction/GetPCF（PCF）
  國泰 00878：cwapi.cathaysite.com.tw（GetBuySale / GetETFAssets / GetETFDetailStockList…）

每檔都轉成同一格式：
  {code, date(持股資料日), name, issuer, updated, ann_date, summary{...}, stocks[{c,n,q,w}],
   futures[{c,n,ym,q,w}], inkind[{c,n,q,cash,min}], pcf_items[[標籤, 數值, 型態]], memo}

儲存：data/etf/<代號>/YYYY-MM-DD.json（以資料的交易日命名）
網站：_site/data/etf/<代號>/index.json（日期清單）、_site/data/etf/<代號>/YYYY-MM-DD.json（含與前一筆紀錄的增減）
"""
from __future__ import annotations

import datetime as dt
import html as htmlmod
import io
import json
import re
import subprocess
from pathlib import Path

import requests

import twdata

# 代號 → (投信, 該投信網站的基金代碼)
ETFS = {
    "0050": ("yuanta", "0050"),
    "0056": ("yuanta", "0056"),
    "00878": ("cathay", "CN"),
    "00919": ("capital", "195"),
    "006208": ("fubon", "006208"),
    "00631L": ("yuanta", "00631L"),
    "00981A": ("ezmoney", "49YTW"),
    "009816": ("kgi", "J023"),
    "00918": ("uob", "88329556"),
    "00929": ("fuhhwa", "ETF21"),
    "00881": ("cathay", "CR"),
    "00403A": ("ezmoney", "63YTW"),
    "00713": ("yuanta", "00713"),
    "00685L": ("capital", "094"),
    "00922": ("cathay", "DO"),
    "00927": ("capital", "366"),
    "00940": ("yuanta", "00940"),
    "00991A": ("fuhhwa", "ETF23"),
}
# 顯示名稱
NAMES = {
    "0050": "元大台灣50", "0056": "元大高股息", "00631L": "元大台灣50正2", "00713": "元大台灣高息低波",
    "00940": "元大台灣價值高息",
    "00878": "國泰永續高股息", "00919": "群益台灣精選高息", "006208": "富邦台50", "00981A": "主動統一台股增長",
    "009816": "凱基台灣TOP50", "00918": "大華優利高填息30", "00929": "復華台灣科技優息", "00881": "國泰台灣科技龍頭",
    "00403A": "主動統一升級50", "00685L": "群益臺灣加權正2", "00922": "國泰台灣領袖50", "00927": "群益半導體收益",
    "00991A": "主動復華未來50",
}
ISSUER = {"yuanta": "元大", "cathay": "國泰", "capital": "群益", "fubon": "富邦", "ezmoney": "統一",
          "kgi": "凱基", "uob": "大華銀", "fuhhwa": "復華"}
ROOT = Path(__file__).resolve().parent
# 回補歷史資料時設定：DAY = 要抓的持股資料日（交易日），ANN = 下一個交易日（申購買回清單公告日）
DAY: str | None = None
ANN: str | None = None
UA = {"User-Agent": twdata.HEADERS["User-Agent"], "Accept-Language": "zh-TW,zh;q=0.9"}


def num(x):
    """'1,234.5' / '12.3%' / 1234 → float；空值 → None"""
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).replace(",", "").replace("%", "").replace("NT$", "").replace("$", "").strip()
    if s in ("", "-", "--", "—"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def inum(x):
    v = num(x)
    return None if v is None else int(round(v))


def iso(s) -> str | None:
    """'2026/11/17' / '2026-11-17T00:00:00' / '20261117' / '115/11/17' → '2026-11-17'"""
    if not s:
        return None
    m = re.search(r"(\d{3,4})[/-](\d{1,2})[/-](\d{1,2})", str(s))
    if m:
        y = int(m.group(1))
        y = y + 1911 if y < 1000 else y
        return f"{y:04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", str(s).strip())
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def jsdate(s) -> str | None:
    """'/Date(1794904218000)/' 或 ISO 字串 → 'YYYY-MM-DD HH:MM'（台北時間）"""
    m = re.search(r"/Date\((\d+)", str(s or ""))
    if m:
        t = dt.datetime.fromtimestamp(int(m.group(1)) / 1000, dt.timezone(dt.timedelta(hours=8)))
        return t.strftime("%Y-%m-%d %H:%M")
    return str(s).replace("T", " ")[:16] if s else None


def ymd(s) -> str | None:
    d = iso(s)
    return d.replace("-", "") if d else None


def stocks_value(stocks):
    v = [s.get("amt") for s in stocks if s.get("amt") is not None]
    return sum(v) if v else None


# ---------------------------------------------------------------- 元大
def _yuanta_history(fid: str) -> dict:
    """元大網站查詢歷史 PCF 用的 API（date = 公告日）"""
    r = requests.get("https://etfapi.yuantaetfs.com/ectranslation/api/bridge", timeout=60, headers=UA, params={
        "APIType": "ETFAPI", "CompanyName": "YUANTAFUNDS", "PageName": f"/tradeInfo/pcf/{fid}", "DeviceId": "null",
        "FuncId": "PCF/Daily", "AppName": "ETF", "Device": "3", "Platform": "ETF", "ticker": fid,
        "date": ANN.replace("-", "")})
    r.raise_for_status()
    j = r.json()
    return j.get("Data") if j.get("ResultCode") == 0 else j


def fetch_yuanta(code: str, fid: str) -> dict:
    if DAY:
        pcf = _yuanta_history(fid) or {}
    else:
        r = requests.get(f"https://www.yuantaetfs.com/tradeInfo/pcf/{fid}", timeout=60, headers=UA)
        r.raise_for_status()
        if "maintenance" in r.url:
            raise RuntimeError("元大網站維護中，下次排程再抓")
        out = subprocess.run(["node", str(ROOT / "etf_extract.js")], input=r.text, capture_output=True,
                             text=True, timeout=60)
        if out.returncode != 0:
            raise RuntimeError(f"{code} 解析失敗：{out.stderr.strip()[:200]}")
        pcf = json.loads(out.stdout)
    p, fw = pcf.get("PCF") or {}, pcf.get("FundWeights") or {}
    td = str(p.get("trandate") or "")
    if len(td) != 8:
        raise RuntimeError(f"{code} 無交易日")
    ben = p.get("Beneficiary") or {}
    return {
        "code": code, "date": f"{td[:4]}-{td[4:6]}-{td[6:]}", "name": p.get("fundname"), "fullname": p.get("fullname"),
        "updated": p.get("upddate"), "ann_date": p.get("anndate"),
        "summary": {
            "totalav": p.get("totalav"), "nav": p.get("nav"), "osunit": p.get("osunit"),
            "issuesdiff": p.get("issuesdiff"), "baseunit": p.get("baseunit"),
            "estcvalue": p.get("estcvalue"), "estdvalue": p.get("estdvalue"), "cashdiff": p.get("cashdiff"),
            "beneficiaries": ben.get("bf_cnt_a"), "ben_month": ben.get("doc_ym"),
            "stkvalues": (fw.get("Summary") or {}).get("stkvalues"), "futvalues": (fw.get("Summary") or {}).get("futvalues"),
        },
        "stocks": [{"c": s["code"], "n": s["name"], "q": s["qty"], "w": s["weights"]} for s in fw.get("StockWeights") or []],
        "futures": [{"c": s["code"], "n": s["name"], "ym": s.get("ym"), "q": s["qty"], "w": s["weights"]}
                    for s in fw.get("FutureWeights") or []],
        "inkind": [{"c": s["stkcd"], "n": s["name"], "q": s["qty"], "cash": s.get("cashinlieu"), "min": s.get("minimum")}
                   for s in (pcf.get("InKind") or {}).get("FundComposition") or []],
        "memo": pcf.get("Memo") or [],
    }


# ---------------------------------------------------------------- 群益
def fetch_capital(code: str, fid: str) -> dict:
    r = requests.post("https://www.capitalfund.com.tw/CFWeb/api/etf/buyback", json={"fundId": fid, "date": ANN},
                      headers={**UA, "Referer": f"https://www.capitalfund.com.tw/etf/product/detail/{fid}/buyback"},
                      timeout=60)
    r.raise_for_status()
    d = r.json().get("data") or {}
    p = d.get("pcf") or {}
    date = iso(p.get("date2"))
    if not date:
        raise RuntimeError(f"{code} 無交易日")
    stocks = [{"c": str(s.get("stocNo")).strip(), "n": (s.get("stocName") or "").strip(), "q": inum(s.get("share")),
               "w": num(s.get("weight"))} for s in d.get("stocks") or []]
    futures = []
    for f in d.get("futures") or []:
        desc = (f.get("txDesc") or "").strip()
        m = re.search(r"(\d{6})", desc)
        futures.append({"c": desc, "n": desc, "ym": m.group(1) if m else None, "q": inum(f.get("lot")), "w": num(f.get("weight"))})
    nav, osu = num(p.get("pUnit")), inum(p.get("totUnit"))
    ym = str(p.get("yymmPeople") or "")
    s = {
        "totalav": num(p.get("nav")), "nav": nav, "osunit": osu, "issuesdiff": inum(p.get("disUnit")),
        "baseunit": inum(p.get("tUnit")), "beneficiaries": inum(p.get("numberPeople")),
        "ben_month": ymd(ym + "/01")[:6] if iso(ym + "/01") else (re.sub(r"\D", "", ym)[:6] or None),
    }
    items = [["公告日期（適用申購日）", iso(p.get("date1")), "date"],
             ["每現金申購／買回基數之受益權單位數", s["baseunit"], ""],
             ["每現金申購／買回基數約當淨值", num(p.get("equNav")), "NTD"],
             ["預收申購總價金", num(p.get("forecastAmt")), "NTD"],
             ["實際申購總價金差額", num(p.get("disAmt")), "NTD"],
             ["與前日已發行單位差異數", s["issuesdiff"], "sgn"]]
    return {"code": code, "date": date, "name": "群益台灣精選高息", "updated": p.get("date1"), "ann_date": ymd(p.get("date1")),
            "summary": s, "stocks": stocks, "futures": futures, "inkind": [], "pcf_items": items, "memo": []}


# ---------------------------------------------------------------- 富邦
def _fubon_text(url: str) -> tuple[str, str]:
    r = requests.get(url, headers=UA, timeout=60)
    r.raise_for_status()
    r.encoding = r.apparent_encoding if not r.encoding or r.encoding.lower() == "iso-8859-1" else r.encoding
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", r.text, flags=re.S | re.I)
    t = htmlmod.unescape(re.sub(r"<[^>]+>", " ", t))
    return r.text, re.sub(r"\s+", " ", t)


def _after(text: str, label: str, pat=r"(-?[\d,]+(?:\.\d+)?)"):
    m = re.search(re.escape(label) + r"[^0-9\-]{0,40}?" + pat, text)
    return m.group(1) if m else None


def fetch_fubon(code: str, fid: str) -> dict:
    import pandas as pd
    if DAY:
        raise RuntimeError("富邦官網只提供最新一日持股，無法回補")
    raw, text = _fubon_text(f"https://websys.fsit.com.tw/FubonETF/Fund/Assets.aspx?stkId={fid}")
    tables = pd.read_html(io.StringIO(raw))
    stocks, futures = [], []
    for t in tables:
        cols = [str(c) for c in t.columns]
        t.columns = cols
        if not any("代碼" in c for c in cols):
            # 表頭在第一列資料裡
            hdr = next((i for i in range(min(3, len(t))) if any("代碼" in str(v) for v in t.iloc[i])), None)
            if hdr is None:
                continue
            cols = [str(v).strip() for v in t.iloc[hdr]]
            t = t.iloc[hdr + 1:].copy()
            t.columns = cols
        if any("股票代碼" in c for c in cols):
            cc = {k: next(c for c in cols if k in c) for k in ("股票代碼", "股票名稱", "股數", "權重")}
            amt = next((c for c in cols if "金額" in c), None)
            for _, row in t.iterrows():
                c = str(row[cc["股票代碼"]]).strip()
                if not re.fullmatch(r"[0-9A-Z]{4,6}", c):
                    continue
                stocks.append({"c": c, "n": str(row[cc["股票名稱"]]).strip(), "q": inum(row[cc["股數"]]),
                               "w": num(row[cc["權重"]]), "amt": num(row[amt]) if amt else None})
        elif any("期貨代碼" in c for c in cols):
            cc = {k: next(c for c in cols if k in c) for k in ("期貨代碼", "期貨名稱", "口數", "權重")}
            for _, row in t.iterrows():
                c = str(row[cc["期貨代碼"]]).strip()
                if c in ("", "nan") or "合計" in c or "期貨代碼" in c:
                    continue
                nm = str(row[cc["期貨名稱"]]).strip()
                m = re.search(r"(\d{4})/(\d{1,2})", nm)
                futures.append({"c": c, "n": nm, "ym": f"{m.group(1)}{int(m.group(2)):02d}" if m else None,
                                "q": inum(row[cc["口數"]]), "w": num(row[cc["權重"]])})
    hold_date = iso(_after(text, "資料日期", r"(\d{3,4}/\d{1,2}/\d{1,2})") or _after(text, "日期", r"(\d{3,4}/\d{1,2}/\d{1,2})"))

    _, pt = _fubon_text(f"https://websys.fsit.com.tw/FubonETF/Trade/Pcf.aspx?stkId={fid}&lan=TW")
    ann = iso(_after(pt, "申購買回清單", r"(\d{3,4}/\d{1,2}/\d{1,2})") or re.search(r"(\d{4}/\d{1,2}/\d{1,2})", pt).group(1))
    nav = num(_after(pt, "每受益權單位淨資產價值"))
    osu = inum(_after(pt, "已發行受益權單位總數"))
    diff = inum(_after(pt, "與前日已發行單位差異數"))
    base = inum(_after(pt, "每現金申購/買回基數之受益權單位數") or _after(pt, "基數之受益權單位數"))
    bm = re.search(r"上一個月之受益人人數\s*\(?\s*(\d{3,4})/(\d{1,2})\s*\)?[^0-9]{0,20}([\d,]+)", pt)
    s = {"totalav": num(_after(pt, "基金淨資產價值")), "nav": nav, "osunit": osu, "issuesdiff": diff, "baseunit": base,
         "beneficiaries": inum(bm.group(3)) if bm else None,
         "ben_month": f"{int(bm.group(1)) + (1911 if int(bm.group(1)) < 1000 else 0)}{int(bm.group(2)):02d}" if bm else None,
         "stkvalues": stocks_value(stocks)}
    items = [["公告日期（適用申購日）", ann, "date"],
             ["每現金申購／買回基數之受益權單位數", base, ""],
             ["預收申購總價金", num(_after(pt, "預收申購總價金")), "NTD"],
             ["每現金申購／買回基數約當市值", num(_after(pt, "約當市值")), "NTD"],
             ["總價金差異額", num(_after(pt, "總價金差異額")), "NTD"],
             ["實際申購總價金", num(_after(pt, "實際申購總價金")), "NTD"],
             ["與前日已發行單位差異數", diff, "sgn"]]
    date = hold_date or prev_trading_day(ann)
    for x in stocks:
        x.pop("amt", None)
    return {"code": code, "date": date, "name": "富邦台50", "updated": ann, "ann_date": ymd(ann),
            "summary": s, "stocks": stocks, "futures": futures, "inkind": [], "pcf_items": items, "memo": []}


def prev_trading_day(d: str | None) -> str | None:
    """公告日的前一個交易日（以加權指數交易日判斷；無資料時往前找平日）"""
    if not d:
        return None
    day = dt.date.fromisoformat(d)
    try:
        import pandas as pd
        tx = pd.read_csv(ROOT.parent / "data" / "taiex.csv", usecols=["date"])["date"]
        prev = [x for x in tx if x < d]
        if prev and (day - dt.date.fromisoformat(prev[-1])).days < 10:
            return prev[-1]
    except Exception:  # noqa: BLE001
        pass
    day -= dt.timedelta(days=1)
    while day.weekday() >= 5:
        day -= dt.timedelta(days=1)
    return day.isoformat()


# ---------------------------------------------------------------- 統一 (ezmoney)
def fetch_ezmoney(code: str, fid: str) -> dict:
    s = requests.Session()
    s.headers.update(UA)
    hist = None
    if DAY:
        # 歷史查詢以公告日（ANN）查詢，回傳的是前一交易日（DAY）的持股與申購買回清單
        s.get(f"https://www.ezmoney.com.tw/ETF/Transaction/PCF?fundCode={fid}", timeout=60)

        def get_pcf(day: str) -> dict:
            dd = dt.date.fromisoformat(day)
            hr = s.post("https://www.ezmoney.com.tw/ETF/Transaction/GetPCF", timeout=60,
                        json={"fundCode": fid, "date": f"{dd.year - 1911}/{dd:%m/%d}", "specificDate": True},
                        headers={"Referer": f"https://www.ezmoney.com.tw/ETF/Transaction/PCF?fundCode={fid}"})
            hr.raise_for_status()
            return hr.json()
        hist = get_pcf(ANN)
        assets = hist.get("asset") or []
        if isinstance(assets, str):
            assets = json.loads(assets)
    else:
        r = s.get(f"https://www.ezmoney.com.tw/ETF/Fund/Info?fundCode={fid}", timeout=60)
        r.raise_for_status()
        m = re.search(r'id="DataAsset"[^>]*data-content="([^"]*)"', r.text)
        if not m:
            raise RuntimeError(f"{code} 找不到持股資料")
        assets = json.loads(htmlmod.unescape(m.group(1)))
    by = {a.get("AssetCode"): a for a in assets}
    det = lambda k: (by.get(k) or {}).get("Details") or []  # noqa: E731
    stocks = [{"c": str(x.get("DetailCode")).strip(), "n": (x.get("DetailName") or "").strip(), "q": inum(x.get("Share")),
               "w": num(x.get("NavRate")), "amt": num(x.get("Amount"))} for x in det("ST")]
    futures = [{"c": str(x.get("DetailCode")).strip(), "n": (x.get("DetailName") or "").strip(),
                "ym": re.sub(r"\D", "", str(x.get("MTH") or ""))[:6] or None,
                "q": inum(x.get("Share")) * (-1 if str(x.get("Position", "B")).upper().startswith("S") else 1)
                if x.get("Share") is not None else None, "w": num(x.get("NavRate"))} for x in det("GD")]
    hold_date = next((iso(jsdate(x.get("TranDate"))) for x in det("ST") if x.get("TranDate")), None)

    if hist is not None:
        pj = hist
    else:
        tw = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date()
        q = {"fundCode": fid, "date": f"{tw.year - 1911}/{tw:%m/%d}", "specificDate": False}
        pr = s.post("https://www.ezmoney.com.tw/ETF/Transaction/GetPCF", json=q, timeout=60,
                    headers={"Referer": f"https://www.ezmoney.com.tw/ETF/Transaction/PCF?fundCode={fid}"})
        pr.raise_for_status()
        pj = pr.json()
    pcf = {x.get("PCFCode"): x for x in (pj.get("pcf") or [])}
    v = lambda k: num((pcf.get(k) or {}).get("Amount"))  # noqa: E731
    any_ = next(iter(pcf.values()), {})
    tran, post = iso(jsdate(any_.get("TranDate"))), iso(jsdate(any_.get("PostDate")))
    nav = v("P_UNIT") or num((by.get("P_UNIT") or {}).get("Amount"))
    s_ = {"totalav": v("NAV") or num((by.get("NAV") or {}).get("Amount")), "nav": nav,
          "osunit": inum(v("OUT_UNIT") or (by.get("OUT_UNIT") or {}).get("Amount")),
          "issuesdiff": inum(v("DIFF_UNIT")), "baseunit": inum(v("FUND_BASEUNIT")),
          "stkvalues": stocks_value(stocks), "futvalues": None}
    items = [["公告日期（適用申購日）", post, "date"],
             ["每現金申購／買回基數之受益權單位數", s_["baseunit"], ""],
             ["每現金申購／買回基數約當淨值", v("BASEUNIT_MRK_VAL"), "NTD"],
             ["預收申購總價金", v("PRE_AMT"), "NTD"],
             ["實際申購總價金差額（前一日）", v("DIFF_ACT_AMT"), "NTD"],
             ["與前日已發行單位差異數", s_["issuesdiff"], "sgn"]]
    date = hold_date or tran
    if tran and hold_date and tran != hold_date:
        # 持股與 PCF 日期不一致（其中一邊尚未更新）時，申購贖回數字不套用到持股日
        s_["issuesdiff"] = s_["issuesdiff"] if tran == date else None
    for x in stocks:
        x.pop("amt", None)
    return {"code": code, "date": date, "name": "統一台股增長主動式", "updated": jsdate(any_.get("EditDate")),
            "ann_date": ymd(post), "summary": s_, "stocks": stocks, "futures": futures, "inkind": [],
            "pcf_items": items, "memo": []}


# ---------------------------------------------------------------- 國泰
CATHAY = "https://cwapi.cathaysite.com.tw/api/"


def _cathay(ep: str, **params):
    r = requests.get(CATHAY + ep, params=params, timeout=60,
                     headers={**UA, "Origin": "https://www.cathaysite.com.tw", "Referer": "https://www.cathaysite.com.tw/"})
    r.raise_for_status()
    j = r.json()
    return j.get("result") if str(j.get("returnCode")) == "2000" else None


def fetch_cathay(code: str, fid: str) -> dict:
    a = (_cathay("ETF/GetETFAssets", FundCode=fid, SearchDate=DAY) if DAY else _cathay("ETF/GetETFAssets", FundCode=fid)) or {}
    date = iso(a.get("preDate"))
    if not date:
        raise RuntimeError(f"{code} 無資料日期")
    st = _cathay("ETF/GetETFDetailStockList", FundCode=fid, SearchDate=date) or []
    ft = _cathay("ETF/GetETFDetailFutureList", FundCode=fid, SearchDate=date) or []
    b = (_cathay("BuySale/GetBuySale", FundCode=fid, SearchDate=ANN) if DAY else _cathay("BuySale/GetBuySale", FundCode=fid)) or {}
    stocks = [{"c": str(x.get("stockCode")).strip(), "n": (x.get("stockName") or "").strip(), "q": inum(x.get("volumn")),
               "w": num(x.get("weights"))} for x in st]
    futures = []
    for x in ft:
        c = str(x.get("ftNo") or "").strip()
        ym = re.sub(r"\D", "", str(x.get("ftDate") or ""))[:6]
        futures.append({"c": c, "n": (x.get("ftName") or "").strip(), "ym": ym or None,
                        "q": inum(x.get("volumn")), "w": num(x.get("ntMkval"))})
    inkind = []
    if "實物" in str(b.get("pbTypeString") or "") and b.get("date"):
        for x in _cathay("BuySale/GetStocksList", FundCode=fid, SearchDate=iso(b.get("date"))) or []:
            inkind.append({"c": str(x.get("prod")).strip(), "n": (x.get("prodName") or "").strip(),
                           "q": inum(x.get("basketShares")), "cash": "Y" if x.get("isCashReplace") else "N",
                           "min": "Y" if x.get("isSmallestBuy") else "N"})
    bdate = iso(b.get("preDateC"))
    same = bdate == date
    bm = iso(b.get("dataDate"))
    s = {"totalav": num(a.get("fundNav")), "nav": num(a.get("fundPerNav")), "osunit": inum(a.get("fundOutstandingShares")),
         "issuesdiff": inum(b.get("diffUnit")) if same else None, "baseunit": inum(b.get("basketUnit")),
         "beneficiaries": inum(b.get("benefiCount")), "ben_month": bm.replace("-", "")[:6] if bm else None}
    items = [["公告日期（適用申購日）", iso(b.get("date")), "date"],
             ["申購方式", b.get("pbTypeString") or "—", "txt"],
             ["每現金申購／買回基數之受益權單位數", s["baseunit"], ""],
             ["每現金申購／買回基數約當淨值", num(b.get("basketNav")), "NTD"],
             ["每現金申購／買回基數約當市值", num(b.get("marketVal")), "NTD"],
             ["預收申購總價金", num(b.get("preAmtS")), "NTD"],
             ["與前日已發行單位差異數", inum(b.get("diffUnit")), "sgn"]]
    return {"code": code, "date": date, "name": "國泰永續高股息", "updated": b.get("date") or a.get("preDate"),
            "ann_date": ymd(b.get("date")), "summary": s, "stocks": stocks, "futures": futures, "inkind": inkind,
            "pcf_items": items, "memo": []}


# ---------------------------------------------------------------- 凱基
def _table_text(html_: str) -> str:
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html_, flags=re.S | re.I)
    t = htmlmod.unescape(re.sub(r"<[^>]+>", "|", t))
    return re.sub(r"(\|\s*)+", "|", re.sub(r"\s+", " ", t))


def fetch_kgi(code: str, fid: str) -> dict:
    r = requests.post("https://www.kgifund.com.tw/Fund/RedemptionVC", data={"fundID": fid, **({"queryDate": ANN.replace("-", "/")} if DAY else {})}, timeout=60,
                      headers={**UA, "Referer": f"https://www.kgifund.com.tw/Fund/RedemptionList?fundNo={fid}"})
    r.raise_for_status()
    t = _table_text(r.text)
    f = lambda label: _after(t, label)  # noqa: E731
    ann = iso(re.search(r"(\d{4}/\d{1,2}/\d{1,2})\s*\|?\s*現金申購買回清單", t).group(1))
    dm = re.search(r"\((\d{4}/\d{1,2}/\d{1,2})\)", t)
    date = iso(dm.group(1)) if dm else prev_trading_day(ann)
    stocks, futures = [], []
    seg = t.split("|股票|股票代號|股票名稱|股數|權重(%)|", 1)
    if len(seg) == 2:
        body = seg[1].split("|期貨|", 1)[0]
        for m in re.finditer(r"([0-9A-Z]{4,6})\s*\|([^|]+)\|([\d,]+)\|([\d.]+)\|", body):
            stocks.append({"c": m.group(1), "n": m.group(2).strip(), "q": inum(m.group(3)), "w": num(m.group(4))})
    fseg = t.split("|期貨代號|期貨名稱|口數|權重(%)|契約年月|", 1)
    if len(fseg) == 2:
        for m in re.finditer(r"([A-Z0-9]+)\s*\|([^|]+)\|(-?[\d,]+)\|(-?[\d.]+)\|(\d{4})/(\d{1,2})", fseg[1]):
            futures.append({"c": m.group(1), "n": m.group(2).strip(), "ym": f"{m.group(5)}{int(m.group(6)):02d}",
                            "q": inum(m.group(3)), "w": num(m.group(4))})
    diff = inum(f("與前日已發行單位差異數"))
    s = {"totalav": num(f("基金淨資產價值")), "nav": num(f("每受益權單位淨資產價值")), "osunit": inum(f("已發行受益權單位總數")),
         "issuesdiff": diff, "baseunit": 500000}
    items = [["公告日期（適用申購日）", ann, "date"],
             ["每申購基數之預收申購總價金", num(f("預收申購總價金")), "NTD"],
             ["每現金申購單位約當市值", num(f("約當市值")), "NTD"],
             ["每基數申購總價金差異額", num(f("申購總價金差異額")), "NTD"],
             ["每基數實際申購總價金", num(f("實際申購總價金")), "NTD"],
             ["與前日已發行單位差異數", diff, "sgn"]]
    return {"code": code, "date": date, "name": code, "updated": ann, "ann_date": ymd(ann), "summary": s,
            "stocks": stocks, "futures": futures, "inkind": [], "pcf_items": items, "memo": []}


# ---------------------------------------------------------------- 大華銀
def fetch_uob(code: str, fid: str) -> dict:
    import urllib3
    urllib3.disable_warnings()
    # 大華銀官網憑證鏈不完整（缺中繼憑證），只讀公開資料，此網域略過憑證驗證
    r = requests.get("https://www.uobam.com.tw/json/reply/WebSitePcfRequest", params={"fundID": fid, "pcfDate": ANN.replace("-", "/") if DAY else ""},
                     headers={**UA, "Accept": "application/json"}, timeout=60, verify=False)
    r.raise_for_status()
    j = r.json()
    date, ann = iso(jsdate(j.get("datadate"))), iso(jsdate(j.get("announce")))
    stocks, futures = [], []
    for x in j.get("result") or []:
        if x.get("kind") == "stock":
            stocks.append({"c": str(x.get("code")).strip(), "n": (x.get("cName") or "").strip(), "q": inum(x.get("qty")),
                           "w": num(x.get("weight"))})
        elif x.get("kind") == "futures":
            futures.append({"c": str(x.get("code")).strip(), "n": (x.get("cName") or "").strip(),
                            "ym": re.sub(r"\D", "", str(x.get("dym") or ""))[:6] or None, "q": inum(x.get("qty")),
                            "w": num(x.get("weight"))})
    diff = inum(j.get("issuesDiff"))
    s = {"totalav": num(j.get("totalAV")), "nav": num(j.get("nav")), "osunit": inum(j.get("totalIssues")),
         "issuesdiff": diff, "baseunit": inum(j.get("baseValue"))}
    items = [["公告日期（適用申購日）", ann, "date"],
             ["每現金申購／買回基數之受益權單位數", s["baseunit"], ""],
             ["預收申購總價金", num(j.get("basketValue")), "NTD"],
             ["每基數約當市值", num(j.get("estcValue")), "NTD"],
             ["實際申購總價金", num(j.get("basketValueP")), "NTD"],
             ["總價金差異額", num(j.get("diffBasketValue")), "NTD"],
             ["與前日已發行單位差異數", diff, "sgn"]]
    return {"code": code, "date": date, "name": code, "updated": jsdate(j.get("publish")), "ann_date": ymd(ann),
            "summary": s, "stocks": stocks, "futures": futures, "inkind": [], "pcf_items": items, "memo": []}


# ---------------------------------------------------------------- 復華
def fetch_fuhhwa(code: str, fid: str) -> dict:
    H = {**UA, "Accept": "application/json", "Referer": f"https://www.fhtrust.com.tw/ETF/etf_detail/{fid}"}
    today = dt.date.fromisoformat(DAY) if DAY else dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date()
    a = None
    for back in range(1 if DAY else 8):  # 由今天往回找最近一個有資料的日子
        d = today - dt.timedelta(days=back)
        r = requests.get("https://www.fhtrust.com.tw/api/assets", params={"fundID": fid, "qDate": f"{d:%Y/%m/%d}"},
                         headers=H, timeout=60)
        r.raise_for_status()
        res = (r.json().get("result") or [{}])[0]
        if res.get("detail"):
            a = res
            break
    if not a:
        raise RuntimeError(f"{code} 近一週無持股資料")
    stocks, futures = [], []
    for x in a["detail"]:
        w = num(x.get("prate_addaccint"))
        if x.get("ftype") == "股票":
            stocks.append({"c": str(x.get("stockid")).strip(), "n": (x.get("stockname") or "").strip(),
                           "q": inum(x.get("qshare")), "w": w})
        elif x.get("ftype") == "期貨":
            nm = (x.get("stockname") or "").strip()
            m = re.search(r"(\d{4})/?(\d{2})", str(x.get("stockid")) + nm)
            futures.append({"c": str(x.get("stockid")).strip(), "n": nm, "ym": m.group(1) + m.group(2) if m else None,
                            "q": inum(x.get("qshare")), "w": w})
    date = iso(a.get("dDate"))
    tot = {x.get("ftype"): num(x.get("tot_mvalue")) for x in a.get("result") or [] if x.get("ftype") in ("股票", "期貨")}
    p = {}
    for back in range(8):
        d = (dt.date.fromisoformat(ANN) if DAY else today) - dt.timedelta(days=back)
        r = requests.get("https://www.fhtrust.com.tw/api/ETFPcf", params={"fundID": fid, "pcfDate": f"{d:%Y/%m/%d}"},
                         headers=H, timeout=60)
        rr = (r.json().get("result") or [{}]) if r.ok else [{}]
        if rr and rr[0].get("postDate"):
            p = rr[0]
            break
    same = iso(p.get("actCashDiffDate")) == date
    s = {"totalav": num(a.get("pcf_FundNav")), "nav": num(a.get("pcf_Fundpnav")), "osunit": inum(a.get("pcf_FundQissue")),
         "issuesdiff": inum(p.get("qDiff")) if same else None, "baseunit": inum(p.get("sharesPerUnit")),
         "stkvalues": tot.get("股票"), "futvalues": tot.get("期貨")}
    items = [["公告日期（適用申購日）", iso(p.get("postDate")), "date"],
             ["每現金申購／買回基數之受益權單位數", s["baseunit"], ""],
             ["預收申購總價金", num(p.get("preBuyVal")), "NTD"],
             ["每基數約當市值", num(p.get("mVal")), "NTD"],
             ["實際申購總價金差額", num(p.get("actCashDiff")), "NTD"],
             ["實際申購總價金", num(p.get("actBuyVal")), "NTD"],
             ["與前日已發行單位差異數", inum(p.get("qDiff")), "sgn"]]
    return {"code": code, "date": date, "name": code, "updated": p.get("postDate"), "ann_date": ymd(p.get("postDate")),
            "summary": s, "stocks": stocks, "futures": futures, "inkind": [], "pcf_items": items, "memo": []}


FETCH = {"yuanta": fetch_yuanta, "capital": fetch_capital, "fubon": fetch_fubon, "ezmoney": fetch_ezmoney,
         "cathay": fetch_cathay, "kgi": fetch_kgi, "uob": fetch_uob, "fuhhwa": fetch_fuhhwa}


def fetch(code: str) -> dict:
    issuer, fid = ETFS[code]
    doc = FETCH[issuer](code, fid)
    doc["issuer"] = ISSUER[issuer]
    doc["name"] = NAMES.get(code) or doc["name"]
    doc["stocks"] = [s for s in doc["stocks"] if s["c"] and s["w"] is not None]
    return doc


def update(data: Path, log=print):
    for code in ETFS:
        try:
            doc = fetch(code)
        except Exception as e:  # noqa: BLE001
            log(f"etf {code}: 失敗 {e}")
            continue
        if not doc.get("date") or not doc["stocks"] and not doc["futures"]:
            log(f"etf {code}: 無持股資料，略過")
            continue
        folder = data / "etf" / code
        folder.mkdir(parents=True, exist_ok=True)
        p = folder / f"{doc['date']}.json"
        old = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
        if old and old == doc:
            continue
        if old:
            # 同一資料日重抓：先前已取得的申購贖回數字不要被「尚未更新」的空值蓋掉
            for k, v in (old.get("summary") or {}).items():
                if doc["summary"].get(k) is None and v is not None:
                    doc["summary"][k] = v
        p.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        log(f"etf {code}: {doc['date']} 持股 {len(doc['stocks'])} 檔、期貨 {len(doc['futures'])}、"
            f"申購籃 {len(doc['inkind'])} 檔（{doc['issuer']} {doc.get('updated')}）")


def trading_days() -> list[str]:
    import pandas as pd
    tx = pd.read_csv(ROOT.parent / "data" / "taiex.csv", usecols=["date"])["date"]
    return sorted(str(x) for x in tx)


def backfill(data: Path, start: str, end: str, codes=None, log=print):
    """回補 start ~ end（含）之間各交易日的持股與申購買回清單；已有紀錄的日子略過"""
    import time
    global DAY, ANN
    days = trading_days()
    targets = [d for d in days if start <= d <= end]
    stats = {}
    for code in codes or list(ETFS):
        issuer, _ = ETFS[code]
        if issuer == "fubon":
            log(f"etf {code}: 富邦官網只提供最新一日持股，無法回補")
            continue
        ok = miss = 0
        folder = data / "etf" / code
        for T in targets:
            if (folder / f"{T}.json").exists():
                continue
            i = days.index(T)
            DAY, ANN = T, (days[i + 1] if i + 1 < len(days) else None)
            if not ANN:
                continue
            try:
                doc = fetch(code)
            except Exception as e:  # noqa: BLE001
                log(f"etf {code} {T}: 失敗 {str(e)[:150]}")
                miss += 1
                continue
            finally:
                time.sleep(0.4)
            if doc.get("date") != T or not (doc["stocks"] or doc["futures"]):
                log(f"etf {code} {T}: 官網無此日資料（回傳 {doc.get('date')}，持股 {len(doc['stocks'])}）")
                miss += 1
                continue
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"{T}.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            ok += 1
        stats[code] = (ok, miss)
        log(f"etf {code}: 回補 {ok} 天，缺 {miss} 天")
    DAY = ANN = None
    return stats


def write(data: Path, site: Path):
    listing, flows = [], {}
    for code in ETFS:
        files = sorted((data / "etf" / code).glob("20*.json"))
        if not files:
            continue
        out = site / "data" / "etf" / code
        out.mkdir(parents=True, exist_ok=True)
        prev = None
        dates = []
        for p in files:
            doc = json.loads(p.read_text(encoding="utf-8"))
            doc.setdefault("issuer", "元大")
            # 與前一筆紀錄比較：持股股數／權重增減、新增與剔除
            if prev:
                pq = {s["c"]: s for s in prev["stocks"]}
                for s in doc["stocks"]:
                    o = pq.get(s["c"])
                    s["dq"] = None if o is None or s["q"] is None or o["q"] is None else s["q"] - o["q"]
                    s["dw"] = None if o is None or s["w"] is None or o["w"] is None else round(s["w"] - o["w"], 2)
                    s["new"] = o is None
                cur = {s["c"] for s in doc["stocks"]}
                doc["removed"] = [{"c": s["c"], "n": s["n"], "q": s["q"], "w": s["w"]} for s in prev["stocks"] if s["c"] not in cur]
                doc["prev_date"] = prev["date"]
                # 期貨部位：同一商品同一月份比較口數；轉倉時舊月份列為已平倉
                pf = {(f["c"], f.get("ym")): f for f in prev.get("futures") or []}
                for f in doc["futures"]:
                    o = pf.get((f["c"], f.get("ym")))
                    f["dq"] = (f["q"] or 0) - (o["q"] or 0) if o else f["q"]
                    f["new"] = o is None
                curf = {(f["c"], f.get("ym")) for f in doc["futures"]}
                doc["fut_removed"] = [{"c": f["c"], "n": f["n"], "ym": f.get("ym"), "q": 0, "dq": -(f["q"] or 0), "w": 0}
                                      for k, f in pf.items() if k not in curf]
            prev = json.loads(p.read_text(encoding="utf-8"))
            s = doc["summary"]
            flows.setdefault(doc["date"], []).append({
                "code": code, "name": doc["name"], "nav": s.get("nav"), "osunit": s.get("osunit"),
                "diff": s.get("issuesdiff"), "base": s.get("baseunit"), "totalav": s.get("totalav")})
            (out / p.name).write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            dates.append(doc["date"])
        (out / "index.json").write_text(json.dumps({"code": code, "name": doc["name"], "dates": dates}, ensure_ascii=False),
                                        encoding="utf-8")
        listing.append({"code": code, "name": doc["name"]})
        print(f"etf {code}: {len(dates)} 天，最新 {dates[-1]}")
    (site / "data" / "etf").mkdir(parents=True, exist_ok=True)
    write_holdings(data, site)
    (site / "data" / "etf" / "list.json").write_text(json.dumps(listing, ensure_ascii=False), encoding="utf-8")
    # 申購贖回總表：每個日期所有追蹤 ETF 的淨申購／贖回
    (site / "data" / "etf" / "flows.json").write_text(json.dumps(flows, ensure_ascii=False, separators=(",", ":")),
                                                      encoding="utf-8")


def write_holdings(data: Path, site: Path):
    """
    持股總表：以個股為主體，加總所有追蹤 ETF 的持股股數與當日增減。
    某日 D：每檔 ETF 取資料日 ≤ D 的最新一筆；資料日 = D 才計入當日增減（與該 ETF 前一筆比較），
    尚未更新到 D 的 ETF 只計入持股、不計增減。
    """
    recs = {}   # code -> [(date, name, {stock: (name, q)})]
    for code in ETFS:
        lst = []
        for p in sorted((data / "etf" / code).glob("20*.json")):
            d = json.loads(p.read_text(encoding="utf-8"))
            lst.append((d["date"], NAMES.get(code) or d["name"],
                        {x["c"]: (x["n"], x["q"]) for x in d["stocks"] if x.get("q") is not None}))
        if lst:
            recs[code] = lst
    shares = {}   # 發行股數（上市／上櫃股本資料）
    for f in ("shares_twse.csv", "shares_tpex.csv"):
        p = data / f
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines()[1:]:
                c, _, v = line.partition(",")
                try:
                    if float(v) > 0:
                        shares[c.strip()] = float(v)
                except ValueError:
                    pass
    out = site / "data" / "etf" / "holdings"
    out.mkdir(parents=True, exist_ok=True)
    dates = sorted({r[0] for lst in recs.values() for r in lst})
    for D in dates:
        etfs, agg = [], {}
        for code, lst in recs.items():
            i = max((k for k, r in enumerate(lst) if r[0] <= D), default=None)
            if i is None:
                continue
            date, name, cur = lst[i]
            prev = lst[i - 1][2] if i > 0 else None
            status = "stale" if date < D else ("first" if prev is None else "upd")
            etfs.append([code, name, date, status])
            codes = set(cur) | (set(prev) if status == "upd" else set())
            for c in codes:
                n, q = cur.get(c, (None, 0))
                if n is None:
                    n = prev[c][0]
                dq = q - prev.get(c, (None, 0))[1] if status == "upd" else None
                a = agg.setdefault(c, {"n": n, "q": 0, "dq": 0, "known": False, "by": []})
                a["q"] += q
                if dq is not None:
                    a["dq"] += dq
                    a["known"] = True
                a["by"].append([code, q, dq])
        rows = []
        for c, a in agg.items():
            a["by"].sort(key=lambda x: -x[1])
            sh = shares.get(c)
            rows.append([c, a["n"], a["q"], a["dq"] if a["known"] else None, sum(1 for b in a["by"] if b[1] > 0), a["by"],
                         round(a["q"] / sh * 100, 3) if sh else None])     # [6] ETF 合計持股占股本(%)
        rows.sort(key=lambda r: -(r[6] or 0))
        (out / f"{D}.json").write_text(json.dumps({"date": D, "etfs": etfs, "rows": rows}, ensure_ascii=False,
                                                  separators=(",", ":")), encoding="utf-8")
    (out / "index.json").write_text(json.dumps(dates), encoding="utf-8")
    print(f"etf 持股總表: {len(dates)} 天")


if __name__ == "__main__":
    import sys
    if sys.argv[1:2] == ["--backfill"]:
        # python scripts/etf.py --backfill 2026-10-01 2026-11-16 [代號 ...]
        backfill(ROOT.parent / "data", sys.argv[2], sys.argv[3], sys.argv[4:] or None)
        sys.exit(0)
    for c in sys.argv[1:] or list(ETFS):
        try:
            d = fetch(c)
            print("DOC", c, json.dumps({k: v for k, v in d.items() if k not in ("stocks",)}, ensure_ascii=False)[:1500])
            print("STK", c, len(d["stocks"]), d["stocks"][:3], "sumw", round(sum(s["w"] or 0 for s in d["stocks"]), 2))
        except Exception as e:  # noqa: BLE001
            import traceback
            print("ERR", c, e)
            traceback.print_exc()
