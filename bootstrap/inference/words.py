from typing import Tuple
from dataclasses import dataclass

import format
from format import Formattable, Formatter

from lexer import Token
from parsing.words import NumberWord
from resolving import LocalId, GlobalId, FunctionHandle, ScopeId
from resolving.type_without_holes import Type, CustomTypeType, FunctionType, PtrType, Bool, I8, I32, I64
from unstacking import MatchVoid, StringWord, MemGrow, SetStackSize, Break, MemCopy, MemFill, Sizeof

@dataclass
class FieldAccess(Formattable):
    name: Token
    source_type: PtrType | CustomTypeType
    target_type: Type
    field_index: int
    def format(self, fmt: Formatter):
        fmt.unnamed_record("FieldAccess", [self.name, self.source_type, self.target_type, self.field_index])

@dataclass(frozen=True)
class GetLocal(Formattable):
    name: Token
    var: LocalId | GlobalId
    var_type: Type
    fields: Tuple[FieldAccess, ...]
    result_taip: Type
    def format(self, fmt: Formatter):
        fmt.unnamed_record("GetLocal", [
            self.name,
            self.var,
            self.var_type,
            self.result_taip,
            format.Seq(self.fields, multi_line=True)])

@dataclass(frozen=True)
class RefLocal(Formattable):
    name: Token
    var: LocalId | GlobalId
    fields: Tuple[FieldAccess, ...]
    def format(self, fmt: Formatter):
        fmt.unnamed_record("RefLocal", [
            self.name,
            self.var,
            format.Seq(self.fields, multi_line=True)])

@dataclass(frozen=True)
class InitLocal(Formattable):
    name: Token
    taip: Type
    local: LocalId
    def format(self, fmt: Formatter):
        fmt.unnamed_record("InitLocal", [
            self.name,
            self.taip,
            self.local])


@dataclass(frozen=True)
class Call(Formattable):
    name: Token
    function: FunctionHandle
    generic_arguments: Tuple[Type, ...]
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Call", [self.name, self.function, format.Seq(self.generic_arguments)])

@dataclass(frozen=True)
class Cast(Formattable):
    token: Token
    src: Type
    dst: Type
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Cast", [self.token, self.src, self.dst])

@dataclass(frozen=True)
class MakeStruct(Formattable):
    token: Token
    taip: CustomTypeType
    def format(self, fmt: Formatter):
        fmt.named_record("MakeStruct", [("token", self.token), ("type", self.taip)])

@dataclass(frozen=True)
class FunRef(Formattable):
    call: Call
    def format(self, fmt: Formatter):
        fmt.unnamed_record("FunRef", [self.call])

@dataclass(frozen=True)
class Scope(Formattable):
    id: ScopeId
    words: Tuple['Word', ...]
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Scope", [self.id, format.Seq(self.words, multi_line=True)])

@dataclass(frozen=True)
class If(Formattable):
    token: Token
    parameters: Tuple[Type, ...]
    returns: Tuple[Type, ...] | None
    true_branch: Scope
    false_branch: Scope
    def format(self, fmt: Formatter):
        fmt.named_record("If", [
            ("token", self.token),
            ("parameters", self.parameters),
            ("returns", format.Optional(self.returns)),
            ("true-branch", self.true_branch),
            ("false-branch", self.false_branch)])

@dataclass(frozen=True)
class SetLocal(Formattable):
    name: Token
    var: LocalId | GlobalId
    fields: Tuple[FieldAccess, ...]
    type: Type
    def format(self, fmt: Formatter):
        return fmt.unnamed_record("SetLocal", [self.name, self.var, self.type, format.Seq(self.fields, multi_line=True)])

@dataclass(frozen=True)
class StoreLocal(Formattable):
    name: Token
    var: LocalId
    type: Type
    fields: Tuple[FieldAccess, ...]
    def format(self, fmt: Formatter):
        return fmt.unnamed_record("StoreLocal", [self.name, self.var, self.type, format.Seq(self.fields)])

@dataclass(frozen=True)
class MatchCase(Formattable):
    taip: Type | None
    tag: int
    body: Scope
    def format(self, fmt: Formatter):
        return fmt.unnamed_record("MatchCase", [format.Optional(self.taip), self.tag, self.body])

@dataclass(frozen=True)
class Match(Formattable):
    token: Token
    variant: CustomTypeType
    by_ref: bool
    cases: Tuple[MatchCase, ...]
    default: Scope | None
    parameters: Tuple[Type, ...]
    returns: Tuple[Type, ...] | None
    def format(self, fmt: Formatter):
        return fmt.named_record("Match", [
            ("token", self.token),
            ("variant", self.variant),
            ("by-ref", self.by_ref),
            ("cases", format.Seq(self.cases, multi_line=True)),
            ("default", format.Optional(self.default)),
            ("parameters", format.Seq(self.parameters)),
            ("returns", format.Optional(format.Seq(self.returns) if self.returns is not None else None))])

@dataclass(frozen=True)
class Loop(Formattable):
    token: Token
    parameters: Tuple[Type, ...]
    returns: Tuple[Type, ...] | None
    body: Scope
    def format(self, fmt: Formatter):
        fmt.named_record("Loop", [
            ("token", self.token),
            ("parameters", format.Seq(self.parameters)),
            ("returns", format.Optional(format.Seq(self.returns) if self.returns is not None else None)),
            ("body", self.body)])

