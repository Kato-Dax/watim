from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import format
from format import Formattable, Formatter
from lexer import Token

import resolving.type_without_holes as without_holes
from resolving.types import CustomTypeHandle, NamedType
from resolving.words import FunctionHandle, LocalId, Scope

type TopItem = Import | Struct | Variant | Extern | Function
type TypeDefinition = Struct | Variant

@dataclass
class StructImport(Formattable):
    name: Token
    handle: CustomTypeHandle
    def format(self, fmt: Formatter):
        fmt.unnamed_record("StructImport", [self.name, self.handle])

@dataclass
class VariantImport(Formattable):
    name: Token
    handle: CustomTypeHandle
    constructors: tuple[int, ...]
    def format(self, fmt: Formatter):
        fmt.unnamed_record("VariantImport", [
            self.name,
            self.handle,
            format.Seq(self.constructors)])

@dataclass
class FunctionImport(Formattable):
    name: Token
    handle: FunctionHandle
    def format(self, fmt: Formatter):
        fmt.unnamed_record("FunctionImport", [self.name, self.handle])

type ImportItem = VariantImport | FunctionImport | StructImport

@dataclass
class Import(Formattable):
    token: Token
    file_path: str
    qualifier: Token
    module: int
    items: tuple[ImportItem, ...]
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Import", [
            self.token,
            self.module,
            format.Str(self.file_path),
            self.qualifier,
            format.Seq(self.items, multi_line=True)])

@dataclass
class Struct(Formattable):
    name: Token
    generic_parameters: tuple[Token, ...]
    fields: tuple[without_holes.NamedType, ...]
    def format(self, fmt: Formatter):
        fmt.named_record("Struct", [
            ("name", self.name),
            ("generic-parameters", format.Seq(self.generic_parameters)),
            ("fields", format.Seq(self.fields, multi_line=True))])

@dataclass
class VariantCase(Formattable):
    name: Token
    taip: without_holes.Type | None
    def format(self, fmt: Formatter):
        fmt.unnamed_record("VariantCase", [self.name, format.Optional(self.taip)])

@dataclass
class Variant(Formattable):
    name: Token
    generic_parameters: tuple[Token, ...]
    cases: tuple[VariantCase, ...]
    def format(self, fmt: Formatter):
        fmt.named_record("Variant", [
            ("name", self.name),
            ("generic-parameters", format.Seq(self.generic_parameters)),
            ("cases", format.Seq(self.cases, multi_line=True))])

@dataclass(frozen=True)
class MustBeOneOf:
    generic: int
    allowed: set[without_holes.Type | Literal["AnyPtr"]]
    def format(self, fmt: Formatter):
        return fmt.unnamed_record("MustBeOneOf", [self.generic, format.Seq(self.allowed)])

@dataclass(frozen=True)
class MustSatisfyPredicate(Formattable):
    name: str
    description: str
    predicate: Callable[[tuple[without_holes.Type | None, ...]], str | None]
    def format(self, fmt: Formatter):
        return fmt.unnamed_record("MustSatisfyPredicate", [self.name])

type ConstraintOnGeneric = MustBeOneOf | MustSatisfyPredicate

@dataclass
class FunctionSignature(Formattable):
    generic_parameters: tuple[Token, ...]
    parameters: tuple[without_holes.NamedType, ...]
    returns: tuple[without_holes.Type, ...]
    constraints: tuple[ConstraintOnGeneric, ...] = ()
    def format(self, fmt: Formatter):
        fmt.named_record("Signature", [
            ("generic-parameters", format.Seq(self.generic_parameters)),
            ("parameters", format.Seq(self.parameters)),
            ("returns", format.Seq(self.returns))])


@dataclass
class IntrinsicSignature(Formattable):
    generic_parameters: tuple[str, ...]
    parameters: tuple[without_holes.Type, ...]
    returns: tuple[without_holes.Type, ...]
    constraints: tuple[ConstraintOnGeneric, ...] = ()
    def format(self, fmt: Formatter):
        fmt.named_record("IntrinsicSignature", [
            ("generic-parameters", format.Seq(map(format.Str, self.generic_parameters))),
            ("parameters", format.Seq(self.parameters)),
            ("returns", format.Seq(self.returns)),
            ("constraints", format.Seq(self.constraints))])

type Signature = FunctionSignature | IntrinsicSignature

@dataclass
class Global(Formattable):
    name: Token
    taip: without_holes.Type
    reffed: bool = False
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Global", [self.name, self.taip, self.reffed])

@dataclass(frozen=True, eq=True)
class SyntheticName(Formattable):
    _token: Token
    name: str
    def format(self, fmt: Formatter):
        fmt.unnamed_record("SyntheticName", [self._token, format.Str(self.name)])

    def get(self) -> str:
        return self.name

    def token(self) -> Token:
        return self._token


@dataclass(frozen=True, eq=True)
class FromSource(Formattable):
    name: Token
    def format(self, fmt: Formatter):
        return self.name.format(fmt)

    def get(self) -> str:
        return self.name.lexeme

    def token(self) -> Token:
        return self.name

type LocalName = SyntheticName | FromSource

@dataclass
class Local(Formattable):
    name: LocalName
    parameter: without_holes.Type | None # if this local is a parameter, then this will be non-None

    @staticmethod
    def make(taip: NamedType) -> Local:
        return Local(FromSource(taip.name), None)

    @staticmethod
    def make_parameter(taip: without_holes.NamedType) -> Local:
        return Local(FromSource(taip.name), taip.taip)

    def format(self, fmt: Formatter):
        fmt.unnamed_record("Local", [self.name, format.Optional(self.parameter)])

@dataclass
class Function(Formattable):
    name: Token
    export_name: Token | None
    signature: FunctionSignature
    body: Scope
    locals: dict[LocalId, Local]
    def format(self, fmt: Formatter):
        fmt.named_record("Function", [
            ("name", self.name),
            ("export", format.Optional(self.export_name)),
            ("signature", self.signature),
            ("locals", format.Dict(dict(self.locals.items()))),
            ("body", self.body)])

@dataclass
class Extern(Formattable):
    name: Token
    extern_module: str
    extern_name: str
    signature: FunctionSignature
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Extern", [
            self.name,
            self.extern_module,
            self.extern_name,
            self.signature])
