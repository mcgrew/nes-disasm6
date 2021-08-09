#!/usr/bin/env python3
import sys
from enum import Enum
from io import BytesIO
from hashlib import md5

from hashdb import known_md5
from disasm import mappers

class Singleton(type):
    """
    A metaclass used to create a Singleton class
    """
    _instances = {}
    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]

try:
    import usb.core
    import usb.util
except ImportError:
    print("Unable to locate pyusb library")

SET_OPERATION = 0x00
GET_OPERATION = 0x40 

class OpType(Enum):
    IO       = 2
    NES      = 3
    SNES     = 4
    BUFFER   = 5
    USB      = 6
    OPER     = 7
    SWIM     = 8
    JTAG     = 9
    BOOTLOAD = 10
    CICCOM   = 11
    GAMEBOY  = 12
    GBA      = 13
    SEGA     = 14
    N64      = 15
    FWUPDATE = 16
    STUFF    = 17

class IO(Enum):
    def __call__(self, data:int=0):
        return (self.value | (data << 8)) & 0xffff

    IO_RESET     = 0
    NES_INIT     = 1
    SNES_INIT    = 2
    SWIM_INIT    = 3
    JTAG_INIT    = 4
    GAMEBOY_INIT = 5
    GBA_INIT     = 6
    SEGA_INIT    = 7
    N64_INIT     = 8
    GB_POWER_5V  = 9
    GB_POWER_3V  = 10

class NES(Enum):
    def __call__(self, data:int=0):
        return (self.value | (data << 8)) & 0xffff
    # ===================
    #  NES OPCODES
    # ===================
    # 	OPCODES with no operand and no return value besides SUCCESS/ERROR_CODE
    
    # Discrete board PRG-ROM only write, does not write to mapper
    # This is a /WE controlled write with data latched on rising edge EXP0
    # PRG-ROM /WE <- EXP0 w/PU
    # PRG-ROM /OE <- /ROMSEL
    # PRG-ROM /CE <- GND
    # PRG-ROM write: /WE & /CE low, /OE high
    # mapper '161 CLK  <- /ROMSEL
    # mapper '161 /LOAD <- PRG R/W
    # wValueMSB: data
    # wIndex: address
    DISCRETE_EXP0_PRGROM_WR  = 0x00
    NES_PPU_WR               = 0x01

    # generic CPU write with M2 toggle as expected with NES CPU
    #  A15 decoded to enable /ROMSEL as it should
    NES_CPU_WR               = 0x02

    # write to an MMC1 register, provide bank/address & data
    NES_MMC1_WR              = 0x04
    NES_DUALPORT_WR          = 0x05
    DISC_PUSH_EXP0_PRGROM_WR = 0x06


    MMC3_PRG_FLASH_WR        = 0x07 # TODO set return lengths for all these functions
    MMC3_CHR_FLASH_WR        = 0x08
    NROM_PRG_FLASH_WR        = 0x09
    NROM_CHR_FLASH_WR        = 0x0A
    CNROM_CHR_FLASH_WR       = 0x0B # needs cur_bank & bank_table prior to calling
    CDREAM_CHR_FLASH_WR      = 0x0C # needs cur_bank & bank_table prior to calling
    UNROM_PRG_FLASH_WR       = 0x0D # needs cur_bank & bank_table prior to calling
    MMC1_PRG_FLASH_WR        = 0x0E
    MMC1_CHR_FLASH_WR        = 0x0F # needs cur_bank set prior to calling
    MMC4_PRG_SOP_FLASH_WR    = 0x10 # current bank must be selected, & needs cur_bank set prior to calling
    MMC4_CHR_FLASH_WR        = 0x11 # needs cur_bank set prior to calling
    MAP30_PRG_FLASH_WR       = 0x12 # needs cur_bank set prior to calling
    GTROM_PRG_FLASH_WR       = 0x13 # desired bank must be selected
    MMC4_PRG_FLASH_WR        = 0x14 # mapper mod to XOR A14 with A13

    SET_CUR_BANK             = 0x20
    SET_BANK_TABLE           = 0x21
    M2_LOW_WR                = 0x22 # like CPU WR, but M2 stays low

    # write a page worth of random data to ppu
    # make sure the LSFR is initialized first in misc dict
    # send start address in operand, doesn't have to be page boundary
    # but A13 and /A13 get set once based on provided address.
    PPU_PAGE_WR_LFSR         = 0x23

    SET_NUM_PRG_BANKS        = 0x24 # used for determining banktable structure for mapper 11 and such
    M2_HIGH_WR               = 0x25 # like CPU WR, but M2 stays high
    FLASH_3V_WR              = 0x25 # same as above but easier to remember when 
                                    # being used to write to 3v tssop flash
    MMC3S_PRG_FLASH_WR       = 0x26 # TODO set return lengths for all these functions

    # ================================================================
    # OPCODES WITH OPERAND AND RETURN VALUE plus SUCCESS/ERROR_CODE
    # ================================================================

    # read from NES CPU ADDRESS
    # set /ROMSEL, M2, and PRG R/W
    # read from cartridge just as NES's CPU would
    # nice and slow trying to be more like the NES
    EMULATE_NES_CPU_RD       = 0x80 # RL=3

    # like the one above but not so slow..
    NES_CPU_RD               = 0x81 # RL=3
    NES_PPU_RD               = 0x82 # RL=3

    # doesn't have operands just returns sensed CIRAM A10 mirroring 
    # now used to detect old firmware versions so NESmaker folks don't have to update firmware
    CIRAM_A10_MIRROR         = 0x83 # RL=3
    NES_DUALPORT_RD          = 0x84 # RL=3
    GET_CUR_BANK             = 0x85 # RL=3
    GET_BANK_TABLE           = 0x86 # RL=4 16bit value so 2 bytes need returned
    GET_NUM_PRG_BANKS        = 0x87 # RL=3 
    MMC5_PRG_RAM_WR          = 0x88 # RL=3 Enable writting to PRG-RAM and then write a single byte
    # after written read back for verification as a timeout would cause fail

