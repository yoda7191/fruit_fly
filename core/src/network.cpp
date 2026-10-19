#include "fruit_fly/network.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <map>
#include <stdexcept>

#include "fruit_fly/csv.hpp"

namespace fruit_fly {

namespace {

bool starts_with(const std::string& s, const std::string& prefix) {
    return s.compare(0, prefix.size(), prefix) == 0;
}

float parse_float_or_nan(const std::string& s) {
    if (s.empty()) return std::numeric_limits<float>::quiet_NaN();
    try {
        return std::stof(s);
    } catch (...) {
        return std::numeric_limits<float>::quiet_NaN();
    }
}

struct Edge {
    int32_t pre, post, syn;
    float w;
};

}  // namespace

Network Network::load(const std::string& neurons_csv,
                      const std::string& edges_csv,
                      const Params& p) {
    Network net;

    // ------------------------------------------------------------ neurons
    CsvTable nt = read_csv(neurons_csv);
    const int c_id = nt.col("root_id"), c_group = nt.col("group");
    const int c_type = nt.col_or_missing("cell_type"), c_side = nt.col_or_missing("side");
    const int c_x = nt.col_or_missing("x"), c_y = nt.col_or_missing("y"),
              c_z = nt.col_or_missing("z");
    // Optional: transmitter computed by the extractor over ALL of a neuron's
    // output synapses (most MBON outputs lie outside the extracted circuit).
    const int c_neuron_nt = nt.col_or_missing("nt_type");
    std::vector<std::string> declared_nt;

    for (const auto& r : nt.rows) {
        int64_t id = std::stoll(r[c_id]);
        if (net.index_.count(id)) continue;   // ignore duplicate rows
        net.index_[id] = net.size();
        net.root_id.push_back(id);
        net.group.push_back(r[c_group]);
        net.cell_type.push_back(c_type >= 0 ? r[c_type] : "");
        net.side.push_back(c_side >= 0 ? r[c_side] : "");
        declared_nt.push_back(c_neuron_nt >= 0 ? r[c_neuron_nt] : "");
        net.x.push_back(c_x >= 0 ? parse_float_or_nan(r[c_x]) : NAN);
        net.y.push_back(c_y >= 0 ? parse_float_or_nan(r[c_y]) : NAN);
        net.z.push_back(c_z >= 0 ? parse_float_or_nan(r[c_z]) : NAN);
        bool is_graded = std::find(p.graded_groups.begin(), p.graded_groups.end(),
                                   r[c_group]) != p.graded_groups.end();
        net.graded.push_back(is_graded ? 1 : 0);
    }
    const int32_t n = net.size();

    // ------------------------------------------------------------ edges
    CsvTable et = read_csv(edges_csv);
    const int c_pre = et.col("pre_root_id"), c_post = et.col("post_root_id");
    const int c_syn = et.col("syn_count"), c_sign = et.col("sign");
    const int c_nt = et.col_or_missing("nt_type");

    std::vector<Edge> edges;
    std::vector<std::map<std::string, int64_t>> nt_votes(n);         // synapses per transmitter
    std::map<std::pair<int32_t, int32_t>, int32_t> dan_to_mbon;   // (dan, mbon) -> synapses

    if (p.kc_dan != "fast" && p.kc_dan != "terminal")
        throw std::invalid_argument("kc_dan must be 'fast' or 'terminal', got '" + p.kc_dan + "'");
    const bool kc_terminal = p.kc_dan == "terminal";
    // MBONs, plus APL with apl_plasticity: their KC inputs learn, gated by dopamine
    auto plastic_target = [&](const std::string& g) {
        return g == p.plastic_post_group || (p.apl_plasticity && g == p.apl_group);
    };
    net.kc_to_dan.assign(n, {});
    for (const auto& r : et.rows) {
        int32_t a = net.index_of(std::stoll(r[c_pre]));
        int32_t b = net.index_of(std::stoll(r[c_post]));
        if (a < 0 || b < 0) continue;                  // endpoint outside the circuit
        int32_t syn = std::stoi(r[c_syn]);
        int sign = std::stoi(r[c_sign]);
        if (c_nt >= 0 && !r[c_nt].empty()) nt_votes[a][r[c_nt]] += syn;
        const std::string& ga = net.group[a];
        const std::string& gb = net.group[b];

        // Dopamine is modulatory: remember DAN->MBON synapse counts for the
        // plasticity rule, but don't make a fast connection out of them.
        if (starts_with(ga, p.dan_prefix) && plastic_target(gb))
            dan_to_mbon[{a, b}] += syn;
        // KC -> DAN as terminal contacts: a gain on release, not a fast synapse
        if (kc_terminal && ga == p.plastic_pre_group && starts_with(gb, p.dan_prefix)) {
            net.kc_to_dan[b].push_back({a, syn});
            continue;
        }

        if (sign == 0) continue;
        bool excluded = false;
        for (const auto& pr : p.excluded_pairs)
            if (pr.first == ga && pr.second == gb) excluded = true;
        if (excluded) continue;

        edges.push_back({a, b, syn, static_cast<float>(sign * syn * p.w_syn_mV)});
    }

    // ------------------------------------------------------------ transmitter per neuron
    // Declared (whole-brain) transmitter if the neurons file has one; otherwise
    // a vote over the neuron's synapses inside this circuit.
    net.transmitter.assign(n, "");
    for (int32_t i = 0; i < n; ++i) {
        if (!declared_nt[i].empty()) {
            net.transmitter[i] = declared_nt[i];
            continue;
        }
        int64_t best = 0;
        for (const auto& [nt, votes] : nt_votes[i])      // std::map: ties go to the first name
            if (votes > best) { best = votes; net.transmitter[i] = nt; }
    }

    // ------------------------------------------------------------ CSR (counting sort by pre)
    net.row_ptr.assign(n + 1, 0);
    for (const auto& e : edges) net.row_ptr[e.pre + 1]++;
    for (int32_t i = 0; i < n; ++i) net.row_ptr[i + 1] += net.row_ptr[i];

    net.col.resize(edges.size());
    net.weight.resize(edges.size());
    net.syn_count.resize(edges.size());
    std::vector<int32_t> fill(net.row_ptr.begin(), net.row_ptr.end() - 1);
    for (const auto& e : edges) {
        int32_t k = fill[e.pre]++;
        net.col[k] = e.post;
        net.weight[k] = e.w;
        net.syn_count[k] = e.syn;
    }

    // ------------------------------------------------------------ plastic synapses
    net.plastic_by_post.assign(n, {});
    for (int32_t i = 0; i < n; ++i) {
        if (net.group[i] != p.plastic_pre_group) continue;
        for (int32_t k = net.row_ptr[i]; k < net.row_ptr[i + 1]; ++k) {
            int32_t j = net.col[k];
            if (!plastic_target(net.group[j]) || net.weight[k] <= 0) continue;
            net.plastic_by_post[j].push_back(static_cast<int32_t>(net.plastic.size()));
            net.plastic.push_back({k, i, j, net.weight[k]});
        }
    }

    // ------------------------------------------------------------ dopamine coupling
    // Each MBON's dopamine inputs are normalised to sum to 1, so one spike
    // from a DAN that supplies all of an MBON's dopamine synapses adds 1.0.
    std::vector<int32_t> total_per_mbon(n, 0);
    for (const auto& kv : dan_to_mbon) total_per_mbon[kv.first.second] += kv.second;

    net.da_row_ptr.assign(n + 1, 0);
    for (const auto& kv : dan_to_mbon) net.da_row_ptr[kv.first.first + 1]++;
    for (int32_t i = 0; i < n; ++i) net.da_row_ptr[i + 1] += net.da_row_ptr[i];
    net.da_col.resize(dan_to_mbon.size());
    net.da_coef.resize(dan_to_mbon.size());
    std::vector<int32_t> da_fill(net.da_row_ptr.begin(), net.da_row_ptr.end() - 1);
    for (const auto& kv : dan_to_mbon) {
        int32_t d = kv.first.first, m = kv.first.second;
        int32_t k = da_fill[d]++;
        net.da_col[k] = m;
        net.da_coef[k] = static_cast<float>(kv.second) / total_per_mbon[m];
    }

    return net;
}

int32_t Network::index_of(int64_t id) const {
    auto it = index_.find(id);
    return it == index_.end() ? -1 : it->second;
}

std::vector<int32_t> Network::indices_in_group(const std::string& g) const {
    std::vector<int32_t> out;
    for (int32_t i = 0; i < size(); ++i)
        if (group[i] == g) out.push_back(i);
    return out;
}

std::vector<int32_t> Network::indices_with_group_prefix(const std::string& prefix) const {
    std::vector<int32_t> out;
    for (int32_t i = 0; i < size(); ++i)
        if (starts_with(group[i], prefix)) out.push_back(i);
    return out;
}

}  // namespace fruit_fly