#!/usr/bin/env python3

from enum import Enum
from collections import OrderedDict
from sys import stdout, stderr, exit
from io import StringIO
from os import urandom
import os.path
from base64 import b32encode
from argparse import ArgumentParser
from typing import Any

mmio = {
    0x2000 : 'PPUCTRL',
    0x2001 : 'PPUMASK',
    0x2002 : 'PPUSTATUS',
    0x2003 : 'OAMADDR',
    0x2004 : 'OAMDATA',
    0x2005 : 'PPUSCROLL',
    0x2006 : 'PPUADDR',
    0x2007 : 'PPUDATA',
    0x4000 : 'SQ1_VOL',
    0x4001 : 'SQ1_SWEEP',
    0x4002 : 'SQ1_LO',
    0x4003 : 'SQ1_HI',
    0x4004 : 'SQ2_VOL',
    0x4005 : 'SQ2_SWEEP',
    0x4006 : 'SQ2_LO',
    0x4007 : 'SQ2_HI',
    0x4008 : 'TRI_LINEAR',
    0x400A : 'TRI_LO',
    0x400B : 'TRI_HI',
    0x400C : 'NOISE_VOL',
    0x400E : 'NOISE_LO',
    0x400F : 'NOISE_HI',
    0x4010 : 'DMC_FREQ',
    0x4011 : 'DMC_RAW',
    0x4012 : 'DMC_START',
    0x4013 : 'DMC_LEN',
    0x4014 : 'OAMDMA',
    0x4015 : 'SND_CHN',
    0x4016 : 'JOY1',
    0x4017 : 'JOY2',
}

mappers = {
        # Name, Bank Size, Fixed bank count (at end)
    0  : ('NROM',32, 1),
    1  : ('SxROM, MMC1', 16, 1), # Technically 0, but most configurations use 1
    2  : ('UxROM', 16, 1),
    3  : ('CNROM', 32, 1),
    4  : ('TxROM, MMC3, MMC6', 8, 2),
    5  : ('ExROM, MMC5 (Contains expansion sound)', 8, 0),
    7  : ('AxROM', 32, 0),
    9  : ('PxROM, MMC2', 8, 3),
    10 : ('FxROM, MMC4', 16, 1),
    11 : ('Color Dreams', 32, 0),
    13 : ('CPROM', 32, 1),
    15 : ('100-in-1 Contra Function 16 Multicart', 8, 0),
    16 : ('Bandai EPROM (24C02)', -1, 0), # Too many submappers
    18 : ('Jaleco SS8806', 8, 1),
    19 : ('Namco 163 (Contains expansion sound)', 8, 1),
    21 : ('VRC4a, VRC4c', 8, 2),
    22 : ('VRC2a', 8, 2),
    23 : ('VRC2b, VRC4e', 8, 2),
    24 : ('VRC6a (Contains expansion sound)', 8, 1),
    25 : ('VRC4b, VRC4d', 8, 2),
    26 : ('VRC6b (Contains expansion sound)', 8, 1),
    34 : ('BNROM, NINA-001', 32, 0),
    64 : ('RAMBO-1 (MMC3 clone with extra features)', 8, 1),
    66 : ('GxROM, MxROM', 32, 0),
    68 : ('After Burner', 16, 1),
    69 : ('FME-7, Sunsoft 5B', 8, 1),
    71 : ('Camerica/Codemasters (Similar to UNROM)', 16, 1),
    73 : ('VRC3', 16, 1),
    74 : ('Pirate MMC3 derivative', 8, 2),
    75 : ('VRC1', 8, 1),
    76 : ('Namco 109 variant', 8, 2),
    79 : ('NINA-03/NINA-06', 32, 0),
    85 : ('VRC7', 8, 1),
    86 : ('JALECO-JF-13', 32, 0),
    94 : ('Senjou no Ookami', 16, 1),
    105: ('NES-EVENT (Similar to MMC1)', 16, 0),
    113: ('NINA-03/NINA-06?? (For multicarts including mapper 79 games.)', 32, 0),
    118: ('TxSROM, MMC3 (MMC3 with independent mirroring control)', 8, 2),
    119: ('TQROM, MMC3 (Has both CHR ROM and CHR RAM)', 8, 2),
    159: ('Bandai EPROM (24C01)', -1, -1),
    166: ('SUBOR', 8, 0),
    167: ('SUBOR', 8, 0),
    180: ('Crazy Climber', 16, 1), #Fixed first bank
    185: ('CNROM with protection diodes', 32, 1),
    192: ('Pirate MMC3 derivative', 8, 2),
    206: ('DxROM, Namco 118 / MIMIC-1', 8, 2),
    210: ('Namco 175 and 340 (Namco 163 with different mirroring)', 8, 1),
    228: ('Action 52', 16, 0),
    232: ('Camerica/Codemasters Quattro (Multicarts)', 16, 0),
}

