"""
Functions used in the notebooks. The notebooks show what we do and the results;
the details of the calculations are here.

Parts of this file:
    A. Data cleaning             notebook 1
    B. Default definition        notebook 2
    C. Test of the definition    notebook 3
    D. Model dataset             notebook 4
    E. Tables and charts         notebook 5
    F. First look at raw data    notebook 0
"""
import datetime as dt
import hashlib
from datetime import date

import matplotlib.pyplot as plt
import polars as pl

import config as C
from columns import LAYOUTS

BLUE = "#2a78d6"


# ===========================================================================
# A. DATA CLEANING
# ===========================================================================

def list_raw_files():
    """List of the quarterly files to process."""
    paths = sorted(C.RAW_DIR.glob("*.csv"))
    if C.FILES:
        paths = [p for p in paths if p.stem in C.FILES]
    if not paths:
        raise FileNotFoundError(f"No files in {C.RAW_DIR}")
    return paths


def read_raw(path):
    """Opens a raw file: no header, "|" separator, all fields as text."""
    with open(path, encoding="latin-1") as f:
        n_columns = f.readline().count("|") + 1
    if n_columns not in LAYOUTS:
        raise ValueError(f"{path.name}: {n_columns} columns. Update columns.py.")
    return pl.scan_csv(path, separator="|", has_header=False, new_columns=LAYOUTS[n_columns],
                       infer_schema=False, quote_char=None, encoding="utf8-lossy")


def in_sample(loan_id):
    """Is the loan in the sample? The same rule applies to every file."""
    digest = hashlib.md5(f"{C.SAMPLE_SEED}_{loan_id}".encode()).hexdigest()
    return int(digest[:8], 16) % 100 < C.SAMPLE_PCT


def mmyyyy_to_date(col):
    """Turns MMYYYY text into a date: the first day of the month."""
    text = pl.col(col)
    return pl.date(text.str.slice(2, 4).cast(pl.Int32, strict=False),
                   text.str.slice(0, 2).cast(pl.Int32, strict=False), 1).alias(col)


def load_cohort(path):
    """Reads the sampled loans of one file and sets the column types."""
    all_ids = read_raw(path).select("LOAN_ID").unique().collect()["LOAN_ID"].to_list()
    sampled = [loan_id for loan_id in all_ids if in_sample(loan_id)]

    df = (
        read_raw(path)
        .select(list(C.RAW_VARIABLES))
        .filter(pl.col("LOAN_ID").is_in(sampled))
        .with_columns(pl.all().str.strip_chars())
        .with_columns(pl.when(pl.all() == "").then(None).otherwise(pl.all()).name.keep())
        .with_columns(
            [pl.col(c).cast(pl.Float64, strict=False) for c in C.FLOAT_COLS]
            + [pl.col(c).cast(pl.Int32, strict=False) for c in C.INT_COLS]   # "XX" becomes missing
            + [mmyyyy_to_date(c) for c in C.DATE_COLS]
            + [pl.col("Zero_Bal_Code").str.zfill(2), pl.lit(path.stem).alias("cohort")]
        )
        .sort("LOAN_ID", "ACT_PERIOD")
        .collect()
    )
    # Fill origination fields within each loan
    df = df.with_columns(
        [pl.col(c).forward_fill().backward_fill().over("LOAN_ID") for c in C.ORIGINATION_COLS]
    )
    # Values outside the allowed ranges become missing
    for col, (low, high) in C.LIMITS.items():
        df = df.with_columns(
            pl.when(pl.col(col).is_between(low, high)).then(pl.col(col)).otherwise(None).alias(col)
        )
    return df, len(all_ids)


def filter_population(df, cohort, n_all):
    """Restricts the population and counts loans and rows after each step."""
    hltv = "HIGH_LOAN_TO_VALUE_HLTV_REFINANCE_OPTION_INDICATOR"
    loans = df.group_by("LOAN_ID").agg(
        pl.col(["ORIG_TERM", "PRODUCT", hltv] + C.CRITICAL_FIELDS).first(), rows=pl.len()
    )
    steps = [
        ("1. Sampled loans", pl.lit(True)),
        (f"2. Term of {C.KEEP_ORIG_TERM} months", pl.col("ORIG_TERM") == C.KEEP_ORIG_TERM),
        (f"3. Product {C.KEEP_PRODUCT}", pl.col("PRODUCT") == C.KEEP_PRODUCT),
        ("4. No relief refinance", (pl.col(hltv) != "Y").fill_null(True)),
        ("5. Key fields present", pl.all_horizontal(pl.col(C.CRITICAL_FIELDS).is_not_null())),
    ]
    waterfall = [{"cohort": cohort, "step": "0. All loans in the file", "loans": n_all, "rows": None}]
    for name, condition in steps:
        loans = loans.filter(condition)
        waterfall.append({"cohort": cohort, "step": name, "loans": loans.height,
                          "rows": int(loans["rows"].sum())})
    return df.filter(pl.col("LOAN_ID").is_in(loans["LOAN_ID"].implode())), waterfall


