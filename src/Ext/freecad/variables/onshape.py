# SPDX-License-Identifier: LGPL-2.1-or-later
# ****************************************************************************
# *                                                                          *
# *   This file is part of FreeCAD.                                          *
# *                                                                          *
# *   FreeCAD is free software: you can redistribute it and/or modify it     *
# *   under the terms of the GNU Lesser General Public License as            *
# *   published by the Free Software Foundation, either version 2.1 of the   *
# *   License, or (at your option) any later version.                        *
# *                                                                          *
# *   FreeCAD is distributed in the hope that it will be useful, but         *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of             *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU       *
# *   Lesser General Public License for more details.                        *
# *                                                                          *
# *   You should have received a copy of the GNU Lesser General Public       *
# *   License along with FreeCAD. If not, see                                *
# *   <https://www.gnu.org/licenses/>.                                       *
# *                                                                          *
# ***************************************************************************/

"""Onshape variable studio exports to FreeCAD expressions (FreeCAD-CH, ops#317 PR D).

The design is notes/variables-studio.md, section 2. An export is a JSON array of studio entries;
each variable has a type, a name and an Onshape expression, and no computed value. This module
reads that file, parses each expression with Onshape's rules as far as they are documented,
writes the FreeCAD expression and evaluates the expression itself, so the import (PR E1) can
check FreeCAD's value against the translator's. It needs no document.

**It never guesses.** A form whose meaning in Onshape isn't pinned down, or that FreeCAD can't
express, is refused with the reason (`Refused`). Until a reference studio built in Onshape
settles them (decision 68, D3), these are refused: a fraction with a unit next to `*`, `/` or
`^` (`#a*3/4 in`, `1/3/4 in`), a unary minus before `^` (`-2^2`), a unit before `^`
(`2 mm^2`; `(2 mm)^2` is clear), `%` with units or negative operands, `round`, chained `^` and
exponent notation.

The writer's rules (section 2.4):
- every unit is written as a factor: `10mm` becomes `(10 * 1 mm)`;
- an integer fraction followed by a unit, as a term of its own (bounded by `+`, `-`, a
  comparison, `?`, `:`, `,`, parentheses or the ends), is a fraction literal: `3/4 in` becomes
  `(3 / 4 * 1 in)`; FreeCAD reads `3/4in` as `3/(4 in)`, an inverse length, without an error;
- a unit after `)` or a function call applies to that group: `sqrt(16) m` is `(sqrt(16) * 1 m)`;
- unit words become FreeCAD's symbols, `PI` and `Pi` become `pi`;
- a `#name` becomes the text the caller gives for it (a sibling's bare name, another copy's
  `Copy.Name`, a document variable's path), never `#name`: FreeCAD's `#name` searches the whole
  document, a silent binding (section 2.6).
The text never holds `#`, `!`, `&&` or `||` (FreeCAD's lexer drops `!` without a word, ops#320).

Values are in SI units, angles in radians: `Quantity(0.01905, LENGTH)` is 3/4 in.
"""

import json
import math
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple, Union

# Dimensions: (length exponent, angle exponent).
NONE = (0, 0)
LENGTH = (1, 0)
ANGLE = (0, 1)


class Refused(Exception):
    """An expression or variable the translator won't translate; str() is the reason."""


class ExportError(ValueError):
    """The file isn't an Onshape variable studio export of the known structure (section 0)."""


@dataclass(frozen=True)
class Quantity:
    """A value in SI units (metres, radians) with its dimensions."""

    value: float
    dims: Tuple[int, int] = NONE

    def to(self, unit: str) -> float:
        """The value counted in @a unit (a FreeCAD symbol or an Onshape unit name)."""
        factor, dims, _symbol = UNITS[unit]
        if dims != self.dims:
            raise ValueError(f"{describe_dims(self.dims)} can't be counted in {unit}")
        return self.value / factor


def describe_dims(dims: Tuple[int, int]) -> str:
    names = {NONE: "a number", LENGTH: "a length", ANGLE: "an angle"}
    if dims in names:
        return names[dims]
    parts = []
    for exponent, base in zip(dims, ("length", "angle")):
        if exponent:
            parts.append(base if exponent == 1 else f"{base}^{exponent}")
    return " * ".join(parts)


# Onshape's unit names (symbols, words and plurals) -> (SI factor, dimensions, FreeCAD symbol).
UNITS: Dict[str, Tuple[float, Tuple[int, int], str]] = {}


def _units(symbol: str, factor: float, dims: Tuple[int, int], *names: str):
    for name in (symbol,) + names:
        UNITS[name] = (factor, dims, symbol)