def parse_args():
    parser = ArgumentParser()
    parser.add_argument('filename', help='The rom file to disassemble')
    parser.add_argument('-b', '--bank-size', type=int, default=-1,
            help='The size of the switchable bank in KB. Should be 8, 16, or 32. '
            'The default is to auto-detect based on the mapper')
    parser.add_argument('-f', '--fixed-banks', type=int, default=-1,
            help='The number of banks which are fixed (non-swappable) at the end '
            'of PRG-ROM space. The default is to auto-detect based on the mapper')
    parser.add_argument('-m', '--min-sub-size', type=int, default=2,
            help='The minimum number of instructions for a valid subroutine. '
            'Anything smaller will be converted to a data table. Default is 2.')
    parser.add_argument('-s', '--no-sub-check', action='store_true',
         help='Do not attempt to analyze subroutines for validity. Some '
         'applications may intermix data and code in an odd way and confuse the '
         'analysis, resulting in valid code interpreted as data. This output will '
         'require much more cleanup')
    parser.add_argument('-c', '--no-chr', action='store_true', help="Do not create chr file")
    parser.add_argument('--stdout', action='store_true',
            help='Write all assembly code to stdout. CHR ROM is still saved to disk.')
    return parser.parse_args()

class OpType(Enum):
    IMPLIED, IMMMEDIATE, ACCUMULATOR, BRANCH, ZEROPAGE, ABSOLUTE, INDIRECT = range(7)

class Indexing(Enum):
    NONE, X, Y = ('', 'x', 'y')

    def __str__(self):
        return self.value

