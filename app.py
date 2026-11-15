"""
Project Cost of Equity & WACC: USD vs. a selected country's currency.

Data sources (fetched live, each with a refresh button and manual overrides):
  * Damodaran (NYU Stern): U.S. industry unlevered betas, BBB (Baa2) default spread
  * OECD: statutory corporate income tax rates
  * Trading Economics: 10-year government bond yields

Formulas (standard textbook versions - compare with your class notes):
  D/E            = d / (1 - d)
  Levered beta   = Bu * (1 + (1 - t) * D/E)                       (Hamada)
  Ke (USD)       = y_US + Beta_L * ERP
  Kd (USD)       = y_US + BBB spread (USD)
  WACC (USD)     = (1 - d) * Ke + d * Kd * (1 - t)
  Foreign currency (interest-rate / inflation-differential parity):
  Ke (FC)        = (1 + Ke_USD) * (1 + y_FC) / (1 + y_US) - 1
  Kd (FC)        = y_FC + BBB spread (FC)
  Auto FC spread = (1 + y_US + s_USD) * (1 + y_FC) / (1 + y_US) - 1 - y_FC
                   (i.e. Kd_FC is the USD cost of debt converted by the yield ratio)
  WACC (FC)      = (1 - d) * Ke_FC + d * Kd_FC * (1 - t)
Both currencies use the same project tax rate, debt share and equity risk premium.
"""

from __future__ import annotations

import datetime as dt
import io
import re

import pandas as pd
import requests
import streamlit as st

# --------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------
BETAS_URL = "https://pages.stern.nyu.edu/~adamodar/pc/datasets/betas.xls"
RATINGS_URL = "https://pages.stern.nyu.edu/adamodar/New_Home_Page/datafile/ratings.html"
OECD_URL = (
    "https://www.oecd.org/en/publications/corporate-tax-statistics-2024_9c27d6e8-en/"
    "full-report/statutory-corporate-income-tax-rates_440f9286.html"
)
TE_URL = "https://tradingeconomics.com/bonds"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

DEFAULT_INDUSTRY = "Software (System & Application)"
DEFAULT_COUNTRY = "United States"
MONTH_YEAR = re.compile(
    r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+(?:\d{1,2},\s*)?(20\d\d)"
)

COUNTRY_ALIASES = {
    "united states of america": "united states",
    "us": "united states",
    "usa": "united states",
    "korea": "south korea",
    "republic of korea": "south korea",
    "turkiye": "turkey",
    "czechia": "czech republic",
    "slovak republic": "slovakia",
    "russian federation": "russia",
    "people's republic of china": "china",
    "peoples republic of china": "china",
    "hong kong china": "hong kong",
    "viet nam": "vietnam",
}


def norm_country(name: str) -> str:
    s = str(name).lower().strip()
    s = s.replace("ü", "u").replace("é", "e").replace("ô", "o").replace("ı", "i")
    s = re.sub(r"\(.*?\)", "", s)
    s = re.sub(r"[^a-z' ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return COUNTRY_ALIASES.get(s, s)


def to_float(x) -> float:
    if x is None:
        return float("nan")
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(x).replace(",", ""))
    return float(m.group(0)) if m else float("nan")


def http_get(url: str) -> requests.Response:
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    return r


def find_dates(text: str) -> str | None:
    m = MONTH_YEAR.search(text)
    return f"{m.group(1)} {m.group(2)}" if m else None


