from typing import List, Callable, Tuple, Protocol, runtime_checkable, Iterable
from dataclasses import dataclass

type Writable = None | str | int | bool | Tuple[Formattable, ...] | Formattable

@dataclass
class Formatter:
    indentation: str
    indentation_level: int
    splits: List[str]

    def indent(self):
        self.indentation_level += 1
    def dedent(self):
        self.indentation_level -= 1
    def indented(self, body: Callable):
        self.indent()
        try:
            body()
        finally:
            self.dedent()
    def write_indent(self):
        self.splits.extend(self.indentation for _ in range(self.indentation_level))

    def write(self, *values: Writable) -> 'Formatter':
        for value in values:
            if isinstance(value, str):
                self.splits.append(value)
                continue
            if isinstance(value, bool):
                self.write("True" if value else "False")
                continue
            if isinstance(value, int):
                self.write(str(value))
                continue
            if value is None:
                self.write("None")
                continue
            if isinstance(value, tuple):
                Seq(value).format(self)
                continue
            value.format(self)
        return self

    def to_string(self) -> str:
        return "".join(self.splits)

    def unnamed_record(self, name: str, fields: List[Writable]):
        self.write("(", name)
        for field in fields:
            self.write(" ", field)
        self.write(")")

    def named_record(self, name: str, fields: List[Tuple[str, Writable]]):
        if len(fields) == 0:
            return self.write("(", name, ")")
        self.write("(", name, "\n")
        self.indent()
        for i,(name,value) in enumerate(fields):
            self.write_indent()
            self.write(name, "=", value)
            if i + 1 == len(fields):
                break
            self.write(",\n")
        self.dedent()
        self.write(")")

@runtime_checkable
class Formattable(Protocol):
    def format(self, fmt: Formatter) -> None:
        fmt.write(type(self).__name__)
    def __str__(self) -> str:
        return Formatter("  ", 0, []).write(self).to_string()

@dataclass(frozen=True)
class Seq(Formattable):
    seq: Iterable[Writable]
    multi_line: bool = False

    def format(self, fmt: Formatter):
        fmt.write("[")
        i = 0
        for value in self.seq:
            if self.multi_line:
                if i == 0:
                    fmt.indent()
                    fmt.write("\n").write_indent()
                else:
                    fmt.write(",\n").write_indent()
            elif i != 0:
                fmt.write(", ")
            fmt.write(value)
            i += 1
        if self.multi_line and i != 0:
            fmt.dedent()
        fmt.write("]")

@dataclass(frozen=True)
class Dict(Formattable):
    dict: dict[Writable, Writable]
    def format(self, fmt: Formatter):
        if len(self.dict) == 0:
            fmt.write("(Map)")
            return
        fmt.write("(Map\n")
        try:
            fmt.indent()
            for i,(k,v) in enumerate(self.dict.items()):
                fmt.write_indent()
                fmt.write(k, "=", v)
                if i + 1 != len(self.dict):
                    fmt.write(",\n")
        finally:
            fmt.dedent()
            fmt.write(")")

@dataclass(frozen=True)
class Str:
    value: str
    def format(self, fmt: Formatter):
        fmt.write("\"", self.value, "\"")

@dataclass(frozen=True)
class Optional(Formattable):
    value: Writable | None
    def format(self, fmt: Formatter):
        if self.value is None:
            fmt.write("None")
            return
        fmt.write("(Some ", self.value, ")")

@dataclass(frozen=True)
class UnnamedRecord(Formattable):
    name: str
    fields: List[Writable]
    def format(self, fmt: Formatter):
        fmt.unnamed_record(self.name, self.fields)

