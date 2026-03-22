from format import Formatter
from util import align_to
from indexed_dict import IndexedDict

from lexer import Token
from resolving import ScopeId, ROOT_SCOPE
from monomorphization import Monomized, Extern, Signature, type_size, can_live_in_reg, Local, LocalId, Function, local_lives_in_memory

from codegen.common import generate_type, generate_type_pretty, generate_returns
from codegen.ctx import Ctx
from codegen.words import generate_words

def generate(fmt: Formatter, program: Monomized, guard_stack: bool):
    fmt.write("(module\n")
    fmt.indent()

    static_data_offsets = []
    all_static_data = bytearray()
    for module in program.modules.values():
        static_data_offsets.append(len(all_static_data))
        all_static_data.extend(module.static_data)

    ctx = Ctx(fmt, program, tuple(static_data_offsets), guard_stack, False, False, False, False, False, False, False, False)

    for module_id, module in enumerate(program.modules.values()):
        for function in module.functions:
            if isinstance(function, Extern):
                generate_extern(ctx, function, module_id)

    ctx.write_line("(memory 1 65536)")
    ctx.write_line("(export \"memory\" (memory 0))")

    generate_function_table(ctx)
    stack_start = align_to(generate_globals(ctx, align_to(len(all_static_data), 4)), 4)

    fmt.write_indent()
    fmt.write("(global $stac:k (mut i32) (i32.const ")
    fmt.write(stack_start)
    fmt.write("))\n")

    if guard_stack:
        fmt.write_indent()
        fmt.write("(global $stack-siz:e (mut i32) (i32.const 65536))\n")

    generate_data(fmt, bytes(all_static_data))
    generate_functions(ctx)
    generate_intrinsic_functions(ctx)
    fmt.dedent()
    fmt.write(")")

def generate_signature(ctx: Ctx, signature: Signature, export: str | Token | None, module: int, name: Token, instance: int, locals: IndexedDict[LocalId, Local]):
    ctx.fmt.write(f"func ${module}:{name.lexeme}")
    if instance != 0:
        ctx.fmt.write(f":{instance}")
    if export is not None:
        ctx.fmt.write(f" (export {export.lexeme if isinstance(export, Token) else export})")
    for parameter in signature.parameters:
        ctx.fmt.write(" (param $")
        for local in locals.values():
            if local.is_parameter and local.name.get() == parameter.name.lexeme:
                if local_lives_in_memory(ctx.program.sizes, local) and can_live_in_reg(ctx.program.sizes, local.type) and type_size(ctx.program.sizes, local.type) > 4:
                    ctx.fmt.write("v:")
                break
        ctx.fmt.write(f"{parameter.name.lexeme} ")
        generate_type(ctx, parameter.taip)
        ctx.fmt.write(")")
    generate_returns(ctx, signature.returns)

def generate_extern(ctx: Ctx, extern: Extern, module_id: int):
    ctx.fmt.write_indent()
    ctx.fmt.write("(import ")
    ctx.fmt.write(extern.extern_module)
    ctx.fmt.write(" ")
    ctx.fmt.write(extern.extern_name)
    ctx.fmt.write(" (")
    generate_signature(ctx, extern.signature, None, module_id, extern.name, 0, IndexedDict())
    ctx.fmt.write("))\n")

def generate_function_table(ctx: Ctx) -> None:
    if len(ctx.program.function_table) == 0:
        ctx.write_line("(table funcref (elem))")
        return
    ctx.write_line("(table funcref (elem $intrinsic:flip")
    ctx.fmt.indent()
    ctx.fmt.write_indent()
    for i, handle in enumerate(ctx.program.function_table):
        module = ctx.program.modules.index(handle.module)
        function = module.functions[handle.index]
        if isinstance(function, Extern):
            name = "generate_function_table:TODO"
        else:
            assert(handle.instance is not None)
            instance = function[handle.instance]
            if handle.instance == 0:
                name = f"${handle.module}:{instance.name.lexeme}"
            else:
                name = f"${handle.module}:{instance.name.lexeme}:{handle.instance}"
        ctx.fmt.write(name)
        if i + 1 != len(ctx.program.function_table):
            ctx.fmt.write(" ")
    ctx.fmt.write("))\n")
    ctx.fmt.dedent()

