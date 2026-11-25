#!/usr/bin/env python
"""verify_report.py: what the filled-in verification log says.

    ../apex-canopy/df-venv/bin/python verify_report.py [--log ../out_verify/verify_log.csv] [--out ../out_verify]

Reads verify_log.csv (id, set, acres, first_quarter, reviewer, verdict, share_of_outline_cleared, notes), items.csv and, if it has
entries, verify_log_large_optional.csv. Writes verify_report.txt and verify_report_groups.csv into --out.
The release set and the sample are reported separately: they are different populations.

Only id, set, reviewer, verdict, share_of_outline_cleared and notes are taken from the log. Acres, quarter, year, size and stratum
come from items.csv, so a cell changed by accident in a spreadsheet cannot move a result; any difference is listed.

Verdicts: cleared / partly / not cleared / can't tell. Blank = not yet reviewed.
  share confirmed          rows marked "cleared" over rows with a verdict other than "can't tell". "Cleared or partly" is given beside it,
                           and a floor that counts every "can't tell" as not confirmed.
  acres-weighted share     sum of acres x share of the outline cleared, over sum of acres. The share is the reviewer's
                           share_of_outline_cleared where given; else 1 for "cleared" and 0 for "not cleared". A "partly" row with no
                           share is not guessed: the result is given as a range, with those rows at 0 and at 1.
  shares as typed          a value with a % sign is a percent. Without one, the whole column is read one way: if any value is above 1
                           they are all percents, otherwise all fractions (so 1 means all of it). The report says which was used.
  release set              every release clearing is in it, so each reviewed row counts once.
  sample set               each row stands for the clearings of its stratum (year x size) in the 2017-2026 detection: weight =
                           clearings in the stratum / rows with a usable verdict in it. If a stratum has none, the overall and by-year
                           figures share its clearings among the other rows of the same year; the by-size table does not borrow across
                           sizes and names what is missing.
  optional large set       verify_log_large_optional.csv lists the clearings over 10 acres that the random draw did not pick. Where every
                           one of a stratum's rows there has a verdict, that stratum becomes a full count (weight 1) and the rows join
                           the sample's figures. A stratum only partly filled in is left on its random rows alone.
  95% interval             Wilson score interval on the weighted share with Kish's effective sample size, (sum w)^2 / sum w^2
                           (for the acres-weighted share the weights are w x acres). Approximate. For the count share it runs wide.
                           For the acres-weighted share it can run NARROW when a few large clearings carry most of the acres and the
                           sample holds one row from each of their strata: a simulation on this frame put its real coverage near 80%
                           when the failures sat in the largest clearings. Filling in the optional large set removes that weakness.
                           A bootstrap interval (rows resampled within year, 10,000 times, fixed seed) is printed as a cross-check; it
                           collapses to a point when every row agrees.
"""
import argparse, os, re
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument("--log", default=os.path.join(HERE, "..", "out_verify", "verify_log.csv"))
ap.add_argument("--large", default="", help="the optional large-clearing log; default: verify_log_large_optional.csv beside --log")
ap.add_argument("--out", default=os.path.join(HERE, "..", "out_verify"))
ap.add_argument("--items", default=os.path.join(HERE, "..", "out_verify", "items.csv"))
args = ap.parse_args()
VERDICTS = ["cleared", "partly", "not cleared", "can't tell"]
BOOT, BOOT_SEED = 10000, 20261124
SIZE_ORDER = ["under 3 ac", "3 to 10 ac", "over 10 ac"]
LOG_COLS = ["id", "set", "acres", "first_quarter", "reviewer", "verdict", "share_of_outline_cleared", "notes"]
Z = 1.959964
S = []
say = S.append
notes = []


def norm_verdict(v):
    v = re.sub(r"\s+", " ", str(v).strip().lower().replace("’", "'").replace("`", "'"))
    return {"cant tell": "can't tell", "can not tell": "can't tell", "cannot tell": "can't tell", "not_cleared": "not cleared", "notcleared": "not cleared", "partial": "partly", "partially": "partly"}.get(v, v)


def wilson(p, n):
    if n <= 0 or np.isnan(p):
        return np.nan, np.nan
    d = 1 + Z * Z / n
    c = (p + Z * Z / (2 * n)) / d
    h = Z * np.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / d
    return max(c - h, 0.0), min(c + h, 1.0)