_units("mm", 0.001, LENGTH, "millimeter", "millimeters")
_units("cm", 0.01, LENGTH, "centimeter", "centimeters")
_units("m", 1.0, LENGTH, "meter", "meters")
_units("in", 0.0254, LENGTH, "inch", "inches")
_units("ft", 0.3048, LENGTH, "foot", "feet")
_units("yd", 0.9144, LENGTH, "yard", "yards")
_units("deg", math.pi / 180, ANGLE, "degree", "degrees")
_units("rad", 1.0, ANGLE, "radian", "radians")

CONSTANTS = {"pi": math.pi, "PI": math.pi, "Pi": math.pi}

# Functions both languages have with the same meaning; the unit rules are in _call().
FUNCTIONS = {"abs", "acos", "asin", "atan", "atan2", "ceil", "cos", "cosh", "exp", "floor",
             "log", "log10", "max", "min", "sin", "sinh", "sqrt", "tan", "tanh"}
REFUSED_FUNCTIONS = {
    "round": "round() is refused until the reference studio shows how Onshape rounds halves "
             "(FreeCAD rounds them away from zero)",
    "asinh": "FreeCAD has no asinh()",
    "acosh": "FreeCAD has no acosh()",
    "atanh": "FreeCAD has no atanh()",
}

# The Onshape `type` -> (FreeCAD property type, the dimensions its expression must have).
TYPES = {
    "LENGTH": ("App::PropertyDistance", LENGTH),
    "ANGLE": ("App::PropertyAngle", ANGLE),
    "NUMBER": ("App::PropertyFloat", NONE),
}

UNDOCUMENTED = ("Onshape's reading of it isn't documented; refused until the reference studio "
                "settles it")


# --- Tokens ----------------------------------------------------------------------------------

@dataclass(frozen=True)
class Token:
    kind: str  # "number", "name", "ref", "op", "end"
    text: str
    pos: int


_TOKEN = re.compile(r"""
    (?P<space>\s+)
  | (?P<number>\d+\.?\d*|\.\d+)
  | (?P<ref>\#[A-Za-z_][A-Za-z0-9_]*)
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>==|!=|<=|>=|&&|\|\||[-+*/^%(),?:<>!])
  | (?P<other>.)
""", re.VERBOSE | re.DOTALL)

_REFUSED_CHARS = {
    "[": "arrays aren't supported",
    "]": "arrays aren't supported",
    "{": "maps and function definitions aren't supported",
    "}": "maps and function definitions aren't supported",
    '"': "strings aren't supported",
    "'": "strings aren't supported",
    "#": "a # must be followed by a variable name",
    "=": "= isn't an operator in expressions (== compares)",
    ";": "; isn't allowed (function arguments are separated by commas)",
}


def tokenize(text: str) -> List[Token]:
    tokens = []
    for match in _TOKEN.finditer(text):
        kind = match.lastgroup
        value = match.group()
        pos = match.start()
        if kind == "space":
            continue
        if kind == "other":
            reason = _REFUSED_CHARS.get(value, f"unexpected character {value!r}")
            raise Refused(f"{reason} (at position {pos + 1})")
        if kind == "op" and value in ("&&", "||", "!"):
            word = {"&&": "and", "||": "or", "!": "not"}[value]
            raise Refused(f"FreeCAD has no {value} ({word}) operator")
        if kind == "number":
            rest = text[match.end():]
            if re.match(r"[eE][-+]?\d", rest):
                raise Refused(f"exponent notation ({value}{rest[:3]}...): {UNDOCUMENTED}")
        tokens.append(Token(kind, value, pos))
    tokens.append(Token("end", "", len(text)))
    return tokens


# --- The tree --------------------------------------------------------------------------------

@dataclass(frozen=True)
class Num:
    text: str

    @property
    def is_int(self) -> bool:
        return self.text.isdigit()


@dataclass(frozen=True)
class Qty:
    """A number followed by a unit: `10mm`, `10 mm`."""

    num: Num
    unit: str


@dataclass(frozen=True)
class Frac:
    """An integer fraction followed by a unit, as a term of its own: `3/4 in`, `-3/4 in`."""

    negative: bool
    num: Num
    den: Num
    unit: str


@dataclass(frozen=True)
class WithUnit:
    """A unit after a group or a call: `(3/4) in`, `sqrt(16) m`."""

    node: object
    unit: str


@dataclass(frozen=True)
class Ref:
    name: str


@dataclass(frozen=True)
class Const:
    name: str


@dataclass(frozen=True)
class Bool:
    value: bool


@dataclass(frozen=True)
class Group:
    node: object


@dataclass(frozen=True)
class Unary:
    op: str
    node: object


@dataclass(frozen=True)
class Bin:
    op: str
    left: object
    right: object


@dataclass(frozen=True)
class Call:
    name: str
    args: Tuple[object, ...]


@dataclass(frozen=True)
class Cond:
    cond: object
    then: object
    other: object


_COMPARISONS = ("==", "!=", "<", ">", "<=", ">=")


