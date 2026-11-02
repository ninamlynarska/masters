"""
Project settings. Change only this file to change the assumptions of the study.
"""
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Folders and files
# ---------------------------------------------------------------------------
DATA_DIR = Path(os.environ.get("FM_DATA_DIR", r"C:/fannie_mae"))  # main data folder

RAW_DIR = DATA_DIR / "raw"            # raw quarterly files, e.g. 2007Q1.csv
CLEAN_DIR = DATA_DIR / "clean"        # output of notebook 1
DEFAULT_DIR = DATA_DIR / "default"    # output of notebook 2
MODEL_DIR = DATA_DIR / "model"        # output of notebook 4, one file per cohort
MODEL_FILE = DATA_DIR / "model_dataset.parquet"   # final dataset for the PD model
REPORT_DIR = DATA_DIR / "reports"     # tables and charts

# ---------------------------------------------------------------------------
# Notebook 1: data cleaning
# ---------------------------------------------------------------------------
FILES = ["2007Q1", "2019Q1"]          # cohorts to process; None means all
SAMPLE_PCT = int(os.environ.get("FM_SAMPLE_PCT", 3))   # percent of loans sampled
SAMPLE_SEED = 42                      # random seed: the same sample in every run

KEEP_ORIG_TERM = 360                  # 30-year loans only
KEEP_PRODUCT = "FRM"                  # fixed-rate loans only
CRITICAL_FIELDS = ["ORIG_DATE", "ORIG_UPB", "ORIG_RATE", "OLTV", "STATE"]   # must be present

# Allowed ranges. A value outside the range is treated as missing.
LIMITS = {"OLTV": (1, 200), "OCLTV": (1, 200), "DTI": (0, 100),
          "CSCORE_B": (300, 850), "CSCORE_C": (300, 850)}

# Columns read from the raw files: column -> description
RAW_VARIABLES = {
    "LOAN_ID": "loan identifier",
    "ACT_PERIOD": "monthly reporting period",
    "CSCORE_B": "borrower FICO at origination",
    "CSCORE_C": "co-borrower FICO at origination",
    "OLTV": "LTV at origination (%)",
    "OCLTV": "CLTV at origination (%)",
    "DTI": "DTI at origination (%)",
    "ORIG_RATE": "interest rate at origination (%)",
    "ORIG_UPB": "loan amount (USD)",
    "ORIG_TERM": "loan term (months)",
    "ORIG_DATE": "origination date",
    "PURPOSE": "loan purpose",
    "OCC_STAT": "occupancy",
    "PROP": "property type",
    "NO_UNITS": "number of units",
    "NUM_BO": "number of borrowers",
    "FIRST_FLAG": "first-time buyer",
    "MI_PCT": "mortgage insurance coverage (%)",
    "CHANNEL": "sales channel",
    "STATE": "state",
    "PRODUCT": "product type",
    "HIGH_LOAN_TO_VALUE_HLTV_REFINANCE_OPTION_INDICATOR": "relief refinance program",
    "CURRENT_UPB": "current balance (USD)",
    "CURR_RATE": "current interest rate (%)",
    "LOAN_AGE": "loan age (months)",
    "REM_MONTHS": "remaining term (months)",
    "DLQ_STATUS": "delinquency status (months)",
    "MOD_FLAG": "loan modification",
    "Zero_Bal_Code": "loan termination code",
    "FORBEARANCE_INDICATOR": "assistance plan, F means forbearance",
}
ORIGINATION_COLS = ["CSCORE_B", "CSCORE_C", "OLTV", "OCLTV", "DTI", "ORIG_RATE", "ORIG_UPB", "ORIG_TERM",
                    "ORIG_DATE", "PURPOSE", "OCC_STAT", "PROP", "NO_UNITS", "NUM_BO", "FIRST_FLAG",
                    "MI_PCT", "CHANNEL", "STATE", "PRODUCT",
                    "HIGH_LOAN_TO_VALUE_HLTV_REFINANCE_OPTION_INDICATOR"]
FLOAT_COLS = ["CSCORE_B", "CSCORE_C", "OLTV", "OCLTV", "DTI", "ORIG_RATE", "ORIG_UPB",
              "MI_PCT", "CURRENT_UPB", "CURR_RATE"]
INT_COLS = ["ORIG_TERM", "NO_UNITS", "NUM_BO", "LOAN_AGE", "REM_MONTHS", "DLQ_STATUS"]
DATE_COLS = ["ACT_PERIOD", "ORIG_DATE"]