class Bank:
    """
    A ROM bank.
    """
    def __init__(self, number:int, base:int, _bytes:bytes, fixed:int=0):
        """
        Creates a new bank.

        :param number: The bank number for this bank
        :param base: The base, if known. 0 if unknown, and will attempt to be
            determined automatically.
        :param _bytes: The bytes for this bank to be parsed.
        """
        if base < 0:
            raise ValueError("Bank address cannot be negative.")
        self._bytes = bytes(_bytes)
        self.base = base if base else 0x8000
        self.number = number
        self.components = []
        self._fixed = fixed
        self._disassemble(_bytes[:-6], _bytes[-6:])
        i = 0
        if not base:
            old_base = self.base
            new_base = self.find_base()
            # use the jump addresses to guess the base address of this bank
            if new_base != old_base:
                # it changed, so redo the disassembly
                self.base = new_base
                self._disassemble(_bytes[:-6], _bytes[-6:])
        # generate any necessary labels
        str(self)

    def _disassemble(self, bank_bytes:bytes, interrupts:bytes=bytes()):
        self.components.clear()
        last_instr = i = 0
        while i < len(bank_bytes):
            instr = Instruction(i + self.base, self, bank_bytes[i:i+3])
            if instr:
                if not len(self.components) or type(self.components[-1]) is not Subroutine \
                        or self.components[-1].is_complete():
                    self.components.append(Subroutine(self, instr.position))
                self.components[-1].append(instr)
                i += len(instr)
            else:
                if len(self.components) and type(self.components[-1]) is Subroutine:
                    self._merge_tables()
                if not len(self.components) or type(self.components[-1]) is not Table:
                    self.components.append(Table(i + self.base, self))
                self.components[-1].append(bank_bytes[i])
                i += 1
        if len(interrupts):
            # no need to prefix the labels if there are fixed banks
            prefix = f'b{self.number}_' if not self._fixed else ''
            nmi = Word(len(self) - 6, self, *interrupts[:2], f'{prefix}NMI')
            reset = Word(len(self) - 4, self, *interrupts[2:4], f'{prefix}RESET')
            irq = Word(len(self) - 2, self, *interrupts[4:], f'{prefix}IRQ')
            if self.base == 0x10000 - len(self): # and self._valid_interrupts(nmi, reset, irq):
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

    def _merge_tables(self):
        if len(self.components):
            c = self.components[-1]
            if not c.is_valid():
                self.components[-1] = Table(c.position, self, c)
                while len(self.components) > 1 and type(self.components[-2]) is Table:
                    self.components[-2].extend(self.components[-1])
                    self.components = self.components[:-1]

    def find_component(self, addr:int) -> Any:
        """
        Finds the component at the specified address

        :param addr: The address of the component.

        :return: The requested component, or None if no instruction exists at
            that address.
        """
        for c in self.components:
            if addr >= c.position and addr < c.position + len(c):
                return c
        return None


    def find_label(self, addr:int) -> str:
        """
        Finds the component at the specified address and returns its label. If
        no such component exists, the hex address is returned.

        :param position: The address of the component.

        :return: The requested label, or a hex address if no component exists at
            that address.
        """
        c = self.find_component(addr)
        if c:
            return f'{c.get_label(addr)}'
        return f'${addr:04x}'

    def find_base(self):
        """
        Attempts to find the base address based on jump addresses in this bank.
        """
        bases = list(range(0x8000, 0x10001 - len(self) * self._fixed, len(self)))
        if type(self.components[-1]) is not Word:
            bases = bases[:-1] # no interrupt vectors, can't be the last bank
        bins = [0] * (len(bases) - 1)
        for c in self.components:
            if type(c) is Subroutine:
                for i in c.instructions:
                    if i.op in ('jmp', 'jsr') and i.type == OpType.ABSOLUTE:
                        b1, b2, _ = bytes(i)
                        jpoint = b2 << 8 | b1
                        for i in range(len(bins)):
                            if jpoint > bases[i] and jpoint < bases[i+1]:
                                bins[i] += 1
        base = 0
        for i,b in enumerate(bins):
            if bases[base] < bases[i]:
                base = i
        return bases[base]

    def __len__(self):
        return len(self._bytes)

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
    """
    A single assembly instruction.
    """
    def __init__(self, position:int, bank:Bank, _bytes:bytes):
        """
        Creates a new Instruction.

        :param position: The address of this instruction.
        :param bank: The bank which contains this instruction.
        :param _bytes: The bytes which make up this instruction. Any extra bytes
            will be discarded.
        """
        self.position = position
        self.opcode = _bytes[0]
        self.bank = bank
        self._bytes = bytes(_bytes)
        b1 = _bytes[1] if len(_bytes) > 1 else None
        b2 = _bytes[2] if len(_bytes) > 2 else None
        self._size = 0
        self.label = ''

        self.op = ''
        self.comment = ''
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

        elif b2 is not None and self.absolute(self.opcode):
            self.type = OpType.ABSOLUTE
            self._size = 3

        self._bytes = self._bytes[:self._size]

    def implied(self, opcode):
        """
        Determines if this is an implied instruction. Sets the operation name if
        so.

        :param opcode: The opcode for the instruction.

        :return: True if this opcode is for an implied instruction.
        """
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
        """
        Determines if this is a zero page instruction. Sets the operation name if
        so.

        :param opcode: The opcode for the instruction.

        :return: True if this opcode is for a zero page instruction.
        """
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
        """
        Determines if this is an absolute instruction. Sets the operation name if
        so.

        :param opcode: The opcode for the instruction.

        :return: True if this opcode is for an absolute instruction.
        """
        if opcode in (0x9c, 0x9e):
            return False
        if self._bytes[2] >= 0x60: # don't interpret jumps below 0x6000 (SRAM)
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
        """
        Determines if this is a branch instruction. Sets the operation name if
        so.

        :param opcode: The opcode for the instruction.

        :return: True if this opcode is for a branch  instruction.
        """
        if opcode & 0x1f == 0x10:
            self.op = ('bpl', 'bmi', 'bvc', 'bvs', 'bcc', 'bcs', 'bne', 'beq')[opcode >> 5]
            return True
        return False

    def accumulator(self, opcode):
        """
        Determines if this is an accumulator instruction. Sets the operation name if
        so.

        :param opcode: The opcode for the instruction.

        :return: True if this opcode is for an accumulator instruction.
        """
        if opcode & 0x9f == 0x0a:
            self.op = ('asl', 'rol', 'lsr', 'ror')[opcode >> 5]
            return True
        return False

    def immediate(self, opcode):
        """
        Determines if this is an immediate instruction. Sets the operation name if
        so.

        :param opcode: The opcode for the instruction.

        :return: True if this opcode is for an immediate instruction.
        """
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
        """
        Determines if this is an indirect instruction. Sets the operation name if
        so.

        :param opcode: The opcode for the instruction.

        :return: True if this opcode is for an indirect  instruction.
        """
        if opcode & 0xf == 1:
            self.op = ('ora', 'and', 'eor', 'adc', 'sta', 'lda', 'cmp', 'sbc')[opcode >> 5]
            self.indexing = Indexing.Y if (opcode >> 4) & 1 else Indexing.X
            return True
        return False

    def get_label(self, addr):
        """
        Creates a label for this instruction if one does not exist and returns
        it.

        :return: The instruction label
        """
        self.label = f'b{self.bank.number}_{self.position:04x}'
        offset = ''
        if addr != self.position:
            offset = f'+{addr - self.position}'
        return f'{self.label}{offset}'

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
        if self.comment:
            buf.write(' ' * 10)
            buf.write(f'; {self.comment}\n')
        line_len = buf.tell()
        if self.label:
            buf.write(f'{self.label}:'.ljust(12))
        else:
            buf.write(' ' * 12)

        if self.type == OpType.IMPLIED:
            buf.write(self.op)

        if self.type == OpType.ACCUMULATOR:
            buf.write(f'{self.op} a')

        if self.type == OpType.IMMMEDIATE:
                buf.write(f'{self.op} #${b1:02x}')
        if self.type == OpType.BRANCH:
            dest = self.position + 2 + (b1 if b1 < 128 else b1 - 256)
            buf.write(f'{self.op} {self.bank.find_label(dest)}')

        if self.type == OpType.ZEROPAGE:
            if self.indexing == Indexing.NONE:
                buf.write(f'{self.op} ${b1:02x}')
            else:
                buf.write(f'{self.op} ${b1:02x},{self.indexing}')
        if self.type == OpType.ABSOLUTE:
            addr = (b2 << 8) | b1
