from dataclasses import dataclass

import format
from format import Formattable, Formatter
from indexed_dict import IndexedDict

from lexer import Token
from resolving import FunctionSignature, LocalId, LocalName, Extern as Extern, Global as Global
from resolving.type_without_holes import Type

from inference.words import Scope

@dataclass(frozen=True)
class Local(Formattable):
    name: LocalName
    type: Type
    is_parameter: bool
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Local", [self.name, self.type, self.is_parameter])

@dataclass(frozen=True)
class Function(Formattable):
    name: Token
    export: Token | None
    signature: FunctionSignature
    locals: IndexedDict[LocalId, Local]
    body: Scope
    def format(self, fmt: Formatter):
        fmt.named_record("Function", [
            ("name", self.name),
            ("export", format.Optional(self.export)),
            ("signature", self.signature),
            ("locals", self.locals.formattable(lambda k: k, lambda v: v)),
            ("body", self.body)])
