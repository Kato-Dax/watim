from typing import Sequence

from format import Formatter
from indexed_dict import IndexedDict

from codegen.ctx import Ctx
from monomorphization import TypeId, type_size, Bool, I8, I32, I64, PtrType, FunType, CustomTypeType, LocalId, Local, GlobalId, ROOT_SCOPE

def generate_var_ident(ctx: Ctx, locals: IndexedDict[LocalId, Local], var_id: LocalId | GlobalId):
    match var_id:
        case LocalId():
            generate_local_ident(ctx.fmt, locals[var_id], var_id)
        case GlobalId():
            ctx.fmt.write("$")
            ctx.fmt.write(ctx.program.lookup_global(var_id).name.lexeme)
            ctx.fmt.write(":")
            ctx.fmt.write(var_id.module)

def generate_local_ident(fmt: Formatter, local: Local, local_id: LocalId):
    fmt.write(f"${local.name.get()}")
    if local_id.scope != ROOT_SCOPE or local_id.shadow != 0:
        fmt.write(f":{local_id.scope.raw}:{local_id.shadow}")

def generate_store(ctx: Ctx, type: TypeId):
    size = type_size(ctx.program.sizes, type)
    if size > 8:
        ctx.fmt.write("i32.const ")
        ctx.fmt.write(size)
        ctx.fmt.write(" memory.copy")
        return
    if size > 4:
        ctx.fmt.write("i64.store")
        return
    if size == 1:
        ctx.fmt.write("i32.store8")
        return
    ctx.fmt.write("i32.store")

def generate_type(ctx: Ctx, type: TypeId):
    size = type_size(ctx.program.sizes, type)
    if size > 4 and size <= 8:
        ctx.fmt.write("i64")
    else:
        ctx.fmt.write("i32")

def generate_type_pretty(ctx: Ctx, type_id: TypeId):
    type = ctx.lookup_type(type_id)
    match type:
        case Bool():
            str = "bool"
        case I8():
            str = "i8"
        case I32():
            str = "i32"
        case I64():
            str = "i64"
        case PtrType():
            ctx.fmt.write(".")
            generate_type_pretty(ctx, type.child)
            return
        case FunType():
            ctx.fmt.write("(")
            for i, parameter in enumerate(type.parameters):
                generate_type_pretty(ctx, parameter)
                if i + 1 != len(type.parameters):
                    ctx.fmt.write(",")
                ctx.fmt.write(" ")
            ctx.fmt.write("->")
            for i, ret in enumerate(type.returns):
                generate_type_pretty(ctx, ret)
                if i + 1 != len(type.returns):
                    ctx.fmt.write(",")
                ctx.fmt.write(" ")
            ctx.fmt.write(")")
            return
        case CustomTypeType():
            str = ctx.lookup_type_definition(type.handle).name.lexeme
    ctx.fmt.write(str)

def generate_parameters_unnamed(ctx: Ctx, parameters: Sequence[TypeId]):
    for parameter in parameters:
        ctx.fmt.write(" (param ")
        generate_type(ctx, parameter)
        ctx.fmt.write(")")

def generate_returns(ctx: Ctx, returns: Sequence[TypeId]):
    for type in returns:
        ctx.fmt.write(" (result ")
        generate_type(ctx, type)
        ctx.fmt.write(")")

def generate_flip_i32_i32(ctx: Ctx):
    ctx.flip_i32_i32_used = True
    ctx.fmt.write("call $intrinsic:flip")

def generate_flip_i32_i64(ctx: Ctx):
    ctx.flip_i32_i64_used = True
    ctx.fmt.write("call $intrinsic:flip-i32-i64")

def generate_flip_i64_i32(ctx: Ctx):
    ctx.flip_i64_i32_used = True
    ctx.fmt.write("call $intrinsic:flip-i64-i32")

def generate_flip_i64_i64(ctx: Ctx):
    ctx.flip_i64_i64_used = True
    ctx.fmt.write("call $intrinsic:flip-i64-i64")

def generate_dup_i32(ctx: Ctx):
    ctx.dup_i32_used = True
    ctx.fmt.write("call $intrinsic:dupi32")

def generate_dup_i64(ctx: Ctx):
    ctx.dup_i64_used = True
    ctx.fmt.write("call $intrinsic:dupi64")

