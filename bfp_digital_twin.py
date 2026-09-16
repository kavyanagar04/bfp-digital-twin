"""
bfp_digital_twin.py
===================
Digital twin core for a BOILER FEED PUMP (BFP) in a thermal power plant.

A pump twin has two coupled halves, and this script builds both:

  A. MECHANICAL CORE (ANSYS MAPDL, via PyMAPDL)
     A rotordynamic finite-element model of the multistage BFP rotor:
     a BEAM188 shaft carrying lumped impeller masses, supported on
     COMBI214 journal bearings, spun with CORIOLIS enabled.
       1. Modal        -> lateral critical speeds (API 610 separation margin)
       2. Campbell     -> critical speeds vs shaft speed, whirl direction
       3. Harmonic     -> synchronous unbalance response -> FRF CSV
       4. SPMWRITE     -> LTI state-space ROM (.spm) for ANSYS Twin Builder

  B. HYDRAULIC / PERFORMANCE CORE (pure NumPy, no license needed)
     Head-flow-efficiency-power model with affinity laws and three
     degradation modes (impeller wear, suction strainer fouling,
     bearing degradation) -> pump_curves.csv, degradation_sweep.csv

Run the whole thing on a machine with a licensed MAPDL:
    python bfp_digital_twin.py
Run only the license-free hydraulic half (works anywhere):
    python bfp_digital_twin.py --no-mapdl

Requires: ansys-mapdl-core, numpy   (numpy only for --no-mapdl)
"""

import argparse
import csv
import math
import os

import numpy as np

# ---------------------------------------------------------------------------
# 1. PARAMETERS  (single source of truth - edit here, not in the functions)
# ---------------------------------------------------------------------------

# --- Rotor geometry / material -------------------------------------------
SHAFT_LEN = 1.20          # m      bearing-to-bearing span
SHAFT_DIA = 0.100         # m      shaft outer diameter
N_ELEM = 24               # -      beam elements along the shaft
E_MOD = 2.0e11            # Pa     steel Young's modulus
POISSON = 0.30            # -
DENSITY = 7850.0          # kg/m3

# --- Impellers as lumped masses (4-stage rotor) ---------------------------
N_STAGES = 4
IMP_MASS = 25.0           # kg     per impeller (wetted)
IMP_IT = 0.35             # kg.m2  transverse (diametral) inertia
IMP_IP = 0.60             # kg.m2  polar (spin) inertia

# --- Journal bearings -----------------------------------------------------
BRG_K = 2.0e8             # N/m    direct stiffness (both directions)
BRG_C = 1.5e4             # N.s/m  direct damping
BRG_KXY = 0.0             # N/m    cross-coupled stiffness (set >0 to probe
                          #        rotordynamic instability)

# --- Operating point ------------------------------------------------------
RPM_RATED = 3000.0        # rev/min  50 Hz, 2-pole, direct drive
CAMPBELL_RPM = [0.0, 750.0, 1500.0, 2250.0, 3000.0, 3750.0]
N_MODES = 10

# --- Unbalance excitation (ISO 1940 grade G2.5 on a 100 kg rotor) ---------
# U = G * M / omega  ->  eccentricity * mass, in kg.m
ISO_GRADE = 2.5e-3        # mm/s -> m/s (G2.5)
ROTOR_MASS = 130.0        # kg   total rotating mass (shaft + impellers)
HARM_FREQ_MIN = 5.0       # Hz
HARM_FREQ_MAX = 150.0     # Hz
HARM_SUBSTEPS = 145

# --- Hydraulic design point (mid-size single-body BFP, per stage x4) -----
Q_BEP = 0.050             # m3/s   180 m3/h  best-efficiency flow
H_BEP = 220.0             # m      total rated head (4 stages x 55 m)
ETA_BEP = 0.82            # -      hydraulic efficiency at BEP
RHO_WATER = 917.0         # kg/m3  feedwater at ~160 degC
G = 9.81                  # m/s2
NPSH_R_BEP = 4.5          # m      required NPSH at BEP