class _Parser:
    def __init__(self, text: str):
        self.text = text
        self.tokens = tokenize(text)
        self.index = 0

    def peek(self) -> Token:
        return self.tokens[self.index]

    def take(self) -> Token:
        token = self.tokens[self.index]
        self.index += 1
        return token

    def at_op(self, *ops: str) -> bool:
        token = self.peek()
        return token.kind == "op" and token.text in ops

    def expect(self, op: str):
        token = self.take()
        if token.kind != "op" or token.text != op:
            raise Refused(f"expected {op!r} at position {token.pos + 1}{self.found(token)}")

    @staticmethod
    def found(token: Token) -> str:
        return ", found the end" if token.kind == "end" else f", found {token.text!r}"

    def parse(self):
        if self.peek().kind == "end":
            raise Refused("the expression is empty")
        node = self.ternary()
        token = self.peek()
        if token.kind != "end":
            raise Refused(f"unexpected {token.text!r} at position {token.pos + 1}")
        return node

    def ternary(self):
        cond = self.comparison()
        if not self.at_op("?"):
            return cond
        self.take()
        then = self.ternary()
        self.expect(":")
        other = self.ternary()
        return Cond(cond, then, other)

    def comparison(self):
        left = self.additive()
        if self.at_op(*_COMPARISONS):
            op = self.take().text
            right = self.additive()
            if self.at_op(*_COMPARISONS):
                raise Refused(f"chained comparisons (a < b < c): {UNDOCUMENTED}")
            return Bin(op, left, right)
        return left

    def additive(self):
        node = self.term()
        while self.at_op("+", "-"):
            op = self.take().text
            node = Bin(op, node, self.term())
        return node

    def term(self):
        factors = [self.unary()]
        ops = []
        while self.at_op("*", "/", "%"):
            ops.append(self.take().text)
            factors.append(self.unary())
        return _fold_term(factors, ops)

    def unary(self):
        if self.at_op("-", "+"):
            op = self.take().text
            operand = self.unary()
            if op == "-" and isinstance(operand, Bin) and operand.op == "^":
                raise Refused(f"a minus before ^ (-2^2): {UNDOCUMENTED}")
            return Unary(op, operand)
        return self.power()

    def power(self):
        base = self.postfix()
        if not self.at_op("^"):
            return base
        if isinstance(base, (Qty, WithUnit)):
            # `2 mm^2` is (2 mm)^2 or 2 (mm^2), and Onshape's docs don't say which
            unit = base.unit
            raise Refused(f"a unit before ^ ({unit}^): {UNDOCUMENTED}; write (2 {unit})^2 for "
                          "a squared value")
        self.take()
        exponent = self.unary()
        if isinstance(exponent, Bin) and exponent.op == "^":
            raise Refused(f"chained ^ (a^b^c): {UNDOCUMENTED}")
        return Bin("^", base, exponent)

    def postfix(self):
        node = self.primary()
        token = self.peek()
        if token.kind == "name" and token.text in UNITS:
            if isinstance(node, Num):
                self.take()
                node = Qty(node, token.text)
            elif isinstance(node, (Group, Call)):
                self.take()
                node = WithUnit(node, token.text)
            else:
                raise Refused(f"a unit after {self.text_of(node)} ({token.text}): {UNDOCUMENTED}")
            after = self.peek()
            if after.kind == "name" and after.text in UNITS:
                raise Refused(f"two units in a row ({token.text} {after.text})")
        elif (token.kind == "name" and isinstance(node, Num) and token.text not in CONSTANTS
              and token.text not in FUNCTIONS and token.text not in REFUSED_FUNCTIONS):
            raise Refused(f"unknown unit {token.text!r}")
        return node

    @staticmethod
    def text_of(node) -> str:
        if isinstance(node, Ref):
            return f"#{node.name}"
        if isinstance(node, Const):
            return node.name
        if isinstance(node, Qty):
            return f"{node.num.text} {node.unit}"
        return "a value"

    def primary(self):
        token = self.take()
        if token.kind == "number":
            return Num(token.text)
        if token.kind == "ref":
            return Ref(token.text[1:])
        if token.kind == "op" and token.text == "(":
            node = self.ternary()
            self.expect(")")
            return Group(node)
        if token.kind == "name":
            name = token.text
            if self.at_op("("):
                self.take()
                args = []
                if not self.at_op(")"):
                    args.append(self.ternary())
                    while self.at_op(","):
                        self.take()
                        args.append(self.ternary())
                self.expect(")")
                if name in REFUSED_FUNCTIONS:
                    raise Refused(REFUSED_FUNCTIONS[name])
                if name not in FUNCTIONS:
                    raise Refused(f"unknown function {name}()")
                return Call(name, tuple(args))
            if name in CONSTANTS:
                return Const(name)
            if name in ("true", "false"):
                return Bool(name == "true")
            if name in UNITS:
                raise Refused(f"a unit ({name}) needs a number before it")
            raise Refused(f"unknown name {name!r} (a variable is written #{name})")
        if token.kind == "end":
            raise Refused("the expression ends too early")
        raise Refused(f"unexpected {token.text!r} at position {token.pos + 1}")


