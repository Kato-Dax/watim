#!/usr/bin/env python
from dataclasses import dataclass
from typing import List
import subprocess
import tempfile
import glob
import json
import sys
import os
import difflib

sys.path.insert(0, os.path.abspath('./bootstrap'))
from bootstrap import __main__
bootstrap_compiler = __main__

compare_stderr = True
if "--ignore-stderr" in sys.argv:
    compare_stderr = False
    sys.argv.remove("--ignore-stderr")

interactive = False
if "--interactive" in sys.argv:
    interactive = True
    sys.argv.remove("--interactive")

native = False
if "--native" in sys.argv:
    native = True
    sys.argv.remove("--native")

if not os.path.isfile("test.wat"):
    if subprocess.run("bash ./run.sh ./native/main.watim compile ./test.watim -q > test.wat", shell=True).returncode != 0:
        exit(1)

def parse_test_file(path: str) -> dict | None:
    output = subprocess.run(f"wasmtime --dir=. -- test.wat read {path}", shell=True, stdout=subprocess.PIPE)
    if output.returncode != 0:
        return None
    return json.loads(output.stdout)

def write_test_file(path: str, test: dict):
    output = subprocess.run(["wasmtime", "--dir=.", "--", "./test.wat", "write", path], input=bytes(json.dumps(test), 'UTF-8'))
    if output.returncode != 0:
        print(output, file=sys.stderr)
        return exit(1)

@dataclass
class CompilerOutput:
    returncode: int
    stdout: str
    stderr: str

watim_bin_path = None
if native:
    if os.path.isfile("./watim.wasm"):
        if subprocess.run("wasmtime --dir=. -- ./watim.wasm compile ./native/main.watim > watim.wat", shell=True).returncode != 0:
            exit(1)
    else:
        if subprocess.run("python bootstrap compile ./native/main.watim > watim.wat", shell=True).returncode != 0:
            exit(1)
    watim_bin_path = os.path.realpath("./watim.wat")