def check_panel(df, cohort):
    """Removes duplicate months and counts gaps in loan histories."""
    n_before = df.height
    df = df.unique(["LOAN_ID", "ACT_PERIOD"], keep="last").sort("LOAN_ID", "ACT_PERIOD")
    month = pl.col("ACT_PERIOD").dt.year() * 12 + pl.col("ACT_PERIOD").dt.month()
    step = month - month.shift(1).over("LOAN_ID")
    gaps = df.with_columns(missing=step - 1).filter(pl.col("missing") > 0)
    check = {"cohort": cohort, "loans": df["LOAN_ID"].n_unique(), "rows": df.height,
             "duplicates": n_before - df.height, "loans_with_gaps": gaps["LOAN_ID"].n_unique(),
             "missing_months": int(gaps["missing"].sum())}
    return df, check


# ===========================================================================
# B. DEFAULT DEFINITION
# ===========================================================================

def add_balance_and_payment(df):
    """Step 1: current balance and monthly payment."""
    r0 = pl.col("ORIG_RATE") / 1200
    n0 = pl.col("ORIG_TERM")
    k = pl.col("LOAN_AGE").fill_null(0).clip(0)
    scheduled = (
        pl.when(r0 > 0)
        .then(pl.col("ORIG_UPB") * ((1 + r0) ** n0 - (1 + r0) ** k) / ((1 + r0) ** n0 - 1))
        .otherwise(pl.col("ORIG_UPB") * (1 - k / n0))
    )
    # A balance that is empty or 0 is masked, so we use the repayment schedule
    masked = pl.col("CURRENT_UPB").is_null() | (pl.col("CURRENT_UPB") <= 0)
    df = df.with_columns(
        balance_masked=masked,
        balance=pl.when(masked).then(scheduled).otherwise(pl.col("CURRENT_UPB")),
    )
    r = pl.coalesce("CURR_RATE", "ORIG_RATE") / 1200
    n = pl.coalesce(pl.col("REM_MONTHS"), n0 - pl.col("LOAN_AGE"))
    # In the termination month n is empty, so the payment is empty too
    return df.with_columns(
        payment=pl.when(n <= 0).then(pl.col("balance"))
        .when(r == 0).then(pl.col("balance") / n)
        .otherwise(pl.col("balance") * r / (1 - (1 + r) ** (-n)))
    )


def add_thresholds(df):
    """Step 2: overdue amount and materiality thresholds."""
    df = df.with_columns(
        # An unknown status is replaced with the last known one
        n_overdue_payments=pl.col("DLQ_STATUS").forward_fill().over("LOAN_ID").fill_null(0)
    )
    df = df.with_columns(overdue_usd=pl.col("n_overdue_payments") * pl.col("payment"))
    df = df.with_columns(
        overdue_eur=pl.col("overdue_usd") / C.USD_PER_EUR,
        overdue_share=pl.col("overdue_usd") / pl.col("balance"),
    )
    return df.with_columns(
        above_abs_threshold=pl.col("overdue_eur") > C.THRESHOLD_ABS_EUR,
        above_rel_threshold=pl.col("overdue_share") > C.THRESHOLD_REL,
    ).with_columns(above_threshold=pl.col("above_abs_threshold") & pl.col("above_rel_threshold"))


def add_counter(df):
    """Step 3: counter of consecutive months above the thresholds."""
    in_covid = pl.col("ACT_PERIOD").is_between(pl.lit(C.COVID_START).str.to_date(),
                                               pl.lit(C.COVID_END).str.to_date())
    month = pl.col("ACT_PERIOD").dt.year() * 12 + pl.col("ACT_PERIOD").dt.month()
    df = df.with_columns(
        covid_freeze=((pl.col("FORBEARANCE_INDICATOR") == C.FORBEARANCE_CODE) & in_covid).fill_null(False),
        gap=(month - month.shift(1).over("LOAN_ID")).fill_null(1) > 1,
    )
    # A new series starts in a month below the threshold or after a gap
    df = df.with_columns(series=(~pl.col("above_threshold") | pl.col("gap")).cum_sum().over("LOAN_ID"))
    # Within a series, count months above the thresholds, except COVID forbearance months
    counted = pl.col("above_threshold") & ~pl.col("covid_freeze")
    return df.with_columns(
        month_counter=counted.cast(pl.Int32).cum_sum().over("LOAN_ID", "series")
    ).drop("series")