class Buffer(Enum):
    def __call__(self, data:int=0):
        return (self.value | (data << 8)) & 0xffff

    RAW_BUFFER_RESET         = 0x00
    SET_MEM_N_PART           = 0x30
    SET_MULT_N_ADDMULT       = 0x31
    SET_MAP_N_MAPVAR         = 0x32
    SET_FUNCTION             = 0x33

    GET_PRI_ELEMENTS         = 0x50
    GET_SEC_ELEMENTS         = 0x51
    GET_PAGE_NUM             = 0x52
    GET_RAW_BANK_STATUS      = 0x60
    GET_CUR_BUFF_STATUS      = 0x61
    BUFF_PAYLOAD             = 0x70
    BUFF_OUT_PAYLOAD_2B_INSP = 0x71

    BUFF_OPCODE_BUFN_MIN     = 0x80
    BUFF_OPCODE_BUFN_MAX     = 0xFF

    BUFF_OPCODE_BUFN_NRV_MIN = 0x80
    BUFF_OPCODE_BUFN_NRV_MAX = 0xBF

    BUFF_OPCODE_BUFN_RV_MIN  = 0xC0
    BUFF_OPCODE_BUFN_RV_MAX  = 0xEF

    BUFF_OPCODE_PAYLOAD_MIN  = 0xF0
    BUFF_OPCODE_PAYLOAD_MAX  = 0xFF

    ALLOCATE_BUFFER0         = 0x80
    ALLOCATE_BUFFER1         = 0x81
    ALLOCATE_BUFFER2         = 0x82
    ALLOCATE_BUFFER3         = 0x83
    ALLOCATE_BUFFER4         = 0x84
    ALLOCATE_BUFFER5         = 0x85
    ALLOCATE_BUFFER6         = 0x86
    ALLOCATE_BUFFER7         = 0x87

    SET_RELOAD_PAGENUM0      = 0x90
    SET_RELOAD_PAGENUM1      = 0x91
    SET_RELOAD_PAGENUM2      = 0x92
    SET_RELOAD_PAGENUM3      = 0x93
    SET_RELOAD_PAGENUM4      = 0x94
    SET_RELOAD_PAGENUM5      = 0x95
    SET_RELOAD_PAGENUM6      = 0x96
    SET_RELOAD_PAGENUM7      = 0x97

    BUFF_PAYLOAD1            = 0xF1
    BUFF_PAYLOAD2            = 0xF2
    BUFF_PAYLOAD3            = 0xF3
    BUFF_PAYLOAD4            = 0xF4
    BUFF_PAYLOAD5            = 0xF5
    BUFF_PAYLOAD6            = 0xF6
    BUFF_PAYLOAD7            = 0xF7