#             if self.op in ('jmp','jsr') and self.dest:
#                 buf.write(f'{self.op} {self.dest}')
#             else:
            if not b2:
                buf.seek(buf.tell() - 2)
                buf.write('; ')
            label = self.bank.find_label(addr)
            if addr in mmio:
                buf.write(f'{self.op} {mmio[addr]}')
            else:
                buf.write(f'{self.op} {label}')
            if self.indexing != Indexing.NONE:
                buf.write(f',{self.indexing}')
            if not b2: 
                buf.write('     ; avoid optimization\n')
                line_len = buf.tell()
                buf.write(' ' * 12)
                buf.write(f'hex {self.opcode:02x} {b1:02x} {b2:02x}')

        if self.type == OpType.INDIRECT:
            if self.op == 'jmp':
                buf.write(f'{self.op} (${b2:02x}{b1:02x})')
            elif self.indexing == Indexing.NONE:
                buf.write(f'{self.op} ${b1:02x}')
            elif self.indexing == Indexing.X:
                buf.write(f'{self.op} (${b1:02x},x)')
            elif self.indexing == Indexing.Y:
                buf.write(f'{self.op} (${b1:02x}),y')

        source_pos = self.position % len(self.bank)
        source_pos += len(self.bank) * self.bank.number
        buf.write(' ' * (40 + line_len - buf.tell()))
        buf.write(f'; {source_pos:05X}:  ')
        buf.write(' '.join([f'{x:02x}' for x in self._bytes]))
        buf.write('\n')

        buf.seek(0)
        return buf.read()

    def __add__(self, instr):
        s = Subroutine(self.bank, self.position)
        s.append(self)
        s.append(instr)
        return s