OUT_DIR = "twin_outputs"


# ---------------------------------------------------------------------------
# 2. MECHANICAL CORE - model build
# ---------------------------------------------------------------------------

def build_rotor(mapdl):
    """Build the BFP rotor FE model: shaft, impellers, bearings."""
    mapdl.clear()
    mapdl.prep7()
    mapdl.units("SI")

    # --- material ---------------------------------------------------------
    mapdl.mp("EX", 1, E_MOD)
    mapdl.mp("PRXY", 1, POISSON)
    mapdl.mp("DENS", 1, DENSITY)

    # --- shaft: BEAM188, circular solid section --------------------------
    mapdl.et(1, 188)
    mapdl.keyopt(1, 3, 3)          # cubic shape function (better for rotors)
    mapdl.sectype(1, "BEAM", "CSOLID")
    mapdl.secdata(SHAFT_DIA / 2.0)

    dx = SHAFT_LEN / N_ELEM
    for i in range(N_ELEM + 1):
        mapdl.n(i + 1, i * dx, 0.0, 0.0)

    mapdl.type(1)
    mapdl.mat(1)
    mapdl.secnum(1)
    for i in range(1, N_ELEM + 1):
        mapdl.e(i, i + 1)

    # --- impellers: MASS21 at equally spaced interior nodes --------------
    mapdl.et(2, 21)
    mapdl.keyopt(2, 3, 0)          # 3-D mass with rotary inertia
    mapdl.r(2, IMP_MASS, IMP_MASS, IMP_MASS, IMP_IP, IMP_IT, IMP_IT)

    imp_nodes = []
    for s in range(1, N_STAGES + 1):
        x = SHAFT_LEN * s / (N_STAGES + 1)
        nd = int(round(x / dx)) + 1
        imp_nodes.append(nd)
        mapdl.type(2)
        mapdl.real(2)
        mapdl.e(nd)

    # --- rotating component (needed by CORIOLIS / CMOMEGA) ---------------
    mapdl.esel("S", "TYPE", "", 1)
    mapdl.esel("A", "TYPE", "", 2)
    mapdl.cm("ROTOR", "ELEM")
    mapdl.allsel()

    # --- bearings: COMBI214 in the YZ plane (rotor axis = X) -------------
    mapdl.et(3, 214)
    mapdl.keyopt(3, 2, 1)          # element lies in the YZ plane
    mapdl.keyopt(3, 3, 1)          # no rotational dof
    # R: K11, K22, C11, C22, K12, K21
    mapdl.r(3, BRG_K, BRG_K, BRG_C, BRG_C, BRG_KXY, -BRG_KXY)

    brg_nodes = [1, N_ELEM + 1]
    ground = []
    for j, nd in enumerate(brg_nodes):
        gnd = 1000 + j
        mapdl.n(gnd, (nd - 1) * dx, 0.0, 0.0)
        mapdl.type(3)
        mapdl.real(3)
        mapdl.e(nd, gnd)
        ground.append(gnd)

    # --- boundary conditions ---------------------------------------------
    for gnd in ground:
        mapdl.d(gnd, "ALL", 0.0)               # bearing housings grounded
    mapdl.d(1, "UX", 0.0)                      # axial restraint at NDE
    mapdl.d(1, "ROTX", 0.0)                    # spin dof handled by CORIOLIS
    mapdl.allsel()
    mapdl.finish()

    mid_node = N_ELEM // 2 + 1
    return {"imp_nodes": imp_nodes, "brg_nodes": brg_nodes,
            "mid_node": mid_node, "dx": dx}


# ---------------------------------------------------------------------------
# 3. ANALYSIS 1 - modal / critical speeds at rated speed
# ---------------------------------------------------------------------------

