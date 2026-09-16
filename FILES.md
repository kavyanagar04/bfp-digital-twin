# FILES.md — what every file is, how to open it, what it shows

Read this if you just cloned the repo and want to know where to click.

```
bfp-digital-twin/
├── README.md                       project documentation (start here)
├── FILES.md                        this file — the file-by-file guide
├── requirements.txt                Python dependencies
├── LICENSE                         MIT
├── .gitignore                      keeps ANSYS junk out of Git
├── bfp_digital_twin.py             THE TWIN — physics + ANSYS analyses
├── view_twin.py                    THE VIEWER — turns results into pictures
├── apdl/
│   └── bfp_rotor.inp               native ANSYS input file (GUI route)
├── docs/
│   └── pump_digital_twin_ansys.pdf 9-page methodology reference
└── examples/
    ├── pump_curves.csv             sample output, committed so the repo
    ├── degradation_sweep.csv       shows results without anyone running it
    ├── pump_performance.png
    └── degradation.png
```

---

## 1. `bfp_digital_twin.py` — the twin itself

**Purpose.** The executable core. Two halves in one file: a hydraulic
performance model in NumPy (no license needed) and a rotordynamic
finite-element model driven into ANSYS MAPDL through PyMAPDL.

**How to run.**

```bash
pip install -r requirements.txt
python bfp_digital_twin.py --no-mapdl     # hydraulic half only, runs anywhere
python bfp_digital_twin.py                # full run, needs a licensed MAPDL
python bfp_digital_twin.py --skip-campbell --out my_results
```

**What it prints.** An analytical first-critical-speed estimate (≈ 71 Hz =
1.42 × running speed), the BEP check (220 m head, η 0.82, 120.7 kW, 7.0 m NPSH
margin), and — on a full run — the critical speed table with API 610
separation margins.

**What it writes**, into `twin_outputs/`:

| Output | Meaning |
|---|---|
| `pump_curves.csv` | The pump's performance envelope: head, efficiency, power, NPSHa and NPSHr against flow, at 2400 / 2700 / 3000 rpm |
| `degradation_sweep.csv` | The fault-signature library: each of the three fault modes swept healthy → fully degraded, with the resulting head, efficiency, power, NPSH margin and energy penalty |
| `unbalance_frf.csv` | *(full run only)* Vibration response vs frequency at mid-span and at the bearing, in microns and in ISO velocity units |
| `bfp_rotor_rom.spm` | *(full run only)* The reduced-order model — a linear state-space file that executes in milliseconds. **This is the file Twin Builder imports.** |

**What it represents.** Sections 2–7 of the file map onto the real machine: a
4-stage boiler feed pump on a 1.2 m shaft in two journal bearings, pumping
feedwater at ~160 °C, with three degradation mechanisms — impeller/clearance
wear, suction strainer fouling, and bearing degradation.

**Edit here, nowhere else.** All parameters are in one block at the top
(section 1). Changing `SHAFT_DIA` moves the critical speed; changing `BRG_KXY`
above zero lets you hunt rotordynamic instability.

---

## 2. `view_twin.py` — the viewer

**Purpose.** You cannot judge a twin from a CSV. This reads the outputs and
draws them.

**How to run.**

```bash
python view_twin.py                  # plots from the CSVs — no ANSYS needed
python view_twin.py --model          # opens the 3-D FE model + mode shapes
python view_twin.py --all            # both
python view_twin.py --out my_results # point it at a different folder
```

**What it writes**, alongside the CSVs:

| Figure | What it shows |
|---|---|
| `pump_performance.png` | Four panels: head–flow curves at three speeds, the efficiency hill, shaft power, and the NPSH margin falling toward the cavitation line as flow rises |
| `degradation.png` | The diagnostic core of the project. Head, efficiency, NPSH margin and energy penalty against fault severity, one line per fault mode. The three lines separate differently in each panel — **that separation is what makes diagnosis possible** |
| `vibration.png` | *(after a full run)* The unbalance response with ISO 20816-3 zone A/B/C lines drawn on, so you can see at a glance whether the rotor passes |
| `model_mesh.png`, `mode_1..4.png` | *(with `--model`)* The FE model and its mode shapes |

With `--model` it also opens **interactive** 3-D windows — rotate with the
mouse, close each to advance to the next. Set `matplotlib.use("TkAgg")` near
the top if you want the 2-D plots to pop up as windows too instead of only
saving to PNG.

**Known artifact, worth mentioning before an examiner spots it:** the power
curve rises steeply below ~40 m³/h. That is `P = ρgQH/η` with η → 0 at
shut-off, not real physics. Real feed pumps never operate there, which is
exactly why they carry minimum-flow recirculation valves.

