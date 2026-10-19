# Model validation

- Circuit: `data/processed-min3` (8603 neurons)
- Run: 2026-10-10 09:56 UTC, 2089 s, seed 1
- Parameters: `kc_dan` = terminal, `kc_dan_gain` = 0, `apl_plasticity` = True, `graded_input_gain` = 0.06589, `graded_gain` = 0.01758, `mbon_tonic_mV` = 7.415, `learning_rate` = 4.593e-07 (calibrated: graded_input_gain, mbon_tonic_mV, graded_gain, learning_rate)
- **9 of 12 checks passed**

| Check | In flies | Model | Target | Result |
|---|---|---|---|---|
| Sparse Kenyon cell code | Each odour activates about 5-10% of Kenyon cells. (Turner et al. 2008; Honegger et al. 2011) | median 7.0% (range 3.7%-10.9%, 16 odours) | median 2-20% | pass |
| APL keeps the code sparse | Blocking APL makes Kenyon cell responses larger and less odour-specific. (Lin et al. 2014) | median active 23.0% without APL vs 7.0% (3.3x) | >= 1.5x more active | pass |
| Pattern separation | Odour representations are less correlated in Kenyon cells than in projection neurons. (Campbell et al. 2013) | 101 of 120 odour pairs less correlated in KCs (84%) | >= 70% of pairs | pass |
| Odours that excite the US compartments | Learning can only be read out for odours that drive the output neurons it changes. ((selection rule)) | 9 of 16 test odours; not: butyric acid, phenethyl alcohol, benzaldehyde, 1-octen-3-ol, 1-hexanol, geranyl acetate, E2-hexenal | reported; learning checks use these | info |
| Generalisation grows with odour similarity | Flies generalise more between similar odours; the untrained odour is avoided more. (Campbell et al. 2013; Barth et al. 2014) | Spearman rho(similarity, CS- change) = -0.50 over 5 pairs (similarity -0.16 to +0.94) | rho < 0 | pass |
| Odour-specific memory | Training changes the response to the trained odour, not to a dissimilar one. (Tully & Quinn 1985; Hige et al. 2015) | CS+ -63%, CS- +4% (acetic acid / ethyl butyrate) | CS+ <= -30%, |CS-| < 15% | pass |
| Plasticity is compartment-specific | Dopamine changes KC-MBON synapses only in the compartments it innervates. (Hige et al. 2015; Aso & Rubin 2016) | synapses of CS+ Kenyon cells: 93% of initial in shock compartments, 100% elsewhere | < 90% in, > 97% elsewhere | **FAIL** |
| Acquisition curve | Memory grows with the number of pairings and saturates. (Tully & Quinn 1985) | 0 trials: +0.00, 1 trials: +0.03, 2 trials: +0.04, 3 trials: +0.18, 5 trials: +0.24 | PI(0) < 0.15, non-decreasing, PI(max) > PI(1) | pass |
| Shock teaches avoidance, reward approach | Flies avoid odours paired with shock and approach odours paired with sugar. (Tully & Quinn 1985; Tempel et al. 1983) | PI shock +0.18, reward -0.09 (positive = as taught) | both > 0.3 | **FAIL** |
| PPL1 dopamine neurons are needed for shock learning | Blocking these dopamine neurons abolishes aversive memory. (Schwaerzel et al. 2003; Aso et al. 2010) | PI +0.08 with PPL1 silenced vs +0.18 intact | |PI| < 0.1 | pass |
| PAM dopamine neurons are needed for reward learning | Blocking PAM neurons abolishes appetitive memory. (Liu et al. 2012; Burke et al. 2012) | PI -0.07 with PAM silenced vs -0.09 intact | |PI| < 0.1 | pass |
| Backward pairing gives relief learning | An odour that follows a shock becomes attractive, much more weakly than forward pairing makes it aversive. (Tanimoto et al. 2004; Handler et al. 2019) | PI backward -0.08, forward +0.45 (timing rule) | backward < 0, |backward| < forward | pass |
| Extinction (prediction-error dopamine) | Presenting the trained odour without shock weakens avoidance, through an opposing memory formed by reward dopamine neurons; it is reduced, not erased. (Schwaerzel et al. 2002; Felsenberg et al. 2018) | PI +0.16 after training -> +0.14 after 6 unpaired CS+ (without prediction error: +0.18 -> +0.13) | reduced by >= 40%, still >= -0.2 | **FAIL** |
| Blocking (Rescorla-Wagner US prediction) | A cue trained together with one that already predicts the US learns less (Kamin blocking). Prediction-error learning rules predict it; whether flies show it in odour learning is not judged here. (Kamin 1969; Rescorla & Wagner 1972) | X after pretrained A vs control: PI +0.07 vs +0.08 (ratio n/a (control learned too little)); X-only synapses lost +3% vs +4% (ratio n/a (control learned too little)); without US prediction: PI ratio 0.58, synapse ratio n/a (control learned too little); with receptor competition in the compound: PI ratio n/a (control learned too little), synapse ratio n/a (control learned too little) (acetic acid, pentyl acetate; ethyl butyrate as CS-) | reported, not judged | info |

## Details

- **Generalisation grows with odour similarity:** acetic acid / ethyl butyrate: r=-0.16, CS- +4%; acetic acid / acetone: r=+0.10, CS- +21%; pentyl acetate / ethyl butyrate: r=+0.23, CS- -5%; propanoic acid / isopentyl acetate: r=+0.51, CS- +12%; propanoic acid / acetic acid: r=+0.94, CS- -44%
- **Blocking (Rescorla-Wagner US prediction):** Ratio 1 = no blocking, 0 = complete. The synapse ratio is the learning itself; the performance index passes through the output neurons' spike threshold, which turns a small weight loss into a large drop in output and so compresses blocking.

## How to read this

A pass means the model reproduces the qualitative finding at the stated threshold, with parameters calibrated only on Kenyon cell sparseness and learning strength, never on the findings being checked. A known gap (second-order conditioning) is described in `docs/CIRCUIT.md`.