def run_modal(mapdl, rpm=RPM_RATED):
    """Damped modal analysis with gyroscopics at a given shaft speed."""
    spin = rpm * 2.0 * math.pi / 60.0

    mapdl.slashsolu()
    mapdl.antype("MODAL")
    mapdl.modopt("QRDAMP", N_MODES, 0.0, 5000.0, "", "ON")
    mapdl.mxpand(N_MODES, "", "", "YES")
    mapdl.coriolis("ON", "", "", "ON")         # stationary reference frame
    mapdl.cmomega("ROTOR", spin, 0.0, 0.0)
    mapdl.solve()
    mapdl.finish()

    mapdl.post1()
    freqs = mapdl.post_processing.time_values
    print(f"\n--- Critical speeds at {rpm:.0f} rpm "
          f"(running = {rpm/60:.1f} Hz) ---")
    for i, f in enumerate(freqs, start=1):
        margin = (f / (rpm / 60.0) - 1.0) * 100.0 if rpm > 0 else float("nan")
        print(f"  mode {i:2d}: {f:9.2f} Hz   "
              f"separation from 1x = {margin:+7.1f} %")
    print("  API 610 wants the separation margin outside -20 % .. +20 %.")
    mapdl.finish()
    return list(freqs)


# ---------------------------------------------------------------------------
# 4. ANALYSIS 2 - Campbell diagram
# ---------------------------------------------------------------------------

def run_campbell(mapdl, rpm_list=None):
    """Multi-load-step modal solve -> Campbell diagram / critical speeds."""
    rpm_list = rpm_list or CAMPBELL_RPM

    mapdl.slashsolu()
    mapdl.antype("MODAL")
    mapdl.modopt("QRDAMP", N_MODES, 0.0, 5000.0, "", "ON")
    mapdl.mxpand(N_MODES, "", "", "YES")
    mapdl.coriolis("ON", "", "", "ON")

    for i, rpm in enumerate(rpm_list, start=1):
        spin = rpm * 2.0 * math.pi / 60.0
        mapdl.cmomega("ROTOR", spin, 0.0, 0.0)
        mapdl.solve()
    mapdl.finish()

    mapdl.post1()
    # PRCAMP/PLCAMP need the spin-axis direction and a unit multiplier:
    # SPINOPT=RPM, option 1 = ignore rigid-body modes
    mapdl.run("/POST1")
    mapdl.run("PLCAMP,ON,1.0,RPM,,ROTOR")
    mapdl.run("PRCAMP,ON,1.0,RPM,,ROTOR")
    print("\n--- Campbell diagram written (see PRCAMP table above) ---")
    print("  Intersections of the 1x line with a forward-whirl branch")
    print("  are the critical speeds to keep out of the operating range.")
    mapdl.finish()


# ---------------------------------------------------------------------------
# 5. ANALYSIS 3 - synchronous unbalance response -> FRF CSV
# ---------------------------------------------------------------------------

