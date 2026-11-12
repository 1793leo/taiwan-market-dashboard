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


def build(data: Path, site: Path, start: dt.date | None = None):
    tx = pd.read_csv(data / "taiex.csv")
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

    contrib.write(data, site)
    hot.write(data, site)
    block.write(data, site)

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
