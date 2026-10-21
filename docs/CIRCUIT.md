# Why these neurons? The circuit behind the model

The model includes eight groups of neurons. Each one is there because olfactory conditioning in the fly *cannot happen without it*, or because leaving it out would make the model misbehave in a known way. This document goes through them in the order a signal travels: from the antenna to the learning site, then to behaviour. It ends with what was deliberately left out and which assumptions the model makes.

A useful frame from psychology: in Pavlovian terms, the **odour is the conditioned stimulus (CS)**, **shock is the unconditioned stimulus (US)**, and the **learned response is avoidance of the odour**. The mushroom body is where CS and US information meet. Every group below either carries the CS, carries the US, shapes how the CS is represented, or reads out the result.

```
  CS pathway                 US pathway
  ----------                 ----------
  odour
   |
  ORN  (receptor neurons)
   |
  ALPN (projection neurons)
   |
  KC   (Kenyon cells) <----> APL (inhibition), DPM
   |
   |  plastic synapses  <--- dopamine --- DAN_PPL1 (punishment)
   v                                      DAN_PAM  (reward)
  MBON (output neurons)  ---> approach / avoid
       \______ feedback _____^
```

---

## 1. ORN — olfactory receptor neurons

**What they are.** Sensory neurons in the antenna and maxillary palp, roughly 1,300 per side. Each ORN expresses one type of olfactory receptor, and there are about 50 receptor types. All ORNs expressing the same receptor send their axons to the same spot in the antennal lobe, a ball of neuropil called a **glomerulus**. In FlyWire, their cell types are named after their glomerulus (e.g. `ORN_DA1`).

**Why they're in the model.** They are where odours enter the brain, so they're the natural place to inject a stimulus. An odour activates a *combination* of receptor types to different degrees. Ethyl acetate activates one set of glomeruli, benzaldehyde another. This combinatorial code is how ~50 receptor types can distinguish thousands of odours. In the model, an odour = "drive the ORNs of these glomeruli at this rate", which is exactly how the nervous system receives it.

**Why start this early rather than at the projection neurons?** Two reasons. First, it lets real receptor data drive the model: `core/src/odours.cpp` turns DoOR 2.0 measurements for ~690 odours into per-ORN firing rates, so the stimulus can be "3-octanol" rather than a random pattern. Second, many ORNs converge on few PNs, and that convergence is part of the circuit's computation (it averages out noise in single ORNs).

**Why prune them.** The extractor keeps only ORNs that connect to projection neurons that reach the mushroom body. The rest are irrelevant to learning here and would only slow the simulation.

---

## 1b. ALLN — antennal lobe local neurons

Local neurons stay inside the antennal lobe and connect glomeruli with each other. Most are inhibitory: GABAergic, or glutamatergic acting through the GluCl chloride channel. A minority are cholinergic and excitatory. They inhibit receptor neuron terminals (presynaptic inhibition) and projection neurons, which normalises odour responses and holds spontaneous activity down.

FlyWire's class `ALLN` contains 429 of them, all connected to the receptor and projection neurons kept in this circuit (147 GABAergic, 138 glutamatergic, 79 cholinergic by predicted transmitter). They were added after the real-circuit run showed what happens without them. Projection neurons fired spontaneously at 37 Hz on average (10% above 112 Hz), and half the Kenyon cells fired with no odour, held back only by an APL neuron driven to its ceiling. With the local neurons, and no parameter changed, PNs fire spontaneously at 5.7 Hz and KCs at 0.05 Hz, close to the ~0.1 Hz measured in vivo (Turner et al. 2008).

## 2. ALPN — antennal lobe projection neurons

**What they are.** Output neurons of the antennal lobe, about 150 per side. Most are **uniglomerular**: each collects input from a single glomerulus, so each PN reports on one receptor type. The excitatory (cholinergic) ones project along the medial antennal lobe tract to two places: the mushroom body **calyx** (the learning pathway) and the **lateral horn** (the innate-behaviour pathway).

**Why they're in the model.** They are the only route by which olfactory information reaches the Kenyon cells, so without them the mushroom body gets no odour input. They also transform the signal: PNs respond more broadly and more strongly than their ORNs, which spreads odour representations across the available range of firing rates before they reach the KCs.

**Why only the ones that contact KCs.** The FlyWire `ALPN` class includes PNs that project only to the lateral horn, multiglomerular PNs, and GABAergic PNs that mostly skip the calyx. Filtering to "PNs with at least one synapse onto a KC" keeps precisely the ones that carry odour information into the learning centre.

---

## 3. KC — Kenyon cells

