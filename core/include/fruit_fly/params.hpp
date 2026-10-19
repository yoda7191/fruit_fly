// params.hpp — every tunable number in the model lives here.
//
// Neuron and synapse defaults follow the whole-brain leaky integrate-and-fire
// model of Shiu et al. 2024 (Nature), which used the same FlyWire data.
// Plasticity defaults are hand-chosen starting points: expect to tune them.
#pragma once

#include <map>
#include <string>
#include <utility>
#include <vector>

namespace fruit_fly {

struct Params {
    // ---- integration
    double dt_ms = 0.1;              // Euler time step

    // ---- leaky integrate-and-fire neuron
    double v_rest_mV   = -52.0;      // resting potential
    double v_reset_mV  = -52.0;      // potential right after a spike
    double v_thresh_mV = -45.0;      // spike threshold
    double tau_m_ms    = 20.0;       // membrane time constant
    double tau_syn_ms  = 5.0;        // synaptic current decay
    double t_ref_ms    = 2.2;        // refractory period
    double delay_ms    = 1.8;        // axonal + synaptic delay

    // ---- synapses
    double w_syn_mV = 0.275;         // jump in synaptic current per synapse per spike
    double w_ext_mV = 68.75;         // one external (stimulus) spike; big enough to fire the cell

    // ---- graded (non-spiking) neurons, e.g. APL
    std::vector<std::string> graded_groups = {"APL"};
    double graded_gain     = 0.05;   // output per mV of depolarisation, per ms
    double graded_v_max_mV = 30.0;   // cap on depolarisation above rest
    // Scale on all synaptic input to graded neurons. APL is a giant non-spiking cell:
    // with the standard per-synapse weight, each KC spike (~22 synapses in FlyWire)
    // moves it ~6 mV and any odour pins it at graded_v_max_mV, so its output can't
    // grade with KC activity or fall with learning (Liu & Davis 2009; Zhou et al.
    // 2019). Validation calibrates it so a typical odour drives APL to half its range.
    double graded_input_gain = 1.0;

    // ---- connections to drop, as (pre group, post group)
    // KC->KC axo-axonic synapses are numerous in the connectome but their sign
    // and function are unclear; as plain excitation they cause runaway activity.
    std::vector<std::pair<std::string, std::string>> excluded_pairs = {{"KC", "KC"}};

    // ---- dopamine-gated plasticity on KC -> MBON synapses
    bool plasticity_on = true;
    std::string plastic_pre_group  = "KC";
    std::string plastic_post_group = "MBON";
    std::string dan_prefix         = "DAN";   // matches DAN_PAM and DAN_PPL1
    double tau_elig_ms   = 300.0;    // how long a KC "remembers" it just fired
    double tau_da_ms     = 300.0;    // how long dopamine lingers at an MBON
    double learning_rate = 2e-6;     // per ms, per unit eligibility x dopamine
    double w_min_frac    = 0.0;      // weights can't drop below w0 * this
    double plasticity_interval_ms = 1.0;  // apply the rule every 1 ms, not every step
    // Dopamine also suppresses APL, odour-specifically and lastingly: DANs active
    // during conditioning synapse onto APL and act through D2-like receptors
    // (Zhou et al. 2019, PNAS; Liu & Davis 2009 saw APL's CS+ response fall after
    // training). Modelled as the same dopamine-gated depression on KC -> APL
    // synapses, so APL is recruited less by the trained odour. Off by default.
    bool apl_plasticity = false;
    std::string apl_group = "APL";

    // Which learning rule:
    //  "overlap" (default): weaken in proportion to KC trace x dopamine level,
    //            continuously. Order doesn't matter; all results so far use it.
    //  "timing": event-based; the ORDER of KC and dopamine activity sets the sign
    //            (Handler et al. 2019, Cell). Dopamine arriving after KC activity
    //            weakens the synapse; KC activity after dopamine strengthens it.
    //            Needed for backward pairing ("relief" learning).
    std::string plasticity_rule = "overlap";
    double timing_depression   = 6e-4;  // per dopamine spike: x coupling x KC trace x w0
    double timing_potentiation = 1e-3;  // per KC spike: x residual dopamine at the MBON x w0
    // Potentiation uses only dopamine that has STOPPED arriving: the slow trace
    // minus what ongoing release accounts for, estimated from a fast trace
    // (residual = slow - fast * tau_da / tau_fast, floored at 0). During release
    // the two cancel; after it ends the fast one vanishes within ~3 tau_fast.
    // Without this, KC spikes during simultaneous odour + shock would potentiate
    // and could outweigh depression, contradicting aversive learning in flies.
    double timing_fast_tau_ms = 30.0;