def add_first_default(df):
    """Step 4: date and reason of the first default."""
    month = pl.col("ACT_PERIOD")
    is_dpd = ((pl.col("month_counter") >= C.DPD_MONTHS)
              & (pl.col("n_overdue_payments") >= C.DPD_MIN_STATUS)
              & ~pl.col("covid_freeze"))
    events = df.group_by("LOAN_ID").agg(
        d_dpd=month.filter(is_dpd).min(),
        d_loss=month.filter(pl.col("Zero_Bal_Code").is_in(C.ZB_LOSS).fill_null(False)).min(),
        d_mod=month.filter((pl.col("MOD_FLAG") == "Y").fill_null(False)).min(),
    ).with_columns(first_default_date=pl.min_horizontal("d_dpd", "d_loss", "d_mod"))
    first = pl.col("first_default_date")
    events = events.with_columns(
        default_reason=pl.when(first.is_null()).then(None)
        .when(first == pl.col("d_dpd")).then(pl.lit("DPD"))
        .when(first == pl.col("d_loss")).then(pl.lit("UTP_loss_sale"))
        .otherwise(pl.lit("UTP_modification"))
    ).select("LOAN_ID", "first_default_date", "default_reason")
    return df.join(events, on="LOAN_ID", how="left").with_columns(
        default_flag=(month == first).fill_null(False),
        after_default=(month > first).fill_null(False),
    )


def build_default(df):
    """The whole default definition: four steps in order."""
    df = df.sort("LOAN_ID", "ACT_PERIOD")
    return add_first_default(add_counter(add_thresholds(add_balance_and_payment(df))))


def example_loan(status, balance=200_000, rate=6, remaining=300, start=dt.date(2019, 1, 1),
                 mod=None, zb=None, forbearance=None, current_upb=None, age=24):
    """Artificial loan for the examples: one row per month."""
    n = len(status)
    months = pl.date_range(start, start + dt.timedelta(days=31 * n), "1mo", eager=True)[:n]
    return pl.DataFrame({
        "LOAN_ID": ["X"] * n, "ACT_PERIOD": months,
        "ORIG_UPB": [float(balance)] * n, "ORIG_RATE": [float(rate)] * n, "ORIG_TERM": [360] * n,
        "LOAN_AGE": [age + i for i in range(n)], "REM_MONTHS": [remaining - i for i in range(n)],
        "CURRENT_UPB": current_upb or [float(balance)] * n, "CURR_RATE": [float(rate)] * n,
        "DLQ_STATUS": status, "MOD_FLAG": mod or ["N"] * n, "Zero_Bal_Code": zb or [None] * n,
        "FORBEARANCE_INDICATOR": forbearance or [None] * n,
    }, schema_overrides={"DLQ_STATUS": pl.Int32, "LOAN_AGE": pl.Int32, "REM_MONTHS": pl.Int32,
                         "ORIG_TERM": pl.Int32, "CURRENT_UPB": pl.Float64,
                         "Zero_Bal_Code": pl.String, "FORBEARANCE_INDICATOR": pl.String})


def example_table(loan):
    """Readable result table for an artificial loan."""
    return build_default(loan).select(
        month=pl.col("ACT_PERIOD").dt.strftime("%Y-%m"),
        status="n_overdue_payments",
        payment_usd=pl.col("payment").round(0),
        overdue_eur=pl.col("overdue_eur").round(0),
        share_pct=(pl.col("overdue_share") * 100).round(2),
        above_threshold="above_threshold",
        counter="month_counter",
        default="default_flag",
        reason=pl.when("default_flag").then(pl.col("default_reason")),
    )


# ===========================================================================
# C. TEST OF THE DEFINITION
# ===========================================================================

