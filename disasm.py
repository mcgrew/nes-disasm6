#!/usr/bin/env python3

from enum import Enum
from collections import OrderedDict
from sys import argv, stdout, stderr
from io import StringIO
from os import urandom
from base64 import b32encode

def to_hex(bytes_:bytes):
    return ' '.join([f'{x:02x}' for x in bytes_])

def table(bytes_:bytes):
    return '.hex ' + to_hex(bytes_)

class OpType(Enum):
    IMPLIED, IMMMEDIATE, ACCUMULATOR, BRANCH, ZEROPAGE, ABSOLUTE, INDIRECT = range(7)

class Indexing(Enum):
    NONE, X, Y = ('', 'x', 'y')

    def __str__(self):
        return self.value

class Bank:
    def __init__(self, number:int, base:int, _bytes:bytes):
        self._bytes = bytes(_bytes)
        self.base = base if base else 0x8000
        self.number = number
        self.components = []
        self.disassemble(_bytes[:-6], _bytes[-6:])
        i = 0
        if not base:
            old_base = self.base
            new_base = self.find_base()
            # use the jump addresses to guess the base address of this bank
            if new_base != old_base:
                # it changed, so redo the disassembly
                self.base = new_base
                self.disassemble(_bytes[:-6], _bytes[-6:])
        self._add_labels()

    def disassemble(self, bank_bytes:bytes, interrupts:bytes=bytes()):
        self.components.clear()
        last_instr = i = 0
        while i < len(bank_bytes):
            instr = Instruction(i + self.base, self, bank_bytes[i:i+3])
            if instr:
                if not len(self.components) or type(self.components[-1]) is not Subroutine \
                        or self.components[-1].is_valid():
                    self.components.append(Subroutine(self, instr.position))
                self.components[-1].append(instr)
                i += len(instr)
            else:
                if len(self.components) and type(self.components[-1]) is Subroutine:
                    self.merge_tables()
                if not len(self.components) or type(self.components[-1]) is not Table:
                    self.components.append(Table(i + self.base, self))
                self.components[-1].append(bank_bytes[i])
                i += 1
        if len(interrupts):
            nmi = Word(0xffa, *interrupts[:2], 'NMI')
            reset = Word(0xffc, *interrupts[2:4], 'RESET')
            irq = Word(0xffe, *interrupts[4:], 'IRQ')
            if self._valid_interrupts(nmi, reset, irq):
                self.components.append(nmi)
                self.components.append(reset)
                self.components.append(irq)
            else:
                if type(self.components[-1]) is Table:
                    t = self.components[-1]
                else:
                    t = Table(self.base + len(bank_bytes), self)
                    self.components.append(t)
                t.extend(nmi)
                t.extend(reset)
                t.extend(irq)

    def _valid_interrupts(self, nmi, reset, irq):
        if nmi.addr < 0x8000 or reset.addr < 0x8000 or irq.addr < 0x8000:
            return False
        if nmi.addr >= 0xfffa or reset.addr >= 0xfffa or irq.addr >= 0xfffa:
            return False
        return True

    def merge_tables(self):
        if len(self.components):
            c = self.components[-1]
            if not c.is_valid():
                self.components[-1] = Table(c.position, self, c)
                while len(self.components) > 1 and type(self.components[-2]) is Table:
                    self.components[-2].extend(self.components[-1])
                    self.components = self.components[:-1]

    def _add_labels(self):
        for c in self.components:
            if type(c) is Subroutine:
                for i in c.instructions:
                    if i.type == OpType.BRANCH:
                        b1 = bytes(i)[1]
                        dest = i.position + 2 + (b1 if b1 < 128 else b1 - 256)
                        target = self.find_instr(dest)
                        if target:
                            i.dest = target.get_label()
                    elif i.op == 'jmp' and i.type == OpType.ABSOLUTE:
                        dest = bytes(i)[2] << 8 | bytes(i)[1]
                        target = self.find_instr(dest)
                        if target:
                            i.dest = target.get_label()


    def find_instr(self, position) -> 'Instruction':
        for c in self.components:
            if type(c) is Subroutine:
                for i in c.instructions:
                    if i.position == position:
                        return i
        return None

    def find_base(self):
        """
        Attempts to find the base address based on jump addresses in this bank.
        """
        base_8 = 0
        base_c = 0
        if type(self.components[-1]) is not Word:
            return 0x8000
        for c in self.components:
            if type(c) is Subroutine:
                for i in c.instructions:
                    if i.op in ('jmp', 'jsr') and i.type == OpType.ABSOLUTE:
                        b1, b2, _ = bytes(i)
                        jpoint = b2 << 8 | b1
                        if jpoint > 0xc000:
                            base_c += 1
                        elif jpoint > 0x8000:
                            base_8 += 1
        return 0xc000 if base_c > base_8 else 0x8000

    def __bytes__(self):
        return self._bytes

    def __str__(self):
        buf = StringIO()
        buf.write(f'.base ${self.base:04x}\n\n')
        for c in self.components:
            buf.write(str(c))
        buf.seek(0)
        return buf.read()

