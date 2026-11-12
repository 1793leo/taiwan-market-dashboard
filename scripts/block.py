"""
鉅額交易（上市＋上櫃，單一證券）

來源：
  上市：證交所 BFIAUU（鉅額交易日成交資訊－單一證券）
  上櫃：櫃買中心 blockTrade/quote（鉅額交易個股最新行情）

儲存：data/block/YYYY-MM.csv（每筆成交一列）、data/block/dates.csv（已抓取日期與筆數）
網站：_site/data/block/index.json（日曆用）、_site/data/block/YYYY-MM.json（每月明細）

當日資料要等晚上才完整（鉅額交易收盤較晚），因此 20:00 前不抓當天。
"""
from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path

import pandas as pd

import twdata

START = dt.date(2026, 1, 1)
READY_HOUR = 20                      # 台北時間 20:00 之後才抓當天
COLS = ["date", "code", "name", "type", "price", "shares", "value", "time", "src"]
TPE = dt.timezone(dt.timedelta(hours=8))


def _clean(s) -> str:
    return " ".join(str(s or "").split())


def fetch_twse(day: dt.date) -> list[dict]:
    j = twdata._request("GET", "https://www.twse.com.tw/rwd/zh/block/BFIAUU",
                        params={"date": day.strftime("%Y%m%d"), "selectType": "S", "response": "json"})
    if str(j.get("stat", "")).upper() != "OK":
        raise twdata.NoData(f"TWSE block {day}: {j.get('stat')}")
    f = [twdata._clean_field(x) for x in j.get("fields", [])]
    ix = {k: f.index(k) for k in ("證券代號", "證券名稱", "交易別", "成交價", "成交股數", "成交金額")}
    out = []
    for r in j.get("data") or []:
        code = _clean(r[ix["證券代號"]])
        if not code or code.startswith("總計") or code == "合計":
            continue
        out.append({"code": code, "name": _clean(r[ix["證券名稱"]]), "type": _clean(r[ix["交易別"]]),
                    "price": twdata.num(r[ix["成交價"]]), "shares": twdata.num(r[ix["成交股數"]]),
                    "value": twdata.num(r[ix["成交金額"]]), "time": "", "src": "twse"})
    return out


def fetch_tpex(day: dt.date) -> list[dict]:
    url = "https://www.tpex.org.tw/www/zh-tw/blockTrade/quote"
    form = {"date": day.strftime("%Y/%m/%d"), "response": "json"}
    try:
        j = twdata._request("POST", url, data=form, retries=3)
    except Exception:  # noqa: BLE001
        j = twdata._request("GET", url, params=form, retries=3)
    tables = j.get("tables") or []
    if not tables:
        raise RuntimeError(f"TPEx block {day}: 無表格 {str(j)[:200]}")
    t = tables[0]
    f = [twdata._clean_field(x) for x in t.get("fields", [])]

    def col(*names):
        for n in names:
            for i, x in enumerate(f):
                if x.startswith(n):
                    return i
        raise RuntimeError(f"TPEx block 欄位改變: {f}")
    ic, inm, ity, ip, ish, iv = col("代號"), col("名稱"), col("交易型態"), col("成交價"), col("成交股數"), col("成交值", "成交金額")
    it = next((i for i, x in enumerate(f) if x.startswith("成交時間")), None)
    out = []
    for r in t.get("data") or []:
        out.append({"code": _clean(r[ic]), "name": _clean(r[inm]),
                    "type": _clean(r[ity]).split("-")[0],          # 「配對交易-單一型」→「配對交易」，與上市一致
                    "price": twdata.num(r[ip]), "shares": twdata.num(r[ish]),
                    "value": twdata.num(r[iv]), "time": _clean(r[it]) if it is not None else "", "src": "tpex"})
    return out


# ---------------------------------------------------------------- storage
def _dates_file(data: Path) -> Path:
    return data / "block" / "dates.csv"


def fetched_dates(data: Path) -> set[str]:
    p = _dates_file(data)
    return set(pd.read_csv(p)["date"]) if p.exists() else set()


def _save(data: Path, day: dt.date, rows: list[dict]):
    d = day.isoformat()
    folder = data / "block"
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / f"{d[:7]}.csv"
    new = pd.DataFrame([{**r, "date": d} for r in rows], columns=COLS)
    if p.exists():
        old = pd.read_csv(p, dtype={"code": str, "time": str})
        new = pd.concat([old[old["date"] != d], new])
    if len(new):
        new.sort_values(["date", "value"], ascending=[True, False]).to_csv(p, index=False)
    dp = _dates_file(data)
    idx = pd.read_csv(dp) if dp.exists() else pd.DataFrame(columns=["date", "count"])
    idx = pd.concat([idx[idx["date"] != d], pd.DataFrame([{"date": d, "count": len(rows)}])])
    idx.sort_values("date").to_csv(dp, index=False)


def update(data: Path, trading_days: list[dt.date], deadline: float, log=print):
    now = dt.datetime.now(TPE)
    have = fetched_dates(data)
    todo = [d for d in trading_days
            if d >= START and d.isoformat() not in have
            and (d < now.date() or (d == now.date() and now.hour >= READY_HOUR))]
    log(f"block: 需抓取 {len(todo)} 天")
    for i, d in enumerate(todo):
        if time.time() > deadline:
            log(f"block: 達到時間上限，剩 {len(todo) - i} 天下次續抓")
            break
        try:
            rows = fetch_twse(d)
            time.sleep(3)
            rows += fetch_tpex(d)
            _save(data, d, rows)
            if (i + 1) % 10 == 0 or i == len(todo) - 1:
                log(f"block: {d} ({i + 1}/{len(todo)}) {len(rows)} 筆")
        except Exception as e:  # noqa: BLE001
            log(f"block: {d} 失敗 {e}")
            time.sleep(20)
        time.sleep(3)


# ---------------------------------------------------------------- site
def write(data: Path, site: Path):
    folder = data / "block"
    out = site / "data" / "block"
    out.mkdir(parents=True, exist_ok=True)
    dates = {}
    for p in sorted(folder.glob("20*.csv")):
        df = pd.read_csv(p, dtype={"code": str, "time": str}).fillna({"time": "", "type": ""})
        month = {}
        for d, g in df.groupby("date"):
            g = g.sort_values("value", ascending=False)
            month[d] = [[r.code, r.name, r.type, r.price, int(r.shares), int(r.value), r.time] for r in g.itertuples()]
            dates[d] = {"n": len(g), "v": int(g["value"].sum())}
        (out / f"{p.stem}.json").write_text(json.dumps(month, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    # 抓過但當天沒有鉅額交易的日子也要標示（日曆可點、顯示「無成交」）
    dp = _dates_file(data)
    if dp.exists():
        for d in pd.read_csv(dp)["date"]:
            dates.setdefault(d, {"n": 0, "v": 0})
    (out / "index.json").write_text(json.dumps({"dates": dict(sorted(dates.items()))}, ensure_ascii=False,
                                               separators=(",", ":")), encoding="utf-8")
    print(f"block: {len(dates)} 個交易日")