#  0  : ('NROM', 32, 8, 0x0, 0x0),
#  1  : ('SxROM, MMC1', 16, 4, 0xffff, 0xbfff),
#  2  : ('UxROM', 16, 8, 0xffff, 0x0),
#  3  : ('CNROM', 16),
#  4  : ('TxROM, MMC3, MMC6', 8),
#  5  : ('ExROM, MMC5 (Contains expansion sound)', 8),
#  7  : ('AxROM', 32),
#  9  : ('PxROM, MMC2', 8),
#  10 : ('FxROM, MMC4', 16),
#  11 : ('Color Dreams', 32),
#  13 : ('CPROM', 16),
#  15 : ('100-in-1 Contra Function 16 Multicart', 8),
#  16 : ('Bandai EPROM (24C02)', -1),
#  18 : ('Jaleco SS8806', 8),
#  19 : ('Namco 163', 8),
#  21 : ('VRC4a, VRC4c', 8),
#  22 : ('VRC2a', 8),
#  23 : ('VRC2b, VRC4e', 8),
#  24 : ('VRC6a (Contains expansion sound)', 8),
#  25 : ('VRC4b, VRC4d', 8),
#  26 : ('VRC6b (Contains expansion sound)', 8),
#  34 : ('BNROM, NINA-001', 32),
#  64 : ('RAMBO-1 (MMC3 clone with extra features)', 8),
#  66 : ('GxROM, MxROM', 32),
#  68 : ('After Burner', 16),
#  69 : ('FME-7, Sunsoft 5B', 8),
#  71 : ('Camerica/Codemasters (Similar to UNROM)', 16),
#  73 : ('VRC3', 16),
#  74 : ('Pirate MMC3 derivative', 8),
#  75 : ('VRC1', 8),
#  76 : ('Namco 109 variant', 8),
#  79 : ('NINA-03/NINA-06', 32),
#  85 : ('VRC7', 8),
#  86 : ('JALECO-JF-13', 32),
#  94 : ('Senjou no Ookami', 16),
#  105: ('NES-EVENT (Similar to MMC1)', 16),
#  113: ('NINA-03/NINA-06??', 32),
#  118: ('TxSROM, MMC3', 8),
#  119: ('TQROM, MMC3', 8),
#  159: ('Bandai EPROM', -1),
#  166: ('SUBOR', 8),
#  167: ('SUBOR', 8),
#  180: ('Crazy Climber', 16), #Fixed first bank
#  185: ('CNROM with protection diodes', 16),
#  192: ('Pirate MMC3 derivative', 8),
#  206: ('DxROM, Namco 118 / MIMIC-1', 8),
#  210: ('Namco 175 and 340', 8),
#  228: ('Action 52', 16),
#  232: ('Camerica/Codemasters Quattro', 16),

class Mapper:
    def __init__(self):
        self.number = 0
        self.name = type(self).__name__
        self.bank_size = 32
        self.chr_bank_size = 8
        self.prg_addr = 0
        self.chr_addr = 0
        self._post_init()

    def do(self, *args):
        INLRetro().do(*args)

    def _post_init(self):
        pass

    def set_prg_bank(self, bank):
        pass

    def set_chr_bank(self, bank):
        pass