def rule_examples():
    """Rules of the definition on artificial loans: actual versus expected result."""
    covid = [None, "F", "F", "F", "F", "F", "F", None, None, None]
    cases = [
        ("Two thresholds: one payment is not enough, default at status 4",
         example_loan([0, 1, 2, 3, 4, 5]), "2019-05", "DPD"),
        ("Only the relative threshold exceeded: no default",
         example_loan([1] * 5, balance=3_500, rate=0, remaining=40), None, None),
        ("Only the absolute threshold exceeded: no default",
         example_loan([1] * 5, balance=500_000, remaining=360), None, None),
        ("A repayment resets the counter",
         example_loan([1, 2, 0, 1, 2, 3], balance=20_000, rate=0, remaining=12), "2019-06", "DPD"),
        ("Status 2 for several months: default only at status 3",
         example_loan([2, 2, 2, 2, 3], balance=20_000, rate=0, remaining=12), "2019-05", "DPD"),
        ("A loss sale is a default",
         example_loan([0, 1, 0], zb=[None, None, "03"]), "2019-03", "UTP_loss_sale"),
        ("A modification is a default",
         example_loan([0, 1, 0, 0], mod=["N", "Y", "Y", "Y"]), "2019-02", "UTP_modification"),
        ("COVID forbearance freezes the counter",
         example_loan(list(range(10)), balance=20_000, rate=0, remaining=120,
                      start=dt.date(2020, 3, 1), forbearance=covid), "2020-12", "DPD"),
        ("Masked balance: the overdue amount can still be calculated, default at status 3",
         example_loan([1, 2, 3], balance=20_000, rate=0, remaining=12, age=1,
                      current_upb=[0.0, None, 18_000.0]), "2019-03", "DPD"),
    ]
    rows = []
    for name, loan, expected_month, expected_reason in cases:
        result = build_default(loan)
        first = result["first_default_date"][0]
        month = first.strftime("%Y-%m") if first else None
        reason = result["default_reason"][0]
        passed = month == expected_month and reason == expected_reason
        rows.append({"rule": name, "expected_default": expected_month, "result": month,
                     "reason": reason, "test": "PASS" if passed else "FAIL"})
    return pl.DataFrame(rows, schema_overrides={"expected_default": pl.String, "result": pl.String,
                                                "reason": pl.String})


def choose_test_loans(panel):
    """Samples loans for the test: half with and half without a default, if possible."""
    import random
    random.seed(C.SAMPLE_SEED)
    loans = panel.group_by("LOAN_ID").agg(has_default=pl.col("default_flag").any()).collect().sort("LOAN_ID")
    with_default = loans.filter(pl.col("has_default"))["LOAN_ID"].to_list()
    without_default = loans.filter(~pl.col("has_default"))["LOAN_ID"].to_list()
    half = C.TEST_LOANS // 2
    return (random.sample(with_default, min(half, len(with_default)))
            + random.sample(without_default, min(half, len(without_default))))


def recalculate_loan(rows):
    """Calculates the default again: a plain loop, month by month, from source fields."""
    covid_start, covid_end = date.fromisoformat(C.COVID_START), date.fromisoformat(C.COVID_END)
    counter, status, previous = 0, 0, None
    first_dpd = first_loss = first_mod = None

    for row in rows:
        month = row["ACT_PERIOD"]
        if row["DLQ_STATUS"] is not None:
            status = row["DLQ_STATUS"]

        # Balance
        balance = row["CURRENT_UPB"]
        if balance is None or balance <= 0:
            r0, n0, k = row["ORIG_RATE"] / 1200, row["ORIG_TERM"], max(row["LOAN_AGE"] or 0, 0)
            if r0 > 0:
                balance = row["ORIG_UPB"] * ((1 + r0) ** n0 - (1 + r0) ** k) / ((1 + r0) ** n0 - 1)
            else:
                balance = row["ORIG_UPB"] * (1 - k / n0)

        # Payment
        rate = row["CURR_RATE"] if row["CURR_RATE"] is not None else row["ORIG_RATE"]
        r = rate / 1200
        n = row["REM_MONTHS"]
        if n is None and row["LOAN_AGE"] is not None:
            n = row["ORIG_TERM"] - row["LOAN_AGE"]
        if n is None:
            payment = None                  # termination month
        elif n <= 0:
            payment = balance
        elif r == 0:
            payment = balance / n
        else:
            payment = balance * r / (1 - (1 + r) ** (-n))

        # Thresholds and counter
        freeze = row["FORBEARANCE_INDICATOR"] == C.FORBEARANCE_CODE and covid_start <= month <= covid_end
        gap = previous is not None and (month.year * 12 + month.month) - (previous.year * 12 + previous.month) > 1
        if payment is not None:
            overdue = status * payment
            above = overdue / C.USD_PER_EUR > C.THRESHOLD_ABS_EUR and overdue / balance > C.THRESHOLD_REL
            if not above:
                counter = 0
            else:
                if gap:
                    counter = 0
                if not freeze:
                    counter += 1
            if not freeze and counter >= C.DPD_MONTHS and status >= C.DPD_MIN_STATUS and first_dpd is None:
                first_dpd = month

        # UTP events
        if row["Zero_Bal_Code"] in C.ZB_LOSS and first_loss is None:
            first_loss = month
        if row["MOD_FLAG"] == "Y" and first_mod is None:
            first_mod = month
        previous = month

    events = [("DPD", first_dpd), ("UTP_loss_sale", first_loss), ("UTP_modification", first_mod)]
    events = [e for e in events if e[1] is not None]
    if not events:
        return None, None
    earliest = min(e[1] for e in events)
    return earliest, next(reason for reason, d in events if d == earliest)


