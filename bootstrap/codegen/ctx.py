from typing import Tuple
from dataclasses import dataclass

from format import Formatter

from monomorphization import Monomized, TypeId, Type, CustomTypeHandle, TypeDefinition

@dataclass
class Ctx:
    fmt: Formatter
    program: Monomized
    module_data_offsets: Tuple[int, ...]
    guard_stack: bool
    flip_i32_i32_used: bool
    flip_i32_i64_used: bool
    flip_i64_i32_used: bool
    flip_i64_i64_used: bool
    pack_i32s_used: bool
    unpack_i32s_used: bool
    dup_i32_used: bool
    dup_i64_used: bool

    def write_line(self, line: str):
        self.fmt.write_indent()
        self.fmt.write(line)
        self.fmt.write("\n")

    def lookup_type(self, type_id: TypeId) -> Type:
        type = self.program.types[type_id.index]
        assert type is not None
        return type

    def lookup_type_definition(self, handle: CustomTypeHandle) -> TypeDefinition:
        return self.program.modules.index(handle.module).type_definitions[handle.index]

