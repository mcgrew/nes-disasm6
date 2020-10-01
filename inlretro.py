#!/usr/bin/env python3
import sys
from enum import Enum
from io import BytesIO
from hashlib import md5

from hashdb import known_md5

try:
    import usb.core
    import usb.util
except ImportError:
    print("Unable to locate pyusb library")

class OpSelect(Enum):
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
    def data(self, data:int=0):
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
    def data(self, data:int=0):
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
    def data(self, data:int=0):
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

class INLRetro:
    def __init__(self):
        self.device = usb.core.find(idVendor=0x16c0, idProduct=0x05dc)

        if self.device is None:
            raise IOError("Unable to locate INLretro device. Be sure it is connected properly.")
        sys.stderr.write("Found INLRetro device.\n")

        self.device.set_configuration()
        self.do(OpSelect.IO, IO.IO_RESET.data(0x00), 0x0000, 1)
        self.do(OpSelect.IO, IO.NES_INIT.value, 0x0000, 1)
#          self.do(OpSelect.IO, IO.IO_RESET.data(0x00), 0x0000, 1)
#          self.do(OpSelect.IO, IO.NES_INIT.value, 0x0000, 1)

    def do(self, select:OpSelect, op_misc, addr, returnLength):
        response = self.device.ctrl_transfer(
            0xc0, select.value, op_misc, addr, returnLength)[0]
        if response:
            raise IOError(f'INLRetro device responded with error code {response}')

    def get_buffer(self):
        return bytearray(self.device.ctrl_transfer(
            0xc0, OpSelect.BUFFER.value, Buffer.BUFF_PAYLOAD.value, 0x0000, 128))

    def set_bank(self):
        self.do(OpSelect.NES,    0x0081, 0x8000, 3)
        self.do(OpSelect.NES,    0x8002, 0x8000, 1)
        self.do(OpSelect.NES,    0x1004, 0x8000, 1)
        self.do(OpSelect.NES,    0x1004, 0xe000, 1)
        self.do(OpSelect.NES,    0x1204, 0xa000, 1)
        self.do(OpSelect.NES,    0x1504, 0xc000, 1)
        self.do(OpSelect.NES,    0x0004, 0xe000, 1)

    def init_chr_dump(self):
        sys.stderr.write("Dumping CHR ROM...\n")
        self.do(OpSelect.OPER,   0x0000, 0x0001, 1)
        self.do(OpSelect.BUFFER, 0x0000, 0x0000, 1)
        self.do(OpSelect.BUFFER, 0x0480, 0x0000, 1)
        self.do(OpSelect.BUFFER, 0x0481, 0x8004, 1)
        self.do(OpSelect.BUFFER, 0x0190, 0x0000, 1)
        self.do(OpSelect.BUFFER, 0x0191, 0x0000, 1)
        self.do(OpSelect.BUFFER, 0x0030, 0x21dd, 1)
        self.do(OpSelect.BUFFER, 0x0130, 0x21dd, 1)
        self.do(OpSelect.BUFFER, 0x0032, 0x0000, 1)
        self.do(OpSelect.BUFFER, 0x0132, 0x0000, 1)
        self.do(OpSelect.OPER,   0x0000, 0x00d2, 1)

    def init_prg_dump(self):
        sys.stderr.write("Dumping PRG ROM...\n")
        self.do(OpSelect.OPER,   0x0000, 0x0001, 1)
        self.do(OpSelect.BUFFER, 0x0000, 0x0000, 1)
        self.do(OpSelect.BUFFER, 0x0480, 0x0000, 1)
        self.do(OpSelect.BUFFER, 0x0481, 0x8004, 1)
        self.do(OpSelect.BUFFER, 0x0190, 0x0000, 1)
        self.do(OpSelect.BUFFER, 0x0191, 0x0000, 1)
        self.do(OpSelect.BUFFER, 0x0030, 0x20dd, 1)
        self.do(OpSelect.BUFFER, 0x0130, 0x20dd, 1)
        self.do(OpSelect.BUFFER, 0x0032, 0x0800, 1)
        self.do(OpSelect.BUFFER, 0x0132, 0x0800, 1)
        self.do(OpSelect.OPER,   0x0000, 0x00d2, 1)

    def dump(self, io, size):
        for i in range(size//128):
            self.do(OpSelect.BUFFER,  0x0061, 0x0000, 3)
            io.write(self.get_buffer())

    def dump_full(self, io, prg_size, chr_size):
        self.init_prg_dump()
        self.dump(io, prg_size)
        self.init_chr_dump()
        self.dump(io, chr_size)

def hash_buf(buf):
    buf.seek(0)
    _hash = md5()
    _hash.update(buf.read())
    return _hash.hexdigest()

def main():
    i = INLRetro()
    buf = BytesIO()

    i.dump_full(buf, 32768, 8192)
    digest = hash_buf(buf)
    if digest in known_md5:
        print("Matched known hash.")
    else:
        print("Did not match a known hash, rereading...")
        last_digest = digest
        buf = BytesIO()
        i.dump_full(buf, 32768, 8192)
        digest = hash_buf(buf)
        if digest == last_digest:
            print("Hash matches previous read but not a known hash.")
            print("This likely indicates the cartridge is not seated properly.")
            answer = input("Proceed anyway? (y/n)")
            if answer[0].lower() != 'y':
                return
        else:
            print("Second read did not match the first!")
            print("Please make sure the cartridge is seated properly and try again.")
            return

    print(digest)

if __name__ == '__main__':
    main()

