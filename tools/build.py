"""Build the playable Rap Basketball ROM + IPS patch from src/patch.asm.

usage: python tools/build.py "Rap Basketball (USA) (Proto).sfc" [-o out.sfc] [--ips out.ips]
"""
import argparse, os, sys, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from asm65816 import Asm, apply, lorom_off

EXPECTED_CRC = 0x3F0343A7  # Rap Basketball (USA) (Proto).sfc, 1 MiB, unheadered


def make_ips(orig, new):
    out = bytearray(b'PATCH')
    i = 0
    while i < len(orig):
        if orig[i] == new[i]:
            i += 1
            continue
        j = i
        while j < len(orig) and j - i < 0xFFFF and (orig[j] != new[j] or (j + 1 < len(orig) and orig[j + 1] != new[j + 1])):
            j += 1
        if i == 0x454F46:  # offset that would spell "EOF"
            i -= 1
        out += i.to_bytes(3, 'big') + (j - i).to_bytes(2, 'big') + new[i:j]
        i = j
    out += b'EOF'
    return bytes(out)


def fix_checksum(rom):
    rom[0x7FDC:0x7FE0] = b'\xff\xff\x00\x00'
    cs = sum(rom) & 0xFFFF
    rom[0x7FDE:0x7FE0] = cs.to_bytes(2, 'little')
    rom[0x7FDC:0x7FDE] = (cs ^ 0xFFFF).to_bytes(2, 'little')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('rom', help='original Rap Basketball (USA) (Proto).sfc')
    ap.add_argument('-o', '--out', default='Rap Basketball (USA) (Proto) [Playable].sfc')
    ap.add_argument('--ips', default=os.path.join(ROOT, 'patch', 'Rap Basketball (Proto) - Playable.ips'))
    ap.add_argument('--src', default=os.path.join(ROOT, 'src', 'patch.asm'))
    a = ap.parse_args()

    orig = open(a.rom, 'rb').read()
    if len(orig) == 0x100200:
        print('note: stripping 512-byte copier header')
        orig = orig[0x200:]
    crc = zlib.crc32(orig)
    if crc != EXPECTED_CRC:
        print('warning: CRC32 %08X does not match expected %08X - patch may not work' % (crc, EXPECTED_CRC))

    asm = Asm()
    out = asm.assemble(open(a.src).read())
    rom = bytearray(orig)
    for addr, data in out.items():  # new code must land in free (0xFF) space
        if 0x80B000 <= addr < 0x810000:
            o = lorom_off(addr)
            assert rom[o:o + len(data)] == b'\xff' * len(data), 'code overlaps used ROM at %06X' % addr
    apply(rom, out)
    fix_checksum(rom)

    open(a.out, 'wb').write(rom)
    ips = make_ips(orig, bytes(rom))
    os.makedirs(os.path.dirname(os.path.abspath(a.ips)), exist_ok=True)
    open(a.ips, 'wb').write(ips)
    end = max(k + len(v) for k, v in out.items() if 0x80B000 <= k < 0x810000)
    print('wrote %s (code $80B000-$%06X)' % (a.out, end - 1))
    print('wrote %s (%d bytes)' % (a.ips, len(ips)))


if __name__ == '__main__':
    main()
