from typing import List, Tuple
from dataclasses import dataclass

import format
from format import Formattable, Formatter
from lexer import Token
from parsing.words import Word
from parsing.types import Type, NamedType

type TypeDefinition = Struct | Variant

type TopItem = Import | TypeDefinition | Global | Function | Extern

@dataclass(frozen=True)
class VariantImport(Formattable):
    name: Token
    constructors: Tuple[Token, ...]
    def format(self, fmt: Formatter):
        fmt.unnamed_record("VariantImport", [
            self.name, format.Seq(self.constructors)])

type ImportItem = Token | VariantImport

@dataclass(frozen=True, eq=True)
class Import(Formattable):
    token: Token
    file_path: Token
    qualifier: Token
    items: Tuple[ImportItem, ...]
    def format(self, fmt: Formatter):
        fmt.named_record("Import", [
            ("start", self.token),
            ("path", self.file_path),
            ("qualifier", self.qualifier),
            ("items", format.Seq(self.items))])

@dataclass
class FunctionSignature(Formattable):
    export_name: Token | None
    name: Token
    generic_parameters: Tuple[Token, ...]
    parameters: Tuple[NamedType, ...]
    returns: Tuple[Type, ...]
    def format(self, fmt: Formatter):
        fmt.named_record("Signature", [
            ("generic-parameters", format.Seq(self.generic_parameters)),
            ("parameters", format.Seq(self.parameters, multi_line=True)),
            ("returns", format.Seq(self.returns, multi_line=True))])

@dataclass
class Extern(Formattable):
    start: Token
    module: Token
    name: Token
    signature: FunctionSignature
    def format(self, fmt: Formatter):
        fmt.named_record("Extern", [
            ("start", self.start),
            ("export-module", self.module),
            ("export-name", self.name),
            ("name", self.signature.name),
            ("signature", self.signature)])

@dataclass
class Global(Formattable):
    token: Token
    name: Token
    taip: Type

@dataclass
class Function(Formattable):
    start: Token
    signature: FunctionSignature
    body: Tuple[Word, ...]
    def format(self, fmt: Formatter):
        fmt.named_record("Function", [
            ("start", self.start),
            ("name", self.signature.name),
            ("export-name", format.Optional(self.signature.export_name)),
            ("signature", self.signature),
            ("body", format.Seq(self.body, multi_line=True))])

@dataclass
class Struct(Formattable):
    token: Token
    name: Token
    fields: Tuple[NamedType, ...]
    generic_parameters: Tuple[Token, ...]
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Struct", [
            self.token,
            self.name,
            format.Seq(self.generic_parameters),
            format.Seq(self.fields, multi_line=True)])

@dataclass
class VariantCase:
    name: Token
    taip: Type | None

@dataclass
class Variant(Formattable):
    name: Token
    generic_parameters: Tuple[Token, ...]
    cases: List[VariantCase]
