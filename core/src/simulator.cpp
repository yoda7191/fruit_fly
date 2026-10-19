#include "fruit_fly/simulator.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace fruit_fly {

Simulator::Simulator(const Network& net, const Params& p, uint64_t seed)
    : net_(net), p_(p), rng_(seed) {
    const int32_t n = net_.size();
    w_ = net_.weight;
    v_.assign(n, static_cast<float>(p_.v_rest_mV));
    g_.assign(n, 0.0f);
    ref_.assign(n, 0);
    elig_.assign(n, 0.0f);
    da_.assign(n, 0.0f);
    da_fast_.assign(n, 0.0f);
    rate_hz_.assign(n, 0.0);
    counts_.assign(n, 0);

    delay_steps_ = std::max(1, static_cast<int32_t>(std::lround(p_.delay_ms / p_.dt_ms)));
    buf_.assign(delay_steps_ + 1, std::vector<float>(n, 0.0f));
    plast_every_ = std::max(1, static_cast<int32_t>(std::lround(p_.plasticity_interval_ms / p_.dt_ms)));

    for (int32_t i = 0; i < n; ++i) {
        if (net_.graded[i]) graded_idx_.push_back(i);
        if (net_.group[i] == p_.plastic_post_group) mbon_idx_.push_back(i);
        if (!net_.plastic_by_post[i].empty()) plastic_post_idx_.push_back(i);
    }
    silenced_.assign(n, 0);

    if (p_.plasticity_rule == "timing") {
        timing_rule_ = true;
    } else if (p_.plasticity_rule != "overlap") {
        throw std::invalid_argument("plasticity_rule must be 'overlap' or 'timing', got '" +
                                    p_.plasticity_rule + "'");
    }
    plastic_by_pre_.assign(n, {});
    for (size_t s = 0; s < net_.plastic.size(); ++s)
        plastic_by_pre_[net_.plastic[s].pre].push_back(static_cast<int32_t>(s));

    pe_rate_hz_.assign(n, 0.0f);
    ext_scale_.assign(n, 1.0f);
    bias_.assign(n, 0.0f);
    for (int32_t m : mbon_idx_) {
        const auto t = p_.mbon_tonic_by_type.find(net_.cell_type[m]);
        bias_[m] = static_cast<float>(t != p_.mbon_tonic_by_type.end() ? t->second : p_.mbon_tonic_mV);
    }
    expect_on_ = p_.prediction_error || p_.pe_us;
    if (p_.pe_expectation == "sum") {
        expect_sum_ = true;
    } else if (p_.pe_expectation != "average") {
        throw std::invalid_argument("pe_expectation must be 'average' or 'sum', got '" +
                                    p_.pe_expectation + "'");
    }
    if (p_.pe_omission == "net") {
        omission_net_ = true;
    } else if (p_.pe_omission != "separate") {
        throw std::invalid_argument("pe_omission must be 'separate' or 'net', got '" + p_.pe_omission + "'");
    }
    if (p_.mixture != "linear" && p_.mixture != "binding")      // used by run_protocol; fail early
        throw std::invalid_argument("mixture must be 'linear' or 'binding', got '" + p_.mixture + "'");
    if (!(p_.orn_max_rate_hz > 0.0)) throw std::invalid_argument("orn_max_rate_hz must be > 0");
    if (expect_on_) {
        pe_every_ = std::max(1, static_cast<int32_t>(std::lround(p_.pe_interval_ms / p_.dt_ms)));
        auto targets = [&](const std::vector<int32_t>& dans) {
            std::vector<uint8_t> mask(n, 0);
            for (int32_t d : dans)
                for (int32_t k = net_.da_row_ptr[d]; k < net_.da_row_ptr[d + 1]; ++k) mask[net_.da_col[k]] = 1;
            std::vector<int32_t> out;
            for (int32_t m : mbon_idx_)
                if (mask[m]) out.push_back(m);
            return out;
        };
        shock_dans_ = net_.indices_in_group(p_.pe_shock_group);
        reward_dans_ = net_.indices_in_group(p_.pe_reward_group);
        shock_mbons_ = targets(shock_dans_);
        reward_mbons_ = targets(reward_dans_);
        auto share = [&](const std::vector<int32_t>& dans) {
            std::vector<double> out(n, 0.0);
            for (int32_t d : dans)
                for (int32_t k = net_.da_row_ptr[d]; k < net_.da_row_ptr[d + 1]; ++k)
                    out[net_.da_col[k]] += net_.da_coef[k];
            return out;
        };
        shock_share_ = share(shock_dans_);
        reward_share_ = share(reward_dans_);
        // "sum": asymptote = naive drive if pe_ref_active_frac of all KCs were fully active
        auto naive_total = [&](const std::vector<int32_t>& mbons, const std::vector<double>& sh) {
            double w0 = 0.0;
            for (int32_t m : mbons)
                for (int32_t s : net_.plastic_by_post[m]) w0 += sh[m] * net_.plastic[s].w0;
            return p_.pe_ref_active_frac * w0;
        };
        shock_ref_ = naive_total(shock_mbons_, shock_share_);
        reward_ref_ = naive_total(reward_mbons_, reward_share_);
        if (p_.prediction_error) {
            pe_dans_ = shock_dans_;
            pe_dans_.insert(pe_dans_.end(), reward_dans_.begin(), reward_dans_.end());
        }
    }
}

