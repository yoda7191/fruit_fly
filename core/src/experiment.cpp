#include "fruit_fly/experiment.hpp"

#include <algorithm>
#include <sstream>
#include <stdexcept>
#include <unordered_map>

namespace fruit_fly {

const char* to_string(US us) {
    switch (us) {
        case US::None:   return "none";
        case US::Shock:  return "shock";
        case US::Reward: return "reward";
    }
    return "none";
}

US us_from_string(const std::string& s) {
    if (s == "none") return US::None;
    if (s == "shock") return US::Shock;
    if (s == "reward") return US::Reward;
    throw std::invalid_argument("unknown US '" + s + "' (use none, shock or reward)");
}

Experiment::Experiment(const Network& net, const Params& params,
                       const ProtocolConfig& config, uint64_t seed)
    : net_(net), cfg_(config), sim_(net, params, seed) {
    shock_ = net_.indices_in_group(cfg_.shock_group);
    reward_ = net_.indices_in_group(cfg_.reward_group);
}

const std::vector<int32_t>& Experiment::us_neurons(US us) const {
    switch (us) {
        case US::Shock:  return shock_;
        case US::Reward: return reward_;
        default:         return none_;
    }
}

void Experiment::set_baseline(const RateSet& baseline) {
    if (baseline.neurons.size() != baseline.hz.size())
        throw std::invalid_argument("baseline neurons and hz differ in length");
    baseline_ = baseline;
    rest();
}

void Experiment::rest() {
    sim_.clear_rates();
    sim_.apply(baseline_);
}

void Experiment::settle() {
    rest();
    sim_.run(cfg_.settle_ms);
    const Params& p = sim_.params();
    if ((p.mbon_tonic_mV > 0 || !p.mbon_tonic_by_type.empty()) && cfg_.spontaneous_ms > 0) {
        sim_.reset_counts();
        sim_.run(cfg_.spontaneous_ms);
        const auto& c = sim_.spike_counts();
        spontaneous_hz_.assign(c.size(), 0.0);
        for (size_t i = 0; i < c.size(); ++i) spontaneous_hz_[i] = c[i] * 1000.0 / cfg_.spontaneous_ms;
    }
}

const Presentation& Experiment::present(const std::string& label, const RateSet& odour, US us) {
    ProtocolStep step;
    step.odour = label;
    step.us = us;
    return present_step(step, &odour);
}

const Presentation& Experiment::present_step(const ProtocolStep& st, const RateSet* odour) {
    const bool has_odour = odour != nullptr;
    const bool has_us = st.us != US::None;
    if (!has_odour && !has_us) throw std::invalid_argument("a step needs an odour, a US, or both");
    const double odour_ms = st.odour_ms >= 0 ? st.odour_ms : cfg_.stim_ms;
    const double us_ms = st.us_ms >= 0 ? st.us_ms : (has_odour ? odour_ms : cfg_.stim_ms);
    const double gap_ms = st.gap_ms >= 0 ? st.gap_ms : cfg_.gap_ms;
    if (has_odour && !(odour_ms > 0)) throw std::invalid_argument("odour_ms must be > 0");
    if (has_us && !(us_ms > 0)) throw std::invalid_argument("us_ms must be > 0");
    const auto& dans = us_neurons(st.us);
    if (has_us && dans.empty())
        throw std::runtime_error(std::string("no neurons for US '") + to_string(st.us) +
                                 "' in this circuit");

    // Step time: 0 = odour onset (US onset if there's no odour). Spikes are
    // counted in [win_on, win_off): the odour, or the US for a US-only step.
    const double us_on = has_us && has_odour ? st.us_onset_ms : 0.0;
    const double us_off = us_on + us_ms;
    const double win_on = 0.0, win_off = has_odour ? odour_ms : us_ms;
    std::vector<double> edges{win_on, win_off};
    if (has_us) {
        edges.push_back(us_on);
        edges.push_back(us_off);
    }
    std::sort(edges.begin(), edges.end());
    edges.erase(std::unique(edges.begin(), edges.end()), edges.end());
    const double t0 = sim_.time_ms() - edges.front();     // absolute time of step-time 0

    Presentation p;
    p.label = has_odour ? st.odour : "US";
    p.phase = st.phase;
    p.us = st.us;
    p.t_start_ms = t0 + win_on;
    p.duration_ms = win_off - win_on;
    if (has_us) {
        p.us_start_ms = t0 + us_on;
        p.us_end_ms = t0 + us_off;
    }

    // Run segment by segment; within a segment the inputs are constant.
    for (size_t i = 0; i + 1 < edges.size(); ++i) {
        const double a = edges[i], b = edges[i + 1];
        if (a == win_on) sim_.reset_counts();
        rest();
        if (has_odour && a >= 0.0 && a < odour_ms) sim_.apply(*odour);   // overrides baseline ORN rates
        if (has_us && a >= us_on && a < us_off) sim_.set_rates(dans, cfg_.us_hz);
        sim_.run(b - a);
        if (b == win_off) p.counts = sim_.spike_counts();
    }

    rest();
    sim_.run(gap_ms);

    history_.push_back(std::move(p));
    return history_.back();
}

ConditioningResult run_differential_conditioning(
    Experiment& exp,
    const std::string& cs_plus_name, const RateSet& cs_plus,
    const std::string& cs_minus_name, const RateSet& cs_minus,
    int trials, US us, const ProgressCallback& progress) {
    if (trials < 0) throw std::invalid_argument("trials must be >= 0");

    // 2 pre-test + 2 per trial + 2 post-test presentations
    const int total = 2 * trials + 4;
    int done = 0;
    auto present = [&](const std::string& label, const RateSet& odour, US u) -> const Presentation& {
        const Presentation& p = exp.present(label, odour, u);
        ++done;
        if (progress) progress(done, total);
        return p;
    };

    ConditioningResult r;
    r.cs_plus = cs_plus_name;
    r.cs_minus = cs_minus_name;
    r.us = us;
    r.trials = trials;
    r.weights_before = exp.simulator().plastic_weights();

    r.pre_plus = present(cs_plus_name, cs_plus, US::None);
    r.pre_minus = present(cs_minus_name, cs_minus, US::None);
    for (int t = 0; t < trials; ++t) {
        present(cs_plus_name, cs_plus, us);
        present(cs_minus_name, cs_minus, US::None);
    }
    r.post_plus = present(cs_plus_name, cs_plus, US::None);
    r.post_minus = present(cs_minus_name, cs_minus, US::None);

    r.weights_after = exp.simulator().plastic_weights();
    r.spontaneous_hz = exp.spontaneous_hz();
    return r;
}

RateSet mix_odours(const std::vector<const RateSet*>& odours, const RateSet& baseline,
                   const std::string& mode, double max_rate_hz) {
    const bool binding = mode == "binding";
    if (!binding && mode != "linear")
        throw std::invalid_argument("mixture must be 'linear' or 'binding', got '" + mode + "'");
    if (binding && !(max_rate_hz > 0.0)) throw std::invalid_argument("max_rate_hz must be > 0");
    std::unordered_map<int32_t, double> base;
    for (size_t i = 0; i < baseline.neurons.size(); ++i) base[baseline.neurons[i]] = baseline.hz[i];

    // Per neuron: linear sum of changes, or the binding model's sums of occupancies.
    struct Acc { double base = 0, sum = 0, occ_up = 0, occ_down = 0; };
    std::map<int32_t, Acc> acc;                         // ordered: deterministic output
    for (const RateSet* o : odours) {
        if (o->neurons.size() != o->hz.size())
            throw std::invalid_argument("odour neurons and hz differ in length");
        for (size_t i = 0; i < o->neurons.size(); ++i) {
            const int32_t n = o->neurons[i];
            const auto b = base.find(n);
            auto [it, fresh] = acc.try_emplace(n);
            Acc& a = it->second;
            if (fresh) a.base = std::clamp(b == base.end() ? 0.0 : b->second, 0.0, max_rate_hz);
            const double d = o->hz[i] - a.base;
            a.sum += d;
            if (!binding) continue;
            // Occupancy x (bound / free, in units of the dissociation constant) that
            // gives this odour's response on its own: full agonist,
            //   r = base + (max - base) x / (1 + x)   ->  x = d / (max - base - d);
            // full inverse agonist, r = base - base x / (1 + x)  ->  x = -d / (base + d).
            // Responses at the very limits are pulled inside, so x stays finite.
            const double ceiling = max_rate_hz - a.base, floor_ = a.base;
            if (d > 0.0 && ceiling > 0.0)
                a.occ_up += std::min(d, 0.999 * ceiling) / (ceiling - std::min(d, 0.999 * ceiling));
            else if (d < 0.0 && floor_ > 0.0)
                a.occ_down += std::min(-d, 0.999 * floor_) / (floor_ - std::min(-d, 0.999 * floor_));
        }
    }
    RateSet out;
    for (const auto& [n, a] : acc) {
        // Competitive binding: every ligand takes its share of the one site,
        //   r = base + [(max - base) X_up - base X_down] / (1 + X_up + X_down).
        const double r = binding
            ? a.base + ((max_rate_hz - a.base) * a.occ_up - a.base * a.occ_down) / (1.0 + a.occ_up + a.occ_down)
            : a.base + a.sum;
        out.neurons.push_back(n);
        out.hz.push_back(std::max(0.0, r));
    }
    return out;
}

namespace {

// "A+C" -> {"A", "C"}; throws on empty parts or repeats.
std::vector<std::string> compound_slots(const std::string& key) {
    if (key.back() == '+') throw std::invalid_argument("odour '" + key + "' has an empty slot");
    std::vector<std::string> parts;
    std::stringstream ss(key);
    for (std::string part; std::getline(ss, part, '+');) {
        if (part.empty()) throw std::invalid_argument("odour '" + key + "' has an empty slot");
        if (std::find(parts.begin(), parts.end(), part) != parts.end())
            throw std::invalid_argument("odour '" + key + "' names slot '" + part + "' twice");
        parts.push_back(part);
    }
    return parts;
}

}  // namespace

std::vector<Presentation> run_protocol(Experiment& exp, const std::vector<ProtocolStep>& steps,
                                       const std::map<std::string, RateSet>& odours,
                                       const ProgressCallback& progress) {
    int total = 0;
    std::map<std::string, RateSet> compounds;          // "A+C" -> its mix
    for (const auto& st : steps) {                     // validate everything before running
        if (st.repeat < 1) throw std::invalid_argument("repeat must be >= 1");
        if (st.odour.empty() && st.us == US::None)
            throw std::invalid_argument("a step needs an odour, a US, or both");
        total += st.repeat;
        if (st.odour.empty() || odours.count(st.odour) || compounds.count(st.odour)) continue;
        const auto slots = compound_slots(st.odour);
        std::vector<const RateSet*> parts;
        for (const auto& s : slots) {
            if (!odours.count(s))
                throw std::invalid_argument("step uses odour slot '" + s + "', which isn't defined");
            parts.push_back(&odours.at(s));
        }
        const Params& p = exp.simulator().params();
        compounds.emplace(st.odour, mix_odours(parts, exp.baseline(), p.mixture, p.orn_max_rate_hz));
    }
    std::vector<Presentation> made;
    made.reserve(total);
    int done = 0;
    for (const auto& st : steps) {
        const RateSet* odour = st.odour.empty() ? nullptr
                               : odours.count(st.odour) ? &odours.at(st.odour) : &compounds.at(st.odour);
        for (int r = 0; r < st.repeat; ++r) {
            made.push_back(exp.present_step(st, odour));
            ++done;
            if (progress) progress(done, total);
        }
    }
    return made;
}

ConditioningResult conditioning_readout(const std::vector<Presentation>& presentations,
                                        const std::string& plus, const std::string& minus,
                                        const std::string& before_phase,
                                        const std::string& after_phase, US us, int trials,
                                        std::vector<float> weights_before,
                                        std::vector<float> weights_after,
                                        std::vector<double> spontaneous_hz) {
    auto find = [&](const std::string& slot, const std::string& phase) -> const Presentation& {
        for (const auto& p : presentations)
            if (p.label == slot && p.phase == phase && p.us == US::None) return p;
        throw std::invalid_argument("no US-free presentation of '" + slot + "' in phase '" +
                                    phase + "' to read out");
    };
    ConditioningResult r;
    r.cs_plus = plus;
    r.cs_minus = minus;
    r.us = us;
    r.trials = trials;
    r.pre_plus = find(plus, before_phase);
    r.pre_minus = find(minus, before_phase);
    r.post_plus = find(plus, after_phase);
    r.post_minus = find(minus, after_phase);
    r.weights_before = std::move(weights_before);
    r.weights_after = std::move(weights_after);
    r.spontaneous_hz = std::move(spontaneous_hz);
    return r;
}

}  // namespace fruit_fly