class Instruction:
    def __init__(self, position:int, bank:Bank, _bytes:bytes):
        self.position = position
        self.opcode = _bytes[0]
        self.bank = bank
        self._bytes = bytes(_bytes)
        b1 = _bytes[1] if len(_bytes) > 1 else None
        b2 = _bytes[2] if len(_bytes) > 2 else None
        self._size = 0
        self.label = ''
        self.dest = ''

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
            self._size = 2
            self.dest = f'${position + 2 + (b1 if b1 < 128 else b1 - 256):04X}'

        elif b2 is not None and self.absolute(self.opcode):
            self.type = OpType.ABSOLUTE
            if not b2:
                if self.indexing == Indexing.NONE:
                    self.pre_comment = f'{self.op} ${b2:02x}{b1:02x}'
                else:
                    self.pre_comment = f'{self.op} ${b2:02x}{b1:02x},{self.indexing}'
            self._size = 3

        if self.op:
            self.comment = f'{self.position:04X}:  ' + \
                ' '.join([f'{x:02x}' for x in _bytes[:self._size]])
        self._bytes = self._bytes[:self._size]

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
        if opcode in (0x84, 0x94, 0xa4, 0xb4, 0xc4, 0xe4):
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
        if self._bytes[2] >= 0x80: # don't interpret jumps below 0x8000
            if opcode == 0x20:
                self.op = 'jsr'
            if opcode == 0x4c:
                self.op = 'jmp'
        if opcode & 0x1f == 0x19:
            self.op = ('ora', 'and', 'eor', 'adc', 'sta', 'lda', 'cmp', 'sbc')[opcode >> 5]
        if opcode & 0xf == 0xd:
            self.op = ('ora', 'and', 'eor', 'adc', 'sta', 'lda', 'cmp', 'sbc')[opcode >> 5]
        if opcode & 0xf == 0xe:
            self.op = ('asl', 'rol', 'lsr', 'ror', 'stx', 'ldx', 'dec', 'inc')[opcode >> 5]
        if opcode == 0x2c:
            self.op = 'bit'
        if opcode in (0x8c, 0xac, 0xbc, 0xcc, 0xec):
            self.op = ('sty', 'ldy', 'cpy', 'cpx')[(opcode >> 5) - 8]
        if self.op:
            if opcode & 0x10 == 0x10:
                self.indexing = Indexing.X
            if opcode == 0xbe or opcode & 0x1f == 0x19:
                self.indexing = Indexing.Y
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
        if opcode & 0x9f == 0x80:
            self.op = ('', 'ldy', 'cpy', 'cpx')[(opcode >> 5) - 8]
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

    def get_label(self):
#         if not self._tag:
#             self._tag = '_' + b32encode(urandom(5)).decode('utf-8').lower()
        self.label = f'b{self.bank.number}_{self.position:04x}'
        return self.label

    def __bool__(self):
        return bool(self.op)

    def __len__(self):
        return self._size

    def __bytes__(self):
        return self._bytes

    def __str__(self):
        if not self.op:
            return ''
        b1 = self._bytes[1] if len(self._bytes) > 1 else None
        b2 = self._bytes[2] if len(self._bytes) > 2 else None
        buf = StringIO()
        if self.pre_comment:
            buf.write(f';           {self.pre_comment}\n')
        if self.label:
            buf.write(f'{self.label}:'.ljust(12))
        else:
            buf.write(' ' * 12)
        line_len = buf.tell()
        if self.type == OpType.IMPLIED:
            buf.write(self.op)
        if self.type == OpType.ACCUMULATOR:
            buf.write(f'{self.op} a')
        if self.type == OpType.IMMMEDIATE:
                buf.write(f'{self.op} #${b1:02x}')
        if self.type == OpType.BRANCH:
            buf.write(f'{self.op} {self.dest}')
        if self.type == OpType.ZEROPAGE:
            if self.indexing == Indexing.NONE:
                buf.write(f'{self.op} ${b1:02x}')
            else:
                buf.write(f'{self.op} ${b1:02x},{self.indexing}')
        if self.type == OpType.ABSOLUTE:
            if self.op == 'jmp' and self.dest:
                buf.write(f'{self.op} {self.dest}')
            elif not b2:
                buf.seek(buf.tell()-4)
                buf.write(f'.hex {self.opcode:02x} {b1:02x} {b2:02x}')
            elif self.indexing == Indexing.NONE:
                buf.write(f'{self.op} ${b2:02x}{b1:02x}')
            else:
                buf.write(f'{self.op} ${b2:02x}{b1:02x},{self.indexing}')

        if self.type == OpType.INDIRECT:
            if self.op == 'jmp':
                buf.write(f'{self.op} (${b2:02x}{b1:02x})')
            elif self.indexing == Indexing.NONE:
                buf.write(f'{self.op} ${b1:02x}')
            elif self.indexing == Indexing.X:
                buf.write(f'{self.op} (${b1:02x},x)')
            elif self.indexing == Indexing.Y:
                buf.write(f'{self.op} (${b1:02x}),y')

        if self.comment:
            buf.write(' ' * (28 + line_len - buf.tell()))
            buf.write(f'; {self.comment}')
        buf.write('\n')

        buf.seek(0)
        return buf.read()

    def __add__(self, instr):
        s = Subroutine(self.bank, self.position)
        s.append(self)
        s.append(instr)
        return s