def generate_globals(ctx: Ctx, static_data_len: int) -> int:
    for module_id, module in enumerate(ctx.program.modules.values()):
        for globl in module.globals:
            size = type_size(ctx.program.sizes, globl.type)
            lives_in_memory = globl.reffed or not can_live_in_reg(ctx.program.sizes, globl.type)

            ctx.fmt.write_indent()
            ctx.fmt.write("(global $")
            ctx.fmt.write(globl.name.lexeme)
            ctx.fmt.write(":").write(module_id).write(" ")
            if lives_in_memory:
                ctx.fmt.write("i32")
            else:
                ctx.fmt.write("(mut ")
                generate_type(ctx, globl.type)
                ctx.fmt.write(")")
            ctx.fmt.write(" (")
            if lives_in_memory:
                ctx.fmt.write(f"i32.const {static_data_len}")
            else:
                generate_type(ctx, globl.type)
                ctx.fmt.write(".const 0")
            ctx.fmt.write("))\n")
            if lives_in_memory:
                static_data_len += size
    return static_data_len

def generate_data(fmt: Formatter, data: bytes) -> None:
    fmt.write_indent()
    fmt.write("(data (i32.const 0) \"")
    def escape_char(char: int) -> str:
        if char == b"\\"[0]:
           return "\\\\"
        if char == b"\""[0]:
            return "\\\""
        if char == b"\t"[0]:
           return "\\t"
        if char == b"\r"[0]:
           return "\\r"
        if char == b"\n"[0]:
           return "\\n"
        if char >= 32 and char <= 126:
           return chr(char)
        hex_digits = "0123456789abcdef"
        return f"\\{hex_digits[char >> 4]}{hex_digits[char & 15]}"
    for char in data:
        fmt.write(escape_char(char))
    fmt.write("\")\n")

def generate_functions(ctx: Ctx):
    for module_id, module in enumerate(ctx.program.modules.values()):
        for function in module.functions:
            if isinstance(function, Extern):
                continue
            for instance_id, instance in enumerate(function):
                generate_function(ctx, instance, module_id, instance_id)

def generate_function(ctx: Ctx, function: Function, module: int, instance_id: int):
    ctx.fmt.write_indent()
    ctx.fmt.write("(")
    generate_signature(ctx, function.signature, function.export, module, function.name, instance_id, function.locals)
    if len(function.generic_arguments) > 0:
        ctx.fmt.write(" ;;")
        for taip in function.generic_arguments:
            ctx.fmt.write(" ")
            generate_type_pretty(ctx, taip)
    ctx.fmt.write("\n")
    ctx.fmt.indent()
    generate_locals(ctx, function.locals)
    for i in range(0, function.max_stack_returns):
        ctx.fmt.write_indent()
        ctx.fmt.write(f"(local $s{i}:4 i32) (local $s{i}:8 i64)\n")
    if function.local_copy_space != 0:
        ctx.fmt.write_indent()
        ctx.fmt.write("(local $locl-copy-spac:e i32)\n")

    uses_stack = function.local_copy_space != 0 or any_local_lives_in_memory(ctx, function.locals)
    if uses_stack:
        ctx.fmt.write_indent()
        ctx.fmt.write("(local $stac:k i32)\n")
        ctx.fmt.write_indent()
        ctx.fmt.write("global.get $stac:k local.set $stac:k\n")

    if function.local_copy_space != 0:
        generate_memory_slot(ctx, "locl-copy-spac:e", function.local_copy_space, ROOT_SCOPE, 0)
    generate_memory_slots_for_locals(ctx, function.locals)
    if uses_stack and ctx.guard_stack:
        ctx.write_line("call $stack-overflow-guar:d")
    generate_words(ctx, module, function.locals, function.body.words)
    if uses_stack:
        ctx.write_line("local.get $stac:k global.set $stac:k")
    ctx.fmt.dedent()
    ctx.write_line(")")

def any_local_lives_in_memory(ctx: Ctx, locals: IndexedDict[LocalId, Local]) -> bool:
    return any(local_lives_in_memory(ctx.program.sizes, local) for local in locals.values())

