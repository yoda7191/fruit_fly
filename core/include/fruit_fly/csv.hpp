// csv.hpp — a small CSV reader: header row, configurable separator,
// "quoted, fields" (which may contain separators, "" escapes and line breaks),
// and R-style files whose header lacks the row-name column.
#pragma once

#include <string>
#include <vector>

namespace fruit_fly {

struct CsvTable {
    std::vector<std::string> header;
    std::vector<std::vector<std::string>> rows;

    // Index of a column by name; throws std::runtime_error if missing.
    int col(const std::string& name) const;
    // Same, but returns -1 instead of throwing.
    int col_or_missing(const std::string& name) const;
};

// sep: field separator (',' for FlyWire/pandas files, ';' for DoOR).
// If every data row has exactly one more field than the header (R writes
// row names without a header cell), an empty column name is prepended.
CsvTable read_csv(const std::string& path, char sep = ',');

// Split one CSV line into fields (exposed so it can be unit-tested).
std::vector<std::string> split_csv_line(const std::string& line, char sep = ',');

}  // namespace fruit_fly
