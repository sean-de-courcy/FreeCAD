// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <FCConfig.h>

#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <string>
#include <string_view>

namespace Data
{

/** The content ID of a mapped-name node (bounded names, interning).
 *
 * The ID is SipHash-2-4 of the node's canonical bytes, with a fixed key, 64 or 128 bits wide.
 * SipHash was chosen over BLAKE2b (through QCryptographicHash) by the microbenchmark in
 * tests/src/App/NameId.cpp: about 43 against 218 ns per hash at the median node size of 45
 * bytes, at both widths, and faster at every size up to 4 kB (ops#6). Its text form is
 * lowercase base32hex (RFC 4648 section 7, digits `0-9a-v`, no padding): 13 characters for
 * 64 bits, 26 for 128. The text holds no name delimiter, no `.` and no whitespace, and every ID
 * has exactly one text form (the unused low bits of the last character are zero).
 *
 * The ID is a pure function of the bytes and the width: it doesn't depend on the
 * platform, the process or the run. The golden vectors in tests/src/App/NameId.cpp hold it there.
 */
class AppExport NameId
{
public:
    static constexpr int MaxBytes = 16;

    /// An invalid ID (zero bits).
    NameId() = default;

    /// The ID of \a size bytes at \a data, \a bits wide (64 or 128).
    static NameId compute(const char* data, std::size_t size, int bits);
    static NameId compute(std::string_view data, int bits)
    {
        return compute(data.data(), data.size(), bits);
    }

    /// The ID with the given bytes, \a bits wide (64 or 128).
    static NameId fromBytes(const unsigned char* bytes, int bits);

    /// Parses the text form. The width follows from the length (13 or 26 characters). Returns
    /// nothing for any other length, a character outside `0-9a-v`, or nonzero padding bits.
    static std::optional<NameId> fromBase32(std::string_view text);

    std::string toBase32() const;

    /// The length of the text form of an ID \a bits wide.
    static constexpr int base32Length(int bits)
    {
        return (bits + 4) / 5;
    }

    /// True for the widths an ID can have (64 or 128).
    static constexpr bool isValidWidth(int bits)
    {
        return bits == 64 || bits == 128;
    }

    int bits() const
    {
        return _bits;
    }
    bool isValid() const
    {
        return _bits != 0;
    }
    /// The ID's bytes; only the first bits() / 8 are used, the rest are zero.
    const std::array<unsigned char, MaxBytes>& bytes() const
    {
        return _bytes;
    }

    friend bool operator==(const NameId& a, const NameId& b)
    {
        return a._bits == b._bits && a._bytes == b._bytes;
    }
    friend bool operator!=(const NameId& a, const NameId& b)
    {
        return !(a == b);
    }
    friend bool operator<(const NameId& a, const NameId& b)
    {
        return a._bits != b._bits ? a._bits < b._bits : a._bytes < b._bytes;
    }

private:
    std::array<unsigned char, MaxBytes> _bytes {};
    int _bits = 0;
};

/// SipHash-2-4 (Aumasson and Bernstein, 2012), as in its reference implementation: the
/// result bytes are the reference's output bytes (the 64-bit result little-endian).
namespace SipHash
{
/// The fixed key of NameId: the 16 ASCII bytes "MappedName ID v1".
AppExport const std::array<unsigned char, 16>& nameIdKey();

AppExport void hash64(
    const unsigned char* key,
    const char* data,
    std::size_t size,
    unsigned char* out8
);
AppExport void hash128(
    const unsigned char* key,
    const char* data,
    std::size_t size,
    unsigned char* out16
);
}  // namespace SipHash

}  // namespace Data