def _number_literal(node) -> Optional[Tuple[bool, Num]]:
    """(negative, number) for a bare number literal, possibly signed; else None."""
    if isinstance(node, Num):
        return False, node
    if isinstance(node, Unary) and isinstance(node.node, Num):
        return node.op == "-", node.node
    return None


def _fold_term(factors: list, ops: list):
    """A product of factors, with the fraction-literal rule (section 2.4)."""
    if len(factors) == 2 and ops[0] == "/" and isinstance(factors[1], Qty):
        literal = _number_literal(factors[0])
        if literal is not None:
            negative, num = literal
            den = factors[1].num
            if num.is_int and den.is_int:
                return Frac(negative, num, den, factors[1].unit)
            raise Refused(f"a fraction of decimals with a unit ({num.text}/{den.text} "
                          f"{factors[1].unit}): {UNDOCUMENTED}")
    for i, op in enumerate(ops, start=1):
        if (op == "/" and _number_literal(factors[i - 1]) is not None
                and isinstance(factors[i], Qty)):
            raise Refused(f"a fraction with a unit next to *, / or ^: {UNDOCUMENTED}")
    node = factors[0]
    for op, factor in zip(ops, factors[1:]):
        node = Bin(op, node, factor)
    return node


def parse(text: str):
    """The tree of an Onshape expression; raises Refused."""
    return _Parser(text).parse()


def references(node) -> List[str]:
    """The `#names` a tree uses, each once, in order."""
    found: List[str] = []

    def walk(n):
        if isinstance(n, Ref):
            if n.name not in found:
                found.append(n.name)
        elif isinstance(n, (Group, Unary, WithUnit)):
            walk(n.node)
        elif isinstance(n, Bin):
            walk(n.left)
            walk(n.right)
        elif isinstance(n, Call):
            for arg in n.args:
                walk(arg)
        elif isinstance(n, Cond):
            walk(n.cond)
            walk(n.then)
            walk(n.other)

    walk(node)
    return found


# --- Writing FreeCAD text --------------------------------------------------------------------

def _number_text(num: Num) -> str:
    text = num.text
    if text.startswith("."):
        text = "0" + text
    if text.endswith("."):
        text += "0"
    return text


def write(node, resolve_text: Callable[[str], str], top: bool = True) -> str:
    """The FreeCAD expression of a tree, fully parenthesized (the outermost operation bare)."""

    def w(n):
        return write(n, resolve_text, top=False)

    if isinstance(node, Num):
        return _number_text(node)
    if isinstance(node, Qty):
        return f"({_number_text(node.num)} * 1 {UNITS[node.unit][2]})"
    if isinstance(node, Frac):
        sign = "-" if node.negative else ""
        return (f"({sign}{_number_text(node.num)} / {_number_text(node.den)} "
                f"* 1 {UNITS[node.unit][2]})")
    if isinstance(node, WithUnit):
        return f"({w(node.node)} * 1 {UNITS[node.unit][2]})"
    if isinstance(node, Ref):
        return resolve_text(node.name)
    if isinstance(node, Const):
        return "pi"
    if isinstance(node, Bool):
        return "true" if node.value else "false"
    if isinstance(node, Group):
        return write(node.node, resolve_text, top)
    if isinstance(node, Unary):
        inner = w(node.node)
        return inner if node.op == "+" else f"(-{inner})"
    if isinstance(node, Bin):
        text = f"{w(node.left)} {node.op} {w(node.right)}"
        return text if top else f"({text})"
    if isinstance(node, Call):
        return f"{node.name}({', '.join(w(arg) for arg in node.args)})"
    if isinstance(node, Cond):
        text = f"{w(node.cond)} ? {w(node.then)} : {w(node.other)}"
        return text if top else f"({text})"
    raise TypeError(node)


# --- The reference evaluator -----------------------------------------------------------------

Value = Union[Quantity, bool]


def _quantity(value: Value, what: str) -> Quantity:
    if isinstance(value, bool):
        raise Refused(f"{what} is a comparison (true or false), not a value")
    return value


def evaluate(node, resolve_value: Callable[[str], Quantity]) -> Value:
    """The value of a tree by Onshape's rules as this module reads them; raises Refused.

    Every step's value must be finite: an overflow, a zero to a negative power or an infinity
    on the way (`10^300 * 10^300 > 1`) is refused, not passed on as an exception or a value."""
    try:
        value = _evaluate(node, resolve_value)
    except (ArithmeticError, ValueError) as e:
        raise Refused(f"the value can't be computed ({e})") from None
    if isinstance(value, Quantity) and not math.isfinite(value.value):
        raise Refused(f"the value can't be computed (it is {value.value})")
    return value


