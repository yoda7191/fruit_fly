// real odours: DoOR 2.0 receptor responses -> ORN firing rates.
//   odour name ("3-octanol")
//     -> DoOR response of each receptor (0..1, globally normalised)
//     -> glomerulus of that receptor      (Or22a -> DM2)
//     -> FlyWire ORNs of that glomerulus   (cell_type "ORN_DM2")
//     -> Poisson firing rate for each ORN
//
// Caveats: ~86% of DoOR's receptor x odour pairs were never measured; those
// are set to the receptor's spontaneous rate ("no change"). DoOR has no real
// concentration axis; `concentration` is a crude linear scale.
//
// Data: Münch & Galizia 2016, Sci Rep 6:21841 (CC BY-SA 4.0).
#pragma once

#include <cstdint>
#include <map>
#include <string>
#include <vector>

#include "fruit_fly/network.hpp"
#include "fruit_fly/simulator.hpp"

namespace fruit_fly {

// DoOR glomerulus name -> FlyWire glomerulus name, for known renamings.
const std::map<std::string, std::string>& glomerulus_aliases();

class OdourLibrary {
public:
    // Reads door_response_matrix.csv, door_mappings.csv and odor.csv (DoOR's own file name).
    static OdourLibrary load(const std::string& door_dir);

    const std::vector<std::string>& glomeruli() const { return glomeruli_; }
    const std::vector<std::string>& names() const { return names_; }
    const std::vector<double>& spontaneous() const { return spontaneous_; }

    // Row of an odour by name (case-insensitive); throws std::out_of_range.
    int32_t odour_index(const std::string& name) const;
    std::vector<std::string> search(const std::string& text) const;

    // Raw responses per glomerulus; NaN = not measured.
    const std::vector<double>& raw(const std::string& odour) const;
    // Responses with NaN replaced by the spontaneous value.
    std::vector<double> profile(const std::string& odour) const;
    // Fraction of glomeruli with a measured response.
    double coverage(const std::string& odour) const;
    // Correlation of (response - spontaneous) over glomeruli measured for both.
    double similarity(const std::string& a, const std::string& b) const;

private:
    std::vector<std::string> glomeruli_;
    std::vector<double> spontaneous_;
    std::vector<std::string> names_;
    std::vector<std::vector<double>> responses_;   // [odour][glomerulus]
};

class OdourStimulus {
public:
    static constexpr double kDefaultMaxRateHz = 200.0;   // DoOR 1.0 -> this rate

    OdourStimulus(const OdourLibrary& lib, const Network& net,
                 double max_rate_hz = kDefaultMaxRateHz);

    RateSet baseline() const;                                        // spontaneous only
    RateSet rates(const std::string& odour, double concentration = 1.0) const;
    std::string report() const;

    const std::vector<std::string>& matched() const { return matched_; }
    const std::vector<std::string>& unmatched_door() const { return unmatched_door_; }
    const std::vector<std::string>& unmatched_network() const { return unmatched_network_; }

private:
    RateSet from_values(const std::vector<double>& per_glom) const;

    const OdourLibrary& lib_;
    double max_rate_hz_;
    std::vector<int32_t> orn_;          // matched ORN neurons
    std::vector<int32_t> orn_glom_;     // their glomerulus column in the library
    std::vector<int32_t> other_;        // ORNs whose glomerulus has no DoOR data
    std::vector<std::string> matched_, unmatched_door_, unmatched_network_;
};

// A synthetic odour: a random but reproducible set of glomeruli (seeded by
// `name`), each active ORN firing at `hz`. Useful when no odour data is loaded.
RateSet random_odour(const Network& net, const std::string& name,
                    double fraction = 0.3, double hz = 80.0);

} 