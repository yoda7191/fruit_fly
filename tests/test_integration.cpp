// test_integration.cpp — the whole model on a full circuit, plus DoOR odours.
//
// usage: test_integration <circuit_dir> <door_dir>
// Parts whose data are missing are skipped. Exit code 77 = everything skipped.
//
// These are behavioural checks with generous margins: they catch a model that
// stops producing sparse codes or specific memories, not small numeric drift.
#include <cstdio>
#include <filesystem>
#include <string>

#include "check.hpp"
#include "fruit_fly/analysis.hpp"
#include "fruit_fly/experiment.hpp"
#include "fruit_fly/network.hpp"
#include "fruit_fly/odours.hpp"

using namespace fruit_fly;
namespace fs = std::filesystem;

static std::string g_circuit, g_door;
static bool has_circuit() { return fs::exists(g_circuit + "/mb_neurons.csv"); }
static bool has_door() { return fs::exists(g_door + "/door_response_matrix.csv"); }

static Network load(const Params& p) {
    return Network::load(g_circuit + "/mb_neurons.csv", g_circuit + "/mb_edges.csv", p);
}

TEST_CASE(apl_makes_kc_code_sparse) {
    if (!has_circuit()) return;
    for (bool with_apl : {true, false}) {
        Params p;
        if (!with_apl) p.graded_gain = 0.0;   // APL present but releases nothing
        Network net = load(p);
        Experiment exp(net, p, ProtocolConfig(), 1);
        exp.settle();
        const auto& pr = exp.present("A", random_odour(net, "odour_A"));
        double frac = fraction_active(pr.counts, net.indices_in_group("KC"));
        if (with_apl) CHECK(frac > 0.01 && frac < 0.15);
        else CHECK(frac > 0.15);
    }
}

TEST_CASE(shock_creates_specific_memory_random_odours) {
    if (!has_circuit()) return;
    Params p;
    Network net = load(p);
    Experiment exp(net, p, ProtocolConfig(), 7);
    exp.settle();
    auto r = run_differential_conditioning(exp, "A", random_odour(net, "odour_A"),
                                           "B", random_odour(net, "odour_B"), 3, US::Shock);
    auto target = dopamine_targets(net, exp.us_neurons(US::Shock));
    auto c = compartment_change(net, r, target);
    CHECK(c.valid);
    CHECK(c.cs_plus < -0.3);                     // CS+ response clearly reduced
    CHECK(c.cs_minus > -0.15);                   // CS- essentially unchanged
    CHECK(tmaze_test(net, r).performance_index > 0.3);    // flies learn to avoid CS+

    // compartments without the US dopamine are untouched
    auto reward = dopamine_targets(net, exp.us_neurons(US::Reward));
    auto rc = compartment_change(net, r, reward);
    if (rc.valid) CHECK(rc.cs_plus > -0.15);
}

TEST_CASE(door_library_loads) {
    if (!has_door()) return;
    OdourLibrary lib = OdourLibrary::load(g_door);
    CHECK(lib.glomeruli().size() >= 40);
    CHECK(lib.names().size() > 500);
    CHECK(lib.coverage("ethyl acetate") > 0.8);
    CHECK_NEAR(lib.similarity("ethyl acetate", "ethyl acetate"), 1.0, 1e-9);
    CHECK(lib.odour_index("3-OCTANOL") == lib.odour_index("3-octanol"));   // case-insensitive
    bool threw = false;
    try { lib.raw("not an odour"); } catch (const std::out_of_range&) { threw = true; }
    CHECK(threw);
}

TEST_CASE(real_odours_dissimilar_pair_is_specific) {
    if (!has_circuit() || !has_door()) return;
    Params p;
    Network net = load(p);
    OdourLibrary lib = OdourLibrary::load(g_door);
    OdourStimulus stim(lib, net);
    CHECK(!stim.matched().empty());
    auto base = stim.baseline();
    CHECK(base.neurons.size() == base.hz.size());

    Experiment exp(net, p, ProtocolConfig(), 1);
    exp.set_baseline(base);
    exp.settle();
    auto r = run_differential_conditioning(exp, "ethyl acetate", stim.rates("ethyl acetate"),
                                           "benzaldehyde", stim.rates("benzaldehyde"), 3,
                                           US::Shock);
    auto c = compartment_change(net, r, dopamine_targets(net, exp.us_neurons(US::Shock)));
    CHECK(c.valid);
    CHECK(c.cs_plus < -0.3);
    CHECK(c.cs_minus > -0.15);
    CHECK(tmaze_test(net, r).performance_index > 0.5);
}

int main(int argc, char** argv) {
    if (argc < 3) {
        std::fprintf(stderr, "usage: %s <circuit_dir> <door_dir>\n", argv[0]);
        return 2;
    }
    g_circuit = argv[1];
    g_door = argv[2];
    std::printf("circuit data: %s\nDoOR data:    %s\n\n", has_circuit() ? "found" : "missing (skipping)",
                has_door() ? "found" : "missing (skipping)");
    if (!has_circuit() && !has_door()) return 77;
    return check::run_all();
}