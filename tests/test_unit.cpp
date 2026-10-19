// test_unit.cpp — fast tests on tiny hand-built circuits. No data files needed.
#include <cmath>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <string>

#include "check.hpp"
#include "fruit_fly/analysis.hpp"
#include "fruit_fly/csv.hpp"
#include "fruit_fly/experiment.hpp"
#include "fruit_fly/network.hpp"
#include "fruit_fly/simulator.hpp"

using namespace fruit_fly;
namespace fs = std::filesystem;

namespace {

fs::path temp_dir() {
    fs::path d = fs::temp_directory_path() / "fruit_fly_unit_tests";
    fs::create_directories(d);
    return d;
}

std::string write_file(const std::string& name, const std::string& text) {
    fs::path p = temp_dir() / name;
    std::ofstream(p) << text;
    return p.string();
}

// Tiny circuit:
//   ORN(1) -> PN(2) -> KC(3), KC(4) -> MBON(5), MBON(6)
//   APL(7) <-> KCs, DAN_PPL1(8) -> MBON(5) (dopamine), KC(3) -> KC(4) (excluded)
Network tiny_network(const Params& p) {
    auto neurons = write_file("n.csv",
        "root_id,group,cell_type,side,x,y,z\n"
        "1,ORN,ORN_DA1,right,0,0,0\n"
        "2,ALPN,DA1_PN,right,1,0,0\n"
        "3,KC,KCg,right,2,0,0\n"
        "4,KC,KCg,right,2,1,0\n"
        "5,MBON,MBON01,right,3,0,0\n"
        "6,MBON,MBON02,right,3,1,\n"
        "7,APL,APL,right,2,2,0\n"
        "8,DAN_PPL1,PPL101,right,4,0,0\n");
    auto edges = write_file("e.csv",
        "pre_root_id,post_root_id,syn_count,nt_type,sign\n"
        "1,2,100,ACH,1\n"
        "2,3,100,ACH,1\n"
        "2,4,100,ACH,1\n"
        "3,5,30,ACH,1\n"
        "4,5,30,ACH,1\n"
        "3,6,30,ACH,1\n"
        "3,7,5,ACH,1\n"
        "7,3,10,GABA,-1\n"
        "8,5,12,DA,0\n"
        "3,4,50,ACH,1\n"
        "99,5,10,ACH,1\n");      // unknown neuron: ignored
    return Network::load(neurons, edges, p);
}

}  // namespace

// ------------------------------------------------------------------ csv

TEST_CASE(csv_splits_quoted_fields) {
    auto f = split_csv_line("a,\"b, c\",\"say \"\"hi\"\"\",", ',');
    CHECK(f.size() == 4);
    CHECK(f[1] == "b, c");
    CHECK(f[2] == "say \"hi\"");
    CHECK(f[3].empty());
}

TEST_CASE(csv_quoted_line_breaks) {
    auto path = write_file("nl.csv", "a,b\n1,\"two\nlines\"\n3,4\n");
    CsvTable t = read_csv(path);
    CHECK(t.rows.size() == 2);
    CHECK(t.rows[0][1] == "two\nlines");
    CHECK(t.rows[1][0] == "3");
}

TEST_CASE(csv_semicolon_and_r_style_header) {
    auto path = write_file("r.csv", "\"x\";\"y\"\n\"row1\";1;NA\n\"row2\";2;3\r\n");
    CsvTable t = read_csv(path, ';');
    CHECK(t.header.size() == 3);
    CHECK(t.header[0].empty());          // row-name column was added
    CHECK(t.col("y") == 2);
    CHECK(t.rows[0][0] == "row1");
    CHECK(t.rows[1][2] == "3");          // \r stripped
}

// ------------------------------------------------------------------ network

TEST_CASE(network_builds_csr_and_signs) {
    Params p;
    Network net = tiny_network(p);
    CHECK(net.size() == 8);
    CHECK(net.row_ptr.size() == 9);
    // fast synapses: 11 rows - DA (sign 0) - KC->KC (excluded) - unknown = 8
    CHECK(net.col.size() == 8);
    CHECK(net.row_ptr.back() == static_cast<int32_t>(net.col.size()));

    int32_t pn = net.index_of(2);
    CHECK(net.row_ptr[pn + 1] - net.row_ptr[pn] == 2);          // PN -> 2 KCs
    int32_t apl = net.index_of(7);
    int32_t k = net.row_ptr[apl];
    CHECK_NEAR(net.weight[k], -10 * p.w_syn_mV, 1e-5);          // GABA is negative
    CHECK(net.graded[apl] == 1);
    CHECK(std::isnan(net.z[net.index_of(6)]));                   // empty coordinate
}

TEST_CASE(network_plasticity_and_dopamine_tables) {
    Params p;
    Network net = tiny_network(p);
    CHECK(net.plastic.size() == 3);                              // KC3->5, KC4->5, KC3->6
    int32_t m5 = net.index_of(5), dan = net.index_of(8);
    CHECK(net.plastic_by_post[m5].size() == 2);
    CHECK(net.da_row_ptr[dan + 1] - net.da_row_ptr[dan] == 1);
    CHECK(net.da_col[net.da_row_ptr[dan]] == m5);
    CHECK_NEAR(net.da_coef[net.da_row_ptr[dan]], 1.0, 1e-6);     // sole DAN -> normalised to 1
}