class Subroutine:
    """
    An assembly subroutine.
    """
    always_valid:bool = False
    min_size:int = 2
    def __init__(self, bank:Bank, position:int):
        if position < 0:
            raise ValueError("Subroutine address cannot be negative.")
        self.position = position
        self.instructions = []
        self.bank = bank

    def is_complete(self):
        """
        Determines whether this subroutine is complete. Generally this means the
        subroutine ends with either a 'jmp' or 'rts' instruction to avoid
        executing invalid code.
        """
        return self.instructions[-1].op in ('rts', 'jmp')

    def is_valid(self):
        """
        Determines whether this subroutine is valid. Generally this means the
        subroutine ends with either a 'jmp' or 'rts' instruction to avoid
        executing invalid code. The behavior of this method can be influenced by
        command line flags
        """
        return len(self.instructions) >= Subroutine.min_size and \
            (Subroutine.always_valid or self.instructions[-1].op in ('rts', 'jmp'))

    def append(self, instruction:Instruction):
        """
        Appends an instruction to this Subroutine

        :param instruction: The instruction to append.
        """
        self.instructions.append(instruction)

    def get_label(self, addr):
        for i in self.instructions:
            if addr >= i.position and addr < i.position + len(i):
                return i.get_label(addr)

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
        buf.write('\n')
        buf.seek(0)
        return buf.read()

class Table:
    """
    A table of bytes containing data.
    """
    def __init__(self, position:int, bank:Bank, _bytes:bytes=bytes()):
        self._bytes = bytes(_bytes)
        self.position = position
        self.bank = bank
        self.label = ''

    def append(self, byte:int):
        """
        Appenda a single byte to this table.

        :param byte: The byte to append
        """
        self._bytes += bytes((byte,))

    def extend(self, _bytes):
        """
        Appends several bytes to this table. This can be any type which supports
        the __bytes__ method.
        """
        self._bytes += bytes(_bytes)

    def get_label(self, addr):
        """
        Gets the label for this table if one does not exist and returns it.

        :return: The instruction label
        """
        self.label = f'tab_b{self.bank.number}_{self.position:04x}'
        offset = ''
        if addr != self.position:
            offset = f'+{addr - self.position}'
        return f'{self.label}{offset}'

    def __bytes__(self):
        return self._bytes

    def __str__(self):
        buf = StringIO()
        source_pos = self.position % len(self.bank)
        source_pos += len(self.bank) * self.bank.number
        if self.label:
            buf.write(f'{self.label}: ')
            buf.write(f'; {len(self)} bytes\n')
        last_line = buf.tell()
        for i in range(0, len(self._bytes), 16):
            buf.write(' ' * 12)
            buf.write(f'hex {" ".join([f"{x:02x}" for x in self._bytes[i:i+16]])}')
            buf.write(' ' * (64 + last_line - buf.tell()))
            buf.write(f'  ; {source_pos + i:05X}\n')
            last_line = buf.tell()
        buf.write('\n')
        buf.seek(0)
        return buf.read()

    def __len__(self):
        return len(self._bytes)

