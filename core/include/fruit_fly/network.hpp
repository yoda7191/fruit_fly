// network.hpp — the connectome as fixed, read-only data structures.
//
// Neurons get dense indices 0..N-1 (FlyWire root IDs are 18-digit numbers,
// useless as array indices). Synapses are stored in CSR form grouped by
// PRESYNAPTIC neuron, because the simulator's question is always
// "neuron i just spiked: who receives it, and how strongly?"
#pragma once

#include <cstdint>
#include <string>
#include <unordered_map>
#include <vector>

#include "fruit_fly/params.hpp"

namespace fruit_fly {

// One KC -> MBON synapse whose weight can change.
struct PlasticSynapse {
    int32_t syn;    // index into Network::weight (the CSR entry)
    int32_t pre;    // KC index
    int32_t post;   // MBON index
    float   w0;     // initial weight, for resets and bounds
};

class Network {
public:
    // Build from the CSVs written by scripts/extract_mb_circuit.py.
    static Network load(const std::string& neurons_csv,
                        const std::string& edges_csv,
                        const Params& p);

    int32_t size() const { return static_cast<int32_t>(root_id.size()); }

    // ---- per-neuron attributes (index = neuron id)
    std::vector<int64_t>     root_id;
    std::vector<std::string> group;      // ORN, ALPN, KC, APL, DPM, MBON, DAN_PAM, DAN_PPL1
    std::vector<std::string> cell_type;  // e.g. ORN_DA1, MBON01, PPL101
    std::vector<std::string> side;
    std::vector<float>       x, y, z;    // position (NaN if unknown)
    std::vector<uint8_t>     graded;     // 1 = non-spiking graded neuron
    // Predicted transmitter ("ACH", "GABA", "GLUT", "DA", ...): the neurons
    // file's nt_type column if present (computed over the whole brain by the
    // extractor), else the nt_type carrying most of the neuron's output
    // synapses within this circuit; "" if unknown.
    std::vector<std::string> transmitter;

    // ---- fast synapses, CSR by presynaptic neuron
    // targets of neuron i are col[row_ptr[i] .. row_ptr[i+1])
    std::vector<int32_t> row_ptr;
    std::vector<int32_t> col;
    std::vector<float>   weight;         // mV, signed (inhibitory < 0)
    std::vector<int32_t> syn_count;

    // ---- plasticity
    std::vector<PlasticSynapse> plastic;
    // plastic_by_post[m] = indices into `plastic` of synapses onto neuron m
    std::vector<std::vector<int32_t>> plastic_by_post;

    // ---- dopamine coupling, CSR by DAN: a spike of DAN d adds
    // da_coef[k] to the dopamine level of MBON da_col[k]
    std::vector<int32_t> da_row_ptr;
    std::vector<int32_t> da_col;
    std::vector<float>   da_coef;

    // ---- Params::kc_dan == "terminal": KC inputs per DAN, (kc, synapses);
    // these are not fast synapses then
    std::vector<std::vector<std::pair<int32_t, int32_t>>> kc_to_dan;

    // ---- lookups
    int32_t index_of(int64_t root_id) const;   // -1 if unknown
    std::vector<int32_t> indices_in_group(const std::string& g) const;
    std::vector<int32_t> indices_with_group_prefix(const std::string& prefix) const;

private:
    std::unordered_map<int64_t, int32_t> index_;
};

}  // namespace fruit_fly