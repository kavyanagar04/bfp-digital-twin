# Digital Twin of a Boiler Feed Pump in Thermal Power Generation

An ANSYS-based digital twin of the boiler feed pump (BFP), the highest-duty
rotating machine in a thermal power station's water–steam cycle.

The project has two coupled halves: a rotordynamic finite-element model solved
in **ANSYS Mechanical APDL 2026 R1**, and a real-time twin that executes the
pump's performance and degradation physics using the ANSYS result.

---

## Results obtained

Solved in ANSYS MAPDL 2026 R1 (QRDAMP complex eigensolution, gyroscopic
effects active via `CORIOLIS`, rotor spinning at 3000 rpm):

| Mode | Frequency | Type |
|---|---|---|
| 1, 2 | **77.17 Hz** | First bending pair — splits to 76.01 / 78.33 Hz under spin |
| 3 | 123.96 Hz | Torsional |
| 4, 5 | 267.20 Hz | Second bending pair |
| 6 | 363.39 Hz | Higher torsional |
| 10 | 682.50 Hz | Axial |

**Key findings**

- **Separation margin.** First critical speed 77.17 Hz against a running speed
  of 50 Hz (3000 rpm) gives a **54% separation margin**. API 610 requires a
  minimum of 20%, so the rotor design is compliant — a stiff-shaft design
  operating below its first critical speed.

- **Gyroscopic split.** The first bending mode at 77.17 Hz splits into
  **76.01 Hz (backward whirl)** and **78.33 Hz (forward whirl)** when the rotor
  spins. This split appears only because gyroscopic coupling is included, and
  confirms the analysis is genuine rotordynamics rather than a static modal
  analysis.

- **Model verification.** An independent analytical estimate using
  `f₁ = (1/2π)·√(48EI/L³ / m_eff)` predicts **71.2 Hz**, against ANSYS's
  **77.17 Hz** — agreement within **8%**. The FE result is higher because it
  captures bearing flexibility and shear deformation that the closed-form
  expression neglects. This agreement verifies the model.

- **Mass check.** Total rotor mass 173.93 kg (73.93 kg shaft + 100 kg
  impellers), centre of mass at mid-span as expected for a symmetric rotor.

---

## Model description

A 4-stage boiler feed pump rotor:

| Component | Representation | Value |
|---|---|---|
| Shaft | `BEAM188`, cubic shape function, circular solid section | 1.20 m span, 100 mm diameter, steel |
| Impellers | `MASS21` with rotary inertia, 4 off at equal spacing | 25 kg each, Ip 0.60, It 0.35 kg·m² |
| Bearings | `COMBI214` journal bearings normal to the spin axis | K = 2×10⁸ N/m, C = 1.5×10⁴ N·s/m |
| Speed | `CMOMEGA` on a rotating component, `CORIOLIS` in stationary frame | 3000 rpm (50 Hz, 2-pole direct drive) |
| Fluid | Feedwater at approximately 160 °C | ρ = 917 kg/m³ |
| Duty | 4 stages × 55 m | 180 m³/h at 220 m total head, 82% efficiency |

436 equations, 10 modes extracted, solution time approximately 6 seconds.

---

## The twin: three degradation modes

The twin represents the three degradation mechanisms that account for the
majority of real BFP condition-monitoring findings, and — critically — each
produces a **distinct signature**, which is what makes diagnosis possible:

| Fault | Mechanism | Signature |
|---|---|---|
| Impeller / clearance wear | Erosion and cavitation pitting open running clearances; internal recirculation rises | Head and efficiency fall; discharge pressure drops with suction pressure unchanged |
| Suction strainer fouling | Debris raises the suction line loss coefficient | Head rise nearly unchanged, but **NPSH margin collapses** and cavitation follows |
| Bearing degradation | Oil film breakdown, babbitt wear, misalignment | Shaft power rises at unchanged hydraulic output; support stiffness falls, moving the critical speed toward running speed |

**Instrumentation finding.** Without a suction-pressure measurement, strainer
fouling and impeller wear are mathematically indistinguishable, and an inverse
estimator will return a confident wrong answer. This is the most important
instrument-selection conclusion of the study.

**Energy accounting.** A degraded pump delivers less head for the same power,
so comparing raw power understates the loss. The twin normalises to equal
useful hydraulic output: `ΔP = P_degraded·(H_ref/H_degraded) − P_ref`.

---

## What to open

### 1. The ANSYS model — `apdl/bfp_rotor.inp`

Start menu → **Mechanical APDL Product Launcher**
→ Working Directory: the `apdl` folder → Job Name: `bfp_rotor` → **Run**
→ in ANSYS: **File → Read Input from…** → `bfp_rotor.inp`