# --------------------------------------------------------------------------
# Fetchers (raise on failure so failures are not cached)
# --------------------------------------------------------------------------
@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _fetch_betas() -> dict:
    r = http_get(BETAS_URL)
    sheets = pd.read_excel(io.BytesIO(r.content), sheet_name=None, header=None)
    for name, raw in sheets.items():
        hdr = None
        for i in range(min(40, len(raw))):
            if any(str(v).strip().lower() == "industry name" for v in raw.iloc[i].tolist()):
                hdr = i
                break
        if hdr is None:
            continue
        cols = [str(c).strip() for c in raw.iloc[hdr].tolist()]
        body = raw.iloc[hdr + 1:].copy()
        body.columns = cols
        body = body[body["Industry Name"].notna()]
        body["Industry Name"] = body["Industry Name"].astype(str).str.strip()
        body = body[~body["Industry Name"].str.lower().str.startswith("total market")]

        def pick(pred):
            return next((c for c in cols if pred(c.lower())), None)

        c_beta_u = pick(lambda c: c == "unlevered beta")
        c_beta_u_cash = pick(lambda c: "unlevered beta" in c and "cash" in c)
        c_firms = pick(lambda c: "number of firms" in c)
        c_beta = pick(lambda c: c == "beta")
        c_de = pick(lambda c: c.startswith("d/e"))
        if c_beta_u is None:
            continue
        out = pd.DataFrame({
            "Industry": body["Industry Name"].values,
            "Firms": pd.to_numeric(body[c_firms], errors="coerce").values if c_firms else float("nan"),
            "Levered beta (industry avg)": pd.to_numeric(body[c_beta], errors="coerce").values if c_beta else float("nan"),
            "D/E (industry avg)": pd.to_numeric(body[c_de], errors="coerce").values if c_de else float("nan"),
            "Unlevered beta": pd.to_numeric(body[c_beta_u], errors="coerce").values,
            "Unlevered beta (cash-corrected)": (
                pd.to_numeric(body[c_beta_u_cash], errors="coerce").values if c_beta_u_cash else float("nan")
            ),
        }).dropna(subset=["Unlevered beta"]).reset_index(drop=True)
        head_text = " ".join(str(v) for v in raw.iloc[:hdr].values.ravel() if isinstance(v, str))
        date = find_dates(head_text) or find_dates(r.headers.get("Last-Modified", "") + " ")
        return {
            "df": out,
            "date": date or r.headers.get("Last-Modified", "n/a"),
            "retrieved": dt.datetime.now(),
            "note": head_text[:200],
        }
    raise ValueError("Could not locate the 'Industry Name' header in betas.xls")


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _fetch_bbb() -> dict:
    r = http_get(RATINGS_URL)
    html = r.text
    tables = pd.read_html(io.StringIO(html))
    spread = None
    for t in tables:
        t = t.copy()
        t.columns = [" ".join(map(str, c)) if isinstance(c, tuple) else str(c) for c in t.columns]
        ts = t.astype(str)
        mask = ts.apply(lambda col: col.str.contains("Baa2/BBB", regex=False)).any(axis=1)
        if not mask.any():
            continue
        row = ts[mask].iloc[0]
        spread_cols = [c for c in ts.columns if "spread" in c.lower()]
        for c in spread_cols:
            if "%" in row[c] or re.search(r"\d", row[c]):
                spread = to_float(row[c]) / 100.0
                break
        if spread is None:
            pct = [v for v in row.tolist() if re.fullmatch(r"\s*\d+(\.\d+)?\s*%\s*", v)]
            if pct:
                spread = to_float(pct[-1]) / 100.0
        if spread is not None:
            break
    if spread is None:
        raise ValueError("Could not find the Baa2/BBB spread on the ratings page")
    text = re.sub(r"<[^>]+>", " ", html)
    date = find_dates(text) or r.headers.get("Last-Modified", "n/a")
    return {"spread": spread, "date": date, "retrieved": dt.datetime.now()}


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def _fetch_tax() -> dict:
    r = http_get(OECD_URL)
    tables = pd.read_html(io.StringIO(r.text))
    rates: dict[str, tuple[str, float, int]] = {}
    for t in tables:
        t = t.copy()
        t.columns = [" ".join(map(str, c)) if isinstance(c, tuple) else str(c) for c in t.columns]
        cols = list(t.columns)
        years = [c for c in cols if re.fullmatch(r"\s*(19|20)\d\d\s*", c)]
        if len(years) < 5:
            continue
        years_sorted = sorted(years, key=lambda c: int(c.strip()), reverse=True)
        for _, row in t.iterrows():
            name = str(row.iloc[0]).strip()
            if not name or name.lower() == "nan":
                continue
            for y in years_sorted:
                v = to_float(row[y])
                if v == v:  # not NaN
                    rate = v / 100.0 if v > 1 else v
                    key = norm_country(name)
                    prev = rates.get(key)
                    if prev is None or int(y) > prev[2]:
                        rates[key] = (name, rate, int(y))
                    break
    if not rates:
        raise ValueError("No statutory tax-rate table found on the OECD page")
    latest = max(v[2] for v in rates.values())
    return {"rates": rates, "date": f"Statutory rates, latest year {latest}", "retrieved": dt.datetime.now()}


