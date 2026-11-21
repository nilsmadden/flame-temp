"""Adiabatic flame temperature calculations with Cantera.

No web code in here, so the science can be tested on its own:
    python flame.py
"""

from dataclasses import dataclass

import cantera as ct

MECHANISM = "gri30.yaml"  # GRI-Mech 3.0: natural-gas chemistry, 53 species

# Display name -> Cantera composition string (all species exist in GRI-Mech 3.0)
FUELS = {
    "Methane (CH₄)": "CH4:1",
    "Natural gas (typical)": "CH4:0.93, C2H6:0.04, C3H8:0.01, N2:0.01, CO2:0.01",
    "Ethane (C₂H₆)": "C2H6:1",
    "Propane (C₃H₈)": "C3H8:1",
    "Ethylene (C₂H₄)": "C2H4:1",
    "Acetylene (C₂H₂)": "C2H2:1",
    "Hydrogen (H₂)": "H2:1",
    "Carbon monoxide (CO)": "CO:1",
    "Methanol (CH₃OH)": "CH3OH:1",
}


# Cooled flue gas: only the stable species a stack sample contains once radicals have
# recombined. Their mix is settled by equilibrium at QUENCH_T, roughly where the
# CO/H2 reactions become too slow to continue as the gas cools.
FLUE_SPECIES = ["N2", "O2", "CO2", "H2O", "CO", "H2", "AR"]
QUENCH_T = 1500.0  # K


@dataclass
class FlameResult:
    T_ad: float                    # adiabatic flame temperature [K]
    products: dict[str, float]     # flame equilibrium: species -> mole fraction, wet (major species only)
    T_mix: float                   # temperature of fresh reactants + FGR after mixing, before burning [K]
    iterations: int = 0            # FGR loop iterations needed (0 = no FGR)
    flue_wet: dict[str, float] | None = None   # cooled flue gas, wet basis (None if not possible)
    flue_dry: dict[str, float] | None = None   # cooled flue gas, dry basis (H2O removed)


def _oxidizer(o2_percent: float) -> dict[str, float]:
    """Oxidizer as O2 diluted with N2 (21 % = air, 100 % = pure oxygen)."""
    x = o2_percent / 100.0
    return {"O2": x, "N2": 1.0 - x}


def _new_gas() -> ct.Solution:
    # A fresh object per call: Cantera objects are not safe to share
    # between several website visitors calculating at the same time.
    return ct.Solution(MECHANISM)


def _solve(gas: ct.Solution, fuel: str, phi: float, T0: float, P_bar: float,
           o2_percent: float, fgr_percent: float, T_fgr: float,
           Y_products_guess=None, tol: float = 0.01, max_iter: int = 100):
    """Core calculation, with optional flue gas recirculation (FGR).

    FGR rate = mass of recirculated flue gas / mass of fresh fuel + oxidizer.
    The recirculated gas has the composition of this flame's own equilibrium
    products, at temperature T_fgr. Since adding FGR changes those products,
    the calculation repeats until the flame temperature stops changing.

    Leaves `gas` in the burned (equilibrium) state.
    Returns (T_mix, products mass fractions, iterations).
    """
    P = P_bar * 1e5
    gas.TP = T0, P
    gas.set_equivalence_ratio(phi, fuel, _oxidizer(o2_percent))
    Y_fresh, h_fresh = gas.Y.copy(), gas.enthalpy_mass

    if fgr_percent <= 0:
        gas.equilibrate("HP")
        return T0, gas.Y.copy(), 0

    r = fgr_percent / 100.0
    if Y_products_guess is None:          # first guess: products without FGR
        gas.equilibrate("HP")
        Y_products_guess = gas.Y.copy()
    Y_p, T_old = Y_products_guess, None

    for i in range(1, max_iter + 1):
        gas.TPY = T_fgr, P, Y_p                       # FGR stream (products, frozen, at T_fgr)
        h_fgr = gas.enthalpy_mass
        Y_mix = (Y_fresh + r * Y_p) / (1.0 + r)       # mass-weighted mixing
        h_mix = (h_fresh + r * h_fgr) / (1.0 + r)
        gas.HPY = h_mix, P, Y_mix                     # mixed, unburned
        T_mix = gas.T
        gas.equilibrate("HP")                         # burn
        Y_p = gas.Y.copy()
        if T_old is not None and abs(gas.T - T_old) < tol:
            return T_mix, Y_p, i
        T_old = gas.T
    raise RuntimeError("FGR calculation did not converge")


