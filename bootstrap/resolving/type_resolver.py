from typing import Dict, Tuple, Sequence, NoReturn, Iterable, assert_never
from dataclasses import dataclass

from indexed_dict import IndexedDict
from lexer import Token
import parsing.parser as parsed
from parsing.types import I8, I32, I64, Bool, GenericType, HoleType
from resolving.types import Type, NamedType, PtrType, FunctionType, CustomTypeType, CustomTypeHandle
import resolving.type_without_holes as without_holes
from resolving.top_items import Import, TypeDefinition, Struct, Variant
from resolving.module import Module, ResolveException

@dataclass
class TypeLookup:
    module: int | None
    modules: Tuple[Module, ...]
    type_definitions: IndexedDict[str, TypeDefinition] | None
    def lookup(self, handle: CustomTypeHandle) -> TypeDefinition:
        if self.module is not None and self.module == handle.module and self.type_definitions is not None:
            return self.type_definitions.index(handle.index)
        return self.modules[handle.module].type_definitions.index(handle.index)

    def types_pretty_bracketed(self, types: Sequence[Type] | Sequence[without_holes.Type]) -> str:
        return f"[{self.types_pretty(types)}]"

    def types_pretty(self, types: Sequence[Type] | Sequence[without_holes.Type]) -> str:
        s = ""
        for i, taip in enumerate(types):
            s += self.type_pretty(taip)
            if i + 1 < len(types):
                s += ", "
        return s

    def type_pretty(self, taip: Type | without_holes.Type) -> str:
        if isinstance(taip, I8):
            return "i8"
        if isinstance(taip, I32):
            return "i32"
        if isinstance(taip, I64):
            return "i64"
        if isinstance(taip, Bool):
            return "bool"
        if isinstance(taip, PtrType) or isinstance(taip, without_holes.PtrType):
            return f".{self.type_pretty(taip.child)}"
        if isinstance(taip, CustomTypeType) or isinstance(taip, without_holes.CustomTypeType):
            s = self.lookup(taip.type_definition).name.lexeme
            if len(taip.generic_arguments) != 0:
                return f"{s}<{self.types_pretty(taip.generic_arguments)}>"
            return s
        if isinstance(taip, FunctionType) or isinstance(taip, without_holes.FunctionType):
            return f"({self.types_pretty(taip.parameters)} -> {self.types_pretty(taip.returns)})"
        if isinstance(taip, GenericType):
            return taip.token.lexeme
        if isinstance(taip, HoleType):
            return taip.token.lexeme

    def find_directly_recursive_types(self) -> Iterable[CustomTypeHandle]:
        if self.module is None or self.type_definitions is None:
            return
        for i in range(len(self.type_definitions)):
            handle = CustomTypeHandle(self.module, i)
            if self.is_directly_recursive(handle, ()):
                yield handle

    def is_directly_recursive(self, handle: CustomTypeHandle, stack: Tuple[CustomTypeHandle, ...] = ()) -> bool:
        if handle in stack:
            return True
        taip = self.lookup(handle)
        match taip:
            case Struct():
                for field in taip.fields:
                    if isinstance(field.taip, without_holes.CustomTypeType):
                        if self.is_directly_recursive(field.taip.type_definition, (handle,) + stack):
                            return True
            case Variant():
                for case in taip.cases:
                    if isinstance(case.taip, without_holes.CustomTypeType):
                        if self.is_directly_recursive(case.taip.type_definition, (handle,) + stack):
                            return True
            case other:
                assert_never(other)
        return False

@dataclass
class TypeResolver:
    module_id: int
    module_path: str
    imports: Dict[str, Tuple[Import, ...]]
    module: parsed.Module
    modules: IndexedDict[str, Module]

    def abort(self, token: Token, message: str) -> NoReturn:
        raise ResolveException(self.module_path, token, message)

    def resolve_named_type(self, taip: parsed.NamedType) -> NamedType:
        return NamedType(taip.name, self.resolve_type(taip.taip))

    def resolve_type(self, taip: parsed.Type) -> Type:
        if isinstance(taip, parsed.PtrType):
            return PtrType(self.resolve_type(taip.child))
        if isinstance(taip, parsed.CustomTypeType) or isinstance(taip, parsed.ForeignType):
            return self.resolve_custom_type(taip)
        if isinstance(taip, parsed.FunctionType):
            return FunctionType(
                taip.token,
                self.resolve_types(taip.parameters),
                self.resolve_types(taip.returns),
            )
        return taip

    def resolve_types(self, types: Sequence[parsed.Type]) -> Tuple[Type, ...]:
        return tuple(self.resolve_type(taip) for taip in types)

    def resolve_custom_type(self, taip: parsed.CustomTypeType | parsed.ForeignType) -> CustomTypeType:
        generic_arguments = self.resolve_types(taip.generic_arguments) if taip.generic_arguments is not None else None
        if isinstance(taip, parsed.CustomTypeType):
            handle = self.resolve_custom_type_name(taip.name)
            if handle.module == self.module_id:
                expected = len(self.module.type_definitions[handle.index].generic_parameters)
            else:
                expected = len(self.modules.index(handle.module).type_definitions.index(handle.index).generic_parameters)
            if generic_arguments is not None and len(generic_arguments) != expected:
                self.generic_arguments_mismatch_error(taip.name, expected, len(generic_arguments))
            if generic_arguments is None:
                generic_arguments = tuple(HoleType(taip.name) for _ in range(expected))
            return CustomTypeType(handle, generic_arguments)
        if isinstance(taip, parsed.ForeignType):
            if taip.module.lexeme not in self.imports:
                self.abort(taip.module, "module not found")
            for imp in self.imports[taip.module.lexeme]:
                module = self.modules.index(imp.module)
                for j,custom_type in enumerate(module.type_definitions.values()):
                    if custom_type.name.lexeme == taip.name.lexeme:
                        if generic_arguments is not None and len(custom_type.generic_parameters) != len(generic_arguments):
                            self.generic_arguments_mismatch_error(taip.name, len(custom_type.generic_parameters), len(generic_arguments))
                        if generic_arguments is None:
                            generic_arguments = tuple(HoleType(taip.module) for _ in custom_type.generic_parameters)
                        return CustomTypeType(CustomTypeHandle(imp.module, j), generic_arguments)
            self.abort(taip.name, "type not found")

    def resolve_custom_type_name(self, name: Token) -> CustomTypeHandle:
        for (type_index, type_definition) in enumerate(self.module.type_definitions):
            if type_definition.name.lexeme == name.lexeme:
                return CustomTypeHandle(self.module_id, type_index)
        for imports_with_same_qualifier in self.imports.values():
            for imp in imports_with_same_qualifier:
                for item in imp.items:
                    if isinstance(item.handle, CustomTypeHandle) and item.name.lexeme == name.lexeme:
                        return item.handle
        self.abort(name, "type not found")

    def generic_arguments_mismatch_error(self, token: Token, expected: int, actual: int):
        msg = f"expected {expected} generic arguments, not {actual}"
        self.abort(token, msg)

