// experiment.hpp — behavioural protocols on top of the Simulator.
//
// An Experiment owns one simulated fly: a Simulator plus the resting input
// between stimuli and the neurons that deliver punishment or reward.
// Every presentation is recorded, so anything built on top (CLI, Python,
// web backend) can inspect the full history, not just a summary.
#pragma once

#include <cmath>
#include <cstdint>
#include <functional>
#include <map>
#include <string>
#include <vector>

#include "fruit_fly/network.hpp"
#include "fruit_fly/params.hpp"
#include "fruit_fly/simulator.hpp"

namespace fruit_fly {

// Unconditioned stimulus paired with an odour.
enum class US { None, Shock, Reward };

const char* to_string(US us);
US us_from_string(const std::string& s);   // "none" | "shock" | "reward"

struct ProtocolConfig {
    double stim_ms   = 1000.0;   // odour duration
    double gap_ms    = 2000.0;   // rest after each odour; lets KC traces fade
    double settle_ms = 500.0;    // rest before the first stimulus
    double spontaneous_ms = 2000.0;   // with spontaneously active MBONs: rest window that
                                      // measures every neuron's spontaneous rate (after settle)
    double us_hz     = 40.0;     // DAN firing during shock / reward
    std::string shock_group  = "DAN_PPL1";
    std::string reward_group = "DAN_PAM";
};

// One odour presentation and the spikes it evoked.
struct Presentation {
    std::string label;             // odour slot (e.g. "A"), or "US" for a US-only step
    std::string phase;             // e.g. "pre-test", "training", "post-test"
    US us = US::None;
    double t_start_ms = 0.0;       // odour onset (US onset for a US-only step)
    double duration_ms = 0.0;      // the counting window: odour duration (or US duration)
    double us_start_ms = NAN, us_end_ms = NAN;   // absolute US window; NaN without a US
    std::vector<int32_t> counts;   // spikes per neuron during the counting window
};

// One step of a protocol: an odour and/or a US, with the US timed relative to
// the odour. Negative us_onset_ms puts the US BEFORE the odour (backward pairing).
// Durations < 0 mean "use the ProtocolConfig default".
struct ProtocolStep {
    std::string phase;             // free text; readouts pick presentations by phase
    std::string odour;              // odour slot key, "" = no odour (US alone); "A+C" = compound
    US us = US::None;
    double odour_ms = -1.0;         // default: stim_ms
    double us_onset_ms = 0.0;      // relative to odour onset
    double us_ms = -1.0;           // default: odour_ms (or stim_ms without an odour)
    double gap_ms = -1.0;          // rest after the step; default: gap_ms
    int repeat = 1;
};

class Experiment {
public:
    // The Network must outlive the Experiment.
    Experiment(const Network& net, const Params& params,
               const ProtocolConfig& config = ProtocolConfig(), uint64_t seed = 42);

    // Input applied between stimuli (e.g. OdourStimulus::baseline()).
    void set_baseline(const RateSet& baseline);
    // Rest for settle_ms. If MBONs fire spontaneously (Params::mbon_tonic_mV > 0),
    // then also measure each neuron's spontaneous rate over spontaneous_ms.
    void settle();
    // Spontaneous rate per neuron (Hz), or empty if not measured. Readouts subtract
    // it from odour responses, as recordings do (Hige et al. 2015).
    const std::vector<double>& spontaneous_hz() const { return spontaneous_hz_; }

    // Present an odour (optionally paired with a US), then rest for gap_ms.
    const Presentation& present(const std::string& label, const RateSet& odour,
                                US us = US::None);

    // General form: odour (nullptr = none) and/or US with independent timing.
    // present() is the special case "US exactly during the odour".
    const Presentation& present_step(const ProtocolStep& step, const RateSet* odour);

    Simulator& simulator() { return sim_; }
    const Simulator& simulator() const { return sim_; }
    const Network& network() const { return net_; }
    const ProtocolConfig& config() const { return cfg_; }
    const RateSet& baseline() const { return baseline_; }
    const std::vector<Presentation>& history() const { return history_; }
    const std::vector<int32_t>& us_neurons(US us) const;

private:
    void rest();

    const Network& net_;
    ProtocolConfig cfg_;
    Simulator sim_;
    RateSet baseline_;
    std::vector<int32_t> shock_, reward_, none_;
    std::vector<Presentation> history_;
    std::vector<double> spontaneous_hz_;
};

// Differential conditioning:
//   pre-test CS+, CS-  ->  trials x (CS+ with US, CS- alone)  ->  post-test CS+, CS-
struct ConditioningResult {
    std::string cs_plus, cs_minus;
    US us = US::Shock;
    int trials = 0;
    Presentation pre_plus, pre_minus, post_plus, post_minus;
    std::vector<float> weights_before, weights_after;   // order of Network::plastic
    // Spontaneous rate per neuron (Hz); empty = none. When set, readouts use evoked
    // activity: spikes minus spontaneous_hz x window, which can be negative.
    std::vector<double> spontaneous_hz;
};

// Called after each presentation with (presentations done, total). Used to
// report progress while a long experiment runs. May be empty.
using ProgressCallback = std::function<void(int done, int total)>;

ConditioningResult run_differential_conditioning(
    Experiment& exp,
    const std::string& cs_plus_name, const RateSet& cs_plus,
    const std::string& cs_minus_name, const RateSet& cs_minus,
    int trials = 3, US us = US::Shock,
    const ProgressCallback& progress = nullptr);

// Compound of several odours presented together (see Params::mixture).
//  "linear":  each neuron fires at its baseline rate plus the sum of every
//             odour's change from baseline, floored at 0.
//  "binding": competitive binding at one receptor site, rates kept within
//             [0, max_rate_hz); a single odour's own rates are reproduced exactly.
RateSet mix_odours(const std::vector<const RateSet*>& odours, const RateSet& baseline,
                   const std::string& mode = "linear", double max_rate_hz = 200.0);

// Run steps in order (each `repeat` times). `odours` maps slot keys to rates;
// every slot a step names must be present. A step's odour may name a compound,
// "A+C": the slots' mix_odours() over the experiment's baseline, labelled "A+C".
// Returns the presentations made.
std::vector<Presentation> run_protocol(Experiment& exp, const std::vector<ProtocolStep>& steps,
                                       const std::map<std::string, RateSet>& odours,
                                       const ProgressCallback& progress = nullptr);

// Build a ConditioningResult (the input of the analysis and T-maze functions)
// from any protocol: CS+ / CS- responses are the first US-free presentations
// of those slots in `before_phase` and in `after_phase`. Throws if missing.
ConditioningResult conditioning_readout(const std::vector<Presentation>& presentations,
                                        const std::string& plus, const std::string& minus,
                                        const std::string& before_phase,
                                        const std::string& after_phase, US us, int trials,
                                        std::vector<float> weights_before,
                                        std::vector<float> weights_after,
                                        std::vector<double> spontaneous_hz = {});

}  // namespace fruit_fly