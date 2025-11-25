from typing import List, Dict, Tuple, Iterable, assert_never
from dataclasses import dataclass

import format
from format import Formattable, Formatter

import sys
import copy

from util import Ref

from lexer import Token
from parsing.types import Bool, I32, I8

import resolving.module as resolved
import resolving.type_without_holes as without_holes
from resolving.type_without_holes import Type, CustomTypeHandle
import resolving.types as with_holes
from resolving.top_items import FunctionSignature, LocalName, Global as ResolvedGlobal, TypeDefinition, Variant, Struct
from resolving.words import LocalId, Scope as ResolvedScope, Word as ResolvedWord, GlobalId, IntrinsicWord as ResolvedIntrinsicWord, IntrinsicType, IfWord as ResolvedIfWord, MatchWord as ResolvedMatchWord
import resolving.words as resolved_words

import unstacking.word as words
from unstacking.word import InferenceHole, InferenceFieldHole, FieldAccess, Scope, Word
from unstacking.source import Source, MultiReturnNode
import unstacking.source as source
from unstacking.voids import StackVoid, NonSpecificVoid, CallVoid, SetGlobalVoid, StoreVoid, IndirectCallVoid
from unstacking.stack import Stack

@dataclass(frozen=True)
class Assignment(Formattable):
    token: Token
    source: Source | None
    fields: Tuple[FieldAccess, ...]
    taip: InferenceHole
    is_store: bool
    def format(self, fmt: Formatter):
        fmt.named_record("Assignment", [
            ("token", self.token),
            ("source", format.Optional(self.source)),
            ("fields", format.Seq(self.fields, multi_line=True)),
            ("type", self.taip),
            ("is-store", self.is_store)])

@dataclass
class Local(Formattable):
    name: LocalName
    taip: InferenceHole
    parameter: Type | None
    assignments: List[Assignment]
    reffed: bool
    assignments_checked: bool
    def format(self, fmt: Formatter):
        fmt.named_record("Local", [
            ("name", self.name),
            ("type", self.taip),
            ("parameter", format.Optional(self.parameter)),
            ("reffed", self.reffed),
            ("assignments", format.Seq(self.assignments, multi_line=True)),
            ("assignments-checked", self.assignments_checked)])

@dataclass(frozen=True)
class Holes(Formattable):
    holes: List[Type | None]

    def fill(self, hole: InferenceHole, known: Type):
        while len(self.holes) <= hole.index:
            self.holes.append(None)
        self.holes[hole.index] = known

    def lookup(self, hole: InferenceHole) -> Type | None:
        if hole.index >= len(self.holes):
            return None
        return self.holes[hole.index]

    def format(self, fmt: Formatter):
        if len(self.holes) == 0:
            fmt.write("(Holes)")
            return
        fmt.write("(Holes")
        fmt.indent()
        for i,hole in enumerate(self.holes):
            if i == 0:
                fmt.write("\n")
            else:
                fmt.write(",\n")
            fmt.write_indent()
            fmt.write(i, "=", format.Optional(hole))
        fmt.dedent()
        fmt.write(")")

@dataclass(frozen=True)
class Function(Formattable):
    name: Token
    export: Token | None
    signature: FunctionSignature
    locals: Dict[LocalId, Local]
    voids: Tuple[StackVoid, ...]
    holes: Holes
    nodes: Tuple[MultiReturnNode, ...]
    body: Scope
    returns: Tuple[Source, ...] | None
    def format(self, fmt: Formatter):
        fmt.named_record("Function", [
            ("name", self.name),
            ("export", format.Optional(self.export)),
            ("signature", self.signature),
            ("locals", format.Dict(dict((k,v) for k,v in self.locals.items()))),
            ("voids", format.Seq(self.voids, multi_line=True)),
            ("holes", self.holes),
            ("nodes", format.Seq(self.nodes, multi_line=True)),
            ("body", self.body),
            ("returns", format.Optional(None if self.returns is None else format.Seq(self.returns, multi_line=True)))])

def unstack_function(modules: List[resolved.Module], function: resolved.Function) -> Function:
    stack = Stack.root()

    unstacker = Unstacker(
        locals={},
        modules=modules,
        voids=[],
        holes=Holes([]),
        multi_return_nodes=[],
        next_inference_hole_index=Ref(0),
        next_inference_field_hole_index=Ref(0),
        break_stacks=None,
        block_returns=None,
        struct_init_type=None,
        struct_field_init_arguments=[],
        reachable=True
    )

    for local_id, local in function.locals.items():
        unstacker.locals[local_id] = Local(
            name=local.name,
            parameter=local.parameter,
            taip=unstacker.fresh_hole(local.name.token()),
            assignments=[],
            reffed=False,
            assignments_checked=False,
        )

    body = unstacker.unstack_scope(stack, function.body)

    return Function(
        name=function.name,
        export=function.export_name,
        locals=unstacker.locals,
        voids=tuple(unstacker.voids),
        signature=function.signature,
        holes=unstacker.holes,
        nodes=tuple(unstacker.multi_return_nodes),
        body=body,
        returns=tuple(stack.positive) if unstacker.reachable else None
    )

