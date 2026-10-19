// analysis.hpp — turning spike counts and weights into interpretable numbers.
#pragma once

#include <cmath>
#include <cstdint>
#include <random>
#include <string>
#include <vector>

#include "fruit_fly/experiment.hpp"
#include "fruit_fly/network.hpp"

namespace fruit_fly {

// Pearson correlation of two count vectors over the neurons in idx (NaN if undefined).
double correlation(const std::vector<int32_t>& a, const std::vector<int32_t>& b,
                   const std::vector<int32_t>& idx);

// Fraction of neurons in idx with at least one spike.
double fraction_active(const std::vector<int32_t>& counts, const std::vector<int32_t>& idx);

// Number of neurons in idx active in both a and b.
int32_t shared_active(const std::vector<int32_t>& a, const std::vector<int32_t>& b,
                      const std::vector<int32_t>& idx);

// mask[m] = 1 if neuron m receives dopamine from any neuron in `dans`.
std::vector<uint8_t> dopamine_targets(const Network& net, const std::vector<int32_t>& dans);

// How similar two odours are at each processing stage (pattern separation).
struct Separation {
    double pn_correlation = 0, kc_correlation = 0;
    double kc_active_plus = 0, kc_active_minus = 0;
    int32_t kc_shared = 0;
};
Separation pattern_separation(const Network& net, const std::vector<int32_t>& a,
                              const std::vector<int32_t>& b);

// Mean MBON spike counts per cell type, before and after training.
struct MbonTypeSummary {
    std::string cell_type;
    int32_t n = 0;
    bool us_target = false;   // receives dopamine from the US neurons
    double pre_plus = 0, post_plus = 0, pre_minus = 0, post_minus = 0;
};
std::vector<MbonTypeSummary> summarize_mbons(const Network& net, const ConditioningResult& r,
                                             const std::vector<uint8_t>& us_target);

// Relative response change in the US-innervated MBONs (e.g. -0.8 = -80%).
struct CompartmentChange {
    bool valid = false;        // false if those MBONs never responded
    double cs_plus = 0, cs_minus = 0;
};
CompartmentChange compartment_change(const Network& net, const ConditioningResult& r,
                                     const std::vector<uint8_t>& us_target);

// Mean of weights_after / initial weight over all plastic synapses.
double mean_weight_ratio(const Network& net, const std::vector<float>& weights);

// ====================================================================== behaviour
//
// T-maze choice from mushroom body output ("valence balance" model).
// Aso et al. 2014b (eLife 3:e04580): optogenetically activating glutamatergic
// MBONs repelled flies; activating cholinergic or GABAergic MBONs attracted them.

// +1 approach (ACH, GABA), -1 avoidance (GLUT), 0 anything else.
int valence_of_transmitter(const std::string& nt);

// valence per neuron: that of its transmitter for MBONs, 0 for every other neuron.
std::vector<int8_t> mbon_valences(const Network& net);

// Net approach drive of an odour: sum(valence * spikes) over MBONs with a valence,
// divided by `scale`. tmaze_test passes the larger of the two odours' naive
// (pre-training) valenced output, so drives keep their absolute size: an odour
// that evokes little output of either kind is near-neutral, however lopsided.
// Without a scale (NaN), returns the ratio sum(valence * spikes) / sum(spikes),
// NaN if none of them fired.
double approach_drive(const std::vector<int32_t>& counts, const std::vector<int8_t>& valence,
                      double scale = NAN);

struct TMazeChoice {
    double drive_plus = NAN, drive_minus = NAN;
    double p_plus = 0.5;           // probability a fly enters the CS+ arm
    double preference = 0.0;       // p(CS+) - p(CS-): -1 = every fly avoids CS+
    int32_t flies = 0;             // sampled group (a simulated experiment)
    int32_t chose_plus = 0;
    double sampled_preference = 0.0;
};

// p_plus = 1 / (1 + exp(-sharpness * (drive_plus - drive_minus))); undefined drives -> 0.5.
TMazeChoice tmaze_choice(double drive_plus, double drive_minus, double sharpness,
                         int32_t flies, std::mt19937_64& rng);

struct BehaviorConfig {
    double sharpness = 6.0;        // how strongly drive differences decide the choice
    int32_t flies = 100;           // flies per simulated group
    uint64_t seed = 1;
};

struct BehaviorResult {
    // False if a prediction is impossible: no MBON has a known transmitter, or
    // the MBONs that do were silent for an odour. Then learned_drive and both
    // performance indices are NaN; they are never reported as 0 ("no learning").
    bool valid = false;
    int32_t valenced_mbons = 0;    // MBONs with an approach/avoid valence
    // One group of flies choosing before and after training (includes any
    // innate preference for one odour).
    TMazeChoice naive, trained;
    // (drive+ - drive-) after training minus the same before: the learned part.
    // Removing the naive difference cancels innate odour bias, which real
    // T-maze experiments do with a reciprocal design (odour roles swapped).
    double learned_drive = NAN;
    // Choice driven by the learned part alone, as a performance index in
    // (-1, 1), signed so positive = learned in the direction the US teaches
    // (shock: away from CS+, reward: toward it).
    double performance_index = NAN;
    int32_t flies = 0;
    double sampled_performance_index = NAN;   // the same for a sampled group of flies
};

BehaviorResult tmaze_test(const Network& net, const ConditioningResult& r,
                          const BehaviorConfig& config = BehaviorConfig());

}  // namespace fruit_fly