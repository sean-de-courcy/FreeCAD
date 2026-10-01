// SPDX-License-Identifier: LGPL-2.1-or-later

#include <gtest/gtest.h>

#include <App/NameId.h>
#include <Base/Exception.h>

#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <random>
#include <sstream>
#include <string>
#include <vector>

using Data::NameId;

namespace
{

std::string hex(const unsigned char* bytes, std::size_t size)
{
    std::ostringstream out;
    out << std::hex << std::setfill('0');
    for (std::size_t i = 0; i < size; ++i) {
        out << std::setw(2) << static_cast<int>(bytes[i]);
    }
    return out.str();
}

std::string counting(std::size_t size)
{
    std::string data(size, '\0');
    for (std::size_t i = 0; i < size; ++i) {
        data[i] = static_cast<char>(i);
    }
    return data;
}

// The ID of every row at both widths. The values were computed with an independent
// implementation (Python: SipHash-2-4 per its reference code, RFC 4648 base32hex) and are
// written here; the test doesn't generate them.
struct Golden
{
    std::string data;
    const char* id64;
    const char* id128;
};

// clang-format off
const std::vector<Golden>& goldens()
{
    static const std::vector<Golden> rows {
        {"",
         "tk9bop2c56sug", "410e7kfsvera9ufku77uavrhvo"},
        {"Edge1",
         "juojvc2rvkcj0", "4b2e2j1ifm34kodma1u0dd3qmk"},
        {"Face12",
         "2jnrokcl56bs0", "j08o0bph7cb8pc6tgdhmqdj4d8"},
        {"12345678",
         "qta1qhgnrtm5m", "9hcj6igjddmj1hnh70dt0lk7us"},
        {"1234567890abcdef",
         "ts9egl5jtbfvo", "0t3kj3mg5av8p0gac2dadtt6go"},
        {"_;_;5;FLT;0;F;0;GEN;_",
         "5frmroobjfh6m", "m48bd4f8415v1nfqtp5hmtij0c"},
        {"_;_;-12;FUS;0;F;0;MOD;_",
         "3hc36aaoe3nnm", "boq5pvpis84moup15ibb907n48"},
        {"_;_;5;TRF;3;F;0;MOD;_",
         "o2kpq1es845jq", "dhuajpt516qv9hfmo0nems96r8"},
        {"_;~0123456789abc;7;FLT;0;F;0;GEN;_",
         "ieai1i5ed318c", "66q6pe3gfpgu1mcuc5g4fpbk0k"},
        {"_;~0123456789abe;7;FLT;0;F;0;GEN;_",
         "1cqbes03c932q", "3krmjrdqcbk33uem6jq7pvnj1k"},
        {"~0123456789abc|_;_;23;CUT;0;E;0;MOD;~0123456789abc,~fedcba9876544",
         "01k1o7kl2i5d4", "cgvb2nu1csbcg3f2g9e99ip9k8"},
        {"_;~aaaaaaaaaaaaa,~bbbbbbbbbbbb0,~cccccccccccc0;9;XTR;1;F;0;GEN;~dddddddddddd0",
         "jk4as2r3du3ki", "f3b0iuasu0ti1gpt9gjcvnqm08"},
        {"~vvvvvvvvvvvvu|~0000000000000|_;_;-3;SKT;0;V;0;GEN;_",
         "7496j2fc6lfr4", "hua59k57tvhlaqdd1p69jq53no"},
        {"_;~0123456789abcdefghijklmnos;7;FLT;0;F;0;GEN;_",
         "dc86nol6jab5a", "tqogj20mkun5o8ohh6c1jd5mus"},
        {"_;Edge1^;_^;5^;FLT^;0^;E^;0^;IDX^,SRC^;_;7;FLT;0;F;0;GEN;_",
         "69qkudoski6om", "ds7i2as2lbenf49jgas0n1drlg"},
        {"Fl\xc3\xa4" "che",
         "iop5dge6frqoi", "3esbpeh9c5g85l9quh8eqf9gcs"},
        {std::string(127, 'x'),
         "pf83uqpt96i10", "8v5k4redc2s7numashhhc09k3k"},
        {std::string(128, 'x'),
         "ct5038mej78pc", "4227knqt3ltoau4t9fpq4atpo8"},
        {std::string(129, 'x'),
         "gljjs891mkcvq", "qonkummmk9k70639jfbhgafgjs"},
        {std::string(1947, 'y'),
         "denj0cglts5hk", "bru07qrsnlblbrien2tuio0v9o"},
    };
    return rows;
}
// clang-format on

}  // namespace

