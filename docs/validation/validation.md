# Validating the model against fly experiments

`fruit_fly.validation` runs the model the way published experiments were run and checks that it reproduces their findings. It can also calibrate the two parameters that have no direct measurement. Use it whenever the circuit or the model changes, and above all on the **real FlyWire circuit**: everything so far has been developed on a synthetic circuit that was designed to resemble the fly, so passing on it proves the pipeline works, not that the model is right.

## Running it on the real circuit

```bash
bash scripts/download_data.sh && python scripts/extract_mb_circuit.py     # -> data/processed/ (all synapses)
bash scripts/download_door.sh

python -m fruit_fly.validation --circuit data/processed --door data/raw/door \
    --calibrate --params-out data/calibration.json --out temp/docs/validation-flywire.md
```

The run prints each check as it goes and writes a Markdown report. The exit code is 0 only if every check passes. A full run takes a few minutes on the synthetic circuit and longer on the real one. `--quick` uses fewer odours, odour pairs and trial counts.

To make the calibrated values the defaults for every experiment the API runs:

```bash
FRUIT_FLY_CIRCUIT_DIR=data/processed FRUIT_FLY_PARAMS_FILE=data/calibration.json uvicorn backend.app.main:app
```

Requests can still override any value. Unknown names in the file stop the server at startup instead of being silently ignored.

## Calibration

Only two parameters are set from data, and from data *other* than the findings being checked:

| Parameter | Calibrated so that | Source |
|---|---|---|
| `graded_input_gain` (APL's input scale; `--no-apl-half-range` to skip) | the median odour drives APL to half its range | a modelling choice: APL responds in a graded, learnable way (Liu & Davis 2009; Zhou et al. 2019); no measured depolarisation found. On the synthetic circuit APL never saturates and the gain stays ~1 |
| `graded_gain` (APL strength) | the median odour activates ~7% of Kenyon cells | Turner et al. 2008; Honegger et al. 2011 |
| `mbon_tonic_mV` (with `--mbon-spontaneous-hz`, default 12.1; 0 = silent MBONs) | the median MBON fires at 12.1 Hz at rest | MBON-α3, eLife 77578 (the only measured rate found) |
| `mbon_tonic_by_type` (only with `--mbon-tonic per-type`) | every MBON type fires at that rate | as above. MBON types inhibit each other, so all types are nudged together by their rate error, damped, for 50 rounds; on FlyWire they settle at 11-15 Hz. Not the default: with one measured rate, assuming every type fires at it is a stronger claim than the median, and results trade off (see below) |
| `learning_rate` | 3 forward pairings reduce the CS+ output response by ~60% (moderate, not saturated) | a choice: keeps effects measurable |

All use bisection, since each target changes monotonically with its parameter. APL gain and MBON tonic input affect each other, so they are calibrated in turn, twice, before the learning rate. If the measurement is undefined (no output neuron in the US compartments responds, so the CS+ change is n/a), calibration stops and the report says so, rather than returning the end of the search range. The neuron parameters (from Shiu et al. 2024) and the timing-rule parameters are not calibrated.

## The checks

| Check | What flies do | Pass if |
|---|---|---|
| Sparse Kenyon cell code | each odour activates ~5–10% of KCs | median 2–20% |
| APL keeps the code sparse | blocking APL increases KC responses (Lin et al. 2014) | ≥ 1.5× more active without APL |
| Pattern separation | odours are less correlated in KCs than in projection neurons (Campbell et al. 2013) | ≥ 70% of odour pairs |
| Generalisation grows with similarity | more similar odours generalise more (Campbell et al. 2013; Barth et al. 2014) | Spearman ρ(similarity, CS− change) < 0 |
| Odour-specific memory | training changes the trained odour's response only | CS+ ≤ −30%, \|CS−\| < 15% |
| Compartment-specific plasticity | dopamine changes synapses only in its compartments (Hige et al. 2015) | the CS+ Kenyon cells' synapses < 90% inside, > 97% elsewhere |
| Acquisition curve | memory grows with pairings and saturates (Tully & Quinn 1985) | PI(0) < 0.15, non-decreasing, PI(max) > PI(1) |
| Shock → avoidance, reward → approach | (Tully & Quinn 1985; Tempel et al. 1983) | both PIs > 0.3 |
| PPL1 needed for shock learning | blocking them abolishes aversive memory (Schwaerzel et al. 2003; Aso et al. 2010) | \|PI\| < 0.1 with PPL1 silenced |
| PAM needed for reward learning | (Liu et al. 2012; Burke et al. 2012) | \|PI\| < 0.1 with PAM silenced |
| Relief learning | backward pairing makes the odour mildly attractive (Tanimoto et al. 2004; Handler et al. 2019) | backward PI < 0 and weaker than forward |
| Extinction | unreinforced CS+ weakens avoidance through an opposing reward memory (Schwaerzel et al. 2002; Felsenberg et al. 2018) | PI reduced by ≥ 40%, still ≥ −0.2 (`prediction_error`, Rescorla-Wagner `sum` expectation) |
| Blocking | a cue trained with one that already predicts the US learns less (Kamin 1969; Rescorla & Wagner 1972) | **reported, not judged**: PI and synaptic ratios, blocking vs control (`pe_us`, `sum`) |

The blocking cue X is the odour least similar to A among those of comparable salience (evoking at least half of A's response in the shock compartments): blocking designs match cue salience, and in Rescorla-Wagner salience sets the learning rate. Choosing by dissimilarity alone picked a weakly driving odour on FlyWire, whose control group barely learned. Blocking is reported without a pass/fail target: the prediction-error rule predicts it, but this check does not assume what flies do in odour learning. The synaptic ratio (weight lost by the KCs only X activates) measures the learning itself; the performance index passes through the output neurons' spike threshold and compresses it.

Three details keep the checks honest:

- **Responses are evoked activity.** With spontaneously active MBONs, readouts subtract each neuron's spontaneous rate (measured at rest) from its odour response, as recordings do (Hige et al. 2015).
- **Learning checks use only odours that excite the US compartments**: evoked response positive in both the shock and the reward compartments by more than 3× its trial-to-trial SD. An odour that doesn't drive those output neurons has no response for learning to change. How many test odours qualify is reported as its own line; the coding checks (sparseness, APL, pattern separation) use all odours.

- **Odour pairs are chosen by rule** (among the qualifying odours), at quantiles of receptor-level similarity across all well-measured test odours, not by hand. Hand-picked pairs could make generalisation look better than it is.
- **The compartment check compares the same Kenyon cells** (those the CS+ activated) inside and outside the shock compartments. Averaging over all Kenyon cells dilutes the effect about 15-fold, since only ~7% respond to an odour; an earlier version of the check did exactly that and failed for the wrong reason.

## Reading the report

- A **pass** means the model reproduces the qualitative finding at that threshold. The thresholds are deliberately loose: they test direction and rough size, not exact values, because the model's numbers (spike counts, a choice rule with an assumed sharpness) are not directly comparable with behavioural scores.
- A **fail on the real circuit** is a result, not a bug to hide: it says which assumption doesn't hold for the real wiring. Report it, then investigate (transmitter predictions, missing inputs, parameter ranges).
- Known gaps are documented rather than checked: weak second-order conditioning, and predictions read from the weights rather than computed by MBON-to-DAN feedback (see `CIRCUIT.md` §9d).

`validation-synthetic.md` is an example report from the synthetic circuit (quick mode). It shows the format only; its numbers say nothing about real flies.