def run_native_compiler(args: List[str] | None, stdin: str):
    assert(watim_bin_path is not None)
    compiler = subprocess.run(["wasmtime", "--dir=.", "--", watim_bin_path] + (args or ["compile", "-", "--quiet"]), input=bytes(stdin, 'UTF-8'), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return CompilerOutput(compiler.returncode, compiler.stdout.decode("UTF-8").strip(), compiler.stderr.decode("UTF-8").strip())

bootstrap_entry_path = os.path.realpath("./bootstrap")
def run_bootstrap_compiler(args: List[str] | None, stdin: str) -> CompilerOutput:
    main = bootstrap_compiler.main
    stderr = ""
    stdout = ""
    status = 0
    try:
        stdout = main(["bootstrap.py"] + (args or ["compile", "-", "--quiet"]), stdin=stdin)
    except bootstrap_compiler.CliArgException as e:
        stderr = e.message
        status = 1
    except bootstrap_compiler.ParseException as e:
        stderr = e.display()
        status = 1
    except bootstrap_compiler.ResolveException as e:
        stderr = e.display()
        status = 1
    except bootstrap_compiler.InferenceException as e:
        stderr = e.display()
        status = 1
    return CompilerOutput(status, stdout.strip(), stderr.strip())

def accept(test_path: str):
    test = parse_test_file(test_path)
    if test is None:
        print(f"{path}: failed to parse test file", file=sys.stderr)
        return
    os.chdir("./tests/fixtures")
    if native:
        compiler = run_native_compiler(test['compiler-args'], test['compiler-stdin'])
    else:
        compiler = run_bootstrap_compiler(test['compiler-args'], test['compiler-stdin'])
    os.chdir("../..")
    stdout = None
    stderr = None
    status = None
    if compiler.returncode == 0 and test['status'] is not None:
        with open('./out.wat', 'wb') as outwat:
            outwat.write(compiler.stdout.encode("UTF-8"))
        program = subprocess.run(["wasmtime", "./out.wat"], input=bytes(test["stdin"] or "", 'UTF-8'), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout = None if test['stdout'] is None else program.stdout.decode()
        stderr = None if test['stderr'] is None else program.stderr.decode()
        status = None if test['status'] is None else program.returncode
    write_test_file(path, {
        "compiler-stdin": test['compiler-stdin'],
        "compiler-args": test['compiler-args'],
        "compiler-stdout": None if test['compiler-stdout'] is None else compiler.stdout,
        "compiler-stderr": None if test['compiler-stderr'] is None else compiler.stderr,
        "compiler-status": None if test['compiler-status'] is None else compiler.returncode,
        "stdin": test['stdin'],
        "stdout": stdout,
        "stderr": stderr,
        "status": status,
    })

if len(sys.argv) > 2 and sys.argv[1] == "accept":
    paths = sys.argv[2:]
    for path in paths:
        accept(path)
    exit(0)

tests = set()
if len(sys.argv) > 1:
    tests = set(path for pattern in sys.argv[1:] for path in glob.glob(pattern, recursive=True))
else:
    tests = set(glob.glob("./tests/**/*.watim", recursive=True)).difference(set(glob.glob("./tests/fixtures/**", recursive=True)))

def print_mismatch(expected: str, actual: str):
    for line in difflib.unified_diff(expected.splitlines(), actual.splitlines(), fromfile='expected', tofile='actual'):
        print(line, file=sys.stderr)

@dataclass
class Test:
    compiler_stdin: str | None
    compiler_status: int | None
    compiler_stdout: str | None
    compiler_stderr: str | None
    stdin: str | None
    status: int | None
    stdout: str | None
    stderr: str | None

failed = False
for path in tests:
    test = parse_test_file(path)
    previous_failed = failed
    failed = True
    if test is None:
        print(f"{path}: failed to parse test file", file=sys.stderr)
        exit(1)
    if test["compiler-stdin"] is None:
        print(f"{path}: compiler-stdin ist missing", file=sys.stderr)
        continue
    os.chdir("./tests/fixtures")
    if native:
        compiler = run_native_compiler(test['compiler-args'], test['compiler-stdin'])
    else:
        compiler = run_bootstrap_compiler(test['compiler-args'], test['compiler-stdin'])
    os.chdir("../..")

    def on_error():
        if interactive:
            response = input("accept?\ny/n:")
            if response == "y":
                accept(path)

    if test['compiler-status'] is not None and compiler.returncode != test['compiler-status']:
        print(f"{path}: expected different compiler status:", file=sys.stderr)
        print(f"Expected:\n{test['compiler-status']}", file=sys.stderr)
        print(f"Actual:\n{compiler.returncode}", file=sys.stderr)
        print(f"compiler-stderr was: {compiler.stderr}", file=sys.stderr)
        on_error()
        continue
    if compare_stderr and test['compiler-stderr'] is not None and compiler.stderr != test['compiler-stderr'].strip():
        print(f"{path}: expected different compiler stderr:", file=sys.stderr)
        print_mismatch(test['compiler-stderr'], compiler.stderr)
        on_error()
        continue
    if test['compiler-stdout'] is not None and compiler.stdout != test['compiler-stdout'].strip():
        print(f"{path}: expected different compiler stdout:", file=sys.stderr)
        print_mismatch(test['compiler-stdout'], compiler.stdout)
        print(f"stderr was: {compiler.stderr}", file=sys.stderr)
        on_error()
        continue

    with tempfile.TemporaryDirectory() as tmpdir:
        outwat_path = os.path.join(tmpdir, 'out.wat')
        with open(outwat_path, 'wb') as outwat:
            outwat.write(compiler.stdout.encode("UTF-8"))
        if compiler.returncode == 0 and test['status'] is not None:
            program = subprocess.run(["wasmtime", outwat_path], input=bytes(test["stdin"] or "", 'UTF-8'), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if test['stderr'] is not None and program.stderr.strip() != test['stderr'].encode('UTF-8').strip():
                print(f"{path}: expected different stderr:", file=sys.stderr)
                print(f"Expected:\n{test['stderr']}", file=sys.stderr)
                print(f"Actual:\n{program.stderr.decode('UTF-8')}", file=sys.stderr)
                on_error()
                continue
            if test['stdout'] is not None and program.stdout.strip() != test['stdout'].encode('UTF-8').strip():
                print(f"{path}: expected different stdout:", file=sys.stderr)
                print(f"Expected:\n{test['stdout']}", file=sys.stderr)
                print(f"Actual:\n{program.stdout.decode('UTF-8')}", file=sys.stderr)
                on_error()
                continue
            if test['status'] is not None and program.returncode != test['status']:
                print(f"{path}: expected different status:", file=sys.stderr)
                print(f"Expected:\n{test['status']}", file=sys.stderr)
                print(f"Actual:\n{program.returncode}", file=sys.stderr)
                if test['stderr'] is None:
                    print(f"stderr was: {program.stderr.decode('UTF-8')}", file=sys.stderr)
                on_error()
                continue
    failed = previous_failed
    print(f"{path} passed")

if failed:
    exit(1)
