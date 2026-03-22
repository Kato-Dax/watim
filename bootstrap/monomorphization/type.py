from typing import Tuple
from dataclasses import dataclass

from format import Formattable, Formatter
import format

from lexer import Token

from parsing.types import Bool, I8, I32, I64
from resolving.types import CustomTypeHandle

@dataclass(frozen=True, eq=True)
class TypeId(Formattable):
    index: int

    def format(self, fmt: Formatter):
        fmt.unnamed_record("TypeId", [self.index])

@dataclass(frozen=True, eq=True)
class NamedTypeId(Formattable):
    name: Token
    taip: TypeId
    def format(self, fmt: Formatter):
        fmt.unnamed_record("NamedTypeId", [self.name, self.taip])

@dataclass(frozen=True)
class CustomTypeType(Formattable):
    handle: CustomTypeHandle
    def format(self, fmt: Formatter):
        fmt.unnamed_record("CustomType", [self.handle.module, self.handle.index])

type Type = Bool | I8 | I32 | I64 | PtrType | CustomTypeType | FunType

@dataclass(frozen=True, eq=True)
class PtrType(Formattable):
    child: TypeId
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Ptr", [self.child])

@dataclass(frozen=True, eq=True)
class Struct(Formattable):
    name: Token
    fields: Tuple[NamedTypeId, ...]
    def format(self, fmt: Formatter):
        fmt.named_record("Struct", [("name", self.name), ("fields", format.Seq(self.fields, multi_line=True))])

@dataclass(frozen=True, eq=True)
class VariantCase(Formattable):
    name: Token
    taip: TypeId | None
    def format(self, fmt: Formatter):
        fmt.unnamed_record("VariantCase", [self.name, format.Optional(self.taip)])

@dataclass(frozen=True)
class Variant(Formattable):
    name: Token
    cases: Tuple[VariantCase, ...]
    def format(self, fmt: Formatter):
        fmt.named_record("Variant", [
            ("name", self.name),
            ("cases", format.Seq(self.cases, multi_line=True))])

type TypeDefinition = Struct | Variant

@dataclass(frozen=True, eq=True)
class FunType(Formattable):
    parameters: Tuple[TypeId, ...]
    returns: Tuple[TypeId, ...]
    def format(self, fmt: Formatter):
        fmt.unnamed_record("FunType", [self.parameters, self.returns])