---

## 3. `apdl/bfp_rotor.inp` — the ANSYS GUI route

**Purpose.** Same rotor model, written in native APDL instead of Python. This
is the file to use when you want the model *inside* the ANSYS window — for a
demo, a viva, or screenshots. PyMAPDL drives ANSYS from outside and shows
nothing in the GUI; this does the opposite.

**How to open it.**

1. Start menu → **Mechanical APDL Product Launcher**
2. Working Directory → the folder holding this file (keep it clean, e.g. `D:\twin`)
3. Job Name → `bfp_rotor` → **Run**
4. In the ANSYS window: **File → Read Input from…** → select `bfp_rotor.inp`

Or batch, no GUI:

```
"D:\Program Files\ANSYS Inc\v242\ansys\bin\winx64\ANSYS242.exe" -b -i bfp_rotor.inp -o bfp_rotor.out
```

(substitute your actual version folder for `v242`)

**What you see**, in order: the rotor mesh with the impeller masses and
bearings → a text window listing the critical speeds → four mode shape plots →
the first mode animating, the shaft whipping in first bending. That animation
is the thing that looks like a digital twin on screen.

**Two optional blocks at the bottom**, commented out. Uncomment the first for
the **Campbell diagram** (critical speeds against shaft speed — the single most
recognisable figure in rotordynamics, and a strong report exhibit). Uncomment
the second to write the `.spm` reduced model from the GUI route.

**If the critical speed list comes back with modes near zero**, the bearings
aren't holding the rotor. That's the `KEYOPT,3,2,1` line — try `2` instead
of `1`.

---

## 4. `docs/pump_digital_twin_ansys.pdf` — the methodology

**Purpose.** The written half of the project: what to say when someone asks
*why* the model is built this way. Open it in any PDF reader.

Nine pages: BFP anatomy and position in the water–steam cycle, the L0→L4 twin
maturity levels, governing physics with equations (Euler head, affinity laws,
NPSH, the rotor equation of motion with the gyroscopic term, MAC, Miner's
rule), the five-stage analysis chain, the three reduction routes, inverse
estimation for fault diagnosis, validation practice, the standards set
(API 610, ISO 20816-3, ISO 1940, ANSI/HI 9.6.1, ASME PTC 8.2), extensions, and
an honest-limitations section.

If you write a report for this project, this PDF is the source you paraphrase
from.

---

## 5. `examples/` — sample outputs

**Purpose.** Committed so anyone browsing the GitHub page sees real results
without installing anything, and so you have a reference to diff against if a
change breaks something. Regenerating them is one command
(`python bfp_digital_twin.py --no-mapdl && python view_twin.py`).

Embed `examples/degradation.png` in your README on GitHub — it is the most
informative single image in the project.

---

## 6. `requirements.txt` — the dependencies

```bash
pip install -r requirements.txt
```

`numpy` and `matplotlib` are all the license-free half needs.
`ansys-mapdl-core` pulls in pyvista, pandas, protobuf, grpcio and
ansys-tools-path automatically — that is where the 3-D rendering comes from.

**What is *not* in here, and cannot be:** ANSYS itself. It is commercial
software, gigabytes in size, and not a pip package. Ansys Student is free and
sufficient for models this size. Install it separately, then the scripts will
find it.

---

## 7. `.gitignore` and `LICENSE`

`.gitignore` keeps generated results and ANSYS working files out of the repo.
MAPDL litters its working directory with `.err`, `.rst`, `.esav`, `.emat`,
`file.*` and lock files, some of them hundreds of megabytes; committing those
is the classic way to ruin a simulation repo.

`LICENSE` is MIT — put your name in the copyright line before pushing.

---

## Suggested order to work through it

1. `pip install -r requirements.txt`
2. `python bfp_digital_twin.py --no-mapdl` — proves the physics runs
3. `python view_twin.py` — look at the two figures; sanity-check the shapes
4. `apdl/bfp_rotor.inp` in the Mechanical APDL GUI — see the rotor and its modes
5. Uncomment the Campbell block — get the figure for your report
6. `python bfp_digital_twin.py` (full) — get the vibration FRF and the `.spm`
7. Import the `.spm` into Twin Builder, wire up the system, export an FMU

Steps 1–4 are an afternoon. Step 7 is the actual deliverable.

## Pushing it to GitHub

```bash
cd bfp-digital-twin
git init
git add .
git commit -m "Digital twin of boiler feed pumps in thermal power generation"
git branch -M main
git remote add origin https://github.com/<you>/bfp-digital-twin.git
git push -u origin main
```
