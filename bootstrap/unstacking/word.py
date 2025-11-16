from typing import Tuple
from dataclasses import dataclass

from resolving.words import ScopeId, LocalId, GlobalId, NumberWord, InitLocal, StringWord, SizeofWord, BreakWord
from resolving import FunctionHandle, CustomTypeHandle
import resolving.types as with_holes

import format
from format import Formattable, Formatter
from lexer import Token

@dataclass(frozen=True)
class InferenceHole(Formattable):
    token: Token
    index: int
    def format(self, fmt: Formatter):
        fmt.unnamed_record("InferenceHole", [self.token, self.index])

@dataclass(frozen=True)
class InferenceFieldHole(Formattable):
    index: int
    def format(self, fmt: Formatter):
        fmt.unnamed_record("InferenceFieldHole", [self.index])

@dataclass(frozen=True)
class FieldAccess(Formattable):
    name: Token
    source_type: InferenceHole
    target_type: InferenceHole
    field_index: InferenceFieldHole
    def format(self, fmt: Formatter):
        fmt.unnamed_record("FieldAccess", [self.name, self.source_type, self.target_type, self.field_index])

@dataclass(frozen=True)
class Scope(Formattable):
    id: ScopeId
    words: Tuple['Word', ...]

    def format(self, fmt: Formatter):
        fmt.unnamed_record("Scope", [self.id, format.Seq(self.words, multi_line=True)])

type Word = 'InitLocal | RefLocal | GetLocal | NumberWord | Intrinsic | If | Match | Cast | Call | SetLocal | SetGlobal | StringWord | GetField | SizeofWord | Store | Load | MakeStructNamed | FieldInit | MakeVariant | Block | BreakWord | Loop | IndirectCall | MakeStruct | StoreLocal | FunRef'

@dataclass(frozen=True)
class GetLocal(Formattable):
    name: Token
    var: LocalId | GlobalId
    var_type: InferenceHole
    result_type: InferenceHole
    fields: Tuple[FieldAccess, ...]
    def format(self, fmt: Formatter):
        fmt.unnamed_record("GetLocal", [self.name, self.var, self.var_type, self.result_type, format.Seq(self.fields, multi_line=True)])

@dataclass(frozen=True)
class RefLocal(Formattable):
    name: Token
    var: LocalId | GlobalId
    var_type: InferenceHole
    result_type: InferenceHole
    fields: Tuple[FieldAccess, ...]
    def format(self, fmt: Formatter):
        fmt.unnamed_record("RefLocal", [self.name, self.var, self.var_type, self.result_type, format.Seq(self.fields, multi_line=True)])

@dataclass(frozen=True)
class SetLocal(Formattable):
    name: Token
    local: LocalId
    fields: Tuple[FieldAccess, ...]
    field_type: InferenceHole
    def format(self, fmt: Formatter):
        fmt.unnamed_record("SetLocal", [self.name, self.local, format.Seq(self.fields, multi_line=True), self.field_type])

@dataclass(frozen=True)
class SetGlobal(Formattable):
    name: Token
    globl: GlobalId
    fields: Tuple[FieldAccess, ...]
    field_type: InferenceHole
    def format(self, fmt: Formatter):
        fmt.unnamed_record("SetGlobal", [self.name, self.globl, format.Seq(self.fields, multi_line=True), self.field_type])

@dataclass(frozen=True)
class StoreLocal(Formattable):
    name: Token
    var: LocalId
    fields: Tuple[FieldAccess, ...]
    field_type: InferenceHole
    def format(self, fmt: Formatter):
        fmt.unnamed_record("StoreLocal", [self.name, self.var, format.Seq(self.fields, multi_line=True), self.field_type])

@dataclass(frozen=True)
class If(Formattable):
    token: Token
    parameters: Tuple[InferenceHole, ...]
    returns: Tuple[InferenceHole, ...] | None
    true_branch: Scope
    false_branch: Scope
    def format(self, fmt: Formatter):
        fmt.named_record("If", [
            ("token", self.token),
            ("parameters", format.Seq(self.parameters)),
            ("returns", format.Optional(format.Seq(self.returns, multi_line=True) if self.returns is not None else None)),
            ("true-branch", self.true_branch),
            ("false-branch", self.false_branch)])

@dataclass(frozen=True)
class MatchCase(Formattable):
    name: Token
    tag: int
    body: Scope
    def format(self, fmt: Formatter):
        fmt.named_record("MatchCase", [
            ("name", self.name),
            ("tag", self.tag),
            ("body", self.body)])

@dataclass(frozen=True)
class DefaultCase(Formattable):
    name: Token
    body: Scope
    def format(self, fmt: Formatter):
        fmt.named_record("MatchCase", [
            ("name", self.name),
            ("body", self.body)])

@dataclass(frozen=True)
class Match(Formattable):
    token: Token
    type: InferenceHole
    parameters: Tuple[InferenceHole, ...]
    returns: Tuple[InferenceHole, ...] | None
    cases: Tuple[MatchCase, ...]
    default: DefaultCase | None
    def format(self, fmt: Formatter):
        fmt.named_record("Match", [
            ("token", self.token),
            ("type", self.type),
            ("parameters", self.parameters),
            ("returns", format.Optional(None if self.returns is None else format.Seq(self.returns, multi_line=True))),
            ("cases", format.Seq(self.cases, multi_line=True)),
            ("default", format.Optional(self.default))])

