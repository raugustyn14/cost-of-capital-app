# Project Cost of Equity & WACC: USD vs. Local Currency

A Streamlit app that compares a project's cost of equity and WACC in U.S. dollars and in the
currency of a selected country, using the same tax rate, debt share and equity risk premium.

## Data sources (fetched live, with a Refresh button)

| Data | Source | Used for |
|---|---|---|
| U.S. industry unlevered betas | Damodaran `betas.xls` (sheet *Industry Averages*, column *Unlevered beta*) | Project beta |
| BBB spread | Damodaran *ratings.html* (Baa2/BBB, large non-financial service firms) | USD cost of debt |
| Corporate tax rates | OECD *Corporate Tax Statistics 2024*, statutory rates table (latest year per country) | Tax shield |
| 10-year government yields | Trading Economics `/bonds` (scraped; no API key) | Risk-free rates |

The *Sources and data dates* table in the app shows each URL, the data date, the retrieval time and
any fetch error. Data are cached (yields 30 min, others 6–24 h); **Refresh data** clears the cache.

## Formulas (standard versions; check against your class notes)

- D/E = d / (1 − d)
- Levered beta = Bu × (1 + (1 − t) × D/E)
- **USD:** Ke = y_US + β_L × ERP; Kd = y_US + BBB spread; WACC = (1 − d)·Ke + d·Kd·(1 − t)
- **Local currency:** Ke_FC = (1 + Ke_USD)·(1 + y_FC)/(1 + y_US) − 1; Kd_FC = y_FC + local BBB spread;
  WACC_FC = (1 − d)·Ke_FC + d·Kd_FC·(1 − t)
- **Auto local BBB spread:** (1 + y_US + s_USD)·(1 + y_FC)/(1 + y_US) − 1 − y_FC, so Kd_FC equals the USD Kd
  converted by the yield ratio. It can be overridden manually.

## Features

- Defaults: Software (System & Application), United States, U.S. tax rate, ERP 6.5%, debt share 30%.
- Select industry and country; adjust ERP and debt share.
- Manual overrides for unlevered beta, U.S. and country tax rates, USD BBB spread, and both 10Y yields.
  The foreign BBB spread has an override switch; when off it shows the automatic value.
- Button to switch the project tax rate between the U.S. and the selected country.
- Side-by-side USD vs. local-currency results, assumptions, calculation checks,
  an all-industry comparison (table and chart) and CSV downloads.

## Run locally

```bash
python3.12 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## Deploy on Streamlit Community Cloud

1. Create a GitHub repository and upload `app.py`, `requirements.txt`, `README.md`.
2. At share.streamlit.io choose **New app**, select the repository, branch `main`, main file `app.py`.
3. Set Python 3.12 under *Advanced settings* and deploy.

## Limitations

- Pages are scraped, so layout changes at Damodaran, OECD or Trading Economics can break a parser or
  rename a country. The app reports the failure and every input has a manual override.
- Trading Economics may block automated requests from some hosts; check its terms of use.
- Betas are U.S. industry averages. No country-risk premium is added; the ERP is a single input.
- Country names are matched across sources by normalized name with a small alias list
  (e.g. Korea / South Korea); a missing match asks for a manual tax rate.
- I could not test live fetches from the build environment (no internet), only the calculations and
  the parsers on sample data. Verify the first live run against the source websites.