def run_unbalance_harmonic(mapdl, nodes, out_csv):
    """Harmonic sweep with a co-rotating unbalance force (forward whirl)."""
    # ISO 1940 G2.5: permissible eccentricity e = G / omega_rated
    omega_rated = RPM_RATED * 2.0 * math.pi / 60.0
    ecc = ISO_GRADE / omega_rated                  # m
    unbalance = ecc * ROTOR_MASS                   # kg.m  (applied as m*e)
    print(f"\nUnbalance applied: e = {ecc*1e6:.1f} micron, "
          f"m*e = {unbalance*1e3:.2f} g.m")

    mid = nodes["mid_node"]

    mapdl.slashsolu()
    mapdl.antype("HARMIC")
    mapdl.hropt("FULL")
    mapdl.hrout("OFF")                             # amplitude / phase output
    mapdl.coriolis("ON", "", "", "ON")
    mapdl.run(f"SYNCHRO,1.0,ROTOR")                # excitation = 1x spin
    mapdl.harfrq(HARM_FREQ_MIN, HARM_FREQ_MAX)
    mapdl.nsubst(HARM_SUBSTEPS)
    mapdl.kbc(1)
    mapdl.dmprat(0.02)                             # 2 % structural damping

    # Rotating force: real part on Y, imaginary part on Z -> forward whirl.
    # With SYNCHRO active MAPDL scales m*e by omega^2 automatically.
    mapdl.f(mid, "FY", unbalance, 0.0)
    mapdl.f(mid, "FZ", 0.0, unbalance)
    mapdl.solve()
    mapdl.finish()

    # --- extract the FRF at the mid-span and at one bearing --------------
    mapdl.post26()
    mapdl.numvar(20)
    mapdl.nsol(2, mid, "U", "Y", "MID_UY")
    mapdl.nsol(3, mid, "U", "Z", "MID_UZ")
    mapdl.nsol(4, nodes["brg_nodes"][1], "U", "Y", "BRG_UY")
    freq = np.asarray(mapdl.post_processing.time_values, dtype=float)
    mid_y = np.abs(np.asarray(mapdl.vget("", 2), dtype=float))
    mid_z = np.abs(np.asarray(mapdl.vget("", 3), dtype=float))
    brg_y = np.abs(np.asarray(mapdl.vget("", 4), dtype=float))
    mapdl.finish()

    n = min(len(freq), len(mid_y), len(mid_z), len(brg_y))
    os.makedirs(os.path.dirname(out_csv) or ".", exist_ok=True)
    with open(out_csv, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["freq_Hz", "rpm", "mid_UY_um", "mid_UZ_um",
                    "mid_vib_vel_mm_s_rms", "brg_UY_um"])
        for i in range(n):
            f = freq[i]
            amp_m = math.hypot(mid_y[i], mid_z[i])
            # ISO 20816 judges velocity: v_rms = 2*pi*f*amp/sqrt(2)
            v_rms = 2.0 * math.pi * f * amp_m / math.sqrt(2.0) * 1e3
            w.writerow([f"{f:.3f}", f"{f*60:.1f}",
                        f"{mid_y[i]*1e6:.4f}", f"{mid_z[i]*1e6:.4f}",
                        f"{v_rms:.4f}", f"{brg_y[i]*1e6:.4f}"])
    print(f"Unbalance FRF written -> {out_csv}  ({n} points)")
    print("  ISO 20816-3 zone A/B boundary for this machine class is")
    print("  about 2.3 mm/s rms; B/C about 4.5 mm/s rms.")
    return out_csv


# ---------------------------------------------------------------------------
# 6. ANALYSIS 4 - state-space ROM export for Twin Builder
# ---------------------------------------------------------------------------

def export_rom(mapdl, nodes, spm_path):
    """Modal solve + SPMWRITE -> LTI state-space model for Twin Builder."""
    mid = nodes["mid_node"]
    brg = nodes["brg_nodes"][1]

    # SPMWRITE needs an undamped/damped modal basis with element results.
    mapdl.slashsolu()
    mapdl.antype("MODAL")
    mapdl.modopt("QRDAMP", N_MODES, 0.0, 5000.0, "", "ON")
    mapdl.mxpand(N_MODES, "", "", "YES")
    mapdl.coriolis("ON", "", "", "ON")
    mapdl.cmomega("ROTOR", RPM_RATED * 2.0 * math.pi / 60.0, 0.0, 0.0)
    mapdl.solve()
    mapdl.finish()

    # Define the twin's input and output ports as node components.
    mapdl.prep7()
    mapdl.nsel("S", "NODE", "", mid)
    mapdl.cm("IN_UNBAL", "NODE")
    mapdl.nsel("S", "NODE", "", mid)
    mapdl.nsel("A", "NODE", "", brg)
    mapdl.cm("OUT_SENS", "NODE")
    mapdl.allsel()
    mapdl.finish()

    mapdl.post1()
    # SPMWRITE, Method, NMODE, INPUTS, INPUTSTRICT, OUTPUTS, OUTPUTSTRICT,
    #           VELACCKEY, FileFormat
    mapdl.run("SPMWRITE,MODAL,%d,IN_UNBAL,,OUT_SENS,,1,0" % N_MODES)
    mapdl.finish()

    default_spm = "file.spm"
    if os.path.exists(default_spm):
        os.replace(default_spm, spm_path)
    print(f"\nState-space ROM exported -> {spm_path}")
    print("  Import in Twin Builder: Project > Add Component > "
          "State Space Dynamic Model.")
    return spm_path