// ------------------------------------------------------------------ prediction error

// How strongly the currently active KCs predict the US whose compartments are `mbons`,
// 0..1. 0 if too little KC activity to judge. Each MBON's synapses count by `share`,
// the fraction of its dopamine that comes from that US's DANs: an MBON with a few
// stray synapses from the other cluster must not read as that US's compartment
// (on FlyWire 57 of 96 MBONs have some input from both, few in equal measure).
//   average: sum((w0 - w) * trace) / sum(w0 * trace), the fraction of their drive lost
//   sum:     sum((w0 - w) * min(1, trace)) / ref, Rescorla-Wagner with asymptote ref
double Simulator::expectation(const std::vector<int32_t>& mbons, const std::vector<double>& share,
                              double ref) const {
    if (mbons.empty()) return 0.0;
    double lost = 0.0, naive = 0.0, trace = 0.0;
    for (int32_t m : mbons)
        for (int32_t s : net_.plastic_by_post[m]) {
            const PlasticSynapse& ps = net_.plastic[s];
            const double e = elig_[ps.pre];
            if (e < 1e-3) continue;
            const double x = (expect_sum_ ? std::min(1.0, e) : e) * share[m];
            lost += (ps.w0 - w_[ps.syn]) * x;
            naive += ps.w0 * x;
            trace += e;
        }
    if (naive <= 0.0 || trace / static_cast<double>(mbons.size()) < p_.pe_min_trace) return 0.0;
    if (expect_sum_) return ref > 0.0 ? std::clamp(lost / ref, 0.0, 1.0) : 0.0;
    return std::clamp(lost / naive, 0.0, 1.0);
}

void Simulator::update_prediction() {
    expect_shock_ = expectation(shock_mbons_, shock_share_, shock_ref_);
    expect_reward_ = expectation(reward_mbons_, reward_share_, reward_ref_);
    if (p_.pe_us) {
        // An expected US releases less dopamine (applies to whatever drives these DANs).
        for (int32_t d : shock_dans_) ext_scale_[d] = static_cast<float>(1.0 - expect_shock_);
        for (int32_t d : reward_dans_) ext_scale_[d] = static_cast<float>(1.0 - expect_reward_);
    }
    if (!p_.prediction_error) return;
    auto driven = [&](const std::vector<int32_t>& dans) {
        for (int32_t d : dans)
            if (rate_hz_[d] > 0) return true;
        return false;
    };
    // An expected US that arrives produces no error; an absent one drives the opposite DANs.
    // "net": one signed prediction per cue (shock minus reward), so only the larger
    // expectation's omission drives the opposite DANs, by the difference.
    double omit_shock = expect_shock_, omit_reward = expect_reward_;
    if (omission_net_) {
        omit_shock = std::max(0.0, expect_shock_ - expect_reward_);
        omit_reward = std::max(0.0, expect_reward_ - expect_shock_);
    }
    const float to_reward = driven(shock_dans_) ? 0.0f : static_cast<float>(p_.pe_gain_hz * omit_shock);
    const float to_shock = driven(reward_dans_) ? 0.0f : static_cast<float>(p_.pe_gain_hz * omit_reward);
    for (int32_t d : reward_dans_) pe_rate_hz_[d] = to_reward;
    for (int32_t d : shock_dans_) pe_rate_hz_[d] = to_shock;
}