def wmean(y, w):
    return float(np.sum(w * y) / np.sum(w)) if np.sum(w) > 0 else np.nan


def kish(w):
    return float(np.sum(w) ** 2 / np.sum(w * w)) if np.sum(w) > 0 else 0.0


def boot(d, cols, w):
    """Percentile interval of the weighted means of cols, rows resampled within year."""
    rng = np.random.default_rng(BOOT_SEED)
    Y, yr = d[cols].values.astype(float), d.year.values
    num, den = np.zeros((BOOT, len(cols))), np.zeros(BOOT)
    for y in np.unique(yr):
        ix = np.where(yr == y)[0]
        pick = ix[rng.integers(0, len(ix), (BOOT, len(ix)))]
        num += (w[pick][:, :, None] * Y[pick]).sum(1); den += w[pick].sum(1)
    return np.nanpercentile(num / den[:, None], [2.5, 97.5], axis=0).T


def estimate(d, wcol="w", with_boot=False):
    """d: rows with a verdict other than can't tell. Returns the figures as a dict."""
    if not len(d):
        return dict(decided=0)
    w = d[wcol].values.astype(float); wa = w * d.acres.values
    p, p2 = wmean(d.is_cleared.values, w), wmean(d.is_any.values, w)
    lo, hi = wmean(d.s_lo.values, wa), wmean(d.s_hi.values, wa)
    n1, n2 = kish(w), kish(wa)
    r = dict(decided=len(d), share_confirmed=p, ci=wilson(p, n1), share_cleared_or_partly=p2, ci_any=wilson(p2, n1), acres_share_lo=lo, acres_share_hi=hi, ci_acres=(wilson(lo, n2)[0], wilson(hi, n2)[1]),
             n_eff=n1, n_eff_acres=n2, top_row=d.id.values[np.argmax(wa)], top_row_share=float(wa.max() / wa.sum()))
    if with_boot and len(d) >= 5:
        b, ba = boot(d, ["is_cleared", "is_any"], w), boot(d, ["s_lo", "s_hi"], wa)
        r.update(boot=tuple(b[0]), boot_any=tuple(b[1]), boot_acres=(ba[0][0], ba[1][1]))
    return r


pc = lambda x: "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{100 * x:.1f}%"
rng_ = lambda t: f"{pc(t[0])} to {pc(t[1])}"
span = lambda lo, hi: pc(lo) if abs(hi - lo) < 5e-4 else f"{pc(lo)} to {pc(hi)}"


def sample_weights(d, frame):
    """Clearings in the stratum per usable row (w_raw); and the same with an empty stratum's clearings shared within its year (w)."""
    d = d.copy()
    d["w_raw"] = d.stratum_N / d.groupby("stratum").id.transform("size")
    Ny = frame.groupby("year").stratum_N.sum()
    cov = d.drop_duplicates("stratum").groupby("year").stratum_N.sum()
    d["w"] = d.w_raw * d.year.map(Ny / cov)
    return d, Ny, cov


def read_log(fn):
    L = pd.read_csv(fn, dtype=str).fillna("")
    missing = [c for c in LOG_COLS if c not in L.columns]
    if missing:
        raise SystemExit(f"{fn} is missing columns: {missing}")
    for c in LOG_COLS:
        L[c] = L[c].str.strip()
    L = L[L.id != ""].copy()                                          # trailing empty spreadsheet rows
    L["set"] = L["set"].str.lower()
    dup = L[L.duplicated(["id", "set"], keep=False)]
    if len(dup):
        raise SystemExit(f"{fn}: these ids appear more than once, fix the log first: {', '.join(sorted(set(dup.id)))}")
    return L


I = pd.read_csv(args.items, dtype=str).fillna("")
I["acres"] = I.acres.astype(float); I["year"] = I.year.astype(int)
I["stratum_N"] = pd.to_numeric(I.stratum_N, errors="coerce")
LOG = read_log(args.log)
large_fn = args.large or os.path.join(os.path.dirname(os.path.abspath(args.log)), "verify_log_large_optional.csv")
if os.path.exists(large_fn):
    LG = read_log(large_fn)
    if LG.verdict.ne("").any():
        LOG = pd.concat([LOG, LG], ignore_index=True)
