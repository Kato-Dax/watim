from typing import Tuple
from dataclasses import dataclass

import format
from format import Formattable, Formatter

from lexer import Token

from resolving.type_without_holes import Type
from resolving import FunctionHandle, IntrinsicType

from unstacking.word import FieldAccess
from unstacking.source import InferenceHole, Source

@dataclass(frozen=True)
class StoreVoid(Formattable):
    token: Token
    dst: Source | None
    src: Source | None
    taip: InferenceHole
    def format(self, fmt: Formatter):
        fmt.named_record("StoreVoid", [
            ("token", self.token),
            ("dst", format.Optional(self.dst)),
            ("src", format.Optional(self.src)),
            ("type", self.taip)])

@dataclass(frozen=True)
class NonSpecificVoid(Formattable):
    token: Token
    source: Source | None
    known: Type | None
    taip: InferenceHole | None
    def format(self, fmt: Formatter):
        fmt.named_record("NonSpecificVoid", [
            ("token", self.token),
            ("type", format.Optional(self.taip)),
            ("source", format.Optional(self.source)),
            ("known", format.Optional(self.known))])

@dataclass(frozen=True)
class CallVoid(Formattable):
    token: Token
    function: FunctionHandle | IntrinsicType
    arguments: Tuple[Source, ...]
    generic_arguments: Tuple[InferenceHole, ...]
    def format(self, fmt: Formatter):
        fmt.named_record("CallVoid", [
            ("token", self.token),
            ("function", self.function),
            ("arguments", format.Seq(self.arguments, multi_line=True)),
            ("generic-arguments", format.Seq(self.generic_arguments, multi_line=True))])

@dataclass(frozen=True)
class SetGlobalVoid(Formattable):
    token: Token
    global_type: Type
    fields: Tuple[FieldAccess, ...]
    type: InferenceHole
    source: Source | None
    def format(self, fmt: Formatter):
        fmt.named_record("SetGlobalVoid", [
            ("token", self.token),
            ("global-type", self.global_type),
            ("fields", format.Seq(self.fields, multi_line=True)),
            ("type", self.type),
            ("source", format.Optional(self.source))])

@dataclass(frozen=True)
class IndirectCallVoid(Formattable):
    token: Token
    function: Source | None
    parameters: Tuple[InferenceHole, ...]
    returns: Tuple[InferenceHole, ...]
    def format(self, fmt: Formatter):
        fmt.named_record("IndirectCallVoid", [
            ("token", self.token),
            ("parameters", format.Seq(self.parameters, multi_line=True)),
            ("returns", format.Seq(self.returns, multi_line=True)),
            ("function", format.Optional(self.function))])

@dataclass(frozen=True)
class ImpossibleMatchVoid(Formattable):
    token: Token
    source: Source | None
    def format(self, fmt: Formatter):
        fmt.unnamed_record("ImpossibleMatchVoid", [self.token, self.source])

type StackVoid = StoreVoid | NonSpecificVoid | CallVoid | SetGlobalVoid | IndirectCallVoid | ImpossibleMatchVoid