// ------------------------------------------------------------------ KC -> DAN terminals

// 1 + kc_dan_gain * (activity of this DAN's KC inputs / a typical odour's); 1 if not "terminal"
double Simulator::release_gain(int32_t dan) const {
    const auto& inputs = net_.kc_to_dan[dan];
    if (inputs.empty() || p_.kc_dan_gain == 0.0) return 1.0;
    double active = 0.0, total = 0.0;
    for (const auto& [kc, syn] : inputs) {
        active += syn * std::min(1.0, static_cast<double>(elig_[kc]));
        total += syn;
    }
    return 1.0 + p_.kc_dan_gain * (active / total) / p_.pe_ref_active_frac;
}

// ------------------------------------------------------------------ lesions

void Simulator::silence(const std::vector<int32_t>& neurons) {
    for (int32_t i : neurons) {
        if (i < 0 || i >= net_.size()) throw std::out_of_range("bad neuron index");
        silenced_[i] = 1;
        v_[i] = static_cast<float>(p_.v_rest_mV);
        g_[i] = 0.0f;
    }
}

void Simulator::clear_silenced() { std::fill(silenced_.begin(), silenced_.end(), 0); }

// ------------------------------------------------------------------ stimulus

void Simulator::set_rate(int32_t neuron, double hz) {
    if (neuron < 0 || neuron >= net_.size()) throw std::out_of_range("bad neuron index");
    bool was_driven = rate_hz_[neuron] > 0;
    rate_hz_[neuron] = hz;
    if (hz > 0 && !was_driven) driven_.push_back(neuron);
    if (hz <= 0 && was_driven)
        driven_.erase(std::remove(driven_.begin(), driven_.end(), neuron), driven_.end());
}

void Simulator::set_rates(const std::vector<int32_t>& neurons, double hz) {
    for (int32_t i : neurons) set_rate(i, hz);
}

void Simulator::set_rates(const std::vector<int32_t>& neurons, const std::vector<double>& hz) {
    if (neurons.size() != hz.size()) throw std::invalid_argument("neurons and hz differ in length");
    for (size_t k = 0; k < neurons.size(); ++k) set_rate(neurons[k], hz[k]);
}

void Simulator::clear_rates() {
    for (int32_t i : driven_) rate_hz_[i] = 0;
    driven_.clear();
}

// ------------------------------------------------------------------ time

void Simulator::run(double ms) {
    const int64_t n_steps = std::llround(ms / p_.dt_ms);
    for (int64_t s = 0; s < n_steps; ++s) step();
}