class Subroutine:
    def __init__(self, bank:Bank, position:int):
        self.position = position
        self.instructions = []
        self.bank = bank

    def is_valid(self):
#         return len(self.instructions) > 1 and self.instructions[-1].op in ('rts', 'jmp')
        return self.instructions[-1].op in ('rts', 'jmp')

    def append(self, instruction:Instruction):
        self.instructions.append(instruction)

    def __bytes__(self):
        ret = bytes()
        for i in self.instructions:
            ret += bytes(i)
        return ret

    def __len__(self):
        return sum([len(i) for i in self.instructions])

    def __str__(self):
        buf = StringIO()
#         buf.write(f'sub_b{self.bank.number}_{self.position:04x}:\n')
        for i in self.instructions:
            buf.write(str(i))
        buf.seek(0)
        return buf.read()

class Table:
    def __init__(self, position:int, bank:Bank, _bytes:bytes=bytes()):
        self._bytes = bytes(_bytes)
        self.position = position
        self.bank = bank

    def append(self, byte:int):
        self._bytes += bytes((byte,))

    def extend(self, _bytes):
        self._bytes += bytes(_bytes)

    def __bytes__(self):
        return self._bytes

    def __str__(self):
        buf = StringIO()
        buf.write(f'tab_b{self.bank.number}_{self.position:04x}:\n')
        last_line = buf.tell()
        for i in range(0, len(self._bytes), 16):
            buf.write(' ' * 8)
            buf.write(f'.hex {" ".join([f"{x:02x}" for x in self._bytes[i:i+16]])}')
            buf.write(' ' * (60 + last_line - buf.tell()))
            buf.write(f'  ; {self.position + i:04X}\n')
            last_line = buf.tell()
        buf.seek(0)
        return buf.read()

    def __len__(self):
        return len(self._bytes)

class Word:
    def __init__(self, position, b1, b2, comment):
        self.position = position
        self.b1 = b1
        self.b2 = b2
        self.addr = b2 << 8 | b1
        self.comment = comment

    def __bytes__(self):
        return bytes((self.b1, self.b2))

    def __str__(self):
        return f'        .word ${self.addr:04x}         ' \
                f'; {self.comment:12s}{self.position:04X}: {self.b1:02x} {self.b2:02x}\n'

    def __len__(self):
        return 2

class Header:
    def __init__(self, _bytes:bytes):
        self._bytes = bytes(_bytes)
        self.mapper = (_bytes[6] >> 4) | (_bytes[7] * 0xf0)

    def __str__(self):
        buf = StringIO()
        buf.write(f';  HEADER - MAPPER {self.mapper}\n')
        buf.write('        .db "NES", $1a\n')
        buf.write(f'        .db {self._bytes[ 4]:d}  ; PRG ROM banks\n')
        buf.write(f'        .db {self._bytes[ 5]:d}  ; CHR ROM banks\n')
        buf.write(f'        .db ${self._bytes[ 6]:02x} ; Mapper, mirroring, battery, trainer\n')
        buf.write(f'        .db ${self._bytes[ 7]:02x} ; Mapper, VS/Playchoice, NES 2.0 Header\n')
        buf.write(f'        .db {self._bytes[ 8]:d}  ; PRG-RAM size (rarely used)\n')
        buf.write(f'        .db {self._bytes[ 9]:d}  ; TV system (rarely used)\n')
        buf.write(f'        .db {self._bytes[10]:d}  ; TV system, PRG-RAM presense (unofficial, rarely used)\n')
        buf.write(' ' * 8)
        buf.write(f'.db ' + ', '.join([f'${x:02X}' for x in self._bytes[11:16]]) + ' ; Unused padding')
        buf.seek(0)
        return buf.read()

    def __bytes__(self):
        return self._bytes

def main():
    banks = []
    with open(argv[1], 'rb') as f:
        header = Header(f.read(16))
        for i in range(bytes(header)[4]):
            rom = f.read(16384)
            if i == bytes(header)[4]-1: # is the last bank always base $C000?
                banks.append(Bank(i, 0xc000, rom))
            else:
                banks.append(Bank(i, 0, rom))
        incbin = f.read()
    print(header)
    for b in banks:
        print(b)
    with open('chr_rom.bin', 'wb') as chr_rom:
        chr_rom.write(incbin)
    print('.incbin chr_rom.bin')

if __name__ == '__main__':
    main()


