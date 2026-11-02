# Building a PD model dataset using Fannie Mae data

This project converts raw mortgage loan data into a PD model dataset, with a default definition based on Article 178 of the CRR.

## Workflow

Run the notebooks one by one using **Run All**. Each notebook begins with a description of the purpose, input data, and output.

| Notebook | Data | Output |
|---|---|---|
| `00_data_overview.ipynb` | Original data | tables in `reports/overview/` |
| `01_data_cleaning.ipynb` | Analyses of loans and variables - raw data | `clean/` |
| `02_default_definition.ipynb` | Loans in default | `default/` |
| `03_default_test.ipynb` | Testing DoD | Test tables |
| `04_model_dataset.ipynb` | Model set | `model_dataset.parquet` |
| `05_eda.ipynb` | Data analysis | Tables and graphs |

## Support files

| File | What is it for | When to open it |
|---|---|---|
| `config.py` | all assumptions: data folder, cohorts, thresholds, COVID period | when changing an assumption |
| `functions.py` | details of calculations used in notebooks | when you want to check the exact formula |
| `columns.py` | column order in raw files | when the file layout changes |
| `DEFAULT_DEFINITION.md` | description of the method and assumptions | when writing a thesis |
| `tests/make_synthetic.py` | artificial data for code verification | usually unnecessary |

## Preparation

1. Install the libraries:
```
python -m pip install -r requirements.txt
```
2. Save the quarterly files as `raw/2007Q1.csv` in the data folder.
3. Set the `DATA_DIR` and `FILES` values ​​in `config.py`.
