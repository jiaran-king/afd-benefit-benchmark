"""Read libc's current environment without attaching, pausing or executing in a worker."""
import ctypes
import os
from pathlib import Path
import struct


def mappings(pid):
    for line in Path(f'/proc/{pid}/maps').read_text().splitlines():
        fields = line.split(maxsplit=5)
        if len(fields) == 6 and fields[5].startswith('/'):
            low, high = (int(v, 16) for v in fields[0].split('-'))
            yield low, high, int(fields[2], 16), fields[5], fields[3], fields[4]


def read_environment(pid):
    pointer = ctypes.c_void_p.in_dll(ctypes.CDLL(None), 'environ')
    symbol = ctypes.addressof(pointer)
    own = next(v for v in mappings(os.getpid()) if v[0] <= symbol < v[1])
    own_base = next(v for v in mappings(os.getpid()) if v[3:] == own[3:] and v[2] == 0)
    symbol_offset = symbol - own_base[0]
    target = next(v for v in mappings(pid) if v[3:] == own[3:] and v[2] == 0)
    address = target[0] + symbol_offset
    size = ctypes.sizeof(ctypes.c_void_p)
    fmt = '<Q' if size == 8 else '<I'
    fd = os.open(f'/proc/{pid}/mem', os.O_RDONLY)
    try:
        def pointer_at(where):
            return struct.unpack(fmt, os.pread(fd, size, where))[0]
        vector = pointer_at(address)
        result = {}
        for i in range(8192):
            value = pointer_at(vector + i * size)
            if not value:
                break
            raw = bytearray()
            for offset in range(0, 1048576, 256):
                block = os.pread(fd, 256, value + offset)
                if not block:
                    raise RuntimeError('Unterminated environment string')
                raw.extend(block.split(b'\0', 1)[0])
                if b'\0' in block:
                    break
            else:
                raise RuntimeError('Environment string exceeded read limit')
            text = raw.decode(errors='replace')
            if '=' in text:
                key, val = text.split('=', 1)
                result[key] = val
        else:
            raise RuntimeError('Environment vector exceeded read limit')
        assert pointer_at(address) == vector, 'Environment changed while reading; preserve and retry read only'
        return result
    finally:
        os.close(fd)
