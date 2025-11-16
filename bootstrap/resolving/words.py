from typing import Tuple
from dataclasses import dataclass, field

import format
from format import Formattable, Formatter
from lexer import Token

from resolving.intrinsics import IntrinsicType
from resolving.types import CustomTypeType, Type, CustomTypeHandle
from parsing.words import (
    BreakWord as BreakWord,
    NumberWord as NumberWord,
    LoadWord as LoadWord,
    GetFieldWord as GetFieldWord,
)

type Word = (
      NumberWord
    | StringWord
    | CallWord
    | GetLocal
    | RefLocal
    | SetLocal
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
    | InitLocal
    | StructFieldInitWord
    | StructWordNamed
    | StructWord
    | VariantWord
    | MatchVoidWord
    | MatchWord
    | StackAnnotation
)

@dataclass(frozen=True, eq=True)
class ScopeId(Formattable):
    raw: int
    def format(self, fmt: Formatter):
        fmt.write(self.raw)

ROOT_SCOPE: ScopeId = ScopeId(0)

@dataclass
class Scope(Formattable):
    id: ScopeId
    words: Tuple[Word, ...]
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Scope", [self.id, format.Seq(self.words, multi_line=True)])


@dataclass(frozen=True, eq=True)
class GlobalId(Formattable):
    name: Token = field(compare=False, hash=False)
    module: int
    index: int
    def format(self, fmt: Formatter):
        fmt.unnamed_record("GlobalId", [self.name, self.module, self.index])

@dataclass(frozen=True, eq=True)
class LocalId(Formattable):
    name: str
    scope: ScopeId
    shadow: int
    def format(self, fmt: Formatter):
        fmt.unnamed_record("LocalId", [
            format.Str(self.name),
            self.scope,
            self.shadow])

@dataclass(frozen=True, eq=True)
class StringWord(Formattable):
    token: Token
    offset: int
    len: int
    def format(self, fmt: Formatter):
        fmt.unnamed_record("StringWord", [self.token, self.offset, self.len])

@dataclass
class InitLocal(Formattable):
    name: Token
    local_id: LocalId
    def format(self, fmt: Formatter):
        fmt.unnamed_record("InitLocal", [self.name, self.local_id])

@dataclass
class GetLocal(Formattable):
    name: Token
    var: LocalId | GlobalId
    fields: Tuple[Token, ...]
    def format(self, fmt: Formatter):
        fmt.unnamed_record("GetLocal", [
            self.name,
            self.var,
            format.Seq(self.fields, multi_line=True)])

@dataclass
class RefLocal(Formattable):
    name: Token
    var: LocalId | GlobalId
    fields: Tuple[Token, ...]
    def format(self, fmt: Formatter):
        fmt.unnamed_record("RefLocal", [self.name, self.var, format.Seq(self.fields, multi_line=True)])

@dataclass
class SetLocal(Formattable):
    name: Token
    var: LocalId | GlobalId
    fields: Tuple[Token, ...]

@dataclass
class StoreWord(Formattable):
    name: Token
    var: LocalId | GlobalId
    fields: Tuple[Token, ...]

@dataclass
class CallWord(Formattable):
    name: Token
    function: 'FunctionHandle'
    generic_arguments: Tuple[Type, ...]
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Call", [self.name, self.function, format.Seq(self.generic_arguments)])

@dataclass(frozen=True, eq=True)
class FunctionHandle(Formattable):
    module: int
    index: int
    def format(self, fmt: Formatter):
        fmt.unnamed_record("FunctionHandle", [self.module, self.index])

@dataclass
class FunRefWord(Formattable):
    call: CallWord
    def format(self, fmt: Formatter):
        fmt.unnamed_record("FunRef", [self.call])

@dataclass
class IfWord(Formattable):
    token: Token
    true_branch: Scope
    false_branch: Scope
    def format(self, fmt: Formatter):
        fmt.named_record("If", [
            ("token", self.token),
            ("true-branch", self.true_branch),
            ("false-branch", self.false_branch)])