def independent_check(test):
    """Compares the default from notebook 2 with the independent recalculation."""
    rows = []
    for (loan_id,), loan in test.group_by(["LOAN_ID"], maintain_order=True):
        first, reason = recalculate_loan(loan.to_dicts())
        rows.append({"LOAN_ID": loan_id, "date_check": first, "reason_check": reason})
    check = pl.DataFrame(rows, schema_overrides={"date_check": pl.Date, "reason_check": pl.String})
    result = test.group_by("LOAN_ID").agg(
        pl.col("first_default_date").first(), pl.col("default_reason").first()
    ).join(check, on="LOAN_ID")
    different = result.filter(
        pl.col("first_default_date").eq_missing(pl.col("date_check")).not_()
        | pl.col("default_reason").eq_missing(pl.col("reason_check")).not_()
    )
    return result.height, different.height


def crr_checks(test, n_compared, n_different):
    """List of requirements. Counts the violations of each one."""
    dpd = test.filter(pl.col("default_flag") & (pl.col("default_reason") == "DPD"))
    first = pl.col("first_default_date")
    loss = test.filter(pl.col("Zero_Bal_Code").is_in(C.ZB_LOSS).fill_null(False))
    mod = test.filter((pl.col("MOD_FLAG") == "Y").fill_null(False))
    per_loan = test.group_by("LOAN_ID").agg(n_flags=pl.col("default_flag").sum())

    checks = [
        ("The independent recalculation gives the same date and reason", "method", n_different, n_compared),
        ("A DPD default has a counter of at least 3", "Art. 178(1)(b)",
         dpd.filter(pl.col("month_counter") < C.DPD_MONTHS).height, dpd.height),
        ("A DPD default has a status of at least 3 (90 days)", "Art. 178(1)(b)",
         dpd.filter(pl.col("n_overdue_payments") < C.DPD_MIN_STATUS).height, dpd.height),
        ("Both thresholds are exceeded in the DPD default month", "Regulation 2018/171",
         dpd.filter(~pl.col("above_abs_threshold") | ~pl.col("above_rel_threshold")).height, dpd.height),
        ("A loss sale is a default", "Art. 178(3)(c)",
         loss.filter(first.is_null() | (first > pl.col("ACT_PERIOD"))).height, loss.height),
        ("A modification is a default", "Art. 178(3)(d)",
         mod.filter(first.is_null() | (first > pl.col("ACT_PERIOD"))).height, mod.height),
        ("No DPD default in a COVID forbearance month", "EBA/GL/2020/02",
         dpd.filter(pl.col("covid_freeze")).height, dpd.height),
        ("A loan has at most one default", "study assumption",
         per_loan.filter(pl.col("n_flags") > 1).height, per_loan.height),
        ("Months after default are marked correctly", "study assumption",
         test.filter(pl.col("after_default") != (first < pl.col("ACT_PERIOD")).fill_null(False)).height, test.height),
    ]
    return pl.DataFrame(checks, schema=["requirement", "basis", "violations", "checked"], orient="row").with_columns(
        result=pl.when(pl.col("violations") > 0).then(pl.lit("FAIL"))
        .when(pl.col("checked") == 0).then(pl.lit("NO DATA"))
        .otherwise(pl.lit("PASS"))
    )


def compare_with_simple_rule(panel):
    """Comparison with the simple rule: DPD default at the first status of 3 or higher."""
    is_dpd = ((pl.col("month_counter") >= C.DPD_MONTHS)
              & (pl.col("n_overdue_payments") >= C.DPD_MIN_STATUS) & ~pl.col("covid_freeze"))
    dates = (
        panel.group_by("LOAN_ID").agg(
            simple=pl.col("ACT_PERIOD").filter(pl.col("n_overdue_payments") >= 3).min(),
            definition=pl.col("ACT_PERIOD").filter(is_dpd).min(),
            forbearance=pl.col("covid_freeze").any(),
        ).filter(pl.col("simple").is_not_null()).collect()
    )
    return dates.with_columns(
        result=pl.when(pl.col("definition").is_null()).then(pl.lit("no DPD default"))
        .when(pl.col("definition") == pl.col("simple")).then(pl.lit("same month"))
        .otherwise(pl.lit("later"))
    ).group_by("result").agg(loans=pl.len(), with_forbearance=pl.col("forbearance").sum()).sort("result")


# ===========================================================================
# D. MODEL DATASET
# ===========================================================================

