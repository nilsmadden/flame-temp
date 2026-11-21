"""Adiabatic flame temperature calculator — the web page.

Run locally with:  streamlit run app.py

All calculations in flame.py use SI units (K, bar absolute, equivalence ratio).
This file converts the user's inputs to SI and the results back for display.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from flame import FUELS, flame_temperature, sweep_phi, validate_fuel

ATM_BAR = 1.01325           # standard atmosphere [bar]
PSI_PER_BAR = 14.5037738

st.set_page_config(page_title="Adiabatic Flame Temperature", page_icon="🔥", layout="wide")

st.title("Adiabatic flame temperature")
st.caption("Chemical equilibrium calculation with Cantera and the GRI-Mech 3.0 mechanism.")


# ---------------------------------------------------------------- conversions
def phi_to_excess_air(phi: float) -> float:
    """Equivalence ratio -> excess air [%]. Excess air = (1/φ − 1) × 100."""
    return (1.0 / phi - 1.0) * 100.0


def excess_air_to_phi(excess_air: float) -> float:
    return 1.0 / (1.0 + excess_air / 100.0)


def altitude_to_bar(meters: float) -> float:
    """Standard-atmosphere pressure (ISA troposphere, valid up to 11 km)."""
    return ATM_BAR * (1.0 - 2.25577e-5 * meters) ** 5.25588


def to_kelvin(value: float) -> float:
    """°C (metric) or °F (imperial) -> K. `metric` is set in the sidebar below."""
    return value + 273.15 if metric else (value - 32.0) / 1.8 + 273.15


# ---------------------------------------------------------------- inputs
with st.sidebar:
    st.header("Settings")
    units = st.radio("Units", ["Metric", "Imperial"], index=1, horizontal=True)
    mix_mode = st.radio("Mixture given as", ["Equivalence ratio", "Excess air"], index=1, horizontal=True)
    p_mode = st.radio("Pressure", ["Absolute", "Gauge", "Altitude"], index=2, horizontal=True,
                      help="Altitude: open to the atmosphere at that elevation (standard atmosphere).")
    metric = units == "Metric"

    st.header("Inputs")

    fuel_choice = st.selectbox("Fuel", [*FUELS, "Custom mixture…"])
    if fuel_choice == "Custom mixture…":
        fuel = st.text_input("Fuel composition (mole fractions)", "CH4:0.8, H2:0.2",
                             help="GRI-Mech 3.0 species names, e.g. CH4, C2H6, C3H8, H2, CO, CO2, N2.")
    else:
        fuel = FUELS[fuel_choice]

    # --- mixture: equivalence ratio or excess air (φ = 0.2 … 4 either way)
    if mix_mode == "Equivalence ratio":
        phi = st.number_input("Equivalence ratio φ", min_value=0.2, max_value=4.0, value=1.0, step=0.05,
                              help="1 = stoichiometric, below 1 = lean (excess air), above 1 = rich (excess fuel).")
        st.caption(f"= {phi_to_excess_air(phi):+.1f} % excess air")
    else:
        excess_air = st.number_input("Excess air [%]", min_value=-75.0, max_value=400.0, value=0.0, step=5.0,
                                     help="Air supplied above what is needed to burn the fuel completely. "
                                          "0 % = stoichiometric, 20 % = 1.2× the needed air, "
                                          "negative = too little air (rich). With enriched oxygen this is "
                                          "excess oxidizer.")
        phi = excess_air_to_phi(excess_air)
        st.caption(f"= equivalence ratio φ {phi:.3f}")

    # --- initial temperature (stored as K)
    T_unit = "°C" if metric else "°F"
    T_min, T_max = (-73.0, 1726.0) if metric else (-99.0, 3140.0)
    T0 = to_kelvin(st.number_input(f"Fuel/air temperature [{T_unit}]", min_value=T_min, max_value=T_max,
                                   value=25.0 if metric else 77.0, step=10.0, key=f"T0_{units}",
                                   help="Temperature of the fresh fuel and oxidizer."))

    # --- pressure (stored as bar absolute)
    p_unit = "bar" if metric else "psi"
    to_bar = 1.0 if metric else 1.0 / PSI_PER_BAR
    atm_default = ATM_BAR if metric else ATM_BAR * PSI_PER_BAR
    if p_mode == "Absolute":
        label = "Pressure [bar(a)]" if metric else "Pressure [psia]"
        P_in = st.number_input(label, min_value=0.01 / to_bar, max_value=200.0 / to_bar,
                               value=atm_default, step=0.5 if metric else 5.0, format="%.5g",
                               key=f"P_abs_{units}")
        P_bar = P_in * to_bar
    elif p_mode == "Altitude":
        if metric:
            alt = st.number_input("Altitude [m ASL]", min_value=-500.0, max_value=11000.0,
                                  value=0.0, step=100.0, key="alt_m")
            P_bar = altitude_to_bar(alt)
            st.caption(f"= {P_bar:.4g} bar(a)")
        else:
            alt = st.number_input("Altitude [FASL]", min_value=-1500.0, max_value=36000.0,
                                  value=0.0, step=500.0, key="alt_ft", help="Feet above sea level.")
            P_bar = altitude_to_bar(alt * 0.3048)
            st.caption(f"= {P_bar * PSI_PER_BAR:.4g} psia")
    else:
        label = "Pressure [barg]" if metric else "Pressure [psig]"
        P_in = st.number_input(label, min_value=-atm_default, max_value=200.0 / to_bar,
                               value=0.0, step=0.5 if metric else 5.0, format="%.5g",
                               key=f"P_gauge_{units}")
        atm = st.number_input(f"Atmospheric pressure [{p_unit}]", min_value=0.3 / to_bar,
                              max_value=1.2 / to_bar, value=atm_default, format="%.5g",
                              key=f"atm_{units}",
                              help="Standard sea level by default. Lower it for high altitude.")
        P_bar = (P_in + atm) * to_bar
        abs_label = f"{P_bar:.4g} bar(a)" if metric else f"{P_bar * PSI_PER_BAR:.4g} psia"
        st.caption(f"= {abs_label}")

    o2 = st.slider("O₂ in oxidizer [%]", min_value=10, max_value=100, value=21,
                   help="21 % = air. 100 % = pure oxygen. The rest is nitrogen.")

    # --- flue gas recirculation
    fgr = st.number_input("FGR [%]", min_value=0.0, max_value=200.0, value=0.0, step=5.0,
                          help="Flue gas recirculation: mass of recirculated flue gas per mass of "
                               "fresh fuel + air. Its composition is this flame's equilibrium products.")
    T_fgr = to_kelvin(st.number_input(f"FGR temperature [{T_unit}]", min_value=T_min, max_value=T_max,
                                      value=150.0 if metric else 300.0, step=10.0, key=f"Tfgr_{units}",
                                      disabled=fgr == 0))
    if fgr > 0:
        st.caption(f"= {100 * fgr / (100 + fgr):.1f} % of the total flue gas is recirculated")

# ---------------------------------------------------------------- validation
error = validate_fuel(fuel)
if error:
    st.error(error)
    st.stop()
if P_bar < 0.01:
    st.error("The absolute pressure must be above 0.01 bar (0.15 psia).")
    st.stop()


@st.cache_data(show_spinner=False, max_entries=500)
def cached_result(fuel, phi, T0, P_bar, o2, fgr, T_fgr):
    return flame_temperature(fuel, phi, T0, P_bar, o2, fgr, T_fgr)


@st.cache_data(show_spinner=False, max_entries=200)
def cached_sweep(fuel, T0, P_bar, o2, lo, hi, fgr, T_fgr):
    return sweep_phi(fuel, T0, P_bar, o2, lo, hi, fgr, T_fgr)


try:
    result = cached_result(fuel, phi, T0, P_bar, o2, fgr, T_fgr)
except Exception as exc:  # Cantera can fail on extreme inputs
    st.error(f"The calculation did not converge for these inputs: {exc}")
    st.stop()


# ---------------------------------------------------------------- display units
def show_T(kelvin: float) -> float:
    """K -> °C (metric) or °F (imperial)."""
    return kelvin - 273.15 if metric else (kelvin - 273.15) * 1.8 + 32.0


abs_unit = "K" if metric else "°R"
abs_factor = 1.0 if metric else 1.8           # K -> °R
diff_factor = 1.0 if metric else 1.8          # temperature difference K -> °F

# ---------------------------------------------------------------- results
cols = st.columns(4 if fgr > 0 else 3)
cols[0].metric("Flame temperature", f"{show_T(result.T_ad):,.0f} {T_unit}")
cols[1].metric("Absolute", f"{result.T_ad * abs_factor:,.0f} {abs_unit}")
cols[2].metric("Temperature rise", f"{(result.T_ad - result.T_mix) * diff_factor:,.0f} {T_unit}",
               help="Flame temperature minus the temperature of the unburned mixture.")
if fgr > 0:
    cols[3].metric("Mixed inlet (fuel/air + FGR)", f"{show_T(result.T_mix):,.0f} {T_unit}",
                   help="Temperature after mixing fresh fuel/air with the recirculated flue gas, before burning.")

left, right = st.columns([3, 2])

with left:
    x_name = "Equivalence ratio φ" if mix_mode == "Equivalence ratio" else "Excess air [%]"
    st.subheader(f"Flame temperature vs. {mix_mode.lower()}")
    lo, hi = min(0.4, phi), max(2.0, phi)
    with st.spinner("Calculating curve…"):
        phis, temps = cached_sweep(fuel, T0, P_bar, o2, lo, hi, fgr, T_fgr)

    if mix_mode == "Equivalence ratio":
        xs, x_point, x_fmt = phis, phi, "φ = %{x:.2f}"
    else:
        xs, x_point, x_fmt = [phi_to_excess_air(p) for p in phis], phi_to_excess_air(phi), "%{x:+.0f} % excess air"
    ys = [show_T(t) for t in temps]
    hover = f"{x_fmt}<br>%{{y:,.0f}} {T_unit}<extra></extra>"

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", line=dict(width=3), hovertemplate=hover))
    fig.add_trace(go.Scatter(x=[x_point], y=[show_T(result.T_ad)], mode="markers",
                             marker=dict(size=12), hovertemplate=hover))
    fig.update_layout(xaxis_title=x_name, yaxis_title=f"Temperature [{T_unit}]",
                      showlegend=False, height=420, margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, use_container_width=True)

with right:
    st.subheader("Equilibrium products at flame")
    df = pd.DataFrame({"Species": list(result.products),
                       "Mole fraction [%]": [100 * x for x in result.products.values()]})
    st.dataframe(df, hide_index=True, use_container_width=True,
                 column_config={"Mole fraction [%]": st.column_config.NumberColumn(format="%.3f")})
    st.caption("Wet basis, at the flame temperature. Species above 0.01 % shown.")


# ---------------------------------------------------------------- analyzer reading
def analyzer_value(x: float) -> str:
    """Percent for major gases, ppm below 0.1 % — the way combustion analyzers report."""
    return f"{100 * x:.2f} %" if x >= 1e-3 else f"{1e6 * x:,.0f} ppm"


st.subheader("Flue gas analyzer reading")
if result.flue_dry is None:
    st.info("Not available: this mixture is so rich that the cooled gas would contain soot, "
            "which this tool does not model.")
else:
    dry = result.flue_dry
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("O₂ (dry)", f"{100 * dry.get('O2', 0):.2f} %")
    m2.metric("CO₂ (dry)", f"{100 * dry.get('CO2', 0):.2f} %")
    m3.metric("CO (dry)", analyzer_value(dry.get("CO", 0)))
    m4.metric("H₂O (wet)", f"{100 * result.flue_wet.get('H2O', 0):.1f} %",
              help="Water vapour in the flue gas before the analyzer dries the sample.")

    order = ["O2", "CO2", "CO", "H2", "N2", "AR", "H2O"]
    rows = [s for s in order if result.flue_wet.get(s, 0) > 0]
    flue_df = pd.DataFrame({
        "Species": rows,
        "Wet": [analyzer_value(result.flue_wet[s]) for s in rows],
        "Dry": [analyzer_value(dry[s]) if s in dry else "—" for s in rows],
    })
    st.dataframe(flue_df, hide_index=True)
    st.caption("Cooled flue gas: radicals (OH, H, O…) recombined into stable species. **Dry** removes "
               "the water and rescales the rest, as an analyzer reads after drying the sample. "
               "NOx is not shown: it depends on reaction speed and residence time, which equilibrium "
               "cannot predict.")

with st.expander("Assumptions"):
    st.markdown(
        """
