from typing import Dict, Tuple, NoReturn
from dataclasses import dataclass
import os

from util import normalize_path
from indexed_dict import IndexedDict
from lexer import Token
import parsing as parser
from resolving.words import Scope
from resolving.top_items import Function, FunctionSignature, Import, Global, Extern, Local, Struct, Variant, VariantCase, TypeDefinition, FunctionImport, StructImport, VariantImport, FunctionHandle, ImportItem, CustomTypeHandle
from resolving.env import Env
from resolving.word_resolver import WordResolver
from resolving.type_resolver import TypeResolver, TypeLookup
from resolving.module import Module, ResolveException
from resolving.types import Type, NamedType
import resolving.type_without_holes as without_holes

class ModuleResolver:
    module_id: int
    module_path: str
    imports: Dict[str, Tuple[Import, ...]]
    module: parser.Module
    modules: IndexedDict[str, Module]

    def __init__(self, module_id: int, module_path: str, imports: Dict[str, Tuple[Import,...]], module: parser.Module, modules: IndexedDict[str, Module]):
        self.module_id = module_id
        self.module_path = module_path
        self.imports = imports
        self.module = module
        self.modules = modules
        self.type_resolver = TypeResolver(module_id, module_path, imports, module, modules)

    def abort(self, token: Token, message: str) -> NoReturn:
        raise ResolveException(self.module_path, token, message)

    @staticmethod
    def resolve_module(modules: IndexedDict[str, Module], module: parser.Module, id: int) -> Module:
        imports: Dict[str, Tuple[Import, ...]] = { imp.qualifier.lexeme: () for imp in module.imports }
        for imp in module.imports:
            imports[imp.qualifier.lexeme] += ModuleResolver.resolve_import(modules, module.path, imp),

        resolver = ModuleResolver(id, module.path, imports, module, modules)

        type_definitions = IndexedDict.from_items((type_definition.name.lexeme, resolver.resolve_type_definition(type_definition)) for type_definition in module.type_definitions)
        globals: IndexedDict[str, Global] = IndexedDict.from_items((globl.name.lexeme, resolver.resolve_global(globl)) for globl in module.globals)

        signatures: IndexedDict[str, FunctionSignature] = IndexedDict.from_items(
            (function.signature.name.lexeme, resolver.resolve_signature(function.signature))
            for function in module.functions
        )

        static_data = bytearray()

        function_resolver = FunctionResolver(resolver, imports, globals, type_definitions, signatures, static_data)
        functions: IndexedDict[str, Function | Extern] = IndexedDict.from_items(
            (fun.signature.name.lexeme, function_resolver.resolve_function(fun))
            for fun in module.functions
        )

        return Module(module.path, id, imports, type_definitions, globals, functions, bytes(static_data))

    def forbid_holes(self, taip: Type) -> without_holes.Type:
        without = without_holes.without_holes(taip)
        if isinstance(without, Token):
            self.abort(without, "hole not allowed here")
        return without

    def forbid_holes_named(self, taip: NamedType) -> without_holes.NamedType:
        return without_holes.NamedType(taip.name, self.forbid_holes(taip.taip))

    def resolve_global(self, globl: parser.Global) -> Global:
        return Global(globl.name, self.forbid_holes(self.type_resolver.resolve_type(globl.taip)), False)

    def resolve_signature(self, signature: parser.FunctionSignature) -> FunctionSignature:
        return FunctionSignature(
            signature.generic_parameters,
            tuple(self.forbid_holes_named(self.type_resolver.resolve_named_type(param)) for param in signature.parameters),
            tuple(self.forbid_holes(self.type_resolver.resolve_type(ret)) for ret in signature.returns))

    @staticmethod
    def resolve_import(modules: IndexedDict[str, Module], importing_module_path: str, imp: parser.Import) -> Import:
        path = "" if importing_module_path == "" else os.path.dirname(importing_module_path)
        path = normalize_path(path + "/" + imp.file_path.lexeme[1:-1])
        imported_module_id = modules.index_of(path)
        imported_module = modules.index(imported_module_id)
        def resolve_item(parsed_item: parser.ImportItem) -> ImportItem:
            if isinstance(parsed_item, Token):
                item = imported_module.lookup_item(parsed_item)
                if item is None:
                    raise ResolveException(importing_module_path, parsed_item, "not found")
                if isinstance(item, FunctionHandle):
                    return FunctionImport(parsed_item, item)
                else:
                    if isinstance(modules.index(item.module).type_definitions.index(item.index), Variant):
                        return VariantImport(parsed_item, item, ())
                    return StructImport(parsed_item, item)
            else:
                item = imported_module.lookup_item(parsed_item.name)
                if item is None or not isinstance(item, CustomTypeHandle):
                    raise ResolveException(importing_module_path, parsed_item.name, "not a variant")
                variant = modules.index(item.module).type_definitions.index(item.index)
                if not isinstance(variant, Variant):
                    raise ResolveException(importing_module_path, parsed_item.name, "not a variant")
                def lookup_constructor(constructor: Token) -> int:
                    for i,case in enumerate(variant.cases):
                        if case.name.lexeme == constructor.lexeme:
                            return i
                    raise ResolveException(importing_module_path, constructor, "constructor not found")
                return VariantImport(parsed_item.name, item, tuple(
                    (lookup_constructor(constructor) for constructor in parsed_item.constructors)))
        return Import(imp.token, path, imp.qualifier, imported_module_id, tuple(map(resolve_item, imp.items)))

    def resolve_type_definition(self, type_definition: parser.TypeDefinition) -> TypeDefinition:
        if isinstance(type_definition, parser.Struct):
            return self.resolve_struct(type_definition)
        if isinstance(type_definition, parser.Variant):
            return self.resolve_variant(type_definition)

    def resolve_struct(self, struct: parser.Struct) -> Struct:
        return Struct(
            struct.name,
            struct.generic_parameters,
            tuple(self.forbid_holes_named(self.type_resolver.resolve_named_type(t)) for t in struct.fields))

    def resolve_variant(self, variant: parser.Variant) -> Variant:
        return Variant(
            variant.name,
            variant.generic_parameters,
            tuple(VariantCase(case.name, None if case.taip is None else self.forbid_holes(self.type_resolver.resolve_type(case.taip))) for case in variant.cases))