@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_yields() -> dict:
    r = http_get(TE_URL)
    tables = pd.read_html(io.StringIO(r.text))
    out: dict[str, tuple[str, float, str]] = {}
    for t in tables:
        t = t.copy()
        t.columns = [" ".join(map(str, c)) if isinstance(c, tuple) else str(c) for c in t.columns]
        cols = [c.strip() for c in t.columns]
        yi = next((i for i, c in enumerate(cols) if c.lower().startswith("yield")), None)
        if yi is None:
            continue
        di = next((i for i, c in enumerate(cols) if c.lower() == "date"), None)
        for _, row in t.iterrows():
            name = re.sub(r"\s+", " ", str(row.iloc[0])).strip()
            y = to_float(row.iloc[yi])
            if not name or name.lower() == "nan" or y != y:
                continue
            d = str(row.iloc[di]).strip() if di is not None else ""
            out[norm_country(name)] = (name, y / 100.0, d)
    if not out:
        raise ValueError("No yield table found on Trading Economics")
    return {"yields": out, "retrieved": dt.datetime.now()}


def safe(fetcher):
    """Call a cached fetcher; return (data, error_message)."""
    try:
        return fetcher(), None
    except Exception as e:  # noqa: BLE001 - show any failure to the user
        return None, f"{type(e).__name__}: {e}"


def clear_all() -> None:
    st.cache_data.clear()
    for k in [k for k in st.session_state if str(k).startswith("man_") or str(k).startswith("fs_")]:
        del st.session_state[k]


# --------------------------------------------------------------------------
# Finance calculations
# --------------------------------------------------------------------------
def auto_fc_spread(y_us: float, y_fc: float, s_usd: float) -> float:
    return (1 + y_us + s_usd) * (1 + y_fc) / (1 + y_us) - 1 - y_fc


def compute(beta_u, tax, d, erp, y_us, y_fc, s_usd, s_fc) -> dict:
    de = d / (1 - d)
    beta_l = beta_u * (1 + (1 - tax) * de)
    ke_usd = y_us + beta_l * erp
    kd_usd = y_us + s_usd
    wacc_usd = (1 - d) * ke_usd + d * kd_usd * (1 - tax)
    ke_fc = (1 + ke_usd) * (1 + y_fc) / (1 + y_us) - 1
    kd_fc = y_fc + s_fc
    wacc_fc = (1 - d) * ke_fc + d * kd_fc * (1 - tax)
    return {
        "D/E": de, "beta_l": beta_l,
        "usd": {"rf": y_us, "ke": ke_usd, "spread": s_usd, "kd": kd_usd,
                "kd_at": kd_usd * (1 - tax), "wacc": wacc_usd},
        "fc": {"rf": y_fc, "ke": ke_fc, "spread": s_fc, "kd": kd_fc,
               "kd_at": kd_fc * (1 - tax), "wacc": wacc_fc},
    }


def pct(x: float, digits: int = 2) -> str:
    return "n/a" if x != x else f"{x * 100:.{digits}f}%"