TEST_CASE(network_excluded_pairs_can_be_disabled) {
    Params p;
    p.excluded_pairs.clear();
    Network net = tiny_network(p);
    CHECK(net.col.size() == 9);                                  // KC->KC now present
}

// ------------------------------------------------------------------ simulator

TEST_CASE(simulator_poisson_drive_matches_rate) {
    Params p;
    Network net = tiny_network(p);
    Simulator sim(net, p, 3);
    int32_t orn = net.index_of(1);
    sim.set_rate(orn, 50.0);
    sim.run(10000);                                              // 10 s
    CHECK_NEAR(sim.spike_counts()[orn], 500, 60);                // Poisson noise ~ sqrt(500)
}

TEST_CASE(simulator_respects_delay_and_refractory) {
    Params p;
    Network net = tiny_network(p);
    Simulator sim(net, p, 3);
    int32_t orn = net.index_of(1), pn = net.index_of(2);
    sim.set_rate(orn, 1e9);                                      // spike whenever possible
    sim.run(100);
    const auto& sp = sim.spikes();
    float first_orn = -1, first_pn = -1;
    for (const auto& s : sp) {
        if (s.neuron == orn && first_orn < 0) first_orn = s.t_ms;
        if (s.neuron == pn && first_pn < 0) first_pn = s.t_ms;
    }
    CHECK(first_orn >= 0 && first_pn > first_orn);
    CHECK(first_pn - first_orn >= p.delay_ms - 1e-3);            // no faster than the delay
    // refractory: at most one spike per (t_ref + dt)
    CHECK(sim.spike_counts()[orn] <= static_cast<int>(100.0 / p.t_ref_ms) + 1);
}

TEST_CASE(simulator_rate_overloads_and_clear) {
    Params p;
    Network net = tiny_network(p);
    Simulator sim(net, p, 3);
    RateSet rs{{net.index_of(1), net.index_of(8)}, {100.0, 20.0}};
    sim.apply(rs);
    sim.run(1000);
    CHECK(sim.spike_counts()[net.index_of(8)] > 5);
    sim.clear_rates();
    sim.reset_counts();
    sim.reset_state();
    sim.run(500);
    CHECK(sim.spike_counts()[net.index_of(1)] == 0);
    bool threw = false;
    try { sim.set_rates({0, 1}, std::vector<double>{1.0}); } catch (const std::invalid_argument&) { threw = true; }
    CHECK(threw);
}

TEST_CASE(learning_needs_kc_activity_and_dopamine) {
    Params p;
    p.graded_groups.clear();                                     // keep the tiny circuit simple
    p.learning_rate = 1e-4;
    Network net = tiny_network(p);
    int32_t orn = net.index_of(1), dan = net.index_of(8);

    // dopamine alone: no KC activity -> no change
    Simulator a(net, p, 1);
    a.set_rate(dan, 40.0);
    a.run(1000);
    for (size_t s = 0; s < net.plastic.size(); ++s) CHECK_NEAR(a.plastic_weights()[s], net.plastic[s].w0, 1e-6);

    // odour alone: KCs fire but no dopamine -> no change
    Simulator b(net, p, 1);
    b.set_rate(orn, 100.0);
    b.run(1000);
    for (size_t s = 0; s < net.plastic.size(); ++s) CHECK_NEAR(b.plastic_weights()[s], net.plastic[s].w0, 1e-6);

    // odour + dopamine: synapses onto the DAN's MBON weaken, others don't
    Simulator c(net, p, 1);
    c.set_rate(orn, 100.0);
    c.set_rate(dan, 40.0);
    c.run(1000);
    auto w = c.plastic_weights();
    int32_t m5 = net.index_of(5);
    for (size_t s = 0; s < net.plastic.size(); ++s) {
        if (net.plastic[s].post == m5) CHECK(w[s] < 0.9f * net.plastic[s].w0);
        else CHECK_NEAR(w[s], net.plastic[s].w0, 1e-6);
        CHECK(w[s] >= 0.0f);                                     // bounded below
    }
    c.reset_weights();
    CHECK_NEAR(c.plastic_weights()[0], net.plastic[0].w0, 1e-6);
}

// ------------------------------------------------------------------ experiment + analysis

TEST_CASE(experiment_records_history_and_us) {
    Params p;
    Network net = tiny_network(p);
    Experiment exp(net, p, ProtocolConfig(), 5);
    exp.settle();
    RateSet odour{{net.index_of(1)}, {80.0}};
    exp.present("odour", odour, US::Shock);
    exp.present("odour", odour);
    CHECK(exp.history().size() == 2);
    CHECK(exp.history()[0].us == US::Shock);
    CHECK(exp.history()[0].counts[net.index_of(8)] > 0);        // DAN driven by the shock
    CHECK(exp.history()[1].counts[net.index_of(8)] == 0);
    CHECK(exp.history()[1].t_start_ms > exp.history()[0].t_start_ms);
    bool threw = false;
    try { exp.present("odour", odour, US::Reward); } catch (const std::runtime_error&) { threw = true; }
    CHECK(threw);                                                // no PAM in the tiny circuit
    CHECK(us_from_string("reward") == US::Reward);
}

