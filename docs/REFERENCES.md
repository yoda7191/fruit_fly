# References

Every study the code relies on: what it is, what the code uses it for, and where. Citations in the code (comments, protocol descriptions, validation checks, curated tables) use the short names below. Two papers by Aso et al. in 2014 are distinguished as **2014a** (architecture and transmitters, eLife 3:e04577) and **2014b** (valence, eLife 3:e04580).

Bibliographic details were taken from Europe PMC; the two book chapters (Kamin 1969; Rescorla & Wagner 1972) are cited in their standard form.

## Data

- **Dorkenwald et al. 2024.** Dorkenwald S, Matsliah A, Sterling AR, Schlegel P, Yu SC, McKellar CE, et al. Neuronal wiring diagram of an adult brain. *Nature* 634:124-138 (2024). [doi:10.1038/s41586-024-07558-y](https://doi.org/10.1038/s41586-024-07558-y)  
  *Used for:* The FlyWire whole-brain connectome (FAFB v783): every neuron and synapse of the real circuit comes from it. Cited as the data licence (CC BY-NC 4.0) requires.  
  *Where:* `scripts/download_data.sh`, `scripts/extract_mb_circuit.py` (the tables it reads); the brain region meshes the 3D view draws are FlyWire's (`scripts/build_anatomy.py`)

- **Schlegel et al. 2024.** Schlegel P, Yin Y, Bates AS, Dorkenwald S, Eichler K, Brooks P, et al. Whole-brain annotation and multi-connectome cell typing of Drosophila. *Nature* 634:139-152 (2024). [doi:10.1038/s41586-024-07686-5](https://doi.org/10.1038/s41586-024-07686-5)  
  *Used for:* FlyWire's cell-type annotations (`consolidated_cell_types`, `classification`): how the extractor recognises ORNs, PNs, local neurons, KCs, MBONs, DANs, APL and DPM, and the MBON type names (matched to the hemibrain).  
  *Where:* `scripts/download_data.sh`, `scripts/extract_mb_circuit.py` (`assign_groups`)  
  *Also used for:* the neuron skeletons (every FlyWire v783 neuron's shape, made by the same Cambridge group) that the 3D view draws, simplified.  
  *Where:* `scripts/download_skeletons.py`, `scripts/build_anatomy.py`, `frontend/src/morphology.ts`

- **Ito et al. 2014.** Ito K, Shinomiya K, Ito M, Armstrong JD, Boyan G, Hartenstein V, et al. A systematic nomenclature for the insect brain. *Neuron* 81:755-765 (2014). [doi:10.1016/j.neuron.2013.12.017](https://doi.org/10.1016/j.neuron.2013.12.017)  
  *Used for:* The brain's division into neuropils (antennal lobe, mushroom body calyx, peduncle, vertical and medial lobes, lateral horn, ...) and their names. FlyWire's region meshes are these neuropils, transformed into FlyWire space; the 3D view draws them, and the regional APL option splits the APL by the mushroom body ones.  
  *Where:* `scripts/build_anatomy.py`, `frontend/src/viewer.ts`, `scripts/extract_mb_circuit.py` (`mb_region`)

- **Eckstein et al. 2024.** Eckstein N, Bates AS, Champion A, Du M, Yin Y, Schlegel P, et al. Neurotransmitter classification from electron microscopy images at synaptic sites in Drosophila melanogaster. *Cell* 187:2574-2594.e23 (2024). [doi:10.1016/j.cell.2024.03.016](https://doi.org/10.1016/j.cell.2024.03.016)  
  *Used for:* The image-based neurotransmitter predictions in FlyWire's connection tables. Used for every neuron without an established or immunostained transmitter, pooled over the cell type's synapses; noisy per synapse, which is why edges take their neuron's transmitter (Dale's principle) rather than their own prediction.  
  *Where:* `scripts/extract_mb_circuit.py` (`transmitters`, `KNOWN_NT`)

- **Münch & Galizia 2016.** Münch D, Galizia CG. DoOR 2.0--Comprehensive Mapping of Drosophila melanogaster Odorant Responses. *Sci Rep* 6:21841 (2016). [doi:10.1038/srep21841](https://doi.org/10.1038/srep21841)  
  *Used for:* DoOR 2.0, measured odour responses per olfactory receptor: turns an odour name into ORN firing rates ("3-octanol" instead of a random pattern), and odour similarity at the receptor level. Licence CC BY-SA 4.0.  
  *Where:* `core/include/fruit_fly/odours.hpp`, `core/src/odours.cpp`, `scripts/download_door.sh`; the odours' chemical classes in the web app's odour menu come from DoOR's `odor.csv` (`backend/app/model.py`, `odour_classes`)

## Neuron and synapse model

- **Shiu et al. 2024.** Shiu PK, Sterne GR, Spiller N, Franconville R, Sandoval A, Zhou J, et al. A Drosophila computational brain model reveals sensorimotor processing. *Nature* 634:210-219 (2024). [doi:10.1038/s41586-024-07763-9](https://doi.org/10.1038/s41586-024-07763-9)  
  *Used for:* The leaky integrate-and-fire parameters (rest, threshold, reset, membrane and synaptic time constants, refractory period, delay, weight per synapse) and the sign rule (acetylcholine excitatory, GABA and glutamate inhibitory) of a whole-brain model built on the same FlyWire data. The model starts from their values rather than tuning its own.  
  *Where:* `core/include/fruit_fly/params.hpp`, `scripts/extract_mb_circuit.py` (`NT_SIGN`)

- **Liu & Wilson 2013.** Liu WW, Wilson RI. Glutamate is an inhibitory neurotransmitter in the Drosophila olfactory system. *Proc Natl Acad Sci U S A* (2013). [doi:10.1073/pnas.1220560110](https://doi.org/10.1073/pnas.1220560110)  
  *Used for:* Glutamate is inhibitory in the Drosophila antennal lobe (through GluCl): the basis for treating the glutamatergic antennal-lobe local neurons, a third of them, as inhibitory.  
  *Where:* `scripts/extract_mb_circuit.py` (`NT_SIGN` comment)

## Circuit anatomy and transmitters

- **Aso et al. 2014a.** Aso Y, Hattori D, Yu Y, Johnston RM, Iyer NA, Ngo TT, et al. The neuronal architecture of the mushroom body provides a logic for associative learning. *Elife* 3:e04577 (2014). [doi:10.7554/elife.04577](https://doi.org/10.7554/elife.04577)  
  *Used for:* The mushroom body's cell types and compartments, and the transmitter of each MBON type (MBON-01 to 19) by immunostaining of axon terminals (Table 1). Supplies every row of the curated transmitter table, which overrides the predictions; also where MBON dendrites lie (in the lobes), which is why MBON→MBON synapses outside the MB are treated as axonal; and the layout the synthetic circuit copies.  
  *Where:* `scripts/known_transmitters.csv`, `scripts/extract_mb_circuit.py`, `scripts/make_synthetic_mb.py`

- **Li et al. 2020.** Li F, Lindsey JW, Marin EC, Otto N, Dreher M, Dempsey G, et al. The connectome of the adult Drosophila mushroom body provides insights into function. *Elife* 9:e62576 (2020). [doi:10.7554/elife.62576](https://doi.org/10.7554/elife.62576)  
  *Used for:* The hemibrain mushroom body connectome: MBON type names including the atypical MBON20-35 and the "-like" variants grouped with MBON15 and MBON17; and that MBONs and DANs express both inhibitory GluCl and excitatory NMDA receptors, so glutamate's sign onto them is not settled (why measured exceptions are curated). Also where synapses onto dopamine neurons lie: MBON feedback reaches "the dendrites of DANs" from MBON axon termini outside the MB, while inside the lobes MBONs make only "axo-axonal synapses onto a subset of DANs". This is the basis for leaving synapses onto DAN axons inside the MB out of the spiking input (`--dan-input dendritic`).  
  *Where:* `scripts/known_transmitters.csv`, `scripts/extract_mb_circuit.py`

- **Amin et al. 2020.** Amin H, Apostolopoulou AA, Suárez-Grimalt R, Vrontou E, Lin AC. Localized inhibition in the Drosophila mushroom body. *eLife* 9:e56954 (2020). [doi:10.7554/elife.56954](https://doi.org/10.7554/elife.56954)  
  *Used for:* APL's inhibition is spatially localised: local stimulation inhibits nearby compartments, so APL can inhibit different mushroom body compartments differently. Basis of the extractor's `--apl regional`, which replaces each APL by one unit per MB region (calyx, peduncle, vertical lobe, medial lobe), each driven by and inhibiting only the synapses in its region.  
  *Where:* `scripts/extract_mb_circuit.py` (`split_apl`)

- **Barnstedt et al. 2016.** Barnstedt O, Owald D, Felsenberg J, Brain R, Moszynski JP, Talbot CB, et al. Memory-Relevant Mushroom Body Output Synapses Are Cholinergic. *Neuron* 89:1237-1247 (2016). [doi:10.1016/j.neuron.2016.02.015](https://doi.org/10.1016/j.neuron.2016.02.015)  
  *Used for:* Kenyon cells are cholinergic: their transmitter is set to acetylcholine instead of the image-based prediction.  
  *Where:* `scripts/extract_mb_circuit.py` (`KNOWN_NT`)

- **Liu & Davis 2009.** Liu X, Davis RL. The GABAergic anterior paired lateral neuron suppresses and is suppressed by olfactory learning. *Nat Neurosci* 12:53-59 (2009). [doi:10.1038/nn.2235](https://doi.org/10.1038/nn.2235)  
  *Used for:* APL is GABAergic (its transmitter is set to GABA), and APL's response to the trained odour falls after conditioning: evidence for `apl_plasticity` and for APL working in a graded range rather than saturated.  
  *Where:* `scripts/extract_mb_circuit.py` (`KNOWN_NT`), `core/include/fruit_fly/params.hpp`

- **Séjourné et al. 2011.** Séjourné J, Plaçais PY, Aso Y, Siwanowicz I, Trannoy S, Thoma V, et al. Mushroom body efferent neurons responsible for aversive olfactory memory retrieval in Drosophila. *Nat Neurosci* 14:903-910 (2011). [doi:10.1038/nn.2846](https://doi.org/10.1038/nn.2846)  
  *Used for:* ChAT immunoreactivity of MBON types, which Aso et al. 2014a confirmed; supporting evidence behind the curated cholinergic MBONs.  
  *Where:* (via `scripts/known_transmitters.csv`)

- **Plaçais et al. 2013.** Plaçais PY, Trannoy S, Friedrich AB, Tanimoto H, Preat T. Two pairs of mushroom body efferent neurons are required for appetitive long-term memory retrieval in Drosophila. *Cell Rep* 5:769-780 (2013). [doi:10.1016/j.celrep.2013.09.032](https://doi.org/10.1016/j.celrep.2013.09.032)  
  *Used for:* As above: earlier ChAT staining of MBON types, consistent with Aso et al. 2014a.  
  *Where:* (via `scripts/known_transmitters.csv`)

- **Johard et al. 2008.** Johard HA, Enell LE, Gustafsson E, Trifilieff P, Veenstra JA, Nässel DR. Intrinsic neurons of Drosophila mushroom bodies express short neuropeptide F: relations to extrinsic neurons expressing different neurotransmitters. *J Comp Neurol* 507:1479-1496 (2008). [doi:10.1002/cne.21636](https://doi.org/10.1002/cne.21636)  
  *Used for:* The dVGluT enhancer trap (OK371) whose pattern agreed with Aso et al.'s anti-dVGluT staining of glutamatergic MBONs.  
  *Where:* (via `scripts/known_transmitters.csv`)

## Odour mixtures

- **Münch et al. 2013.** Münch D, Schmeichel B, Silbering AF, Galizia CG. Weaker ligands can dominate an odor blend due to syntopic interactions. *Chem Senses* 38:293-304 (2013). [doi:10.1093/chemse/bjs138](https://doi.org/10.1093/chemse/bjs138)  
  *Used for:* At the Drosophila receptor Or22a, mixture responses were fully explained by odorants competing for a single binding site (syntopic interaction). Basis of `mixture = "binding"`: each odour's occupancy is inferred from its own DoOR response, and a compound's response follows from competitive binding.  
  *Where:* `core/include/fruit_fly/params.hpp`, `core/src/experiment.cpp` (`mix_odours`)

- **Silbering & Galizia 2007.** Silbering AF, Galizia CG. Processing of odor mixtures in the Drosophila antennal lobe reveals both global inhibition and glomerulus-specific interactions. *J Neurosci* 27:11966-11977 (2007). [doi:10.1523/jneurosci.3099-07.2007](https://doi.org/10.1523/jneurosci.3099-07.2007)  
  *Used for:* Sensory-neuron responses to mixtures were mostly predictable from the components, while mixture suppression arose in projection neurons through GABAergic inhibition in the antennal lobe. This is why the mixture rule acts only within each receptor, and interactions between glomeruli are left to the modelled antennal lobe local neurons.  
  *Where:* `core/include/fruit_fly/params.hpp`

## Mechanisms: plasticity, dopamine and spontaneous activity

- **Hige et al. 2015.** Hige T, Aso Y, Modi MN, Rubin GM, Turner GC. Heterosynaptic Plasticity Underlies Aversive Olfactory Learning in Drosophila. *Neuron* 88:985-998 (2015). [doi:10.1016/j.neuron.2015.11.003](https://doi.org/10.1016/j.neuron.2015.11.003)  
  *Used for:* Pairing odour with dopamine depresses KC→MBON synapses odour-specifically and only in the dopamine neurons' compartment (the learning rule's form and the compartment-specificity check); MBON-γ1pedc's ~80% response drop after pairing (a benchmark); and that recordings subtract spontaneous spikes, which the readout copies.  
  *Where:* `core/include/fruit_fly/params.hpp`, `core/include/fruit_fly/experiment.hpp`, `fruit_fly/validation.py`

- **Handler et al. 2019.** Handler A, Graham TGW, Cohn R, Morantte I, Siliciano AF, Zeng J, et al. Distinct Dopamine Receptor Pathways Underlie the Temporal Sensitivity of Associative Learning. *Cell* 178:60-75.e19 (2019). [doi:10.1016/j.cell.2019.05.040](https://doi.org/10.1016/j.cell.2019.05.040)  
  *Used for:* The timing rule: dopamine after KC activity depresses the synapse, dopamine before it potentiates, through distinct dopamine receptors. Needed for backward pairing (relief learning).  
  *Where:* `core/include/fruit_fly/params.hpp` (`plasticity_rule`), `backend/app/protocols.py`, `fruit_fly/validation.py`

- **Cervantes-Sandoval et al. 2017.** Cervantes-Sandoval I, Phan A, Chakraborty M, Davis RL. Reciprocal synapses between mushroom body and dopamine neurons form a positive feedback loop required for learning. *Elife* 6:e23789 (2017). [doi:10.7554/elife.23789](https://doi.org/10.7554/elife.23789)  
  *Used for:* KC→DAN synapses are axo-axonic contacts on dopamine-neuron terminals that raise terminal calcium without spikes (TTX-insensitive) and act as a positive gain on dopamine release, needed for normal learning. Basis of `kc_dan = "terminal"`; as ordinary synapses they made odours drive punishment dopamine on their own.  
  *Where:* `core/include/fruit_fly/params.hpp`

- **Zhou et al. 2019.** Zhou M, Chen N, Tian J, Zeng J, Zhang Y, Zhang X, et al. Suppression of GABAergic neurons through D2-like receptor secures efficient conditioning in Drosophila aversive olfactory learning. *Proc Natl Acad Sci U S A* 116:5118-5125 (2019). [doi:10.1073/pnas.1812342116](https://doi.org/10.1073/pnas.1812342116)  
  *Used for:* Conditioning dopamine neurons synapse onto APL and suppress it through D2-like receptors, odour-specifically and lastingly. Basis of `apl_plasticity`.  
  *Where:* `core/include/fruit_fly/params.hpp`, `backend/app/schemas.py`, `frontend/src/types.ts`

- **Hafez et al. 2023.** Hafez OA, Escribano B, Ziegler RL, Hirtz JJ, Niebur E, Pielage J. The cellular architecture of memory modules in Drosophila supports stochastic input integration. *Elife* 12:e77578 (2023). [doi:10.7554/elife.77578](https://doi.org/10.7554/elife.77578)  
  *Used for:* MBON-α3 fires spontaneously at 12.1 Hz (ex vivo whole-cell): the only measured MBON spontaneous rate found, the calibration target for MBON tonic input.  
  *Where:* `core/include/fruit_fly/params.hpp`, `fruit_fly/validation.py` (`--mbon-spontaneous-hz`)

- **Zhao et al. 2018.** Zhao X, Lenek D, Dag U, Dickson BJ, Keleman K. Persistent activity in a recurrent circuit underlies courtship memory in Drosophila. *Elife* 7:e31425 (2018). [doi:10.7554/elife.31425](https://doi.org/10.7554/elife.31425)  
  *Used for:* MBON-γ5β′2a (glutamatergic) excites PAM-γ5 dopamine neurons, measured by imaging: one of the two sources for overriding that connection's sign to excitatory.  
  *Where:* `scripts/known_synapse_signs.csv`

- **Otto et al. 2020.** Otto N, Pleijzier MW, Morgan IC, Edmondson-Stait AJ, Heinz KJ, Stark I, et al. Input Connectivity Reveals Additional Heterogeneity of Dopaminergic Reinforcement in Drosophila. *Curr Biol* 30:3200-3211.e8 (2020). [doi:10.1016/j.cub.2020.05.077](https://doi.org/10.1016/j.cub.2020.05.077)  
  *Used for:* Direct synaptic excitation of PAM-γ5 by MBON-γ5β′2a: the second source for that excitatory sign.  
  *Where:* `scripts/known_synapse_signs.csv`

- **Pavlowsky et al. 2018.** Pavlowsky A, Schor J, Plaçais PY, Preat T. A GABAergic Feedback Shapes Dopaminergic Input on the Drosophila Mushroom Body to Promote Appetitive Long-Term Memory. *Curr Biol* 28:1783-1793.e4 (2018). [doi:10.1016/j.cub.2018.04.040](https://doi.org/10.1016/j.cub.2018.04.040)  
  *Used for:* MBON-γ1pedc's feedback onto PPL1-γ1pedc acts through GABA-B receptors (slow, metabotropic). Basis for giving that connection no fast effect; as a fast synapse it vetoed the γ1pedc shock response.  
  *Where:* `scripts/known_synapse_signs.csv`

- **Felsenberg et al. 2018.** Felsenberg J, Jacob PF, Walker T, Barnstedt O, Edmondson-Stait AJ, Pleijzier MW, et al. Integration of Parallel Opposing Memories Underlies Memory Extinction. *Cell* 175:709-722.e15 (2018). [doi:10.1016/j.cell.2018.08.021](https://doi.org/10.1016/j.cell.2018.08.021)  
  *Used for:* Extinction forms a parallel, opposing (appetitive) memory driven by dopamine neurons signalling the omitted shock, through the MBON-γ1pedc → MBON-γ5β′2a → PAM-γ5 chain. Basis of `prediction_error`, of the extinction preset and check, and of the MBON01→PAM01 sign entry. Also the evidence that MBON-γ5β′2a responds to odours in flies (extinction plasticity was measured in its dendrites, and aversive learning potentiates its CS+ response by releasing feedforward inhibition onto its axons), against which the model's silent MBON-γ5β′2a was judged.  
  *Where:* `core/include/fruit_fly/params.hpp`, `backend/app/protocols.py`, `fruit_fly/validation.py`, `scripts/known_synapse_signs.csv`

## Learning theory

- **Rescorla & Wagner 1972.** Rescorla RA, Wagner AR. A theory of Pavlovian conditioning: variations in the effectiveness of reinforcement and nonreinforcement. In: Black AH, Prokasy WF (eds), *Classical Conditioning II: Current Research and Theory*, pp. 64–99. Appleton-Century-Crofts (1972).  
  *Used for:* Learning is driven by the difference between the US received and the US predicted, summed over the cues present. Basis of `pe_us`, `pe_expectation = "sum"`, and the blocking presets and check.  
  *Where:* `fruit_fly/validation.py`, `backend/app/protocols.py`, `core/include/fruit_fly/params.hpp`

- **Kamin 1969.** Kamin LJ. Predictability, surprise, attention, and conditioning. In: Campbell BA, Church RM (eds), *Punishment and Aversive Behavior*, pp. 279–296. Appleton-Century-Crofts (1969).  
  *Used for:* Blocking: a cue trained together with one that already predicts the US learns less. The blocking presets and the (reported, not judged) blocking check.  
  *Where:* `backend/app/protocols.py`, `fruit_fly/validation.py`

## Validation targets and protocol descriptions

- **Turner et al. 2008.** Turner GC, Bazhenov M, Laurent G. Olfactory representations by Drosophila mushroom body neurons. *J Neurophysiol* 99:734-746 (2008). [doi:10.1152/jn.01283.2007](https://doi.org/10.1152/jn.01283.2007)  
  *Used for:* Odours activate a sparse ~5-10% of Kenyon cells, and KCs barely fire spontaneously (~0.1 Hz). Sparse-code check and KC_ACTIVE_TARGET for calibrating APL; the spontaneous rate is the benchmark that showed the antennal-lobe local neurons were needed.  
  *Where:* `fruit_fly/validation.py`

- **Honegger et al. 2011.** Honegger KS, Campbell RA, Turner GC. Cellular-resolution population imaging reveals robust sparse coding in the Drosophila mushroom body. *J Neurosci* 31:11772-11785 (2011). [doi:10.1523/jneurosci.1099-11.2011](https://doi.org/10.1523/jneurosci.1099-11.2011)  
  *Used for:* Population imaging confirming sparse KC coding: the second source for the sparseness target.  
  *Where:* `fruit_fly/validation.py`

- **Lin et al. 2014.** Lin AC, Bygrave AM, de Calignon A, Lee T, Miesenböck G. Sparse, decorrelated odor coding in the mushroom body enhances learned odor discrimination. *Nat Neurosci* 17:559-568 (2014). [doi:10.1038/nn.3660](https://doi.org/10.1038/nn.3660)  
  *Used for:* Blocking APL makes KC responses larger and less odour-specific: the APL check.  
  *Where:* `fruit_fly/validation.py`

- **Campbell et al. 2013.** Campbell RA, Honegger KS, Qin H, Li W, Demir E, Turner GC. Imaging a population code for odor identity in the Drosophila mushroom body. *J Neurosci* 33:10568-10581 (2013). [doi:10.1523/jneurosci.0682-12.2013](https://doi.org/10.1523/jneurosci.0682-12.2013)  
  *Used for:* Odour representations in the KC population: decorrelation relative to projection neurons, and generalisation tracking similarity. The pattern-separation and generalisation checks.  
  *Where:* `fruit_fly/validation.py`

- **Barth et al. 2014.** Barth J, Dipt S, Pech U, Hermann M, Riemensperger T, Fiala A. Differential associative training enhances olfactory acuity in Drosophila melanogaster. *J Neurosci* 34:1819-1837 (2014). [doi:10.1523/jneurosci.2598-13.2014](https://doi.org/10.1523/jneurosci.2598-13.2014)  
  *Used for:* Flies generalise more between similar odours, and differential training sharpens discrimination: the second source for the generalisation check.  
  *Where:* `fruit_fly/validation.py`

- **Tully & Quinn 1985.** Tully T, Quinn WG. Classical conditioning and retention in normal and mutant Drosophila melanogaster. *J Comp Physiol A* 157:263-277 (1985). [doi:10.1007/bf01350033](https://doi.org/10.1007/bf01350033)  
  *Used for:* The standard T-maze differential conditioning paradigm and its performance index; the acquisition curve. What the model's readout imitates, and the shock-learning and acquisition checks.  
  *Where:* `fruit_fly/validation.py`, `backend/app/protocols.py`

- **Tempel et al. 1983.** Tempel BL, Bonini N, Dawson DR, Quinn WG. Reward learning in normal and mutant Drosophila. *Proc Natl Acad Sci U S A* 80:1482-1486 (1983). [doi:10.1073/pnas.80.5.1482](https://doi.org/10.1073/pnas.80.5.1482)  
  *Used for:* Flies learn to approach an odour paired with sugar: the reward-learning check.  
  *Where:* `fruit_fly/validation.py`

- **Schwaerzel et al. 2003.** Schwaerzel M, Monastirioti M, Scholz H, Friggi-Grelin F, Birman S, Heisenberg M. Dopamine and octopamine differentiate between aversive and appetitive olfactory memories in Drosophila. *J Neurosci* 23:10495-10502 (2003). [doi:10.1523/jneurosci.23-33-10495.2003](https://doi.org/10.1523/jneurosci.23-33-10495.2003)  
  *Used for:* Dopamine is needed for aversive memory (octopamine for appetitive): the PPL1-dependence check.  
  *Where:* `fruit_fly/validation.py`

- **Aso et al. 2010.** Aso Y, Siwanowicz I, Bräcker L, Ito K, Kitamoto T, Tanimoto H. Specific dopaminergic neurons for the formation of labile aversive memory. *Curr Biol* 20:1445-1451 (2010). [doi:10.1016/j.cub.2010.06.048](https://doi.org/10.1016/j.cub.2010.06.048)  
  *Used for:* Specific PPL1 dopamine neurons are needed for aversive memory: the second source for that check.  
  *Where:* `fruit_fly/validation.py`

- **Claridge-Chang et al. 2009.** Claridge-Chang A, Roorda RD, Vrontou E, Sjulson L, Li H, Hirsh J, et al. Writing memories with light-addressable reinforcement circuitry. *Cell* 139:405-415 (2009). [doi:10.1016/j.cell.2009.08.034](https://doi.org/10.1016/j.cell.2009.08.034)  
  *Used for:* PPL1 dopamine neurons write aversive memories: the backend test that silencing PPL1 abolishes shock learning.  
  *Where:* `backend/tests/test_protocols.py`

- **Liu et al. 2012.** Liu C, Plaçais PY, Yamagata N, Pfeiffer BD, Aso Y, Friedrich AB, et al. A subset of dopamine neurons signals reward for odour memory in Drosophila. *Nature* 488:512-516 (2012). [doi:10.1038/nature11304](https://doi.org/10.1038/nature11304)  
  *Used for:* A subset of PAM dopamine neurons signals reward: the PAM-dependence check.  
  *Where:* `fruit_fly/validation.py`

- **Burke et al. 2012.** Burke CJ, Huetteroth W, Owald D, Perisse E, Krashes MJ, Das G, et al. Layered reward signalling through octopamine and dopamine in Drosophila. *Nature* 492:433-437 (2012). [doi:10.1038/nature11614](https://doi.org/10.1038/nature11614)  
  *Used for:* Reward signalling through octopamine and PAM dopamine neurons: the second source for that check.  
  *Where:* `fruit_fly/validation.py`

- **Aso & Rubin 2016.** Aso Y, Rubin GM. Dopaminergic neurons write and update memories with cell-type-specific rules. *Elife* 5:e16135 (2016). [doi:10.7554/elife.16135](https://doi.org/10.7554/elife.16135)  
  *Used for:* Dopamine neurons write and update memories with compartment-specific rules: the compartment-specificity check.  
  *Where:* `fruit_fly/validation.py`

- **Tanimoto et al. 2004.** Tanimoto H, Heisenberg M, Gerber B. Experimental psychology: event timing turns punishment to reward. *Nature* 430:983 (2004). [doi:10.1038/430983a](https://doi.org/10.1038/430983a)  
  *Used for:* Event timing turns punishment into reward: an odour following a shock becomes mildly attractive. The relief-learning check and the backward-pairing preset.  
  *Where:* `fruit_fly/validation.py`, `backend/app/protocols.py`

- **König et al. 2018.** König C, Khalili A, Ganesan M, Nishu AP, Garza AP, Niewalda T, et al. Reinforcement signaling of punishment versus relief in fruit flies. *Learn Mem* 25:247-257 (2018). [doi:10.1101/lm.047308.118](https://doi.org/10.1101/lm.047308.118)  
  *Used for:* Single dopamine neurons reinforce avoidance or approach depending on timing (punishment vs relief): supporting the backward-pairing preset.  
  *Where:* `backend/app/protocols.py`

- **Schwaerzel et al. 2002.** Schwaerzel M, Heisenberg M, Zars T. Extinction antagonizes olfactory memory at the subcellular level. *Neuron* 35:951-960 (2002). [doi:10.1016/s0896-6273(02)00832-2](https://doi.org/10.1016/s0896-6273(02)00832-2)  
  *Used for:* Repeated unreinforced CS+ presentations weaken avoidance (extinction): the extinction preset and check.  
  *Where:* `backend/app/protocols.py`, `fruit_fly/validation.py`

- **Aso et al. 2014b.** Aso Y, Sitaraman D, Ichinose T, Kaun KR, Vogt K, Belliart-Guérin G, et al. Mushroom body output neurons encode valence and guide memory-based action selection in Drosophila. *Elife* 3:e04580 (2014). [doi:10.7554/elife.04580](https://doi.org/10.7554/elife.04580)  
  *Used for:* Activating glutamatergic MBONs repels flies, cholinergic or GABAergic MBONs attracts them: the valence of each output neuron in the T-maze readout.  
  *Where:* `core/include/fruit_fly/analysis.hpp`, `frontend/src/ui/results.ts`, `scripts/make_synthetic_mb.py`

- **Wu et al. 2012.** Wu Y, Ren Q, Li H, Guo A. The GABAergic anterior paired lateral neurons facilitate olfactory reversal learning in Drosophila. *Learn Mem* 19:478-486 (2012). [doi:10.1101/lm.025726.112](https://doi.org/10.1101/lm.025726.112)  
  *Used for:* Flies learn a reversed contingency (and APL helps): the reversal-learning preset.  
  *Where:* `backend/app/protocols.py`

- **Tabone & de Belle 2011.** Tabone CJ, de Belle JS. Second-order conditioning in Drosophila. *Learn Mem* 18:250-253 (2011). [doi:10.1101/lm.2035411](https://doi.org/10.1101/lm.2035411)  
  *Used for:* Second-order conditioning in Drosophila: the second-order preset.  
  *Where:* `backend/app/protocols.py`

- **Yamada et al. 2023.** Yamada D, Bushey D, Li F, Hibbard KL, Sammons M, Funke J, et al. Hierarchical architecture of dopaminergic circuits enables second-order conditioning in Drosophila. *Elife* 12:e79042 (2023). [doi:10.7554/elife.79042](https://doi.org/10.7554/elife.79042)  
  *Used for:* Second-order conditioning needs a feedforward circuit between dopamine subsystems (through an excitatory interneuron): why the model, which reads predictions from weights, shows weak second-order conditioning.  
  *Where:* `backend/app/protocols.py`