// SipHash-2-4's reference vectors (the reference implementation's vectors.h): key 00..0f,
// message 00 01 02 ... of the given length.
TEST(NameIdSipHash, referenceVectors64)
{
    std::array<unsigned char, 16> key {};
    for (int i = 0; i < 16; ++i) {
        key[i] = static_cast<unsigned char>(i);
    }
    const std::vector<std::pair<std::size_t, const char*>> vectors {
        {0, "310e0edd47db6f72"},
        {1, "fd67dc93c539f874"},
        {7, "37d1018bf50002ab"},
        {8, "6224939a79f5f593"},
        {15, "e545be4961ca29a1"},  // the paper's example, 0xa129ca6149be45e5
        {16, "db9bc2577fcc2a3f"},
        {63, "724506eb4c328a95"},
    };
    for (const auto& [size, expected] : vectors) {
        const std::string data = counting(size);
        unsigned char out[8];
        Data::SipHash::hash64(key.data(), data.data(), data.size(), out);
        EXPECT_EQ(hex(out, 8), expected) << "length " << size;
    }
}

TEST(NameIdSipHash, referenceVectors128)
{
    std::array<unsigned char, 16> key {};
    for (int i = 0; i < 16; ++i) {
        key[i] = static_cast<unsigned char>(i);
    }
    const std::vector<std::pair<std::size_t, const char*>> vectors {
        {0, "a3817f04ba25a8e66df67214c7550293"},
        {1, "da87c1d86b99af44347659119b22fc45"},
        {7, "a1f1ebbed8dbc153c0b84aa61ff08239"},
        {8, "3b62a9ba6258f5610f83e264f31497b4"},
        {15, "5493e99933b0a8117e08ec0f97cfc3d9"},
        {16, "6ee2a4ca67b054bbfd3315bf85230577"},
        {63, "5150d1772f50834a503e069a973fbd7c"},
    };
    for (const auto& [size, expected] : vectors) {
        const std::string data = counting(size);
        unsigned char out[16];
        Data::SipHash::hash128(key.data(), data.data(), data.size(), out);
        EXPECT_EQ(hex(out, 16), expected) << "length " << size;
    }
}

TEST(NameIdSipHash, fixedKey)
{
    const auto& key = Data::SipHash::nameIdKey();
    EXPECT_EQ(std::string(reinterpret_cast<const char*>(key.data()), key.size()), "MappedName ID v1");
}

TEST(NameId, goldenIds)
{
    for (const auto& row : goldens()) {
        const std::string what = "input of " + std::to_string(row.data.size())
            + " bytes: " + row.data.substr(0, 80);
        EXPECT_EQ(NameId::compute(row.data, 64).toBase32(), row.id64) << what;
        EXPECT_EQ(NameId::compute(row.data, 128).toBase32(), row.id128) << what;
    }
}

TEST(NameId, goldenIdsAreDistinct)
{
    std::vector<std::string> ids;
    for (const auto& row : goldens()) {
        ids.insert(ids.end(), {row.id64, row.id128});
    }
    std::sort(ids.begin(), ids.end());
    EXPECT_EQ(std::adjacent_find(ids.begin(), ids.end()), ids.end());
}