@dataclass(frozen=True)
class BreakStack(Formattable):
    token: Token
    sources: Tuple[Source, ...]
    reachable: bool

@dataclass
class Unstacker:
    locals: Dict[LocalId, Local]
    modules: List[resolved.Module]
    voids: List[StackVoid]
    holes: Holes
    multi_return_nodes: List[MultiReturnNode]
    next_inference_hole_index: Ref[int]
    next_inference_field_hole_index: Ref[int]
    break_stacks: List[BreakStack] | None
    block_returns: Tuple[InferenceHole, ...] | None
    struct_init_type: InferenceHole | None
    struct_field_init_arguments: List[Source | None]
    reachable: bool

    def with_cleared_reachable_flag(self) -> 'Unstacker':
        new = copy.copy(self)
        new.reachable = True
        return new

    def with_struct_init(self, taip: InferenceHole, arguments: List[Source | None]) -> 'Unstacker':
        new = copy.copy(self)
        new.struct_init_type = taip
        new.struct_field_init_arguments = arguments
        return new

    def with_break_stacks(self, break_stacks: List[BreakStack], block_returns: Tuple[InferenceHole, ...] | None) -> 'Unstacker':
        new = copy.copy(self)
        new.break_stacks = break_stacks
        new.block_returns = block_returns
        return new

    def lookup_global(self, global_id: GlobalId) -> ResolvedGlobal:
        return self.modules[global_id.module].globals.index(global_id.index)

    def lookup_type_definition(self, handle: CustomTypeHandle) -> TypeDefinition:
        return self.modules[handle.module].type_definitions.index(handle.index)

    def lookup_signature(self, handle: resolved.FunctionHandle) -> FunctionSignature:
        return self.modules[handle.module].functions.index(handle.index).signature

    def pre_add_node(self) -> int:
        self.multi_return_nodes.append(source.PlaceHolder())
        return len(self.multi_return_nodes) - 1

    def add_node(self, node: MultiReturnNode) -> int:
        self.multi_return_nodes.append(node)
        return len(self.multi_return_nodes) - 1

    def fill_node(self, index: int, node: MultiReturnNode):
        assert(self.multi_return_nodes[index] == source.PlaceHolder())
        self.multi_return_nodes[index] = node

    def unstack_scope(self, stack: Stack, body: ResolvedScope) -> Scope:
        words = self.unstack_words(stack, body.words)
        return Scope(body.id, words)

    def unstack_words(self, stack: Stack, remaining: List[ResolvedWord] | Iterable[ResolvedWord]) -> Tuple[Word, ...]:
        if not isinstance(remaining, List):
            remaining = list(remaining)
        unstacked: List[Word] = []
        while len(remaining) != 0:
            word = remaining.pop(0)
            unstacked.append(self.unstack_word(stack, word, remaining))
        return tuple(unstacked)

    def unstack_word(self, stack: Stack, word: ResolvedWord, remaining: List[ResolvedWord]) -> Word:
        match word:
            case resolved_words.GetLocal():
                return self.unstack_get_local(stack, word)
            case resolved_words.NumberWord():
                stack.push(source.FromNumber(word.token))
                return word
            case resolved_words.IntrinsicWord():
                return self.unstack_intrinsic(stack, word)
            case resolved_words.InitLocal():
                return self.unstack_init_local(stack, word)
            case resolved_words.IfWord():
                return self.unstack_if(stack, word, remaining)
            case resolved_words.RefLocal():
                return self.unstack_ref_local(stack, word)
            case resolved_words.MatchWord():
                return self.unstack_match(stack, word)
            case resolved_words.CastWord():
                return self.unstack_cast(stack, word)
            case resolved_words.CallWord():
                return self.unstack_call(stack, word)
            case resolved_words.SetLocal():
                return self.unstack_set_local(stack, word)
            case resolved_words.StringWord():
                stack.push(source.FromString(word.token))
                stack.push(source.FromNumber(word.token))
                return word
            case resolved_words.GetFieldWord():
                return self.unstack_get_field(stack, word)
            case resolved_words.SizeofWord():
                stack.push(source.FromNumber(word.token))
                return word
            case resolved_words.LoadWord():
                return self.unstack_load(stack, word)
            case resolved_words.StructWordNamed():
                return self.unstack_make_struct_named(stack, word)
            case resolved_words.StructFieldInitWord():
                return self.unstack_field_init(stack, word)
            case resolved_words.VariantWord():
                return self.unstack_make_variant(stack, word)
            case resolved_words.BlockWord():
                return self.unstack_block(stack, word)
            case resolved_words.BreakWord():
                return self.unstack_break(stack, word)
            case resolved_words.LoopWord():
                return self.unstack_loop(stack, word)
            case resolved_words.IndirectCallWord():
                return self.unstack_indirect_call(stack, word)
            case resolved_words.StructWord():
                return self.unstack_make_struct(stack, word)
            case resolved_words.StoreWord():
                return self.unstack_store_local(stack, word)
            case resolved_words.FunRefWord():
                return self.unstack_fun_ref(stack, word)
        print(word, file=sys.stderr)
        # assert_never(word)
        assert False

    def unstack_fun_ref(self, stack: Stack, word: resolved_words.FunRefWord) -> Word:
        signature = self.lookup_signature(word.call.function)
        generic_arguments = self.fresh_holes(word.call.name, len(signature.generic_parameters))
        if word.call.generic_arguments is not None:
            for generic_argument, hole in zip(word.call.generic_arguments, generic_arguments):
                generic_argument_without_hole = without_holes.without_holes(generic_argument)
                if isinstance(generic_argument_without_hole, Token):
                    continue
                self.holes.fill(hole, generic_argument_without_hole)

        stack.push(source.FromFunRef(word.call.name, word.call.function, generic_arguments))

        return words.FunRef(word.call.name, word.call.function, generic_arguments)

    def unstack_store_local(self, stack: Stack, word: resolved_words.StoreWord) -> Word:
        src = stack.pop()
        fields = self.unstack_field_accesses(word.fields)
        field_type = self.fresh_hole(word.name)
        if isinstance(word.var, LocalId):
            local = self.locals[word.var]
            local.assignments.append(Assignment(word.name, src, fields, field_type, True))
            return words.StoreLocal(var=word.var, name=word.name, fields=fields, field_type=field_type)
        if isinstance(word.var, GlobalId):
            # TODO
            assert False
        assert_never(word.var)

    def unstack_make_struct(self, stack: Stack, word: resolved_words.StructWord) -> Word:
        struct = self.lookup_type_definition(word.taip.type_definition)
        assert(not isinstance(struct, Variant))
        arguments = stack.pop_n(len(struct.fields))
        generic_arguments = self.fresh_holes(word.token, len(struct.generic_parameters))
        taip = self.fresh_hole(word.token)
        for generic_argument, hole in zip(word.taip.generic_arguments, generic_arguments):
            generic_argument_without_hole = without_holes.without_holes(generic_argument)
            if isinstance(generic_argument_without_hole, Token):
                continue
            self.holes.fill(hole, generic_argument_without_hole)
        stack.push(source.FromMakeStruct(
            token=word.token,
            name=word.name,
            type_definition=word.taip.type_definition,
            taip=taip,
            generic_arguments=generic_arguments,
            arguments=arguments))

        return words.MakeStruct(word.token, word.taip.type_definition, taip)

    def unstack_indirect_call(self, stack: Stack, word: resolved_words.IndirectCallWord) -> Word:
        function = stack.pop()
        arguments = stack.pop_n(len(word.parameters))
        parameters = self.fresh_holes(word.token, len(word.parameters))
        return_types = self.fresh_holes(word.token, len(word.returns))

        node = self.add_node(source.FromIndirectCall(
            token=word.token,
            function=function,
            return_types=return_types,
            arguments=arguments,
            parameters=parameters))

        for i in range(len(word.returns)):
            stack.push(source.FromNode(word.token, node, i))

        if len(word.returns) == 0:
            for argument, hole, parameter in zip(arguments, parameters, word.parameters):
                parameter_without_holes = without_holes.without_holes(parameter)
                if isinstance(parameter_without_holes, Token):
                    known = None
                else:
                    known = parameter_without_holes
                self.voids.append(NonSpecificVoid(
                    token=word.token,
                    source=argument,
                    known=known,
                    taip=hole))
            self.voids.append(IndirectCallVoid(
                token=word.token,
                function=function,
                parameters=parameters,
                returns=return_types))

        return words.IndirectCall(word.token, parameters, return_types)

    def unstack_loop(self, stack: Stack, word: resolved_words.LoopWord) -> Word:
        loop_break_stacks: List[BreakStack] = []
        return_types_annotation = None if word.annotation is None else self.fresh_holes(word.token, len(word.annotation.returns))
        loop_unstacker = self.with_break_stacks(loop_break_stacks, return_types_annotation)
        entry_node = loop_unstacker.pre_add_node()
        loop_stack = stack.child(entry_node, word.token)
        body = loop_unstacker.unstack_scope(loop_stack, word.body)

        arguments = tuple(loop_stack.negative)
        parameters = self.fresh_holes(word.token, len(arguments))

        self.fill_node(entry_node, source.FromLoopEntry(
            token=word.token,
            arguments=arguments,
            parameters=parameters,
            next_arguments=tuple(loop_stack.positive)))

        if len(loop_break_stacks) != 0:
            first_break_stack = loop_break_stacks[0]
            if not first_break_stack.reachable:
                self.reachable = False
            n_returns = max((len(stack.sources) for stack in loop_break_stacks), default=0)
            return_types = return_types_annotation if return_types_annotation is not None else self.fresh_holes(word.token, n_returns)
            break_returns = tuple(
                    source.BreakReturns(tuple(source.BreakReturnSource(
                        break_stack.token,
                        break_stack.sources[return_index]) for break_stack in loop_break_stacks))
                    for return_index in range(n_returns))

            exit_node = loop_unstacker.add_node(source.FromBlockExit(word.token, return_types, break_returns))

            for i in range(len(break_returns)):
                return_depth = len(break_returns) - 1 - i
                stack.push(source.FromNode(word.token, exit_node, return_depth))

            loop = words.Loop(word.token, parameters, return_types, body)
        else:
            return_types = None
            loop = words.Loop(word.token, parameters, None, body)
            self.reachable = False

        if return_types is None or len(return_types) == 0:
            for i, (argument, parameter) in enumerate(zip(arguments, parameters)):
                return_depth = len(arguments) - i - 1
                loop_unstacker.voids.append(NonSpecificVoid(
                    token=word.token,
                    source=source.FromNode(word.token, entry_node, return_depth),
                    known=None,
                    taip=parameter))
        return loop

    def unstack_block(self, stack: Stack, word: resolved_words.BlockWord) -> Word:
        block_break_stacks: List[BreakStack] = []
        return_types_annotation = None if word.annotation is None else self.fresh_holes(word.token, len(word.annotation.returns))

        block_unstacker = self.with_break_stacks(block_break_stacks, return_types_annotation)
        entry_node = block_unstacker.pre_add_node()
        block_stack = stack.child(entry_node, word.token)
        loop_block_unstacker = block_unstacker.with_cleared_reachable_flag()

        body = loop_block_unstacker.unstack_scope(block_stack, word.body)

        if loop_block_unstacker.reachable:
            block_break_stacks.append(BreakStack(word.end, tuple(block_stack.positive), True))

        arguments = tuple(reversed(block_stack.negative))
        parameters = self.fresh_holes(word.token, len(arguments))
        self.fill_node(entry_node, source.FromBlockEntry(
            word.token, parameters, arguments))

        if return_types_annotation is not None:
            n_returns = len(return_types_annotation)
            return_types = return_types_annotation
        else:
            any_break_reachable = any(break_stack.reachable for break_stack in block_break_stacks)
            n_returns = max((len(stack.sources) for stack in block_break_stacks), default=0)
            if any_break_reachable:
                return_types = block_unstacker.fresh_holes(word.token, n_returns)
            else:
                return_types = None

        break_returns = tuple(
                source.BreakReturns(tuple(source.BreakReturnSource(
                    break_stack.token,
                    break_stack.sources[return_index]) for break_stack in block_break_stacks))
                for return_index in range(n_returns))

        if return_types is None:
            self.reachable = True
        elif len(return_types) != 0:
            exit_node = block_unstacker.add_node(source.FromBlockExit(
                word.token,
                return_types,
                break_returns))
            for i in range(len(break_returns)):
                return_depth = len(break_returns) - 1 - i
                stack.push(source.FromNode(word.token, exit_node, return_depth))

        return words.Block(word.token, parameters, return_types, body)

    def unstack_break(self, stack: Stack, word: resolved_words.BreakWord) -> Word:
        if self.block_returns is None:
            dump = stack.dump()
        else:
            dump = stack.pop_n(len(self.block_returns))
            size = len(stack)
            while size != 0:
                self.voids.append(NonSpecificVoid(
                    word.token, stack.index(size - 1), None, None))
                size -= 1

        assert(self.break_stacks is not None)
        self.break_stacks.append(BreakStack(word.token, dump, self.reachable))

        self.reachable = False
        return word

    def unstack_make_variant(self, stack: Stack, word: resolved_words.VariantWord) -> Word:
        variant = self.lookup_type_definition(word.variant.type_definition)
        assert(not isinstance(variant, Struct))
        cays = variant.cases[word.tag]
        if cays.taip is None:
            src = None
        else:
            src = stack.pop()

        taip = self.fresh_hole(word.token)
        generic_arguments = self.fresh_holes(word.token, len(variant.generic_parameters))
        stack.push(source.FromMakeVariant(
            token=word.token,
            type_definition=word.variant.type_definition,
            generic_arguments=generic_arguments,
            taip=taip,
            source=src,
            tag=word.tag))

        for generic_argument, hole in zip(word.variant.generic_arguments, generic_arguments):
            generic_argument_without_holes = without_holes.without_holes(generic_argument)
            if isinstance(generic_argument_without_holes, Token):
                continue
            self.holes.fill(hole, generic_argument_without_holes)

        return words.MakeVariant(word.token, taip, word.tag)

    def unstack_field_init(self, stack: Stack, word: resolved_words.StructFieldInitWord) -> Word:
        src = stack.pop()
        self.struct_field_init_arguments[word.field_index] = src
        struct_init_type = self.struct_init_type
        assert(struct_init_type is not None)
        return words.FieldInit(word.name, struct_init_type, word.field_index)

    def unstack_make_struct_named(self, stack: Stack, word: resolved_words.StructWordNamed) -> Word:
        struct = self.lookup_type_definition(word.taip.type_definition)
        assert(not isinstance(struct, Variant))
        generic_arguments = self.fresh_holes(word.token, len(struct.generic_parameters))
        taip = self.fresh_hole(word.token)
        for generic_argument, hole in zip(word.taip.generic_arguments, generic_arguments):
            generic_argument_without_holes = without_holes.without_holes(generic_argument)
            if isinstance(generic_argument_without_holes, Token):
                continue
            self.holes.fill(hole, generic_argument_without_holes)

        argument_slots: List[Source | None] = list(None for _ in struct.fields)
        unstacker = self.with_struct_init(taip, argument_slots)
        body = unstacker.unstack_scope(stack, word.body)

        def assert_some(src: Source | None) -> Source:
            assert(src is not None)
            return src
        arguments: Tuple[Source, ...] = tuple(assert_some(arg) for arg in argument_slots)
        stack.push(source.FromMakeStruct(
            token=word.token,
            name=word.name,
            type_definition=word.taip.type_definition,
            taip=taip,
            generic_arguments=generic_arguments,
            arguments=arguments))
        return words.MakeStructNamed(word.token, taip, body)

    def unstack_load(self, stack: Stack, word: resolved_words.LoadWord) -> Word:
        taip = self.fresh_hole(word.token)
        src = stack.pop()
        stack.push(source.FromLoad(word.token, taip, src))
        return words.Load(word.token, taip)

    def unstack_get_field(self, stack: Stack, word: resolved_words.GetFieldWord) -> Word:
        src = stack.pop()
        fields = self.unstack_field_accesses(word.fields)
        base_type = self.fresh_hole(word.token)
        stack.push(source.FromGetField(word.token, base_type, src, fields))
        return words.GetField(word.token, base_type, fields)

    def unstack_call(self, stack: Stack, word: resolved_words.CallWord) -> Word:
        signature = self.lookup_signature(word.function)
        arguments = stack.pop_n(len(signature.parameters))
        generic_arguments = self.fresh_holes(word.name, len(signature.generic_parameters))
        if word.generic_arguments is not None:
            for i, generic_argument in enumerate(word.generic_arguments):
                hole_or_type = without_holes.without_holes(generic_argument)
                if not isinstance(hole_or_type, Token):
                    self.holes.fill(generic_arguments[i], hole_or_type)

        node_index = self.add_node(source.FromCall(word.name, word.function, generic_arguments, arguments))

        for i in range(len(signature.returns), 0, -1):
            return_depth = i - 1
            stack.push(source.FromNode(word.name, node_index, return_depth))

        if len(signature.returns) == 0:
            self.voids.append(CallVoid(
                word.name,
                word.function,
                arguments,
                generic_arguments))

        return words.Call(word.name, word.function, generic_arguments)

    def unstack_cast(self, stack: Stack, word: resolved_words.CastWord) -> Word:
        src_type = self.fresh_hole(word.token)
        src = stack.pop()
        stack.push(source.FromCast(word.token, src_type, word.dst, src))
        return words.Cast(word.token, src_type, word.dst)

    def unstack_init_local(self, stack: Stack, word: resolved_words.InitLocal) -> Word:
        local = self.locals[word.local_id]
        local.assignments.append(Assignment(
            token=word.name,
            source=stack.pop(),
            fields=(),
            taip=local.taip,
            is_store=False,
        ))
        return words.InitLocal(word.name, word.local_id)

    def unstack_ref_local(self, stack: Stack, word: resolved_words.RefLocal) -> Word:
        match word.var:
            case LocalId():
                local = self.locals[word.var]
                local.reffed = True
                result_type = self.fresh_hole(word.name)
                fields = self.unstack_field_accesses(word.fields)
                stack.push(source.FromLocal(
                    word.name, word.var, local.taip, fields, result_type, True))
                return words.RefLocal(word.name, word.var, local.taip, result_type, fields)
            case GlobalId():
                globl = self.lookup_global(word.var)
                var_type = self.fresh_hole(word.name)
                self.holes.fill(var_type, globl.taip)
                result_type = self.fresh_hole(word.name)
                fields = self.unstack_field_accesses(word.fields)
                stack.push(source.FromGlobal(
                    word.name, word.var, globl.taip, fields, result_type, True))
                return words.RefLocal(word.name, word.var, var_type, result_type, fields)

    def unstack_set_local(self, stack: Stack, word: resolved_words.SetLocal) -> Word:
        source = stack.pop()
        fields = self.unstack_field_accesses(word.fields)
        field_type = self.fresh_hole(word.name) if len(fields) == 0 else fields[-1].target_type
        match word.var:
            case LocalId():
                local = self.locals[word.var]
                local.assignments.append(Assignment(
                    word.name, source, fields, field_type, False))
                return words.SetLocal(word.name, word.var, fields, field_type)
            case GlobalId():
                self.voids.append(SetGlobalVoid(
                    word.name,
                    self.lookup_global(word.var).taip,
                    fields,
                    field_type,
                    source))

                return words.SetGlobal(
                        word.name,
                        word.var,
                        fields,
                        field_type)

    @dataclass(frozen=True)
    class MatchCaseUnstacked:
        name: Token
        tag: int | None
        stack: Stack
        body: Scope
        diverges: bool

        def to_case(self) -> words.MatchCase | None:
            if self.tag is None:
                return None
            return words.MatchCase(self.name, self.tag, self.body)
        def to_default_case(self) -> words.DefaultCase | None:
            if self.tag is not None:
                return None
            return words.DefaultCase(self.name, self.body)

    def unstack_match(self, stack: Stack, word: ResolvedMatchWord) -> Word:
        entry_node = self.pre_add_node()
        scrutinee = stack.pop()
        scrutinee_type = self.fresh_hole(word.token)
        varint = self.lookup_type_definition(word.variant)
        assert(isinstance(varint, Variant))
        generic_arguments = self.fresh_holes(word.token, len(varint.generic_parameters))

        unstacked_cases: List[Unstacker.MatchCaseUnstacked] = []
        for match_case in word.cases:
            case_stack = stack.clone().child(entry_node, word.token)
            case_unstacker = self.with_cleared_reachable_flag()
            variant_case = varint.cases[match_case.tag]
            if variant_case.taip is not None:
                case_stack.push(source.FromCase(match_case.name, word.variant, generic_arguments, match_case.tag, scrutinee, scrutinee_type))

            body = Scope(match_case.body.id, case_unstacker.unstack_words(case_stack, match_case.body.words))

            unstacked_cases.append(self.MatchCaseUnstacked(match_case.name, match_case.tag, case_stack, body, not case_unstacker.reachable))

        if word.default is not None:
            case_stack = stack.clone().child(entry_node, word.token)
            case_unstacker = self.with_cleared_reachable_flag()
            if scrutinee is not None:
                case_stack.push(source.FromProxied(scrutinee, scrutinee_type))

            body = Scope(word.default.body.id, case_unstacker.unstack_words(case_stack, word.default.body.words))

            unstacked_cases.append(self.MatchCaseUnstacked(word.default.underscore, None, case_stack, body, not case_unstacker.reachable))

        parameters = self.fresh_holes(word.token, max(len(case.stack.negative) for case in unstacked_cases))
        arguments = stack.pop_n(len(parameters))

        self.fill_node(entry_node, source.FromMatchEntry(word.token, scrutinee_type, parameters, scrutinee, arguments))

        for unstacked_case in unstacked_cases:
            unstacked_case.stack.ensure_negatives(len(parameters))

        n_returns: int | None = None
        for unstacked_case in unstacked_cases:
            if unstacked_case.diverges:
                continue
            if n_returns is None:
                n_returns = len(unstacked_case.stack.positive)
                continue
            n_returns = max(n_returns, len(unstacked_case.stack.positive))

        if len(parameters) == 0 and (n_returns is None or n_returns == 0):
            self.voids.append(NonSpecificVoid(
                word.token,
                scrutinee,
                None,
                scrutinee_type))

        return_types: Tuple[InferenceHole, ...] | None
        if n_returns is None:
            self.reachable = False
            return_types = None
        else:
            returns_per_case = tuple(
                source.ReturnsOfCase(unstacked_case.tag, unstacked_case.stack.pop_n(n_returns))
                for unstacked_case in unstacked_cases
                if not unstacked_case.diverges)
            return_types = self.fresh_holes(word.token, n_returns)
            exit_node = self.add_node(source.FromMatchExit(word.token, word.variant, return_types, scrutinee_type, scrutinee, returns_per_case))

            for i in range(len(return_types)):
                return_depth = len(return_types) - 1 - i
                stack.push(source.FromNode(word.token, exit_node, return_depth))

        cases = tuple(x for case in unstacked_cases for x in (case.to_case(),) if x is not None)
        default = next((x for case in unstacked_cases for x in (case.to_default_case(),)), None)
        return words.Match(word.token, scrutinee_type, parameters, return_types, cases, default)

    def unstack_if(self, stack: Stack, word: ResolvedIfWord, remaining: List[ResolvedWord]) -> Word:
        entry_node = self.pre_add_node()
        condition = stack.pop()
        true_stack = stack.clone().child(entry_node, word.token)

        true_unstacker = self.with_cleared_reachable_flag()
        true_body = true_unstacker.unstack_scope(true_stack, word.true_branch)

        if len(word.false_branch.words) == 0 and not true_unstacker.reachable:
            remaining_stack = stack.clone().child(entry_node, word.token)
            remaining_stack.ensure_negatives(len(true_stack.negative))

            remaining_unstacker = self.with_cleared_reachable_flag()
            remaining_words = remaining_unstacker.unstack_words(remaining_stack, remaining)
            remaining_body = Scope(word.false_branch.id, remaining_words)

            parameters = self.fresh_holes(word.token, max(len(true_stack.negative), len(remaining_stack.negative)))

            arguments = stack.pop_n(len(parameters))

            true_stack.ensure_negatives(len(parameters))
            remaining_stack.ensure_negatives(len(parameters))

            self.reachable = remaining_unstacker.reachable
            self.fill_node(entry_node, source.FromIfEntry(word.token, condition, parameters, arguments))

            if self.reachable:
                return_types = self.fresh_holes(word.token, len(remaining_stack.positive))
            else:
                return_types = None

            if return_types is not None and len(return_types) != 0:
                exit_node = self.add_node(source.FromIfExit(
                    token=word.token,
                    condition=condition,
                    return_types=return_types,
                    true_branch_returns=None,
                    false_branch_returns=tuple(remaining_stack.positive)))
                for i in range(len(remaining_stack.positive)):
                    return_depth = len(remaining_stack.positive) - i - 1
                    stack.push(source.FromNode(word.token, exit_node, return_depth))

            feeds_into_void = return_types is None or len(return_types) == 0

            if feeds_into_void:
                for i, parameter in enumerate(parameters):
                    return_depth = len(parameters) - i - 1
                    self.voids.append(NonSpecificVoid(
                        token=word.token,
                        source=source.FromNode(word.token, entry_node, return_depth),
                        known=None,
                        taip=parameter))
                self.voids.append(NonSpecificVoid(
                    token=word.token,
                    source=condition,
                    known=Bool(),
                    taip=None))

            return words.If(word.token, parameters, return_types, true_body, remaining_body)
        else:
            false_unstacker = self.with_cleared_reachable_flag()
            false_stack = stack.clone().child(entry_node, word.token)

            false_body = false_unstacker.unstack_scope(false_stack, word.false_branch)
            arguments = stack.pop_n(max(len(true_stack.negative), len(false_stack.negative)))
            parameters = self.fresh_holes(word.token, len(arguments))
            return_types = self.fresh_holes(word.token, max(len(true_stack.positive), len(false_stack.positive)))

            self.fill_node(entry_node, source.FromIfEntry(word.token, condition, parameters, arguments))

            if len(arguments) == 0 and len(return_types) == 0:
                self.voids.append(NonSpecificVoid(
                    word.token,
                    condition,
                    Bool(),
                    None))
            else:
                exit_node = self.add_node(source.FromIfExit(
                    word.token,
                    condition,
                    return_types,
                    true_branch_returns=true_stack.pop_n(len(return_types)),
                    false_branch_returns=false_stack.pop_n(len(return_types))))
                for i in range(len(return_types)):
                    return_depth = len(return_types) - i - 1
                    stack.push(source.FromNode(word.token, exit_node, return_depth))

            return words.If(word.token, parameters, return_types, true_body, false_body)

    def unstack_intrinsic(self, stack: Stack, word: ResolvedIntrinsicWord) -> Word:
        match word.ty:
            case IntrinsicType.ADD | IntrinsicType.SUB:
                taip = self.fresh_hole(word.token)
                stack.push(source.FromAdd(
                    token=word.token,
                    addition=stack.pop(),
                    base=stack.pop(),
                    taip=taip))
                match word.ty:
                    case IntrinsicType.ADD:
                        return words.Add(word.token, taip)
                    case IntrinsicType.SUB:
                        return words.Sub(word.token, taip)
            case IntrinsicType.MUL | IntrinsicType.DIV | IntrinsicType.MOD | IntrinsicType.SHR | IntrinsicType.SHL | IntrinsicType.ROTL | IntrinsicType.ROTR:
                taip = self.fresh_hole(word.token)
                stack.push(source.FromMul(
                    token=word.token,
                    b=stack.pop(),
                    a=stack.pop(),
                    taip=taip))
                match word.ty:
                    case IntrinsicType.MUL:
                        return words.Mul(word.token, taip)
                    case IntrinsicType.DIV:
                        return words.Div(word.token, taip)
                    case IntrinsicType.MOD:
                        return words.Mod(word.token, taip)
                    case IntrinsicType.SHL:
                        return words.Shl(word.token, taip)
                    case IntrinsicType.SHR:
                        return words.Shr(word.token, taip)
                    case IntrinsicType.ROTL:
                        return words.Rotl(word.token, taip)
                    case IntrinsicType.ROTR:
                        return words.Rotr(word.token, taip)
                assert_never(word.ty)
            case IntrinsicType.EQ | IntrinsicType.NOT_EQ:
                taip = self.fresh_hole(word.token)
                stack.push(source.FromEq(
                    token=word.token,
                    taip=taip,
                    a=stack.pop(),
                    b=stack.pop()))
                match word.ty:
                    case IntrinsicType.EQ:
                        return words.Eq(word.token, taip)
                    case IntrinsicType.NOT_EQ:
                        return words.NotEq(word.token, taip)
            case IntrinsicType.DROP:
                src = stack.pop()
                taip = self.fresh_hole(word.token)
                self.voids.append(NonSpecificVoid(
                    word.token, src, None, taip))
                return words.Drop(word.token, taip)
            case IntrinsicType.UNINIT:
                generic_arguments = self.unstack_generic_arguments(word.token, word.generic_arguments, 1)
                stack.push(source.FromUninit(word.token, generic_arguments))
                return words.Uninit(word.token, generic_arguments[0])
            case IntrinsicType.FLIP:
                b = stack.pop()
                a = stack.pop()
                lower = self.fresh_hole(word.token)
                upper = self.fresh_hole(word.token)
                if b is not None:
                    stack.push(source.FromProxied(b, upper))
                if a is not None:
                    stack.push(source.FromProxied(a, lower))
                return words.Flip(word.token, lower, upper)
            case IntrinsicType.MEM_GROW:
                src = stack.pop()
                stack.push(source.FromMemGrow(word.token, src))
                return words.MemGrow(word.token)
            case IntrinsicType.SET_STACK_SIZE:
                self.voids.append(NonSpecificVoid(
                    token=word.token,
                    source=stack.pop(),
                    known=without_holes.I32(),
                    taip=None))
                return words.SetStackSize(word.token)
            case IntrinsicType.LESS_EQ | IntrinsicType.LESS | IntrinsicType.GREATER | IntrinsicType.GREATER_EQ:
                taip = self.fresh_hole(word.token)
                stack.push(source.FromCmp(
                    word.token,
                    b=stack.pop(),
                    a=stack.pop(),
                    taip=taip))
                match word.ty:
                    case IntrinsicType.LESS:
                        return words.Lt(word.token, taip)
                    case IntrinsicType.LESS_EQ:
                        return words.Le(word.token, taip)
                    case IntrinsicType.GREATER_EQ:
                        return words.Ge(word.token, taip)
                    case IntrinsicType.GREATER:
                        return words.Gt(word.token, taip)
            case IntrinsicType.STORE:
                taip = self.fresh_hole(word.token)
                self.voids.append(StoreVoid(
                    word.token,
                    src=stack.pop(),
                    dst=stack.pop(),
                    taip=taip))
                return words.Store(word.token, taip)
            case IntrinsicType.AND | IntrinsicType.OR:
                taip = self.fresh_hole(word.token)
                stack.push(source.FromAnd(
                    word.token,
                    b=stack.pop(),
                    a=stack.pop(),
                    taip=taip))
                match word.ty:
                    case IntrinsicType.AND:
                        return words.And(word.token, taip)
                    case IntrinsicType.OR:
                        return words.Or(word.token, taip)
            case IntrinsicType.NOT:
                taip = self.fresh_hole(word.token)
                src = stack.pop()
                stack.push(source.FromNot(word.token, taip, src))
                return words.Not(word.token, taip)
            case IntrinsicType.MEM_COPY:
                self.voids.append(NonSpecificVoid(
                    token=word.token,
                    source=stack.pop(),
                    known=I32(),
                    taip=None))
                self.voids.append(NonSpecificVoid(
                    token=word.token,
                    source=stack.pop(),
                    known=without_holes.PtrType(I8()),
                    taip=None))
                self.voids.append(NonSpecificVoid(
                    token=word.token,
                    source=stack.pop(),
                    known=without_holes.PtrType(I8()),
                    taip=None))
                return words.MemCopy(word.token)
            case IntrinsicType.MEM_FILL:
                self.voids.append(NonSpecificVoid(
                    token=word.token,
                    source=stack.pop(),
                    known=I32(),
                    taip=None))
                self.voids.append(NonSpecificVoid(
                    token=word.token,
                    source=stack.pop(),
                    known=I8(),
                    taip=None))
                self.voids.append(NonSpecificVoid(
                    token=word.token,
                    source=stack.pop(),
                    known=without_holes.PtrType(I8()),
                    taip=None))
                return words.MemFill(word.token)


        print(word, file=sys.stderr)
        assert False

    def unstack_generic_arguments(self, token: Token, generic_arguments: Tuple[with_holes.Type, ...], expected_arguments: int) -> Tuple[InferenceHole, ...]:
        holes: List[InferenceHole] = []
        for i in range(expected_arguments):
            if i >= len(generic_arguments):
                holes.append(self.fresh_hole(token))
                continue
            generic_argument = generic_arguments[i]
            if isinstance(generic_argument, with_holes.HoleType):
                hole = self.fresh_hole(generic_argument.token)
            else:
                hole = self.fresh_hole(token)
            generic_argument_or_hole = without_holes.without_holes(generic_argument)
            if not isinstance(generic_argument_or_hole, Token):
                self.holes.fill(hole, generic_argument_or_hole)
            holes.append(hole)
        return tuple(holes)

    def unstack_get_local(self, stack: Stack, word: resolved_words.GetLocal) -> Word:
        match word.var:
            case LocalId():
                local = self.locals[word.var]
                result_type = self.fresh_hole(word.name)
                fields = self.unstack_field_accesses(word.fields)
                stack.push(source.FromLocal(word.name, word.var, local.taip, fields, result_type, False))
                return words.GetLocal(
                    name=word.name,
                    var=word.var,
                    var_type=local.taip,
                    fields=fields,
                    result_type=result_type,
                )
            case GlobalId():
                globl = self.lookup_global(word.var)
                var_type = self.fresh_hole(word.name)
                self.holes.fill(var_type, globl.taip)
                result_type = self.fresh_hole(word.name)
                fields = self.unstack_field_accesses(word.fields)
                stack.push(source.FromGlobal(word.name, word.var, globl.taip, fields, result_type, False))
                return words.GetLocal(
                    name=word.name,
                    var=word.var,
                    var_type=var_type,
                    fields=fields,
                    result_type=result_type,
                )

    def fresh_hole(self, token: Token) -> InferenceHole:
        self.next_inference_hole_index.value += 1
        return InferenceHole(token, self.next_inference_hole_index.value - 1)

    def fresh_holes(self, token: Token, n: int) -> Tuple[InferenceHole, ...]:
        return tuple(self.fresh_hole(token) for _ in range(n))

    def fresh_field_hole(self) -> InferenceFieldHole:
        self.next_inference_field_hole_index.value += 1
        return InferenceFieldHole(self.next_inference_field_hole_index.value - 1)

    def unstack_field_accesses(self, fields: Tuple[Token, ...]) -> Tuple[FieldAccess, ...]:
        return tuple(self.unstack_field_access(field) for field in fields)

    def unstack_field_access(self, access: Token) -> FieldAccess:
        return FieldAccess(
            name=access,
            field_index=self.fresh_field_hole(),
            source_type=self.fresh_hole(access),
            target_type=self.fresh_hole(access))

