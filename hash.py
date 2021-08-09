#!/usr/bin/env python 
import sys
from hashlib import md5

m = md5()
sys.stdin.buffer.read(16)
m.update(sys.stdin.buffer.read())
print(f"'{m.hexdigest()}',")
