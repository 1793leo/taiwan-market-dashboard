"""
台股資料抓取模組
- 上市個股：證交所 MI_INDEX (type=ALLBUT0999，不含權證/牛熊證)
- 上櫃個股：櫃買中心 afterTrading/otc (type=EW)，含多重備援端點
- 加權指數：證交所 MI_5MINS_HIST (OHLC) + FMTQIK (成交股數/成交金額)

只保留「普通股」：代號為 4 位數字且首碼非 0
  -> 排除 ETF(00xx/00xxxA)、特別股(2881A)、TDR(91xxxx)、權證(6 碼)、可轉債(5 碼)
"""
from __future__ import annotations

import datetime as dt
import re
import time
from typing import Optional

import requests

COMMON_STOCK_RE = re.compile(r"^[1-9]\d{3}$")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}

_session = requests.Session()
_session.headers.update(HEADERS)


class NoData(Exception):
    """該日/該月沒有資料（休市或尚未公布）"""


# ---------------------------------------------------------------- helpers
def num(v) -> Optional[float]:
    if v is None:
        return None
    s = re.sub(r"<[^>]+>", "", str(v)).replace(",", "").strip()
    if not s or set(s) <= set("-X ") or s in ("除權息", "除權", "除息"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def roc_to_date(s: str) -> dt.date:
    y, m, d = re.split(r"[/-]", s.strip())
    return dt.date(int(y) + 1911, int(m), int(d))


def _clean_field(f: str) -> str:
    return re.sub(r"<[^>]+>|\s", "", str(f))


def _find_col(fields: list[str], *cands: str) -> Optional[int]:
    cf = [_clean_field(f) for f in fields]
    for c in cands:  # exact first
        if c in cf:
            return cf.index(c)
    for c in cands:  # then prefix
        for i, f in enumerate(cf):
            if f.startswith(c):
                return i
    return None


def _request(method: str, url: str, *, params=None, data=None, retries=4, pause=5.0):
    last = None
    for i in range(retries):
        try:
            r = _session.request(method, url, params=params, data=data, timeout=30)
            if r.status_code == 200:
                try:
                    return r.json()
                except ValueError:
                    last = RuntimeError(f"non-JSON response from {url} (可能被限流)")
            else:
                last = RuntimeError(f"HTTP {r.status_code} from {url}")
        except requests.RequestException as e:
            last = e
        time.sleep(pause * (2 ** i))
    raise last  # type: ignore[misc]


def _filter_common(rows: list[dict]) -> list[dict]:
    return [r for r in rows if COMMON_STOCK_RE.match(r["code"])]


# ---------------------------------------------------------------- TWSE stocks
def fetch_twse_stocks(date: dt.date) -> list[dict]:
    j = _request(
        "GET",
        "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX",
        params={"date": date.strftime("%Y%m%d"), "type": "ALLBUT0999", "response": "json"},
    )
    tables = j.get("tables") or []
    # 舊版格式相容 (fields9/data9)
    if not tables and "fields9" in j:
        tables = [{"fields": j["fields9"], "data": j["data9"]}]
    tbl = next((t for t in tables if t.get("fields") and "證券代號" in [_clean_field(f) for f in t["fields"]]), None)
    if not tbl or not tbl.get("data"):
        raise NoData(f"TWSE {date}: {j.get('stat')}")
    f = tbl["fields"]
    ic, iname = _find_col(f, "證券代號"), _find_col(f, "證券名稱")
    io, ih, il, icl = (_find_col(f, k) for k in ("開盤價", "最高價", "最低價", "收盤價"))
    iv = _find_col(f, "成交股數")
    rows = []
    for d in tbl["data"]:
        rows.append({
            "code": str(d[ic]).strip(), "name": str(d[iname]).strip(),
            "open": num(d[io]), "high": num(d[ih]), "low": num(d[il]),
            "close": num(d[icl]), "volume": num(d[iv]),
        })
    return _filter_common(rows)


# ---------------------------------------------------------------- TPEx stocks
def _parse_tpex_tables(j: dict) -> list[dict]:
    tables = j.get("tables") or []
    tbl = next((t for t in tables if t.get("fields") and _find_col(t["fields"], "代號") is not None and t.get("data")), None)
    if not tbl:
        raise NoData("TPEx: no table")
    f = tbl["fields"]
    ic, iname = _find_col(f, "代號"), _find_col(f, "名稱")
    io, ih, il, icl = (_find_col(f, k) for k in ("開盤", "最高", "最低", "收盤"))
    iv = _find_col(f, "成交股數", "成交量")
    if None in (ic, io, ih, il, icl, iv):
        raise RuntimeError(f"TPEx 欄位格式改變: {f}")
    return [{
        "code": str(d[ic]).strip(), "name": str(d[iname]).strip() if iname is not None else "",
        "open": num(d[io]), "high": num(d[ih]), "low": num(d[il]),
        "close": num(d[icl]), "volume": num(d[iv]),
    } for d in tbl["data"]]


def _parse_tpex_legacy(j: dict) -> list[dict]:
    data = j.get("aaData") or []
    if not data:
        raise NoData("TPEx legacy: empty")
    # 舊版欄位：0代號 1名稱 2收盤 3漲跌 4開盤 5最高 6最低 7均價 8成交股數
    return [{
        "code": str(d[0]).strip(), "name": str(d[1]).strip(),
        "open": num(d[4]), "high": num(d[5]), "low": num(d[6]),
        "close": num(d[2]), "volume": num(d[8]),
    } for d in data]


_tpex_pref = 0


def fetch_tpex_stocks(date: dt.date) -> list[dict]:
    ymd = date.strftime("%Y/%m/%d")
    roc = f"{date.year - 1911}/{date:%m/%d}"
    url = "https://www.tpex.org.tw/www/zh-tw/afterTrading/otc"
    attempts = [
        ("POST", url, None, {"date": ymd, "type": "EW", "response": "json"}, _parse_tpex_tables),
        ("GET", url, {"date": ymd, "type": "EW", "response": "json"}, None, _parse_tpex_tables),
        ("GET", "https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/stk_wn1430_result.php",
         {"l": "zh-tw", "d": roc, "se": "EW"}, None, _parse_tpex_legacy),
    ]
    global _tpex_pref
    order = [_tpex_pref] + [i for i in range(len(attempts)) if i != _tpex_pref]
    errors = []
    for idx in order:
        method, u, params, data, parser = attempts[idx]
        try:
            j = _request(method, u, params=params, data=data, retries=2, pause=3)
            rows = _filter_common(parser(j))
            _tpex_pref = idx  # 記住可用端點，之後優先使用
            return rows
        except NoData as e:
            errors.append(e)
            # 有回應但沒資料 → 休市或未公布，不必再試舊端點以外的
            continue
        except Exception as e:  # noqa: BLE001
            errors.append(e)
    if all(isinstance(e, NoData) for e in errors):
        raise NoData(f"TPEx {date}")
    raise RuntimeError(f"TPEx {date} 全部端點失敗: {errors}")


# ---------------------------------------------------------------- TAIEX
def fetch_taiex_month(year: int, month: int) -> list[dict]:
    d = f"{year}{month:02d}01"
    j1 = _request("GET", "https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST",
                  params={"date": d, "response": "json"})
    if not j1.get("data"):
        raise NoData(f"TAIEX {year}-{month}")
    f = j1["fields"]
    i_d, io, ih, il, ic = (_find_col(f, k) for k in ("日期", "開盤指數", "最高指數", "最低指數", "收盤指數"))
    out = {}
    for r in j1["data"]:
        day = roc_to_date(r[i_d])
        out[day] = {"date": day, "open": num(r[io]), "high": num(r[ih]), "low": num(r[il]),
                    "close": num(r[ic]), "volume": None, "turnover": None}
    time.sleep(3)
    j2 = _request("GET", "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK",
                  params={"date": d, "response": "json"})
    if j2.get("data"):
        f = j2["fields"]
        i_d, iv, it = _find_col(f, "日期"), _find_col(f, "成交股數"), _find_col(f, "成交金額")
        for r in j2["data"]:
            day = roc_to_date(r[i_d])
            if day in out:
                out[day]["volume"] = num(r[iv])
                out[day]["turnover"] = num(r[it])
    return sorted(out.values(), key=lambda x: x["date"])