def build_model_dataset(df, data_end):
    """
    Builds quarterly snapshots: one row is a loan at a quarter end.
    Explanatory variables use only information known at the snapshot date.
    """
    month = pl.col("ACT_PERIOD")
    window_end = month.dt.offset_by(f"{C.TARGET_HORIZON_M}mo")
    first_default = pl.col("first_default_date")
    status = pl.col("n_overdue_payments")
    window = {"by": "ACT_PERIOD", "window_size": C.HISTORY_WINDOW}

    prepaid = df.filter(pl.col("Zero_Bal_Code") == C.ZB_PREPAID).group_by("LOAN_ID").agg(prepaid_date=month.min())

    return (
        df.sort("LOAN_ID", "ACT_PERIOD")
        # Loan history is calculated on all months, before selecting snapshots
        .with_columns(
            max_delinquency_12m=status.rolling_max_by(**window).over("LOAN_ID"),
            n_late_months_12m=(status >= 1).cast(pl.Int32).rolling_sum_by(**window).over("LOAN_ID"),
            in_forbearance=(pl.col("FORBEARANCE_INDICATOR") == C.FORBEARANCE_CODE).fill_null(False),
        )
        .with_columns(ever_forbearance=pl.col("in_forbearance").cum_max().over("LOAN_ID"))
        .join(prepaid, on="LOAN_ID", how="left")
        # Snapshot: quarter end, active loan, no default yet, 12 full months observed
        .filter(
            month.dt.month().is_in(C.SNAPSHOT_MONTHS)
            & pl.col("Zero_Bal_Code").is_null()
            & (first_default.is_null() | (first_default > month))
            & (window_end <= data_end)
        )
        .select(
            loan_id="LOAN_ID",
            snapshot_date="ACT_PERIOD",
            cohort="cohort",
            # Target variable
            target_12m=(first_default <= window_end).fill_null(False).cast(pl.Int8),
            # For analysis only: future information, must not enter the model
            prepaid_12m=(pl.col("prepaid_date") <= window_end).fill_null(False).cast(pl.Int8),
            # Structural variables
            fico=pl.min_horizontal("CSCORE_B", "CSCORE_C"),
            fico_missing=pl.min_horizontal("CSCORE_B", "CSCORE_C").is_null().cast(pl.Int8),
            ltv_orig="OLTV",
            cltv_orig="OCLTV",
            dti="DTI",
            dti_missing=pl.col("DTI").is_null().cast(pl.Int8),
            rate_orig="ORIG_RATE",
            loan_amount_k=pl.col("ORIG_UPB") / 1000,
            mi_pct=pl.col("MI_PCT").fill_null(0),
            n_borrowers="NUM_BO",
            n_units="NO_UNITS",
            purpose="PURPOSE",
            occupancy="OCC_STAT",
            property_type="PROP",
            first_time_buyer="FIRST_FLAG",
            channel="CHANNEL",
            state="STATE",
            # Cyclical variables
            months_delinquent=status,
            max_delinquency_12m="max_delinquency_12m",
            n_late_months_12m="n_late_months_12m",
            in_forbearance=pl.col("in_forbearance").cast(pl.Int8),
            ever_forbearance=pl.col("ever_forbearance").cast(pl.Int8),
            # Mixed variables
            loan_age="LOAN_AGE",
            balance_k=pl.col("balance") / 1000,
            paid_share=1 - pl.col("balance") / pl.col("ORIG_UPB"),
        )
    )


def variable_dictionary():
    """Dictionary of the explanatory variables."""
    return pl.DataFrame([(name, group, text) for name, (group, text) in C.MODEL_VARIABLES.items()],
                        schema=["variable", "group", "description"], orient="row")


# ===========================================================================
# E. TABLES AND CHARTS
# ===========================================================================