TEST(NameId, computeMatchesTheHash)
{
    const std::string data = "_;~0123456789abc;7;FLT;0;F;0;GEN;_";
    unsigned char out[16];
    Data::SipHash::hash128(Data::SipHash::nameIdKey().data(), data.data(), data.size(), out);
    EXPECT_EQ(NameId::compute(data, 128), NameId::fromBytes(out, 128));
    Data::SipHash::hash64(Data::SipHash::nameIdKey().data(), data.data(), data.size(), out);
    EXPECT_EQ(NameId::compute(data, 64), NameId::fromBytes(out, 64));
    EXPECT_EQ(NameId::compute(data.data(), data.size(), 64), NameId::compute(data, 64));
}

TEST(NameId, base32)
{
    // RFC 4648's "foobar" in base32hex is CPNMUOJ1E8; these are 8 and 16 byte IDs.
    const unsigned char foobarba[] = {'f', 'o', 'o', 'b', 'a', 'r', 'b', 'a'};
    EXPECT_EQ(NameId::fromBytes(foobarba, 64).toBase32(), "cpnmuoj1e9h62");

    const unsigned char zeros[16] = {};
    EXPECT_EQ(NameId::fromBytes(zeros, 64).toBase32(), "0000000000000");
    EXPECT_EQ(NameId::fromBytes(zeros, 128).toBase32(), "00000000000000000000000000");

    unsigned char ones[16];
    std::memset(ones, 0xff, sizeof(ones));
    EXPECT_EQ(NameId::fromBytes(ones, 64).toBase32(), "vvvvvvvvvvvvu");
    EXPECT_EQ(NameId::fromBytes(ones, 128).toBase32(), "vvvvvvvvvvvvvvvvvvvvvvvvvs");

    unsigned char counted[16];
    for (int i = 0; i < 16; ++i) {
        counted[i] = static_cast<unsigned char>(i);
    }
    EXPECT_EQ(NameId::fromBytes(counted, 128).toBase32(), "000g40o40k30e209185go38e1s");

    EXPECT_EQ(NameId::base32Length(64), 13);
    EXPECT_EQ(NameId::base32Length(128), 26);
}

TEST(NameId, base32RoundTrips)
{
    std::mt19937_64 random(20260930);
    for (int bits : {64, 128}) {
        for (int i = 0; i < 1000; ++i) {
            unsigned char bytes[16];
            for (auto& b : bytes) {
                b = static_cast<unsigned char>(random());
            }
            const NameId id = NameId::fromBytes(bytes, bits);
            const std::string text = id.toBase32();
            ASSERT_EQ(text.size(), static_cast<std::size_t>(NameId::base32Length(bits)));
            ASSERT_EQ(text.find_first_not_of("0123456789abcdefghijklmnopqrstuv"), std::string::npos);
            const auto back = NameId::fromBase32(text);
            ASSERT_TRUE(back.has_value()) << text;
            EXPECT_EQ(*back, id) << text;
            EXPECT_EQ(back->bits(), bits);
        }
    }
}

TEST(NameId, base32RejectsOtherForms)
{
    EXPECT_FALSE(NameId::fromBase32(""));
    EXPECT_FALSE(NameId::fromBase32("000000000000"));    // 12 characters
    EXPECT_FALSE(NameId::fromBase32("00000000000000"));  // 14 characters
    EXPECT_FALSE(NameId::fromBase32("CPNMUOJ1E9H62"));   // upper case
    EXPECT_FALSE(NameId::fromBase32("cpnmuoj1e9h6w"));   // outside 0-9a-v
    EXPECT_FALSE(NameId::fromBase32("cpnmuoj1e9h6~"));
    // Nonzero padding bits: the last character of a 64-bit ID holds 4 bits and one zero bit,
    // the last of a 128-bit ID 3 bits and two zero bits.
    EXPECT_FALSE(NameId::fromBase32("0000000000001"));
    EXPECT_TRUE(NameId::fromBase32("0000000000002"));
    EXPECT_FALSE(NameId::fromBase32("00000000000000000000000002"));
    EXPECT_TRUE(NameId::fromBase32("00000000000000000000000004"));
}

