# MBON transmitters: literature, FlyWire prediction, value used

`used` is the transmitter the circuit uses. **Literature** is Aso et al. 2014 (eLife 3:e04577, Table 1): transmitters of MBON-01 to MBON-19 determined by immunostaining of axon terminals (anti-dVGluT, anti-GAD1, anti-ChAT), consistent with earlier ChAT staining (Séjourné et al. 2011; Plaçais et al. 2013) and a dVGluT enhancer trap (Johard et al. 2008). Those types are listed in `scripts/known_transmitters.csv` and override the prediction. MBON20–22 were "not determined" in Aso et al.; MBON23–35 are atypical MBONs added by Li et al. 2020 (eLife 9:e62576), whose transmitters are only predicted. For all of those the circuit uses FlyWire's image-based prediction (Eckstein et al. 2024), pooled over the type's synapses; `share` is the fraction of the type's output synapses with the top prediction.

**Result of the check (2026-10-10):** for every immunostained type, FlyWire's pooled prediction agrees with Aso et al. except MBON02 (predicted GABA at 47%, glutamatergic in the literature, corrected). The previously flagged types (MBON03, 05, 06, 07: glutamate; MBON10: GABA) all agree. Moving MBON01–19 to the curated table changed no neuron or connection in the extracted circuit.

| type | compartment (Aso 2014) | literature | FlyWire top | share | used | PPL1 syn | PAM syn |
|:--|:--|:--|:--|:--|:--|--:|--:|
| MBON01 | γ5β′2a | glutamate | GLUT | 76% | GLUT | 0 | 397 |
| MBON02 | β2β′2a | glutamate | GABA | 47% | GLUT | 0 | 431 |
| MBON03 | β′2mp | glutamate | GLUT | 64% | GLUT | 2 | 1818 |
| MBON04 | β′2mp_bilateral | glutamate | GLUT | 80% | GLUT | 126 | 989 |
| MBON05 | γ4>γ1γ2 | glutamate | GLUT | 49% | GLUT | 15 | 1470 |
| MBON06 | β1>α | glutamate | GLUT | 49% | GLUT | 19 | 1329 |
| MBON07 | α1 | glutamate | GLUT | 58% | GLUT | 5 | 1556 |
| MBON09 | γ3β′1 | GABA | GABA | 79% | GABA | 4 | 889 |
| MBON10 | β′1 | GABA | GABA | 68% | GABA | 20 | 116 |
| MBON11 | γ1pedc>α/β | GABA | GABA | 82% | GABA | 954 | 61 |
| MBON12 | γ2α′1 | acetylcholine | ACH | 96% | ACH | 471 | 11 |
| MBON13 | α′2 | acetylcholine | ACH | 96% | ACH | 294 | 0 |
| MBON14 | α3 | acetylcholine | ACH | 88% | ACH | 471 | 1 |
| MBON15 | α′1 | acetylcholine | ACH | 96% | ACH | 39 | 6 |
| MBON15-like | α′1 | acetylcholine (as MBON15) | ACH | 98% | ACH | 96 | 1 |
| MBON16 | α′3ap | acetylcholine | ACH | 97% | ACH | 141 | 0 |
| MBON17-like | α′3m | acetylcholine (as MBON17) | ACH | 98% | ACH | 16 | 1 |
| MBON17 | α′3m | acetylcholine | ACH | 95% | ACH | 49 | 0 |
| MBON18 | α2sc | acetylcholine | ACH | 93% | ACH | 137 | 0 |
| MBON19 | α2p3p | acetylcholine | ACH | 98% | ACH | 27 | 0 |
| MBON20 | γ1γ2 | not determined | GABA | 98% | GABA | 25 | 6 |
| MBON21 | γ4γ5 | not determined | ACH | 85% | ACH | 3 | 350 |
| MBON22 | calyx | not determined | ACH | 86% | ACH | 0 | 21 |
| MBON23 | — | predicted only (Li 2020) | ACH | 94% | ACH | 55 | 1 |
| MBON24 | — | predicted only (Li 2020) | ACH | 84% | ACH | 1 | 288 |
| MBON25 | — | predicted only (Li 2020) | GLUT | 79% | GLUT | 51 | 4 |
| MBON26 | — | predicted only (Li 2020) | ACH | 96% | ACH | 27 | 735 |
| MBON27 | — | predicted only (Li 2020) | ACH | 96% | ACH | 3 | 231 |
| MBON28 | — | predicted only (Li 2020) | ACH | 98% | ACH | 80 | 0 |
| MBON29 | — | predicted only (Li 2020) | ACH | 92% | ACH | 3 | 251 |
| MBON30 | — | predicted only (Li 2020) | GLUT | 86% | GLUT | 91 | 27 |
| MBON31 | — | predicted only (Li 2020) | GABA | 88% | GABA | 227 | 4 |
| MBON32 | — | predicted only (Li 2020) | GABA | 75% | GABA | 280 | 10 |
| MBON33 | — | predicted only (Li 2020) | ACH | 97% | ACH | 101 | 75 |
| MBON35 | — | predicted only (Li 2020) | ACH | 98% | ACH | 294 | 13 |
