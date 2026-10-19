// bindings.cpp — exposes the whole C++ library to Python as `fruit_fly_core`.
//
//   import fruit_fly_core as fc
//   p   = fc.Params()
//   net = fc.Network.load("data/synthetic/mb_neurons.csv", "data/synthetic/mb_edges.csv", p)
//   lib = fc.OdourLibrary.load("data/raw/door")
//   stim = fc.OdourStimulus(lib, net)
//   exp = fc.Experiment(net, p, fc.ProtocolConfig(), seed=1)
//   exp.set_baseline(stim.baseline()); exp.settle()
//   r = fc.run_differential_conditioning(exp, "3-octanol", stim.rates("3-octanol"),
//                                        "4-methylcyclohexanol",
//                                        stim.rates("4-methylcyclohexanol"), 3, fc.US.Shock)
//
// Lifetimes: objects that keep a reference to another (Simulator -> Network,
// Experiment -> Network, OdourStimulus -> OdourLibrary + Network) use
// py::keep_alive so Python can't free the referenced object first.
#include <pybind11/functional.h>
#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "fruit_fly/analysis.hpp"
#include "fruit_fly/experiment.hpp"
#include "fruit_fly/network.hpp"
#include "fruit_fly/odours.hpp"
#include "fruit_fly/params.hpp"
#include "fruit_fly/simulator.hpp"

namespace py = pybind11;
using namespace fruit_fly;

namespace {

// Copy a std::vector into a new NumPy array.
template <typename T>
py::array_t<T> to_numpy(const std::vector<T>& v) {
    py::array_t<T> out(static_cast<py::ssize_t>(v.size()));
    std::copy(v.begin(), v.end(), out.mutable_data());
    return out;
}

py::array_t<bool> mask_to_numpy(const std::vector<uint8_t>& v) {
    py::array_t<bool> out(static_cast<py::ssize_t>(v.size()));
    auto* p = out.mutable_data();
    for (size_t i = 0; i < v.size(); ++i) p[i] = v[i] != 0;
    return out;
}

std::vector<uint8_t> mask_from(const py::array_t<bool, py::array::forcecast>& a) {
    auto r = a.unchecked<1>();
    std::vector<uint8_t> v(static_cast<size_t>(r.shape(0)));
    for (py::ssize_t i = 0; i < r.shape(0); ++i) v[i] = r(i) ? 1 : 0;
    return v;
}

}  // namespace