@dataclass(frozen=True)
class Cast(Formattable):
    token: Token
    src_type: InferenceHole
    dst_type: with_holes.Type
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Cast", [self.token, self.src_type, self.dst_type])

@dataclass(frozen=True)
class Call(Formattable):
    name: Token
    function: FunctionHandle
    generic_arguments: Tuple[InferenceHole, ...]
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Call", [self.name, self.function, format.Seq(self.generic_arguments, multi_line=True)])

@dataclass(frozen=True)
class GetField(Formattable):
    token: Token
    base_type: InferenceHole
    fields: Tuple[FieldAccess, ...]
    def format(self, fmt: Formatter):
        fmt.unnamed_record("GetField", [self.token, self.base_type, format.Seq(self.fields, multi_line=True)])

@dataclass(frozen=True)
class Store(Formattable):
    token: Token
    taip: InferenceHole
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Store", [self.token, self.taip])

@dataclass(frozen=True)
class Load(Formattable):
    token: Token
    taip: InferenceHole
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Load", [self.token, self.taip])

@dataclass(frozen=True)
class MakeStructNamed(Formattable):
    token: Token
    taip: InferenceHole
    body: Scope
    def format(self, fmt: Formatter):
        fmt.named_record("MakeStructNamed", [
            ("token", self.token),
            ("type", self.taip),
            ("body", self.body)])

@dataclass(frozen=True)
class MakeStruct(Formattable):
    token: Token
    struct: CustomTypeHandle
    taip: InferenceHole
    def format(self, fmt: Formatter):
        fmt.named_record("MakeStruct", [
            ("token", self.token),
            ("struct", self.struct),
            ("type", self.taip)])

@dataclass(frozen=True)
class FieldInit(Formattable):
    name: Token
    taip: InferenceHole
    field_index: int
    def format(self, fmt: Formatter):
        fmt.unnamed_record("FieldInit", [self.name, self.taip, self.field_index])

@dataclass(frozen=True)
class MakeVariant(Formattable):
    token: Token
    taip: InferenceHole
    tag: int
    def format(self, fmt: Formatter):
        fmt.named_record("MakeVariant", [
            ("token", self.token),
            ("type", self.taip),
            ("tag", self.tag)])

@dataclass(frozen=True)
class Block(Formattable):
    token: Token
    parameters: Tuple[InferenceHole, ...]
    returns: Tuple[InferenceHole, ...] | None
    body: Scope
    def format(self, fmt: Formatter):
        fmt.named_record("Block", [
            ("token", self.token),
            ("parameters", self.parameters),
            ("returns", format.Optional(format.Seq(self.returns, multi_line=True) if self.returns is not None else None)),
            ("body", self.body)])

@dataclass(frozen=True)
class Loop(Formattable):
    token: Token
    parameters: Tuple[InferenceHole, ...]
    returns: Tuple[InferenceHole, ...] | None
    body: Scope
    def format(self, fmt: Formatter):
        fmt.named_record("Loop", [
            ("token", self.token),
            ("parameters", self.parameters),
            ("returns", format.Optional(format.Seq(self.returns, multi_line=True) if self.returns is not None else None)),
            ("body", self.body)])

@dataclass(frozen=True)
class IndirectCall(Formattable):
    token: Token
    parameters: Tuple[InferenceHole, ...]
    return_types: Tuple[InferenceHole, ...]
    def format(self, fmt: Formatter):
        fmt.named_record("IndirectCall", [
            ("token", self.token),
            ("parameters", format.Seq(self.parameters)),
            ("return-types", format.Seq(self.return_types))])

@dataclass(frozen=True)
class FunRef(Formattable):
    token: Token
    function: FunctionHandle
    generic_arguments: Tuple[InferenceHole, ...]
    def format(self, fmt: Formatter):
        fmt.named_record("FunRef", [
            ("token", self.token),
            ("function", self.function),
            ("generic-arguments", self.generic_arguments)])

@dataclass(frozen=True)
class CommonIntrinsic(Formattable):
    token: Token
    taip: InferenceHole
    def format(self, fmt: Formatter):
        fmt.unnamed_record(type(self).__name__, [self.token, self.taip])

@dataclass(frozen=True)
class Add(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Sub(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Eq(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class NotEq(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Drop(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Uninit(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Mul(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Div(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Mod(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Lt(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Le(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Ge(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Gt(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class And(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Or(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Not(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Shl(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Shr(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Rotl(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Rotr(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Flip(Formattable):
    token: Token
    lower: InferenceHole | None
    upper: InferenceHole | None
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Flip", [self.token, self.lower, self.upper])

@dataclass(frozen=True)
class MemGrow:
    token: Token
    def format(self, fmt: Formatter):
        fmt.unnamed_record("MemGrow", [self.token])

@dataclass(frozen=True)
class SetStackSize:
    token: Token
    def format(self, fmt: Formatter):
        fmt.unnamed_record("SetStackSize", [self.token])

@dataclass(frozen=True)
class MemCopy:
    token: Token
    def format(self, fmt: Formatter):
        fmt.unnamed_record("MemCopy", [self.token])

@dataclass(frozen=True)
class MemFill:
    token: Token
    def format(self, fmt: Formatter):
        fmt.unnamed_record("MemFill", [self.token])

type Intrinsic = Add | Sub | Eq | NotEq | Drop | Uninit | Flip | MemGrow | Mul | Div | Mod | SetStackSize | Lt | Le | Ge | Gt | And | Or | Not | MemCopy | MemFill | Shl | Shr | Rotl | Rotr

