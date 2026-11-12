"""
成交重心股：上市櫃普通股當日成交值前 30 名

輸出 data/hot.json：
  - top  ：最新交易日（盤後官方資料）成交值前 30 名
  - pool ：盤中即時追蹤的候選池＝近 5 個交易日單日成交值最高的 200 檔
           （盤中前 30 名幾乎必定落在其中；即時報價只查這些股票以控制請求量）
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

TOP_N = 30
POOL_N = 200
POOL_DAYS = 5


def _load_recent(data: Path) -> pd.DataFrame:
    frames = []
    for market, ex in (("twse", "tse"), ("tpex", "otc")):
        for p in sorted((data / "stocks" / market).glob("*.csv"))[-2:]:
            f = pd.read_csv(p, dtype={"code": str})
            f["m"] = ex
            frames.append(f)
    df = pd.concat(frames, ignore_index=True)
    if "turnover" not in df.columns:
        df["turnover"] = None
    # 舊資料沒有成交金額時，以 成交股數 × 收盤價 近似
    df["tv"] = df["turnover"].astype(float).fillna(df["volume"] * df["close"])
    return df.dropna(subset=["close"])


def build_hot(data: Path) -> dict:
    df = _load_recent(data)
    dates = sorted(df["date"].unique())
    last, recent = dates[-1], dates[-POOL_DAYS:]

    # 轉市股票（上櫃→上市）同代號只留最新市場
    latest_m = df.sort_values("date").groupby("code")["m"].last()

    prev = df[df["date"] == dates[-2]].set_index("code")["close"] if len(dates) > 1 else pd.Series(dtype=float)
    cur = df[df["date"] == last].drop_duplicates("code", keep="last").copy()
    cur["y"] = cur["code"].map(prev)
    cur["pct"] = (cur["close"] / cur["y"] - 1) * 100
    top = cur.sort_values("tv", ascending=False).head(TOP_N)

    # 前一交易日前 30 名（用來標註「今日新上榜」）
    prev_top = []
    if len(dates) > 1:
        pday = df[df["date"] == dates[-2]].drop_duplicates("code", keep="last")
        prev_top = pday.sort_values("tv", ascending=False).head(TOP_N)["code"].tolist()

    pool = (df[df["date"].isin(recent)].groupby("code")["tv"].max()
            .sort_values(ascending=False).head(POOL_N))
    names = df.sort_values("date").groupby("code")["name"].last()

    out = {
        "date": last,
        "top": [{
            "c": r.code, "n": r.name, "m": r.m, "p": float(r.close),
            "pct": None if pd.isna(r.pct) else round(float(r.pct), 2),
            "v": int(round((r.volume or 0) / 1000)), "tv": float(r.tv),
        } for r in top.itertuples()],
        "prev": prev_top,
        "pool": [{"c": c, "n": names[c], "m": latest_m[c]} for c in pool.index],
    }
    print(f"hot {last}: 前{TOP_N}大合計 {top['tv'].sum() / 1e8:,.0f} 億 / 候選池 {len(out['pool'])} 檔"
          f"（上市 {sum(p['m'] == 'tse' for p in out['pool'])}、上櫃 {sum(p['m'] == 'otc' for p in out['pool'])}）")
    return out


def write(data: Path, site: Path):
    try:
        out = build_hot(data)
    except Exception as e:  # noqa: BLE001
        print(f"hot 失敗: {e}")
        return
    (site / "data").mkdir(parents=True, exist_ok=True)
    (site / "data" / "hot.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
