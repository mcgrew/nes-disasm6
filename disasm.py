#!/usr/bin/env python3

from enum import Enum
from collections import OrderedDict
from sys import argv, stdout
from io import StringIO

def to_hex(*bytes_:bytes):
    return ' '.join([f'{x:02x}' for x in bytes_])

def table(*bytes_:bytes):
    return '.hex ' + to_hex(*bytes_)

class OpType(Enum):
    IMPLIED, IMMMEDIATE, ACCUMULATOR, BRANCH, ZEROPAGE, ABSOLUTE, INDIRECT = range(7)

class Indexing(Enum):
    NONE, X, Y = ('', 'x', 'y')

    def __str__(self):
        return self.value

class Instruction:
    def __init__(self, position, *_bytes):
        self.position = position
        self.opcode = _bytes[0]
        b1 = _bytes[1] if len(_bytes) > 1 else None
        b2 = _bytes[2] if len(_bytes) > 2 else None
        self._size = 0
        self.label = 0

        self.op = ''
        self.comment = ''
        self.pre_comment = ''
        self.indexing = Indexing.NONE

        if b2 is not None and self.opcode == 0x6c:
            self.type = OpType.INDIRECT
            self.op = 'jmp'
            self._size = 3

        elif self.implied(self.opcode):
            self.type = OpType.IMPLIED
            self._size = 1

        elif self.accumulator(self.opcode):
            self.type = OpType.ACCUMULATOR
            self._size = 1

        elif b1 is not None and self.immediate(self.opcode):
            self.type = OpType.IMMMEDIATE
            self._size = 2

        elif b1 is not None and self.zeropage(self.opcode):
            self.type = OpType.ZEROPAGE
            self._size = 2

        elif b1 is not None and self.indirect(self.opcode):
            self.type = OpType.INDIRECT
            self._size = 2

        elif b1 is not None and self.branch(self.opcode):
            self.type = OpType.BRANCH
            dest = self.position + 2 + (b1 if b1 < 128 else b1 - 256)
            self.label = dest
            self._size = 2

        elif b2 is not None and self.absolute(self.opcode):
            self.type = OpType.ABSOLUTE
            if not b2:
                self.pre_comment = f'{self.op} ${b2:02x}{b1:02x}'
            self._size = 3

        if self.op:
            self.comment = f'{self.position:04X}:  ' + \
                ' '.join([f'{x:02x}' for x in _bytes[:self._size]])
        self.bytes = bytes(_bytes[:self._size])

    def implied(self, opcode):
        if opcode & 0xf == 0x8:
            self.op = (( 'php', 'clc', 'plp', 'sec', 'pha', 'cli', 'pla', 'sei',
                'dey', 'tya', 'tay', 'clv', 'iny', 'cld', 'inx', 'sed')
                [opcode >> 4])
        if opcode == 0x00:
            self.op = 'brk'
        if opcode == 0x40:
            self.op = 'rti'
        if opcode == 0x60:
            self.op = 'rts'
        if opcode & 0x8f == 0x8a:
            self.op = ('txa', 'txs', 'tax', 'tsx', 'dex', '', 'nop', '')[(opcode >> 4) - 8]
        if self.op:
            return True
        return False

    def zeropage(self, opcode):
        if opcode & 0xf == 5:
            self.op = ('ora', 'and', 'eor', 'adc', 'sta', 'lda', 'cmp', 'sbc')[opcode >> 5]
        if opcode & 0xf == 6:
            self.op = ('asl', 'rol', 'lsr', 'ror', 'stx', 'ldx', 'dec', 'inc')[opcode >> 5]
        if opcode == 0x24:
            self.op = 'bit'
        if opcode in (0x84, 0x94, 0xa4, 0xc4, 0xe4):
            self.op = ('sty', 'ldy', 'cpy', 'cpx')[(opcode >> 5) - 8]

        if self.op:
            if opcode & 0x10 == 0x10:
                self.indexing = Indexing.X
            if opcode in (0x96, 0xb6):
                self.indexing = Indexing.Y
            return True
        return False

    def absolute(self, opcode):
        if opcode in (0x9c, 0x9e):
            return False
        zp = self.zeropage(opcode - 8)
        if opcode == 0x20:
            self.op = 'jsr'
        if opcode == 0x4c:
            self.op = 'jmp'
        if self.opcode:
            return True
        return False

    def branch(self, opcode):
        if opcode & 0x1f == 0x10:
            self.op = ('bpl', 'bmi', 'bvc', 'bvs', 'bcc', 'bcs', 'bne', 'beq')[opcode >> 5]
            return True
        return False

    def accumulator(self, opcode):
        if opcode & 0x9f == 0x0a:
            self.op = ('asl', 'rol', 'lsr', 'ror')[opcode >> 5]
            return True
        return False

    def immediate(self, opcode):
        if opcode & 0x1f == 0x09:
            self.op = ('ora', 'and', 'eor', 'adc', '', 'lda', 'cmp', 'sbc')[opcode >> 5]
        if opcode & 0x8f == 0x80:
            self.op = ('', 'ldy', 'cpy', 'cpx')[(opcode & ~0x80) >> 5]
        if opcode == 0xa2:
            self.op = 'ldx'
        if self.op:
            return True
        return False

    def indirect(self, opcode):
        if opcode & 0xf == 1:
            self.op = ('ora', 'and', 'eor', 'adc', 'sta', 'lda', 'cmp', 'sbc')[opcode >> 5]
            self.indexing = Indexing.Y if (opcode >> 4) & 1 else Indexing.X
            return True
        return False

    def __bool__(self):
        return bool(self.op)

    def __len__(self):
        return self._size

    def __str__(self):
        if not self.op:
            return ''
        b1 = self.bytes[1] if len(self.bytes) > 1 else None
        b2 = self.bytes[2] if len(self.bytes) > 2 else None
        ret = ' ' * 12 
        if self.type == OpType.IMPLIED:
            ret += self.op
        if self.type == OpType.ACCUMULATOR:
            ret += f'{self.op} a'
        if self.type == OpType.IMMMEDIATE:
                ret += f'{self.op} #${b1:02x}'
        if self.type == OpType.BRANCH:
            ret += f'bpl ${self.label:x}'
        if self.type == OpType.ZEROPAGE:
            if self.indexing == Indexing.NONE:
                ret += f'{self.op} ${b1:02x}'
            else:
                ret += f'{self.op} ${b1:02x}, {self.indexing}'
        if self.type == OpType.ABSOLUTE:
            if not b2:
                ret = ret[:-4]
                ret += f'.hex {self.opcode:02x} {b1:02x} {b2:02x}'
            elif self.indexing == Indexing.NONE:
                ret += f'{self.op} ${b2:02x}{b1:02x}'
            elif self.indexing == Indexing.X:
                ret += f'{self.op} (${b2:02x}{b1:02x}, x)'
            elif self.indexing == Indexing.Y:
                ret += f'{self.op} (${b2:02x}{b1:02x}), y'

        if self.type == OpType.INDIRECT:
            if self.op == 'jmp':
                ret += f'{self.op} (${b2:02x}{b1:02x})'
            elif self.indexing == Indexing.NONE:
                ret += f'{self.op} ${b1:02x}'
            elif self.indexing == Indexing.X:
                ret += f'{self.op} (${b1:02x}, x)'
            elif self.indexing == Indexing.Y:
                ret += f'{self.op} (${b1:02x}), y'

        if self.comment:
            ret = f'{ret:28s}; {self.comment}'
        if self.pre_comment:
            ret = f';           {self.pre_comment}\n{ret}'
        ret += '\n'

        return ret

    def __add__(self, instr):
        s = Subroutine(self.position)
        s.append(self)
        s.append(instr)
        return s