class NROM(Mapper):
    banks = (32, 8)

class SxROM(Mapper):
    banks = (16, 4)
    def _post_init(self):
        self.number = 1
        self.bank_size = 16
        self.chr_bank_size = 4
        self.prg_addr = 0xffff
        self.chr_addr = 0xbfff
        # initialize the mapper chip
        self.do(OpType.NES, NES.NES_MMC1_WR(0x1c), 0x9fff, 1)

    def set_prg_bank(self, bank):
        sys.stderr.write(f"Swapping in PRG bank {bank}...\n")
        self.do(OpType.NES, NES.NES_MMC1_WR(bank), self.prg_addr, 1)

    def set_chr_bank(self, bank):
        sys.stderr.write(f"Swapping in CHR bank {bank}...\n")
        self.do(OpType.NES, NES.NES_MMC1_WR(bank), self.chr_addr, 1)

class UxROM(Mapper):
    banks = (16, 8)
    def _post_init(self):
        self.number = 2
        self.bank_size = 16
        self.prg_addr = 0xffff

    def set_prg_bank(self, bank):
        sys.stderr.write(f"Swapping in PRG bank {bank}...\n")
        self.do(OpType.NES, NES.NES_CPU_WR(bank), self.prg_addr, 1)

class INLRetro(metaclass=Singleton):
    mappers = {
            0: NROM, 1: SxROM, 2: UxROM, 94: UxROM, 105: SxROM, 180:UxROM,
    }
    def __init__(self, mapper:int=0):
        if mapper not in INLRetro.mappers:
            raise IndexError(f'Mapper {mapper} is not yet supported')
        self.device = usb.core.find(idVendor=0x16c0, idProduct=0x05dc)
        self.mapper = INLRetro.mappers[mapper]()
        self.prg_bank_size, self.chr_bank_size = type(self.mapper).banks

        if self.device is None:
            raise IOError("Unable to locate INLretro device. Be sure it is connected properly.")
        sys.stderr.write("Found INLRetro device.\n")

        self.device.set_configuration()
        self.do(OpType.IO, IO.IO_RESET(0x00), 0x0000, 1)
        self.do(OpType.IO, IO.NES_INIT(), 0x0000, 1)