void Simulator::step() {
    const int32_t n = net_.size();
    const float dt = static_cast<float>(p_.dt_ms);
    const float v_rest = static_cast<float>(p_.v_rest_mV);
    const float tau_m = static_cast<float>(p_.tau_m_ms);
    const float tau_syn = static_cast<float>(p_.tau_syn_ms);
    const int32_t n_ref = static_cast<int32_t>(std::lround(p_.t_ref_ms / p_.dt_ms));
    const int32_t n_slots = static_cast<int32_t>(buf_.size());

    // 1. input whose delay ends now
    std::vector<float>& arriving = buf_[head_];
    for (int32_t i = 0; i < n; ++i) {
        g_[i] += arriving[i];
        arriving[i] = 0.0f;
    }

    // 2. external Poisson input (odour, shock, sugar ...); ext_scale_ is 1 unless pe_us
    if (expect_on_ && step_ % pe_every_ == 0) update_prediction();
    for (int32_t i : driven_) {
        if (unif_(rng_) < rate_hz_[i] * ext_scale_[i] * p_.dt_ms / 1000.0 && !silenced_[i])
            g_[i] += static_cast<float>(p_.w_ext_mV);
    }
    // prediction-error drive to dopamine neurons (empty unless prediction_error)
    if (!pe_dans_.empty()) {
        for (int32_t i : pe_dans_) {
            if (pe_rate_hz_[i] > 0 && !silenced_[i] && unif_(rng_) < pe_rate_hz_[i] * p_.dt_ms / 1000.0)
                g_[i] += static_cast<float>(p_.w_ext_mV);
        }
    }

    // 3. membrane update
    for (int32_t i = 0; i < n; ++i) {
        if (silenced_[i]) {                      // lesioned: held at rest, input discarded
            v_[i] = v_rest;
            g_[i] = 0.0f;
            continue;
        }
        const float leak_and_input = (g_[i] + bias_[i] - (v_[i] - v_rest)) / tau_m;
        g_[i] -= dt * g_[i] / tau_syn;

        if (net_.graded[i]) {                    // graded: integrate, never spike
            const float gin = static_cast<float>(p_.graded_input_gain);
            v_[i] += dt * (g_[i] * gin + bias_[i] - (v_[i] - v_rest)) / tau_m;
            v_[i] = std::clamp(v_[i], v_rest - static_cast<float>(p_.graded_v_max_mV),
                               v_rest + static_cast<float>(p_.graded_v_max_mV));
            continue;
        }
        if (ref_[i] > 0) {                       // refractory: clamp at reset
            --ref_[i];
            v_[i] = static_cast<float>(p_.v_reset_mV);
            continue;
        }
        v_[i] += dt * leak_and_input;
        if (v_[i] >= p_.v_thresh_mV) {
            v_[i] = static_cast<float>(p_.v_reset_mV);
            ref_[i] = n_ref;
            emit_spike(i);
        }
    }

    // 4. graded neurons release continuously, proportional to depolarisation
    std::vector<float>& next = buf_[(head_ + 1) % n_slots];
    for (int32_t i : graded_idx_) {
        const float depol = v_[i] - v_rest;
        if (depol <= 0) continue;
        const float scale = static_cast<float>(p_.graded_gain) * depol * dt;
        for (int32_t k = net_.row_ptr[i]; k < net_.row_ptr[i + 1]; ++k)
            next[net_.col[k]] += w_[k] * scale;
    }

    // 5. traces decay, then plasticity
    const float elig_decay = std::exp(-dt / static_cast<float>(p_.tau_elig_ms));
    const float da_decay = std::exp(-dt / static_cast<float>(p_.tau_da_ms));
    for (int32_t i = 0; i < n; ++i) {
        elig_[i] *= elig_decay;
        da_[i] *= da_decay;
    }
    if (timing_rule_) {
        const float fast_decay = std::exp(-dt / static_cast<float>(p_.timing_fast_tau_ms));
        for (int32_t m : plastic_post_idx_) da_fast_[m] *= fast_decay;
    }
    if (p_.plasticity_on && !timing_rule_ && step_ % plast_every_ == 0) apply_plasticity();

    head_ = (head_ + 1) % n_slots;
    ++step_;
}