TEST_CASE(conditioning_reports_progress) {
    Params p;
    Network net = tiny_network(p);
    ProtocolConfig cfg;
    cfg.stim_ms = 20;
    cfg.gap_ms = 20;
    Experiment exp(net, p, cfg, 5);
    RateSet odour{{net.index_of(1)}, {80.0}};
    std::vector<std::pair<int, int>> calls;
    auto r = run_differential_conditioning(exp, "A", odour, "B", RateSet{}, 2, US::Shock,
                                           [&](int done, int total) { calls.push_back({done, total}); });
    CHECK(calls.size() == 8);                       // 2 pre + 2x2 training + 2 post
    CHECK(calls.front() == std::make_pair(1, 8));
    CHECK(calls.back() == std::make_pair(8, 8));
    CHECK(r.trials == 2);
    // no callback is fine too
    run_differential_conditioning(exp, "A", odour, "B", RateSet{}, 0, US::Shock);
    CHECK(exp.history().size() == 8 + 4);
}

TEST_CASE(network_records_transmitters) {
    Params p;
    Network net = tiny_network(p);
    CHECK(net.transmitter[net.index_of(1)] == "ACH");
    CHECK(net.transmitter[net.index_of(7)] == "GABA");
    CHECK(net.transmitter[net.index_of(8)] == "DA");
    CHECK(net.transmitter[net.index_of(5)].empty());            // no outputs in the file
}

TEST_CASE(behaviour_valence_and_drive) {
    CHECK(valence_of_transmitter("GLUT") == -1);
    CHECK(valence_of_transmitter("ACH") == 1);
    CHECK(valence_of_transmitter("GABA") == 1);
    CHECK(valence_of_transmitter("DA") == 0);
    std::vector<int8_t> v{1, -1, 0};
    CHECK_NEAR(approach_drive({30, 10, 99}, v), 0.5, 1e-12);    // (30 - 10) / 40
    CHECK(std::isnan(approach_drive({0, 0, 5}, v)));
}

TEST_CASE(behaviour_tmaze_choice) {
    std::mt19937_64 rng(1);
    auto even = tmaze_choice(0.2, 0.2, 6.0, 1000, rng);
    CHECK_NEAR(even.p_plus, 0.5, 1e-12);
    CHECK_NEAR(even.sampled_preference, 0.0, 0.1);              // binomial noise
    auto prefer = tmaze_choice(0.5, -0.5, 6.0, 0, rng);
    CHECK(prefer.p_plus > 0.99 && prefer.preference > 0.98);
    auto unknown = tmaze_choice(NAN, 0.3, 6.0, 10, rng);
    CHECK_NEAR(unknown.p_plus, 0.5, 1e-12);
}

TEST_CASE(network_prefers_declared_transmitter) {
    // In-circuit edges say ACH, but the extractor saw the whole brain: GLUT.
    Params p;
    auto neurons = write_file("tn.csv",
        "root_id,group,cell_type,side,x,y,z,nt_type\n"
        "1,MBON,M1,r,0,0,0,GLUT\n2,MBON,M2,r,0,0,0,\n3,DAN_PPL1,P,r,0,0,0,DA\n");
    auto edges = write_file("te.csv", "pre_root_id,post_root_id,syn_count,nt_type,sign\n"
                                      "1,3,50,ACH,1\n2,3,50,ACH,1\n");
    Network net = Network::load(neurons, edges, p);
    CHECK(net.transmitter[net.index_of(1)] == "GLUT");            // declared wins
    CHECK(net.transmitter[net.index_of(2)] == "ACH");             // empty -> in-circuit vote
    CHECK(net.transmitter[net.index_of(3)] == "DA");
    CHECK(mbon_valences(net)[net.index_of(1)] == -1);
}