TEST(NameId, widths)
{
    EXPECT_FALSE(NameId().isValid());
    EXPECT_EQ(NameId().bits(), 0);
    EXPECT_TRUE(NameId::compute("x", 64).isValid());
    EXPECT_THROW(NameId::compute("x", 32), Base::ValueError);
    EXPECT_THROW(NameId::compute("x", 256), Base::ValueError);
    const unsigned char bytes[16] = {};
    EXPECT_THROW(NameId::fromBytes(bytes, 96), Base::ValueError);

    // One content gives different IDs at different widths, and they never compare equal.
    const unsigned char ones[16] = {1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1};
    EXPECT_NE(NameId::fromBytes(ones, 64), NameId::fromBytes(ones, 128));
    EXPECT_TRUE(NameId::fromBytes(ones, 64) < NameId::fromBytes(ones, 128));
}

// The hash microbenchmark (notes\task1-plan.md section 6). It asserts nothing about speed: the
// timings go to the log and, through RecordProperty, to the gtest XML of both CI platforms.
// NAMEID_BENCH_SCALE=<n> multiplies the work for a steadier local measurement.
//
// It chose SipHash-2-4 over BLAKE2b-256 through QCryptographicHash (Qt 6.11, OpenSSL 3), on
// Windows, 2026-09-30, in ns per hash (BLAKE2b with a reused hash object, its faster form):
//   bytes       16    32    45    64   128   256  1024  4096
//   sip64       28    37    43    54    85   152   540  2100
//   sip128      36    44    51    61    94   160   560  2130
//   BLAKE2b    217   216   219   219   216   358  1217  4600
// The BLAKE2b arm was removed with that decision (ops#6).
TEST(NameIdBenchmark, hashSpeed)
{
    using Clock = std::chrono::steady_clock;

    // 45 bytes is the median node of the Phase 4 benchmark models (results\bench-baseline.md).
    const std::vector<std::size_t> sizes {16, 32, 45, 64, 128, 256, 1024, 4096};
    const int runs = 5;
    std::size_t scale = 1;
    if (const char* env = std::getenv("NAMEID_BENCH_SCALE")) {
        scale = std::max<std::size_t>(1, std::strtoul(env, nullptr, 10));
    }
    const std::size_t budget = scale * 1024 * 1024;  // bytes hashed per width, size and run

    std::mt19937 random(45);
    std::uniform_int_distribution<int> printable(0x21, 0x7e);
    volatile unsigned sink = 0;

    std::ostringstream table;
    table << std::fixed << std::setprecision(1);
    table << "NameId (SipHash-2-4), ns per hash (median of " << runs << " runs)\n"
          << std::setw(8) << "bytes" << std::setw(10) << "64 bits" << std::setw(10) << "128 bits"
          << '\n';
    for (std::size_t size : sizes) {
        std::vector<std::string> pool(64);
        for (auto& s : pool) {
            s.resize(size);
            for (auto& c : s) {
                c = static_cast<char>(printable(random));
            }
        }
        const std::size_t count = std::clamp<std::size_t>(budget / size, 500, 200000 * scale);
        table << std::setw(8) << size;
        for (int bits : {64, 128}) {
            std::vector<double> perRun;
            for (int run = 0; run < runs; ++run) {
                unsigned acc = 0;
                const auto start = Clock::now();
                for (std::size_t i = 0; i < count; ++i) {
                    acc += NameId::compute(pool[i % pool.size()], bits).bytes()[0];
                }
                const auto stop = Clock::now();
                sink = sink + acc;
                perRun.push_back(
                    std::chrono::duration<double, std::nano>(stop - start).count()
                    / static_cast<double>(count)
                );
            }
            std::nth_element(perRun.begin(), perRun.begin() + runs / 2, perRun.end());
            const double ns = perRun[runs / 2];
            table << std::setw(10) << ns;
            std::ostringstream value;
            value << std::fixed << std::setprecision(1) << ns;
            RecordProperty("ns_sip" + std::to_string(bits) + "_" + std::to_string(size), value.str());
        }
        table << '\n';
    }
    std::cout << table.str() << std::flush;
}
