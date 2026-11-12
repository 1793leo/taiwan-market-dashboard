"""
計算「市場均線風向」並產生網站：
  above5  = 收盤價 > 自身近 5 個交易日收盤均價 的普通股家數
  above20 = 收盤價 > 自身近 20 個交易日收盤均價 的普通股家數
  total5/total20 = 當日有收盤價且均價可計算的家數（分母）
均價以個股「有成交」的交易日計算（停牌/無成交日不納入）。
"""
from __future__ import annotations

import datetime as dt
import json
import re
import shutil
from pathlib import Path

import pandas as pd

import contrib
import hot
import block
import cb

ROOT = Path(__file__).resolve().parent.parent
WINDOWS = (5, 20)


def load_stocks(data: Path) -> pd.DataFrame:
    frames = []
    for market in ("twse", "tpex"):
        for p in sorted((data / "stocks" / market).glob("*.csv")):
            f = pd.read_csv(p, dtype={"code": str}, usecols=["date", "code", "close"])
            f["market"] = market
            frames.append(f)
    if not frames:
        return pd.DataFrame(columns=["date", "code", "close", "market"])
    df = pd.concat(frames, ignore_index=True)
    # 轉市（上櫃→上市）同代號同日只留一筆
    return df.drop_duplicates(["date", "code"], keep="last")


def compute_breadth(stocks: pd.DataFrame) -> pd.DataFrame:
    df = stocks.dropna(subset=["close"]).sort_values(["code", "date"]).copy()
    g = df.groupby("code")["close"]
    out = {}
    for n in WINDOWS:
        ma = g.transform(lambda s, n=n: s.rolling(n, min_periods=n).mean())
        valid = ma.notna()
        df[f"v{n}"] = valid
        df[f"b{n}"] = valid & (df["close"] > ma)
    agg = df.groupby("date").agg(
        above5=("b5", "sum"), total5=("v5", "sum"),
        above20=("b20", "sum"), total20=("v20", "sum"),
        stocks=("code", "count"),
        twse=("market", lambda s: (s == "twse").sum()),
        tpex=("market", lambda s: (s == "tpex").sum()),
    ).reset_index()
    return agg.sort_values("date")


def write_ma_live(stocks: pd.DataFrame, site: Path):
    """
    盤中即時均線風向用的門檻值。
    收盤價 p 高於「含今日的 N 日均價」⇔ p > (前 N-1 個有成交日收盤價的平均)
    因此每檔只需前端拿即時價和 t5（前 4 日均）、t20（前 19 日均）比較。
    """
    last = stocks["date"].max()
    df = stocks.dropna(subset=["close"]).sort_values(["code", "date"])
    recent = sorted(df["date"].unique())[-20:]                  # 近 20 個交易日有成交過的都要納入
    df = df[df["code"].isin(df.loc[df["date"].isin(recent), "code"])]
    tail = df.groupby("code").tail(19)
    g = tail.groupby("code")
    n = g["close"].count()
    t20 = g["close"].mean().where(n >= 19)
    t5 = tail.groupby("code").tail(4).groupby("code")["close"].mean().where(n >= 4)
    mkt = df.groupby("code")["market"].last().map({"twse": "tse", "tpex": "otc"})
    out = {"date": last, "tse": [], "otc": []}
    for code in mkt.index:
        a, b = t5.get(code), t20.get(code)
        out[mkt[code]].append([code, None if pd.isna(a) else round(float(a), 6), None if pd.isna(b) else round(float(b), 6)])
    (site / "data" / "ma_live.json").write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(f"ma_live {last}: 上市 {len(out['tse'])} 上櫃 {len(out['otc'])}")


def build(data: Path, site: Path, start: dt.date | None = None):
    tx = pd.read_csv(data / "taiex.csv")
    tx = tx[tx["turnover"].notna()]          # 排除盤中未收盤的當日指數（無成交金額）
    stocks = load_stocks(data)
    br = compute_breadth(stocks)

    # 只輸出「兩個市場都已抓到」且指數有資料的日子；前 20 天暖機期不輸出
    if len(br):
        br = br[(br["twse"] > 0) & (br["tpex"] > 0) & (br["total20"] > 0)]
    if start:
        tx = tx[tx["date"] >= start.isoformat()]
        br = br[br["date"] >= start.isoformat()]

    br.to_csv(data / "breadth.csv", index=False)

    site.mkdir(parents=True, exist_ok=True)
    (site / "data").mkdir(exist_ok=True)
    payload = {
        "updated": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"),
        "taiex": {
            "date": tx["date"].tolist(),
            "open": tx["open"].round(2).tolist(),
            "high": tx["high"].round(2).tolist(),
            "low": tx["low"].round(2).tolist(),
            "close": tx["close"].round(2).tolist(),
            "volume": tx["volume"].fillna(0).astype("int64").tolist(),
            "turnover": tx["turnover"].fillna(0).astype("int64").tolist(),
        },
        "breadth": {c: br[c].tolist() for c in ["date", "above5", "total5", "above20", "total20"]},
    }
    for k, v in payload["breadth"].items():
        if k != "date":
            payload["breadth"][k] = [int(x) for x in v]
    (site / "data" / "dashboard.json").write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    write_ma_live(stocks, site)
    contrib.write(data, site)
    hot.write(data, site)
    block.write(data, site)
    cb.write(data, site)
    bl = data / "broker" / "latest.json"
    if bl.exists():
        shutil.copy2(bl, site / "data" / "broker.json")

    for name in ("index.html", "config.json", "assets"):
        src = ROOT / "web" / name
        dst = site / name
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        elif src.exists():
            shutil.copy2(src, dst)

    # 版本參數：每次部署後瀏覽器都會載入最新的 js/css，不會卡在舊快取
    stamp = dt.datetime.now().strftime("%Y%m%d%H%M%S")
    html = site / "index.html"
    html.write_text(re.sub(r'(assets/[\w.-]+\.(?:js|css))"', rf'\1?v={stamp}"', html.read_text(encoding="utf-8")),
                    encoding="utf-8")
    print(f"site built: {site}  breadth days={len(br)}  taiex days={len(tx)}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default=str(ROOT / "_site"))
    ap.add_argument("--years", type=float, default=3)
    a = ap.parse_args()
    st = dt.date.today() - dt.timedelta(days=int(365.25 * a.years))
    build(ROOT / "data", Path(a.site), st)