class Bank:
    def __init__(self, number:int, base:int, *_bytes:bytes):
        self.bytes = _bytes
        self.base = base
        self.components = []
        self.disassemble(_bytes[:-6], _bytes[-6:])
        i = 0

    def disassemble(self, bank_bytes, interrupts):
        last_instr = i = 0
        while i < len(bank_bytes):
            instr = Instruction(i + self.base, *bank_bytes[i:i+3])
            if instr:
                if not len(self.components) or type(self.components[-1]) is not Subroutine \
                        or self.components[-1].is_valid():
                    self.components.append(Subroutine(instr.position))
                self.components[-1].append(instr)
                i += len(instr)
            else:
                if len(self.components) and type(self.components[-1]) is Subroutine:
                    self.merge_tables()
                if not len(self.components) or type(self.components[-1]) is not Table:
                    self.components.append(Table(i + self.base))
                self.components[-1].extend(bank_bytes[i])
                i += 1
        self.components.append(Word(*interrupts[:2], 'NMI'))
        self.components.append(Word(*interrupts[2:4], 'RESET'))
        self.components.append(Word(*interrupts[4:], 'IRQ'))

    def merge_tables(self):
        if len(self.components):
            c = self.components[-1]
            if not c.is_valid():
                self.components[-1] = Table(c.position, *c.bytes())
                while len(self.components) > 1 and type(self.components[-2]) is Table:
                    self.components[-2] += self.components[-1]
                    self.components = self.components[:-1]

    def find_base(self):
        pass

    def __str__(self):
        buf = StringIO()
        buf.write(f'.base ${self.base:04x}\n\n')
        for c in self.components:
            buf.write(str(c))
        buf.seek(0)
        return buf.read()

