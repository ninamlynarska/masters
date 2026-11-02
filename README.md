# Budowa zbioru do modelu PD na danych Fannie Mae

Projekt zamienia surowe dane o kredytach hipotecznych w zbiór do modelowania PD, z definicją defaultu opartą na art. 178 CRR.

## Kolejność pracy

Uruchamiaj notatniki po kolei przez **Run All**. Każdy zaczyna się od opisu celu, danych wejściowych i wyniku.

| Notatnik | Pytanie, na które odpowiada | Wynik |
|---|---|---|
| `00_data_overview.ipynb` | Jak wyglądają oryginalne dane? | tabele w `reports/overview/` |
| `01_data_cleaning.ipynb` | Które kredyty i zmienne bierzemy do badania? | `clean/` |
| `02_default_definition.ipynb` | Kiedy kredyt jest w defaulcie? | `default/` |
| `03_default_test.ipynb` | Czy kod poprawnie stosuje tę definicję? | tabele testów |
| `04_model_dataset.ipynb` | Jak wygląda zbiór do modelu PD? | `model_dataset.parquet` |
| `05_eda.ipynb` | Co widać w danych przed modelowaniem? | tabele i wykresy |

## Pliki pomocnicze

| Plik | Do czego służy | Kiedy go otworzyć |
|---|---|---|
| `config.py` | wszystkie założenia: folder z danymi, kohorty, progi, okres COVID | gdy zmieniasz założenie |
| `functions.py` | szczegóły obliczeń używanych w notatnikach | gdy chcesz sprawdzić dokładny wzór |
| `columns.py` | kolejność kolumn w surowych plikach | gdy zmieni się układ plików |
| `DEFAULT_DEFINITION.md` | opis metody i założeń | przy pisaniu pracy |
| `tests/make_synthetic.py` | sztuczne dane do sprawdzenia kodu | zwykle niepotrzebny |

## Przygotowanie

1. Zainstaluj biblioteki:
   ```
   python -m pip install -r requirements.txt
   ```
2. Zapisz pliki kwartalne jako `raw/2007Q1.csv` w folderze z danymi.
3. Ustaw w `config.py` wartości `DATA_DIR` i `FILES`.
