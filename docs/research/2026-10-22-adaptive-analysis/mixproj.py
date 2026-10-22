"""Projected ₹ per audio minute on production's measured 14-day mix (62 calls, 284.4 min), from measured rates.
Mix and per-stage rates: one-pass session (one-pass-break-even-20261021, cost-decision-40-to-10-paise-20261022).
Brain 4.0 part: instructions measured 20,508 chars (~5.1k tokens); answer 1.5-2.5k output tokens (gold-v1 reads)."""
G_IN, G_OUT = 0.75, 3.75          # Gemini 3.8 Flash $/M, standard (production planning rates)
FX = 100
buckets = [  # (label, calls, mean minutes from C2 ₹ at 0.233/min, today's one-pass C4+C5 ₹/call)
    ("<1", 27, 0.12 / 0.233, None), ("1-3", 11, 0.39 / 0.233, 2.91), ("3-6", 7, 1.00 / 0.233, 3.32),
    ("6-10", 8, 1.85 / 0.233, 4.11), ("10-20", 6, 3.40 / 0.233, 4.86), ("20-40", 3, 5.51 / 0.233, 6.06)]
MIN = sum(n * m for _, n, m, _ in buckets)
an = [(n, m, t) for _, n, m, t in buckets if t is not None]          # short-call rule: <1 min gets no analysis
c4 = lambda m: (3579 * G_IN + 3379 * G_OUT + m * (649 * G_IN + 101 * G_OUT)) / 1e6 * FX   # one-pass C4, measured fit
c5 = lambda m, t: t - c4(m)
def b4_part(o):   # Brain 4.0 inside the one-pass read: its instructions + its answer
    return (5100 * G_IN + o * G_OUT) / 1e6 * FX
def b4_read(m, o):  # Brain 4.0 as a separate read: the same + the transcript again
    return b4_part(o) + m * 649 * G_IN / 1e6 * FX
C2_STD, C2_FLEX, C2_COMPACT_FLEX = 0.233, 0.1175, 0.1175 * 0.65
def per_min(total): return total / MIN
rows = []
for o in (1500, 2500):
    today = sum(n * t for n, m, t in an)
    shadow = sum(n * b4_read(m, o) for n, m, t in an)
    fold = sum(n * b4_part(o) for n, m, t in an)
    c5s = sum(n * c5(m, t) for n, m, t in an)
    s = {
        "S0 today: one-pass v1 + C5, Gemini standard": C2_STD + per_min(today),
        "S1 today + Brain 4.0 shadow read on every analysed call": C2_STD + per_min(today + shadow),
        "S2 Brain 4.0 folded into the one-pass read (v2), C5 kept": C2_STD + per_min(today + fold),
        "S3 v2, C5 on demand (Report = Brain 4.0), standard": C2_STD + per_min(today + fold - c5s),
        "S4 S3 on Flex": C2_FLEX + per_min(today + fold - c5s) / 2,
        "S5 v2 on Luna (C4 + Brain 4.0) Flex, C5 on demand": C2_FLEX + per_min(sum(n * (0.19 + 0.0042 * m + (5100 * 0.05 + o * 0.25) / 1e6 * FX) for n, m, t in an)),
        "S6 S5 + compact transcript": C2_COMPACT_FLEX + per_min(sum(n * (0.19 + 0.0042 * m + (5100 * 0.05 + o * 0.25) / 1e6 * FX) for n, m, t in an)),
    }
    rows.append((o, s, c5s / MIN))
print("mix minutes %.1f; analysed calls %d" % (MIN, sum(n for n, m, t in an)))
for k in rows[0][1]:
    print("%-62s ₹%.3f – ₹%.3f" % (k, rows[0][1][k], rows[1][1][k]))
print("C5 share of the mix: ₹%.3f/min; each 10%% of calls tapping 'Get full report' adds back ₹%.3f/min" % (rows[0][2], rows[0][2] / 10))
print("per call, separate read vs folded (std, 2k answer): 2 min ₹%.2f vs ₹%.2f; 15 min ₹%.2f vs ₹%.2f" % (b4_read(1.67, 2000), b4_part(2000), b4_read(14.6, 2000), b4_part(2000)))
