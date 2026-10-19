#include "fruit_fly/odours.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdlib>
#include <limits>
#include <random>
#include <set>
#include <sstream>
#include <stdexcept>
#include <unordered_map>

#include "fruit_fly/csv.hpp"

namespace fruit_fly {

namespace {

constexpr double kNaN = std::numeric_limits<double>::quiet_NaN();
const char* kOrnPrefix = "ORN_";

bool is_missing(const std::string& s) { return s.empty() || s == "NA"; }

double parse_or_nan(const std::string& s) {
    if (is_missing(s)) return kNaN;
    char* end = nullptr;
    double v = std::strtod(s.c_str(), &end);
    return end == s.c_str() ? kNaN : v;
}

std::string lower(std::string s) {
    for (char& c : s) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    return s;
}

std::string alias(const std::string& glom) {
    auto it = glomerulus_aliases().find(glom);
    return it == glomerulus_aliases().end() ? glom : it->second;
}

double median(std::vector<double> v) {
    v.erase(std::remove_if(v.begin(), v.end(), [](double x) { return std::isnan(x); }), v.end());
    if (v.empty()) return 0.0;
    std::sort(v.begin(), v.end());
    size_t n = v.size();
    return n % 2 ? v[n / 2] : 0.5 * (v[n / 2 - 1] + v[n / 2]);
}

// Stable string hash (std::hash differs between compilers).
uint64_t fnv1a(const std::string& s) {
    uint64_t h = 1469598103934665603ULL;
    for (unsigned char c : s) { h ^= c; h *= 1099511628211ULL; }
    return h;
}

}  // namespace

const std::map<std::string, std::string>& glomerulus_aliases() {
    // Extend when OdourStimulus::report() lists ORN glomeruli missing from DoOR.
    static const std::map<std::string, std::string> aliases = {
        {"VA1lm", "VA1v"},
    };
    return aliases;
}

// ====================================================================== library

OdourLibrary OdourLibrary::load(const std::string& door_dir) {
    OdourLibrary lib;
    CsvTable matrix = read_csv(door_dir + "/door_response_matrix.csv", ';');
    CsvTable mappings = read_csv(door_dir + "/door_mappings.csv", ';');
    CsvTable odours = read_csv(door_dir + "/odor.csv", ';');

    // ---- one responding unit per glomerulus (DoOR marks it with `code`)
    const int c_receptor = mappings.col("receptor"), c_code = mappings.col("code");
    std::vector<int> unit_cols;   // matrix column for each glomerulus
    for (const auto& r : mappings.rows) {
        if (is_missing(r[c_code])) continue;
        int mc = matrix.col_or_missing(r[c_receptor]);
        if (mc < 0) continue;
        unit_cols.push_back(mc);
        lib.glomeruli_.push_back(alias(r[c_code]));
    }

    // ---- InChIKey -> readable name (first name wins)
    const int c_name = odours.col("Name"), c_key = odours.col("InChIKey");
    std::unordered_map<std::string, std::string> name_of;
    for (const auto& r : odours.rows) name_of.emplace(r[c_key], r[c_name]);

    // ---- responses; row names are in column 0
    std::set<std::string> seen;
    bool have_sfr = false;
    for (const auto& r : matrix.rows) {
        std::vector<double> vals;
        vals.reserve(unit_cols.size());
        for (int mc : unit_cols) vals.push_back(parse_or_nan(r[mc]));

        if (r[0] == "SFR") {
            lib.spontaneous_ = vals;
            have_sfr = true;
            continue;
        }
        auto it = name_of.find(r[0]);
        std::string name = it == name_of.end() ? r[0] : it->second;
        if (!seen.insert(name).second) continue;          // duplicate name
        lib.names_.push_back(name);
        lib.responses_.push_back(std::move(vals));
    }
    if (!have_sfr) throw std::runtime_error("DoOR matrix has no SFR row");

    // A few units lack a spontaneous value; the median is a neutral stand-in.
    double med = median(lib.spontaneous_);
    for (double& s : lib.spontaneous_)
        if (std::isnan(s)) s = med;
    return lib;
}

int32_t OdourLibrary::odour_index(const std::string& name) const {
    for (size_t i = 0; i < names_.size(); ++i)
        if (names_[i] == name) return static_cast<int32_t>(i);
    const std::string want = lower(name);
    for (size_t i = 0; i < names_.size(); ++i)
        if (lower(names_[i]) == want) return static_cast<int32_t>(i);

    std::string msg = "unknown odour '" + name + "'";
    auto close = search(name);
    if (!close.empty()) {
        msg += "; did you mean:";
        for (size_t i = 0; i < close.size() && i < 5; ++i) msg += " '" + close[i] + "'";
    }
    throw std::out_of_range(msg);
}

std::vector<std::string> OdourLibrary::search(const std::string& text) const {
    std::vector<std::string> out;
    const std::string t = lower(text);
    for (const auto& n : names_)
        if (lower(n).find(t) != std::string::npos) out.push_back(n);
    return out;
}

const std::vector<double>& OdourLibrary::raw(const std::string& odour) const {
    return responses_[odour_index(odour)];
}

std::vector<double> OdourLibrary::profile(const std::string& odour) const {
    std::vector<double> p = raw(odour);
    for (size_t g = 0; g < p.size(); ++g)
        if (std::isnan(p[g])) p[g] = spontaneous_[g];
    return p;
}

double OdourLibrary::coverage(const std::string& odour) const {
    const auto& r = raw(odour);
    if (r.empty()) return 0.0;
    size_t n = 0;
    for (double v : r) n += !std::isnan(v);
    return static_cast<double>(n) / r.size();
}

double OdourLibrary::similarity(const std::string& a, const std::string& b) const {
    const auto& ra = raw(a);
    const auto& rb = raw(b);
    std::vector<double> xa, xb;
    for (size_t g = 0; g < ra.size(); ++g) {
        if (std::isnan(ra[g]) || std::isnan(rb[g])) continue;
        xa.push_back(ra[g] - spontaneous_[g]);
        xb.push_back(rb[g] - spontaneous_[g]);
    }
    if (xa.size() < 3) return kNaN;

    // Pearson correlation
    double ma = 0, mb = 0;
    for (size_t i = 0; i < xa.size(); ++i) { ma += xa[i]; mb += xb[i]; }
    ma /= xa.size();
    mb /= xb.size();
    double sab = 0, saa = 0, sbb = 0;
    for (size_t i = 0; i < xa.size(); ++i) {
        sab += (xa[i] - ma) * (xb[i] - mb);
        saa += (xa[i] - ma) * (xa[i] - ma);
        sbb += (xb[i] - mb) * (xb[i] - mb);
    }
    if (saa == 0 || sbb == 0) return kNaN;
    return sab / std::sqrt(saa * sbb);
}

// ====================================================================== stimulus

OdourStimulus::OdourStimulus(const OdourLibrary& lib, const Network& net, double max_rate_hz)
    : lib_(lib), max_rate_hz_(max_rate_hz) {
    // library column of each glomerulus
    std::map<std::string, int32_t> col_of;
    for (size_t g = 0; g < lib.glomeruli().size(); ++g)
        col_of.emplace(lib.glomeruli()[g], static_cast<int32_t>(g));

    // glomerulus -> ORN neurons, from labels like "ORN_DM2"
    const std::string prefix = kOrnPrefix;
    std::map<std::string, std::vector<int32_t>> orn_by_glom;
    for (int32_t i = 0; i < net.size(); ++i) {
        const std::string& ct = net.cell_type[i];
        if (ct.compare(0, prefix.size(), prefix) != 0) continue;
        orn_by_glom[alias(ct.substr(prefix.size()))].push_back(i);
    }

    for (const auto& [glom, neurons] : orn_by_glom) {
        auto it = col_of.find(glom);
        if (it == col_of.end()) {
            unmatched_network_.push_back(glom);
            other_.insert(other_.end(), neurons.begin(), neurons.end());
            continue;
        }
        matched_.push_back(glom);
        for (int32_t i : neurons) {
            orn_.push_back(i);
            orn_glom_.push_back(it->second);
        }
    }
    for (const auto& [glom, col] : col_of)
        if (!orn_by_glom.count(glom)) unmatched_door_.push_back(glom);
}

RateSet OdourStimulus::from_values(const std::vector<double>& per_glom) const {
    RateSet rs;
    rs.neurons = orn_;
    rs.hz.reserve(orn_.size() + other_.size());
    for (int32_t g : orn_glom_) rs.hz.push_back(std::max(0.0, per_glom[g] * max_rate_hz_));

    // ORNs without data: typical spontaneous rate so they aren't silent
    std::vector<double> base;
    for (int32_t g : orn_glom_) base.push_back(std::max(0.0, lib_.spontaneous()[g] * max_rate_hz_));
    const double other_hz = median(base);
    for (int32_t i : other_) {
        rs.neurons.push_back(i);
        rs.hz.push_back(other_hz);
    }
    return rs;
}

RateSet OdourStimulus::baseline() const { return from_values(lib_.spontaneous()); }

RateSet OdourStimulus::rates(const std::string& odour, double concentration) const {
    const auto prof = lib_.profile(odour);
    const auto& spont = lib_.spontaneous();
    std::vector<double> evoked(prof.size());
    for (size_t g = 0; g < prof.size(); ++g)
        evoked[g] = spont[g] + concentration * (prof[g] - spont[g]);
    return from_values(evoked);
}

std::string OdourStimulus::report() const {
    std::ostringstream os;
    os << "glomeruli with DoOR data and ORNs : " << matched_.size() << "\n"
       << "ORNs driven by DoOR data          : " << orn_.size() << "\n"
       << "ORNs at default spontaneous rate  : " << other_.size();
    auto join = [](const std::vector<std::string>& v) {
        std::string s;
        for (size_t i = 0; i < v.size(); ++i) s += (i ? ", " : "") + v[i];
        return s;
    };
    if (!unmatched_door_.empty())
        os << "\nDoOR glomeruli with no ORNs       : " << join(unmatched_door_);
    if (!unmatched_network_.empty())
        os << "\nORN glomeruli missing from DoOR   : " << join(unmatched_network_)
           << "\n  -> if any are renamings, add them to glomerulus_aliases()";
    return os.str();
}

// ====================================================================== random odours

RateSet random_odour(const Network& net, const std::string& name, double fraction, double hz) {
    const auto orns = net.indices_in_group("ORN");
    std::set<std::string> types;
    for (int32_t i : orns) types.insert(net.cell_type[i]);

    std::mt19937_64 rng(fnv1a(name));
    std::bernoulli_distribution pick(fraction);
    std::set<std::string> active;
    for (const auto& t : types)
        if (pick(rng)) active.insert(t);

    RateSet rs;
    for (int32_t i : orns)
        if (active.count(net.cell_type[i])) {
            rs.neurons.push_back(i);
            rs.hz.push_back(hz);
        }
    return rs;
}

} // namespace fruit_fly