PYBIND11_MODULE(fruit_fly_core, m) {
    m.doc() = "Connectome-constrained mushroom body simulator (C++ core)";

    // ================================================================ Params
    py::class_<Params>(m, "Params")
        .def(py::init<>())
        .def_readwrite("dt_ms", &Params::dt_ms)
        .def_readwrite("v_rest_mV", &Params::v_rest_mV)
        .def_readwrite("v_reset_mV", &Params::v_reset_mV)
        .def_readwrite("v_thresh_mV", &Params::v_thresh_mV)
        .def_readwrite("tau_m_ms", &Params::tau_m_ms)
        .def_readwrite("tau_syn_ms", &Params::tau_syn_ms)
        .def_readwrite("t_ref_ms", &Params::t_ref_ms)
        .def_readwrite("delay_ms", &Params::delay_ms)
        .def_readwrite("w_syn_mV", &Params::w_syn_mV)
        .def_readwrite("w_ext_mV", &Params::w_ext_mV)
        .def_readwrite("graded_groups", &Params::graded_groups)
        .def_readwrite("graded_gain", &Params::graded_gain)
        .def_readwrite("graded_v_max_mV", &Params::graded_v_max_mV)
        .def_readwrite("excluded_pairs", &Params::excluded_pairs)
        .def_readwrite("plasticity_on", &Params::plasticity_on)
        .def_readwrite("plastic_pre_group", &Params::plastic_pre_group)
        .def_readwrite("plastic_post_group", &Params::plastic_post_group)
        .def_readwrite("dan_prefix", &Params::dan_prefix)
        .def_readwrite("tau_elig_ms", &Params::tau_elig_ms)
        .def_readwrite("tau_da_ms", &Params::tau_da_ms)
        .def_readwrite("learning_rate", &Params::learning_rate)
        .def_readwrite("w_min_frac", &Params::w_min_frac)
        .def_readwrite("plasticity_interval_ms", &Params::plasticity_interval_ms)
        .def_readwrite("plasticity_rule", &Params::plasticity_rule)
        .def_readwrite("apl_plasticity", &Params::apl_plasticity)
        .def_readwrite("graded_input_gain", &Params::graded_input_gain)
        .def_readwrite("apl_group", &Params::apl_group)
        .def_readwrite("timing_depression", &Params::timing_depression)
        .def_readwrite("timing_potentiation", &Params::timing_potentiation)
        .def_readwrite("w_max_frac", &Params::w_max_frac)
        .def_readwrite("timing_fast_tau_ms", &Params::timing_fast_tau_ms)
        .def_readwrite("prediction_error", &Params::prediction_error)
        .def_readwrite("pe_us", &Params::pe_us)
        .def_readwrite("pe_expectation", &Params::pe_expectation)
        .def_readwrite("pe_omission", &Params::pe_omission)
        .def_readwrite("pe_ref_active_frac", &Params::pe_ref_active_frac)
        .def_readwrite("mbon_tonic_mV", &Params::mbon_tonic_mV)
        .def_readwrite("mbon_tonic_by_type", &Params::mbon_tonic_by_type)
        .def_readwrite("kc_dan", &Params::kc_dan)
        .def_readwrite("kc_dan_gain", &Params::kc_dan_gain)
        .def_readwrite("mixture", &Params::mixture)
        .def_readwrite("orn_max_rate_hz", &Params::orn_max_rate_hz)
        .def_readwrite("pe_gain_hz", &Params::pe_gain_hz)
        .def_readwrite("pe_min_trace", &Params::pe_min_trace)
        .def_readwrite("pe_interval_ms", &Params::pe_interval_ms)
        .def_readwrite("pe_shock_group", &Params::pe_shock_group)
        .def_readwrite("pe_reward_group", &Params::pe_reward_group);

    // ================================================================ Network
    py::class_<Network>(m, "Network")
        .def_static("load", &Network::load, py::arg("neurons_csv"), py::arg("edges_csv"),
                    py::arg("params"))
        .def_property_readonly("size", &Network::size)
        .def("__len__", &Network::size)
        .def("index_of", &Network::index_of, py::arg("root_id"))
        .def("indices_in_group", &Network::indices_in_group, py::arg("group"))
        .def("indices_with_group_prefix", &Network::indices_with_group_prefix, py::arg("prefix"))
        .def_property_readonly("root_id", [](const Network& n) { return to_numpy(n.root_id); })
        .def_readonly("group", &Network::group)
        .def_readonly("cell_type", &Network::cell_type)
        .def_readonly("side", &Network::side)
        .def_readonly("transmitter", &Network::transmitter)
        .def_property_readonly("graded", [](const Network& n) { return mask_to_numpy(n.graded); })
        .def_property_readonly("positions", [](const Network& n) {
            py::array_t<float> out({static_cast<py::ssize_t>(n.size()), py::ssize_t{3}});
            auto r = out.mutable_unchecked<2>();
            for (int32_t i = 0; i < n.size(); ++i) {
                r(i, 0) = n.x[i]; r(i, 1) = n.y[i]; r(i, 2) = n.z[i];
            }
            return out;
        })
        .def_property_readonly("n_synapses", [](const Network& n) { return n.col.size(); })
        .def_property_readonly("row_ptr", [](const Network& n) { return to_numpy(n.row_ptr); })
        .def_property_readonly("col", [](const Network& n) { return to_numpy(n.col); })
        .def_property_readonly("weight", [](const Network& n) { return to_numpy(n.weight); })
        .def_property_readonly("syn_count", [](const Network& n) { return to_numpy(n.syn_count); })
        .def_property_readonly("plastic_pre", [](const Network& n) {
            std::vector<int32_t> v;
            for (const auto& s : n.plastic) v.push_back(s.pre);
            return to_numpy(v);
        })
        .def_property_readonly("plastic_post", [](const Network& n) {
            std::vector<int32_t> v;
            for (const auto& s : n.plastic) v.push_back(s.post);
            return to_numpy(v);
        })
        .def_property_readonly("plastic_w0", [](const Network& n) {
            std::vector<float> v;
            for (const auto& s : n.plastic) v.push_back(s.w0);
            return to_numpy(v);
        });

    // ================================================================ RateSet
    py::class_<RateSet>(m, "RateSet")
        .def(py::init<>())
        .def(py::init([](std::vector<int32_t> neurons, std::vector<double> hz) {
                 if (neurons.size() != hz.size())
                     throw std::invalid_argument("neurons and hz differ in length");
                 return RateSet{std::move(neurons), std::move(hz)};
             }),
             py::arg("neurons"), py::arg("hz"))
        .def_property_readonly("neurons", [](const RateSet& r) { return to_numpy(r.neurons); })
        .def_property_readonly("hz", [](const RateSet& r) { return to_numpy(r.hz); })
        .def("__len__", [](const RateSet& r) { return r.neurons.size(); })
        // allows:  idx, hz = rate_set
        .def("__iter__", [](const RateSet& r) {
            return py::iter(py::make_tuple(to_numpy(r.neurons), to_numpy(r.hz)));
        });

    // ================================================================ Simulator
    py::class_<Simulator>(m, "Simulator")
        .def(py::init<const Network&, const Params&, uint64_t>(), py::arg("network"),
             py::arg("params"), py::arg("seed") = 42, py::keep_alive<1, 2>())
        .def("set_rate", &Simulator::set_rate, py::arg("neuron"), py::arg("hz"))
        .def("set_rates", py::overload_cast<const std::vector<int32_t>&,
                                            const std::vector<double>&>(&Simulator::set_rates),
             py::arg("neurons"), py::arg("hz"))
        .def("set_rates", py::overload_cast<const std::vector<int32_t>&, double>(
                              &Simulator::set_rates),
             py::arg("neurons"), py::arg("hz"))
        .def("apply", &Simulator::apply, py::arg("rates"))
        .def("clear_rates", &Simulator::clear_rates)
        .def("run", &Simulator::run, py::arg("ms"),
             py::call_guard<py::gil_scoped_release>())   // lets a web server stay responsive
        .def_property_readonly("time_ms", &Simulator::time_ms)
        .def("spikes", [](const Simulator& s) {
            const auto& sp = s.spikes();
            py::array_t<int32_t> idx(static_cast<py::ssize_t>(sp.size()));
            py::array_t<float> t(static_cast<py::ssize_t>(sp.size()));
            auto pi = idx.mutable_data();
            auto pt = t.mutable_data();
            for (size_t k = 0; k < sp.size(); ++k) { pi[k] = sp[k].neuron; pt[k] = sp[k].t_ms; }
            return py::make_tuple(idx, t);
        })
        .def("clear_spikes", &Simulator::clear_spikes)
        .def("spike_counts", [](const Simulator& s) { return to_numpy(s.spike_counts()); })
        .def("reset_counts", &Simulator::reset_counts)
        .def("voltages", [](const Simulator& s) { return to_numpy(s.voltages()); })
        .def("plastic_weights", [](const Simulator& s) { return to_numpy(s.plastic_weights()); })
        .def("reset_weights", &Simulator::reset_weights)
        .def("reset_state", &Simulator::reset_state)
        .def("silence", &Simulator::silence, py::arg("neurons"))
        .def("clear_silenced", &Simulator::clear_silenced)
        .def_property_readonly("silenced", [](const Simulator& s) { return mask_to_numpy(s.silenced()); })
        .def_property_readonly("expected_shock", &Simulator::expected_shock)
        .def_property_readonly("expected_reward", &Simulator::expected_reward);

    // ================================================================ odours
    m.def("glomerulus_aliases", &glomerulus_aliases);

    py::class_<OdourLibrary>(m, "OdourLibrary")
        .def_static("load", &OdourLibrary::load, py::arg("door_dir"))
        .def_property_readonly("glomeruli", &OdourLibrary::glomeruli)
        .def("names", &OdourLibrary::names)
        .def_property_readonly("spontaneous",
                               [](const OdourLibrary& l) { return to_numpy(l.spontaneous()); })
        .def("odour_index", &OdourLibrary::odour_index, py::arg("name"))
        .def("search", &OdourLibrary::search, py::arg("text"))
        .def("raw", [](const OdourLibrary& l, const std::string& o) { return to_numpy(l.raw(o)); },
             py::arg("odour"))
        .def("profile",
             [](const OdourLibrary& l, const std::string& o) { return to_numpy(l.profile(o)); },
             py::arg("odour"))
        .def("coverage", &OdourLibrary::coverage, py::arg("odour"))
        .def("similarity", &OdourLibrary::similarity, py::arg("a"), py::arg("b"));

    py::class_<OdourStimulus>(m, "OdourStimulus")
        .def(py::init<const OdourLibrary&, const Network&, double>(), py::arg("library"),
             py::arg("network"), py::arg("max_rate_hz") = OdourStimulus::kDefaultMaxRateHz,
             py::keep_alive<1, 2>(), py::keep_alive<1, 3>())
        .def("baseline", &OdourStimulus::baseline)
        .def("rates", &OdourStimulus::rates, py::arg("odour"), py::arg("concentration") = 1.0)
        .def("report", &OdourStimulus::report)
        .def_property_readonly("matched", &OdourStimulus::matched)
        .def_property_readonly("unmatched_door", &OdourStimulus::unmatched_door)
        .def_property_readonly("unmatched_network", &OdourStimulus::unmatched_network);

    m.def("random_odour", &random_odour, py::arg("network"), py::arg("name"),
          py::arg("fraction") = 0.3, py::arg("hz") = 80.0);

    // ================================================================ experiment
    py::enum_<US>(m, "US")
        .value("None_", US::None)          // `None` is reserved in Python
        .value("Shock", US::Shock)
        .value("Reward", US::Reward);
    m.def("us_from_string", &us_from_string, py::arg("name"));

    py::class_<ProtocolConfig>(m, "ProtocolConfig")
        .def(py::init<>())
        .def_readwrite("stim_ms", &ProtocolConfig::stim_ms)
        .def_readwrite("gap_ms", &ProtocolConfig::gap_ms)
        .def_readwrite("settle_ms", &ProtocolConfig::settle_ms)
        .def_readwrite("spontaneous_ms", &ProtocolConfig::spontaneous_ms)
        .def_readwrite("us_hz", &ProtocolConfig::us_hz)
        .def_readwrite("shock_group", &ProtocolConfig::shock_group)
        .def_readwrite("reward_group", &ProtocolConfig::reward_group);

    py::class_<Presentation>(m, "Presentation")
        .def_readonly("label", &Presentation::label)
        .def_readonly("us", &Presentation::us)
        .def_readonly("phase", &Presentation::phase)
        .def_readonly("t_start_ms", &Presentation::t_start_ms)
        .def_readonly("duration_ms", &Presentation::duration_ms)
        .def_readonly("us_start_ms", &Presentation::us_start_ms)
        .def_readonly("us_end_ms", &Presentation::us_end_ms)
        .def_property_readonly("counts", [](const Presentation& p) { return to_numpy(p.counts); });

    py::class_<ProtocolStep>(m, "ProtocolStep")
        .def(py::init<>())
        .def_readwrite("phase", &ProtocolStep::phase)
        .def_readwrite("odour", &ProtocolStep::odour)
        .def_readwrite("us", &ProtocolStep::us)
        .def_readwrite("odour_ms", &ProtocolStep::odour_ms)
        .def_readwrite("us_onset_ms", &ProtocolStep::us_onset_ms)
        .def_readwrite("us_ms", &ProtocolStep::us_ms)
        .def_readwrite("gap_ms", &ProtocolStep::gap_ms)
        .def_readwrite("repeat", &ProtocolStep::repeat);

    py::class_<Experiment>(m, "Experiment")
        .def(py::init<const Network&, const Params&, const ProtocolConfig&, uint64_t>(),
             py::arg("network"), py::arg("params"), py::arg("config") = ProtocolConfig(),
             py::arg("seed") = 42, py::keep_alive<1, 2>())
        .def("set_baseline", &Experiment::set_baseline, py::arg("baseline"))
        .def("settle", &Experiment::settle, py::call_guard<py::gil_scoped_release>())
        .def("present_step", &Experiment::present_step, py::arg("step"), py::arg("odour"),
             py::return_value_policy::copy, py::call_guard<py::gil_scoped_release>())
        .def("present", &Experiment::present, py::arg("label"), py::arg("odour"),
             py::arg("us") = US::None, py::return_value_policy::copy,
             py::call_guard<py::gil_scoped_release>())
        .def_property_readonly("simulator",
                               py::overload_cast<>(&Experiment::simulator),
                               py::return_value_policy::reference_internal)
        .def_property_readonly("config", &Experiment::config)
        .def_property_readonly("history", &Experiment::history)
        .def_property_readonly("spontaneous_hz", &Experiment::spontaneous_hz)
        .def_property_readonly("baseline", &Experiment::baseline)
        .def("us_neurons", &Experiment::us_neurons, py::arg("us"));

    py::class_<ConditioningResult>(m, "ConditioningResult")
        .def_readonly("cs_plus", &ConditioningResult::cs_plus)
        .def_readonly("cs_minus", &ConditioningResult::cs_minus)
        .def_readonly("us", &ConditioningResult::us)
        .def_readonly("trials", &ConditioningResult::trials)
        .def_readonly("pre_plus", &ConditioningResult::pre_plus)
        .def_readonly("pre_minus", &ConditioningResult::pre_minus)
        .def_readonly("post_plus", &ConditioningResult::post_plus)
        .def_readonly("post_minus", &ConditioningResult::post_minus)
        .def_property_readonly("weights_before",
                               [](const ConditioningResult& r) { return to_numpy(r.weights_before); })
        .def_readonly("spontaneous_hz", &ConditioningResult::spontaneous_hz)
        .def_property_readonly("weights_after",
                               [](const ConditioningResult& r) { return to_numpy(r.weights_after); });

    // `progress` is an optional Python callable(done, total). The simulation
    // runs without the GIL; pybind11 re-acquires it for each callback.
    m.def("run_differential_conditioning", &run_differential_conditioning,
          py::arg("experiment"), py::arg("cs_plus_name"), py::arg("cs_plus"),
          py::arg("cs_minus_name"), py::arg("cs_minus"), py::arg("trials") = 3,
          py::arg("us") = US::Shock, py::arg("progress") = nullptr,
          py::call_guard<py::gil_scoped_release>());

    m.def("mix_odours", &mix_odours, py::arg("odours"), py::arg("baseline"),
          py::arg("mode") = "linear", py::arg("max_rate_hz") = 200.0);
    m.def("run_protocol", &run_protocol, py::arg("experiment"), py::arg("steps"),
          py::arg("odours"), py::arg("progress") = nullptr,
          py::call_guard<py::gil_scoped_release>());
    m.def("conditioning_readout",
          [](const std::vector<Presentation>& made, const std::string& plus, const std::string& minus,
             const std::string& before, const std::string& after, US us, int trials,
             const std::vector<float>& wb, const std::vector<float>& wa,
             const std::vector<double>& spontaneous_hz) {
              return conditioning_readout(made, plus, minus, before, after, us, trials, wb, wa,
                                          spontaneous_hz);
          },
          py::arg("presentations"), py::arg("plus"), py::arg("minus"), py::arg("before_phase"),
          py::arg("after_phase"), py::arg("us"), py::arg("trials"),
          py::arg("weights_before"), py::arg("weights_after"),
          py::arg("spontaneous_hz") = std::vector<double>{});

    // ================================================================ analysis
    m.def("correlation", &correlation, py::arg("a"), py::arg("b"), py::arg("idx"));
    m.def("fraction_active", &fraction_active, py::arg("counts"), py::arg("idx"));
    m.def("shared_active", &shared_active, py::arg("a"), py::arg("b"), py::arg("idx"));
    m.def("dopamine_targets",
          [](const Network& n, const std::vector<int32_t>& dans) {
              return mask_to_numpy(dopamine_targets(n, dans));
          },
          py::arg("network"), py::arg("dans"));

    py::class_<Separation>(m, "Separation")
        .def_readonly("pn_correlation", &Separation::pn_correlation)
        .def_readonly("kc_correlation", &Separation::kc_correlation)
        .def_readonly("kc_active_plus", &Separation::kc_active_plus)
        .def_readonly("kc_active_minus", &Separation::kc_active_minus)
        .def_readonly("kc_shared", &Separation::kc_shared);
    m.def("pattern_separation", &pattern_separation, py::arg("network"), py::arg("a"),
          py::arg("b"));

    py::class_<MbonTypeSummary>(m, "MbonTypeSummary")
        .def_readonly("cell_type", &MbonTypeSummary::cell_type)
        .def_readonly("n", &MbonTypeSummary::n)
        .def_readonly("us_target", &MbonTypeSummary::us_target)
        .def_readonly("pre_plus", &MbonTypeSummary::pre_plus)
        .def_readonly("post_plus", &MbonTypeSummary::post_plus)
        .def_readonly("pre_minus", &MbonTypeSummary::pre_minus)
        .def_readonly("post_minus", &MbonTypeSummary::post_minus);
    m.def("summarize_mbons",
          [](const Network& n, const ConditioningResult& r,
             const py::array_t<bool, py::array::forcecast>& target) {
              return summarize_mbons(n, r, mask_from(target));
          },
          py::arg("network"), py::arg("result"), py::arg("us_target"));

    py::class_<CompartmentChange>(m, "CompartmentChange")
        .def_readonly("valid", &CompartmentChange::valid)
        .def_readonly("cs_plus", &CompartmentChange::cs_plus)
        .def_readonly("cs_minus", &CompartmentChange::cs_minus);
    m.def("compartment_change",
          [](const Network& n, const ConditioningResult& r,
             const py::array_t<bool, py::array::forcecast>& target) {
              return compartment_change(n, r, mask_from(target));
          },
          py::arg("network"), py::arg("result"), py::arg("us_target"));

    m.def("mean_weight_ratio", &mean_weight_ratio, py::arg("network"), py::arg("weights"));

    // ================================================================ behaviour
    m.def("valence_of_transmitter", &valence_of_transmitter, py::arg("transmitter"));
    m.def("mbon_valences",
          [](const Network& n) { return to_numpy(mbon_valences(n)); }, py::arg("network"));
    m.def("approach_drive",
          [](const std::vector<int32_t>& counts, const std::vector<int8_t>& valence, double scale) {
              return approach_drive(counts, valence, scale);
          },
          py::arg("counts"), py::arg("valence"), py::arg("scale") = NAN);

    py::class_<TMazeChoice>(m, "TMazeChoice")
        .def_readonly("drive_plus", &TMazeChoice::drive_plus)
        .def_readonly("drive_minus", &TMazeChoice::drive_minus)
        .def_readonly("p_plus", &TMazeChoice::p_plus)
        .def_readonly("preference", &TMazeChoice::preference)
        .def_readonly("flies", &TMazeChoice::flies)
        .def_readonly("chose_plus", &TMazeChoice::chose_plus)
        .def_readonly("sampled_preference", &TMazeChoice::sampled_preference);

    py::class_<BehaviorConfig>(m, "BehaviorConfig")
        .def(py::init<>())
        .def_readwrite("sharpness", &BehaviorConfig::sharpness)
        .def_readwrite("flies", &BehaviorConfig::flies)
        .def_readwrite("seed", &BehaviorConfig::seed);

    py::class_<BehaviorResult>(m, "BehaviorResult")
        .def_readonly("valid", &BehaviorResult::valid)
        .def_readonly("valenced_mbons", &BehaviorResult::valenced_mbons)
        .def_readonly("naive", &BehaviorResult::naive)
        .def_readonly("trained", &BehaviorResult::trained)
        .def_readonly("learned_drive", &BehaviorResult::learned_drive)
        .def_readonly("performance_index", &BehaviorResult::performance_index)
        .def_readonly("flies", &BehaviorResult::flies)
        .def_readonly("sampled_performance_index", &BehaviorResult::sampled_performance_index);

    m.def("tmaze_test", &tmaze_test, py::arg("network"), py::arg("result"),
          py::arg("config") = BehaviorConfig());
}