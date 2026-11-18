"""
投信異常賣超

資料來源：富邦 e 點通「投信買賣超排行」一日排行
  上市 https://fubon-ebrokerdj.fbs.com.tw/z/zg/zgk.djhtm?A=DD&B=0&C=1
  上櫃 https://fubon-ebrokerdj.fbs.com.tw/z/zg/zgk.djhtm?A=DD&B=1&C=1
每個市場取賣超前 50 名，存成 data/trust/YYYY-MM-DD.csv（原始排行，全部保留）。
網站只列「投信淨賣超張數 > 當日成交量 10%」的普通股；成交量取自 data/stocks 的個股日成交資料。
"""
from __future__ import annotations

import datetime as dt
import html as htmlmod
import json
import re
from pathlib import Path

import pandas as pd
import requests

import twdata

URL = "https://fubon-ebrokerdj.fbs.com.tw/z/zg/zgk.djhtm?A=DD&B={b}&C=1"
MARKETS = {"twse": 0, "tpex": 1}
THRESHOLD = 0.10
TPE = dt.timezone(dt.timedelta(hours=8))
COLS = ["market", "rank", "code", "name", "lots", "close", "change"]


def _cell(s: str) -> str:
    return re.sub(r"\s+", " ", htmlmod.unescape(re.sub(r"<[^>]+>", "", s))).strip()


def _num(s):
    s = str(s).replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def fetch(market: str) -> tuple[str, list[dict]]:
    r = requests.get(URL.format(b=MARKETS[market]), headers=twdata.HEADERS, timeout=30)
    r.raise_for_status()
    r.encoding = "big5"
    h = r.text
    m = re.search(r"日期：\s*(\d{1,2})/(\d{1,2})", _cell(h))
    if not m:
        raise RuntimeError("找不到資料日期")
    today = dt.datetime.now(TPE).date()
    mo, dd = int(m.group(1)), int(m.group(2))
    year = today.year - (1 if mo > today.month else 0)
    date = dt.date(year, mo, dd).isoformat()
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", h, re.S | re.I):
        cells = [_cell(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S | re.I)]
        if len(cells) < 10:
            continue
        rank, name, lots, close, chg = cells[5:10]   # 右半邊是賣超排行
        mm = re.match(r"^(\d{4,6}[A-Z]?)(.*)$", name)
        if not rank.isdigit() or not mm or _num(lots) is None:
            continue
        rows.append({"market": market, "rank": int(rank), "code": mm.group(1), "name": mm.group(2).rstrip("*").strip(),
                     "lots": int(_num(lots)), "close": _num(close), "change": _num(chg)})
    return date, rows


def update(data: Path, log=print):
    folder = data / "trust"
    folder.mkdir(parents=True, exist_ok=True)
    got: dict[str, list] = {}
    for market in MARKETS:
        try:
            d, rows = fetch(market)
        except Exception as e:  # noqa: BLE001
            log(f"trust {market}: 失敗 {e}")
            continue
        got.setdefault(d, []).extend(rows)
        log(f"trust {market}: {d} 賣超 {len(rows)} 檔")
    for d, rows in got.items():
        p = folder / f"{d}.csv"
        new = pd.DataFrame(rows, columns=COLS)
        if p.exists():   # 某一市場這次抓取失敗時，保留先前抓到的資料
            old = pd.read_csv(p, dtype={"code": str})
            new = pd.concat([old[~old["market"].isin(new["market"].unique())], new])
        new.sort_values(["market", "rank"]).to_csv(p, index=False)


def _volumes(data: Path, dates: set[str]) -> pd.DataFrame:
    frames = []
    for market in MARKETS:
        for ym in sorted({d[:7] for d in dates}):
            p = data / "stocks" / market / f"{ym}.csv"
            if p.exists():
                f = pd.read_csv(p, dtype={"code": str}, usecols=["date", "code", "volume"])
                f["market"] = market
                frames.append(f[f["date"].isin(dates)])
    if not frames:
        return pd.DataFrame(columns=["date", "code", "volume", "market"])
    return pd.concat(frames).drop_duplicates(["date", "code"], keep="last")


def write(data: Path, site: Path):
    out = site / "data" / "trust"
    out.mkdir(parents=True, exist_ok=True)
    files = sorted((data / "trust").glob("20*.csv"))
    dates_all = {p.stem for p in files}
    vol = _volumes(data, dates_all).set_index(["date", "code"])["volume"]
    index, months = {}, {}
    for p in files:
        d = p.stem
        df = pd.read_csv(p, dtype={"code": str})
        df = df[df["code"].str.match(twdata.COMMON_STOCK_RE.pattern) & (df["lots"] < 0)]
        rows, pending = [], False
        for r in df.itertuples():
            v = vol.get((d, r.code))
            if v is None or pd.isna(v):
                pending = True     # 個股成交量尚未更新
                continue
            if v <= 0:
                continue
            vl = v / 1000
            ratio = -r.lots / vl
            if ratio > THRESHOLD:
                rows.append([r.code, r.name, "上市" if r.market == "twse" else "上櫃", -int(r.lots), round(vl),
                             round(ratio * 100, 1), r.close, r.change,
                             None if pd.isna(r.close) else round(-r.lots * 1000 * r.close)])   # [8] 賣超金額（張數×收盤價）
        rows.sort(key=lambda x: -(x[8] or 0))
        months.setdefault(d[:7], {})[d] = rows
        index[d] = {"n": len(rows), "pending": pending and not rows}
    for ym, m in months.items():
        (out / f"{ym}.json").write_text(json.dumps(m, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (out / "index.json").write_text(json.dumps({"dates": index, "threshold": THRESHOLD}, ensure_ascii=False,
                                               separators=(",", ":")), encoding="utf-8")
    print(f"trust: {len(index)} 個交易日")


if __name__ == "__main__":
    for mk in MARKETS:
        d, rows = fetch(mk)
        print(mk, d, len(rows), rows[:3], rows[-2:])