TEST_CASE(behaviour_performance_index_cancels_bias) {
    // Case 1: before training, neither odour evokes valenced output: nothing to
    // scale by -> no prediction (never a performance index of 0, which would read
    // as "no learning").
    Params p;
    auto neurons = write_file("bn.csv",
        "root_id,group,cell_type,side,x,y,z\n1,MBON,MBON01,r,0,0,0\n2,DAN_PPL1,PPL1,r,0,0,0\n");
    auto edges = write_file("be.csv",
        "pre_root_id,post_root_id,syn_count,nt_type,sign\n1,2,5,ACH,1\n");
    Network net = Network::load(neurons, edges, p);
    ConditioningResult r;
    r.us = US::Shock;
    auto counts = [&](int n) { std::vector<int32_t> c(net.size(), 0); c[0] = n; return c; };
    r.pre_plus.counts = counts(0);   r.pre_minus.counts = counts(0);
    r.post_plus.counts = counts(20); r.post_minus.counts = counts(0);
    BehaviorResult same = tmaze_test(net, r);
    CHECK(!same.valid);
    CHECK(same.valenced_mbons == 1);
    CHECK(std::isnan(same.learned_drive));
    CHECK(std::isnan(same.performance_index));
    CHECK(std::isnan(same.sampled_performance_index));
    // Case 1c: a silent odour is neutral (drive 0), not undefined: CS- silent,
    // CS+ unchanged -> valid, and nothing learned.
    r.pre_plus.counts = counts(20);
    r.post_plus.counts = counts(20);
    BehaviorResult silent = tmaze_test(net, r);
    CHECK(silent.valid);
    CHECK_NEAR(silent.naive.drive_minus, 0.0, 1e-12);
    CHECK_NEAR(silent.learned_drive, 0.0, 1e-12);
    // Case 1b: no MBON has a known transmitter (e.g. its outputs were cut off
    // during circuit extraction): also invalid, and says why.
    auto nb = write_file("bn_b.csv",
        "root_id,group,cell_type,side,x,y,z\n1,MBON,MBON01,r,0,0,0\n2,DAN_PPL1,PPL1,r,0,0,0\n");
    auto eb = write_file("be_b.csv", "pre_root_id,post_root_id,syn_count,nt_type,sign\n2,1,5,DA,0\n");
    Network netb = Network::load(nb, eb, p);
    r.pre_minus.counts = counts(20); r.post_minus.counts = counts(20);
    BehaviorResult blind = tmaze_test(netb, r);
    CHECK(!blind.valid);
    CHECK(blind.valenced_mbons == 0);
    // Case 2: one approach (ACH) and one avoidance (GLUT) MBON; the naive fly
    // prefers CS+, training removes CS+'s approach output. The innate bias must
    // not count as learning.
    auto n2 = write_file("bn2.csv", "root_id,group,cell_type,side,x,y,z\n"
                                   "1,MBON,A,r,0,0,0\n2,MBON,B,r,0,0,0\n3,DAN_PPL1,P,r,0,0,0\n");
    auto e2 = write_file("be2.csv", "pre_root_id,post_root_id,syn_count,nt_type,sign\n"
                                   "1,3,5,ACH,1\n2,3,5,GLUT,-1\n");
    Network net2 = Network::load(n2, e2, p);
    auto c2 = [](int approach, int avoid) { return std::vector<int32_t>{approach, avoid, 0}; };
    ConditioningResult s;
    s.us = US::Shock;
    s.pre_plus.counts = c2(30, 10);  s.pre_minus.counts = c2(10, 30);   // innate bias toward CS+
    s.post_plus.counts = c2(10, 30); s.post_minus.counts = c2(10, 30);  // approach output to CS+ weakened
    BehaviorConfig cfg;
    cfg.flies = 200;
    BehaviorResult b = tmaze_test(net2, s, cfg);
    CHECK_NEAR(b.naive.drive_plus, 0.5, 1e-12);
    CHECK_NEAR(b.learned_drive, -1.0, 1e-12);                    // (-0.5 - -0.5) - (0.5 - -0.5)
    CHECK(b.performance_index > 0.99);                           // strong avoidance, positive for shock
    CHECK(b.sampled_performance_index > 0.9);
    // Extinction-like case: CS+ output of BOTH kinds collapses after training.
    // The ratio still says "all avoidance"; the net output correctly says
    // "barely anything", i.e. most of the learned avoidance is gone.
    ConditioningResult x = s;
    x.post_plus.counts = c2(2, 6);                               // ratio -0.5, net only -4
    BehaviorResult ext = tmaze_test(net2, x, cfg);
    CHECK_NEAR(approach_drive(x.post_plus.counts, {1, -1, 0}), -0.5, 1e-12);
    CHECK_NEAR(ext.trained.drive_plus, -0.1, 1e-12);             // -4 / 40
    CHECK(ext.performance_index < b.performance_index);
    s.us = US::Reward;
    CHECK(tmaze_test(net2, s, cfg).performance_index < -0.99);   // wrong direction for reward
}

TEST_CASE(protocol_steps_match_the_classic_protocol_exactly) {
    Params p;
    Network net = tiny_network(p);
    ProtocolConfig cfg;
    cfg.stim_ms = 100;
    cfg.gap_ms = 100;
    RateSet a{{net.index_of(1)}, {80.0}}, b{};
    Experiment classic(net, p, cfg, 9);
    auto r1 = run_differential_conditioning(classic, "A", a, "B", b, 2, US::Shock);

    Experiment stepped(net, p, cfg, 9);
    std::vector<ProtocolStep> steps;
    auto step = [](std::string phase, std::string odour, US us, int repeat = 1) {
        ProtocolStep s; s.phase = phase; s.odour = odour; s.us = us; s.repeat = repeat; return s;
    };
    steps = {step("pre", "A", US::None), step("pre", "B", US::None)};
    for (int t = 0; t < 2; ++t) {
        steps.push_back(step("training", "A", US::Shock));
        steps.push_back(step("training", "B", US::None));
    }
    steps.push_back(step("post", "A", US::None));
    steps.push_back(step("post", "B", US::None));
    auto made = run_protocol(stepped, steps, {{"A", a}, {"B", b}});
    CHECK(made.size() == 8);
    auto r2 = conditioning_readout(made, "A", "B", "pre", "post", US::Shock, 2, {}, {});
    CHECK(r2.pre_plus.counts == r1.pre_plus.counts);       // identical, not just similar
    CHECK(r2.post_plus.counts == r1.post_plus.counts);
    CHECK(r2.post_minus.counts == r1.post_minus.counts);
    CHECK(stepped.simulator().plastic_weights() == classic.simulator().plastic_weights());
}

