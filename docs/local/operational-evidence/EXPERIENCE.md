# rf-link-433-budget

- adopted: `agg1`  (run `rf_fpga-cx-agg1/rf-link-433-budget/agg1`)
- components: 1 scripts; 119 always-on chars

## Why this was chosen
trivial pool: single final at k=1; delivered without a selector session

## What each edit did
component: scripts/solve_rf_fpga.py — prx power chain
candidates: dom1, agg1
change: inserted `- data['sys_loss_db']` into the received-power computation (`prx = ptx + gtx_dbi + grx_dbi - sys_loss_db - fspl`); all other lines byte-identical to base.
observed: base1 and inv1 rollouts (returncode=0) produced prx_dbm=-69.71, fade_margin_db=50.29, leaving the source key `sys_loss_db: 2.5` unused; dom1 and agg1 rollouts (returncode=0) produced prx_dbm=-72.21, fade_margin_db=47.79. link_viable stayed `true` in all four (margin change 2.5 dB, min_margin_db=10, so the term did not cross the decision boundary). Deliverables in deliverables/{dom1,agg1}/result.json.txt vs deliverables/{base1,inv1}/result.json.txt show the exact contrast.
verdict: helped
(repeat lines)

## Transferable lesson
- **cue**: a deterministic solver's formula over an input record leaves one or more source-provided keys unused, while the domain model (here a link/fee/cost budget) conventionally subtracts or adds such a term before any threshold comparison.
- **lesson**: in the solver's result computation, inspect the input record for keys the formula never reads; before changing output structure, fold each genuinely unused domain term into the chain at its standard place (subtracted losses from the measured power, not into the threshold), and re-derive dependent derived keys and the Boolean from the corrected intermediates.
- **evidence**: row "prx power chain" via candidates dom1/agg1 — the only execution contrast in the record (prx_dbm -69.71 → -72.21 in deliverables/base1 and inv1 vs dom1 and agg1); the input key `sys_loss_db: 2.5` is present in source/input.json but absent from the base formula, and all four rollouts returned 0, so the change is isolated to the formula edit.
- **confidence**: high — the contrast is fully isolated (single-component diff, four runs, all rc=0), though the record contains no rubric confirming which value set was preferred; confidence in "edit changed behavior" is high, in "which behavior was correct" rests on the domain convention only.
