# Watim

Watim is a simple, low level, stack-based language which compiles to [Webassembly Text Format (WAT)](https://developer.mozilla.org/en-US/docs/WebAssembly/Understanding_the_text_format).
Which can then be compiled to wasm and run in your favorite browser or by runtimes like [wasmtime](https://github.com/bytecodealliance/wasmtime) and [wasm3](https://github.com/wasm3/wasm3).

The Watim compiler is written in Watim.
The bootstrap compiler is written in python, see [bootstrap](./bootstrap).

This project was inspired by [Porth](https://gitlab.com/tsoding/porth).

Watim = WAT Improved

## Features
- structs
- inline string literals
- terse syntax
- loop expression with `break` keyword
- if expression
- static type checking
- generics using monomorphization
- type inference
- file imports

## TODO
- [ ] `continue` instruction for loops.
- [X] Variable declaration and initiliziation anywhere in function.
- [X] Generics using monomorphization.
- [x] Bidirectional Type inference sort of like [this](https://jimmyhmiller.github.io/pdfs/bidirectional.pdf)
- [X] function pointers
- [X] struct literals
- [ ] error messages that don't just say 'TODO'
- [ ] anonymous functions
- [ ] closures
- [ ] Some sort of Typeclass/Trait system perhaps?

## How to run
With nix: `nix develop`

Or manually install:
- [Wasmtime](https://wasmtime.dev/) 
- [Wabt](https://github.com/WebAssembly/wabt).
- [Python3](https://www.python.org/)

Then compile:
```bash
watim <watim-source-file> > out.wat
```

Then run:
```bash
wasmtime --dir=. ./out.wat [args]...
```

Or just use the provided script:
```bash
./run.sh <watim-source-file> [args]...
```
The script will run [`bootstrap.py`](./bootstrap.py) on first use.

For example:
```bash
./run.sh ./samples/cat.watim ./README.md
```

## Editor Support
VIM syntax highlighting in [./editor/watim.vim](https://github.com/Blugatroff/watim/tree/main/editor/watim.vim)

### Kate
Syntax highlighting in [./editor/watim.xml](https://github.com/Blugatroff/watim/tree/main/editor/watim.xml)<br>
Just copy it into one of the directories listed [here](https://docs.kde.org/stable5/en/kate/katepart/highlight.html#idm3839) to install it.


## Example Program
This program exits with the exit code read from stdin.
```
extern "wasi_snapshot_preview1" "fd_read" fn raw_read(file: i32, iovs: .Iov, iovs_count: i32, written: .i32) -> i32
extern "wasi_snapshot_preview1" "fd_write" fn raw_write(file: i32, iovs: .Iov, iovs_count: i32, written: .i32) -> i32
extern "wasi_snapshot_preview1" "proc_exit" fn exit(code: i32)

struct Iov {
    ptr: .i8
    len: i32
}
fn write(file: i32, ptr: .i8, len: i32) -> i32 {
    uninit @iov
    0 @written
    $ptr #iov.ptr
    $len #iov.len
    $file &iov 1 &written raw_write drop
    $written $len = if {
        $len
    } else {
        $file $ptr $written + $len $written - write $written +
    }
}

fn read(file: i32, buf-addr: .i8, buf-size: i32) -> i32 {
    0 @nread
    uninit @iov
    $buf-addr #iov.ptr
    $buf-size #iov.len
    $file &iov 1 &nread raw_read drop
    $nread
}

struct Buf { a: i32 b: i32 c: i32 d: i32 e: i32 f: i32 g: i32 h: i32 }

fn print(n: i32) {
    uninit<Buf> @buf &buf !.i8 @buf
    uninit<Buf> @buf-reversed &buf-reversed !.i8 @buf-reversed
    0 @l
    $n 0 = if {
        1 #l // length = 1
        $buf 48 !i8 store // put '0' in buf
    } else {
        loop {
            $n 0 = if { break }
            $buf $l +
            $n 10 % // rightmost digit
            48 + !i8 // + ascii 'a'
            store
            $n 10 / #n // shift right in decimal
            $l 1 + #l
        }
    }
    0 @i
    loop {
        $buf-reversed $i +
        $buf $l 1 - $i - + ~
        store
        $i 1 + #i
        $i $l = if { break }
    }
    1 $buf-reversed $l write drop
}

fn write_byte(file: i32, b: i8) {
    $file &b !.i8 1 write drop
}

fn parse(pt: .i8, len: i32) -> i32 {
    $pt @original-ptr
    $len @original-len
    0 @n
    loop {
        $pt ~ !i32 @d
        $d 48 ge $d 58 le and if { // 48 is ascii '0'
            $n $d 48 - + #n
        } else {
            1 "Failed to parse: '" write drop
            1 $original-ptr $original-len write drop
            1 "'" write drop
            //1 "\n" write drop
            1 10 !i8 write_byte
            1 exit
        }
        $pt 1 + #pt // advance pointer
        $len 1 - #len // reduce length
        $len 0 = if { $n break }
        $n 10 * #n
    }
}

fn dup<T>(a: T) -> T, T { $a $a }

fn main "_start" () {
    uninit<Buf> @buf &buf !.i8 @buf
    0 $buf 32 read @nread
    $nread 0 /= if {
        $buf $nread 1 - + ~ "\n" drop ~ = if { $nread 1 - #nread }
    }
    $buf $nread parse
    dup print
    1 "\n" write drop
    exit
}
```