**What they are.** The intrinsic neurons of the mushroom body, about 2,000 per side. Each KC has dendritic "claws" in the calyx, **about 6 on average**, each wrapped around a bouton from a different PN. Their axons run in parallel bundles that form the mushroom body **lobes**. KCs come in three main classes (γ, α′/β′, α/β), whose axons fill different lobes and support different phases of memory.

**Why they're in the model — this is the centre of it all.** KCs are where odour identity becomes something the fly can learn about. Three properties matter:

1. **Random, combinatorial wiring.** Which PNs a KC samples is close to random (Caron et al. 2013). Each KC therefore detects a random *combination* of glomeruli.
2. **Coincidence detection.** A KC needs several of its claws active at the same time to fire. One active PN isn't enough.
3. **Expansion and sparseness.** ~150 PNs expand onto ~2,000 KCs, and any given odour activates only about **5–10% of them**. Each odour therefore gets its own small, mostly non-overlapping set of active KCs.

Together these make the mushroom body a **pattern separator**. Two similar odours that overlap heavily at the PN level end up with much less overlap at the KC level. This is the same computational idea attributed to cerebellar granule cells and to the dentate gyrus in the hippocampus, which makes it a nice bridge to mammalian learning theory.

**Why this matters for learning.** Learning in this model changes KC→MBON synapses. Because odour A and odour B activate *different* KCs, weakening "odour A's" synapses leaves odour B's untouched. **Sparse coding is what makes memories odour-specific.** The model shows this directly: with only 3 KCs shared between the two odours, shocking A changed A's MBON response by −83% and B's by +5%.

**Why KC→KC connections are excluded.** The connectome contains many KC-to-KC synapses, mostly between axons in the lobes. Their predicted transmitter is acetylcholine, so a naive model would treat them as excitatory. But their function isn't settled, and as plain recurrent excitation they cause runaway activity where the whole population lights up. The model drops them by default (`excluded_pairs` in `params.hpp`), and you can turn them back on to experiment.

---

## 4. APL — anterior paired lateral neuron

**What it is.** A single giant GABAergic (inhibitory) neuron per hemisphere that innervates the entire mushroom body. It receives input from essentially all KCs and inhibits essentially all KCs back.

**Why it's in the model.** It is what keeps the KC code sparse. It works as **global feedback inhibition**: the more KCs fire, the more APL is excited, and the harder it pushes all KCs back down. It acts like a thermostat that keeps roughly the same small fraction of KCs active regardless of how strong or broad the odour is. Experiments that block APL make KC responses denser and more overlapping, and flies then struggle to tell similar odours apart (Lin et al. 2014).

**Our model reproduces this.** On the synthetic circuit:

| APL gain | KCs active for one odour | MBON firing |
|---|---|---|
| 0 (APL removed) | 33–46% | 237–290 Hz |
| 0.01 | 14% | 108 Hz |
| **0.05 (default)** | **5%** | **28 Hz** |
| 0.2 | 4% | 1 Hz |

Without APL, a third or more of all KCs fire for every odour. Different odours then share most of their active KCs, and learning about one would bleed into the others.

**Why it's modelled as "graded".** APL is a non-spiking neuron. It releases GABA continuously in proportion to its depolarisation, and different parts of its huge arbour can act semi-independently. A spiking model neuron would inhibit in all-or-nothing bursts, which is wrong. So APL gets its own simple rule in the simulator: *output ∝ how far above rest its membrane potential is.* (A fancier model would split APL into local compartments; the single-compartment version is enough to get sparseness right.)

---

## 5. DPM — dorsal paired medial neuron

**What it is.** Another single large neuron per hemisphere, reciprocally connected with KCs throughout the lobes. It releases serotonin (and likely GABA) and is electrically coupled to APL.

**Why it's in the model.** Honestly, as a **placeholder**. DPM isn't needed for learning to form. It's known to be needed for memory to *last*: the classic learning gene *amnesiac* is expressed in DPM, and silencing DPM after training disrupts intermediate-term memory. In the current model, DPM's output is serotonergic, so it gets sign 0 and does nothing. It's included so that a future "consolidation" extension, such as DPM feedback stabilising recently changed weights, doesn't require re-extracting the circuit.

---

## 6. MBON — mushroom body output neurons

**What they are.** Only about 35 neurons per hemisphere, in 21 types, and yet they're the entire output of the mushroom body. Each MBON's dendrites cover a specific region of the lobes, called a **compartment**. The lobes are divided into 15 such compartments, and each compartment is where one type of MBON listens to all the KC axons passing through.

