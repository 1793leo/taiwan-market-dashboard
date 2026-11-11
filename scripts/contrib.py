"""
貢獻點數（上市前 100 大市值）

加權指數 = 上市股票總市值 / 除數，因此
  個股貢獻點數 = 漲跌價差 × 發行股數 / 除數
  除數        = Σ(參考價 × 發行股數) / 前一日加權指數
參考價 = 收盤價 − 漲跌價差（除權息日已由證交所調整）。

輸出 data/contribution.json 供前端使用：
  - 盤後：直接顯示最新交易日的結果
  - 盤中：前端以即時報價 × shares / divisor_next 計算（divisor_next 以最新收盤市值推得）
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

TOP_N = 100


def _latest_twse(data: Path) -> tuple[str, pd.DataFrame, pd.DataFrame | None]:
    files = sorted((data / "stocks" / "twse").glob("*.csv"))
    if not files:
        raise FileNotFoundError("no twse data")
    df = pd.concat([pd.read_csv(p, dtype={"code": str}) for p in files[-2:]], ignore_index=True)
    dates = sorted(df["date"].unique())
    last = dates[-1]
    prev = df[df["date"] == dates[-2]] if len(dates) > 1 else None
    return last, df[df["date"] == last].copy(), prev


def build_contrib(data: Path) -> dict | None:
    shares_csv = data / "shares_twse.csv"
    if not shares_csv.exists():
        print("contribution: 尚無股本資料，略過")
        return None
    shares = pd.read_csv(shares_csv, dtype={"code": str}).set_index("code")["shares"]
    date, cur, prev = _latest_twse(data)

    tx = pd.read_csv(data / "taiex.csv").set_index("date")
    if date not in tx.index:
        print(f"contribution: 指數缺 {date}，略過")
        return None
    i = tx.index.get_loc(date)
    idx_close = float(tx["close"].iloc[i])
    idx_prev = float(tx["close"].iloc[i - 1]) if i > 0 else idx_close

    cur = cur.dropna(subset=["close"])
    cur["shares"] = cur["code"].map(shares)
    cur = cur.dropna(subset=["shares"])
    # 漲跌價差：優先用證交所公布值；舊資料沒有時以收盤價相減
    if "change" not in cur.columns:
        cur["change"] = None
    if prev is not None:
        pc = prev.set_index("code")["close"]
        fallback = cur["close"] - cur["code"].map(pc)
        cur["change"] = cur["change"].astype(float).fillna(fallback)
    cur["change"] = cur["change"].astype(float).fillna(0.0)

    cur["ref"] = cur["close"] - cur["change"]
    divisor = float((cur["ref"] * cur["shares"]).sum() / idx_prev)
    cur["pts"] = cur["change"] * cur["shares"] / divisor
    cur["mcap"] = cur["close"] * cur["shares"]
    divisor_next = float(cur["mcap"].sum() / idx_close)

    top = cur.sort_values("mcap", ascending=False).head(TOP_N)
    sum_all = float(cur["pts"].sum())
    sum_top = float(top["pts"].sum())
    out = {
        "date": date,
        "index_prev": round(idx_prev, 2),
        "index_close": round(idx_close, 2),
        "index_chg": round(idx_close - idx_prev, 2),
        "sum_all": round(sum_all, 2),
        "sum_top": round(sum_top, 2),
        "divisor_next": divisor_next,
        "items": [
            {
                "c": r.code, "n": r.name, "s": int(r.shares),
                "ref": round(float(r.ref), 4), "p": float(r.close),
                "chg": round(float(r.change), 4), "pts": round(float(r.pts), 3),
            }
            for r in top.itertuples()
        ],
    }
    print(f"contribution {date}: 全體 {sum_all:+.2f} / 實際 {idx_close - idx_prev:+.2f} / 前{TOP_N}大 {sum_top:+.2f}")
    return out


def write(data: Path, site: Path):
    try:
        out = build_contrib(data)
    except Exception as e:  # noqa: BLE001
        print(f"contribution 失敗: {e}")
        return
    if out is None:
        return
    (site / "data").mkdir(parents=True, exist_ok=True)
    (site / "data" / "contribution.json").write_text(
        json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