# ---------------------------------------------------------------------------
# 7. HYDRAULIC / PERFORMANCE CORE  (no ANSYS license required)
# ---------------------------------------------------------------------------

def pump_head(q, rpm=RPM_RATED, wear=0.0):
    """Head [m] from a quadratic characteristic with affinity-law scaling.

    H = (H0 - k*Q^2) * (N/Nr)^2, with impeller wear shaving the shut-off
    head and steepening the loss term.
    """
    n = rpm / RPM_RATED
    h0 = 1.25 * H_BEP * (1.0 - 0.85 * wear)
    k = (h0 - H_BEP * (1.0 - 0.30 * wear)) / Q_BEP ** 2
    return np.maximum((h0 - k * (q / max(n, 1e-6)) ** 2) * n ** 2, 0.0)


def pump_efficiency(q, rpm=RPM_RATED, wear=0.0, bearing=0.0):
    """Efficiency [-] as a parabola through BEP, penalised by degradation."""
    n = rpm / RPM_RATED
    qs = q / max(n, 1e-6)
    eta = ETA_BEP * (1.0 - 1.15 * ((qs - Q_BEP) / Q_BEP) ** 2)
    eta *= (1.0 - 0.25 * wear)          # recirculation through worn clearances
    eta *= (1.0 - 0.10 * bearing)       # parasitic mechanical drag
    return np.clip(eta, 0.05, 0.95)


def shaft_power(q, rpm=RPM_RATED, wear=0.0, bearing=0.0):
    """Shaft power [W] = rho*g*Q*H / eta."""
    h = pump_head(q, rpm, wear)
    eta = pump_efficiency(q, rpm, wear, bearing)
    return RHO_WATER * G * q * h / eta


def npsh_available(q, fouling=0.0, tank_head=12.0):
    """NPSHa [m]: static suction head minus strainer + line losses."""
    k_line = 200.0
    k_foul = k_line * (1.0 + 9.0 * fouling)     # fouling up to 10x loss
    return tank_head - k_foul * q ** 2


