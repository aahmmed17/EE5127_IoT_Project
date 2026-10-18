import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent   # project root (one level above scripts/)
RAW = BASE / "data" / "raw"
OUT = BASE / "data" / "processed"
OUT.mkdir(parents=True, exist_ok=True)

files = {"train": RAW / "datatraining.txt",
         "test1": RAW / "datatest.txt",
         "test2": RAW / "datatest2.txt"}

#read in the data and sort by date
dfs = {}
for name, path in files.items():
    df = pd.read_csv(path, index_col=0, parse_dates=["date"])
    df = df.sort_values("date").reset_index(drop=True)
    dfs[name] = df
    print(name, df.shape, df["date"].min(), "->", df["date"].max())
    print(df["Occupancy"].value_counts(normalize=True).round(3).to_dict())

#analyze the time intervals between data points
for name, df in dfs.items():
    dt = df["date"].diff().dt.total_seconds().dropna()
    print(f"\n{name}: median {dt.median():.0f} s, mean {dt.mean():.1f} s")
    print(dt.value_counts().head(5).to_dict())
    print("gaps > 90 s:", (dt > 90).sum(), "| duplicates (0 s):", (dt == 0).sum())
    print("longest gap:", dt.max(), "s")

#displaying candidate windows for inspection
def candidate_windows(df, length=90, min_transitions=2):
    occ = df["Occupancy"].to_numpy()
    out = []
    for start in range(0, len(df) - length, 10):
        w = occ[start:start + length]
        transitions = int((np.diff(w) != 0).sum())
        frac = w.mean()
        if transitions >= min_transitions and 0.2 <= frac <= 0.8:
            out.append((start, transitions, round(frac, 2),
                        str(df["date"].iloc[start])))
    return out

cands = candidate_windows(dfs["test2"])
print(len(cands), "candidates")
for c in cands[:15]:
    print(c)



df = dfs["test2"]
length = 90
picks = [1020, 1280, 2490]          # shortlisted start rows
#plot for each candidate window
fig, axes = plt.subplots(len(picks), 1, figsize=(10, 3.2 * len(picks)), sharex=False)
for ax, s in zip(axes, picks):
    w = df.iloc[s:s + length]
    dt = w["date"].diff().dt.total_seconds().dropna()
    chg = w.index[w["Occupancy"].diff().fillna(0) != 0]
    print(f"start {s}: {w['date'].iloc[0]} -> {w['date'].iloc[-1]}")
    print(f"  interval min/max: {dt.min():.0f}/{dt.max():.0f} s")
    print("  label changes:", [(str(df.loc[i, 'date'].time()), int(df.loc[i, 'Occupancy'])) for i in chg])

    for col in ["Light", "CO2", "Temperature"]:
        x = w[col]
        ax.plot(w["date"], (x - x.min()) / (x.max() - x.min() + 1e-9), label=col)
    ax.step(w["date"], w["Occupancy"], where="post", color="k", lw=2, label="Occupancy")
    ax.set_title(f"start row {s}")
    ax.legend(loc="upper left", ncol=4, fontsize=8)
plt.tight_layout()
plt.show()


start = 1020                      # replace with your final choice
block = df.iloc[start:start + length].copy()
block.to_csv("data/heldout_test_block.csv", index=False)
print(block["date"].min(), "->", block["date"].max())
print(block["Occupancy"].value_counts().to_dict())


OUT = BASE / "data"
OUT.mkdir(exist_ok=True)

# ---- 1. Save the held-out block (set A) ----
start = 1020          # <- replace with the start row from the previous script
length = 90
block = dfs["test2"].iloc[start:start + length].copy().reset_index(drop=True)
block.to_csv(OUT / "heldout_test_block.csv", index=False)

# ---- 2. Integer export for the node ----
def to_int_frame(df):
    return pd.DataFrame({
        "t": (df["Temperature"] * 100).round().astype(int),   # degC x100
        "h": (df["Humidity"] * 100).round().astype(int),      # %RH x100
        "l": df["Light"].round().astype(int),                 # lux
        "c": df["CO2"].round().astype(int),                   # ppm
    })

def export_set(df, name):
    ints = to_int_frame(df)
    for col in ints.columns:
        assert ints[col].between(-32768, 32767).all(), f"{name}: {col} overflows int16"
    # file the node reads: no header, 4 integers per row
    ints.to_csv(OUT / f"node_{name}.csv", index=False, header=False)
    # ground truth kept on the laptop for link verification (Step 5)
    truth = ints.copy()
    truth.insert(0, "seq", range(len(ints)))
    truth["date"] = df["date"].values
    truth["Occupancy"] = df["Occupancy"].values
    truth.to_csv(OUT / f"truth_{name}.csv", index=False)
    print(name, len(ints), "rows | max per column:", ints.max().to_dict(),
          "| min:", ints.min().to_dict())

export_set(block, "setA")

# ---- 3. Longer set for stress tests (set B) ----
# test1 is only used for validation, so it does not touch your held-out data
export_set(dfs["test1"], "setB")