#          self._mapper_init()
        sys.stderr.write(f'Ready to read {self.mapper.name} board...\n')

    def do(self, select:OpType, op_misc, addr, returnLength):
        response = self.device.ctrl_transfer(
            0xc0, select.value, op_misc, addr, returnLength)[0]
        if response:
            raise IOError(f'INLRetro device responded with error code {response}')

    def get_buffer(self):
        return bytearray(self.device.ctrl_transfer(
            0xc0, OpType.BUFFER.value, Buffer.BUFF_PAYLOAD(), 0x0000, 128))

    def set_prg_bank(self, bank):
        self.mapper.set_prg_bank(bank)

    def set_chr_bank(self, bank):
        self.mapper.set_chr_bank(bank)

    def _init_dump(self, n_part_data_addr, n_mapvar_data_addr):
        self.do(OpType.OPER,   SET_OPERATION, 0x0001, 1)
        self.do(OpType.BUFFER, Buffer.RAW_BUFFER_RESET(), 0x0000, 1)
        self.do(OpType.BUFFER, Buffer.ALLOCATE_BUFFER0(4), 0x0000, 1)
        self.do(OpType.BUFFER, Buffer.ALLOCATE_BUFFER1(4), 0x8004, 1)
        self.do(OpType.BUFFER, Buffer.SET_RELOAD_PAGENUM0(1), 0x0000, 1)
        self.do(OpType.BUFFER, Buffer.SET_RELOAD_PAGENUM1(1), 0x0000, 1)
        self.do(OpType.BUFFER, Buffer.SET_MEM_N_PART(0), n_part_data_addr, 1)
        self.do(OpType.BUFFER, Buffer.SET_MEM_N_PART(1), n_part_data_addr, 1)
        self.do(OpType.BUFFER, Buffer.SET_MAP_N_MAPVAR(0), n_mapvar_data_addr, 1)
        self.do(OpType.BUFFER, Buffer.SET_MAP_N_MAPVAR(1), n_mapvar_data_addr, 1)
        self.do(OpType.OPER,   SET_OPERATION, 0x00d2, 1)

    def _init_chr_dump(self):
        self._init_dump(0x21dd, 0x0000)

    def _init_prg_dump(self):
        self._init_dump(0x20dd, 0x0800)

    def _dump(self, io, size):
        for i in range(size * 8):
            self.do(OpType.BUFFER,  0x0061, 0x0000, 3)
            io.write(self.get_buffer())

    def dump_prg_bank(self, io, bank, prg_size):
        self.set_prg_bank(i)
        self._init_prg_dump()
        self._dump(io, self.prg_bank_size)

    def dump_chr_bank(self, io, bank, chr_size):
        self.set_chr_bank(i)
        self._init_chr_dump()
        self._dump(io, self.chr_bank_size)

    def dump_full(self, io, prg_size, chr_size):
        sys.stderr.write("Dumping PRG ROM...\n")
        for i in range(prg_size // self.prg_bank_size):
            self.set_prg_bank(i)
            self._init_prg_dump()
            self._dump(io, self.prg_bank_size)
        sys.stderr.write("Dumping CHR ROM...\n")
        for i in range(chr_size // self.chr_bank_size):
            self.set_chr_bank(i)
            self._init_chr_dump()
            self._dump(io, self.chr_bank_size)

    def dump_and_verify(self, io, prg_size, chr_size):
        self.dump_full(io, prg_size, chr_size)
        digest = get_hash(io)
        sys.stderr.write(f'Hash: {digest}\n')
        if digest in known_md5:
            sys.stderr.write("Matched known hash.\n")
        else:
            sys.stderr.write("Did not match a known hash, rereading...\n")
            last_digest = digest
            buf = BytesIO()
            self.dump_full(buf, prg_size, chr_size)
            digest = get_hash(buf)
            sys.stderr.write(f'Hash: {digest}\n')
            if digest == last_digest:
                sys.stderr.write("Hash matches previous read but not a known hash.\n")
                sys.stderr.write("This likely indicates the cartridge is not "
                    "seated properly.\n")
                return 1
            else:
                sys.stderr.write("Second read did not match the first!\n")
                sys.stderr.write("Please make sure the cartridge is seated "
                    "properly and try again.\n")
                return -1
        return 0

def get_hash(buf):
    buf.seek(0)
    _hash = md5()
    _hash.update(buf.read())
    return _hash.hexdigest()

def main():
    MAPPER = int(sys.argv[1])
    PRG_SIZE = int(sys.argv[2])
    CHR_SIZE = int(sys.argv[3])

#      MAPPER = 2
#      PRG_SIZE = 128
#      CHR_SIZE = 0
#  
#      MAPPER = 1
#      PRG_SIZE = 64
#      CHR_SIZE = 16 

#      MAPPER = 0
#      PRG_SIZE = 32
#      CHR_SIZE = 8

    inlretro = INLRetro(MAPPER)
    buf = BytesIO()

    fail = inlretro.dump_and_verify(buf, PRG_SIZE, CHR_SIZE)
    if fail < 0:
        return
    elif fail > 0:
        sys.stderr.write("Proceed anyway? (y/n) ")
        answer = input()
        if not answer.lower().startswith('y'):
            return

    header = bytearray(b'NES\x1a\x00\x00\x00\0\0\0\0\0\0\0\0\0')
    header[4] = PRG_SIZE // 16
    header[5] = CHR_SIZE // 8
    header[6] |= (MAPPER & 0xf) << 4
    header[7] |= (MAPPER & 0xf0)

    with open('dump.nes', 'wb') as f:
        f.write(header)
        buf.seek(0)
        f.write(buf.read())
#  
if __name__ == '__main__':
    main()