def flame_temperature(fuel: str, phi: float, T0: float, P_bar: float,
                      o2_percent: float = 21.0, fgr_percent: float = 0.0,
                      T_fgr: float = 423.15, min_fraction: float = 1e-4) -> FlameResult:
    """Equilibrium (constant enthalpy and pressure) flame temperature and products.

    fuel: Cantera composition string, e.g. "CH4:1" or "CH4:0.8, H2:0.2"
    phi: equivalence ratio, T0: fresh fuel/oxidizer temperature [K], P_bar: pressure [bar abs]
    fgr_percent: FGR mass relative to fresh fuel + oxidizer [%], T_fgr: FGR temperature [K]
    """
    gas = _new_gas()
    T_mix, _, iterations = _solve(gas, fuel, phi, T0, P_bar, o2_percent, fgr_percent, T_fgr)
    products = {
        name: x for name, x in zip(gas.species_names, gas.X) if x >= min_fraction
    }
    products = dict(sorted(products.items(), key=lambda kv: kv[1], reverse=True))
    flue_wet = _cooled_flue_gas(gas)
    flue_dry = None
    if flue_wet is not None:
        # Dry basis, as an analyzer reads after condensing out the water:
        # remove H2O and rescale the rest so it adds up to 100 %.
        x_h2o = flue_wet.get("H2O", 0.0)
        flue_dry = {name: x / (1.0 - x_h2o) for name, x in flue_wet.items() if name != "H2O"}
    return FlameResult(T_ad=gas.T, products=products, T_mix=T_mix, iterations=iterations,
                       flue_wet=flue_wet, flue_dry=flue_dry)


def _cooled_flue_gas(burned: ct.Solution) -> dict[str, float] | None:
    """Composition of the flue gas after cooling, as an analyzer would sample it.

    Keeps the burned gas's atoms (C, H, O, N, Ar) but lets them settle into stable
    species only (no radicals such as OH, H, O), at chemical equilibrium at QUENCH_T.
    NO is left out: real NOx depends on reaction speed and residence time, which an
    equilibrium tool cannot predict.

    Returns None if the gas is too rich to fit these species (would form soot).
    """
    # Atoms of each element per mole of burned gas
    atoms = {el: sum(x * burned.n_atoms(k, el) for k, x in enumerate(burned.X))
             for el in ("C", "H", "O", "N", "Ar")}

    # Starting guess built from those atoms: C as CO, H as H2, N as N2, Ar as AR, leftover O as O2
    o_left = atoms.get("O", 0.0) - atoms.get("C", 0.0)
    if o_left < -1e-12:
        return None  # not enough oxygen even for CO: soot territory
    guess = {"CO": atoms.get("C", 0.0), "H2": atoms.get("H", 0.0) / 2, "N2": atoms.get("N", 0.0) / 2,
             "AR": atoms.get("Ar", 0.0), "O2": max(o_left, 0.0) / 2}
    guess = {k: v for k, v in guess.items() if v > 0}

    flue = ct.Solution(thermo="ideal-gas", species=[_SPECIES[n] for n in FLUE_SPECIES])
    flue.TPX = QUENCH_T, burned.P, guess
    flue.equilibrate("TP")
    return {name: x for name, x in zip(flue.species_names, flue.X) if x > 0}


_SPECIES = {s.name: s for s in ct.Species.list_from_file(MECHANISM)}


def sweep_phi(fuel: str, T0: float, P_bar: float, o2_percent: float,
              phi_min: float, phi_max: float, fgr_percent: float = 0.0,
              T_fgr: float = 423.15, n: int = 60) -> tuple[list[float], list[float]]:
    """Flame temperature over a range of equivalence ratios (for the chart)."""
    gas = _new_gas()
    phis, temps, Y_guess = [], [], None
    for i in range(n):
        phi = phi_min + (phi_max - phi_min) * i / (n - 1)
        # the previous point's products are a good starting guess for the FGR loop
        _, Y_guess, _ = _solve(gas, fuel, phi, T0, P_bar, o2_percent, fgr_percent, T_fgr, Y_guess)
        phis.append(phi)
        temps.append(gas.T)
    return phis, temps


def validate_fuel(fuel: str) -> str | None:
    """Return an error message if the composition string is not usable, else None."""
    gas = _new_gas()
    try:
        gas.TPX = 300, ct.one_atm, fuel
    except ct.CanteraError:
        return ("Could not read that fuel. Use GRI-Mech 3.0 species names like "
                "'CH4:0.8, H2:0.2'.")
    # Oxygen needed to burn it completely (moles O2 per mole of fuel mixture)
    o2_demand = sum(
        x * (gas.n_atoms(s, "C") + gas.n_atoms(s, "H") / 4 - gas.n_atoms(s, "O") / 2)
        for s, x in zip(gas.species_names, gas.X) if x > 0
    )
    if o2_demand <= 1e-6:
        return "That mixture cannot burn: it needs no oxygen (e.g. it is all N₂, CO₂ or H₂O)."
    return None


if __name__ == "__main__":
    # Quick self-check against well-known textbook values (stoichiometric, 298 K, 1 atm, air)
    for name, expected in [("Methane (CH₄)", 2226), ("Propane (C₃H₈)", 2267),
                           ("Hydrogen (H₂)", 2390)]:
        r = flame_temperature(FUELS[name], phi=1.0, T0=298.15, P_bar=1.01325)
        print(f"{name:20s} T_ad = {r.T_ad:7.1f} K   (literature ≈ {expected} K)")