TEST_CASE(protocol_step_timing_and_validation) {
    Params p;
    Network net = tiny_network(p);
    ProtocolConfig cfg;
    cfg.stim_ms = 100;
    cfg.gap_ms = 50;
    Experiment exp(net, p, cfg, 3);
    RateSet odour{{net.index_of(1)}, {80.0}};
    ProtocolStep back;                        // US 300 ms before the odour, lasting 200 ms
    back.odour = "A"; back.us = US::Shock; back.us_onset_ms = -300; back.us_ms = 200;
    const double t_before = exp.simulator().time_ms();
    const Presentation& pb = exp.present_step(back, &odour);
    CHECK_NEAR(pb.us_start_ms, t_before, 1e-6);
    CHECK_NEAR(pb.us_end_ms, t_before + 200, 1e-6);
    CHECK_NEAR(pb.t_start_ms, t_before + 300, 1e-6);       // odour starts after the US
    CHECK_NEAR(pb.duration_ms, 100, 1e-9);
    CHECK_NEAR(exp.simulator().time_ms(), t_before + 300 + 100 + 50, 1e-6);
    CHECK(pb.counts[net.index_of(8)] == 0);                 // DAN silent during the odour window

    ProtocolStep us_only;                                   // US alone: counted over the US
    us_only.us = US::Shock; us_only.us_ms = 100;
    const Presentation& pu = exp.present_step(us_only, nullptr);
    CHECK(pu.label == "US" && pu.counts[net.index_of(8)] > 0);

    bool threw = false;
    try { exp.present_step(ProtocolStep{}, nullptr); } catch (const std::invalid_argument&) { threw = true; }
    CHECK(threw);                                           // neither odour nor US
    threw = false;
    ProtocolStep missing; missing.odour = "Z";
    try { run_protocol(exp, {missing}, {{"A", odour}}); } catch (const std::invalid_argument&) { threw = true; }
    CHECK(threw);                                           // undefined odour slot, before running
    threw = false;
    try { conditioning_readout(exp.history(), "A", "B", "pre", "post", US::Shock, 0, {}, {}); }
    catch (const std::invalid_argument&) { threw = true; }
    CHECK(threw);
}

TEST_CASE(silenced_neurons_never_fire_or_transmit) {
    Params p;
    Network net = tiny_network(p);
    Simulator sim(net, p, 3);
    const int32_t orn = net.index_of(1), pn = net.index_of(2);
    sim.silence({pn});
    sim.set_rate(orn, 200.0);
    sim.run(500);
    CHECK(sim.spike_counts()[orn] > 50);                    // its input still fires
    CHECK(sim.spike_counts()[pn] == 0);                     // the lesioned neuron doesn't
    CHECK(sim.spike_counts()[net.index_of(3)] == 0);        // nor anything downstream of it
    sim.silence({orn});
    sim.reset_counts();
    sim.run(200);
    CHECK(sim.spike_counts()[orn] == 0);                    // external drive is ignored too
    sim.clear_silenced();
    sim.reset_counts();
    sim.run(200);
    CHECK(sim.spike_counts()[orn] > 0);
}

TEST_CASE(timing_rule_order_sets_the_sign) {
    Params p;
    p.graded_groups.clear();
    p.plasticity_rule = "timing";
    p.timing_depression = 2e-2;
    p.timing_potentiation = 2e-2;
    Network net = tiny_network(p);
    const int32_t orn = net.index_of(1), dan = net.index_of(8), m5 = net.index_of(5);
    auto mean_ratio = [&](const Simulator& sim) {
        double sum = 0; int n = 0;
        auto w = sim.plastic_weights();
        for (size_t s = 0; s < w.size(); ++s)
            if (net.plastic[s].post == m5) { sum += w[s] / net.plastic[s].w0; ++n; }
        return sum / n;
    };
    Simulator forward(net, p, 1);                           // KC activity, then dopamine
    forward.set_rate(orn, 100.0); forward.run(300);
    forward.clear_rates(); forward.set_rate(dan, 40.0); forward.run(300);
    CHECK(mean_ratio(forward) < 0.95);

    Simulator backward(net, p, 1);                          // dopamine, then KC activity
    backward.set_rate(dan, 40.0); backward.run(300);
    backward.clear_rates(); backward.set_rate(orn, 100.0); backward.run(300);
    CHECK(mean_ratio(backward) > 1.05);
    for (float w : backward.plastic_weights()) CHECK(w <= 2.0f * 100 * p.w_syn_mV + 1e-3f);

    p.plasticity_rule = "nonsense";
    bool threw = false;
    try { Simulator bad(net, p, 1); } catch (const std::invalid_argument&) { threw = true; }
    CHECK(threw);
}

TEST_CASE(prediction_error_expectation_tracks_learning) {
    Params p;
    p.graded_groups.clear();
    p.learning_rate = 1e-4;
    p.prediction_error = true;
    p.pe_min_trace = 0.5;
    Network net = tiny_network(p);
    const int32_t orn = net.index_of(1), dan = net.index_of(8);
    Simulator sim(net, p, 1);
    sim.set_rate(orn, 100.0);                                   // odour, naive
    sim.run(300);
    CHECK_NEAR(sim.expected_shock(), 0.0, 1e-6);               // nothing learned yet
    sim.set_rate(dan, 40.0);                                    // odour + shock
    sim.run(1000);
    sim.set_rate(dan, 0.0);                                     // odour alone again
    sim.run(300);
    CHECK(sim.expected_shock() > 0.3);                          // the learned odour predicts shock
    CHECK_NEAR(sim.expected_reward(), 0.0, 1e-6);               // no PAM in this circuit
    sim.clear_rates();                                          // no odour: no KC activity to judge
    sim.run(3000);
    CHECK_NEAR(sim.expected_shock(), 0.0, 1e-6);
    sim.reset_state();
    CHECK_NEAR(sim.expected_shock(), 0.0, 1e-6);

    Params off;                                                 // default: off, never computed
    Simulator plain(net, off, 1);
    plain.set_rate(orn, 100.0);
    plain.run(300);
    CHECK_NEAR(plain.expected_shock(), 0.0, 1e-12);
}