def generate_memory_slots_for_locals(ctx: Ctx, locals: IndexedDict[LocalId, Local]):
    for local_id, local in locals.items():
        lives_in_memory = local_lives_in_memory(ctx.program.sizes, local)

        if local.is_parameter and lives_in_memory and can_live_in_reg(ctx.program.sizes, local.type):
            ctx.fmt.write_indent()
            ctx.fmt.write("global.get $stac:k global.get $stac:k local.get $")
            if not parameter_can_be_abused_ref(ctx, local):
                ctx.fmt.write("v:")
            ctx.fmt.write(local.name.get()).write(" ")
            generate_type(ctx, local.type)
            ctx.fmt.write(".store local.tee $").write(local.name.get())
            ctx.fmt.write(" i32.const ").write(type_size(ctx.program.sizes, local.type))
            ctx.fmt.write(" i32.add global.set $stac:k\n")

        if not local.is_parameter and lives_in_memory:
            generate_memory_slot(ctx, local.name.get(), type_size(ctx.program.sizes, local.type), local_id.scope, local_id.shadow)

def parameter_needs_moved_into_memory(ctx: Ctx, local: Local) -> bool:
    assert local.is_parameter
    return local.reffed and can_live_in_reg(ctx.program.sizes, local.type)

def parameter_can_be_abused_ref(ctx: Ctx, local: Local) -> bool:
    size = type_size(ctx.program.sizes, local.type)
    return size <= 4 or size > 8

def generate_locals(ctx: Ctx, locals: IndexedDict[LocalId, Local]) -> None:
    for local_id, local in locals.items():
        if local.is_parameter:
            if parameter_needs_moved_into_memory(ctx, local) and not parameter_can_be_abused_ref(ctx, local):
                ctx.write_line(f"(local ${local.name.get()} i32)")
            continue
        local = locals[local_id]
        ctx.fmt.write_indent()
        ctx.fmt.write(f"(local ${local.name.get()}")
        if local_id.scope != ROOT_SCOPE or local_id.shadow != 0:
            ctx.fmt.write(f":{local_id.scope}:{local_id.shadow}")
        ctx.fmt.write(" ")
        if local_lives_in_memory(ctx.program.sizes, local):
            ctx.fmt.write("i32")
        else:
            generate_type(ctx, local.type)
        ctx.fmt.write(")\n")

def generate_memory_slot(ctx: Ctx, name: str, size: int, scope: ScopeId, shadow: int):
    ctx.fmt.write_indent()
    ctx.fmt.write("global.get $stac:k global.get $stac:k i32.const ")
    ctx.fmt.write(align_to(size, 4))
    ctx.fmt.write(" i32.add global.set $stac:k local.set $")
    ctx.fmt.write(name)
    if scope.raw != 0 or shadow != 0:
        ctx.fmt.write(":").write(scope.raw).write(":").write(shadow)
    ctx.fmt.write("\n")

def generate_intrinsic_functions(ctx: Ctx):
    ctx.write_line("(func $intrinsic:flip (param $a i32) (param $b i32) (result i32 i32) local.get $b local.get $a)")
    if ctx.flip_i32_i64_used:
        ctx.write_line("(func $intrinsic:flip-i32-i64 (param $a i32) (param $b i64) (result i64 i32) local.get $b local.get $a)")
    if ctx.flip_i64_i32_used:
        ctx.write_line("(func $intrinsic:flip-i64-i32 (param $a i64) (param $b i32) (result i32 i64) local.get $b local.get $a)")
    if ctx.flip_i64_i64_used:
        ctx.write_line("(func $intrinsic:flip-i64-i64 (param $a i64) (param $b i64) (result i64 i64) local.get $b local.get $a)")
    ctx.write_line("(func $intrinsic:dupi32 (param $a i32) (result i32 i32) local.get $a local.get $a)")
    if ctx.dup_i64_used:
        ctx.write_line("(func $intrinsic:dupi64 (param $a i64) (result i64 i64) local.get $a local.get $a)")
    ctx.write_line("(func $intrinsic:rotate-left (param $a i32) (param $b i32) (param $c i32) (result i32 i32 i32) local.get $b local.get $c local.get $a)")
    if ctx.pack_i32s_used:
        ctx.write_line("(func $intrinsic:pack-i32s (param $a i32) (param $b i32) (result i64) local.get $a i64.extend_i32_u local.get $b i64.extend_i32_u i64.const 32 i64.shl i64.or)")
    if ctx.unpack_i32s_used:
        ctx.write_line("(func $intrinsic:unpack-i32s (param $a i64) (result i32) (result i32) local.get $a i32.wrap_i64 local.get $a i64.const 32 i64.shr_u i32.wrap_i64)")
    if ctx.guard_stack:
        ctx.write_line("(func $stack-overflow-guar:d i32.const 1 global.get $stac:k global.get $stack-siz:e i32.lt_u i32.div_u drop)")