def _evaluate(node, resolve_value: Callable[[str], Quantity]) -> Value:
    def ev(n):
        return evaluate(n, resolve_value)

    if isinstance(node, Num):
        return Quantity(float(node.text))
    if isinstance(node, Qty):
        factor, dims, _symbol = UNITS[node.unit]
        return Quantity(float(node.num.text) * factor, dims)
    if isinstance(node, Frac):
        factor, dims, _symbol = UNITS[node.unit]
        if int(node.den.text) == 0:
            raise Refused("division by zero")
        value = int(node.num.text) / int(node.den.text) * factor
        return Quantity(-value if node.negative else value, dims)
    if isinstance(node, WithUnit):
        inner = _quantity(ev(node.node), "the value before a unit")
        if inner.dims != NONE:
            raise Refused(f"a unit ({node.unit}) after a value that has one already")
        factor, dims, _symbol = UNITS[node.unit]
        return Quantity(inner.value * factor, dims)
    if isinstance(node, Ref):
        return resolve_value(node.name)
    if isinstance(node, Const):
        return Quantity(CONSTANTS[node.name])
    if isinstance(node, Bool):
        return node.value
    if isinstance(node, Group):
        return ev(node.node)
    if isinstance(node, Unary):
        operand = _quantity(ev(node.node), f"the operand of {node.op}")
        return operand if node.op == "+" else Quantity(-operand.value, operand.dims)
    if isinstance(node, Bin):
        return _binary(node.op, ev(node.left), ev(node.right))
    if isinstance(node, Call):
        return _call(node.name, [ev(arg) for arg in node.args])
    if isinstance(node, Cond):
        cond = ev(node.cond)
        if not isinstance(cond, bool):
            raise Refused("the condition before ? must be a comparison")
        then = _quantity(ev(node.then), "the value after ?")
        other = _quantity(ev(node.other), "the value after :")
        if then.dims != other.dims:
            raise Refused(f"the two values of ?: differ: {describe_dims(then.dims)} and "
                          f"{describe_dims(other.dims)}")
        return then if cond else other
    raise TypeError(node)


def _binary(op: str, left: Value, right: Value) -> Value:
    a = _quantity(left, f"the left operand of {op}")
    b = _quantity(right, f"the right operand of {op}")
    if op in ("+", "-") + _COMPARISONS:
        if a.dims != b.dims:
            if NONE in (a.dims, b.dims):
                raise Refused(f"a quantity {op} a bare number (#a {op} 2): give the number a "
                              "unit; Onshape rejects it too")
            raise Refused(f"{describe_dims(a.dims)} {op} {describe_dims(b.dims)}")
        if op == "+":
            return Quantity(a.value + b.value, a.dims)
        if op == "-":
            return Quantity(a.value - b.value, a.dims)
        return {"==": a.value == b.value, "!=": a.value != b.value, "<": a.value < b.value,
                ">": a.value > b.value, "<=": a.value <= b.value, ">=": a.value >= b.value}[op]
    if op == "*":
        return Quantity(a.value * b.value, (a.dims[0] + b.dims[0], a.dims[1] + b.dims[1]))
    if op == "/":
        if b.value == 0:
            raise Refused("division by zero")
        return Quantity(a.value / b.value, (a.dims[0] - b.dims[0], a.dims[1] - b.dims[1]))
    if op == "%":
        if a.dims != NONE or b.dims != NONE:
            raise Refused(f"% with units: {UNDOCUMENTED}")
        if a.value < 0 or b.value <= 0:
            raise Refused(f"% of a negative number: {UNDOCUMENTED}")
        return Quantity(math.fmod(a.value, b.value))
    if op == "^":
        if b.dims != NONE:
            raise Refused("an exponent can't have a unit")
        if a.dims == NONE:
            if a.value < 0 and b.value != int(b.value):
                raise Refused("a negative number to a fractional power")
            return Quantity(a.value ** b.value)
        if abs(b.value - round(b.value)) > 1e-9:
            raise Refused("a value with a unit needs a whole exponent")
        n = int(round(b.value))
        return Quantity(a.value ** n, (a.dims[0] * n, a.dims[1] * n))
    raise TypeError(op)


