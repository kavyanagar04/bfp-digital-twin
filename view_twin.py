"""
view_twin.py
============
The "show me the twin" script. Three things it can do:

  1. python view_twin.py
     Reads the CSVs written by bfp_digital_twin.py and draws them:
       pump_performance.png  - H-Q curves, efficiency, power, NPSH margin
       degradation.png       - how each fault mode moves the observables
       vibration.png         - unbalance FRF with ISO 20816 zone lines
     Needs only numpy + matplotlib. No ANSYS, no license.

  2. python view_twin.py --model
     Launches MAPDL, builds the rotor, and opens interactive 3-D views of
     the mesh and the animated mode shapes. Needs a licensed MAPDL.

  3. python view_twin.py --all
     Both of the above.

Usage:
    python bfp_digital_twin.py --no-mapdl     # generate the data first
    python view_twin.py                       # then look at it
"""

import argparse
import csv
import os

import numpy as np
import matplotlib
matplotlib.use("Agg")          # switch to "TkAgg" for pop-up windows
import matplotlib.pyplot as plt

OUT_DIR = "twin_outputs"


def load_csv(path):
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise SystemExit(f"{path} is empty")
    return rows


def fcol(rows, key, where=None):
    return np.array([float(r[key]) for r in rows
                     if where is None or where(r)])


# ---------------------------------------------------------------------------
# 1. Hydraulic performance
# ---------------------------------------------------------------------------

def plot_performance(out_dir):
    path = os.path.join(out_dir, "pump_curves.csv")
    if not os.path.exists(path):
        print(f"  skip: {path} not found - run bfp_digital_twin.py first")
        return None
    rows = load_csv(path)
    speeds = sorted({float(r["rpm"]) for r in rows})

    fig, ax = plt.subplots(2, 2, figsize=(11, 8))
    fig.suptitle("Boiler feed pump twin - performance envelope",
                 fontsize=13, fontweight="bold")

    for rpm in speeds:
        sel = (lambda r, s=rpm: float(r["rpm"]) == s)
        q = fcol(rows, "Q_m3_h", sel)
        lbl = f"{rpm:.0f} rpm"
        ax[0, 0].plot(q, fcol(rows, "H_m", sel), label=lbl)
        ax[0, 1].plot(q, fcol(rows, "eta", sel) * 100, label=lbl)
        ax[1, 0].plot(q, fcol(rows, "P_shaft_kW", sel), label=lbl)
        margin = fcol(rows, "NPSHa_m", sel) - fcol(rows, "NPSHr_m", sel)
        ax[1, 1].plot(q, margin, label=lbl)

    ax[0, 0].set(title="Head-flow characteristic",
                 xlabel="Flow  [m$^3$/h]", ylabel="Head  [m]")
    ax[0, 1].set(title="Efficiency", xlabel="Flow  [m$^3$/h]",
                 ylabel="Efficiency  [%]")
    ax[1, 0].set(title="Shaft power", xlabel="Flow  [m$^3$/h]",
                 ylabel="Power  [kW]")
    ax[1, 1].set(title="NPSH margin (NPSHa - NPSHr)",
                 xlabel="Flow  [m$^3$/h]", ylabel="Margin  [m]")
    ax[1, 1].axhline(0.0, color="crimson", ls="--", lw=1.2)
    ax[1, 1].text(0.02, 0.06, "cavitation below this line",
                  transform=ax[1, 1].transAxes, color="crimson", fontsize=8)

    for a in ax.ravel():
        a.grid(alpha=0.3)
        a.legend(fontsize=8)
    fig.tight_layout()
    f = os.path.join(out_dir, "pump_performance.png")
    fig.savefig(f, dpi=140)
    plt.close(fig)
    print(f"  wrote {f}")
    return f


# ---------------------------------------------------------------------------
# 2. Degradation / fault signatures
# ---------------------------------------------------------------------------

def plot_degradation(out_dir):
    path = os.path.join(out_dir, "degradation_sweep.csv")
    if not os.path.exists(path):
        print(f"  skip: {path} not found")
        return None
    rows = load_csv(path)
    modes = ["impeller_wear", "strainer_fouling", "bearing_wear"]
    nice = {"impeller_wear": "Impeller / clearance wear",
            "strainer_fouling": "Suction strainer fouling",
            "bearing_wear": "Bearing degradation"}

    fig, ax = plt.subplots(2, 2, figsize=(11, 8))
    fig.suptitle("Fault signatures at the best-efficiency point",
                 fontsize=13, fontweight="bold")

    for m in modes:
        sel = (lambda r, mm=m: r["fault_mode"] == mm)
        s = fcol(rows, "severity", sel) * 100
        ax[0, 0].plot(s, fcol(rows, "H_at_BEP_m", sel), marker="o", ms=3,
                      label=nice[m])
        ax[0, 1].plot(s, fcol(rows, "eta_at_BEP", sel) * 100, marker="o",
                      ms=3, label=nice[m])
        ax[1, 0].plot(s, fcol(rows, "NPSH_margin_m", sel), marker="o", ms=3,
                      label=nice[m])
        ax[1, 1].plot(s, fcol(rows, "excess_power_kW", sel), marker="o",
                      ms=3, label=nice[m])

    ax[0, 0].set(title="Head", xlabel="Severity  [%]", ylabel="Head  [m]")
    ax[0, 1].set(title="Efficiency", xlabel="Severity  [%]",
                 ylabel="Efficiency  [%]")
    ax[1, 0].set(title="NPSH margin", xlabel="Severity  [%]",
                 ylabel="Margin  [m]")
    ax[1, 0].axhline(0.0, color="crimson", ls="--", lw=1.2)
    ax[1, 1].set(title="Energy penalty at equal useful output",
                 xlabel="Severity  [%]", ylabel="Excess power  [kW]")

    for a in ax.ravel():
        a.grid(alpha=0.3)
        a.legend(fontsize=8)
    fig.tight_layout()
    f = os.path.join(out_dir, "degradation.png")
    fig.savefig(f, dpi=140)
    plt.close(fig)
    print(f"  wrote {f}")
    return f