# --------------------------------------------------------------------------
# App
# --------------------------------------------------------------------------
def main() -> None:
    st.set_page_config(page_title="Cost of Equity & WACC: USD vs. Local Currency", layout="wide")
    st.title("Project Cost of Equity & WACC: USD vs. Local Currency")
    st.caption("Industry betas & BBB spread: Damodaran · Tax rates: OECD · 10-year yields: Trading Economics")

    if "tax_basis" not in st.session_state:
        st.session_state["tax_basis"] = "US"

    # ---- Fetch data ----------------------------------------------------
    with st.spinner("Fetching data…"):
        betas, e_beta = safe(_fetch_betas)
        bbb, e_bbb = safe(_fetch_bbb)
        tax, e_tax = safe(_fetch_tax)
        yld, e_yld = safe(_fetch_yields)

    industries = list(betas["df"]["Industry"]) if betas else ["(manual input)"]
    countries = sorted({v[0] for v in yld["yields"].values()}) if yld else [DEFAULT_COUNTRY]
    if DEFAULT_COUNTRY not in countries:
        countries = [DEFAULT_COUNTRY] + countries

    # ---- Sidebar -------------------------------------------------------
    with st.sidebar:
        st.header("Inputs")
        st.button("🔄 Refresh data", on_click=clear_all, help="Clears the cache and re-fetches every source")
        industry = st.selectbox(
            "Industry", industries,
            index=industries.index(DEFAULT_INDUSTRY) if DEFAULT_INDUSTRY in industries else 0,
        )
        country = st.selectbox("Target country", countries, index=countries.index(DEFAULT_COUNTRY))
        erp = st.number_input("Equity risk premium (%)", 0.0, 20.0, 6.5, 0.1, format="%.2f") / 100
        debt_share = st.slider("Target debt share D/(D+E) (%)", 0, 90, 30, 1) / 100
        beta_kind = st.radio(
            "Unlevered beta measure", ["Unlevered beta", "Unlevered beta (cash-corrected)"],
            help="Default follows the assignment: the 'Unlevered beta' column of betas.xls.",
        )

        st.subheader("Project tax rate")
        basis = st.session_state["tax_basis"]
        st.write(f"Using the **{'U.S.' if basis == 'US' else 'selected-country'}** corporate tax rate")
        if st.button("Switch to selected-country rate" if basis == "US" else "Switch to U.S. rate"):
            st.session_state["tax_basis"] = "FC" if basis == "US" else "US"
            st.rerun()

    # ---- Auto values ---------------------------------------------------
    nan = float("nan")
    is_us = norm_country(country) == "united states"
    auto_beta = nan
    if betas:
        row = betas["df"].loc[betas["df"]["Industry"] == industry]
        if not row.empty:
            auto_beta = float(row[beta_kind].iloc[0])
    auto_spread = bbb["spread"] if bbb else nan
    auto_tax_us = tax["rates"].get("united states", (None, nan, 0))[1] if tax else nan
    auto_tax_fc = tax["rates"].get(norm_country(country), (None, nan, 0))[1] if tax else nan
    auto_y_us = yld["yields"].get("united states", (None, nan, ""))[1] if yld else nan
    auto_y_fc = yld["yields"].get(norm_country(country), (None, nan, ""))[1] if yld else nan

    def override(label, auto, key, step=0.01, fmt="%.2f", pct_units=True, minv=-50.0, maxv=100.0, disabled_hint=""):
        """Checkbox + number input; returns the value actually used (decimal)."""
        on = st.checkbox(f"Override {label}", key=f"man_on_{key}")
        shown = (auto * 100 if pct_units else auto) if auto == auto else 0.0
        if on:
            v = st.number_input(label, minv, maxv, float(round(shown, 4)), step, format=fmt, key=f"man_{key}")
            return v / 100 if pct_units else v
        st.caption(f"{label}: **{(f'{shown:.2f}' + ('%' if pct_units else '')) if auto == auto else 'not available – tick override'}**"
                   f"{disabled_hint}")
        return auto

    with st.sidebar:
        st.subheader("Manual overrides")
        beta_u = override("unlevered beta", auto_beta, f"beta_{industry}_{beta_kind}", 0.01, "%.3f", False, 0.0, 5.0)
        tax_us = override("U.S. tax rate (%)", auto_tax_us, "tax_us", 0.1)
        tax_fc = override(f"{country} tax rate (%)", auto_tax_fc, f"tax_fc_{country}", 0.1)
        s_usd = override("USD BBB spread (%)", auto_spread, "spread", 0.01)
        y_us = override("U.S. 10Y yield (%)", auto_y_us, "yus", 0.01)
        y_fc = override(f"{country} 10Y yield (%)", auto_y_fc, f"yfc_{country}", 0.01)

    basis_us = st.session_state["tax_basis"] == "US"
    required = {"unlevered beta": beta_u, "USD BBB spread": s_usd, "U.S. 10Y yield": y_us,
                f"{country} 10Y yield": y_fc,
                ("U.S. tax rate" if basis_us else f"{country} tax rate"): tax_us if basis_us else tax_fc}
    missing = [n for n, v in required.items() if v != v]
    needed_tax = tax_us if basis_us else tax_fc
    if missing:
        st.error("Missing inputs: " + ", ".join(missing) + ". Tick the matching override in the sidebar and enter a value.")
        show_sources(betas, bbb, tax, yld, e_beta, e_bbb, e_tax, e_yld, country, industry)
        st.stop()
    t = needed_tax

    # Foreign spread: auto or manual
    with st.sidebar:
        auto_fs = auto_fc_spread(y_us, y_fc, s_usd)
        fs_on = st.checkbox("Override foreign BBB spread (%)", key="fs_on",
                            help="Off: spread = USD Kd converted by the yield ratio, less the local yield.")
        if fs_on:
            s_fc = st.number_input("Foreign BBB spread (%)", -10.0, 50.0, float(round(auto_fs * 100, 4)), 0.01,
                                   format="%.2f", key="fs_manual") / 100
        else:
            st.number_input("Foreign BBB spread (%) – auto", value=float(round(auto_fs * 100, 4)), disabled=True,
                            format="%.4f", key=f"fs_auto_{auto_fs:.8f}")
            s_fc = auto_fs

    res = compute(beta_u, t, debt_share, erp, y_us, y_fc, s_usd, s_fc)
    u, f = res["usd"], res["fc"]

    # ---- Headline ------------------------------------------------------
    st.subheader(f"{industry} · {country}")
    st.caption(f"Tax rate used: **{pct(t)}** ({'U.S.' if st.session_state['tax_basis'] == 'US' else country}) · "
               f"ERP {pct(erp)} · debt share {pct(debt_share, 0)} · "
               f"levered beta {res['beta_l']:.3f}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Cost of equity – USD", pct(u["ke"]))
    c2.metric(f"Cost of equity – {country}", pct(f["ke"]))
    c3.metric("WACC – USD", pct(u["wacc"]))
    c4.metric(f"WACC – {country}", pct(f["wacc"]), delta=f"{(f['wacc'] - u['wacc']) * 100:+.2f} pp vs USD", delta_color="off")

    # ---- Side-by-side table -------------------------------------------
    labels = [
        ("10Y government yield (risk-free)", "rf"),
        ("Cost of equity (Ke)", "ke"),
        ("BBB spread", "spread"),
        ("Pre-tax cost of debt (Kd)", "kd"),
        ("After-tax cost of debt", "kd_at"),
        ("WACC", "wacc"),
    ]
    common = [
        ("Unlevered beta", f"{beta_u:.3f}", f"{beta_u:.3f}"),
        ("D/E (from debt share)", f"{res['D/E']:.3f}", f"{res['D/E']:.3f}"),
        ("Levered beta", f"{res['beta_l']:.3f}", f"{res['beta_l']:.3f}"),
        ("Equity risk premium", pct(erp), pct(erp)),
        ("Project tax rate", pct(t), pct(t)),
        ("Weight of debt / equity", f"{pct(debt_share, 0)} / {pct(1 - debt_share, 0)}",
         f"{pct(debt_share, 0)} / {pct(1 - debt_share, 0)}"),
    ]
    table = pd.DataFrame(
        [(a, b, c) for a, b, c in common] + [(lbl, pct(u[k]), pct(f[k])) for lbl, k in labels],
        columns=["Item", "USD", f"{country} currency"],
    )
    st.dataframe(table, hide_index=True, use_container_width=True)

    # ---- Assumptions ---------------------------------------------------
    with st.expander("Main assumptions and formulas", expanded=False):
        st.markdown(
            f"""
- **Capital structure:** D/E = d/(1−d). Levered beta = Bu × (1 + (1−t) × D/E) (Hamada).
- **USD:** Ke = y_US + β_L × ERP; Kd = y_US + BBB spread; WACC = (1−d)·Ke + d·Kd·(1−t).
- **Local currency:** the same real project is valued in local currency using the 10-year yields as the
  currency's nominal-rate benchmark: Ke_FC = (1+Ke_USD)·(1+y_FC)/(1+y_US) − 1.
- **Local debt:** Kd_FC = y_FC + local BBB spread. By default the local spread is
  s_FC = (1+y_US+s_USD)·(1+y_FC)/(1+y_US) − 1 − y_FC, so Kd_FC equals the USD Kd converted by the same ratio.
  You can override it manually.
- **Same inputs in both currencies:** the project tax rate, debt share and ERP are identical. The USD ERP is the base;
  no separate country-risk premium is added.
- **Data:** U.S. industry average unlevered betas (not firm-specific), BBB spread for large non-financial firms,
  OECD statutory (combined central + sub-central) tax rates, latest Trading Economics 10-year yields.
- Treat this as a template: confirm the formulas against your class notes.
"""
        )

    # ---- All-industry comparison --------------------------------------
    st.subheader("All-industry comparison")
    if betas:
        rows = []
        for _, r in betas["df"].iterrows():
            b = float(r[beta_kind])
            if b != b:
                continue
            rr = compute(b, t, debt_share, erp, y_us, y_fc, s_usd, s_fc)
            rows.append({
                "Industry": r["Industry"], "Firms": r["Firms"], "Unlevered beta": b,
                "Levered beta": rr["beta_l"],
                "Ke USD": rr["usd"]["ke"], "WACC USD": rr["usd"]["wacc"],
                f"Ke {country}": rr["fc"]["ke"], f"WACC {country}": rr["fc"]["wacc"],
            })
        allind = pd.DataFrame(rows).sort_values("WACC USD", ascending=False).reset_index(drop=True)
        show = allind.copy()
        for c in show.columns:
            if c.startswith(("Ke", "WACC")):
                show[c] = (show[c] * 100).round(2)
        show["Unlevered beta"] = show["Unlevered beta"].round(3)
        show["Levered beta"] = show["Levered beta"].round(3)
        st.caption("Rankings use the settings above (manual beta override applies only to the selected industry). "
                   "Percent columns in %.")
        st.dataframe(show, hide_index=True, use_container_width=True, height=360)
        st.bar_chart((allind.set_index("Industry")[["WACC USD", f"WACC {country}"]] * 100),
                     height=380, y_label="WACC (%)")
    else:
        allind = pd.DataFrame()
        st.info("Industry data unavailable; the comparison needs the Damodaran file (see Sources).")

    # ---- Downloads -----------------------------------------------------
    inputs = pd.DataFrame([
        ("industry", industry), ("country", country), ("unlevered_beta", beta_u), ("tax_rate_used", t),
        ("tax_basis", "US" if st.session_state["tax_basis"] == "US" else "selected country"),
        ("erp", erp), ("debt_share", debt_share), ("us_10y_yield", y_us), (f"fc_10y_yield", y_fc),
        ("usd_bbb_spread", s_usd), ("fc_bbb_spread", s_fc),
        ("fc_spread_manual", bool(fs_on)),
    ], columns=["input", "value"])
    d1, d2, d3 = st.columns(3)
    d1.download_button("⬇ Results (side-by-side) CSV", table.to_csv(index=False).encode(), "wacc_results.csv", "text/csv")
    d2.download_button("⬇ Inputs used CSV", inputs.to_csv(index=False).encode(), "wacc_inputs.csv", "text/csv")
    if not allind.empty:
        d3.download_button("⬇ All-industry CSV", allind.to_csv(index=False).encode(), "wacc_all_industries.csv", "text/csv")

    # ---- Verification --------------------------------------------------
    with st.expander("Calculation checks"):
        checks = {
            "Weights sum to 1": abs((1 - debt_share) + debt_share - 1) < 1e-12,
            "Unlevering levered beta returns Bu": abs(res["beta_l"] / (1 + (1 - t) * res["D/E"]) - beta_u) < 1e-9,
            "USD WACC re-computed": abs(u["wacc"] - ((1 - debt_share) * u["ke"] + debt_share * u["kd"] * (1 - t))) < 1e-12,
            "FC WACC re-computed": abs(f["wacc"] - ((1 - debt_share) * f["ke"] + debt_share * f["kd"] * (1 - t))) < 1e-12,
            "Same yields ⇒ FC equals USD (parity)": abs(
                compute(beta_u, t, debt_share, erp, y_us, y_us, s_usd, auto_fc_spread(y_us, y_us, s_usd))["fc"]["wacc"] - u["wacc"]
            ) < 1e-12,
            "Auto FC Kd = USD Kd × yield ratio": (fs_on or abs(f["kd"] - ((1 + u["kd"]) * (1 + y_fc) / (1 + y_us) - 1)) < 1e-12),
        }
        for k, v in checks.items():
            st.write(("✅ " if v else "❌ ") + k)

    show_sources(betas, bbb, tax, yld, e_beta, e_bbb, e_tax, e_yld, country, industry)


