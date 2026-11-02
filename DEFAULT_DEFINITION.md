# Default definition: methodology

The definition is based on Article 178 of the CRR and Delegated Regulation (EU) 2018/171. The code is
in `02_default_definition.ipynb`, the parameters are in `config.py`, and the test is in `03_default_test.ipynb`.

## 1. Definition

A loan is in default in the month in which the first of three events occurs:

| Reason | Condition | Basis |
|---|---|---|
| `DPD` | for 3 consecutive months the overdue amount exceeds EUR 100 and 1% of the balance, and the delinquency status is at least 3 | Art. 178(1)(b) and (2)(d); Regulation 2018/171 |
| `UTP_loss_sale` | termination code 02, 03, 09 or 15 | Art. 178(3)(c) |
| `UTP_modification` | `MOD_FLAG` = "Y" | Art. 178(3)(d) |

Only the first default of a loan counts. Later months are marked `after_default`
and are excluded from the modelling population.

## 2. Materiality threshold

Both conditions must be met at the same time:

- absolute - overdue amount above EUR 100;
- relative - overdue amount above 1% of the current balance.

The threshold is set in euro because Regulation 2018/171 sets the upper limit of the absolute threshold
for retail exposures in this currency. Poland applies a national threshold of PLN 400, and this difference
must be explained in the thesis. The data is in USD, so the threshold is converted at one fixed rate: EUR 1 = USD 1.10,
which means EUR 100 = USD 110. With a fixed rate, the threshold does not move with the currency market.

## 3. How the overdue amount is calculated

The data does not report the overdue amount, so it is approximated:

1. balance `CURRENT_UPB`. When the field is empty or equal to 0, I use the balance from the repayment schedule.
2. payment balance · r / (1 − (1 + r)^(−n)), where r is the current rate / 12 and n is the remaining term.
   For r = 0 the payment is balance / n. For n ≤ 0 the whole balance is due.
3. Overdue amount - `DLQ_STATUS` × payment. Status `XX` is replaced with the last known status.

## 4. Month counter

- It increases by 1 in each month in which the threshold is exceeded.
- It resets to zero when the threshold is not exceeded or when a month is missing from the loan history.
- A DPD default requires a counter ≥ 3 and a status ≥ 3 (the oldest payment is at least 90 days overdue), outside COVID forbearance months.

-> Why status ≥ 3: in the 2007Q1 and 2019Q1 data, the counter alone triggered some defaults at status 2. This happens when the status stays at 2, for example when a borrower pays one instalment a month but does not catch up on arrears. The oldest payment is then less than 90 days overdue, so the additional condition directly reflects Art. 178(1)(b).

-> Effect:  the payment on a 30-year loan is usually about 0.5–0.7% of the balance, so one overdue payment does not
exceed the 1% threshold. The counter usually starts at the second payment, and the default occurs at status 4
rather than 3. `03_default_test.ipynb` shows the size of this effect in the data.

## 5. COVID forbearance

In forbearance months (code `F`) between 03.2020 and 12.2023, the counter neither increases nor resets
(EBA/GL/2020/02). After forbearance ends:

- if the arrears have been settled, the threshold is not exceeded and the counter resets;
- if the arrears still exceed the threshold, the counter continues to increase.

The length of the COVID period is an assumption that must be justified.

## 6. Assumptions and limitations

| Assumption | Justification | Limitation |
|---|---|---|
| Status ≥ 3 = at least 90 days | the data is monthly | no exact number of days |
| Payment excludes taxes and insurance | they are not in the data | the overdue amount is likely understated |
| Threshold per loan, not per obligor | the data does not link loans of one person | departure from Art. 178(1) |
| Every modification is a default | it is usually a measure for a borrower in difficulty | the reduction in value above 1% is not measured |
| Fixed EUR/USD rate | simplicity and a stable threshold | the rate is a simplification |
| Other UTP indicators omitted | they are not in the data | defaults may be understated |

## 7. Population

Notebook `01_data_cleaning.ipynb` saves the exclusion waterfall in `reports/waterfall.csv`:

1. random selection of 3% of loans by ID, with the same rule for every file;
2. loan term of 360 months;
3. FRM product;
4. no relief refinance;
5. key fields present: origination date, amount, rate, LTV, state.

Loans repurchased by the seller are not excluded, because that would be selection based on a future event.

## 8. Test of the definition

Notebook `03_default_test.ipynb` calculates the default a second time with an independent loop and checks a list of requirements.
The test shows that the results agree with the adopted definition. It does not prove full compliance with the CRR, because some
requirements cannot be reproduced with this data (section 6).

## 9. PD model dataset

Notebook `04_model_dataset.ipynb` creates `model_dataset.parquet`. One row is a loan at a quarter end (a snapshot).

A snapshot enters the dataset when the loan is active, has not yet defaulted, and 12 full months are observed after the snapshot.

- `target_12m` = 1 when the first default occurs within the next 12 months, otherwise 0.
- A loan prepaid within this window has `target_12m` = 0. This is a competing risk that may understate PD in periods of mass refinancing. The `prepaid_12m` flag is for analysis only and must not enter the model.
- The dataset does not contain the default date or reason, because they are future information.
- A missing `MI_PCT` is treated as no insurance. This assumption must be confirmed in the glossary.
- One loan appears in many snapshots, so the observations are not independent.

Variables are divided into structural, cyclical and mixed. The full dictionary is in `config.py` and in `reports/model_variables.csv`.
The dataset does not yet contain macroeconomic data or current LTV.

## 10. Restructuring, forbearance and payment deferrals

The data distinguishes three events, which I treat differently:

| Event | Field | Meaning | Treatment |
|---|---|---|---|
| Modification | `MOD_FLAG` = Y | permanent change to the loan terms | default, in every period |
| Forbearance | code `F` | temporary suspension or reduction of payments | not a default in itself; freezes the DPD counter in the COVID period |
| Payment deferral | `ADR_TYPE` = P, C, D | overdue payments moved to a later date | not a default in itself; usually resets the delinquency status |

**Modification.** Art. 178(3)(d) of the CRR refers to distressed restructuring that is likely to reduce the financial obligation. The EBA guidelines set a 1% threshold for the reduction in present value. The data does not allow this to be measured, so I use a simplification: every modification is a default. The basis is that almost all modifications in the data follow a delinquency (`support_programs.csv` from notebook 0).

**COVID forbearance.** The programme suspended payments for many borrowers, and the delinquency status formally increased. Without an exception, the counter would immediately treat this as credit difficulty. EBA/GL/2020/02 shows a similar approach to moratoria, but it applies to EU institutions and to specific, time-limited moratoria. For US programmes it is therefore only an analogy, and the period 03.2020–12.2023 is an assumption of this study.

**Limitations:**
- some modifications may not meet the 1% threshold, so defaults may be overstated;
- a payment deferral may also be a restructuring under the EBA definition, but I do not treat it as a default, so defaults may be understated;
- the forbearance field is usually empty in older periods, so earlier forbearance often cannot be identified.
