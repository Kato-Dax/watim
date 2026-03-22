from typing import Tuple
from dataclasses import dataclass

import format
from format import Formattable, Formatter
from lexer import Token

from resolving.words import FunctionHandle, GlobalId, LocalId, IntrinsicType
from resolving.type_without_holes import Type, CustomTypeHandle
import resolving.types as with_holes
from unstacking.word import InferenceHole, FieldAccess

type Source = FromNumber | FromLocal | FromGlobal | FromNode | FromCase | FromProxied | FromCast | FromString | FromGetField | FromLoad | FromMakeStruct | FromMakeVariant | FromFunRef | FromAdd

@dataclass(frozen=True)
class FromNumber(Formattable):
    token: Token
    def format(self, fmt: Formatter):
        fmt.unnamed_record("FromNumber", [self.token])

@dataclass(frozen=True)
class FromString(Formattable):
    token: Token
    def format(self, fmt: Formatter):
        fmt.unnamed_record("FromString", [self.token])

@dataclass(frozen=True)
class FromLocal(Formattable):
    token: Token
    var: LocalId
    taip: InferenceHole
    fields: Tuple[FieldAccess, ...]
    result_type: InferenceHole
    by_reference: bool
    def format(self, fmt: Formatter):
        fmt.named_record("FromLocal", [
            ("token", self.token),
            ("var", self.var),
            ("type", self.taip),
            ("fields", format.Seq(self.fields, multi_line=True)),
            ("result-type", self.result_type),
            ("by-reference", self.by_reference)])

@dataclass(frozen=True)
class FromGlobal(Formattable):
    token: Token
    var: GlobalId
    taip: Type
    fields: Tuple[FieldAccess, ...]
    result_type: InferenceHole
    by_reference: bool
    def format(self, fmt: Formatter):
        fmt.named_record("FromGlobal", [
            ("token", self.token),
            ("var", self.var),
            ("type", self.taip),
            ("fields", format.Seq(self.fields)),
            ("result-type", self.result_type),
            ("by-reference", self.by_reference)])


@dataclass(frozen=True)
class FromNode(Formattable):
    token: Token
    index: int
    ret: int
    def format(self, fmt: Formatter):
        fmt.unnamed_record("FromNode", [self.token, self.index, self.ret])

@dataclass(frozen=True)
class FromCase(Formattable):
    token: Token
    variant: CustomTypeHandle
    generic_arguments: Tuple[InferenceHole, ...]
    tag: int
    scrutinee: Source | None
    scrutinee_type: InferenceHole
    def format(self, fmt: Formatter):
        fmt.named_record("FromCase", [
            ("token", self.token),
            ("variant", self.variant),
            ("generic-arguments", format.Seq(self.generic_arguments, multi_line=True)),
            ("tag", self.tag),
            ("scrutinee-type", self.scrutinee_type),
            ("scrutinee", format.Optional(self.scrutinee))])

@dataclass(frozen=True)
class FromProxied(Formattable):
    source: Source
    taip: InferenceHole
    @property
    def token(self):
        return self.source.token
    def format(self, fmt: Formatter):
        fmt.unnamed_record("FromProxied", [self.source, self.taip])

@dataclass(frozen=True)
class FromCast(Formattable):
    token: Token
    src_type: InferenceHole
    dst_type: with_holes.Type
    src: Source | None
    def format(self, fmt: Formatter):
        fmt.named_record("FromCast", [
            ("token", self.token),
            ("src-type", self.src_type),
            ("dst-type", self.dst_type),
            ("src", format.Optional(self.src))])

@dataclass(frozen=True)
class FromLoad(Formattable):
    token: Token
    taip: InferenceHole
    src: Source | None
    def format(self, fmt: Formatter):
        fmt.named_record("FromLoad", [
            ("token", self.token),
            ("type", self.taip),
            ("src", format.Optional(self.src))])

@dataclass(frozen=True)
class FromMakeStruct(Formattable):
    token: Token
    name: Token
    type_definition: CustomTypeHandle
    arguments: Tuple[Source, ...]
    generic_arguments: Tuple[InferenceHole, ...]
    taip: InferenceHole
    def format(self, fmt: Formatter):
        fmt.named_record("FromMakeStruct", [
            ("token", self.token),
            ("name", self.name),
            ("type-definition", self.type_definition),
            ("generic-arguments", format.Seq(self.generic_arguments, True)),
            ("arguments", format.Seq(self.arguments, True)),
            ("type", self.taip)])

