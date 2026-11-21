# Adiabatic flame temperature tool

A web calculator for the adiabatic flame temperature of fuel/oxidizer mixtures,
using [Cantera](https://cantera.org) (chemical equilibrium) and [Streamlit](https://streamlit.io) (web page).

## Inputs

Three settings switch how inputs are entered (defaults: Imperial, excess air, altitude):

- **Units:** Metric (°C, K, bar) or Imperial (°F, °R, psi)
- **Mixture given as:** equivalence ratio φ, or excess air % = (1/φ − 1) × 100
- **Pressure:** absolute; gauge plus an adjustable atmospheric pressure; or altitude
  (FASL in imperial, m ASL in metric) using the standard atmosphere

| Input | Meaning |
|---|---|
| Fuel | Preset fuel or a custom mixture such as `CH4:0.8, H2:0.2` |
| Equivalence ratio φ / Excess air | φ = 1 (0 % excess air) is stoichiometric; φ < 1 lean, > 1 rich |
| Initial temperature | °C or °F |
| Pressure | bar(a)/barg or psia/psig |
| O₂ in oxidizer | 21 % = air, 100 % = pure oxygen (rest N₂) |
| FGR | Flue gas recirculation: recirculated flue gas mass ÷ fresh fuel + air mass |
| FGR temperature | Temperature of the recirculated gas (°C or °F) |

The FGR has the composition of the flame's own equilibrium products, so the calculation
repeats until the flame temperature changes by less than 0.01 K (usually 2–4 rounds).

## Results

- Flame temperature, temperature rise, and (with FGR) the mixed inlet temperature
- Chart of flame temperature vs. equivalence ratio or excess air
- Equilibrium products at the flame (wet)
- **Flue gas analyzer reading:** the products cooled, with radicals recombined into stable species
  (equilibrium among N₂, O₂, CO₂, H₂O, CO, H₂ at 1500 K), shown wet and dry (H₂O removed).
  O₂ and CO₂ are reliable; CO in lean flames depends on the 1500 K assumption. NOx is not predicted.

Note: Streamlit reloads `app.py` automatically when it changes, but not `flame.py`;
restart the server after editing `flame.py`.

`flame.py` always works in SI (K, bar absolute, φ); `app.py` does the unit conversions.

## Files

- `flame.py` – the science: Cantera calculations, no web code. `python flame.py` runs a self-check.
- `app.py` – the web page: inputs, results, chart, products table.
- `requirements.txt` – Python libraries needed (used by hosting services too).

## Run on this PC

```
.venv\Scripts\python.exe -m streamlit run app.py
```

Then open http://localhost:8501.

## Put it online (free)

1. Create a GitHub account and upload this folder as a repository (without `.venv`).
2. Go to https://share.streamlit.io, sign in with GitHub, choose the repository and `app.py`.
3. It builds from `requirements.txt` and gives you a public `*.streamlit.app` link.
