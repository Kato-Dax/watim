#!/usr/bin/env python
from dataclasses import dataclass
from typing import List, Dict
import sys
import os
import unittest

import format

from parsing.parser import ParseException
import parsing.parser as parser
from util import sys_stdin
from indexed_dict import IndexedDict

from lexer import TokenLocation, Lexer

import resolving as resolved
from resolving import ModuleResolver, ResolveException

from checking import determine_compilation_order, CheckCtx, CheckException
import checking as checked
import unstacking as unstacking

from monomizer import Monomizer, merge_locals_module, DetermineLoadsToValueTests
from wat_generator import WatGenerator

def load_recursive(
        modules: Dict[str, parser.Module],
        path: str,
        path_location: TokenLocation | None,
        stdin: str | None = None,
        import_stack: List[str]=[]):
    if path == "-":
        file = stdin if stdin is not None else sys_stdin.get()
    else:
        try:
            with open(path, 'r') as reader:
                file = reader.read()
        except FileNotFoundError:
            raise ParseException(path_location, f"File not found: ./{path}")

    tokens = Lexer(file).lex()
    module = parser.Parser(path, file, tokens).parse()
    modules[path] = module
    for imp in module.imports:
        if os.path.dirname(path) != "":
            p = os.path.normpath(os.path.dirname(path) + "/" + imp.file_path.lexeme[1:-1])
        else:
            p = os.path.normpath(imp.file_path.lexeme[1:-1])
        if p in import_stack:
            error_message = "Module import cycle detected: "
            for a in import_stack:
                error_message += f"{a} -> "
            raise ParseException(TokenLocation(path, imp.file_path.line, imp.file_path.column), error_message)
        if p in modules:
            continue
        import_stack.append(p)
        load_recursive(
            modules,
            p,
            TokenLocation(path, imp.file_path.line, imp.file_path.column),
            stdin,
            import_stack,
        )
        import_stack.pop()

def resolve_modules(modules_unordered: Dict[str, parser.Module]) -> IndexedDict[str, resolved.Module]:
    modules: IndexedDict[str, parser.Module] = determine_compilation_order({
        ("./" + path if path != "-" else path): module
        for path, module in modules_unordered.items()
    })
    resolved_modules: IndexedDict[str, resolved.Module] = IndexedDict()
    for id,(module_path,module) in enumerate(modules.items()):
        resolved_modules[module_path] = ModuleResolver.resolve_module(resolved_modules, module, id)
    return resolved_modules

def check_modules(resolved_modules: IndexedDict[str, resolved.Module]) -> IndexedDict[str, checked.Module]:
    checked_modules: IndexedDict[str, checked.Module] = IndexedDict()
    for id,(module_path,module) in enumerate(resolved_modules.items()):
        type_lookup = resolved.TypeLookup(id, resolved_modules, module.type_definitions)
        ctx = CheckCtx(
                resolved_modules,
                checked_modules,
                [f.signature for f in module.functions.values()],
                module.globals,
                type_lookup,
                id)
        for handle in type_lookup.find_directly_recursive_types():
            token = type_lookup.lookup(handle).name
            raise CheckException(module_path, token, "structs and variants cannot be recursive")
        checked_modules[module_path] = checked.Module(
                module.path,
                module.id,
                module.imports,
                module.type_definitions,
                module.globals,
                ctx.check_functions(),
                bytes(module.static_data))
    return checked_modules

@dataclass
class Lex:
    path: str

@dataclass
class Parse:
    path: str

@dataclass
class Resolve:
    path: str

@dataclass
class Unstack:
    path: str
    function: str

@dataclass
class Check:
    path: str

@dataclass
class Monomize:
    path: str

@dataclass
class Compile:
    path: str

type Cmd = Lex | Parse | Resolve | Unstack | Check | Monomize | Compile

def read_path(path: str, stdin: str | None = None) -> str:
    if path == "-":
        return stdin if stdin is not None else sys_stdin.get()
    else:
        with open(path, 'r') as reader:
            return reader.read()

