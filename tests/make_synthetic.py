"""
Synthetic files in the Fannie Mae layout (108 columns, "|", no header) to test the code.
This is NOT real data, only simulated scenarios: the 2008-2010 crisis, prepayments,
losses (ZB 03/09), repurchases (ZB 06), COVID forbearance with payment deferral,
ARM and 15-year loans, and missing data.

    python tests/make_synthetic.py <raw_folder>
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from columns import COLS_108  # noqa: E402

IDX = {c: i for i, c in enumerate(COLS_108)}
END = (2023, 6)
STATES = ["CA", "FL", "TX", "NY", "AZ", "NV", "OH", "IL"]


def months(y, m):
    while (y, m) <= END:
        yield y, m
        m += 1
        if m == 13:
            y, m = y + 1, 1


def stress(y, m):
    if (2008, 1) <= (y, m) <= (2010, 12):
        return 6.0
    if (2007, 1) <= (y, m) <= (2011, 12):
        return 2.5
    return 1.0


def loan_rows(rng, loan_id, y0, m0):
    r = [""] * len(COLS_108)
    term = 360 if rng.random() > 0.08 else 180
    prod = "FRM" if rng.random() > 0.04 else "ARM"
    fico = int(rng.gauss(730, 50)) if rng.random() > 0.02 else None
    ltv = rng.choice([60, 70, 75, 80, 80, 90, 95, 97])
    upb = round(rng.uniform(80, 450) * 1000, -3)
    state = rng.choice(STATES) if rng.random() > 0.01 else ""
    static = dict(
        LOAN_ID=str(loan_id), CHANNEL=rng.choice("RCB"), SELLER="Synthetic Bank",
        ORIG_RATE=f"{rng.uniform(3, 7.5):.3f}", ORIG_UPB=f"{upb:.0f}", ORIG_TERM=str(term),
        ORIG_DATE=f"{m0:02d}{y0}", OLTV=str(ltv), OCLTV=str(ltv), NUM_BO=rng.choice("12"),
        DTI=str(rng.randint(15, 50)) if rng.random() > 0.03 else "",
        CSCORE_B="" if fico is None else str(min(fico, 850)),
        FIRST_FLAG=rng.choice("NY"), PURPOSE=rng.choice("PCR"), PROP=rng.choice(["SF", "PU", "CO"]),
        NO_UNITS="1", OCC_STAT=rng.choice("PPPSI"), STATE=state, MSA="00000", ZIP="900",
        PRODUCT=prod, HIGH_LOAN_TO_VALUE_HLTV_REFINANCE_OPTION_INDICATOR="Y" if rng.random() < 0.01 else "N",
    )
    for k, v in static.items():
        r[IDX[k]] = v

    risk = 0.0008 * (1 + max(0, 740 - (fico or 700)) / 40) * (1 + (ltv > 90))
    dlq, bal, age, rows, forb_left, mod = 0, upb, 0, [], 0, "N"
    if rng.random() < 0.002:
        dlq = 3                                            # in default from the start
    for y, m in months(y0, m0):
        age += 1
        row = r.copy()
        row[IDX["ACT_PERIOD"]] = f"{m:02d}{y}"
        row[IDX["LOAN_AGE"]] = str(age)
        row[IDX["CURRENT_UPB"]] = f"{bal:.2f}" if age > 6 else ""
        bal *= 0.998
        zb = ""
        # COVID: some loans enter forbearance, delinquency grows, then deferral
        if (y, m) == (2020, 4) and dlq == 0 and rng.random() < 0.07:
            forb_left = rng.randint(4, 15)
        if forb_left > 0:
            row[IDX["FORBEARANCE_INDICATOR"]] = "F"
            dlq += 1
            forb_left -= 1
            if forb_left == 0:
                if rng.random() < 0.85:
                    dlq, row[IDX["ADR_TYPE"]] = 0, "C"     # payment deferral: not a default
                # 15%: leaves forbearance still delinquent
        elif dlq > 0:
            p = rng.random()
            if p < 0.25:
                dlq = 0
            elif p < 0.85 or dlq >= 2:
                dlq += 1
            if dlq >= 4 and rng.random() < 0.05:
                mod, dlq = "Y", 0
        elif rng.random() < risk * stress(y, m):
            dlq = 1
        if mod == "Y":
            row[IDX["MOD_FLAG"]] = "Y"
        else:
            row[IDX["MOD_FLAG"]] = "N"
        row[IDX["DLQ_STATUS"]] = "XX" if rng.random() < 0.001 else f"{dlq:02d}"

        if dlq >= 8 and forb_left == 0 and rng.random() < 0.15:
            zb = rng.choice(["03", "09", "09", "02", "15"])
            if zb == "09":
                row[IDX["FORECLOSURE_DATE"]] = f"{m:02d}{y}"
        elif dlq == 0 and rng.random() < (0.012 if y in (2003, 2012, 2020, 2021) else 0.006):
            zb = "01"
        elif rng.random() < 0.0003:
            zb = "06"
        if zb:
            row[IDX["Zero_Bal_Code"]] = zb
            row[IDX["ZB_DTE"]] = f"{m:02d}{y}"
            rows.append(row)
            return rows
        rows.append(row)
    return rows


def main(out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(1)
    loan_id = 100000000000
    for q, (y, m), n in [("2001Q2", (2001, 5), 600), ("2005Q1", (2005, 2), 2500),
                         ("2007Q2", (2007, 5), 2500), ("2012Q3", (2012, 8), 1500),
                         ("2019Q1", (2019, 2), 2500), ("2021Q4", (2021, 11), 1500)]:
        with open(out / f"{q}.csv", "w", encoding="utf-8", newline="\n") as f:
            for _ in range(n):
                loan_id += rng.randint(1, 50)
                for row in loan_rows(rng, loan_id, y, m):
                    f.write("|".join(row) + "\n")
        print(q, "ok")


if __name__ == "__main__":
    main(sys.argv[1])