keys = set(zip(I.id, I["set"]))
stray = LOG[[k not in keys for k in zip(LOG.id, LOG["set"])]]
if len(stray):
    notes.append("Rows not in items.csv (left out): " + ", ".join(f"{r.id} [{r.set}]" for r in stray.itertuples()))
L = I.merge(LOG[["id", "set", "reviewer", "verdict", "share_of_outline_cleared", "notes"]].assign(in_log=True), on=["id", "set"], how="left").fillna({"in_log": False, "reviewer": "", "verdict": "", "share_of_outline_cleared": "", "notes": ""})
chk = LOG.merge(I[["id", "set", "acres", "first_quarter"]], on=["id", "set"], suffixes=("_log", ""))
diff = chk[(pd.to_numeric(chk.acres_log, errors="coerce").round(2) != chk.acres.round(2)) | (chk.first_quarter_log != chk.first_quarter)]
if len(diff):
    notes.append("Acres or quarter in the log differ from items.csv (items.csv is used): " + "; ".join(f"{r.id} log {r.acres_log} ac {r.first_quarter_log}, items {r.acres:g} ac {r.first_quarter}" for r in diff.itertuples()))

L["in_log"] = L.in_log.astype(bool)
L["v"] = L.verdict.map(norm_verdict)
bad_v = L[(L.v != "") & ~L.v.isin(VERDICTS)]
if len(bad_v):
    notes.append("Verdicts not recognised (counted as not reviewed): " + "; ".join(f"{r.id} '{r.verdict}'" for r in bad_v.itertuples()))
    L.loc[bad_v.index, "v"] = ""
# shares: a % sign means percent; otherwise the whole column is read one way
raw = L.share_of_outline_cleared.str.replace(" ", "")
has_pct = raw.str.endswith("%")
num = pd.to_numeric(raw.str.rstrip("%"), errors="coerce")
bad_s = L[(raw != "") & num.isna()]
plain = num[(raw != "") & ~has_pct]
as_percent = bool((plain > 1).any())
share = np.where(has_pct | as_percent, num / 100, num)
share = pd.Series(share, index=L.index)
out_of_range = L[(share < 0) | (share > 1)]
if len(bad_s) or len(out_of_range):
    notes.append("Shares not readable or outside 0 to 100% (ignored): " + "; ".join(f"{r.id} '{r.share_of_outline_cleared}'" for r in pd.concat([bad_s, out_of_range]).itertuples()))
    share[(share < 0) | (share > 1)] = np.nan
L["share"] = share
mixed = L[(raw != "") & ~has_pct & (num > 0) & (num <= 1)] if as_percent else L.iloc[0:0]
if len(mixed):
    notes.append("CHECK: the share column mixes values above 1 with values of 1 or less and no % sign. All were read as percents, so these were read as 1% or less: " + "; ".join(f"{r.id} '{r.share_of_outline_cleared}'" for r in mixed.itertuples()))
if plain.notna().any():
    notes.append("Shares typed without a % sign were read as " + ("percents (at least one is above 1)." if as_percent else "fractions of 1 (none is above 1), so 1 means the whole outline."))
orphan = L[(L.v == "") & L.share.notna()]
if len(orphan):
    notes.append("A share was entered with no verdict (row counted as not reviewed): " + ", ".join(orphan.id))
odd = L[((L.v == "cleared") & (L.share < 0.5)) | ((L.v == "not cleared") & (L.share > 0.5)) | ((L.v == "partly") & L.share.isin([0.0, 1.0]))]
if len(odd):
    notes.append("Verdict and share look inconsistent (kept as entered; check them): " + "; ".join(f"{r.id} {r.v}, share {pc(r.share)}" for r in odd.itertuples()))
L["is_cleared"] = (L.v == "cleared").astype(float); L["is_any"] = L.v.isin(["cleared", "partly"]).astype(float)
L["s_lo"] = np.where(L.share.notna(), L.share, np.where(L.v == "cleared", 1.0, 0.0))
L["s_hi"] = np.where(L.share.notna(), L.share, np.where(L.v.isin(["cleared", "partly"]), 1.0, 0.0))

say("VERIFICATION REPORT")
say(f"Log: {os.path.abspath(args.log)}")
for p in notes:
    say("NOTE: " + p)