Shows the rotor mesh, the critical speed table, and the mode shapes. To view a
specific mode, type in the command box:

```
SET,1,1
PLDISP,2
```

(`SET,1,1` = first bending, `SET,1,3` = torsional, `SET,1,4` = second bending)

All model parameters sit in a single block near the top of the file, marked
`PARAMETERS (edit only here)`. Change a value, save, re-read the file — for
example increasing `SD` from 0.100 to 0.120 m raises the first critical speed,
because a thicker shaft is stiffer.

### 2. The twin interface — `dashboard/bfp_twin_dashboard.html`

Double-click to open in any browser. No installation required.

Sliders set shaft speed, flow, suction tank level, and the three health
parameters. Head, efficiency, shaft power, NPSH margin, 1× vibration and the
first critical speed update instantly, with alarm states against API 610 and
ISO 20816-3 limits. Four preset buttons demonstrate the healthy baseline and
each fault signature.

### 3. The Python model — `bfp_digital_twin.py`

```bash
pip install -r requirements.txt
python bfp_digital_twin.py --no-mapdl     # hydraulic model only
python bfp_digital_twin.py                # full run, drives ANSYS via PyMAPDL
python view_twin.py                       # plots the results
```

Writes the performance envelope and the fault-signature library to CSV, and on
a full run exports a state-space reduced-order model (`.spm`).

### 4. The methodology — `docs/pump_digital_twin_ansys.pdf`

Nine pages: machine anatomy, the L0–L4 twin maturity levels, governing physics
with equations, the analysis chain, reduction routes, validation practice and
the standards set.

---

## Why the real-time layer is not inside ANSYS

The ANSYS solve takes seconds for this model and would take minutes to hours
for full geometry. A twin must respond in milliseconds. The standard industrial
solution is a **reduced-order model**: run the expensive physics once, compress
it, and execute the compressed form live. ANSYS's own mechanism for this is
`SPMWRITE`, which exports a linear state-space model, normally run inside
**ANSYS Twin Builder**.

Twin Builder is not included in the Ansys Mechanical Enterprise Academic
Student 2026 R1 license used here — it ships with Ansys Electronics Desktop.
The real-time layer is therefore implemented directly from the ANSYS result:
the first critical speed of 77.17 Hz is carried into the twin as the
rotordynamic anchor and scaled with bearing support stiffness. The `.spm`
export path remains in the code (optional block at the end of the `.inp`) for
use with a Twin Builder license.

---

## Twin maturity level

| Level | Definition | This project |
|---|---|---|
| L0 | Digital model — geometry and a static curve | — |
| L1 | Digital shadow — offline comparison with history | — |
| L2 | Executable twin — real-time model | achieved |
| L3 | Predictive twin — fault detection and state estimation | achieved (fault signatures separable) |
| L4 | Prescriptive twin — closes the control loop | out of scope; needs plant interface and safety case |

---

## Standards applied

API 610 / ISO 13709 (critical speed separation margin), ISO 20816-3 (vibration
evaluation zones), ISO 1940-1 / ISO 21940-11 (balance quality grade G2.5),
ANSI/HI 9.6.1 (NPSH margin), ASME PTC 8.2 / ISO 9906 (performance test codes),
ISO 13374 / ISO 17359 (condition monitoring architecture).

---

## Limitations

- The rotor is a beam-and-lumped-mass idealisation. It captures lateral
  critical speeds and 1× unbalance response; it does not capture local impeller
  stress, casing response, or foundation coupling.
- The hydraulic layer is a fitted characteristic, not a solved flow field. It
  cannot predict suction recirculation onset or cavitation pattern detail.
- Bearing coefficients are constants. Real journal bearings vary with speed,
  load and oil temperature.
- Degradation coefficients are physically motivated but not fitted to plant
  trend data, so the twin separates and ranks faults correctly while absolute
  severity readings remain indicative.
- The twin runs on manual inputs, not a live plant data feed. Deployment would
  replace the sliders with a historian connection and solve the health
  parameters inversely from measurements.

---

## Repository contents

```
├── README.md                          this file
├── FILES.md                           file-by-file guide
├── requirements.txt                   Python dependencies
├── LICENSE                            MIT
├── bfp_digital_twin.py                twin core: physics + ANSYS analyses
├── view_twin.py                       plotting and 3-D model viewer
├── apdl/bfp_rotor.inp                 ANSYS input file
├── dashboard/bfp_twin_dashboard.html  the twin interface
├── docs/pump_digital_twin_ansys.pdf   methodology reference
└── examples/                          sample outputs
```