**Why they're in the model.**
1. **They're where memory is stored.** The synapses that change during learning are KC→MBON synapses. After aversive conditioning, the KC→MBON synapses carrying odour A weaken in the compartments that received punishment dopamine (shown directly by Hige et al. 2015).
2. **They're the readout of behaviour.** Different MBONs push behaviour in different directions. Activating some drives approach, activating others drives avoidance (Aso et al. 2014). The fly's choice is thought to depend on the **balance** across MBONs. Weakening an approach-promoting MBON's response to odour A tips the balance toward avoiding A. So "MBON response to odour A dropped in the punishment compartments" is the model's version of "the fly learned to avoid A."

**Transmitter matters.** MBONs are glutamatergic, GABAergic, or cholinergic. The model uses that to set the sign of their outputs (including their feedback onto DANs, see §9).

**From MBONs to behaviour.** The model turns the balance of approach- and avoidance-promoting MBON activity into a predicted T-maze choice; see §9c.

---

## 7. DAN_PPL1 — the punishment signal

**What they are.** A small cluster of dopaminergic neurons, about 12 per hemisphere, that innervate the **vertical lobes** (α, α′) and the γ1 region. They respond to aversive events such as electric shock, bitter taste, and heat.

**Why they're in the model.** They are the **US for aversive learning**. Artificially activating PPL1 dopamine neurons paired with an odour is enough to make flies avoid that odour, even without a real shock (Claridge-Chang et al. 2009, Aso et al. 2012). So "deliver a shock" in the model means "make the PPL1 neurons fire". That's the biologically meaningful version of a shock, since the rest of the pain pathway isn't in the circuit.

**Why they target specific MBONs.** Each DAN type innervates particular compartments, so its dopamine affects only the KC→MBON synapses there. That's why in the model only MBON01–04 (the PPL1 compartments) changed.

**How the model knows which MBONs each DAN reaches.** The model infers it from the connectome itself. DANs make synapses directly onto the MBONs in their compartment, so the number of DAN→MBON synapses is used as "how much of this MBON's dopamine comes from this DAN." Nothing about compartments is hard-coded, and `dopamine_targets()` in `analysis.cpp` reads the compartments straight from those synapses.

---

## 8. DAN_PAM — the reward signal

**What they are.** The large dopaminergic cluster, about 90–100 neurons per hemisphere, innervating the **horizontal lobes** (β, β′, most of γ). Most PAM types respond to rewards like sugar or water.

**Why they're in the model.** They're the US for **appetitive** conditioning (odour + sugar → approach). Even though the first experiment uses shock, including PAM from the start does three things:

1. **It's the control.** When PPL1 is stimulated, PAM compartments shouldn't change. In the model they don't (MBON05–10 stay flat), which confirms that learning is compartment-specific rather than a global effect.
2. **Reward learning comes free.** Drive PAM instead of PPL1 during odour A and you've run an appetitive experiment with no code changes.
3. **Opposing memories.** Real flies can hold aversive and appetitive memories of different odours at once, in different compartments. That's only possible if both DAN systems are present.

**A nuance for the README.** PAM isn't *purely* reward. A few PAM types (e.g. those in γ3 and β′1) respond to punishment too. Using the connectome's cell-type labels means you can refine "which DANs = shock" later without changing the code.

---

## 9. Connections between groups that are included automatically

Because the extractor keeps *every* synapse between the selected neurons, some important loops come along for free:

- **MBON → DAN feedback.** Many MBONs synapse onto DANs. This loop is implicated in memory extinction (the original memory is countered by new learning in a compartment of opposite valence) and in second-order conditioning. You won't see much of it in a basic training protocol, but it's the natural next experiment.
- **MBON → MBON connections.** Some MBONs inhibit others, so a change in one compartment can propagate to another.
- **DAN → KC synapses.** DANs also synapse onto KC axons, which is biologically where dopamine acts (through the dopamine receptor DopR1 and the *rutabaga* adenylyl cyclase, the molecular coincidence detector of KC activity and dopamine). The model folds this into the three-factor rule rather than simulating the molecules.

---

## 9b. What real odours show: pattern separation and generalization

With DoOR odours, the model reproduces a graded effect of odour similarity on learning (synthetic circuit, 3 training trials):

| Odour pair | Similarity at receptors | at Kenyon cells | CS+ change | CS− change |
|---|---|---|---|---|
| ethyl acetate / benzaldehyde | −0.02 | −0.01 | −86% | 0% |
| pentyl acetate / isopentyl acetate | 0.69 | 0.43 | −65% | −41% |