def _call(name: str, args: List[Value]) -> Quantity:
    def count(n):
        if len(args) != n:
            raise Refused(f"{name}() takes {n} argument{'s' if n > 1 else ''}, not {len(args)}")

    values = [_quantity(arg, f"an argument of {name}()") for arg in args]
    if name in ("sin", "cos", "tan"):
        count(1)
        x = values[0]
        if x.dims == NONE:
            radians = math.radians(x.value)  # unitless trig arguments are degrees in both
        elif x.dims == ANGLE:
            radians = x.value
        else:
            raise Refused(f"{name}() of {describe_dims(x.dims)}")
        return Quantity(getattr(math, name)(radians))
    if name in ("asin", "acos", "atan"):
        count(1)
        x = values[0]
        if x.dims != NONE:
            raise Refused(f"{name}() of {describe_dims(x.dims)}")
        if name != "atan" and abs(x.value) > 1:
            raise Refused(f"{name}({x.value:g}) is undefined")
        return Quantity(getattr(math, name)(x.value), ANGLE)
    if name == "atan2":
        count(2)
        y, x = values
        if y.dims != x.dims:
            raise Refused(f"atan2() of {describe_dims(y.dims)} and {describe_dims(x.dims)}")
        return Quantity(math.atan2(y.value, x.value), ANGLE)
    if name in ("exp", "log", "log10", "sinh", "cosh", "tanh"):
        count(1)
        x = values[0]
        if x.dims != NONE:
            raise Refused(f"{name}() of {describe_dims(x.dims)}")
        if name in ("log", "log10") and x.value <= 0:
            raise Refused(f"{name}({x.value:g}) is undefined")
        return Quantity(getattr(math, name)(x.value))
    if name in ("floor", "ceil"):
        count(1)
        x = values[0]
        if x.dims != NONE:
            raise Refused(f"{name}() of a value with a unit depends on the unit it is counted in: "
                          f"{UNDOCUMENTED}")
        return Quantity(float(getattr(math, name)(x.value)))
    if name == "sqrt":
        count(1)
        x = values[0]
        if x.dims[0] % 2 or x.dims[1] % 2:
            raise Refused(f"sqrt() of {describe_dims(x.dims)}")
        if x.value < 0:
            raise Refused("sqrt() of a negative value")
        return Quantity(math.sqrt(x.value), (x.dims[0] // 2, x.dims[1] // 2))
    if name == "abs":
        count(1)
        return Quantity(abs(values[0].value), values[0].dims)
    if name in ("min", "max"):
        if len(values) < 2:
            raise Refused(f"{name}() takes at least two arguments")
        if len({v.dims for v in values}) > 1:
            raise Refused(f"{name}() of values with different units")
        pick = min if name == "min" else max
        return Quantity(pick(v.value for v in values), values[0].dims)
    raise Refused(f"unknown function {name}()")


# --- One variable ----------------------------------------------------------------------------

@dataclass(frozen=True)
class Translation:
    text: str  # the FreeCAD expression
    value: Quantity  # the translator's own value
    property_type: str  # e.g. "App::PropertyDistance"


def translate(expression: str, onshape_type: str,
              resolve: Callable[[str], Tuple[str, Quantity]],
              default_units: Optional[Mapping[str, str]] = None) -> Translation:
    """One Onshape expression of a variable of @a onshape_type, as FreeCAD text and a value.

    @a resolve maps a `#name` to (FreeCAD text, value) and raises Refused when it can't.
    @a default_units maps "LENGTH" / "ANGLE" to the Onshape document's default unit, which a
    unitless result of that type then takes explicitly (`5` becomes `5 * 1 in`); without it such
    a result is refused, since the export doesn't say what the default was.
    """
    if onshape_type == "ANY":
        raise Refused("Any variables aren't supported yet")
    if onshape_type not in TYPES:
        raise Refused(f"unknown variable type {onshape_type!r} (known: {', '.join(TYPES)})")
    property_type, dims = TYPES[onshape_type]
    tree = parse(expression)
    value = evaluate(tree, lambda name: resolve(name)[1])
    value = _quantity(value, "the expression")
    text = write(tree, lambda name: resolve(name)[0])
    if value.dims == NONE and dims != NONE:
        if _has_units(tree, lambda name: resolve(name)[1]):
            raise Refused(f"the expression is a number (its units cancel), but the variable is "
                          f"{describe_dims(dims)} ({onshape_type})")
        unit = (default_units or {}).get(onshape_type)
        if not unit:
            raise Refused(f"the expression has no unit, and a {onshape_type.lower()} without one "
                          "takes the Onshape document's default unit, which the export doesn't "
                          "record: set the default unit")
        factor, unit_dims, symbol = UNITS[unit]
        if unit_dims != dims:
            raise Refused(f"the default unit {unit} isn't {describe_dims(dims)}")
        text = f"{text} * 1 {symbol}" if isinstance(tree, Num) else f"({text}) * 1 {symbol}"
        value = Quantity(value.value * factor, dims)
        if not math.isfinite(value.value):
            raise Refused(f"the value can't be computed (it is {value.value})")
    if value.dims != dims:
        raise Refused(f"the expression is {describe_dims(value.dims)}, but the variable is "
                      f"{describe_dims(dims)} ({onshape_type})")
    return Translation(text, value, property_type)


def _has_units(node, resolve_value: Callable[[str], Quantity]) -> bool:
    """Whether a unit takes part anywhere: a literal one, a reference to a value with one, or an
    inverse trig function (an angle). Only an expression without any takes the default unit."""
    if isinstance(node, (Qty, Frac, WithUnit)):
        return True
    if isinstance(node, Ref):
        return resolve_value(node.name).dims != NONE
    if isinstance(node, Call) and node.name in ("asin", "acos", "atan", "atan2"):
        return True
    children = []
    if isinstance(node, (Group, Unary)):
        children = [node.node]
    elif isinstance(node, Bin):
        children = [node.left, node.right]
    elif isinstance(node, Call):
        children = list(node.args)
    elif isinstance(node, Cond):
        children = [node.cond, node.then, node.other]
    return any(_has_units(child, resolve_value) for child in children)


def values_agree(a: float, b: float) -> bool:
    """Equal within the import's tolerance (absolute 1e-12 plus relative 1e-9, in SI units)."""
    return abs(a - b) <= 1e-12 + 1e-9 * max(abs(a), abs(b))


# --- The export file -------------------------------------------------------------------------

@dataclass(frozen=True)
class Variable:
    type: str
    name: str
    value: object  # null in every export seen
    description: str
    expression: str


@dataclass(frozen=True)
class StudioEntry:
    reference: object  # `variableStudioReference`, null in every export seen
    variables: Tuple[Variable, ...]


_VARIABLE_KEYS = {"type", "name", "value", "description", "expression"}
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def parse_export(text: Union[str, bytes]) -> List[StudioEntry]:
    """The studio entries of an export's JSON text; raises ExportError."""
    try:
        data = json.loads(text)
    except ValueError as e:
        raise ExportError(f"not JSON: {e}") from None
    if not isinstance(data, list):
        raise ExportError("an export is a JSON array of studio entries")
    entries = []
    for i, entry in enumerate(data, start=1):
        if not isinstance(entry, dict) or not isinstance(entry.get("variables"), list):
            raise ExportError(f"studio entry {i} has no list of variables")
        variables = []
        for j, var in enumerate(entry["variables"], start=1):
            where = f"variable {j} of studio entry {i}"
            if not isinstance(var, dict) or set(var) != _VARIABLE_KEYS:
                raise ExportError(f"{where} doesn't have exactly the keys "
                                  f"{', '.join(sorted(_VARIABLE_KEYS))}")
            for key in ("type", "name", "expression"):
                if not isinstance(var[key], str):
                    raise ExportError(f"{where}: {key} isn't text")
            if not _NAME.match(var["name"]):
                raise ExportError(f"{where}: {var['name']!r} isn't a variable name")
            description = var["description"]
            if description is None:
                description = ""
            if not isinstance(description, str):
                raise ExportError(f"{where}: description isn't text")
            variables.append(Variable(var["type"], var["name"], var["value"], description,
                                      var["expression"]))
        entries.append(StudioEntry(entry.get("variableStudioReference"), tuple(variables)))
    return entries


def read_export(path: str) -> List[StudioEntry]:
    with open(path, "rb") as f:
        return parse_export(f.read())


# --- Whole exports ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Binding:
    """What a name no imported file defines stands for: a document variable's path and value,
    or a value the user entered (section 2.6)."""

    text: str
    value: Quantity


@dataclass
class VariableResult:
    entry: int  # index of its studio entry
    variable: Variable
    freecad_name: str
    translation: Optional[Translation] = None
    refusal: Optional[str] = None
    # names it needs, directly or through others, that nothing resolves yet
    needs: List[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.variable.name


@dataclass
class ExportTranslation:
    variables: List[VariableResult]
    # a name nothing defines -> the variables that use it directly
    unresolved: Dict[str, List[str]]
    # a name two entries define -> those entries' indexes; the caller picks one (`providers`)
    ambiguous: Dict[str, List[int]]

    def result(self, name: str, entry: Optional[int] = None) -> VariableResult:
        for result in self.variables:
            if result.name == name and (entry is None or result.entry == entry):
                return result
        raise KeyError(name)


def translate_export(entries: Sequence[StudioEntry], *,
                     containers: Optional[Sequence[str]] = None,
                     name_map: Optional[Mapping[str, str]] = None,
                     bindings: Optional[Mapping[str, Binding]] = None,
                     providers: Optional[Mapping[str, int]] = None,
                     default_units: Optional[Mapping[str, str]] = None) -> ExportTranslation:
    """Every variable of one or more exports' entries, translated in dependency order.

    Each entry becomes its own copy, named by @a containers (default `Studio1`, `Studio2`, ...):
    a reference to a sibling is written as its bare FreeCAD name, one to another entry's variable
    as `Container.Name`. @a name_map renames variables (Onshape name -> FreeCAD name; unit names
    such as `t` need it, checked by the import). @a bindings resolve names no entry defines,
    @a providers pick the entry that provides a name several entries define. Whatever stays
    unresolved is listed, and the variables that need it carry it in `needs` and aren't
    translated: nothing is guessed.
    """
    containers = list(containers) if containers else [f"Studio{i + 1}" for i in range(len(entries))]
    name_map = dict(name_map or {})
    bindings = dict(bindings or {})
    providers = dict(providers or {})

    results: List[VariableResult] = []
    defined: Dict[str, List[int]] = {}
    by_key: Dict[Tuple[int, str], VariableResult] = {}
    for index, entry in enumerate(entries):
        for var in entry.variables:
            result = VariableResult(index, var, name_map.get(var.name, var.name))
            results.append(result)
            if (index, var.name) in by_key:
                result.refusal = f"{var.name} is defined twice in studio entry {index + 1}"
                by_key[(index, var.name)].refusal = result.refusal
                continue
            by_key[(index, var.name)] = result
            if index not in defined.setdefault(var.name, []):
                defined[var.name].append(index)

    ambiguous = {name: idx for name, idx in defined.items()
                 if len(idx) > 1 and providers.get(name) not in idx}

    def provider(name: str, user_entry: int) -> Optional[VariableResult]:
        """The variable @a name stands for in @a user_entry, or None (a binding, or nothing)."""
        if (user_entry, name) in by_key:
            return by_key[(user_entry, name)]
        idx = defined.get(name, [])
        if len(idx) == 1:
            return by_key[(idx[0], name)]
        if name in providers and providers[name] in idx:
            return by_key[(providers[name], name)]
        return None

    trees: Dict[int, object] = {}
    unresolved: Dict[str, List[str]] = {}
    for result in results:
        if result.refusal:
            continue
        if not result.variable.expression.strip():
            result.refusal = "the expression is empty: enter a value"
            continue
        try:
            trees[id(result)] = parse(result.variable.expression)
        except Refused as e:
            result.refusal = str(e)
            continue
        for name in references(trees[id(result)]):
            if provider(name, result.entry) is None and name not in bindings:
                unresolved.setdefault(name, [])
                if result.name not in unresolved[name]:
                    unresolved[name].append(result.name)

    state: Dict[int, str] = {}  # id -> "busy" / "done"

    def solve(result: VariableResult, chain: List[str]):
        key = id(result)
        if state.get(key) == "done":
            return
        if state.get(key) == "busy":
            cycle = chain[chain.index(result.name):] + [result.name]
            raise Refused("refers to itself through " + " -> ".join(f"#{n}" for n in cycle))
        state[key] = "busy"
        try:
            _solve(result, chain + [result.name])
        finally:
            state[key] = "done"

    def _solve(result: VariableResult, chain: List[str]):
        if result.refusal or id(result) not in trees:
            return
        tree = trees[id(result)]
        needs: List[str] = []
        for name in references(tree):
            source = provider(name, result.entry)
            if source is None:
                if name not in bindings:
                    needs.append(name)
                continue
            try:
                solve(source, chain)
            except Refused as e:
                result.refusal = str(e)
                return
            for need in source.needs:
                if need not in needs:
                    needs.append(need)
            if source.translation is None and not source.needs:
                result.refusal = f"#{name} isn't translated: {source.refusal}"
                return
        if needs:
            result.needs = needs
            return

        def resolve(name: str) -> Tuple[str, Quantity]:
            source = provider(name, result.entry)
            if source is None:
                binding = bindings[name]
                return binding.text, binding.value
            if source.entry == result.entry:
                return source.freecad_name, source.translation.value
            return f"{containers[source.entry]}.{source.freecad_name}", source.translation.value

        try:
            translation = translate(result.variable.expression, result.variable.type, resolve,
                                    default_units)
        except Refused as e:
            result.refusal = str(e)
            return
        exported = _exported_value(result.variable)
        if exported is not None and exported.dims == NONE and translation.value.dims != NONE:
            exported = None  # a bare number: its unit isn't known
        if exported is not None and not (exported.dims == translation.value.dims
                                         and values_agree(exported.value,
                                                          translation.value.value)):
            result.refusal = (f"the export's value {result.variable.value!r} disagrees with the "
                              f"expression's ({translation.value.value:g} in SI units)")
            return
        result.translation = translation

    for result in results:
        try:
            solve(result, [])
        except Refused as e:
            if not result.refusal:
                result.refusal = str(e)
    return ExportTranslation(results, unresolved, ambiguous)


def _exported_value(var: Variable) -> Optional[Quantity]:
    """The export's `value` as a quantity, when it holds a finite one (null in every export
    seen)."""
    if var.value is None or isinstance(var.value, bool):
        return None
    if isinstance(var.value, (int, float)):
        try:
            number = float(var.value)
        except OverflowError:  # a whole number beyond any float
            return None
        return Quantity(number) if math.isfinite(number) else None
    if not isinstance(var.value, str):
        return None
    try:
        value = evaluate(parse(var.value), _no_reference)
    except Refused:
        return None
    return value if isinstance(value, Quantity) else None


def _no_reference(name: str) -> Quantity:
    raise Refused(f"#{name} in a value")