def show_sources(betas, bbb, tax, yld, e_beta, e_bbb, e_tax, e_yld, country, industry) -> None:
    st.subheader("Sources and data dates")
    fmt = lambda d: d["retrieved"].strftime("%Y-%m-%d %H:%M") if d else "–"
    us_d = yld["yields"].get("united states", (None, None, "n/a"))[2] if yld else "n/a"
    fc_d = yld["yields"].get(norm_country(country), (None, None, "n/a"))[2] if yld else "n/a"
    tax_year = ""
    if tax:
        hit = tax["rates"].get(norm_country(country))
        tax_year = f" · {country}: {hit[2]}" if hit else ""
    rows = [
        ("Unlevered betas (Damodaran, U.S. industries)", BETAS_URL,
         betas["date"] if betas else "–", fmt(betas), "OK" if betas else f"FAILED – {e_beta}"),
        ("BBB (Baa2) USD spread (Damodaran)", RATINGS_URL,
         bbb["date"] if bbb else "–", fmt(bbb), "OK" if bbb else f"FAILED – {e_bbb}"),
        ("Corporate tax rates (OECD)", OECD_URL,
         (tax["date"] + tax_year) if tax else "–", fmt(tax), "OK" if tax else f"FAILED – {e_tax}"),
        ("10Y government yields (Trading Economics)", TE_URL,
         f"quote dates: U.S. {us_d} · {country} {fc_d}" if yld else "–", fmt(yld),
         "OK" if yld else f"FAILED – {e_yld}"),
    ]
    st.dataframe(pd.DataFrame(rows, columns=["Source", "URL", "Data date", "Retrieved", "Status"]),
                 hide_index=True, use_container_width=True)
    st.caption("If a source fails or a country is missing, tick the manual override in the sidebar. "
               "Use the Refresh button to re-fetch all sources.")


if __name__ == "__main__":
    main()
