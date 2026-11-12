"""
盤後定價交易：委買／委賣未成交張數 × 成交價，各列前 30 名（普通股）

來源：
  上市：證交所 BFT41U（盤後定價交易）  最後揭示買量／最後揭示賣量（單位：千股＝張）
  上櫃：櫃買中心 afterTrading/fixPricing（盤後定價行情）  委買未成交張數／委賣未成交張數
成交價空白（無成交）時以當日收盤價代替（盤後定價交易即以收盤價撮合）。

儲存：data/post/YYYY-MM-DD.json；網站：_site/data/post.json（最新一日）、_site/data/post_dates.json
"""
from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path

import pandas as pd

import twdata

TOP_N = 30


def fetch_twse(day: dt.date) -> list[dict]:
    j = twdata._request("GET", "https://www.twse.com.tw/rwd/zh/afterTrading/BFT41U",
                        params={"date": day.strftime("%Y%m%d"), "selectType": "ALLBUT0999", "response": "json"})
    if str(j.get("stat", "")).upper() != "OK" or not j.get("data"):
        raise twdata.NoData(f"BFT41U {day}")
    f = [twdata._clean_field(x) for x in j["fields"]]
    ix = {k: f.index(k) for k in ("證券代號", "證券名稱", "成交數量", "成交價", "最後揭示買量", "最後揭示賣量")}
    out = []
    for r in j["data"]:
        code = str(r[ix["證券代號"]]).strip()
        if not twdata.COMMON_STOCK_RE.match(code):
            continue
        out.append({"c": code, "n": str(r[ix["證券名稱"]]).strip(), "m": "tse",
                    "p": twdata.num(r[ix["成交價"]]), "vol": twdata.num(r[ix["成交數量"]]) or 0,
                    "bid": twdata.num(r[ix["最後揭示買量"]]) or 0, "ask": twdata.num(r[ix["最後揭示賣量"]]) or 0})
    return out


def fetch_tpex(day: dt.date) -> list[dict]:
    url = "https://www.tpex.org.tw/www/zh-tw/afterTrading/fixPricing"
    form = {"date": day.strftime("%Y/%m/%d"), "response": "json"}
    try:
        j = twdata._request("POST", url, data=form, retries=3)
    except Exception:  # noqa: BLE001
        j = twdata._request("GET", url, params=form, retries=3)
    t = (j.get("tables") or [{}])[0]
    if not t.get("data"):
        raise twdata.NoData(f"fixPricing {day}")
    f = [twdata._clean_field(x) for x in t["fields"]]

    def col(name):
        return next(i for i, x in enumerate(f) if x.startswith(name))
    ic, inm, ip, iv, ib, ia = col("代號"), col("名稱"), col("成交價"), col("成交張數"), col("委買未成交"), col("委賣未成交")
    out = []
    for r in t["data"]:
        code = str(r[ic]).strip()
        if not twdata.COMMON_STOCK_RE.match(code):
            continue
        out.append({"c": code, "n": str(r[inm]).strip(), "m": "otc", "p": twdata.num(r[ip]),
                    "vol": twdata.num(r[iv]) or 0, "bid": twdata.num(r[ib]) or 0, "ask": twdata.num(r[ia]) or 0})
    return out


def _closes(data: Path, day: str) -> dict[str, float]:
    out = {}
    for market in ("twse", "tpex"):
        p = data / "stocks" / market / f"{day[:7]}.csv"
        if p.exists():
            df = pd.read_csv(p, dtype={"code": str}, usecols=["date", "code", "close"])
            out.update(df[df["date"] == day].dropna(subset=["close"]).set_index("code")["close"].to_dict())
    return out


def update(data: Path, trading_days: list[dt.date], log=print, today: dt.date | None = None):
    folder = data / "post"
    folder.mkdir(parents=True, exist_ok=True)
    for d in trading_days[-5:]:
        p = folder / f"{d.isoformat()}.json"
        if p.exists():
            continue
        try:
            rows = fetch_twse(d)
            time.sleep(3)
            rows += fetch_tpex(d)
        except twdata.NoData as e:
            log(f"post: {e} 尚未公布")
            continue
        except Exception as e:  # noqa: BLE001
            log(f"post: {d} 失敗 {e}")
            continue
        p.write_text(json.dumps({"date": d.isoformat(), "rows": rows}, ensure_ascii=False, separators=(",", ":")),
                     encoding="utf-8")
        log(f"post: {d} 普通股 {len(rows)} 檔")
        time.sleep(2)


def write(data: Path, site: Path):
    files = sorted((data / "post").glob("20*.json"))
    if not files:
        print("post: 尚無資料")
        return
    out_dates = []
    for p in files[-20:]:
        j = json.loads(p.read_text(encoding="utf-8"))
        closes = _closes(data, j["date"])
        rows = []
        for r in j["rows"]:
            price = r["p"] or closes.get(r["c"])
            if not price:
                continue
            rows.append({**r, "p": price, "traded": bool(r["vol"]),
                         "bv": r["bid"] * 1000 * price, "av": r["ask"] * 1000 * price})
        df = pd.DataFrame(rows)
        pick = lambda col, side: [  # noqa: E731
            {"c": x.c, "n": x.n, "m": x.m, "p": x.p, "u": int(getattr(x, side)), "v": float(getattr(x, col)),
             "vol": int(x.vol), "t": bool(x.traded)}
            for x in df[df[side] > 0].sort_values(col, ascending=False).head(TOP_N).itertuples()]
        res = {"date": j["date"], "buy": pick("bv", "bid"), "sell": pick("av", "ask"),
               "buy_total": float(df["bv"].sum()), "sell_total": float(df["av"].sum())}
        (site / "data" / "post").mkdir(parents=True, exist_ok=True)
        (site / "data" / "post" / f"{j['date']}.json").write_text(json.dumps(res, ensure_ascii=False, separators=(",", ":")),
                                                                  encoding="utf-8")
        out_dates.append(j["date"])
    (site / "data" / "post_dates.json").write_text(json.dumps(out_dates), encoding="utf-8")
    print(f"post: {len(out_dates)} 天，最新 {out_dates[-1]}")