TEST_CASE(expected_us_releases_less_dopamine) {
    Params p;
    p.graded_groups.clear();
    p.learning_rate = 1e-4;
    p.pe_us = true;                                             // without prediction_error
    p.pe_min_trace = 0.5;
    Network net = tiny_network(p);
    const int32_t orn = net.index_of(1), dan = net.index_of(8);
    auto dan_spikes = [&](Simulator& sim) {                     // 1 s of odour + shock
        sim.reset_counts();
        sim.run(1000);
        return sim.spike_counts()[dan];
    };
    Simulator sim(net, p, 1);
    sim.set_rate(orn, 100.0);
    sim.run(300);
    sim.set_rate(dan, 40.0);
    const int32_t first = dan_spikes(sim);                      // shock not yet predicted
    dan_spikes(sim);
    const int32_t later = dan_spikes(sim);                      // the odour now predicts it
    CHECK(sim.expected_shock() > 0.3);
    CHECK(later < 0.7 * first);

    Params off = p;                                             // default off: the rate is the rate
    off.pe_us = false;
    Simulator plain(net, off, 1);
    plain.set_rate(orn, 100.0);
    plain.run(300);
    plain.set_rate(dan, 40.0);
    const int32_t plain_first = dan_spikes(plain);
    dan_spikes(plain);
    CHECK(dan_spikes(plain) > 0.7 * plain_first);
    CHECK_NEAR(plain.expected_shock(), 0.0, 1e-12);             // never computed
}

TEST_CASE(sum_expectation_is_not_diluted_by_a_new_cue) {
    // Two separate odour channels onto one MBON: ORN1 -> PN -> KC3, ORN2 -> PN -> KC4.
    auto neurons = write_file("n2.csv",
        "root_id,group,cell_type,side,x,y,z\n"
        "1,ORN,ORN_DA1,right,0,0,0\n" "2,ORN,ORN_VA1,right,0,1,0\n"
        "11,ALPN,DA1_PN,right,1,0,0\n" "12,ALPN,VA1_PN,right,1,1,0\n"
        "3,KC,KCg,right,2,0,0\n" "4,KC,KCg,right,2,1,0\n"
        "5,MBON,MBON01,right,3,0,0\n" "8,DAN_PPL1,PPL101,right,4,0,0\n");
    auto edges = write_file("e2.csv",
        "pre_root_id,post_root_id,syn_count,nt_type,sign\n"
        "1,11,100,ACH,1\n" "2,12,100,ACH,1\n" "11,3,100,ACH,1\n" "12,4,100,ACH,1\n"
        "3,5,30,ACH,1\n" "4,5,30,ACH,1\n" "8,5,12,DA,0\n");
    auto predicted = [&](const std::string& mode) {     // {A alone, A + X} after training A
        Params p;
        p.graded_groups.clear();
        p.learning_rate = 1e-4;
        p.prediction_error = true;
        p.pe_min_trace = 0.2;
        p.pe_expectation = mode;
        p.pe_ref_active_frac = 0.5;                     // one of the two KCs = one odour
        Network net = Network::load(neurons, edges, p);
        Simulator sim(net, p, 1);
        const int32_t a = net.index_of(1), x = net.index_of(2), dan = net.index_of(8);
        sim.set_rate(a, 100.0);
        sim.set_rate(dan, 40.0);
        sim.run(1500);                                  // A + shock
        sim.set_rate(dan, 0.0);
        sim.run(300);
        const double alone = sim.expected_shock();
        sim.set_rate(x, 100.0);                         // A + X: X never trained
        sim.run(300);
        return std::make_pair(alone, sim.expected_shock());
    };
    const auto [avg_alone, avg_compound] = predicted("average");
    const auto [sum_alone, sum_compound] = predicted("sum");
    CHECK(avg_alone > 0.3 && sum_alone > 0.3);
    CHECK(avg_compound < 0.85 * avg_alone);             // average: diluted by X
    CHECK(sum_compound > 0.95 * sum_alone);             // sum: A still predicts the shock

    Params bad;
    bad.pe_expectation = "median";
    bool threw = false;
    try { Simulator s(tiny_network(bad), bad, 1); } catch (const std::invalid_argument&) { threw = true; }
    CHECK(threw);
}

TEST_CASE(mbon_tonic_drive_sets_spontaneous_rate) {
    Params p;
    p.graded_groups.clear();
    p.plasticity_on = false;
    p.mbon_tonic_mV = 7.125;                    // LIF: T = t_ref + tau ln(I / (I - 7 mV)) ~ 83 ms
    Network net = tiny_network(p);
    const int32_t mbon = net.index_of(6);       // MBON02: no input at rest
    Simulator sim(net, p, 1);
    sim.run(2000);
    sim.reset_counts();
    sim.run(10000);
    const double hz = sim.spike_counts()[mbon] / 10.0;
    CHECK(hz > 10.0 && hz < 14.0);
    sim.set_rate(net.index_of(1), 100.0);       // odour input now raises the rate
    sim.reset_counts();
    sim.run(10000);
    CHECK(sim.spike_counts()[mbon] / 10.0 > hz + 2.0);

    Params off;                                 // default: silent at rest
    off.graded_groups.clear();
    Simulator quiet(net, off, 1);
    quiet.run(5000);
    CHECK(quiet.spike_counts()[mbon] == 0);

    Params typed = p;                           // per cell type overrides the default
    typed.mbon_tonic_mV = 0.0;
    typed.mbon_tonic_by_type = {{"MBON02", 7.125}};
    Simulator per(net, typed, 1);
    per.run(5000);
    CHECK(per.spike_counts()[mbon] > 40);                   // MBON02: ~12 Hz
    CHECK(per.spike_counts()[net.index_of(5)] == 0);        // MBON01: no input, silent
}

