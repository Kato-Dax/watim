from typing import List, Tuple, Iterable
from dataclasses import dataclass, field

import format
from format import Formattable, Formatter

from lexer import Token
from parsing.types import PrimitiveType, GenericType, Bool, I8, I32, I64

import resolving.types as wh
from resolving.types import CustomTypeHandle

type Type = PrimitiveType | PtrType | GenericType | CustomTypeType | FunctionType

def with_holes(taip: Type) -> wh.Type:
    match taip:
        case Bool():
            return taip
        case I8():
            return taip
        case I32():
            return taip
        case I64():
            return taip
        case PtrType(child):
            return wh.PtrType(with_holes(child))
        case CustomTypeType(name, type_definition, generic_arguments):
            return wh.CustomTypeType(name, type_definition, tuple(with_holes(t) for t in generic_arguments))
        case FunctionType(token, parameters, returns):
            return wh.FunctionType(token, tuple(with_holes(t) for t in parameters), tuple(with_holes(t) for t in returns))
        case GenericType():
            return taip

def types_with_holes(taips: Iterable[Type]) -> Tuple[wh.Type, ...]:
    return tuple(with_holes(t) for t in taips)

def named_type_with_holes(taip: 'NamedType') -> wh.NamedType:
    return wh.NamedType(taip.name, with_holes(taip.taip))

def named_types_with_holes(taips: Iterable['NamedType']) -> Tuple[wh.NamedType, ...]:
    return tuple(named_type_with_holes(t) for t in taips)

def without_holes(taip: wh.Type) -> Type | Token:
    match taip:
        case Bool():
            return taip
        case I8():
            return taip
        case I32():
            return taip
        case I64():
            return taip
        case wh.PtrType():
            child = without_holes(taip.child)
            if isinstance(child, Token):
                return child
            return PtrType(child)
        case wh.CustomTypeType():
            generic_arguments = types_without_holes(taip.generic_arguments)
            if isinstance(generic_arguments, Token):
                return generic_arguments
            return CustomTypeType(taip.name, taip.type_definition, generic_arguments)
        case wh.FunctionType():
            parameters = types_without_holes(taip.parameters)
            returns = types_without_holes(taip.returns)
            if isinstance(parameters, Token):
                return parameters
            if isinstance(returns, Token):
                return returns
            return FunctionType(taip.token, parameters, returns)
        case GenericType():
            return taip
        case wh.HoleType():
            return taip.token

def types_without_holes(types: Tuple[wh.Type, ...]) -> Tuple[Type, ...] | Token:
    result: List[Type] = []
    for taip in types:
        without = without_holes(taip)
        if isinstance(without, Token):
            return without
        result.append(without)
    return tuple(result)

def with_generics(taip: Type, generics: Tuple[Type, ...]) -> Type:
    match taip:
        case PtrType(child):
            return PtrType(with_generics(child, generics))
        case CustomTypeType(name, type_definition, generic_arguments):
            return CustomTypeType(
                name,
                type_definition,
                tuple(with_generics(arg, generics) for arg in generic_arguments))
        case FunctionType(token, parameters, returns):
            return FunctionType(
                token,
                tuple(with_generics(param, generics) for param in parameters),
                tuple(with_generics(ret, generics)   for ret   in returns))
        case GenericType(token, index):
            return generics[index]
        case other:
            return other

@dataclass(frozen=True, eq=True)
class PtrType(Formattable):
    child: Type
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Ptr", [self.child])

@dataclass(eq=True, frozen=True)
class CustomTypeType(Formattable):
    name: Token = field(compare=False)
    type_definition: CustomTypeHandle
    generic_arguments: Tuple[Type, ...]
    def format(self, fmt: Formatter):
        fmt.unnamed_record("CustomType", [
            self.type_definition.module,
            self.type_definition.index,
            format.Seq(self.generic_arguments)])

@dataclass(frozen=True, eq=True)
class FunctionType(Formattable):
    token: Token = field(compare=False)
    parameters: Tuple[Type, ...]
    returns: Tuple[Type, ...]
    def format(self, fmt: Formatter):
        fmt.unnamed_record("FunType", [self.token, format.Seq(self.parameters), format.Seq(self.returns)])

@dataclass(frozen=True)
class NamedType(Formattable):
    name: Token
    taip: Type
    def format(self, fmt: Formatter):
        fmt.unnamed_record("NamedType", [self.name, self.taip])
    def __eq__(self, other: object) -> bool:
        return isinstance(other, NamedType) and other.name.lexeme == self.name.lexeme and other.taip == self.taip

