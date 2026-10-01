// SPDX-License-Identifier: LGPL-2.1-or-later

#include <QByteArrayView>
#include <QCryptographicHash>

#include <algorithm>
#include <cstring>

#include <Base/Exception.h>

#include "NameId.h"

using namespace Data;

namespace
{

constexpr std::array<unsigned char, 16> idKey
    {'M', 'a', 'p', 'p', 'e', 'd', 'N', 'a', 'm', 'e', ' ', 'I', 'D', ' ', 'v', '1'};

constexpr char base32Digits[] = "0123456789abcdefghijklmnopqrstuv";

void checkWidth(int bits)
{
    if (!NameId::isValidWidth(bits)) {
        throw Base::ValueError("A name ID is 64 or 128 bits wide");
    }
}

inline std::uint64_t rotl(std::uint64_t x, int b)
{
    return (x << b) | (x >> (64 - b));
}

inline std::uint64_t load64(const unsigned char* p)
{
    std::uint64_t v = 0;
    for (int i = 7; i >= 0; --i) {
        v = (v << 8) | p[i];
    }
    return v;
}

inline void store64(std::uint64_t v, unsigned char* p)
{
    for (int i = 0; i < 8; ++i) {
        p[i] = static_cast<unsigned char>(v >> (8 * i));
    }
}

struct SipState
{
    std::uint64_t v0, v1, v2, v3;

    void round()
    {
        v0 += v1;
        v1 = rotl(v1, 13);
        v1 ^= v0;
        v0 = rotl(v0, 32);
        v2 += v3;
        v3 = rotl(v3, 16);
        v3 ^= v2;
        v0 += v3;
        v3 = rotl(v3, 21);
        v3 ^= v0;
        v2 += v1;
        v1 = rotl(v1, 17);
        v1 ^= v2;
        v2 = rotl(v2, 32);
    }

    void compress(std::uint64_t m)
    {
        v3 ^= m;
        round();
        round();
        v0 ^= m;
    }

    std::uint64_t finalize(std::uint64_t marker)
    {
        v2 ^= marker;
        for (int i = 0; i < 4; ++i) {
            round();
        }
        return v0 ^ v1 ^ v2 ^ v3;
    }
};

// SipHash-2-4 with 64 or 128 bits of output (the reference implementation's siphash.c).
void sipHash(const unsigned char* key,
             const char* data,
             std::size_t size,
             unsigned char* out,
             bool wide)
{
    const std::uint64_t k0 = load64(key);
    const std::uint64_t k1 = load64(key + 8);
    SipState s {0x736f6d6570736575ULL ^ k0,
                0x646f72616e646f6dULL ^ k1,
                0x6c7967656e657261ULL ^ k0,
                0x7465646279746573ULL ^ k1};
    if (wide) {
        s.v1 ^= 0xee;
    }

    auto in = reinterpret_cast<const unsigned char*>(data);
    const std::size_t whole = size - size % 8;
    for (std::size_t i = 0; i < whole; i += 8) {
        s.compress(load64(in + i));
    }
    std::uint64_t last = static_cast<std::uint64_t>(size & 0xff) << 56;
    for (std::size_t i = whole; i < size; ++i) {
        last |= static_cast<std::uint64_t>(in[i]) << (8 * (i - whole));
    }
    s.compress(last);

    store64(s.finalize(wide ? 0xee : 0xff), out);
    if (wide) {
        s.v1 ^= 0xdd;
        store64(s.finalize(0), out + 8);
    }
}

}  // namespace

const std::array<unsigned char, 16>& SipHash::nameIdKey()
{
    return idKey;
}

void SipHash::hash64(const unsigned char* key, const char* data, std::size_t size, unsigned char* out8)
{
    sipHash(key, data, size, out8, false);
}

void SipHash::hash128(const unsigned char* key, const char* data, std::size_t size, unsigned char* out16)
{
    sipHash(key, data, size, out16, true);
}

NameId NameId::compute(const char* data, std::size_t size, int bits, NameIdHash hash)
{
    checkWidth(bits);
    NameId id;
    id._bits = bits;
    switch (hash) {
        case NameIdHash::SipHash24:
            sipHash(idKey.data(), data, size, id._bytes.data(), bits == 128);
            break;
        case NameIdHash::Blake2b: {
            const QByteArray digest =
                QCryptographicHash::hash(QByteArrayView(data, static_cast<qsizetype>(size)),
                                         QCryptographicHash::Blake2b_256);
            std::memcpy(id._bytes.data(), digest.constData(), bits / 8);
            break;
        }
    }
    return id;
}

NameId NameId::fromBytes(const unsigned char* bytes, int bits)
{
    checkWidth(bits);
    NameId id;
    id._bits = bits;
    std::memcpy(id._bytes.data(), bytes, bits / 8);
    return id;
}

std::string NameId::toBase32() const
{
    // The bytes are read as one big-endian bit string, five bits per character, and the last
    // character is padded with zero bits.
    std::string text;
    text.reserve(base32Length(_bits));
    unsigned buffer = 0;
    int pending = 0;
    for (int i = 0; i < _bits / 8; ++i) {
        buffer = (buffer << 8) | _bytes[i];
        pending += 8;
        while (pending >= 5) {
            pending -= 5;
            text += base32Digits[(buffer >> pending) & 31];
        }
    }
    if (pending > 0) {
        text += base32Digits[(buffer << (5 - pending)) & 31];
    }
    return text;
}

std::optional<NameId> NameId::fromBase32(std::string_view text)
{
    int bits = 0;
    if (text.size() == static_cast<std::size_t>(base32Length(64))) {
        bits = 64;
    }
    else if (text.size() == static_cast<std::size_t>(base32Length(128))) {
        bits = 128;
    }
    else {
        return std::nullopt;
    }

    NameId id;
    id._bits = bits;
    unsigned buffer = 0;
    int pending = 0;
    int byte = 0;
    for (char c : text) {
        unsigned value = 0;
        if (c >= '0' && c <= '9') {
            value = c - '0';
        }
        else if (c >= 'a' && c <= 'v') {
            value = c - 'a' + 10;
        }
        else {
            return std::nullopt;
        }
        buffer = (buffer << 5) | value;
        pending += 5;
        if (pending >= 8) {
            pending -= 8;
            id._bytes[byte++] = static_cast<unsigned char>(buffer >> pending);
        }
    }
    // The padding bits of the last character must be zero, so each ID has one text form.
    if ((buffer & ((1U << pending) - 1)) != 0) {
        return std::nullopt;
    }
    return id;
}
