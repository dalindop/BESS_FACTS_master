# Agent Instructions

## Runtime and Setup

- This is a single Python/Pyomo repository; there is no package manager, CI workflow, formatter, linter, or pytest configuration.
- The lockfiles were generated with Python 3.14; use a compatible interpreter (the verified environment is Python 3.14.6), despite the stale Python 3.11 recommendation in `README.md`.
- Create and activate the ignored virtual environment, then install the pinned dependencies:
  `python -m venv .venv`
  `.venv\Scripts\Activate.ps1`
  `python -m pip install -r requirements-lock.txt`
- Run commands from the repository root. Root `main.py` adds the `02_Model/*` subdirectories to `sys.path`; running model modules from arbitrary directories can import the wrong module or fail.

## Architecture

- `main.py` is the live entrypoint: it loads an Excel case, builds, solves, and optionally exports results.
- The model assembly order in `02_Model/02_Core/model_builder.py` is mandatory: `sets -> parameters -> variables -> objective -> constraints`.
- `02_Model/01_Inputs/data_loader.py` defines the Excel contract. `Config`, `Nodos`, `Lineas`, `Generadores`, and `Demanda` are required; component sheets such as `BESS_Cand` and `FACTS_Cand` are optional.
- `02_Model/03_Solvers/solver_runner.py` maps `highs` to Pyomo `appsi_highs`; supported names are `highs`, `gurobi`, `glpk`, `cbc`, and `cplex_neos`. Gurobi needs a license, GLPK/CBC need separately installed executables, and NEOS needs internet plus `NEOS_EMAIL`.
- A case workbook's `Config.solver` value overrides the `--solver` argument after loading. Check the workbook when a requested solver appears to be ignored.

## Running and Verification

- Always pass an explicit existing workbook path: the CLI default `caso_WW.xlsx` is not present at the repository root.
- Normal smoke run with the default local solver:
  `python main.py "01_Data/03_Test_Cases/IEEE 14/02_Plana/caso_IEEE14_Capa2_1h_plana.xlsx" --solver highs --horas 1`
- Useful CLI flags are `--horas N` for a short horizon, `--lp` to write a symbolic `.lp` model, and `--export` to write Excel results.
- The repository has standalone scripts under `05_Tests`, not a maintained pytest suite. Many older scripts use obsolete fixture names or hard-coded paths such as `/mnt/user-data/uploads`; inspect and repair their fixture path before treating them as runnable tests.
- A cheap syntax/import check is `python -m compileall -q main.py 02_Model 05_Tests`. For a solved-case consistency report, run `python 05_Tests/validacion_resultados.py "<case.xlsx>" --solver highs`.

## Data and Artifacts

- Treat `01_Data/01_Raw` as immutable source data. Put changes in test-case or processed inputs instead of editing raw files.
- `04_Outputs/`, solver files (`*.lp`, `*.sol`, `*.mps`), logs, and Excel lock files are ignored/generated artifacts; do not use them as source code or hand-edit them to fix a model result.