def run(cmd: Cmd, guard_stack: bool, stdin: str | None = None) -> str:
    match cmd:
        case Lex(path):
            tokens = Lexer(read_path(path, stdin)).lex()
            return "\n".join([str(token) for token in tokens])
        case Parse(path):
            file_content = read_path(path, stdin)
            tokens = Lexer(file_content).lex()
            module = parser.Parser(path, file_content, tokens).parse()
            return str(module)
        case Resolve(path):
            modules: Dict[str, parser.Module] = {}
            load_recursive(modules, os.path.normpath(path), None, stdin)
            resolved_modules = resolve_modules(modules)
            return str(resolved_modules.formattable(format.Str, lambda x: x))
        case Unstack(path, function_name):
            modules = {}
            load_recursive(modules, os.path.normpath(path), None, stdin)
            resolved_modules = resolve_modules(modules)

            f = resolved_modules.index(len(resolved_modules) - 1).functions[function_name]
            if isinstance(f, resolved.Extern):
                return "TODO"
            unstacked = unstacking.unstack_function(list(resolved_modules.values()), f)
            return str(unstacked)
        case Check(path):
            modules = {}
            load_recursive(modules, os.path.normpath(path), None, stdin)
            resolved_modules = resolve_modules(modules)
            checked_modules = check_modules(resolved_modules)
            return str(checked_modules.formattable(format.Str, lambda x: x))
        case Monomize(path):
            return "TODO"
        case Compile(path):
            modules = {}
            load_recursive(modules, os.path.normpath(path), None, stdin)
            resolved_modules = resolve_modules(modules)
            checked_modules = check_modules(resolved_modules)
            function_table, mono_modules = Monomizer(checked_modules).monomize()
            for mono_module in mono_modules.values():
                merge_locals_module(mono_module)
            return WatGenerator(mono_modules, function_table, guard_stack).write_wat_module()

help = """The native Watim compiler

Usage: watim <command> <watim-source-file> [options]
Commands:
  lex       Lex code and print the Tokens.
    <path>

  parse     Parse code and print the AST
    <path>

  resolve   resolve all identifiers
    <path>

  unstack   run unstacker for a function
    <path> <function>

  graph     generate graph from unstacked function
    <path> <function>

  infer     run type inference for function
    <path> <function> [log-level]
    log-level = 0 | 1 | 2

  check     unstack and infer everything
    <path>

  monomize  monomorphize all generic functions
    <path>

  optimize  run optimization passes
    <path>

  compile   compile to webassembly text format
    <path>
Options:
  -q, --quiet  Don't print any logs to stderr
"""

@dataclass
class CliArgException(Exception):
    message: str

def main(argv: List[str], stdin: str | None = None) -> str:
    argv = [arg for arg in argv if arg != "-q"]
    if len(argv) == 1:
        raise CliArgException(help)
    if argv[1] == "units":
        suite = unittest.TestSuite()
        classes = [DetermineLoadsToValueTests]
        for klass in classes:
            for method in dir(klass):
                if method.startswith("test_"):
                    suite.addTest(klass(method))
        runner = unittest.TextTestRunner()
        runner.run(suite)
        return ""
    cmd: Cmd
    if len(argv) >= 2 and argv[1] == "lex":
        path = argv[2] if len(argv) > 2 else "-"
        cmd = Lex(path)
    elif len(argv) >= 2 and argv[1] == "parse":
        path = argv[2] if len(argv) > 2 else "-"
        cmd = Parse(path)
    elif len(argv) >= 2 and argv[1] == "resolve":
        path = argv[2] if len(argv) > 2 else "-"
        cmd = Resolve(path)
    elif len(argv) >= 2 and argv[1] == "unstack":
        if len(argv) < 4:
            raise CliArgException(help)
        cmd = Unstack(argv[2], argv[3])
    elif len(argv) > 2 and argv[1] == "check":
        path = argv[2] if len(argv) > 2 else "-"
        cmd = Check(path)
    elif len(argv) > 2 and argv[1] == "monomize":
        path = argv[2] if len(argv) > 2 else "-"
        cmd = Monomize(path)
    elif len(argv) > 2 and argv[1] == "compile":
        path = argv[2] if len(argv) > 2 else "-"
        cmd = Compile(path)
    else:
        raise CliArgException(help)
    return run(cmd, "--guard-stack" in argv, stdin)

if __name__ == "__main__":
    try:
        print(main(sys.argv))
    except CliArgException as e:
        print(e.message, file=sys.stderr)
        exit(1)
    except ParseException as e:
        print(e.display(), file=sys.stderr)
        exit(1)
    except ResolveException as e:
        print(e.display(), file=sys.stderr)
        exit(1)
    except CheckException as e:
        print(e.display(), file=sys.stderr)
        exit(1)
