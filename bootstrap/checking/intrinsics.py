from dataclasses import dataclass

import format
from format import Formattable, Formatter
from parsing.types import I8, I32, I64, PrimitiveType
from resolving.types import PtrType, Type
from lexer import Token

@dataclass
class IntrinsicAdd(Formattable):
    token: Token
    taip: PtrType | I8 | I32 | I64
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Intrinsic", [
            self.token, format.UnnamedRecord("Add", [self.taip])])

@dataclass
class IntrinsicSub(Formattable):
    token: Token
    taip: PtrType | I8 | I32 | I64

@dataclass
class IntrinsicDrop(Formattable):
    token: Token
    taip: Type
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Intrinsic", [
            self.token, format.UnnamedRecord("Drop", [self.taip])])

@dataclass
class IntrinsicMod(Formattable):
    token: Token
    taip: I32 | I64
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Intrinsic", [
            self.token, format.UnnamedRecord("Mod", [self.taip])])

@dataclass
class IntrinsicMul(Formattable):
    token: Token
    taip: I32 | I64

@dataclass
class IntrinsicDiv(Formattable):
    token: Token
    taip: I32 | I64

@dataclass
class IntrinsicAnd(Formattable):
    token: Token
    taip: PrimitiveType

@dataclass
class IntrinsicOr(Formattable):
    token: Token
    taip: Type

@dataclass
class IntrinsicShl(Formattable):
    token: Token
    taip: Type

@dataclass
class IntrinsicShr(Formattable):
    token: Token
    taip: Type

@dataclass
class IntrinsicRotr(Formattable):
    token: Token
    taip: Type

@dataclass
class IntrinsicRotl(Formattable):
    token: Token
    taip: Type

@dataclass
class IntrinsicGreater(Formattable):
    token: Token
    taip: I8 | I32 | I64

@dataclass
class IntrinsicLess(Formattable):
    token: Token
    taip: I8 | I32 | I64

@dataclass
class IntrinsicGreaterEq(Formattable):
    token: Token
    taip: I8 | I32 | I64

@dataclass
class IntrinsicLessEq(Formattable):
    token: Token
    taip: I8 | I32 | I64

@dataclass
class IntrinsicMemCopy(Formattable):
    token: Token

@dataclass
class IntrinsicMemFill(Formattable):
    token: Token

@dataclass
class IntrinsicEqual(Formattable):
    token: Token
    taip: Type
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Intrinsic", [
            self.token,
            format.UnnamedRecord("Eq", [self.taip])])

@dataclass
class IntrinsicNotEqual(Formattable):
    token: Token
    taip: Type

@dataclass
class IntrinsicFlip(Formattable):
    token: Token
    lower: Type
    upper: Type

@dataclass
class IntrinsicMemGrow(Formattable):
    token: Token

@dataclass
class IntrinsicSetStackSize(Formattable):
    token: Token

@dataclass
class IntrinsicStore(Formattable):
    token: Token
    taip: Type

@dataclass
class IntrinsicNot(Formattable):
    token: Token
    taip: PrimitiveType

@dataclass
class IntrinsicUninit(Formattable):
    token: Token
    taip: Type

IntrinsicWord = (
      IntrinsicAdd
    | IntrinsicSub
    | IntrinsicDrop
    | IntrinsicMod
    | IntrinsicMul
    | IntrinsicDiv
    | IntrinsicAnd
    | IntrinsicOr
    | IntrinsicShl
    | IntrinsicShr
    | IntrinsicRotl
    | IntrinsicRotr
    | IntrinsicGreater
    | IntrinsicLess
    | IntrinsicGreaterEq
    | IntrinsicLessEq
    | IntrinsicMemCopy
    | IntrinsicMemFill
    | IntrinsicEqual
    | IntrinsicNotEqual
    | IntrinsicFlip
    | IntrinsicMemGrow
    | IntrinsicStore
    | IntrinsicNot
    | IntrinsicUninit
    | IntrinsicSetStackSize
)
