from typing import Dict, Tuple
from dataclasses import dataclass

import format
from format import Formattable, Formatter

from indexed_dict import IndexedDict
from lexer import Token
from resolving.top_items import Import, TypeDefinition, Function, Extern, Global, FunctionHandle, CustomTypeHandle

@dataclass
class Module(Formattable):
    path: str
    id: int
    imports: Dict[str, Tuple[Import, ...]]
    type_definitions: IndexedDict[str, TypeDefinition]
    globals: IndexedDict[str, Global]
    functions: IndexedDict[str, Function | Extern]
    static_data: bytes

    def format(self, fmt: Formatter):
        fmt.named_record("Module", [
            ("imports", format.Dict(dict((format.Str(k),v) for k,v in self.imports.items()))),
            ("type-definitions", self.type_definitions.formattable(format.Str, lambda x: x)),
            ("globals", self.globals.formattable(format.Str, lambda x: x)),
            ("functions", self.functions.formattable(format.Str, lambda x: x)),
            ("static-data", format.Str(self.static_data.decode("utf-8")))])

    def lookup_item(self, name: Token) -> FunctionHandle | CustomTypeHandle | None:
        if name.lexeme in self.functions:
            return FunctionHandle(self.id, self.functions.index_of(name.lexeme))
        if name.lexeme in self.type_definitions:
            return CustomTypeHandle(self.id, self.type_definitions.index_of(name.lexeme))
        return None

@dataclass
class ResolveException(Exception):
    path: str
    token: Token
    message: str

    def display(self) -> str:
        line = self.token.line
        column = self.token.column
        return f"{self.path}:{line}:{column}: {self.message}"

