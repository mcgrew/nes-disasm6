# nes-disasm6

This project is a 6502 disassembler focused on the NES. Generated source code
files will compile with [asm6f](https://github.com/freem/asm6f) which should
produce a file identical to the input file.

## Usage

```text
  usage: disasm.py [-h] [--info] [-s BANK_SIZE] [-b BANK] [-f FIXED_BANKS]
                   [-m MIN_SUB_SIZE] [-v SUB_VALID_END] [-n] [-c] [--stdout]
                   filename

  positional arguments:
    filename              The rom file to disassemble

  optional arguments:
    -h, --help            show this help message and exit
    --info                Print ROM info to stderr - do not disassemble.
    -s BANK_SIZE, --bank-size BANK_SIZE
                          The size of the switchable bank in KB. Should be 8,
                          16, or 32. The default is to auto-detect based on the
                          mapper
    -b BANK, --bank BANK  Only disassemble the specified bank
    -f FIXED_BANKS, --fixed-banks FIXED_BANKS
                          The number of banks which are fixed (non-swappable) at
                          the end of PRG-ROM space. The default is to auto-
                          detect based on the mapper
    -m MIN_SUB_SIZE, --min-sub-size MIN_SUB_SIZE
                          The minimum number of instructions for a valid
                          subroutine. Anything smaller will be converted to a
                          data table. Default is 2.
    -v SUB_VALID_END, --sub-valid-end SUB_VALID_END
                          Adds extra valid endings for a subroutine. Normally
                          'jmp', 'rti', and 'rts' are the only valid endings.
                          Should be a comma-separated list of strings to look
                          for in the final instruction
    -n, --no-sub-check    Do not attempt to analyze subroutines for validity.
                          Some applications may intermix data and code in an odd
                          way and confuse the analysis, resulting in valid code
                          interpreted as data. This output will require much
                          more cleanup
    -c, --no-chr          Do not create chr file
    --stdout              Write all assembly code to stdout. CHR ROM is still
                          saved to disk.
```