- **Adiabatic, constant pressure:** no heat is lost; enthalpy and pressure stay constant (`equilibrate("HP")`).
- **Chemical equilibrium:** includes dissociation (CO, H₂, OH, H, O, NO…), so results are lower than
  "complete combustion" textbook estimates, especially near φ = 1 and with pure oxygen.
- **Gas phase only, ideal gas:** no soot or condensed water. Very rich mixtures may form soot in reality.
- **Oxidizer:** O₂ + N₂ only (air approximated as 21 % O₂ / 79 % N₂, no argon).
- **Excess air:** defined as (1/φ − 1) × 100 %, i.e. relative to the stoichiometric amount of oxidizer.
- **Gauge pressure:** converted to absolute by adding the atmospheric pressure you set
  (standard: 1.01325 bar = 14.696 psi).
- **Altitude:** pressure from the International Standard Atmosphere,
  P = 1.01325 bar × (1 − 2.25577×10⁻⁵ × h[m])^5.25588, valid up to 11 km (36,000 ft).
- **FGR rate:** mass of recirculated flue gas ÷ mass of fresh fuel + oxidizer. The recirculated gas has the
  same composition as the equilibrium products shown in the table (including CO, OH etc.), at the FGR temperature.
  Because FGR changes those products, the calculation repeats until the flame temperature changes by
  less than 0.01 K. Water in the FGR is treated as vapour even below its dew point.
- **Analyzer reading:** the burned gas's atoms re-settled into stable species only (N₂, O₂, CO₂, H₂O, CO, H₂),
  at chemical equilibrium at 1500 K (2240 °F) — roughly where CO/H₂ reactions freeze as flue gas cools.
  Lean mixtures give near-complete combustion (CO of a few ppm); real burners often show more CO because of
  imperfect mixing. Dry basis: x_dry = x_wet ÷ (1 − x_H₂O), assuming all water is removed (real analyzers
  leave a little). FGR does not change the reading, because it adds no new atoms.
- **Chemistry:** GRI-Mech 3.0 thermodynamic data, intended for natural-gas-type fuels.
"""
    )
