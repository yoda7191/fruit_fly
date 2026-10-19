#include "fruit_fly/analysis.hpp"

#include <algorithm>
#include <cmath>
#include <utility>
#include <map>

namespace fruit_fly {

double correlation(const std::vector<int32_t>& a, const std::vector<int32_t>& b,
                   const std::vector<int32_t>& idx) {
    if (idx.size() < 2) return NAN;
    double ma = 0, mb = 0;
    for (int32_t i : idx) { ma += a[i]; mb += b[i]; }
    ma /= idx.size();
    mb /= idx.size();
    double sab = 0, saa = 0, sbb = 0;
    for (int32_t i : idx) {
        sab += (a[i] - ma) * (b[i] - mb);
        saa += (a[i] - ma) * (a[i] - ma);
        sbb += (b[i] - mb) * (b[i] - mb);
    }
    return (saa == 0 || sbb == 0) ? NAN : sab / std::sqrt(saa * sbb);
}

double fraction_active(const std::vector<int32_t>& counts, const std::vector<int32_t>& idx) {
    if (idx.empty()) return 0.0;
    int32_t active = 0;
    for (int32_t i : idx) active += counts[i] > 0;
    return static_cast<double>(active) / idx.size();
}

int32_t shared_active(const std::vector<int32_t>& a, const std::vector<int32_t>& b,
                      const std::vector<int32_t>& idx) {
    int32_t n = 0;
    for (int32_t i : idx) n += a[i] > 0 && b[i] > 0;
    return n;
}

std::vector<uint8_t> dopamine_targets(const Network& net, const std::vector<int32_t>& dans) {
    std::vector<uint8_t> mask(net.size(), 0);
    for (int32_t d : dans)
        for (int32_t k = net.da_row_ptr[d]; k < net.da_row_ptr[d + 1]; ++k)
            mask[net.da_col[k]] = 1;
    return mask;
}

Separation pattern_separation(const Network& net, const std::vector<int32_t>& a,
                              const std::vector<int32_t>& b) {
    const auto pns = net.indices_in_group("ALPN");
    const auto kcs = net.indices_in_group("KC");
    Separation s;
    s.pn_correlation = correlation(a, b, pns);
    s.kc_correlation = correlation(a, b, kcs);
    s.kc_active_plus = fraction_active(a, kcs);
    s.kc_active_minus = fraction_active(b, kcs);
    s.kc_shared = shared_active(a, b, kcs);
    return s;
}

std::vector<MbonTypeSummary> summarize_mbons(const Network& net, const ConditioningResult& r,
                                             const std::vector<uint8_t>& us_target) {
    std::map<std::string, MbonTypeSummary> by_type;   // sorted by type name
    for (int32_t m : net.indices_in_group("MBON")) {
        MbonTypeSummary& s = by_type[net.cell_type[m]];
        s.cell_type = net.cell_type[m];
        s.n++;
        s.us_target = s.us_target || us_target[m];
        s.pre_plus += r.pre_plus.counts[m];
        s.post_plus += r.post_plus.counts[m];
        s.pre_minus += r.pre_minus.counts[m];
        s.post_minus += r.post_minus.counts[m];
    }
    std::vector<MbonTypeSummary> out;
    for (auto& [type, s] : by_type) {
        s.pre_plus /= s.n;
        s.post_plus /= s.n;
        s.pre_minus /= s.n;
        s.post_minus /= s.n;
        out.push_back(s);
    }
    return out;
}

namespace {

// Evoked activity: spikes minus the spontaneous expectation over the window
// (just the spikes if no spontaneous rates were measured).
std::vector<double> evoked(const Presentation& p, const std::vector<double>& spontaneous_hz) {
    std::vector<double> out(p.counts.begin(), p.counts.end());
    if (spontaneous_hz.size() == out.size())
        for (size_t i = 0; i < out.size(); ++i) out[i] -= spontaneous_hz[i] * p.duration_ms / 1000.0;
    return out;
}

}  // namespace

CompartmentChange compartment_change(const Network& net, const ConditioningResult& r,
                                     const std::vector<uint8_t>& us_target) {
    const auto pre_p = evoked(r.pre_plus, r.spontaneous_hz), post_p = evoked(r.post_plus, r.spontaneous_hz);
    const auto pre_m = evoked(r.pre_minus, r.spontaneous_hz), post_m = evoked(r.post_minus, r.spontaneous_hz);
    double pp = 0, qp = 0, pm = 0, qm = 0;
    for (int32_t m : net.indices_in_group("MBON")) {
        if (!us_target[m]) continue;
        pp += pre_p[m];
        qp += post_p[m];
        pm += pre_m[m];
        qm += post_m[m];
    }
    CompartmentChange c;
    if (pp > 0 && pm > 0) {
        c.valid = true;
        c.cs_plus = qp / pp - 1.0;
        c.cs_minus = qm / pm - 1.0;
    }
    return c;
}

double mean_weight_ratio(const Network& net, const std::vector<float>& weights) {
    if (weights.empty() || weights.size() != net.plastic.size()) return NAN;
    double sum = 0;
    for (size_t s = 0; s < weights.size(); ++s) sum += weights[s] / net.plastic[s].w0;
    return sum / weights.size();
}

// ====================================================================== behaviour

int valence_of_transmitter(const std::string& nt) {
    if (nt == "GLUT") return -1;
    if (nt == "ACH" || nt == "GABA") return 1;
    return 0;
}

std::vector<int8_t> mbon_valences(const Network& net) {
    std::vector<int8_t> v(net.size(), 0);
    for (int32_t m : net.indices_in_group("MBON"))
        v[m] = static_cast<int8_t>(valence_of_transmitter(net.transmitter[m]));
    return v;
}

namespace {

// (sum valence * spikes, sum spikes) over MBONs with a valence
// (sum valence * activity, sum |activity|) over MBONs with a valence. Activity is
// spikes, or evoked activity (may be negative) when spontaneous rates are known.
template <typename T>
std::pair<double, double> valenced_output(const std::vector<T>& activity,
                                          const std::vector<int8_t>& valence) {
    double weighted = 0, total = 0;
    const size_t n = std::min(activity.size(), valence.size());
    for (size_t i = 0; i < n; ++i) {
        if (valence[i] == 0) continue;
        const double a = static_cast<double>(activity[i]);
        weighted += valence[i] * a;
        total += std::abs(a);
    }
    return {weighted, total};
}

double drive(const std::vector<double>& activity, const std::vector<int8_t>& valence, double scale) {
    const auto [weighted, total] = valenced_output(activity, valence);
    (void)total;
    return scale > 0 ? weighted / scale : NAN;
}

}  // namespace

double approach_drive(const std::vector<int32_t>& counts, const std::vector<int8_t>& valence,
                      double scale) {
    const auto [weighted, total] = valenced_output(counts, valence);
    if (std::isfinite(scale)) return scale > 0 ? weighted / scale : NAN;
    return total > 0 ? weighted / total : NAN;
}

TMazeChoice tmaze_choice(double drive_plus, double drive_minus, double sharpness,
                         int32_t flies, std::mt19937_64& rng) {
    TMazeChoice c;
    c.drive_plus = drive_plus;
    c.drive_minus = drive_minus;
    if (std::isfinite(drive_plus) && std::isfinite(drive_minus))
        c.p_plus = 1.0 / (1.0 + std::exp(-sharpness * (drive_plus - drive_minus)));
    c.preference = 2.0 * c.p_plus - 1.0;
    c.flies = std::max(0, flies);
    if (c.flies > 0) {
        std::binomial_distribution<int32_t> pick(c.flies, c.p_plus);
        c.chose_plus = pick(rng);
        c.sampled_preference = (2.0 * c.chose_plus - c.flies) / c.flies;
    }
    return c;
}

BehaviorResult tmaze_test(const Network& net, const ConditioningResult& r,
                          const BehaviorConfig& config) {
    const auto valence = mbon_valences(net);
    std::mt19937_64 rng(config.seed);
    BehaviorResult b;
    for (int8_t v : valence) b.valenced_mbons += v != 0;
    // Scale: the larger naive valenced output of the two odours. Zero means no
    // valenced MBON responded to either odour before training: no prediction.
    const auto pre_p = evoked(r.pre_plus, r.spontaneous_hz), post_p = evoked(r.post_plus, r.spontaneous_hz);
    const auto pre_m = evoked(r.pre_minus, r.spontaneous_hz), post_m = evoked(r.post_minus, r.spontaneous_hz);
    // Scale: the larger naive evoked valenced output of the two odours (its size,
    // either sign). Zero means no valenced MBON responded before training: no prediction.
    const double scale = std::max(valenced_output(pre_p, valence).second,
                                  valenced_output(pre_m, valence).second);
    const double s = scale > 0 ? scale : 0.0;      // 0 -> every drive NaN -> invalid below
    b.naive = tmaze_choice(drive(pre_p, valence, s), drive(pre_m, valence, s),
                           config.sharpness, config.flies, rng);
    b.trained = tmaze_choice(drive(post_p, valence, s), drive(post_m, valence, s),
                             config.sharpness, config.flies, rng);
    const double before = b.naive.drive_plus - b.naive.drive_minus;
    const double after = b.trained.drive_plus - b.trained.drive_minus;
    b.valid = std::isfinite(before) && std::isfinite(after);
    if (!b.valid) return b;                  // NaN, not 0: "unknown" is not "no learning"
    b.learned_drive = after - before;

    // Learned part only: compare "CS+ with the learned change" against CS-.
    TMazeChoice learned = tmaze_choice(b.learned_drive, 0.0, config.sharpness, config.flies, rng);
    const double sign = r.us == US::Reward ? 1.0 : -1.0;   // shock teaches avoidance
    b.performance_index = sign * learned.preference;
    b.flies = learned.flies;
    b.sampled_performance_index = sign * learned.sampled_preference;
    return b;
}

}  // namespace fruit_fly