@dataclass
class BlockAnnotation(Formattable):
    parameters: Tuple[Type, ...]
    returns: Tuple[Type, ...]
    def format(self, fmt: Formatter):
        fmt.unnamed_record("BlockAnnotation", [
            format.Seq(self.parameters),
            format.Seq(self.returns)])

@dataclass
class LoopWord(Formattable):
    token: Token
    body: Scope
    annotation: BlockAnnotation | None
    def format(self, fmt: Formatter):
        fmt.named_record("Loop", [
            ("token", self.token),
            ("body", self.body),
            ("annotation", format.Optional(self.annotation))])

@dataclass
class BlockWord(Formattable):
    token: Token
    end: Token
    body: Scope
    annotation: BlockAnnotation | None

@dataclass
class CastWord(Formattable):
    token: Token
    dst: Type

@dataclass
class SizeofWord(Formattable):
    token: Token
    taip: Type
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Sizeof", [self.token, self.taip])

@dataclass
class StructFieldInitWord(Formattable):
    name: Token
    struct: CustomTypeHandle
    field_index: int

@dataclass
class StructWordNamed(Formattable):
    token: Token
    name: Token
    taip: CustomTypeType
    body: Scope
    def format(self, fmt: Formatter):
        fmt.named_record("StructWordNamed", [
            ("token", self.token),
            ("name", self.token),
            ("type", self.taip),
            ("body", self.body)])

@dataclass
class StructWord(Formattable):
    token: Token
    name: Token
    taip: CustomTypeType
    def format(self, fmt: Formatter):
        fmt.named_record("StructWord", [
            ("token", self.token),
            ("name", self.name),
            ("type", self.taip)])

@dataclass
class VariantWord(Formattable):
    token: Token
    tag: int
    variant: CustomTypeType
    def format(self, fmt: Formatter):
        fmt.named_record("MakeVariant", [
            ("token", self.token),
            ("tag", self.tag),
            ("type", self.variant)])

@dataclass
class MatchCase(Formattable):
    tag: int
    name: Token
    body: Scope
    def format(self, fmt: Formatter):
        fmt.unnamed_record("MatchCase", [self.tag, self.name, self.body])

@dataclass
class DefaultCase(Formattable):
    underscore: Token
    body: Scope
    def format(self, fmt: Formatter):
        fmt.unnamed_record("DefaultCase", [self.underscore, self.body])

@dataclass
class MatchWord(Formattable):
    token: Token
    variant: CustomTypeHandle
    cases: Tuple[MatchCase, ...]
    default: DefaultCase | None
    def format(self, fmt: Formatter):
        fmt.named_record("Match", [
            ("token", self.token),
            ("variant", self.variant),
            ("cases", format.Seq(self.cases, multi_line=True)),
            ("default", format.Optional(self.default))])

@dataclass
class MatchVoidWord(Formattable):
    token: Token
    def format(self, fmt: Formatter):
        fmt.unnamed_record("MatchVoid", [self.token])

@dataclass
class IndirectCallWord(Formattable):
    token: Token
    parameters: Tuple[Type, ...]
    returns: Tuple[Type, ...]
    def format(self, fmt: Formatter):
        fmt.named_record("IndirectCallWord", [
            ("token", self.token),
            ("parameters", format.Seq(self.parameters, multi_line=True)),
            ("returns", format.Seq(self.returns, multi_line=True))])

@dataclass
class StackAnnotation(Formattable):
    token: Token
    types: Tuple[Type, ...]
    def format(self, fmt: Formatter):
        fmt.unnamed_record("StackAnnotation", [
            self.token,
            format.Seq(self.types)])

@dataclass(frozen=True)
class IntrinsicWord(Formattable):
    token: Token
    ty: IntrinsicType
    generic_arguments: Tuple[Type, ...]
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Intrinsic", [self.token, self.ty, format.Seq(self.generic_arguments)])

