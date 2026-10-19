# Model validation

- Circuit: `data/processed` (8603 neurons)
- Run: 2026-10-09 11:15 UTC, 1500 s, seed 1
- Parameters: `kc_dan` = terminal, `kc_dan_gain` = 0, `graded_input_gain` = 0.0865, `graded_gain` = 0.009766, `mbon_tonic_mV` = 7.317, `learning_rate` = 1.119e-06 (calibrated: graded_input_gain, mbon_tonic_mV, graded_gain, learning_rate)
- **8 of 12 checks passed**

| Check | In flies | Model | Target | Result |
|---|---|---|---|---|
| Sparse Kenyon cell code | Each odour activates about 5-10% of Kenyon cells. (Turner et al. 2008; Honegger et al. 2011) | median 7.9% (range 4.0%-11.1%, 16 odours) | median 2-20% | pass |
| APL keeps the code sparse | Blocking APL makes Kenyon cell responses larger and less odour-specific. (Lin et al. 2014) | median active 18.2% without APL vs 7.9% (2.3x) | >= 1.5x more active | pass |
| Pattern separation | Odour representations are less correlated in Kenyon cells than in projection neurons. (Campbell et al. 2013) | 92 of 120 odour pairs less correlated in KCs (77%) | >= 70% of pairs | pass |
| Odours that excite the US compartments | Learning can only be read out for odours that drive the output neurons it changes. ((selection rule)) | 16 of 16 test odours; not: none | reported; learning checks use these | info |
| Generalisation grows with odour similarity | Flies generalise more between similar odours; the untrained odour is avoided more. (Campbell et al. 2013; Barth et al. 2014) | Spearman rho(similarity, CS- change) = -0.70 over 5 pairs (similarity -0.16 to +0.94) | rho < 0 | pass |
| Odour-specific memory | Training changes the response to the trained odour, not to a dissimilar one. (Tully & Quinn 1985; Hige et al. 2015) | CS+ -60%, CS- -4% (acetic acid / ethyl butyrate) | CS+ <= -30%, |CS-| < 15% | pass |
| Plasticity is compartment-specific | Dopamine changes KC-MBON synapses only in the compartments it innervates. (Hige et al. 2015; Aso & Rubin 2016) | synapses of CS+ Kenyon cells: 92% of initial in shock compartments, 100% elsewhere | < 90% in, > 97% elsewhere | **FAIL** |
| Acquisition curve | Memory grows with the number of pairings and saturates. (Tully & Quinn 1985) | 0 trials: -0.11, 1 trials: +0.08, 2 trials: +0.22, 3 trials: +0.33, 5 trials: +0.57 | PI(0) < 0.15, non-decreasing, PI(max) > PI(1) | pass |
| Shock teaches avoidance, reward approach | Flies avoid odours paired with shock and approach odours paired with sugar. (Tully & Quinn 1985; Tempel et al. 1983) | PI shock +0.33, reward +0.09 (positive = as taught) | both > 0.3 | **FAIL** |
| PPL1 dopamine neurons are needed for shock learning | Blocking these dopamine neurons abolishes aversive memory. (Schwaerzel et al. 2003; Aso et al. 2010) | PI -0.01 with PPL1 silenced vs +0.33 intact | |PI| < 0.1 | pass |
| PAM dopamine neurons are needed for reward learning | Blocking PAM neurons abolishes appetitive memory. (Liu et al. 2012; Burke et al. 2012) | PI +0.13 with PAM silenced vs +0.09 intact | |PI| < 0.1 | **FAIL** |
| Backward pairing gives relief learning | An odour that follows a shock becomes attractive, much more weakly than forward pairing makes it aversive. (Tanimoto et al. 2004; Handler et al. 2019) | PI backward -0.40, forward +0.48 (timing rule) | backward < 0, |backward| < forward | pass |
| Extinction (prediction-error dopamine) | Presenting the trained odour without shock weakens avoidance, through an opposing memory formed by reward dopamine neurons; it is reduced, not erased. (Schwaerzel et al. 2002; Felsenberg et al. 2018) | PI +0.46 after training -> +0.41 after 6 unpaired CS+ (without prediction error: +0.33 -> +0.32) | reduced by >= 40%, still >= -0.2 | **FAIL** |
| Blocking (Rescorla-Wagner US prediction) | A cue trained together with one that already predicts the US learns less (Kamin blocking). Prediction-error learning rules predict it; whether flies show it in odour learning is not judged here. (Kamin 1969; Rescorla & Wagner 1972) | X after pretrained A vs control: PI +0.01 vs +0.05 (ratio n/a (control learned too little)); X-only synapses lost +5% vs +5% (ratio 0.88); without US prediction: PI ratio n/a (control learned too little), synapse ratio 0.93 (acetic acid, pentyl acetate; ethyl butyrate as CS-) | reported, not judged | info |

## Details

- **Generalisation grows with odour similarity:** acetic acid / ethyl butyrate: r=-0.16, CS- -4%; pentyl acetate / acetone: r=+0.07, CS- -7%; benzaldehyde / isopentyl acetate: r=+0.17, CS- +1%; phenethyl alcohol / acetone: r=+0.41, CS- -7%; propanoic acid / acetic acid: r=+0.94, CS- -60%
- **Blocking (Rescorla-Wagner US prediction):** Ratio 1 = no blocking, 0 = complete. The synapse ratio is the learning itself; the performance index passes through the output neurons' spike threshold, which turns a small weight loss into a large drop in output and so compresses blocking.

## How to read this

A pass means the model reproduces the qualitative finding at the stated threshold, with parameters calibrated only on Kenyon cell sparseness and learning strength, never on the findings being checked. A known gap (second-order conditioning) is described in `docs/CIRCUIT.md`.
