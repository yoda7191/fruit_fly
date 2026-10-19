#include "fruit_fly/csv.hpp"

#include <algorithm>
#include <fstream>
#include <stdexcept>

namespace fruit_fly {

namespace {

// A quoted field may contain line breaks. The quote count of a complete
// record is even (escaped "" adds two), so keep reading while it's odd.
bool read_record(std::istream& in, std::string& record, size_t& line_no) {
    if (!std::getline(in, record)) return false;
    ++line_no;
    size_t quotes = static_cast<size_t>(std::count(record.begin(), record.end(), '"'));
    std::string more;
    while (quotes % 2 == 1 && std::getline(in, more)) {
        ++line_no;
        record += '\n';
        record += more;
        quotes += static_cast<size_t>(std::count(more.begin(), more.end(), '"'));
    }
    return true;
}

}  // namespace

std::vector<std::string> split_csv_line(const std::string& line, char sep) {
    std::vector<std::string> fields;
    std::string cur;
    bool in_quotes = false;

    for (size_t i = 0; i < line.size(); ++i) {
        char c = line[i];
        if (in_quotes) {
            if (c == '"') {
                // "" inside quotes is an escaped quote character
                if (i + 1 < line.size() && line[i + 1] == '"') {
                    cur += '"';
                    ++i;
                } else {
                    in_quotes = false;
                }
            } else {
                cur += c;
            }
        } else if (c == '"') {
            in_quotes = true;
        } else if (c == sep) {
            fields.push_back(cur);
            cur.clear();
        } else if (c != '\r') {      // tolerate Windows line endings
            cur += c;
        }
    }
    fields.push_back(cur);
    return fields;
}

CsvTable read_csv(const std::string& path, char sep) {
    std::ifstream in(path);
    if (!in) throw std::runtime_error("cannot open " + path);

    CsvTable t;
    std::string line;
    size_t line_no = 0;
    if (!read_record(in, line, line_no)) throw std::runtime_error("empty file " + path);
    t.header = split_csv_line(line, sep);

    bool header_fixed = false;
    while (read_record(in, line, line_no)) {
        if (line.empty() || line == "\r") continue;
        auto fields = split_csv_line(line, sep);

        // R-style file: rows carry a row name the header has no cell for.
        if (!header_fixed && t.rows.empty() && fields.size() == t.header.size() + 1) {
            t.header.insert(t.header.begin(), "");
            header_fixed = true;
        }
        if (fields.size() != t.header.size()) {
            throw std::runtime_error(path + ":" + std::to_string(line_no) +
                                     ": expected " + std::to_string(t.header.size()) +
                                     " fields, got " + std::to_string(fields.size()));
        }
        t.rows.push_back(std::move(fields));
    }
    return t;
}

int CsvTable::col_or_missing(const std::string& name) const {
    for (size_t i = 0; i < header.size(); ++i)
        if (header[i] == name) return static_cast<int>(i);
    return -1;
}

int CsvTable::col(const std::string& name) const {
    int i = col_or_missing(name);
    if (i < 0) throw std::runtime_error("missing CSV column: " + name);
    return i;
}

} // namespace fruit_fly