class Base:
    def __init__(self, base:int):
        self.base = base

    def __str__(self):
        return f'.base ${self.base:04x}\n'

class Subroutine:
    def __init__(self, position:int):
        self.position = position
        self.instructions = []

    def is_valid(self):
        return self.instructions[-1].op in ('rts', 'jmp')

    def append(self, instruction:Instruction):
        self.instructions.append(instruction)

    def bytes(self):
        ret = bytes()
        for i in self.instructions:
            ret += i.bytes
        return bytes(ret)

    def __len__(self):
        return sum([len(i) for i in self.instructions])

    def __str__(self):
        buf = StringIO()
        buf.write(f'sub_{self.position:04x}:\n')
        for i in self.instructions:
            buf.write(str(i))
        buf.seek(0)
        return buf.read()


class Table:
    def __init__(self, position:int, *_bytes:bytes):
        self.bytes = bytes(_bytes)
        self.position = position

    def extend(self, *_bytes:bytes):
        self.bytes += bytes(_bytes)

    def __add__(self, obj):
        if not hasattr(obj, 'bytes'):
            raise TypeError("unsupported operand type(s) for +: "
                    f"'{type(self).__name__}' and '{type(obj).__name__}'")
        if callable(obj.bytes):
            return Table(self.position, *(self.bytes + obj.bytes()))
        return Table(self.position, *(self.bytes + obj.bytes))

    def __str__(self):
        buf = StringIO()
        buf.write(f'tab_{self.position:04x}:\n')
        for i in range(0, len(self.bytes), 16):
            buf.write(' ' * 8)
            buf.write(f'.hex {" ".join([f"{x:02x}" for x in self.bytes[i:i+16]])}\n')
        buf.seek(0)
        return buf.read()

    def __len__(self):
        return len(self.bytes)

class Word:
    def __init__(self, b1, b2, comment):
        self.b1 = b1
        self.b2 = b2
        self.comment = comment

    def __str__(self):
        return f'        .word ${self.b2:02x}{self.b1:02x}         ' \
                f'; {self.comment:10s}{self.b1:02x} {self.b2:02x}\n'

    def __len__(self):
        return 2


def main():
    banks = []
    with open(argv[1], 'rb') as f:
        header = f.read(16)
        for i in range(header[4]):
            rom = f.read(16384)
            banks.append(Bank(0, 0x8000, *rom))
    for b in banks:
        print(b)

if __name__ == '__main__':
    main()