TEST_CASE(kc_dan_terminal_contacts_amplify_release_without_spikes) {
    // ORN -> PN -> KC -> MBON, and KC -> DAN (axo-axonic in the fly), DAN -> MBON dopamine
    auto neurons = write_file("n3.csv",
        "root_id,group,cell_type,side,x,y,z\n"
        "1,ORN,ORN_DA1,right,0,0,0\n" "2,ALPN,DA1_PN,right,1,0,0\n" "3,KC,KCg,right,2,0,0\n"
        "5,MBON,MBON01,right,3,0,0\n" "8,DAN_PPL1,PPL101,right,4,0,0\n");
    auto edges = write_file("e3.csv",
        "pre_root_id,post_root_id,syn_count,nt_type,sign\n"
        "1,2,100,ACH,1\n" "2,3,100,ACH,1\n" "3,5,30,ACH,1\n" "3,8,200,ACH,1\n" "8,5,12,DA,0\n");
    auto run = [&](const std::string& mode, double gain, bool odour, bool shock) {
        Params p;
        p.graded_groups.clear();
        p.kc_dan = mode;
        p.kc_dan_gain = gain;
        p.pe_ref_active_frac = 1.0;             // one KC: "typical odour" = it is active
        Network net = Network::load(neurons, edges, p);
        Simulator sim(net, p, 1);
        if (odour) sim.set_rate(net.index_of(1), 100.0);
        if (shock) sim.set_rate(net.index_of(8), 40.0);
        sim.run(1000);
        return std::make_pair(sim.spike_counts()[net.index_of(8)], sim.plastic_weights()[0]);
    };
    CHECK(run("fast", 0.0, true, false).first > 0);              // as listed: odour drives the DAN
    CHECK(run("terminal", 1.0, true, false).first == 0);         // terminal: it doesn't
    const float w_plain = run("terminal", 0.0, true, true).second;
    const float w_gain = run("terminal", 1.0, true, true).second;
    CHECK(w_gain < w_plain);                                     // KC activity amplifies dopamine
    bool threw = false;
    Params bad;
    bad.kc_dan = "slow";
    try { Network::load(neurons, edges, bad); } catch (const std::invalid_argument&) { threw = true; }
    CHECK(threw);
}

TEST_CASE(readouts_subtract_spontaneous_activity) {
    Params p;
    Network net = tiny_network(p);
    const int32_t m = net.index_of(5);                  // MBON01, a shock target
    auto pres = [&](int32_t spikes) {
        Presentation x;
        x.duration_ms = 1000.0;
        x.counts.assign(net.size(), 0);
        x.counts[m] = spikes;
        return x;
    };
    ConditioningResult r;
    r.pre_plus = pres(120); r.post_plus = pres(105);    // 100 Hz spontaneous + 20 evoked -> + 5
    r.pre_minus = pres(120); r.post_minus = pres(120);
    std::vector<uint8_t> target(net.size(), 0);
    target[m] = 1;
    CHECK_NEAR(compartment_change(net, r, target).cs_plus, 105.0 / 120.0 - 1.0, 1e-9);   // raw spikes
    r.spontaneous_hz.assign(net.size(), 0.0);
    r.spontaneous_hz[m] = 100.0;
    CHECK_NEAR(compartment_change(net, r, target).cs_plus, -0.75, 1e-9);                 // evoked: 20 -> 5
    CHECK_NEAR(compartment_change(net, r, target).cs_minus, 0.0, 1e-9);
    r.spontaneous_hz[m] = 130.0;                        // odour below spontaneous: no excitation
    CHECK(!compartment_change(net, r, target).valid);

    Params tonic;
    tonic.mbon_tonic_mV = 7.125;
    Experiment with(net, tonic, ProtocolConfig(), 1), without(net, Params(), ProtocolConfig(), 1);
    with.settle();
    without.settle();
    CHECK(with.spontaneous_hz().size() == static_cast<size_t>(net.size()));
    CHECK(with.spontaneous_hz()[net.index_of(6)] > 5.0);  // MBON02 fires at rest
    CHECK(without.spontaneous_hz().empty());            // silent MBONs: nothing to subtract
}

