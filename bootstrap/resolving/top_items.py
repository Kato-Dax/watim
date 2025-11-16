from typing import Dict, Tuple
from dataclasses import dataclass

import format
from format import Formattable, Formatter

from lexer import Token
from resolving.words import FunctionHandle, Scope, LocalId
from resolving.types import CustomTypeHandle, Type, NamedType
import resolving.type_without_holes as without_holes

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
    constructors: Tuple[int, ...]
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
    items: Tuple[ImportItem, ...]
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
    generic_parameters: Tuple[Token, ...]
    fields: Tuple[NamedType, ...]
    def format(self, fmt: Formatter):
        fmt.named_record("Struct", [
            ("name", self.name),
            ("generic-parameters", format.Seq(self.generic_parameters)),
            ("fields", format.Seq(self.fields, multi_line=True))])

@dataclass
class VariantCase(Formattable):
    name: Token
    taip: Type | None
    def format(self, fmt: Formatter):
        fmt.unnamed_record("VariantCase", [self.name, format.Optional(self.taip)])

@dataclass
class Variant(Formattable):
    name: Token
    generic_parameters: Tuple[Token, ...]
    cases: Tuple[VariantCase, ...]
    def format(self, fmt: Formatter):
        fmt.named_record("Variant", [
            ("name", self.name),
            ("generic-parameters", format.Seq(self.generic_parameters)),
            ("cases", format.Seq(self.cases, multi_line=True))])

@dataclass
class FunctionSignature(Formattable):
    generic_parameters: Tuple[Token, ...]
    parameters: Tuple[without_holes.NamedType, ...]
    returns: Tuple[without_holes.Type, ...]
    def format(self, fmt: Formatter):
        fmt.named_record("Signature", [
            ("generic-parameters", format.Seq(self.generic_parameters)),
            ("parameters", format.Seq(self.parameters)),
            ("returns", format.Seq(self.returns))])

@dataclass
class Global(Formattable):
    name: Token
    taip: without_holes.Type
    was_reffed: bool = False
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Global", [self.name, self.taip, self.was_reffed])

@dataclass(frozen=True, eq=True)
class SyntheticName(Formattable):
    _token: Token
    name: str
    def format(self, fmt: Formatter):
        fmt.unnamed_record("SyntheticName", [self._token, self.name])

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
    def make(taip: NamedType) -> 'Local':
        return Local(FromSource(taip.name), None)

    @staticmethod
    def make_parameter(taip: without_holes.NamedType) -> 'Local':
        return Local(FromSource(taip.name), taip.taip)

    def format(self, fmt: Formatter):
        fmt.unnamed_record("Local", [self.name, format.Optional(self.parameter)])

@dataclass
class Function(Formattable):
    name: Token
    export_name: Token | None
    signature: FunctionSignature
    body: Scope
    locals: Dict[LocalId, Local]
    def format(self, fmt: Formatter):
        fmt.named_record("Function", [
            ("name", self.name),
            ("export", format.Optional(self.export_name)),
            ("signature", self.signature),
            ("locals", format.Dict(dict((k,v) for k,v in self.locals.items()))),
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
