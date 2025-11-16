from typing import List, Tuple
from dataclasses import dataclass

import format
from format import Formattable, Formatter

from lexer import Token
from parsing.words import BreakWord, NumberWord
from resolving.types import CustomTypeType, PtrType, Type, FunctionType
from resolving.words import ScopeId, LocalId, GlobalId, FunctionHandle, MatchVoidWord, StringWord
from checking import intrinsics as intrinsics
from checking.intrinsics import IntrinsicWord

@dataclass
class Scope(Formattable):
    id: ScopeId
    words: List['Word']
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Scope", [self.id, format.Seq(self.words, multi_line=True)])

@dataclass
class FieldAccess(Formattable):
    name: Token
    source_taip: CustomTypeType | PtrType
    target_taip: Type
    field_index: int
    def format(self, fmt: Formatter):
        fmt.unnamed_record("FieldAccess", [
            self.name, self.source_taip, self.target_taip, self.field_index])

@dataclass
class LoadWord(Formattable):
    token: Token
    taip: Type

@dataclass
class InitWord(Formattable):
    name: Token
    local_id: LocalId
    taip: Type

@dataclass
class GetLocal(Formattable):
    name: Token
    local_id: LocalId | GlobalId
    var_taip: Type
    fields: Tuple[FieldAccess, ...]
    taip: Type
    def format(self, fmt: Formatter):
        fmt.unnamed_record("GetLocal", [
            self.name,
            self.local_id,
            self.var_taip,
            self.taip,
            format.Seq(self.fields, multi_line=True)])

@dataclass
class RefWord(Formattable):
    token: Token
    local_id: LocalId | GlobalId
    fields: Tuple[FieldAccess, ...]
    def format(self, fmt: Formatter):
        fmt.unnamed_record("RefLocal", [self.token, self.local_id, format.Seq(self.fields, multi_line=True)])

@dataclass
class SetWord(Formattable):
    token: Token
    local_id: LocalId | GlobalId
    fields: Tuple[FieldAccess, ...]

@dataclass
class StoreWord(Formattable):
    token: Token
    local: LocalId | GlobalId
    fields: Tuple[FieldAccess, ...]

@dataclass
class CallWord(Formattable):
    name: Token
    function: FunctionHandle
    generic_arguments: Tuple[Type, ...]
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Call", [self.name, self.function, format.Seq(self.generic_arguments)])

@dataclass
class FunRefWord(Formattable):
    call: CallWord
    def format(self, fmt: Formatter):
        fmt.unnamed_record("FunRef", [self.call])

@dataclass
class IfWord(Formattable):
    token: Token
    parameters: Tuple[Type, ...]
    returns: Tuple[Type, ...] | None
    true_branch: Scope
    false_branch: Scope
    diverges: bool
    def format(self, fmt: Formatter):
        fmt.named_record("If", [
            ("token", self.token),
            ("parameters", self.parameters),
            ("returns", format.Optional(self.returns)),
            ("true-branch", self.true_branch),
            ("false-branch", self.false_branch)])

@dataclass
class LoopWord(Formattable):
    token: Token
    body: Scope
    parameters: Tuple[Type, ...]
    returns: Tuple[Type, ...]
    diverges: bool
    def format(self, fmt: Formatter):
        fmt.named_record("Loop", [
            ("token", self.token),
            ("parameters", self.parameters),
            ("returns", format.Optional(None if self.diverges else self.returns)),
            ("body", self.body)])


@dataclass
class BlockWord(Formattable):
    token: Token
    body: Scope
    parameters: Tuple[Type, ...]
    returns: Tuple[Type, ...]

@dataclass
class CastWord(Formattable):
    token: Token
    source: Type
    taip: Type

@dataclass
class SizeofWord(Formattable):
    token: Token
    taip: Type

@dataclass
class GetFieldWord(Formattable):
    token: Token
    fields: Tuple[FieldAccess, ...]
    on_ptr: bool

@dataclass
class IndirectCallWord(Formattable):
    token: Token
    taip: FunctionType
    def format(self, fmt: Formatter):
        fmt.unnamed_record("IndirectCall", [self.token, self.taip])

@dataclass
class StructFieldInitWord(Formattable):
    token: Token
    field_index: int

@dataclass
class StructWord(Formattable):
    token: Token
    taip: CustomTypeType
    body: Scope
    def format(self, fmt: Formatter):
        fmt.named_record("StructWordNamed", [
            ("token", self.token),
            ("type", self.taip),
            ("body", self.body)])

@dataclass
class UnnamedStructWord(Formattable):
    token: Token
    taip: CustomTypeType
    def format(self, fmt: Formatter):
        fmt.named_record("StructWord", [
            ("token", self.token),
            ("type", self.taip)])

@dataclass
class VariantWord(Formattable):
    token: Token
    tag: int
    variant: CustomTypeType
    def format(self, fmt: Formatter):
        fmt.named_record("VariantWord", [
            ("token", self.token),
            ("tag", self.tag),
            ("type", self.variant)])

@dataclass
class MatchCase(Formattable):
    taip: Type | None
    tag: int
    body: Scope
    def format(self, fmt: Formatter):
        fmt.unnamed_record("MatchCase", [format.Optional(self.taip), self.tag, self.body])

@dataclass
class MatchWord(Formattable):
    token: Token
    variant: CustomTypeType
    by_ref: bool
    cases: Tuple[MatchCase, ...]
    default: Scope | None
    parameters: Tuple[Type, ...]
    returns: Tuple[Type, ...] | None
    def format(self, fmt: Formatter):
        fmt.named_record("Match", [
            ("token", self.token),
            ("variant", self.variant),
            ("by-ref", self.by_ref),
            ("cases", format.Seq(self.cases, multi_line=True)),
            ("default", format.Optional(self.default)),
            ("parameters", format.Seq(self.parameters)),
            ("returns", format.Optional(self.returns))])

type Word = (
      NumberWord
    | StringWord
    | CallWord
    | GetLocal
    | RefWord
    | SetWord
    | StoreWord
    | FunRefWord
    | IfWord
    | LoadWord
    | LoopWord
    | BlockWord
    | BreakWord
    | CastWord
    | SizeofWord
    | GetFieldWord
    | IndirectCallWord
    | IntrinsicWord
    | InitWord
    | StructFieldInitWord
    | StructWord
    | UnnamedStructWord
    | VariantWord
    | MatchWord
    | MatchVoidWord
)