TEST_CASE(dopamine_suppresses_apl_input_when_enabled) {
    // ORN -> PN -> KC -> MBON and APL; the DAN innervates both (as PPL1 -> APL in FlyWire)
    auto neurons = write_file("n4.csv",
        "root_id,group,cell_type,side,x,y,z\n"
        "1,ORN,ORN_DA1,right,0,0,0\n" "2,ALPN,DA1_PN,right,1,0,0\n" "3,KC,KCg,right,2,0,0\n"
        "5,MBON,MBON01,right,3,0,0\n" "7,APL,APL,right,2,2,0\n" "8,DAN_PPL1,PPL101,right,4,0,0\n");
    auto edges = write_file("e4.csv",
        "pre_root_id,post_root_id,syn_count,nt_type,sign\n"
        "1,2,100,ACH,1\n" "2,3,100,ACH,1\n" "3,5,30,ACH,1\n" "3,7,5,ACH,1\n"
        "8,5,12,DA,0\n" "8,7,12,DA,0\n");
    auto apl_weight = [&](bool on) {
        Params p;
        p.graded_groups.clear();
        p.learning_rate = 1e-4;
        p.apl_plasticity = on;
        Network net = Network::load(neurons, edges, p);
        const int32_t apl = net.index_of(7);
        float w0 = -1, w1 = -1;
        Simulator sim(net, p, 1);
        sim.set_rate(net.index_of(1), 100.0);
        sim.set_rate(net.index_of(8), 40.0);              // odour + shock
        sim.run(1000);
        const auto w = sim.plastic_weights();
        for (size_t s = 0; s < net.plastic.size(); ++s)
            if (net.plastic[s].post == apl) { w0 = net.plastic[s].w0; w1 = w[s]; }
        return std::make_pair(w0, w1);
    };
    const auto [w0_off, w1_off] = apl_weight(false);
    CHECK(w0_off < 0);                                        // off: KC -> APL is not plastic
    const auto [w0, w1] = apl_weight(true);
    CHECK(w0 > 0 && w1 < 0.8f * w0);                         // on: the active KC's APL input weakens
}

TEST_CASE(compound_odours_compete_for_the_receptor) {
    // Competitive binding (Params::mixture = "binding"), baseline 10 Hz, ceiling 200 Hz.
    const RateSet baseline{{1}, {10.0}};
    const RateSet a{{1}, {50.0}}, c{{1}, {30.0}}, inhibitor{{1}, {5.0}}, strong{{1}, {199.0}};
    auto mix = [&](std::vector<const RateSet*> parts) {
        return mix_odours(parts, baseline, "binding", 200.0).hz.at(0);
    };
    CHECK_NEAR(mix({&a}), 50.0, 1e-9);                     // one odour: its own response
    CHECK_NEAR(mix({&inhibitor}), 5.0, 1e-9);
    // occupancies 40/150 and 20/170: 10 + 190 * 0.3843 / 1.3843
    const double ac = mix({&a, &c});
    CHECK_NEAR(ac, 10.0 + 190.0 * (40.0 / 150 + 20.0 / 170) / (1 + 40.0 / 150 + 20.0 / 170), 1e-9);
    CHECK(ac > 50.0 && ac < 70.0);                         // more than either, less than the sum
    CHECK(mix({&strong, &strong}) < 200.0);                 // saturates below the ceiling
    // an inhibiting odour (occupancy 5/5 = 1) takes the site from the agonist
    CHECK_NEAR(mix({&a, &inhibitor}), 10.0 + (190.0 * 40.0 / 150 - 10.0) / (2 + 40.0 / 150), 1e-9);
    CHECK(mix({&a, &inhibitor}) < 50.0);
    bool threw = false;
    try { mix_odours({&a}, baseline, "sum", 200.0); } catch (const std::invalid_argument&) { threw = true; }
    CHECK(threw);
}

TEST_CASE(compound_odours_add_over_baseline) {
    const RateSet baseline{{1, 2}, {10.0, 10.0}};
    const RateSet a{{1}, {50.0}}, c{{1, 3}, {30.0, 20.0}}, quiet{{2}, {0.0}};
    RateSet ac = mix_odours({&a, &c}, baseline);
    CHECK(ac.neurons == std::vector<int32_t>({1, 3}));
    CHECK_NEAR(ac.hz[0], 10.0 + 40.0 + 20.0, 1e-9);            // both changes add
    CHECK_NEAR(ac.hz[1], 20.0, 1e-9);                           // not in the baseline: from 0
    RateSet qq = mix_odours({&quiet, &quiet}, baseline);
    CHECK_NEAR(qq.hz[0], 0.0, 1e-9);                            // 10 - 10 - 10, floored at 0

    Params p;
    Network net = tiny_network(p);
    ProtocolConfig cfg;
    cfg.stim_ms = 100;
    cfg.gap_ms = 50;
    Experiment exp(net, p, cfg, 3);
    const int32_t orn = net.index_of(1);
    const std::map<std::string, RateSet> odours{{"A", {{orn}, {40.0}}}, {"C", {{orn}, {40.0}}}};
    ProtocolStep both;
    both.odour = "A+C";
    const auto made = run_protocol(exp, {both}, odours);
    CHECK(made.size() == 1 && made[0].label == "A+C");
    for (const char* bad : {"A+Z", "A+A", "A+"}) {
        ProtocolStep s;
        s.odour = bad;
        bool threw = false;
        try { run_protocol(exp, {s}, odours); } catch (const std::invalid_argument&) { threw = true; }
        CHECK(threw);
    }
}

TEST_CASE(analysis_helpers) {
    std::vector<int32_t> a{0, 2, 4, 6}, b{0, 1, 2, 3}, c{6, 4, 2, 0};
    std::vector<int32_t> all{0, 1, 2, 3};
    CHECK_NEAR(correlation(a, b, all), 1.0, 1e-9);
    CHECK_NEAR(correlation(a, c, all), -1.0, 1e-9);
    CHECK_NEAR(fraction_active(a, all), 0.75, 1e-9);
    CHECK(shared_active(a, c, all) == 2);
}

int main() { return check::run_all(); }