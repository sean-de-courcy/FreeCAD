// SPDX-License-Identifier: LGPL-2.1-or-later
/****************************************************************************
 *                                                                          *
 *   This file is part of FreeCAD.                                          *
 *                                                                          *
 *   FreeCAD is free software: you can redistribute it and/or modify it     *
 *   under the terms of the GNU Lesser General Public License as            *
 *   published by the Free Software Foundation, either version 2.1 of the   *
 *   License, or (at your option) any later version.                        *
 *                                                                          *
 *   FreeCAD is distributed in the hope that it will be useful, but         *
 *   WITHOUT ANY WARRANTY; without even the implied warranty of             *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU       *
 *   Lesser General Public License for more details.                        *
 *                                                                          *
 *   You should have received a copy of the GNU Lesser General Public       *
 *   License along with FreeCAD. If not, see                                *
 *   <https://www.gnu.org/licenses/>.                                       *
 *                                                                          *
 ***************************************************************************/

#pragma once

#include <cstddef>
#include <cstdint>
#include <cstdlib>

namespace Part
{

/** Seeded hashing for the hash containers of the naming code (V2 element names).
 *
 * Element names must not depend on the iteration order of a hash container: that order differs
 * between standard libraries (MSVC, libc++) and, for pointer keys, between runs. To test that,
 * the containers at the naming sites hash through NamingHasher, which mixes the plain hash with a
 * seed taken from the environment variable FREECAD_NAMING_HASH_SEED (an unsigned integer). A test
 * runs the same models under different seeds and compares their names.
 *
 * Unset, empty, unparsable or 0, the seed is off and NamingHasher returns the plain hash. The
 * variable is read once, on first use: a seed that changed in a running process would break the
 * lookups of live containers.
 */
inline std::uint64_t namingHashSeed()
{
    static const std::uint64_t seed = []() -> std::uint64_t {
        const char* value = std::getenv("FREECAD_NAMING_HASH_SEED");
        if (!value || !*value) {
            return 0;
        }
        char* end = nullptr;
        unsigned long long parsed = std::strtoull(value, &end, 0);
        return (end && *end == '\0') ? static_cast<std::uint64_t>(parsed) : 0;
    }();
    return seed;
}

/// The plain hash, or with a seed set, splitmix64 of the hash xor the seed.
inline std::size_t namingHash(std::size_t hash)
{
    const std::uint64_t seed = namingHashSeed();
    if (seed == 0) {
        return hash;
    }
    std::uint64_t z = static_cast<std::uint64_t>(hash) ^ seed;
    z += 0x9e3779b97f4a7c15ULL;
    z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ULL;
    z = (z ^ (z >> 27)) * 0x94d049bb133111ebULL;
    return static_cast<std::size_t>(z ^ (z >> 31));
}

/** Wraps a hasher so that its hashes go through namingHash().
 *
 * Equality calls with two arguments are passed on unchanged, so a hasher that also serves as the
 * container's equality (ShapeHasher) can be wrapped as both.
 */
template<class Hasher>
struct NamingHasher
{
    template<class T>
    std::size_t operator()(const T& value) const
    {
        return namingHash(hasher(value));
    }

    template<class T>
    bool operator()(const T& a, const T& b) const
    {
        return hasher(a, b);
    }

private:
    Hasher hasher {};
};

}  // namespace Part
