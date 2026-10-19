# Model validation

- Circuit: `data/processed` (8603 neurons)
- Run: 2026-10-09 08:06 UTC, 1691 s, seed 1
- Parameters: `kc_dan` = terminal, `kc_dan_gain` = 0, `graded_gain` = 0.005859, `mbon_tonic_mV` = 8.538, `mbon_tonic_by_type` = 35 values, `learning_rate` = 2.447e-06 (calibrated: mbon_tonic_mV, mbon_tonic_by_type, graded_gain, learning_rate)
- **9 of 12 checks passed**

| Check | In flies | Model | Target | Result |
|---|---|---|---|---|
| Sparse Kenyon cell code | Each odour activates about 5-10% of Kenyon cells. (Turner et al. 2008; Honegger et al. 2011) | median 5.4% (range 1.6%-10.0%, 16 odours) | median 2-20% | pass |
| APL keeps the code sparse | Blocking APL makes Kenyon cell responses larger and less odour-specific. (Lin et al. 2014) | median active 17.7% without APL vs 5.4% (3.3x) | >= 1.5x more active | pass |
| Pattern separation | Odour representations are less correlated in Kenyon cells than in projection neurons. (Campbell et al. 2013) | 90 of 120 odour pairs less correlated in KCs (75%) | >= 70% of pairs | pass |
| Odours that excite the US compartments | Learning can only be read out for odours that drive the output neurons it changes. ((selection rule)) | 7 of 16 test odours; not: butyric acid, phenethyl alcohol, propanoic acid, acetic acid, benzaldehyde, 1-hexanol, geranyl acetate, E2-hexenal, acetone | reported; learning checks use these | info |
| Generalisation grows with odour similarity | Flies generalise more between similar odours; the untrained odour is avoided more. (Campbell et al. 2013; Barth et al. 2014) | Spearman rho(similarity, CS- change) = -0.50 over 5 pairs (similarity -0.13 to +0.72) | rho < 0 | pass |
| Odour-specific memory | Training changes the response to the trained odour, not to a dissimilar one. (Tully & Quinn 1985; Hige et al. 2015) | CS+ -61%, CS- -27% (ethyl acetate / 1-octen-3-ol) | CS+ <= -30%, |CS-| < 15% | **FAIL** |
| Plasticity is compartment-specific | Dopamine changes KC-MBON synapses only in the compartments it innervates. (Hige et al. 2015; Aso & Rubin 2016) | synapses of CS+ Kenyon cells: 80% of initial in shock compartments, 100% elsewhere | < 90% in, > 97% elsewhere | pass |
| Acquisition curve | Memory grows with the number of pairings and saturates. (Tully & Quinn 1985) | 0 trials: +0.09, 1 trials: +0.54, 2 trials: +0.67, 3 trials: +0.77, 5 trials: +0.81 | PI(0) < 0.15, non-decreasing, PI(max) > PI(1) | pass |
| Shock teaches avoidance, reward approach | Flies avoid odours paired with shock and approach odours paired with sugar. (Tully & Quinn 1985; Tempel et al. 1983) | PI shock +0.77, reward +0.23 (positive = as taught) | both > 0.3 | **FAIL** |
| PPL1 dopamine neurons are needed for shock learning | Blocking these dopamine neurons abolishes aversive memory. (Schwaerzel et al. 2003; Aso et al. 2010) | PI +0.01 with PPL1 silenced vs +0.77 intact | |PI| < 0.1 | pass |
| PAM dopamine neurons are needed for reward learning | Blocking PAM neurons abolishes appetitive memory. (Liu et al. 2012; Burke et al. 2012) | PI -0.07 with PAM silenced vs +0.23 intact | |PI| < 0.1 | pass |
| Backward pairing gives relief learning | An odour that follows a shock becomes attractive, much more weakly than forward pairing makes it aversive. (Tanimoto et al. 2004; Handler et al. 2019) | PI backward -0.19, forward +0.61 (timing rule) | backward < 0, |backward| < forward | pass |
| Extinction (prediction-error dopamine) | Presenting the trained odour without shock weakens avoidance, through an opposing memory formed by reward dopamine neurons; it is reduced, not erased. (Schwaerzel et al. 2002; Felsenberg et al. 2018) | PI +0.80 after training -> +0.67 after 6 unpaired CS+ (without prediction error: +0.77 -> +0.77) | reduced by >= 40%, still >= -0.2 | **FAIL** |
| Blocking (Rescorla-Wagner US prediction) | A cue trained together with one that already predicts the US learns less (Kamin blocking). Prediction-error learning rules predict it; whether flies show it in odour learning is not judged here. (Kamin 1969; Rescorla & Wagner 1972) | X after pretrained A vs control: PI +0.78 vs +0.68 (ratio 1.14); X-only synapses lost +5% vs +9% (ratio 0.54); without US prediction: PI ratio 1.13, synapse ratio 0.98 (ethyl acetate, ethyl butyrate; 1-octen-3-ol as CS-) | reported, not judged | info |

## Details

- **Generalisation grows with odour similarity:** ethyl acetate / 1-octen-3-ol: r=-0.13, CS- -27%; ethyl acetate / pentyl acetate: r=+0.16, CS- -19%; 2-heptanone / ethyl butyrate: r=+0.31, CS- -9%; pentyl acetate / 1-octen-3-ol: r=+0.58, CS- -88%; pentyl acetate / 2-heptanone: r=+0.72, CS- -48%
- **Blocking (Rescorla-Wagner US prediction):** Ratio 1 = no blocking, 0 = complete. The synapse ratio is the learning itself; the performance index passes through the output neurons' spike threshold, which turns a small weight loss into a large drop in output and so compresses blocking.

## How to read this

A pass means the model reproduces the qualitative finding at the stated threshold, with parameters calibrated only on Kenyon cell sparseness and learning strength, never on the findings being checked. A known gap (second-order conditioning) is described in `docs/CIRCUIT.md`.