The Kenyon cell layer reduces overlap between similar odours (0.69 → 0.43) but can't remove it. The shared KCs carry some of the punishment to the unpunished odour, which is **stimulus generalization**, the same phenomenon Pavlov described in dogs. Flies also generalize more between chemically similar odours, and APL inhibition sharpens their discrimination. This makes a good experiment for the portfolio: vary APL strength and measure how CS− generalization changes.

## 9c. From output neurons to behaviour: the T-maze readout

Fly memory is measured in a **T-maze**. A group of flies is pushed to a junction with one odour coming from each arm, and the **performance index** is (flies choosing the "correct" arm − flies choosing the other) ÷ all flies. 1 means every fly chose as trained; 0 means no learning. To make the model's output comparable with published numbers, it ends in the same measurement.

**Step 1: each output neuron's valence.** Activating individual MBON types tells flies which way to go: glutamatergic MBONs repel, cholinergic and GABAergic ones attract (Aso et al. 2014, *eLife* 3:e04580). The model gives each MBON valence −1 (GLUT), +1 (ACH or GABA) or 0 (anything else), using its predicted transmitter.

The transmitter has to come from the **whole brain**. MBONs send most of their output to brain regions outside the mushroom body, which the extractor leaves out of the circuit. Judged only by in-circuit synapses, many real MBONs would have no transmitter at all, or the wrong one. So `extract_mb_circuit.py` records each neuron's dominant transmitter over *all* its output synapses in the `nt_type` column, and the loader uses that, falling back to in-circuit synapses only for older files.

**Step 2: approach drive per odour.**
`drive = Σ valence × spikes ÷ scale` over MBONs with a valence, where `scale` is the larger of the two odours' naive (pre-training) valenced output `Σ spikes`. The same scale is used before and after training, so drives keep their absolute size: an odour that evokes little output of either kind stays near-neutral, however lopsided that little output is. (An earlier version divided each odour by its own output, a ratio; that inflated performance indices for weakly driven odours.)

**Step 3: learned drive.** `(drive CS+ − drive CS−) after training − (the same before)`. Subtracting the naive difference removes innate odour preferences. Real experiments do the same with a reciprocal design, training a second group with the odour roles swapped and averaging.

**Step 4: choice.** `p(CS+) = 1 / (1 + e^(−sharpness × learned drive))`, with sharpness 6 by default. The performance index is `2p − 1`, signed so that positive always means "learned as taught": avoiding the CS+ after shock, approaching it after reward. The model also samples a group of flies (100 by default) from that probability, to show the trial-to-trial scatter a real experiment would have.

**Why it works out right.** In the fly, the shock-signalling PPL1 dopamine neurons target compartments whose MBONs mostly promote approach; reward-signalling PAM neurons target compartments whose MBONs mostly promote avoidance. Shock weakens the CS+'s approach output, so flies avoid it; reward weakens its avoidance output, so flies approach it. The synthetic circuit follows this layout. In the real FlyWire circuit it comes from the data.

**When there is no answer.** If no MBON has a known transmitter, or those that do stay silent for an odour, the drives are undefined and the result is marked *not valid*, with no number. Reporting 0 would wrongly say "the fly didn't learn". The number of MBONs with a valence is always reported, to make this diagnosable.

**Assumptions to state.**
- One valence per transmitter is a simplification. A few MBON types don't follow the rule, and the effect of activating an MBON can depend on context.
- The choice rule (a logistic function with one sharpness) is a standard psychophysics model, but the sharpness value is not measured; it sets how strongly a given drive difference turns into a decision. Compare conditions within the model (e.g. sweeps over APL gain) rather than reading absolute values as predictions.
- Flies choose independently; real groups interact somewhat.

## 9c-2. Spontaneous output neurons, and what counts as a response

MBONs fire spontaneously in flies (MBON-α3: 12.1 Hz, ex vivo, eLife 77578; MBON-γ1pedc in vivo, Hige et al. 2015). With `mbon_tonic_mV` the model gives every MBON a constant depolarising input; validation calibrates it so the median MBON fires at 12.1 Hz at rest, the only measured rate found, so applying it to every type is an assumption. Near threshold, KC input then changes the rate continuously, so depression of a weak input still shows in the output.

Once MBONs fire at rest, part of every odour window is spontaneous activity. Recordings subtract it (Hige et al. 2015), and so does the model: `Experiment.settle()` measures each neuron's spontaneous rate over a rest window, and the compartment change and T-maze readouts use evoked activity, spikes minus that expectation, which can be negative. Counting spontaneous spikes as response diluted learned changes and let trial noise dominate (a performance index of −0.16 with no training at all). An odour that doesn't excite a compartment above its spontaneous rate has no learnable response there; the validation's learning checks therefore use only odours that do (see `validation.md`).