class Word:
    """
    An assembly  WORD. This is only used for NMI, RESET, and IRQ vectors in the
    disassembler.
    """
    def __init__(self, position, bank, b1, b2, label='', comment=''):
        self.position = position
        self.bank = bank
        self.b1 = b1
        self.b2 = b2
        self.addr = b2 << 8 | b1
        self.comment = comment
        self.label = label 

    def get_label(self, addr):
        """
        Creates a label for this word if one does not exist and returns
        it.

        :return: The instruction label
        """
        if label:
            offset = ''
            if addr != self.position:
                offset = f'+{addr - self.position}'
            return f'{self.label}{offset}'
        return f'${addr:04x}'


    def __bytes__(self):
        return bytes((self.b1, self.b2))

    def __str__(self):
        source_pos = self.position % len(self.bank)
        source_pos += len(self.bank) * self.bank.number
        buf = StringIO()
        if self.label:
            buf.write(f'{self.label}:'.ljust(12))
        else:
            buf.write(' ' * 12)
        buf.write(f'word {self.bank.find_label(self.addr)}'.ljust(28))
        buf.write(f'; {source_pos:05X}: {self.b1:02x} {self.b2:02x}     {self.comment}\n')
        buf.seek(0)
        return buf.read()

    def __len__(self):
        return 2

class Header:
    """
    The ROM header
    """
    def __init__(self, _bytes:bytes):
        self._bytes = bytes(_bytes)
        self.prg_size = _bytes[4] * 16 * 1024
        self.chr_size = _bytes[5] *  8 * 1024
        self.mapper = (_bytes[6] >> 4) | (_bytes[7] & 0xf0)

    def __str__(self):
        buf = StringIO()
        if self.mapper in mappers:
            buf.write(f';  HEADER - MAPPER {self.mapper} - {mappers[self.mapper][0]}\n')
        else:
            buf.write(f';  HEADER - MAPPER {self.mapper}\n')
        buf.write( '        .db "NES", $1a\n')
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

def write_base_asm(header, out=stdout):
    out.write(f'{header}\n\n')
    out.write(';  MMIO\n')
    for addr,item in mmio.items():
        out.write(f'        {item:10s} EQU ${addr:04x}\n')
    out.write('\n')


def main():
    args = parse_args()
    if args.no_sub_check:
        Subroutine.always_valid = True
    Subroutine.min_size = args.min_sub_size
    banks = []
    bank_size = args.bank_size
    fixed_banks = args.fixed_banks
    with open(args.filename, 'rb') as f:
        header = Header(f.read(16))
        if bank_size < 0:
            if header.mapper in mappers:
                bank_size = mappers[header.mapper][1] * 1024
                stderr.write(f'ROM uses mapper {header.mapper} '
                    f'- {mappers[header.mapper][0]}\n')
        if bank_size < 0:
            stderr.write(f'Unknown mapper {header.mapper}, please specify bank size.\n')
            exit(-1)
        stderr.write(f'Using bank size of {bank_size//1024}K\n')
        if fixed_banks < 0:
            if header.mapper in mappers:
                fixed_banks = mappers[header.mapper][2]
            else:
                fixed_banks = 0
        bank_count = header.prg_size // bank_size
        stderr.write(f'ROM has {bank_count} banks.\n')
        stderr.write(f'Mapper uses {fixed_banks} fixed banks.\n')
        fixed_bank_start = bank_count - fixed_banks

        for i in range(bank_count):
            rom = f.read(bank_size)
            base = 0
            if bank_size == 0x8000: # 32K banks can only be loaded at 0x8000
                base = 0x8000
            elif i >= fixed_bank_start:
                base = 0x10000 - (bank_size * (bank_count - i))
            banks.append(Bank(i, base, rom, fixed_banks))
        incbin = f.read()
    main_asm = stdout
    if not args.stdout:
        asmfile = f'{os.path.splitext(os.path.basename(args.filename))[0]}.asm'
        main_asm = open(asmfile, 'w')
    write_base_asm(header, main_asm)

    if args.stdout:
        for b in banks:
            stdout.write(str(b))
            stdout.write('\n\n')
    else:
        for b in banks:
            with open(f'bank_{b.number:02d}.asm', 'w') as asm:
                asm.write(str(b))
                main_asm.write(f'        .include bank_{b.number:02d}.asm\n')
    if not args.no_chr:
        with open('chr_rom.bin', 'wb') as chr_rom:
            chr_rom.write(incbin)
        main_asm.write('        .incbin chr_rom.bin\n')
    if not args.stdout:
        main_asm.close()

if __name__ == '__main__':
    main()