def clean_axes(ax, title, ylabel=None):
    """Consistent look of the charts."""
    ax.set_title(title, loc="left", fontsize=11)
    if ylabel:
        ax.set_ylabel(ylabel, color="#52514e", fontsize=9)
    ax.grid(axis="y", color="#e5e4e0", lw=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#b5b4ad")
    ax.tick_params(colors="#52514e", labelsize=8, length=0)


def numeric_summary(data):
    """Descriptive statistics of the numeric variables."""
    rows = []
    for name in C.NUMERIC_VARIABLES:
        c = pl.col(name)
        stats = data.select(
            missing_pct=c.is_null().mean() * 100, mean=c.mean(), std=c.std(), min=c.min(),
            p01=c.quantile(0.01), p25=c.quantile(0.25), median=c.median(),
            p75=c.quantile(0.75), p99=c.quantile(0.99), max=c.max(),
        ).collect().row(0, named=True)
        rows.append({"variable": name, **stats})
    return pl.DataFrame(rows).with_columns(pl.selectors.numeric().round(2))


def category_summary(data, top=10):
    """Share of each category and share of target = 1."""
    tables = []
    for name in C.CATEGORY_VARIABLES:
        table = (
            data.group_by(pl.col(name).cast(pl.String).fill_null("missing").alias("value"))
            .agg(snapshots=pl.len(), target_rate_pct=pl.col("target_12m").mean() * 100)
            .sort("snapshots", descending=True).collect()
            .with_columns(variable=pl.lit(name), share_pct=pl.col("snapshots") / pl.col("snapshots").sum() * 100)
            .select("variable", "value", "snapshots", "share_pct", "target_rate_pct")
        )
        tables.append(table.head(top))
    return pl.concat(tables).with_columns(pl.col("share_pct", "target_rate_pct").round(2))


def target_by_bins(data, name, edges):
    """Share of target = 1 in the bins of one variable."""
    return (
        data.with_columns(
            bin=pl.when(pl.col(name).is_null()).then(pl.lit("missing"))
            .otherwise(pl.col(name).cut(edges).cast(pl.String))
        )
        .group_by("bin")
        .agg(lowest=pl.col(name).min(), snapshots=pl.len(), target_rate_pct=pl.col("target_12m").mean() * 100)
        .sort("lowest", nulls_last=True)
        .collect()
    )


def plot_target_by_bins(data):
    """Charts: how the share of target = 1 changes with the variable."""
    fig, axes = plt.subplots(2, 3, figsize=(12, 6.5))
    for ax, (name, edges) in zip(axes.flat, C.BINS.items()):
        table = target_by_bins(data, name, edges)
        ax.bar(table["bin"].to_list(), table["target_rate_pct"].to_list(), color=BLUE)
        clean_axes(ax, name, "target = 1 (%)")
        ax.tick_params(axis="x", labelrotation=30)
    fig.tight_layout()
    return fig


def plot_target_over_time(data):
    """Chart: share of target = 1 and number of snapshots over time."""
    table = (data.group_by("snapshot_date")
             .agg(snapshots=pl.len(), target_rate_pct=pl.col("target_12m").mean() * 100)
             .sort("snapshot_date").collect())
    fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    axes[0].plot(table["snapshot_date"].to_list(), table["target_rate_pct"].to_list(), lw=2, color=BLUE)
    clean_axes(axes[0], "Share of snapshots with target = 1", "%")
    axes[1].bar(table["snapshot_date"].to_list(), table["snapshots"].to_list(), width=70, color=BLUE)
    clean_axes(axes[1], "Number of snapshots")
    fig.tight_layout()
    return fig, table


def correlations(data, sample_size=500_000):
    """Spearman correlation of the numeric variables, on a random sample of rows."""
    table = data.select(C.NUMERIC_VARIABLES + ["target_12m"]).collect()
    table = table.sample(min(sample_size, table.height), seed=C.SAMPLE_SEED)
    with_target = pl.DataFrame([
        {"variable": name,
         "correlation_with_target": table.drop_nulls(name).select(pl.corr(name, "target_12m", method="spearman")).item()}
        for name in C.NUMERIC_VARIABLES
    ]).with_columns(pl.col("correlation_with_target").round(3)).sort("correlation_with_target", descending=True)
    return table, with_target


def plot_correlation_matrix(table):
    """Correlation map of the numeric variables."""
    names = C.NUMERIC_VARIABLES
    ranks = table.select(names).drop_nulls().select(pl.all().rank()).to_numpy()
    import numpy as np
    matrix = np.corrcoef(ranks, rowvar=False)
    fig, ax = plt.subplots(figsize=(9, 8))
    image = ax.imshow(matrix, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(len(names)), names, rotation=90, fontsize=8)
    ax.set_yticks(range(len(names)), names, fontsize=8)
    ax.set_title("Spearman correlation between variables", loc="left", fontsize=11)
    ax.tick_params(length=0)
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_visible(False)
    fig.colorbar(image, shrink=0.8)
    fig.tight_layout()
    return fig


# ===========================================================================
# F. FIRST LOOK AT THE RAW DATA
# ===========================================================================

def load_raw_sample(path):
    """Reads all columns of the sampled loans, as text. Empty fields become missing."""
    ids = read_raw(path).select("LOAN_ID").unique().collect()["LOAN_ID"].to_list()
    sampled = [loan_id for loan_id in ids if in_sample(loan_id)]
    df = (
        read_raw(path)
        .filter(pl.col("LOAN_ID").is_in(sampled))
        .with_columns(pl.all().str.strip_chars())
        .with_columns(pl.when(pl.all() == "").then(None).otherwise(pl.all()).name.keep())
        .with_columns(period=mmyyyy_to_date("ACT_PERIOD"), cohort=pl.lit(path.stem))
        .collect()
    )
    return df, len(ids)


def raw_size(df, cohort, n_all):
    """Basic size of one file."""
    per_loan = df.group_by("LOAN_ID").len()
    return {"cohort": cohort, "loans_in_file": n_all, "sampled_loans": per_loan.height, "sampled_rows": df.height,
            "columns": df.width - 2, "first_month": df["period"].min(), "last_month": df["period"].max(),
            "median_months_per_loan": per_loan["len"].median(), "max_months_per_loan": per_loan["len"].max()}


def raw_columns(df, cohort):
    """One row per original column: missing values, distinct values, examples and range."""
    columns = [c for c in df.columns if c not in ("period", "cohort")]
    others = [c for c in columns if c != "LOAN_ID"]
    changing = df.group_by("LOAN_ID").agg(pl.col(others).n_unique()).select(
        [(pl.col(c).max() > 1).alias(c) for c in others]).row(0, named=True)
    changing["LOAN_ID"] = False
    rows = []
    for position, name in enumerate(columns, start=1):
        values = df[name]
        known = values.drop_nulls()
        numbers = known.cast(pl.Float64, strict=False).drop_nulls()
        is_numeric = known.len() > 0 and numbers.len() == known.len()
        top = known.value_counts(sort=True).head(3)[name].to_list()
        rows.append({
            "cohort": cohort, "position": position, "column": name,
            "used_in_project": name in C.RAW_VARIABLES,
            "description": C.RAW_VARIABLES.get(name, ""),
            "missing_pct": round(values.is_null().mean() * 100, 2),
            "n_distinct": known.n_unique(),
            "changes_over_time": changing[name],
            "top_values": ", ".join(top),
            "min": numbers.min() if is_numeric else None,
            "max": numbers.max() if is_numeric else None,
        })
    return pl.DataFrame(rows, schema_overrides={"min": pl.Float64, "max": pl.Float64})


def raw_codes(df, cohort, columns):
    """Distribution of the codes used in the project."""
    tables = []
    for name in columns:
        table = (df.group_by(pl.col(name).fill_null("missing").alias("value")).len().sort("len", descending=True)
                 .with_columns(share_pct=(pl.col("len") / pl.col("len").sum() * 100).round(3))
                 .rename({"len": "rows"}))
        tables.append(table.with_columns(cohort=pl.lit(cohort), column=pl.lit(name))
                      .select("cohort", "column", "value", "rows", "share_pct"))
    return pl.concat(tables)


def masked_balance(df, cohort):
    """Share of rows with an empty or zero balance, by loan age."""
    balance = pl.col("CURRENT_UPB").cast(pl.Float64, strict=False)
    return (
        df.with_columns(loan_age=pl.col("LOAN_AGE").cast(pl.Int32, strict=False))
        .filter(pl.col("loan_age").is_between(0, 12))
        .group_by("loan_age")
        .agg(rows=pl.len(), masked_pct=((balance.is_null() | (balance <= 0)).mean() * 100).round(1))
        .sort("loan_age")
        .with_columns(cohort=pl.lit(cohort))
    )


def support_programs(df, cohort):
    """When loans first get a modification, forbearance or payment deferral, and their status before it."""
    start, end = date.fromisoformat(C.COVID_START), date.fromisoformat(C.COVID_END)
    status = pl.col("DLQ_STATUS").cast(pl.Int32, strict=False)
    events = {
        "modification": pl.col("MOD_FLAG") == "Y",
        "forbearance": pl.col("FORBEARANCE_INDICATOR") == C.FORBEARANCE_CODE,
        "payment_deferral": pl.col("ADR_TYPE").is_in(["P", "C", "D"]),
    }
    rows = []
    ordered = df.sort("LOAN_ID", "period").with_columns(previous_status=status.shift(1).over("LOAN_ID"))
    for name, condition in events.items():
        first = (ordered.filter(condition.fill_null(False)).group_by("LOAN_ID")
                 .agg(pl.col("period").min().alias("first"), pl.col("previous_status").first()))
        in_covid = first.filter(pl.col("first").is_between(start, end)).height
        rows.append({
            "cohort": cohort, "event": name, "loans": first.height,
            "share_of_loans_pct": round(first.height / df["LOAN_ID"].n_unique() * 100, 2),
            "first_in_covid_period": in_covid, "first_outside_covid_period": first.height - in_covid,
            "delinquent_before_pct": round(float((first["previous_status"] >= 1).mean() or 0) * 100, 1)
            if first.height else None,
        })
    return pl.DataFrame(rows)