G = []
FRAME = I[I.set.isin(["sample", "large"])].drop_duplicates("stratum")[["stratum", "year", "size_class", "stratum_N"]]
for sname, title in (("release", "RELEASE SET: all 238 clearings of the public release"), ("sample", "SAMPLE SET: 100 drawn at random from the 497 clearings of the 2017-2026 detection, by year and size")):
    A = L[L.set == sname].copy()
    extra_note = ""
    if sname == "sample":
        LGE = L[L.set == "large"]
        full = [s for s, g in LGE.groupby("stratum") if (g.v != "").all()]
        part = [s for s, g in LGE.groupby("stratum") if (g.v != "").any() and not (g.v != "").all()]
        if full:
            A = pd.concat([A, LGE[LGE.stratum.isin(full)]], ignore_index=True)
            extra_note = f"Optional large set: {int(LGE.stratum.isin(full).sum())} more clearings over 10 acres added; fully counted strata: {', '.join(full)}."
        if part:
            extra_note += f" Large-set strata only partly filled in, so not used: {', '.join(part)}."
    R = A[A.v != ""]
    Dd = R[R.v != "can't tell"].copy()
    say(f"\n{'=' * 110}\n{title}")
    absent = A[~A.in_log]
    say(f"Rows {len(A)}; reviewed {len(R)}; not yet reviewed {len(A) - len(R)}. Reviewers: {', '.join(sorted(set(R.reviewer) - {''})) or 'none entered'}.")
    if len(absent):
        say(f"NOTE: {len(absent)} row(s) of this set are missing from the log altogether: {', '.join(absent.id[:40])}{' ...' if len(absent) > 40 else ''}")
    if extra_note:
        say(extra_note.strip())
    if not len(R):
        say("Nothing reviewed yet.")
        continue
    say("Verdicts: " + "; ".join(f"{v} {int((R.v == v).sum())} ({R.acres[R.v == v].sum():,.1f} ac)" for v in VERDICTS))
    np_ = int(((Dd.v == "partly") & Dd.share.isna()).sum())
    if np_:
        say(f"{np_} 'partly' row(s) have no share entered: acres-weighted figures are given as a range.")
    if not len(Dd):
        say("No row has a verdict other than can't tell.")
        continue
    stands_for = None
    if sname == "sample":
        Dd, Ny, cov = sample_weights(Dd, FRAME)
        empty_years = sorted(set(Ny.index) - set(cov.index))
        empty_strata = sorted(set(FRAME.stratum) - set(Dd.stratum))
        if empty_strata:
            say("Strata with no usable verdict yet: " + "; ".join(empty_strata) + ". In the overall and by-year figures their clearings are carried by other rows of the same year"
                + (f"; years with none at all ({', '.join(map(str, empty_years))}) are outside every figure." if empty_years else "."))
        stands_for = float(Dd.w.sum())
        say(f"The rows with a usable verdict stand for {stands_for:,.0f} of the {Ny.sum():,.0f} clearings in the 2017-2026 detection.")
    else:
        Dd["w"] = 1.0; Dd["w_raw"] = 1.0
        if len(R) < len(A):
            say("Not every clearing has been reviewed, and the reviewed ones were not picked at random: read these as 'of those reviewed so far'.")
    e = estimate(Dd, with_boot=True)
    ct = R[R.v == "can't tell"]
    say(f"\nShare confirmed (cleared):            {pc(e['share_confirmed'])}   95% interval {rng_(e['ci'])}" + (f"   [bootstrap {rng_(e['boot'])}]" if "boot" in e else ""))
    say(f"Share cleared or partly:              {pc(e['share_cleared_or_partly'])}   95% interval {rng_(e['ci_any'])}" + (f"   [bootstrap {rng_(e['boot_any'])}]" if "boot_any" in e else ""))
    say(f"Acres-weighted share confirmed:       {span(e['acres_share_lo'], e['acres_share_hi'])}   95% interval {rng_(e['ci_acres'])}" + (f"   [bootstrap {rng_(e['boot_acres'])}]" if "boot_acres" in e else ""))
    say(f"Based on {e['decided']} rows with a verdict other than can't tell ({len(ct)} can't tell left out); effective sample size {e['n_eff']:.0f} (by count), {e['n_eff_acres']:.0f} (by acres).")
    if len(ct):
        both = pd.concat([Dd, ct.assign(is_cleared=0.0, is_any=0.0, s_lo=0.0, s_hi=0.0)])
        both = sample_weights(both, FRAME)[0] if sname == "sample" else both.assign(w=1.0)
        f = estimate(both)
        say(f"Floor, counting every can't tell as not confirmed: {pc(f['share_confirmed'])} by count, {pc(f['acres_share_lo'])} by acres.")
    say(f"The largest single row, {e['top_row']}, carries {pc(e['top_row_share'])} of the weighted acres" + ("; with so much resting on a few large clearings the acres-weighted interval can be too narrow (see the top of this script)." if e["top_row_share"] > 0.05 else "."))
    if sname == "release" and len(R) == len(A) and not len(absent) and len(A) == int((I.set == "release").sum()):
        say("Every release clearing was reviewed, so the shares are a full count; the interval only shows how much a share of this size could move by chance.")
    if stands_for:
        say(f"Applied to the clearings these rows stand for: about {e['share_confirmed'] * stands_for:,.0f} of {stands_for:,.0f} confirmed as cleared.")
    for by, order in (("year", sorted(A.year.unique())), ("size_class", SIZE_ORDER)):
        wcol = "w_raw" if (by == "size_class" and sname == "sample") else "w"
        say(f"\nBy {'year of first detection' if by == 'year' else 'size class'}:")
        say(f"  {'group':12s} {'rows':>5s} {'reviewed':>8s} {'cleared':>8s} {'partly':>7s} {'not':>5s} {'cant tell':>9s}   {'confirmed':>9s}  {'95% interval':>18s}   {'acres-weighted':>18s}  {'95% interval':>18s}")
        for k in order:
            a, r, d = A[A[by] == k], R[R[by] == k], Dd[Dd[by] == k]
            g = estimate(d, wcol)
            row = dict(set=sname, by=by, group=k, rows=len(a), reviewed=len(r), cleared=int((r.v == "cleared").sum()), partly=int((r.v == "partly").sum()), not_cleared=int((r.v == "not cleared").sum()),
                       cant_tell=int((r.v == "can't tell").sum()), acres_reviewed=round(float(r.acres.sum()), 1), strata_without_a_usable_row="")
            gap = ""
            if sname == "sample":
                miss = sorted(set(FRAME.stratum[FRAME[by] == k]) - set(d.stratum))
                row["strata_without_a_usable_row"] = "; ".join(miss)
                gap = f"   no usable row for: {', '.join(m.split(' | ')[0 if by == 'size_class' else 1] for m in miss)}" if miss and by == "size_class" else ""
            if g["decided"]:
                row.update(share_confirmed=round(g["share_confirmed"], 4), ci_low=round(g["ci"][0], 4), ci_high=round(g["ci"][1], 4), share_cleared_or_partly=round(g["share_cleared_or_partly"], 4),
                           acres_weighted_low=round(g["acres_share_lo"], 4), acres_weighted_high=round(g["acres_share_hi"], 4), acres_ci_low=round(g["ci_acres"][0], 4), acres_ci_high=round(g["ci_acres"][1], 4))
                say(f"  {str(k):12s} {len(a):5d} {len(r):8d} {row['cleared']:8d} {row['partly']:7d} {row['not_cleared']:5d} {row['cant_tell']:9d}   {pc(g['share_confirmed']):>9s}  {rng_(g['ci']):>18s}   "
                    f"{span(g['acres_share_lo'], g['acres_share_hi']):>18s}  {rng_(g['ci_acres']):>18s}{gap}")
            else:
                say(f"  {str(k):12s} {len(a):5d} {len(r):8d} {row['cleared']:8d} {row['partly']:7d} {row['not_cleared']:5d} {row['cant_tell']:9d}   {'n/a':>9s}{gap}")
            G.append(row)
    nc = R[R.v.isin(["not cleared", "can't tell"])]
    if len(nc):
        say("\nRows marked not cleared or can't tell: " + "; ".join(f"{r.id} ({r.acres:g} ac, {r.first_quarter}, {r.v})" for r in nc.sort_values("acres", ascending=False).itertuples()))
say("\nSmall groups have wide intervals: a year with nine rows cannot settle a share to better than about 30 points either way.")
os.makedirs(args.out, exist_ok=True)
open(os.path.join(args.out, "verify_report.txt"), "w").write("\n".join(S) + "\n")
pd.DataFrame(G).to_csv(os.path.join(args.out, "verify_report_groups.csv"), index=False)
print("\n".join(S))