void Simulator::emit_spike(int32_t i) {
    spikes_.push_back({i, static_cast<float>(time_ms())});
    ++counts_[i];
    elig_[i] += 1.0f;

    // schedule delivery delay_steps_ from now
    const int32_t n_slots = static_cast<int32_t>(buf_.size());
    std::vector<float>& later = buf_[(head_ + delay_steps_) % n_slots];
    for (int32_t k = net_.row_ptr[i]; k < net_.row_ptr[i + 1]; ++k)
        later[net_.col[k]] += w_[k];

    const bool timing = timing_rule_ && p_.plasticity_on;

    // timing rule, KC spike: strengthen its synapses onto MBONs where dopamine
    // arrived BEFORE this spike (the dopamine trace is still present)
    if (timing) {
        const float pot = static_cast<float>(p_.timing_potentiation);
        const float ratio = static_cast<float>(p_.tau_da_ms / p_.timing_fast_tau_ms);
        for (int32_t s : plastic_by_pre_[i]) {
            const PlasticSynapse& ps = net_.plastic[s];
            const float da = da_[ps.post] - ratio * da_fast_[ps.post];   // dopamine no longer arriving
            if (da < 1e-4f) continue;
            float& w = w_[ps.syn];
            w = std::min(w + pot * ps.w0 * da, ps.w0 * static_cast<float>(p_.w_max_frac));
        }
    }

    // a DAN spike releases dopamine onto the MBONs it innervates
    const float gain = net_.da_row_ptr[i] < net_.da_row_ptr[i + 1] ? static_cast<float>(release_gain(i)) : 1.0f;
    for (int32_t k = net_.da_row_ptr[i]; k < net_.da_row_ptr[i + 1]; ++k) {
        const int32_t m = net_.da_col[k];
        const float c = net_.da_coef[k] * gain;
        da_[m] += c;
        da_fast_[m] += c;
        // timing rule, dopamine spike: weaken synapses of KCs that fired BEFORE it
        if (!timing) continue;
        const float dep = static_cast<float>(p_.timing_depression) * c;
        for (int32_t s : net_.plastic_by_post[m]) {
            const PlasticSynapse& ps = net_.plastic[s];
            const float e = elig_[ps.pre];
            if (e < 1e-4f) continue;
            float& w = w_[ps.syn];
            w = std::max(w - dep * ps.w0 * e, ps.w0 * static_cast<float>(p_.w_min_frac));
        }
    }
}

// Three-factor rule: KC active recently (eligibility) AND dopamine at the
// MBON  ->  that KC->MBON synapse weakens.
void Simulator::apply_plasticity() {
    // the rule runs every plast_every_ steps, so it covers that much time
    const float step_lr = static_cast<float>(p_.learning_rate * p_.dt_ms * plast_every_);
    for (int32_t m : plastic_post_idx_) {
        const float da = da_[m];
        if (da < 1e-4f) continue;                 // no dopamine here: nothing to do
        for (int32_t s : net_.plastic_by_post[m]) {
            const PlasticSynapse& ps = net_.plastic[s];
            const float e = elig_[ps.pre];
            if (e < 1e-4f) continue;
            float& w = w_[ps.syn];
            w -= step_lr * ps.w0 * e * da;
            w = std::max(w, ps.w0 * static_cast<float>(p_.w_min_frac));
        }
    }
}

// ------------------------------------------------------------------ utilities

void Simulator::reset_counts() { std::fill(counts_.begin(), counts_.end(), 0); }

std::vector<float> Simulator::plastic_weights() const {
    std::vector<float> out;
    out.reserve(net_.plastic.size());
    for (const auto& ps : net_.plastic) out.push_back(w_[ps.syn]);
    return out;
}

void Simulator::reset_weights() { w_ = net_.weight; }

void Simulator::reset_state() {
    std::fill(v_.begin(), v_.end(), static_cast<float>(p_.v_rest_mV));
    std::fill(g_.begin(), g_.end(), 0.0f);
    std::fill(ref_.begin(), ref_.end(), 0);
    std::fill(elig_.begin(), elig_.end(), 0.0f);
    std::fill(da_.begin(), da_.end(), 0.0f);
    std::fill(da_fast_.begin(), da_fast_.end(), 0.0f);
    for (auto& slot : buf_) std::fill(slot.begin(), slot.end(), 0.0f);
    std::fill(pe_rate_hz_.begin(), pe_rate_hz_.end(), 0.0f);
    std::fill(ext_scale_.begin(), ext_scale_.end(), 1.0f);
    expect_shock_ = expect_reward_ = 0.0;
}

}  // namespace fruit_fly