@dataclass(frozen=True)
class Block(Formattable):
    token: Token
    parameters: Tuple[Type, ...]
    returns: Tuple[Type, ...] | None
    body: Scope
    def format(self, fmt: Formatter):
        fmt.named_record("Block", [
            ("token", self.token),
            ("parameters", format.Seq(self.parameters)),
            ("returns", format.Optional(format.Seq(self.returns) if self.returns is not None else None)),
            ("body", self.body)])

@dataclass(frozen=True)
class GetField(Formattable):
    token: Token
    fields: Tuple[FieldAccess, ...]
    on_ptr: bool
    type: Type
    def format(self, fmt: Formatter):
        fmt.unnamed_record("GetField", [self.token, self.fields, self.on_ptr, self.type])

@dataclass(frozen=True)
class FieldInit(Formattable):
    name: Token
    type: Type
    field_index: int

@dataclass(frozen=True)
class MakeVariant(Formattable):
    token: Token
    tag: int
    taip: CustomTypeType
    def format(self, fmt: Formatter):
        fmt.named_record("MakeVariant", [
            ("token", self.token),
            ("tag", self.tag),
            ("type", self.taip)])

@dataclass(frozen=True)
class MakeStructNamed(Formattable):
    token: Token
    taip: CustomTypeType
    scope: Scope

@dataclass(frozen=True)
class IndirectCall(Formattable):
    token: Token
    taip: FunctionType

@dataclass(frozen=True)
class CommonIntrinsic(Formattable):
    token: Token
    taip: Type
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Intrinsic", [self.token, format.UnnamedRecord(type(self).__name__, [self.taip])])

@dataclass(frozen=True)
class Drop(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Eq(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class NotEq(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Lt(CommonIntrinsic):
    token: Token
    taip: I8 | I32 | I64
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Intrinsic", [self.token, format.UnnamedRecord(type(self).__name__, [self.taip])])

@dataclass(frozen=True)
class Le(CommonIntrinsic):
    token: Token
    taip: I8 | I32 | I64
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Intrinsic", [self.token, format.UnnamedRecord(type(self).__name__, [self.taip])])

@dataclass(frozen=True)
class Ge(CommonIntrinsic):
    token: Token
    taip: I8 | I32 | I64
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Intrinsic", [self.token, format.UnnamedRecord(type(self).__name__, [self.taip])])

@dataclass(frozen=True)
class Gt(CommonIntrinsic):
    token: Token
    taip: I8 | I32 | I64
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Intrinsic", [self.token, format.UnnamedRecord(type(self).__name__, [self.taip])])

@dataclass(frozen=True)
class Uninit(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Mul(Formattable):
    token: Token
    taip: I8 | I32 | I64
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Intrinsic", [self.token, format.UnnamedRecord(type(self).__name__, [self.taip])])

@dataclass(frozen=True)
class Div(CommonIntrinsic):
    token: Token
    taip: I8 | I32 | I64
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Intrinsic", [self.token, format.UnnamedRecord(type(self).__name__, [self.taip])])

@dataclass(frozen=True)
class Mod(CommonIntrinsic):
    token: Token
    taip: I8 | I32 | I64
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Intrinsic", [self.token, format.UnnamedRecord(type(self).__name__, [self.taip])])

@dataclass(frozen=True)
class Add(CommonIntrinsic):
    token: Token
    taip: PtrType | I8 | I32 | I64
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Intrinsic", [self.token, format.UnnamedRecord(type(self).__name__, [self.taip])])

@dataclass(frozen=True)
class Sub(CommonIntrinsic):
    token: Token
    taip: PtrType | I8 | I32 | I64
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Intrinsic", [self.token, format.UnnamedRecord(type(self).__name__, [self.taip])])

@dataclass(frozen=True)
class Load(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Store(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class And(CommonIntrinsic):
    token: Token
    taip: Bool | I8 | I32 | I64
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Intrinsic", [self.token, format.UnnamedRecord(type(self).__name__, [self.taip])])

@dataclass(frozen=True)
class Or(CommonIntrinsic):
    token: Token
    taip: Bool | I8 | I32 | I64
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Intrinsic", [self.token, format.UnnamedRecord(type(self).__name__, [self.taip])])

@dataclass(frozen=True)
class Rotl(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Rotr(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Shl(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Shr(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Not(CommonIntrinsic):
    token: Token
    taip: Bool | I8 | I32 | I64
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Intrinsic", [self.token, format.UnnamedRecord(type(self).__name__, [self.taip])])

@dataclass(frozen=True)
class Flip(Formattable):
    token: Token
    lower: Type
    upper: Type
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Intrinsic", [self.token, format.UnnamedRecord("Flip", [self.lower, self.upper])])

type Intrinsic = Drop | Eq | NotEq | Uninit | Mul | Div | Mod | Add | Sub | Load | Flip | Store | Lt | Le | Ge | Gt | And | Or | Shl | Shr | Rotl | Rotr | Not | MemCopy | MemFill

type Word = GetLocal | Intrinsic | NumberWord | InitLocal | Call | MatchVoid | Cast | MakeStruct | StringWord | RefLocal | FunRef | If | SetLocal | MemGrow | SetStackSize | Match | Loop | Break | StoreLocal | Block | MakeVariant | GetField | FieldInit | Sizeof | MakeStructNamed | IndirectCall