# ---------------------------------------------------------------------------
# Notebook 2: default definition
# ---------------------------------------------------------------------------
THRESHOLD_ABS_EUR = 100       # absolute threshold: overdue amount above 100 EUR
THRESHOLD_REL = 0.01          # relative threshold: overdue amount above 1% of balance
USD_PER_EUR = 1.10            # fixed rate: 100 EUR = 110 USD
DPD_MONTHS = 3                # consecutive months above both thresholds
DPD_MIN_STATUS = 3            # minimum delinquency status, i.e. at least 90 days

ZB_LOSS = ["02", "03", "09", "15"]   # loss sale: third-party, short sale, REO, note sale
ZB_PREPAID = "01"                    # prepaid or matured

FORBEARANCE_CODE = "F"        # forbearance code
COVID_START = "2020-03-01"    # start of the period in which forbearance freezes the counter
COVID_END = "2023-12-01"      # end of that period

# ---------------------------------------------------------------------------
# Notebook 3: test of the definition
# ---------------------------------------------------------------------------
TEST_LOANS = 5000             # loans in the independent recalculation

# ---------------------------------------------------------------------------
# Notebook 4: model dataset
# ---------------------------------------------------------------------------
SNAPSHOT_MONTHS = [3, 6, 9, 12]   # a snapshot at each quarter end
TARGET_HORIZON_M = 12             # target: default within 12 months
HISTORY_WINDOW = "12mo"           # window of the delinquency history

# Explanatory variables: name -> (group, description)
MODEL_VARIABLES = {
    "fico": ("structural", "lower of the borrowers' FICO scores at origination"),
    "fico_missing": ("structural", "1 if FICO is missing"),
    "ltv_orig": ("structural", "LTV at origination (%)"),
    "cltv_orig": ("structural", "CLTV at origination (%)"),
    "dti": ("structural", "DTI at origination (%)"),
    "dti_missing": ("structural", "1 if DTI is missing"),
    "rate_orig": ("structural", "interest rate at origination (%)"),
    "loan_amount_k": ("structural", "loan amount (thousand USD)"),
    "mi_pct": ("structural", "insurance coverage (%), missing treated as 0"),
    "n_borrowers": ("structural", "number of borrowers"),
    "n_units": ("structural", "number of units"),
    "purpose": ("structural", "purpose: P purchase, C cash-out refinance, R refinance, U not specified"),
    "occupancy": ("structural", "occupancy: P primary, S second home, I investor, U unknown"),
    "property_type": ("structural", "property type"),
    "first_time_buyer": ("structural", "first-time buyer: Y or N"),
    "channel": ("structural", "channel: R retail, C correspondent, B broker"),
    "state": ("structural", "state"),
    "months_delinquent": ("cyclical", "current delinquency status (months)"),
    "max_delinquency_12m": ("cyclical", "highest delinquency status in the last 12 months"),
    "n_late_months_12m": ("cyclical", "number of delinquent months in the last 12 months"),
    "in_forbearance": ("cyclical", "1 if the loan is in forbearance at the snapshot date"),
    "ever_forbearance": ("cyclical", "1 if the loan was in forbearance up to the snapshot date"),
    "loan_age": ("mixed", "loan age (months)"),
    "balance_k": ("mixed", "current balance (thousand USD)"),
    "paid_share": ("mixed", "repaid share of the original amount"),
}

# ---------------------------------------------------------------------------
# Notebook 5: exploratory analysis
# ---------------------------------------------------------------------------
NUMERIC_VARIABLES = ["fico", "ltv_orig", "cltv_orig", "dti", "rate_orig", "loan_amount_k", "mi_pct",
                     "n_borrowers", "n_units", "months_delinquent", "max_delinquency_12m",
                     "n_late_months_12m", "loan_age",
                     "balance_k", "paid_share"]
CATEGORY_VARIABLES = ["purpose", "occupancy", "property_type", "first_time_buyer", "channel",
                      "in_forbearance", "ever_forbearance", "state"]
# Bin edges for the charts
BINS = {"fico": [620, 660, 700, 740, 780], "ltv_orig": [60, 70, 80, 90, 95], "dti": [20, 30, 40, 45],
        "rate_orig": [4, 5, 6, 7], "loan_age": [12, 36, 60, 120], "max_delinquency_12m": [0, 1, 2]}