## 9d. Prediction error: extinction and blocking (optional, off by default)

Dopamine neurons in flies, as in mammals, signal more than "shock now". Two optional mechanisms add the error-driven part of learning, following the Rescorla-Wagner rule (Rescorla & Wagner 1972), in which learning is driven by the difference between the US received and the US predicted.

**The prediction.** For each US, the circuit's expectation is read from the plastic synapses of the currently active Kenyon cells in that US's compartments. This is the honest weak point: the real fly computes predictions through MBON-to-DAN feedback circuits, and the model reads the result directly from the weights instead. Two ways of combining the cues present (`pe_expectation`):

- `"average"` (the default, used by earlier results): the fraction of the active KCs' drive that is already lost. A trained odour mixed with a new one predicts less, in proportion to its share of the KC activity.
- `"sum"` (Rescorla-Wagner): the learned loss summed over every active KC, `Σ (w0 − w) · min(1, trace)`, divided by a fixed asymptote λ, the naive drive of a typical single odour (`pe_ref_active_frac` of all KCs, 7% by default, the calibrated sparseness). Cues present add their predictions, so a trained odour keeps its full prediction inside a compound. This works because the KC code of a compound is close to the union of its parts' codes (A+C keeps 85-87% of each odour's KCs on the synthetic circuit).

**Omitted US: extinction** (`prediction_error`). An expected US that does not arrive drives the opposite dopamine neurons (expected shock omitted → PAM), forming the opposing memory found in fly extinction (Felsenberg et al. 2018).

**Predicted US: blocking** (`pe_us`). While the US drives its dopamine neurons, their rate is scaled by `1 − expectation`. Learning then slows as a memory forms, and a cue trained together with one that already predicts the US learns less (Kamin blocking). Compound stimuli (`"A+C"` steps) present several odours together: each ORN fires at its baseline plus the sum of the odours' changes from baseline, with no mixture interactions.

On the real FlyWire circuit, blocking is clear at the synapses (X-only synapse ratio 0.59, against 0.84 without the US prediction; 0.49 vs 0.71 with `--min-syn 3`) and weaker in the performance index (0.87 vs 1.00; 0.60 vs 0.82).

**What the model shows** (synthetic circuit, `python -m fruit_fly.validation --quick --calibrate`): with A pretrained 10 times, a new cue X trained in compound with A loses about half as much synaptic weight as in the control group (ratio 0.51; 1.15 without the US prediction). The performance index shows less (ratio 0.63), because the output neurons' spike threshold turns a small weight loss into a large output drop. Blocking is partial, not complete, for two model reasons, both visible in the numbers: the prediction approaches its asymptote slowly (learning slows as `1 − expectation`), and an odour whose KCs carry less weight than λ can never fully predict the US (the ceiling was 0.77-1.0 across four odours). **Two corrections to the prediction (2026-10-10).** (1) The expectation of each US now weights every MBON by the share of its dopamine input that comes from that US's DANs (the share by which dopamine reaches its synapses). On FlyWire 57 of 96 MBONs receive some dopamine synapses from both clusters; counted yes/no, shock training's depression read as a reward expectation. (2) `pe_omission = "net"` (used by the validation's Rescorla–Wagner settings): one signed prediction per cue, so an omitted US drives the opposite DANs by `max(0, E_shock − E_reward)`. With separate predictions, the extinction memory itself read as a reward expectation whose omission drove PPL1 (5.7 Hz during unpaired CS+), so extinction undid itself. The cost: on the synthetic circuit extinction falls from −43% to −36%, just under the 40% target, because a growing extinction memory now cancels part of the shock prediction, as Rescorla–Wagner says it should.

Under the `"sum"` expectation, extinction is weaker than under `"average"` (about a third instead of half), with the omission signal strength `pe_gain_hz` left as it was set before the change, not retuned to the check.

## 9d-2. Odour mixtures

Compound stimuli (`"A+C"`) used to add each odour's change from baseline at every ORN, which can exceed what a receptor neuron does. `mixture = "binding"` (option; default `"linear"`) uses competitive binding at one receptor site, which fully explained Or22a's mixture responses (Münch et al. 2013): each odour is a full agonist (toward `orn_max_rate_hz`, 200 Hz) or, if it inhibits the ORN, a full inverse agonist (toward 0), with the occupancy that reproduces its own response; a mixture then saturates, and an inhibiting odour pulls an excited ORN down. Partial agonism can't be inferred from one DoOR concentration and isn't modelled. Interactions between glomeruli are left to the antennal lobe local neurons, where they arise in flies (Silbering & Galizia 2007). Effect on blocking, the only check with compounds (FlyWire; ratio 1 = no blocking): PI ratio 1.03 with linear mixing, 0.53 with binding; synapse ratio 0.91 and 0.93. The learning at X's own synapses is the same; the readout changes, because a saturating compound drives shared ORNs less than the sum.