    // ---- prediction-error dopamine (Rescorla-Wagner style; off by default)
    // The circuit's expectation of a US for the CURRENT odour is the fraction
    // by which the active Kenyon cells' synapses in that US's compartments are
    // already weakened (0 = nothing learned, 1 = fully learned). When a US is
    // expected but absent, the opposite dopamine neurons fire in proportion
    // (expected shock omitted -> PAM; expected reward omitted -> PPL1), as in
    // fly extinction (Felsenberg et al. 2018). That opposing memory is what
    // extinguishes the original one.
    bool prediction_error = false;
    // The other half of Rescorla-Wagner: a US that IS expected releases less
    // dopamine. While the US drives its dopamine neurons, their rate is scaled
    // by (1 - expectation of that US). Learning then slows as the memory
    // forms, and a cue trained together with an already-predictive one learns
    // less (Kamin blocking). Independent of prediction_error; off by default.
    bool pe_us = false;
    // How the expectation combines the cues present:
    //  "average" (default): the fraction by which the active KCs' synapses are
    //            weakened. A trained odour mixed with a new one predicts less,
    //            in proportion to the share of KC activity it contributes.
    //  "sum": Rescorla-Wagner. The learned loss summed over every active KC,
    //            sum((w0 - w) * min(1, trace)), divided by a fixed asymptote:
    //            the naive drive of a typical single odour, i.e. pe_ref_active_frac
    //            of all KCs' weight onto the US compartments. A trained odour keeps
    //            its full prediction inside a compound (needed for full blocking).
    std::string pe_expectation = "average";
    // What an omitted US signals (prediction_error):
    //  "separate" (default): each expectation on its own. An omitted shock drives
    //            PAM by expect_shock, an omitted reward drives PPL1 by expect_reward.
    //  "net": one signed prediction per cue, as in Rescorla-Wagner with reward and
    //            punishment as opposite values of one US dimension: only the larger
    //            expectation's omission drives the opposite DANs, by the difference.
    //            With "separate", the extinction memory itself (PAM depressing the
    //            CS+ synapses in reward compartments) reads as a reward expectation
    //            whose omission drives PPL1, so extinction undoes itself.
    std::string pe_omission = "separate";
    double pe_ref_active_frac = 0.07;   // KCs active per odour (the calibrated sparseness)
    double pe_gain_hz = 20.0;          // DAN rate at expectation 1 (20: partial extinction, as in flies)
    double pe_min_trace = 2.0;         // KC activity (summed traces per MBON) needed to judge
    double pe_interval_ms = 5.0;       // how often the expectation is recomputed
    std::string pe_shock_group = "DAN_PPL1";
    std::string pe_reward_group = "DAN_PAM";
    double w_max_frac = 2.0;            // potentiation can't exceed w0 * this

    // ---- spontaneous MBON activity (off by default)
    // MBONs fire spontaneously in flies (MBON-alpha3: 12.1 Hz ex vivo, Hafez et al. 2023, eLife 12:e77578;
    // MBON-gamma1pedc in vivo, Hige et al. 2015, rate not stated). A constant
    // depolarising input to every plastic_post_group neuron; ~7.1 mV gives ~12 Hz
    // with the default neuron. Near threshold, KC input then modulates the rate
    // continuously, so depression of a weak input still changes the output.
    double mbon_tonic_mV = 0.0;
    // Per MBON cell type (e.g. "MBON01" -> 9.2), overriding mbon_tonic_mV for that type.
    // Each type then fires at its spontaneous rate given its own inhibition; one value
    // for all left strongly inhibited types (e.g. MBON01) silent.
    std::map<std::string, double> mbon_tonic_by_type;

    // ---- Kenyon cell -> dopamine neuron synapses
    //  "fast" (default): ordinary excitatory synapses, as the connectome lists them;
    //          KC activity can make DANs spike.
    //  "terminal": axo-axonic contacts on DAN terminals that amplify dopamine
    //          release without driving DAN spikes (Cervantes-Sandoval et al. 2017,
    //          eLife: TTX-insensitive, "a positive gain signal ... for DA release").
    //          Each DAN spike releases (1 + kc_dan_gain * a) times its dopamine, where
    //          a = activity of the DAN's KC inputs, sum(syn * min(1, trace)) / sum(syn),
    //          divided by pe_ref_active_frac (so a typical odour gives a ~ 1).
    //          Silencing KCs then leaves 1 / (1 + kc_dan_gain) of the release.
    std::string kc_dan = "fast";
    double kc_dan_gain = 0.0;

    // ---- odour mixtures (compounds such as "A+C")
    //  "linear" (default): each ORN fires at baseline + the sum of the odours'
    //          changes from baseline. Can exceed what a receptor can do.
    //  "binding": the odours compete for the receptor's single binding site
    //          (syntopic interaction, which fully explained Or22a's mixture
    //          responses: Münch et al. 2013, Chem Senses 38:293). Each odour is
    //          a full agonist (drives the ORN toward orn_max_rate_hz at full
    //          occupancy) or, if it inhibits the ORN, a full inverse agonist
    //          (toward 0); its occupancy is the one that reproduces its own
    //          response. Mixtures then saturate, and an inhibiting odour pulls an
    //          excited ORN down. Partial agonists can't be told apart from weak
    //          full agonists with one concentration per odour (DoOR), so they
    //          aren't modelled. Interactions between glomeruli come from the
    //          antennal lobe local neurons, where they arise in flies
    //          (Silbering & Galizia 2007, J Neurosci 27:11966).
    std::string mixture = "linear";
    double orn_max_rate_hz = 200.0;     // = OdourStimulus::kDefaultMaxRateHz (DoOR 1.0)
};

}  // namespace fruit_fly