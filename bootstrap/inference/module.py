from dataclasses import dataclass
from typing import Tuple, Dict

from format import Formattable

from resolving.top_items import Extern, Import, Global, TypeDefinition
from inference.top_items import Function

@dataclass(frozen=True)
class Module(Formattable):
    imports: Dict[str, Tuple[Import, ...]]
    type_definitions: Tuple[TypeDefinition, ...]
    globals: Tuple[Global, ...]
    functions: Tuple[Function | Extern, ...]
    static_data: bytes