## 9e. Synapses whose location matters

A point neuron integrates every synapse onto it as input to its spiking. Two kinds of synapse in the connectome sit elsewhere, and are modelled by location:

- **Kenyon cell → dopamine neuron** synapses (125k in FlyWire) are axo-axonic, onto DAN terminals in the lobes. They raise terminal calcium locally, without spikes (TTX-insensitive), and act as "a positive gain signal ... for DA release" needed for normal learning (Cervantes-Sandoval et al. 2017). As ordinary synapses they made some odours drive punishment dopamine neurons on their own, so every unpaired odour acted like a mild shock. With `kc_dan = "terminal"` they scale each DAN spike's release by `1 + kc_dan_gain × a`, a being the DAN's KC input activity relative to a typical odour. The gain has no measured value (the published effects are shown as bar charts); results barely changed between gains 0 and 1.
- **Signs measured against the transmitter rule.** A glutamatergic MBON is treated as inhibitory, but MBON-γ5β′2a (MBON01) excites PAM-γ5 (PAM01) dopamine neurons (Zhao et al. 2018; Otto et al. 2020), presumably through NMDA receptors, which DANs express alongside GluCl (Aso et al. 2019). That feedback is how extinction memory forms in flies (Felsenberg et al. 2018): aversive training depresses the GABAergic MBON-γ1pedc, which disinhibits MBON-γ5β′2a, which excites PAM-γ5 when the CS+ returns without shock. `scripts/known_synapse_signs.csv` sets such measured signs per cell-type pair, with sources; MBON01 → PAM01 is the first entry. Other glutamatergic MBON → DAN connections stay inhibitory: their sign isn't measured (MBON-α1 → PAM-α1 is debated).
- **Synapses onto dopamine neuron axons.** DAN dendrites lie outside the MB; their axons tile the lobes (Aso et al. 2014a). MBON feedback reaches "the dendrites of DANs" from MBON axon termini outside the MB, while inside the lobes MBONs make only "axo-axonal synapses onto a subset of DANs" (Li et al. 2020). As spike-driving input, those in-lobe synapses let odours alone fire punishment DANs: MBON-α3 → PPL1-α3 (91 of its 118 synapses in the vertical lobe) drove PPL106 to 25 Hz with ethyl butyrate and no US. The model learned from odour exposure: with every PAM neuron silenced, reward training still gave PI +0.19 (+0.04 with plasticity off). The extractor now leaves synapses onto DANs inside the MB out of the spiking network (`--dan-input dendritic`, default; KC → DAN stays, handled by `kc_dan`). PAM-silenced reward learning fell to +0.02. Intact reward learning fell too (+0.36 → +0.22, below the 0.3 target): a third of the earlier reward score was the artefact.
- **MBON → MBON** synapses: 64% lie outside the mushroom body (CRE, SMP, SIP), mostly on MBON axons. The extractor keeps only those inside the MB neuropils, on MBON dendrites (`--mbon-mbon in-mb`, the default). The documented feed-forward inhibition, such as MVP2 / MBON-γ1pedc>α/β onto α/β MBONs (Perisse et al. 2016), is inside. Atypical MBONs with dendrites outside the MB lose some real input under this rule.

## 9f. Toward predictions computed by the circuit (open)

In flies the prediction-error signals come from the output network itself: MBONs feed back onto dopamine neurons, and extinction forms through the MBON-γ1pedc → MBON-γ5β′2a → PAM-γ5 chain described in 9e (Felsenberg et al. 2018). The model's prediction-error options read the expectation from the weights instead. Whether the wiring alone produces extinction is tested by the validation's "without prediction error" figures.

Tracing the chain neuron by neuron on FlyWire found three obstacles, two of them fixed:

1. **MBON01 was silent.** One tonic input for all MBONs left strongly inhibited types silent. Each MBON type now gets its own input, calibrated by a damped iteration (the types inhibit each other, so independent bisections didn't converge): all 35 types settle at 10–15 Hz at rest.
2. **PPL1-γ1pedc was vetoed during shock.** MBON-γ1pedc's 358 GABAergic synapses onto PPL1-γ1pedc, as fast synapses, cut its shock response to 1 spike per second, so the main short-term aversive memory site (γ1pedc) barely learned (6% weight loss, against 80% response drop in flies, Hige et al. 2015). That connection acts through metabotropic GABA-B receptors (Pavlowsky et al. 2018) and is now modelled as having no fast effect (`known_synapse_signs.csv`). MBON-γ1pedc's CS+ response then falls by about half after training.
With per-type input and the GABA-B correction, FlyWire passes 9 of 12 checks (10 of 12 with `--min-syn 3`), against 9 and 11 with one input for all MBONs: reward learning becomes PAM-dependent on the default circuit, but memory specificity weakens (CS− −27%) and only 7–8 of 16 odours excite the US compartments. Neither is clearly better, and choosing by pass count would fit the model to its own checks, so uniform input stays the default (`validation-flywire-pertype.md` has the alternative). Circuit-only extinction does not appear in either.

3. **What holds MBON-γ5β′2a down is APL, and APL is saturated (open).** MBON-γ1pedc → MBON-γ5β′2a has only ~20 synapses in FlyWire; removing APL → MBON synapses instead lets MBON-γ5β′2a respond at ~90 Hz. Its silence to odours in the naive model matches flies: γ5 MBONs "show little or no response to olfactory stimuli" before training, and become potentiated to the CS+ after aversive training (Felsenberg et al. 2018). A documented route to that release: APL is "suppressed by olfactory learning" (Liu & Davis 2009), because the dopamine neurons active during conditioning also inhibit APL through D2-like receptors, odour-specifically and lastingly (Zhou et al. 2019). `apl_plasticity` (off by default) models this as dopamine-gated depression of KC → APL synapses. It works at the synapses (the CS+ KCs' APL input falls 15% after training) but changes nothing yet, because APL sits at its 30 mV ceiling during every odour on FlyWire: each KC spike moves it by ~6 mV (22 synapses × the standard per-synapse weight), so a few hundred active KCs saturate it. APL then acts as constant inhibition rather than graded feedback, and the calibrated APL gain reaches the right KC sparseness with a saturated neuron. In flies APL is a giant non-spiking cell (one synapse should move it far less), and its CS+ response measurably falls after training, which a saturated APL could not show.

4. **APL in its working range.** `graded_input_gain` scales all input to graded neurons, standing for APL's size; `--apl-half-range` calibrates it so the median odour drives APL to half its range (on FlyWire: gain 0.087, 13 mV of 30; the synthetic APL was never saturated and keeps gain ~1). The half-range target is a modelling choice: no measurement of APL's depolarisation was found; the evidence is only that APL responds in a graded, learnable way. Results on FlyWire: every one of the 16 test odours now excites the US compartments (12 before; saturated APL had been crushing MBON responses), and APL's CS+ response falls after training with `apl_plasticity` (20.6 → 18.4 mV), as in flies. Validation: 8/12 with half-range APL alone, 10/12 adding `apl_plasticity` (reports `validation-flywire-apl-half-range*.md`), against 9/12 for the default.
5. **Remaining obstacle: APL → MBON inhibition.** Even graded, APL silences MBON-γ5β′2a during odours. With APL → MBON removed, MBON-γ5β′2a's CS+ response does potentiate after training (53.5 → 59 spikes/s), the potentiation Felsenberg et al. describe. So circuit-only extinction now hinges on how strongly APL inhibits MBONs, for which no physiology was found: the model gives every APL synapse the same efficacy, and against sparse KC excitation APL wins on MBONs. With graded APL the prediction-error formula over-extinguishes (+0.85 → −0.28 in a direct test).

6. **Regional APL (2026-10-10).** APL's inhibition is spatially localised (Amin et al. 2020), but as one point neuron every Kenyon cell's input reached every APL target, and MBON-γ5β′2a was silent even at rest. `--apl regional` splits each APL into one unit per MB region (calyx, peduncle, vertical lobe, medial lobe; 8 units on FlyWire), each driven by and inhibiting only the synapses in its region, without coupling: the fully local extreme, the point neuron being the fully global one. Results (`validation-flywire-apl-regional.md`, 10/12, same failures as global):

   | | global (default) | regional |
   |---|---|---|
   | MBON-γ5β′2a at rest / to CS+ | 0 / 0 Hz | 10–11 / 2–16 Hz |
   | PI shock, reward | +0.51, +0.22 | +0.35, +0.12 |
   | acquisition, 5 trials | +0.68 | +0.48 |
   | extinction | +0.54 → +0.56 | +0.38 → +0.37 |
   | blocking, PI ratio | 1.03 | 0.58 |

   MBON-γ5β′2a now fires spontaneously, as MBONs do in flies, and blocking becomes visible, but extinction still doesn't appear and all learning is weaker. Neither is clearly better on all checks and each is one extreme of an unmeasured coupling, so global stays the default. Extinction now hinges on what neither has: MBON-γ5β′2a's CS+ response is weak, and nothing potentiates it after training. In flies that potentiation comes from MBON-γ1pedc releasing feedforward inhibition onto M6's **axons** (Felsenberg et al. 2018), synapses the extractor's MBON → MBON rule leaves out (they lie outside the MB). Modelling them as presynaptic inhibition of M6's output is the next step toward circuit-computed extinction.

## 10. What's deliberately left out

- **The lateral horn.** The parallel pathway for innate odour responses ("this smells like rotting food, approach"). It doesn't participate in conditioning, so it's outside scope.
- **Other dopamine clusters, octopamine neurons, and non-olfactory KC inputs.** Some KCs receive visual or thermal input, and reward signalling involves octopamine upstream of PAM. Leaving these out keeps the model about odour learning specifically.
- **Everything downstream of MBONs.** The model stops at MBONs. The neurons that convert MBON output into walking toward or away from an odour aren't included, which is why behaviour is read out from MBON balance.

---

## 11. Modelling assumptions to state in the README

1. **Neuron model.** Leaky integrate-and-fire with the parameters Shiu et al. (2024) used for the whole FlyWire brain. Real neurons differ in size, threshold, and dynamics. A single set of values for everyone is the biggest simplification.
2. **Synapse strength ∝ synapse count.** More synapses between two neurons = stronger connection. Reasonable on average, but it ignores synapse size and receptor numbers.
3. **Signs from transmitters, one per neuron (Dale's principle).** Every connection uses its presynaptic neuron's transmitter: established values for ORNs and KCs (acetylcholine), APL (GABA) and DANs (dopamine); other neurons pool the predictions of all synapses of their cell type; `scripts/known_transmitters.csv` overrides a type with a sourced value (MBON02: glutamatergic). Taking FlyWire's per-synapse prediction edge by edge flipped ~5% of edges, for example letting APL excite Kenyon cells. Glutamate is treated as inhibitory, as in Shiu et al. (2024), although MBONs and DANs express both inhibitory GluClα and excitatory NMDA receptors (Li et al. 2020).
3b. **Signs from predicted transmitters (detail).** Acetylcholine = excitatory; GABA and glutamate = inhibitory (glutamate acts through the inhibitory GluCl channel in much of the fly central brain); dopamine and serotonin = modulatory, with no direct fast effect. The transmitter predictions are themselves machine-learning estimates from EM images (Eckstein et al. 2024).
4. **Learning rules.** The default rule depresses only, in proportion to KC trace × dopamine. The real rule is timing-dependent: dopamine *after* KC activity depresses, dopamine *before* it can potentiate (Handler et al. 2019); the optional `timing` rule implements that, and backward pairing needs it.
4b. **Connections below FlyWire's usual threshold are kept.** Each Kenyon cell makes only a few synapses on each MBON. FlyWire's standard connection table keeps only rows with ≥ 5 synapses, which removed most KC → MBON input: with it, no output neuron in the shock compartments responded to odours, and learning could not be measured (4 of 12 validation checks passed). The circuit is therefore extracted from the unthresholded table, which includes some false-positive synapses from automatic detection. `extract_mb_circuit.py --min-syn N` tests the sensitivity to that choice: keeping only pairs with ≥ 3 synapses (196k instead of 766k edges) passes 11 of 12 checks against 9 of 12 with every synapse. Reward learning in particular is clear with ≥ 3 (PI +0.34, abolished without PAM) and weak with all synapses (+0.15). So the weakest connections matter, and which result is closer to the fly depends on how many of them are real.
5. **Odour input comes from DoOR, which is incomplete.** About 86% of receptor/odour pairs were never measured, and those are set to "no change from spontaneous". Poorly covered odours therefore look weaker and less distinctive than they are. The classic pair 3-octanol / 4-methylcyclohexanol has only 57% / 45% coverage, and part of the generalization the model shows between them is an artifact of that. Well-covered pairs (ethyl acetate 94%, pentyl acetate 86%) give cleaner results. DoOR also has no real concentration axis.
6. **Parameters were tuned on synthetic data.** Expect to retune on the real circuit. The targets are KC sparseness of ~5–10% per odour and a clear drop in the trained compartments for CS+ but not CS−.