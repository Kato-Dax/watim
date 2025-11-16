from typing import List, Tuple
from dataclasses import dataclass

import format
from format import Formattable, Formatter
from lexer import Token
from parsing.types import Type, CustomTypeType, ForeignType

@dataclass
class NumberWord(Formattable):
    token: Token
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Number", [self.token])

@dataclass
class BreakWord(Formattable):
    token: Token
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Break", [self.token])

type Word = 'NumberWord | StringWord | CallWord | GetWord | RefWord | SetWord | StoreWord | InitWord | CallWord | ForeignCallWord | FunRefWord | IfWord | LoadWord | LoopWord | BlockWord | BreakWord | CastWord | SizeofWord | GetFieldWord | IndirectCallWord | StructWord | StructWordNamed | MatchWord | VariantWord | StackAnnotation | InlineRefWord'
@dataclass
class StringWord(Formattable):
    token: Token
    data: bytearray
    def format(self, fmt: Formatter):
        fmt.unnamed_record("StringWord", [self.token])

@dataclass
class GetWord(Formattable):
    token: Token
    ident: Token
    fields: Tuple[Token, ...]
    def format(self, fmt: Formatter):
        fmt.unnamed_record("GetLocal", [self.token, self.ident, format.Seq(self.fields)])

@dataclass
class RefWord(Formattable):
    token: Token
    ident: Token
    fields: Tuple[Token, ...]
    def format(self, fmt: Formatter):
        fmt.unnamed_record("RefLocal", [self.token, self.ident, format.Seq(self.fields)])

@dataclass
class SetWord(Formattable):
    token: Token
    ident: Token
    fields: Tuple[Token, ...]
    def format(self, fmt: Formatter):
        fmt.unnamed_record("SetLocal", [self.token, self.ident, format.Seq(self.fields)])

@dataclass
class InlineRefWord(Formattable):
    token: Token

@dataclass
class StoreWord(Formattable):
    token: Token
    ident: Token
    fields: Tuple[Token, ...]
    def format(self, fmt: Formatter):
        fmt.unnamed_record("StoreLocal", [self.token, self.ident, format.Seq(self.fields)])

@dataclass
class InitWord(Formattable):
    token: Token
    ident: Token
    def format(self, fmt: Formatter):
        fmt.unnamed_record("InitLocal", [self.token, self.ident])

@dataclass
class ForeignCallWord(Formattable):
    module: Token
    ident: Token
    generic_arguments: Tuple[Type, ...]

@dataclass
class CallWord(Formattable):
    ident: Token
    generic_arguments: Tuple[Type, ...]
    def format(self, fmt: Formatter):
        fmt.unnamed_record("LocalCall", [
            self.ident,
            format.Seq(self.generic_arguments, multi_line=True)])

@dataclass
class FunRefWord(Formattable):
    start: Token
    call: CallWord | ForeignCallWord
    def format(self, fmt: Formatter):
        fmt.unnamed_record("FunRef", [self.start, self.call])

@dataclass
class IfWord(Formattable):
    token: Token
    true_words: 'Words'
    false_words: 'Words | None'
    def format(self, fmt: Formatter):
        fmt.unnamed_record("If", [
            self.token,
            self.true_words,
            format.Optional(self.false_words)])

@dataclass
class LoadWord(Formattable):
    token: Token
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Load", [self.token])

@dataclass
class BlockAnnotation(Formattable):
    parameters: List[Type]
    returns: List[Type]
    def format(self, fmt: Formatter):
        fmt.unnamed_record("BlockAnnotation", [
            format.Seq(self.parameters),
            format.Seq(self.returns)])

@dataclass
class Words(Formattable):
    words: Tuple[Word, ...]
    end: Token
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Words", [
            format.Seq(self.words, multi_line=True),
            self.end])

@dataclass
class LoopWord(Formattable):
    token: Token
    words: Words
    annotation: BlockAnnotation | None
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Loop", [
            self.token,
            format.Optional(self.annotation),
            self.words])

@dataclass
class BlockWord(Formattable):
    token: Token
    words: Words
    annotation: BlockAnnotation | None
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Block", [
            self.token,
            format.Optional(self.annotation),
            self.words])

@dataclass
class CastWord(Formattable):
    token: Token
    taip: Type
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Cast", [
            self.token, self.taip])

@dataclass
class SizeofWord(Formattable):
    token: Token
    taip: Type

@dataclass
class GetFieldWord(Formattable):
    token: Token
    fields: Tuple[Token, ...]
    def format(self, fmt: Formatter):
        fmt.unnamed_record("GetField", [self.token, format.Seq(self.fields)])

@dataclass
class IndirectCallWord(Formattable):
    token: Token
    parameters: Tuple[Type, ...]
    returns: Tuple[Type, ...]
    def format(self, fmt: Formatter):
        fmt.named_record("IndirectCall", [
            ("token", self.token),
            ("parameters", format.Seq(self.parameters, multi_line=True)),
            ("returns", format.Seq(self.returns, multi_line=True))])

@dataclass
class StructWordNamed(Formattable):
    token: Token
    name: Token
    taip: CustomTypeType | ForeignType
    words: Tuple[Word, ...]

@dataclass
class StructWord(Formattable):
    token: Token
    name: Token
    taip: CustomTypeType | ForeignType

@dataclass
class VariantWord(Formattable):
    token: Token
    taip: CustomTypeType | ForeignType
    case: Token
    def format(self, fmt: Formatter):
        return fmt.unnamed_record("MakeVariant", [self.token, self.taip, self.case])

@dataclass
class MatchCase(Formattable):
    case: Token
    module: Token | None
    variant: Token | None
    name: Token
    words: Tuple[Word, ...]
    def format(self, fmt: Formatter):
        fmt.unnamed_record("MatchCase", [
            self.case,
            format.Optional(self.module),
            format.Optional(self.variant),
            self.name,
            format.Seq(self.words)])

@dataclass
class MatchWord(Formattable):
    token: Token
    cases: Tuple[MatchCase, ...]
    default: MatchCase | None
    def format(self, fmt: Formatter):
        fmt.named_record("Match", [
            ("token", self.token),
            ("cases", format.Seq(self.cases, multi_line=True)),
            ("default", format.Optional(self.default))])

@dataclass
class StackAnnotation(Formattable):
    token: Token
    types: Tuple[Type, ...]
    def format(self, fmt: Formatter):
        fmt.unnamed_record("StackAnnotation", [
            self.token,
            format.Seq(self.types)])