@dataclass
class FunctionResolver:
    module_resolver: ModuleResolver
    imports: Dict[str, Tuple[Import, ...]]
    globals: IndexedDict[str, Global]
    type_definitions: IndexedDict[str, TypeDefinition]
    signatures: IndexedDict[str, FunctionSignature]
    static_data: bytearray

    @property
    def module_id(self) -> int:
        return self.module_resolver.module_id

    @property
    def module_path(self) -> str:
        return self.module_resolver.module_path

    @property
    def modules(self) -> IndexedDict[str, Module]:
        return self.module_resolver.modules

    @property
    def type_resolver(self) -> TypeResolver:
        return self.module_resolver.type_resolver

    def resolve_signature(self, signature: parser.FunctionSignature) -> FunctionSignature:
        return self.module_resolver.resolve_signature(signature)

    def resolve_function(self, function: parser.Function | parser.Extern) -> Function | Extern:
        match function:
            case parser.Function():
                return self.resolve_local_function(function)
            case parser.Extern():
                return self.resolve_extern(function)

    def resolve_local_function(self, function: parser.Function) -> Function:
        signature: FunctionSignature = self.signatures[function.signature.name.lexeme]
        env = Env(list(map(Local.make_parameter, signature.parameters)))
        type_lookup = TypeLookup(self.module_id, tuple(self.modules.values()), self.type_definitions)
        resolver = WordResolver(
            self.module_id, self.module_path, self.imports, self.globals,
            self.signatures, self.type_resolver, self.modules,
            type_lookup, env, self.static_data)
        words = resolver.resolve_words(function.body)
        scope = Scope(env.scope_id, words)
        vars = env.vars_by_id
        return Function(function.signature.name, function.signature.export_name, signature, scope, vars)

    def resolve_extern(self, extern: parser.Extern) -> Extern:
        return Extern(extern.signature.name, extern.module.lexeme, extern.name.lexeme, self.resolve_signature(extern.signature))