@dataclass(frozen=True)
class FromMakeVariant(Formattable):
    token: Token
    type_definition: CustomTypeHandle
    generic_arguments: Tuple[InferenceHole, ...]
    taip: InferenceHole
    source: Source | None
    tag: int
    def format(self, fmt: Formatter):
        fmt.named_record("FromMakeVariant", [
            ("token", self.token),
            ("type-definition", self.type_definition),
            ("tag", self.tag),
            ("source", format.Optional(self.source)),
            ("generic-arguments", format.Seq(self.generic_arguments, multi_line=True)),
            ("type", self.taip)])

@dataclass(frozen=True)
class FromCall(Formattable):
    token: Token
    function: FunctionHandle | IntrinsicType
    generic_arguments: Tuple[InferenceHole, ...]
    arguments: Tuple[Source, ...]
    def format(self, fmt: Formatter):
        fmt.named_record("FromCall", [
            ("token", self.token),
            ("function", self.function),
            ("generic-arguments", self.generic_arguments),
            ("arguments", format.Seq(self.arguments, multi_line=True))])

@dataclass(frozen=True)
class FromGetField(Formattable):
    token: Token
    base_type: InferenceHole
    source: Source | None
    fields: Tuple[FieldAccess, ...]
    def format(self, fmt: Formatter):
        fmt.named_record("FromGetField", [
            ("token", self.token),
            ("base-type", self.base_type),
            ("source", format.Optional(self.source)),
            ("fields", format.Seq(self.fields, multi_line=True))])

@dataclass(frozen=True)
class FromFunRef(Formattable):
    token: Token
    function: FunctionHandle
    generic_arguments: Tuple[InferenceHole, ...]
    def format(self, fmt: Formatter):
        fmt.named_record("FromFunRef", [
            ("token", self.token),
            ("function", self.function),
            ("generic-arguments", format.Seq(self.generic_arguments, multi_line=True))])

@dataclass(frozen=True)
class FromAdd(Formattable):
    token: Token
    base: Source | None
    addition: Source | None
    taip: InferenceHole
    def format(self, fmt: Formatter):
        fmt.named_record("FromAdd", [
            ("token", self.token),
            ("base", format.Optional(self.base)),
            ("addition", format.Optional(self.addition)),
            ("type", self.taip)])

type MultiReturnNode = 'PlaceHolder | FromIfEntry | FromIfExit | FromMatchEntry | FromMatchExit | FromCall | FromBlockEntry | FromBlockExit | FromLoopEntry | FromIndirectCall'

@dataclass(frozen=True, eq=True)
class PlaceHolder(Formattable):
    pass

@dataclass(frozen=True, eq=True)
class FromIfEntry(Formattable):
    token: Token
    condition: Source | None
    parameters: Tuple[InferenceHole, ...]
    arguments: Tuple[Source, ...]
    def format(self, fmt: Formatter):
        fmt.named_record("FromIfEntry", [
            ("token", self.token),
            ("condition", format.Optional(self.condition)),
            ("parameters", format.Seq(self.parameters)),
            ("arguments", format.Seq(self.arguments, multi_line=True))])

@dataclass(frozen=True, eq=True)
class FromIfExit(Formattable):
    token: Token
    condition: Source | None
    return_types: Tuple[InferenceHole, ...]
    true_branch_returns: Tuple[Source, ...] | None
    false_branch_returns: Tuple[Source, ...]
    def format(self, fmt: Formatter):
        fmt.named_record("FromIfExit", [
            ("token", self.token),
            ("condition", format.Optional(self.condition)),
            ("return-types", format.Seq(self.return_types, multi_line=True)),
            ("true-branch-returns", format.Optional(format.Seq(self.true_branch_returns, multi_line=True) if self.true_branch_returns is not None else None)),
            ("false-branch-returns", format.Seq(self.false_branch_returns, multi_line=True))])