def hydraulic_twin(out_dir=OUT_DIR):
    """Write the pump-curve family and a degradation sweep to CSV."""
    os.makedirs(out_dir, exist_ok=True)
    q = np.linspace(0.005, 0.075, 71)

    # --- curve family at several speeds ------------------------------------
    curves = os.path.join(out_dir, "pump_curves.csv")
    with open(curves, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["rpm", "Q_m3_s", "Q_m3_h", "H_m", "eta", "P_shaft_kW",
                    "NPSHa_m", "NPSHr_m"])
        for rpm in (2400.0, 2700.0, 3000.0):
            for qi in q:
                npshr = NPSH_R_BEP * (qi / Q_BEP) ** 1.8 * (rpm / RPM_RATED) ** 2
                w.writerow([f"{rpm:.0f}", f"{qi:.5f}", f"{qi*3600:.1f}",
                            f"{float(pump_head(qi, rpm)):.2f}",
                            f"{float(pump_efficiency(qi, rpm)):.4f}",
                            f"{float(shaft_power(qi, rpm))/1e3:.2f}",
                            f"{float(npsh_available(qi)):.2f}",
                            f"{npshr:.2f}"])

    # --- degradation sweep: the twin's fault-signature library ------------
    sweep = os.path.join(out_dir, "degradation_sweep.csv")
    grid = np.linspace(0.0, 1.0, 11)
    with open(sweep, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["fault_mode", "severity", "H_at_BEP_m", "eta_at_BEP",
                    "P_shaft_kW", "NPSH_margin_m", "excess_power_kW"])
        p_ref = float(shaft_power(Q_BEP))
        h_ref = float(pump_head(Q_BEP))
        for mode in ("impeller_wear", "strainer_fouling", "bearing_wear"):
            for s in grid:
                wear = s if mode == "impeller_wear" else 0.0
                foul = s if mode == "strainer_fouling" else 0.0
                brg = s if mode == "bearing_wear" else 0.0
                h = float(pump_head(Q_BEP, wear=wear))
                eta = float(pump_efficiency(Q_BEP, wear=wear, bearing=brg))
                p = float(shaft_power(Q_BEP, wear=wear, bearing=brg))
                margin = float(npsh_available(Q_BEP, fouling=foul)) - NPSH_R_BEP
                # Fair energy comparison: power normalised to equal useful
                # output, NOT raw power.
                p_equiv = p * (h_ref / max(h, 1e-6))
                w.writerow([mode, f"{s:.2f}", f"{h:.2f}", f"{eta:.4f}",
                            f"{p/1e3:.2f}", f"{margin:.2f}",
                            f"{(p_equiv - p_ref)/1e3:.2f}"])

    print(f"\nHydraulic twin outputs:")
    print(f"  {curves}")
    print(f"  {sweep}")
    print(f"  BEP check: H = {float(pump_head(Q_BEP)):.1f} m, "
          f"eta = {float(pump_efficiency(Q_BEP)):.3f}, "
          f"P = {float(shaft_power(Q_BEP))/1e3:.1f} kW, "
          f"NPSH margin = {float(npsh_available(Q_BEP)) - NPSH_R_BEP:.1f} m")
    return curves, sweep


# ---------------------------------------------------------------------------
# 8. MAIN
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-mapdl", action="store_true",
                    help="run only the license-free hydraulic core")
    ap.add_argument("--out", default=OUT_DIR, help="output directory")
    ap.add_argument("--skip-campbell", action="store_true",
                    help="skip the multi-speed Campbell solve (slow)")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)

    # --- estimate the first critical speed before touching a solver -------
    inertia = math.pi * SHAFT_DIA ** 4 / 64.0
    area = math.pi / 4.0 * SHAFT_DIA ** 2
    m_shaft = DENSITY * area * SHAFT_LEN
    k_shaft = 48.0 * E_MOD * inertia / SHAFT_LEN ** 3
    m_eff = N_STAGES * IMP_MASS + 0.49 * m_shaft
    f1_est = math.sqrt(k_shaft / m_eff) / (2.0 * math.pi)
    print(f"Analytical first-critical estimate: {f1_est:.1f} Hz "
          f"({f1_est*60:.0f} rpm) = {f1_est/(RPM_RATED/60):.2f} x running")

    hydraulic_twin(args.out)

    if args.no_mapdl:
        print("\n--no-mapdl set: skipping the ANSYS half.")
        return

    from ansys.mapdl.core import launch_mapdl

    mapdl = launch_mapdl(run_location=os.path.abspath(args.out),
                         override=True)
    try:
        print(f"\nMAPDL: {mapdl.version}")
        nodes = build_rotor(mapdl)
        run_modal(mapdl)
        if not args.skip_campbell:
            run_campbell(mapdl)
        run_unbalance_harmonic(
            mapdl, nodes, os.path.join(args.out, "unbalance_frf.csv"))
        export_rom(mapdl, nodes, os.path.join(args.out, "bfp_rotor_rom.spm"))
    finally:
        mapdl.exit()


if __name__ == "__main__":
    main()
