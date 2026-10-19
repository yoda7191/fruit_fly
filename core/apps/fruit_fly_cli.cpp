// fruit_fly_cli.cpp — command-line front end to the fruit_fly library.
//
//   fruit_fly info      --circuit DIR
//   fruit_fly odours    --door DIR [--search TEXT]
//   fruit_fly condition --circuit DIR [--door DIR] [--cs-plus NAME] [--cs-minus NAME]
//                   [--trials N] [--us shock|reward] [--seed N]
//
// DIR for --circuit holds mb_neurons.csv and mb_edges.csv
// (from scripts/extract_mb_circuit.py or scripts/make_synthetic_mb.py).
// Without --door, odours are random glomerulus patterns seeded by their names.
#include <cmath>
#include <cstdio>
#include <exception>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

#include "fruit_fly/analysis.hpp"
#include "fruit_fly/experiment.hpp"
#include "fruit_fly/network.hpp"
#include "fruit_fly/odours.hpp"
#include "fruit_fly/params.hpp"

using namespace fruit_fly;

namespace {

const char* kUsage =
    "usage:\n"
    "  fruit_fly info      --circuit DIR\n"
    "  fruit_fly odours    --door DIR [--search TEXT]\n"
    "  fruit_fly condition --circuit DIR [--door DIR] [--cs-plus NAME] [--cs-minus NAME]\n"
    "                  [--trials N] [--us shock|reward] [--seed N]\n";

// --key value pairs after the subcommand
std::map<std::string, std::string> parse_options(int argc, char** argv, int first) {
    std::map<std::string, std::string> opts;
    for (int i = first; i < argc; ++i) {
        std::string key = argv[i];
        if (key.rfind("--", 0) != 0) throw std::runtime_error("unexpected argument '" + key + "'");
        if (i + 1 >= argc) throw std::runtime_error("missing value after " + key);
        opts[key.substr(2)] = argv[++i];
    }
    return opts;
}

std::string get(const std::map<std::string, std::string>& o, const std::string& key,
                const std::string& fallback = "") {
    auto it = o.find(key);
    return it == o.end() ? fallback : it->second;
}

std::string require(const std::map<std::string, std::string>& o, const std::string& key) {
    auto it = o.find(key);
    if (it == o.end()) throw std::runtime_error("--" + key + " is required");
    return it->second;
}

Network load_circuit(const std::string& dir, const Params& p) {
    return Network::load(dir + "/mb_neurons.csv", dir + "/mb_edges.csv", p);
}

// ------------------------------------------------------------------ info

int cmd_info(const std::map<std::string, std::string>& o) {
    Params p;
    Network net = load_circuit(require(o, "circuit"), p);
    std::printf("neurons %d, fast synapses %zu, plastic KC->MBON synapses %zu\n\n",
                net.size(), net.col.size(), net.plastic.size());
    std::map<std::string, int> per_group;
    for (const auto& g : net.group) per_group[g]++;
    for (const auto& [g, n] : per_group) std::printf("  %-10s %6d\n", g.c_str(), n);

    const auto ppl1 = dopamine_targets(net, net.indices_in_group("DAN_PPL1"));
    const auto pam = dopamine_targets(net, net.indices_in_group("DAN_PAM"));
    int n_ppl1 = 0, n_pam = 0;
    for (int32_t m : net.indices_in_group("MBON")) { n_ppl1 += ppl1[m]; n_pam += pam[m]; }
    std::printf("\nMBONs receiving PPL1 dopamine: %d, PAM dopamine: %d\n", n_ppl1, n_pam);
    return 0;
}

// ------------------------------------------------------------------ odours

int cmd_odours(const std::map<std::string, std::string>& o) {
    OdourLibrary lib = OdourLibrary::load(require(o, "door"));
    const std::string text = get(o, "search");
    const auto names = text.empty() ? lib.names() : lib.search(text);
    std::printf("%zu odours x %zu glomeruli", lib.names().size(), lib.glomeruli().size());
    if (!text.empty()) std::printf(", %zu matching '%s'", names.size(), text.c_str());
    std::printf("\n\n%-40s %s\n", "odour", "coverage");
    for (const auto& n : names) std::printf("%-40s %5.0f%%\n", n.c_str(), 100 * lib.coverage(n));
    return 0;
}

// ------------------------------------------------------------------ condition

int cmd_condition(const std::map<std::string, std::string>& o) {
    Params params;
    ProtocolConfig cfg;
    Network net = load_circuit(require(o, "circuit"), params);
    const std::string door = get(o, "door");
    const int trials = std::stoi(get(o, "trials", "3"));
    const US us = us_from_string(get(o, "us", "shock"));
    const uint64_t seed = std::stoull(get(o, "seed", "7"));

    std::string plus_name, minus_name;
    RateSet plus, minus, baseline;
    std::unique_ptr<OdourLibrary> lib;
    std::unique_ptr<OdourStimulus> stim;

    if (!door.empty()) {
        lib = std::make_unique<OdourLibrary>(OdourLibrary::load(door));
        stim = std::make_unique<OdourStimulus>(*lib, net);
        plus_name = get(o, "cs-plus", "3-octanol");
        minus_name = get(o, "cs-minus", "4-methylcyclohexanol");
        plus = stim->rates(plus_name);
        minus = stim->rates(minus_name);
        baseline = stim->baseline();
        std::printf("%s\n\n", stim->report().c_str());
        std::printf("%-24s DoOR coverage %3.0f%%\n", plus_name.c_str(), 100 * lib->coverage(plus_name));
        std::printf("%-24s DoOR coverage %3.0f%%\n", minus_name.c_str(), 100 * lib->coverage(minus_name));
        std::printf("%-24s r = %.2f\n", "input similarity", lib->similarity(plus_name, minus_name));
    } else {
        plus_name = get(o, "cs-plus", "odour_A");
        minus_name = get(o, "cs-minus", "odour_B");
        plus = random_odour(net, plus_name);
        minus = random_odour(net, minus_name);
        std::printf("random odours: %s drives %zu ORNs, %s drives %zu ORNs\n", plus_name.c_str(),
                    plus.neurons.size(), minus_name.c_str(), minus.neurons.size());
    }

    Experiment exp(net, params, cfg, seed);
    exp.set_baseline(baseline);
    exp.settle();
    ConditioningResult r =
        run_differential_conditioning(exp, plus_name, plus, minus_name, minus, trials, us);

    // ---- pattern separation (naive responses)
    Separation s = pattern_separation(net, r.pre_plus.counts, r.pre_minus.counts);
    std::printf("\nrepresentation similarity (spike-count correlation)\n");
    std::printf("  projection neurons %.2f\n  Kenyon cells       %.2f\n", s.pn_correlation,
                s.kc_correlation);
    std::printf("  KCs active: %.1f%% CS+, %.1f%% CS-, %d shared\n", 100 * s.kc_active_plus,
                100 * s.kc_active_minus, s.kc_shared);

    // ---- MBONs
    const auto target = dopamine_targets(net, exp.us_neurons(us));
    std::printf("\nMBON spikes per cell during 1 s of odour   US = %s x %d trials\n",
                to_string(us), trials);
    std::printf("%-14s %6s %8s %8s %8s %8s\n", "type", "US-DA", "CS+ pre", "CS+ post",
                "CS- pre", "CS- post");
    for (const auto& m : summarize_mbons(net, r, target))
        std::printf("%-14s %6s %8.1f %8.1f %8.1f %8.1f\n", m.cell_type.c_str(),
                    m.us_target ? "yes" : "", m.pre_plus, m.post_plus, m.pre_minus, m.post_minus);

    CompartmentChange c = compartment_change(net, r, target);
    if (c.valid)
        std::printf("\nUS-innervated MBONs: CS+ %+.0f%%, CS- %+.0f%%\n", 100 * c.cs_plus,
                    100 * c.cs_minus);
    else
        std::printf("\nUS-innervated MBONs did not respond; no change can be computed\n");
    std::printf("mean KC->MBON weight: %.1f%% of initial\n",
                100 * mean_weight_ratio(net, r.weights_after));

    // ---- behaviour
    BehaviorConfig bcfg;
    bcfg.seed = seed;
    BehaviorResult b = tmaze_test(net, r, bcfg);
    std::printf("\nT-maze (valence balance of MBON output; drive -1 = avoid .. +1 = approach)\n");
    std::printf("  approach drive before: CS+ %+.2f, CS- %+.2f\n", b.naive.drive_plus, b.naive.drive_minus);
    std::printf("  approach drive after : CS+ %+.2f, CS- %+.2f\n", b.trained.drive_plus, b.trained.drive_minus);
    if (!b.valid) {
        std::printf("  no prediction: %s\n",
                    b.valenced_mbons == 0
                        ? "no MBON has a known transmitter (re-extract the circuit with nt_type)"
                        : "the MBONs with a known transmitter did not fire for both odours");
        return 0;
    }
    std::printf("  performance index %+.2f  (a group of %d flies: %+.2f)\n", b.performance_index, b.flies,
                b.sampled_performance_index);
    std::printf("  (1 = every fly chooses as trained, 0 = no learning; %d MBONs with a valence)\n",
                b.valenced_mbons);
    return 0;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 2) {
        std::fputs(kUsage, stderr);
        return 1;
    }
    const std::string cmd = argv[1];
    try {
        auto opts = parse_options(argc, argv, 2);
        if (cmd == "info") return cmd_info(opts);
        if (cmd == "odours") return cmd_odours(opts);
        if (cmd == "condition") return cmd_condition(opts);
        std::fprintf(stderr, "unknown command '%s'\n%s", cmd.c_str(), kUsage);
        return 1;
    } catch (const std::exception& e) {
        std::fprintf(stderr, "error: %s\n", e.what());
        return 1;
    }
}