@dataclass(frozen=True)
class FromMatchEntry(Formattable):
    token: Token
    scrutinee_type: InferenceHole
    parameters: Tuple[InferenceHole, ...]
    scrutinee: Source | None
    arguments: Tuple[Source, ...]
    def format(self, fmt: Formatter):
        fmt.named_record("FromMatchEntry", [
            ("token", self.token),
            ("scrutinee-type", self.scrutinee_type),
            ("parameters", self.parameters),
            ("scrutinee", format.Optional(self.scrutinee)),
            ("arguments", format.Seq(self.arguments, multi_line=True))])

@dataclass(frozen=True)
class ReturnsOfCase(Formattable):
    tag: int | None
    returns: Tuple[Source, ...]
    def format(self, fmt: Formatter):
        fmt.unnamed_record("ReturnsOfCase", [format.Optional(self.tag), format.Seq(self.returns, multi_line=True)])

@dataclass(frozen=True)
class FromMatchExit(Formattable):
    token: Token
    variant: CustomTypeHandle
    return_types: Tuple[InferenceHole, ...]
    scrutinee_type: InferenceHole
    scrutinee: Source | None
    returns: Tuple[ReturnsOfCase, ...]
    def format(self, fmt: Formatter):
        fmt.named_record("FromMatchExit", [
            ("token", self.token),
            ("variant", self.variant),
            ("return-types", format.Seq(self.return_types, multi_line=True)),
            ("scrutinee-type", self.scrutinee_type),
            ("scrutinee", format.Optional(self.scrutinee)),
            ("returns", format.Seq(self.returns, multi_line=True))])

@dataclass(frozen=True)
class FromBlockEntry(Formattable):
    token: Token
    parameters: Tuple[InferenceHole, ...]
    arguments: Tuple[Source, ...]
    def format(self, fmt: Formatter):
        fmt.named_record("FromBlockEntry", [
            ("token", self.token),
            ("parameters", format.Seq(self.parameters)),
            ("arguments", format.Seq(self.arguments, multi_line=True))])

@dataclass(frozen=True)
class BreakReturnSource(Formattable):
    token: Token
    source: Source | None
    def format(self, fmt: Formatter):
        fmt.unnamed_record("BreakReturnSource", [self.token, format.Optional(self.source)])

@dataclass(frozen=True)
class BreakReturns(Formattable):
    sources: Tuple[BreakReturnSource, ...]
    def format(self, fmt: Formatter):
        fmt.named_record("BreakReturns", [("sources", format.Seq(self.sources, multi_line=True))])

@dataclass(frozen=True)
class FromBlockExit(Formattable):
    token: Token
    return_types: Tuple[InferenceHole, ...]
    break_returns: Tuple[BreakReturns, ...]
    def format(self, fmt: Formatter):
        fmt.named_record("FromBlockExit", [
            ("token", self.token),
            ("return-types", format.Seq(self.return_types, multi_line=True)),
            ("break-returns", format.Seq(self.break_returns, multi_line=True))])

@dataclass(frozen=True)
class FromLoopEntry(Formattable):
    token: Token
    parameters: Tuple[InferenceHole, ...]
    arguments: Tuple[Source, ...]
    next_arguments: Tuple[Source, ...]
    def format(self, fmt: Formatter):
        fmt.named_record("FromLoopEntry", [
            ("token", self.token),
            ("parameters", format.Seq(self.parameters)),
            ("arguments", format.Seq(self.arguments, multi_line=True)),
            ("next-arguments", format.Seq(self.next_arguments, multi_line=True))])

@dataclass(frozen=True)
class FromIndirectCall(Formattable):
    token: Token
    return_types: Tuple[InferenceHole, ...]
    parameters: Tuple[InferenceHole, ...]
    function: Source | None
    arguments: Tuple[Source, ...]
    def format(self, fmt: Formatter):
        fmt.named_record("FromIndirectCall", [
            ("token", self.token),
            ("parameters", format.Seq(self.parameters, multi_line=True)),
            ("return-types", format.Seq(self.return_types, multi_line=True)),
            ("function", format.Optional(self.function)),
            ("arguments", format.Seq(self.arguments, multi_line=True))])