# ---------------------------------------------------------------------------
# 3. Vibration FRF (only exists after a real MAPDL run)
# ---------------------------------------------------------------------------

def plot_vibration(out_dir):
    path = os.path.join(out_dir, "unbalance_frf.csv")
    if not os.path.exists(path):
        print(f"  skip: {path} not found "
              "(needs the MAPDL harmonic run)")
        return None
    rows = load_csv(path)
    f_hz = fcol(rows, "freq_Hz")
    amp = np.hypot(fcol(rows, "mid_UY_um"), fcol(rows, "mid_UZ_um"))
    vel = fcol(rows, "mid_vib_vel_mm_s_rms")
    brg = fcol(rows, "brg_UY_um")

    fig, ax = plt.subplots(1, 2, figsize=(12, 4.6))
    fig.suptitle("Synchronous unbalance response (1x excitation)",
                 fontsize=13, fontweight="bold")

    ax[0].plot(f_hz, amp, label="mid-span")
    ax[0].plot(f_hz, brg, label="bearing", ls="--")
    ax[0].set(title="Shaft displacement", xlabel="Frequency  [Hz]",
              ylabel="Amplitude  [micron]", yscale="log")
    ax[0].axvline(50.0, color="grey", ls=":", lw=1.2)
    ax[0].text(50.5, ax[0].get_ylim()[0] * 1.5, "running speed",
               rotation=90, fontsize=8, color="grey")

    ax[1].plot(f_hz, vel, color="darkorange")
    for lim, lbl, col in ((2.3, "A/B", "green"), (4.5, "B/C", "orange"),
                          (7.1, "C/D", "crimson")):
        ax[1].axhline(lim, ls="--", lw=1.1, color=col)
        ax[1].text(f_hz[-1], lim, f" zone {lbl}", va="bottom", fontsize=8,
                   color=col, ha="right")
    ax[1].set(title="Vibration velocity vs ISO 20816-3 zones",
              xlabel="Frequency  [Hz]", ylabel="v$_{rms}$  [mm/s]")

    for a in ax:
        a.grid(alpha=0.3)
    ax[0].legend(fontsize=8)
    fig.tight_layout()
    f = os.path.join(out_dir, "vibration.png")
    fig.savefig(f, dpi=140)
    plt.close(fig)
    print(f"  wrote {f}")
    return f


# ---------------------------------------------------------------------------
# 4. The FE model itself, in 3-D
# ---------------------------------------------------------------------------

def show_model(out_dir, n_modes=4):
    """Launch MAPDL, build the rotor, and open interactive 3-D views."""
    from ansys.mapdl.core import launch_mapdl
    import bfp_digital_twin as twin

    mapdl = launch_mapdl(run_location=os.path.abspath(out_dir), override=True)
    try:
        print(f"MAPDL {mapdl.version} started")
        twin.build_rotor(mapdl)

        # --- the mesh ----------------------------------------------------
        mapdl.eplot(show_node_numbering=True, background="white",
                    show_edges=True,
                    savefig=os.path.join(out_dir, "model_mesh.png"))
        print(f"  wrote {os.path.join(out_dir, 'model_mesh.png')}")
        mapdl.eplot(background="white", show_edges=True)   # interactive

        # --- mode shapes -------------------------------------------------
        twin.run_modal(mapdl)
        mapdl.post1()
        for m in range(1, n_modes + 1):
            mapdl.set(1, m)
            print(f"  plotting mode {m}")
            mapdl.post_processing.plot_nodal_displacement(
                "NORM", show_displacement=True, displacement_factor=2.0,
                background="white",
                savefig=os.path.join(out_dir, f"mode_{m}.png"))
        mapdl.finish()
        print("\nClose each plot window to advance to the next one.")
    finally:
        mapdl.exit()


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=OUT_DIR, help="directory with the CSVs")
    ap.add_argument("--model", action="store_true",
                    help="open the 3-D FE model and mode shapes (needs MAPDL)")
    ap.add_argument("--all", action="store_true",
                    help="plots and 3-D model")
    args = ap.parse_args()

    if not args.model or args.all:
        print(f"Reading twin outputs from {args.out}/")
        plot_performance(args.out)
        plot_degradation(args.out)
        plot_vibration(args.out)
        print("\nOpen the PNGs in that folder to see the twin's behaviour.")

    if args.model or args.all:
        show_model(args.out)


if __name__ == "__main__":
    main()
