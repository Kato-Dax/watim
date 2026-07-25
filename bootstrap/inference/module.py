from __future__ import annotations

from dataclasses import dataclass

from format import Formattable
from resolving.top_items import Extern, Global, Import, TypeDefinition

from inference.top_items import Function


@dataclass(frozen=True)
class Module(Formattable):
    imports: dict[str, tuple[Import, ...]]
    type_definitions: tuple[TypeDefinition, ...]
    globals: tuple[Global, ...]
    functions: tuple[Function | Extern, ...]
    static_data: bytes
