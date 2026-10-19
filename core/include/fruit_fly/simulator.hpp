// simulator.hpp — runs the network forward in time.
//
// Holds everything that CHANGES during a simulation (voltages, currents,
// traces, plastic weights, spike records) while the Network stays read-only.
// You can run several Simulators on one Network, e.g. a trained and a naive fly.
#pragma once

#include <cstdint>
#include <random>
#include <vector>

#include "fruit_fly/network.hpp"
#include "fruit_fly/params.hpp"

namespace fruit_fly {

struct Spike {
    int32_t neuron;
    float   t_ms;
};

// A stimulus: one Poisson rate per listed neuron (odour pattern, shock, baseline).
struct RateSet {
    std::vector<int32_t> neurons;
    std::vector<double>  hz;
};

class Simulator {
public:
    // The Network must outlive the Simulator.
    Simulator(const Network& net, const Params& p, uint64_t seed = 42);

    // ---- stimulus: external Poisson spike trains
    void set_rate(int32_t neuron, double hz);
    void set_rates(const std::vector<int32_t>& neurons, double hz);
    // one rate per neuron (e.g. an odour's ORN pattern); sizes must match
    void set_rates(const std::vector<int32_t>& neurons, const std::vector<double>& hz);
    void apply(const RateSet& rates) { set_rates(rates.neurons, rates.hz); }

    // ---- lesions: silenced neurons ignore all input, never spike, release nothing
    void silence(const std::vector<int32_t>& neurons);
    void clear_silenced();
    const std::vector<uint8_t>& silenced() const { return silenced_; }
    void clear_rates();

    // ---- time
    void run(double ms);
    double time_ms() const { return static_cast<double>(step_) * p_.dt_ms; }

    // ---- recording
    const std::vector<Spike>& spikes() const { return spikes_; }
    void clear_spikes() { spikes_.clear(); }
    const std::vector<int32_t>& spike_counts() const { return counts_; }
    void reset_counts();
    const std::vector<float>& voltages() const { return v_; }

    // ---- plasticity
    std::vector<float> plastic_weights() const;   // same order as Network::plastic
    void reset_weights();

    // Voltages, currents, traces and pending spikes back to rest.
    // Weights are kept (that's the fly's memory); time keeps running.
    void reset_state();

    Params& params() { return p_; }

    // ---- prediction error: current expectation of each US (0..1), for inspection
    double expected_shock() const { return expect_shock_; }
    double expected_reward() const { return expect_reward_; }

private:
    void step();
    void emit_spike(int32_t i);
    void apply_plasticity();
    void update_prediction();
    double expectation(const std::vector<int32_t>& mbons, const std::vector<double>& share,
                       double ref) const;

    const Network& net_;
    Params p_;

    std::vector<float> w_;          // working copy of Network::weight
    std::vector<float> v_, g_;      // membrane potential, synaptic current (mV)
    std::vector<int32_t> ref_;      // refractory steps left
    std::vector<float> elig_;       // spike trace per neuron (used for KCs)
    std::vector<float> da_;         // dopamine level per neuron (used for MBONs)
    std::vector<float> da_fast_;    // fast dopamine trace (timing rule: ongoing release)

    // delay line: buf_[slot][neuron] = input arriving when head reaches slot
    std::vector<std::vector<float>> buf_;
    int32_t head_ = 0;
    int32_t delay_steps_ = 1;

    std::vector<float> rate_hz_;
    std::vector<int32_t> driven_;   // neurons with a non-zero rate
    std::vector<int32_t> graded_idx_, mbon_idx_;
    std::vector<int32_t> plastic_post_idx_;   // neurons with plastic KC inputs (MBONs, + APL)
    std::vector<uint8_t> silenced_;
    bool timing_rule_ = false;
    std::vector<std::vector<int32_t>> plastic_by_pre_;   // indices into Network::plastic, per KC

    std::mt19937_64 rng_;
    std::uniform_real_distribution<double> unif_{0.0, 1.0};

    std::vector<Spike> spikes_;
    std::vector<int32_t> counts_;
    int64_t step_ = 0;
    int32_t plast_every_ = 1;       // steps between plasticity updates

    // prediction error
    std::vector<int32_t> shock_dans_, reward_dans_;      // DANs carrying each US
    std::vector<int32_t> shock_mbons_, reward_mbons_;    // MBONs those DANs innervate
    // Per neuron: the share of its dopamine input that comes from those DANs (0..1),
    // the same share by which their dopamine reaches its synapses (Network::da_coef).
    std::vector<double> shock_share_, reward_share_;
    std::vector<int32_t> pe_dans_;                       // DANs that get prediction-error drive
    std::vector<float> pe_rate_hz_;                      // that drive, per neuron
    double expect_shock_ = 0.0, expect_reward_ = 0.0;
    int32_t pe_every_ = 1;
    bool expect_on_ = false;                             // prediction_error or pe_us
    bool expect_sum_ = false;                            // pe_expectation == "sum"
    bool omission_net_ = false;                          // pe_omission == "net"
    double shock_ref_ = 0.0, reward_ref_ = 0.0;          // "sum": the fixed asymptote per US
    std::vector<float> ext_scale_;                       // pe_us: factor on each neuron's external rate
    std::vector<float> bias_;                            // constant input per neuron (mbon_tonic_mV)
    double release_gain(int32_t dan) const;              // kc_dan "terminal": KC gain on release
};

}  // namespace fruit_fly