"""Minimal headless SNES (65816 + stubbed PPU/APU) for tracing a LoROM game."""
import sys, struct
from collections import Counter, defaultdict

class SNES:
    def __init__(self, rom):
        self.rom = bytearray(rom)
        self.wram = bytearray(0x20000)
        self.vram = bytearray(0x10000)
        self.cgram = bytearray(512)
        self.oam = bytearray(544)
        self.io = {}
        self.dma = bytearray(0x80)
        self.vaddr = 0; self.vmain = 0; self.vlatch = 0
        self.cgaddr = 0; self.cglatch = None
        self.oamaddr = 0; self.oamlatch = 0
        self.wraddr = 0
        self.nmitimen = 0; self.rdnmi = 0; self.timeup = 0
        self.vblank = False; self.line = 0
        self.joy = 0
        self.mul_a = 0xff; self.mulres = 0; self.divres = 0; self.dividend = 0
        self.ppu = {}  # raw last writes to 21xx
        self.bgofs = defaultdict(int); self.ofslatch = 0
        self.m7 = 0; self.m7latch = 0; self.m7a = 0; self.m7b = 0
        self.apu_in = [0, 0, 0, 0]   # written by CPU
        self.apu_out = [0xAA, 0xBB, 0, 0]  # read by CPU
        self.apu_mode = 'ipl'
        self.htime = 0x1ff; self.vtime = 0x1ff
        self.irq_pending = False
        self.cov = Counter()
        self.unk = Counter()
        self.trace = None
        self.writes_watch = {}
        self.reset()

    # ---------------- memory ----------------
    def rom_off(self, bank, addr):
        b = bank & 0x7f
        if addr >= 0x8000:
            return (b * 0x8000 + addr - 0x8000) % len(self.rom)
        if b >= 0x40:
            return (b * 0x8000 + addr) % len(self.rom)  # unlikely
        return None

    def read(self, a):
        bank = a >> 16; addr = a & 0xffff
        if bank in (0x7e, 0x7f):
            return self.wram[((bank - 0x7e) << 16) | addr]
        if (bank & 0x7f) < 0x40 or True:
            if (bank & 0x7f) < 0x40 and addr < 0x2000:
                return self.wram[addr]
            if (bank & 0x7f) < 0x40 and addr < 0x8000:
                return self.ioread(addr)
            if addr >= 0x8000:
                return self.rom[self.rom_off(bank, addr)]
        self.unk['r%06x' % a] += 1
        return 0

    def write(self, a, v):
        bank = a >> 16; addr = a & 0xffff
        if a in self.writes_watch:
            self.writes_watch[a](a, v)
        if bank in (0x7e, 0x7f):
            self.wram[((bank - 0x7e) << 16) | addr] = v; return
        if (bank & 0x7f) < 0x40:
            if addr < 0x2000: self.wram[addr] = v; return
            if addr < 0x8000: self.iowrite(addr, v); return
        self.unk['w%06x' % a] += 1

    def ioread(self, addr):
        if 0x2140 <= addr <= 0x217f:
            return self.apu_read(addr & 3)
        if addr == 0x2180:
            v = self.wram[self.wraddr]; self.wraddr = (self.wraddr + 1) & 0x1ffff; return v
        if addr == 0x4210:
            v = self.rdnmi | 0x02; self.rdnmi = 0; return v
        if addr == 0x4211:
            v = self.timeup; self.timeup = 0; self.irq_pending = False; return v
        if addr == 0x4212:
            return (0x80 if self.vblank else 0) | (0x01 if self.vblank and self.line < 228 else 0)
        if addr == 0x4218: return self.joy & 0xff
        if addr == 0x4219: return self.joy >> 8
        if 0x421a <= addr <= 0x421f: return 0
        if addr == 0x4016 or addr == 0x4017: return 0
        if addr == 0x4214: return self.divres & 0xff
        if addr == 0x4215: return self.divres >> 8
        if addr == 0x4216: return self.mulres & 0xff
        if addr == 0x4217: return self.mulres >> 8
        if 0x4300 <= addr <= 0x437f: return self.dma[addr - 0x4300]
        if addr == 0x2137: return 0
        if addr in (0x213c, 0x213d): return self.line & 0xff if addr == 0x213d else 0
        if addr in (0x2134, 0x2135, 0x2136):
            r = (self.m7a * (self.m7b >> 8 if self.m7b >> 8 < 128 else (self.m7b >> 8) - 256)) & 0xffffff
            return (r >> ((addr - 0x2134) * 8)) & 0xff
        if addr == 0x213f or addr == 0x213e: return 0
        if addr == 0x213b:
            v = self.cgram[self.cgaddr & 0x1ff]; self.cgaddr += 1; return v
        if addr == 0x2139:
            return self.vram[(self.vaddr * 2) & 0xffff]
        if addr == 0x213a:
            return self.vram[(self.vaddr * 2 + 1) & 0xffff]
        self.unk['ior%04x' % addr] += 1
        return 0

    def iowrite(self, addr, v):
        if 0x2100 <= addr <= 0x213f: self.ppu[addr] = v
        if addr == 0x2115: self.vmain = v
        elif addr == 0x2116: self.vaddr = (self.vaddr & 0xff00) | v
        elif addr == 0x2117: self.vaddr = (self.vaddr & 0xff) | (v << 8)
        elif addr == 0x2118:
            self.vram[(self.vaddr * 2) & 0xffff] = v
            if not (self.vmain & 0x80): self.vaddr = (self.vaddr + self.vinc()) & 0x7fff
        elif addr == 0x2119:
            self.vram[(self.vaddr * 2 + 1) & 0xffff] = v
            if self.vmain & 0x80: self.vaddr = (self.vaddr + self.vinc()) & 0x7fff
        elif addr == 0x2121: self.cgaddr = v * 2; self.cglatch = None
        elif addr == 0x2122:
            self.cgram[self.cgaddr & 0x1ff] = v; self.cgaddr += 1
        elif addr == 0x2102: self.oamaddr = (self.oamaddr & 0x200) | (v << 1)
        elif addr == 0x2103: self.oamaddr = (self.oamaddr & 0x1fe) | ((v & 1) << 9)
        elif addr == 0x2104:
            if self.oamaddr < 0x220: self.oam[self.oamaddr] = v
            self.oamaddr = (self.oamaddr + 1) & 0x3ff
        elif 0x210d <= addr <= 0x2114:
            self.bgofs[addr] = ((v << 8) | self.ofslatch) & 0x3ff; self.ofslatch = v
        elif addr == 0x211b: self.m7a = ((v << 8) | self.m7latch); self.m7a = self.m7a - 65536 if self.m7a > 32767 else self.m7a; self.m7latch = v
        elif addr == 0x211c: self.m7b = (v << 8) | self.m7latch; self.m7latch = v
        elif 0x2140 <= addr <= 0x217f: self.apu_write(addr & 3, v)
        elif addr == 0x2181: self.wraddr = (self.wraddr & 0x1ff00) | v
        elif addr == 0x2182: self.wraddr = (self.wraddr & 0x100ff) | (v << 8)
        elif addr == 0x2183: self.wraddr = (self.wraddr & 0xffff) | ((v & 1) << 16)
        elif addr == 0x2180: self.wram[self.wraddr] = v; self.wraddr = (self.wraddr + 1) & 0x1ffff
        elif addr == 0x4200: self.nmitimen = v
        elif addr == 0x4202: self.mul_a = v
        elif addr == 0x4203: self.mulres = self.mul_a * v; self.divres = v
        elif addr == 0x4204: self.dividend = (self.dividend & 0xff00) | v
        elif addr == 0x4205: self.dividend = (self.dividend & 0xff) | (v << 8)
        elif addr == 0x4206:
            if v: self.divres = self.dividend // v; self.mulres = self.dividend % v
            else: self.divres = 0xffff; self.mulres = self.dividend
        elif addr == 0x4207: self.htime = (self.htime & 0x100) | v
        elif addr == 0x4208: self.htime = (self.htime & 0xff) | ((v & 1) << 8)
        elif addr == 0x4209: self.vtime = (self.vtime & 0x100) | v
        elif addr == 0x420a: self.vtime = (self.vtime & 0xff) | ((v & 1) << 8)
        elif addr == 0x420b: self.do_dma(v)
        elif 0x4300 <= addr <= 0x437f: self.dma[addr - 0x4300] = v
        elif addr in (0x420c, 0x420d, 0x4201, 0x4016): self.io[addr] = v
        elif 0x2100 <= addr <= 0x213f: pass
        else: self.unk['iow%04x @%02X%04X' % (addr, self.PB, self.PC)] += 1

    def vinc(self):
        return (1, 32, 128, 128)[self.vmain & 3]

    def do_dma(self, mask):
        for ch in range(8):
            if not mask & (1 << ch): continue
            r = self.dma[ch * 16: ch * 16 + 16]
            ctrl = r[0]; dest = 0x2100 | r[1]
            src = r[2] | (r[3] << 8); sbank = r[4]
            n = r[5] | (r[6] << 8)
            if n == 0: n = 0x10000
            mode = ctrl & 7
            pat = {0: [0], 1: [0, 1], 2: [0, 0], 3: [0, 0, 1, 1], 4: [0, 1, 2, 3], 5: [0, 1, 0, 1], 6: [0, 0], 7: [0, 0, 1, 1]}[mode]
            step = 0 if ctrl & 0x08 else (-1 if ctrl & 0x10 else 1)
            for i in range(n):
                d = dest + pat[i % len(pat)]
                if ctrl & 0x80:
                    self.write((sbank << 16) | src, self.read(d))
                else:
                    self.iowrite(d, self.read((sbank << 16) | src))
                src = (src + step) & 0xffff
            self.dma[ch * 16 + 2] = src & 0xff; self.dma[ch * 16 + 3] = src >> 8
            self.dma[ch * 16 + 5] = 0; self.dma[ch * 16 + 6] = 0
            self.dmalog.append((self.frame, ch, hex(ctrl), hex(dest), hex((sbank << 16) | src), n))

    # --------------- fake APU ---------------
    def apu_read(self, p):
        if p == 2: return self.apu_out[2] | 0x80
        return self.apu_out[p]

    def apu_write(self, p, v):
        self.apu_in[p] = v
        self.apulog.append((self.frame, p, v))
        # Echo protocol: port0 echoes. Good for IPL uploads and most drivers' acks.
        self.apu_out[p] = v

    # ---------------- CPU ----------------
    def reset(self):
        self.A = 0; self.X = 0; self.Y = 0; self.S = 0x1ff; self.D = 0; self.DB = 0; self.PB = 0
        self.P = 0x34; self.E = 1
        self.PC = self.r16(0xfffc)
        self.frame = 0; self.icount = 0; self.dmalog = []; self.apulog = []
        self.waiting = False; self.stopped = False

    def r16(self, a):
        return self.read(a) | (self.read((a & 0xff0000) | ((a + 1) & 0xffff)) << 8)

    @property
    def m(self): return (self.P >> 5) & 1
    @property
    def x(self): return (self.P >> 4) & 1

    def push(self, v):
        self.write(self.S, v & 0xff); self.S = (self.S - 1) & 0xffff
        if self.E: self.S = 0x100 | (self.S & 0xff)
    def pull(self):
        self.S = (self.S + 1) & 0xffff
        if self.E: self.S = 0x100 | (self.S & 0xff)
        return self.read(self.S)
    def push16(self, v): self.push(v >> 8); self.push(v)
    def pull16(self): l = self.pull(); return l | (self.pull() << 8)

    def fetch(self):
        v = self.read((self.PB << 16) | self.PC); self.PC = (self.PC + 1) & 0xffff; return v
    def fetch16(self): l = self.fetch(); return l | (self.fetch() << 8)
    def fetch24(self): l = self.fetch16(); return l | (self.fetch() << 16)

    def setP(self, v):
        self.P = v
        if self.E: self.P |= 0x30
        if self.P & 0x10: self.X &= 0xff; self.Y &= 0xff

    def nz8(self, v): self.P = (self.P & 0x7d) | (v & 0x80) | (0 if v & 0xff else 2)
    def nz16(self, v): self.P = (self.P & 0x7d) | ((v >> 8) & 0x80) | (0 if v & 0xffff else 2)
    def nz(self, v, w): self.nz16(v) if w else self.nz8(v)

    def interrupt(self, vec_native, vec_emu):
        if not self.E: self.push(self.PB)
        self.push16(self.PC); self.push(self.P)
        self.P = (self.P | 0x04) & ~0x08
        self.PB = 0
        self.PC = self.r16(vec_emu if self.E else vec_native)
        self.waiting = False

    # addressing: returns effective 24-bit address (data)
    def ea(self, mode):
        D = self.D
        if mode == 'dp': return (D + self.fetch()) & 0xffff
        if mode == 'dpx': return (D + self.fetch() + self.X) & 0xffff
        if mode == 'dpy': return (D + self.fetch() + self.Y) & 0xffff
        if mode == 'idp':
            p = (D + self.fetch()) & 0xffff; return (self.DB << 16) | self.r16(p)
        if mode == 'idx':
            p = (D + self.fetch() + self.X) & 0xffff; return (self.DB << 16) | self.r16(p)
        if mode == 'idy':
            p = (D + self.fetch()) & 0xffff; return (((self.DB << 16) | self.r16(p)) + self.Y) & 0xffffff
        if mode == 'idl':
            p = (D + self.fetch()) & 0xffff; return self.r16(p) | (self.read(p + 2) << 16)
        if mode == 'idly':
            p = (D + self.fetch()) & 0xffff; return ((self.r16(p) | (self.read(p + 2) << 16)) + self.Y) & 0xffffff
        if mode == 'sr': return (self.fetch() + self.S) & 0xffff
        if mode == 'sry':
            p = (self.fetch() + self.S) & 0xffff; return (((self.DB << 16) | self.r16(p)) + self.Y) & 0xffffff
        if mode == 'abs': return (self.DB << 16) | self.fetch16()
        if mode == 'abx': return (((self.DB << 16) | self.fetch16()) + self.X) & 0xffffff
        if mode == 'aby': return (((self.DB << 16) | self.fetch16()) + self.Y) & 0xffffff
        if mode == 'abl': return self.fetch24()
        if mode == 'alx': return (self.fetch24() + self.X) & 0xffffff
        raise Exception(mode)

    def rd(self, a, w):
        if w: return self.read(a) | (self.read((a + 1) & 0xffffff) << 8)
        return self.read(a)
    def wr(self, a, v, w):
        self.write(a, v & 0xff)
        if w: self.write((a + 1) & 0xffffff, (v >> 8) & 0xff)

    def operand(self, mode, w):
        if mode in ('imm',):
            return self.fetch16() if w else self.fetch()
        return self.rd(self.ea(mode), w)

    def step(self):
        pc0 = (self.PB << 16) | self.PC
        self.cov[pc0] |= 1 << ((self.P >> 4) & 3)
        if self.trace is not None: self.trace.append((pc0, self.A, self.X, self.Y, self.P, self.S, self.D, self.DB))
        op = self.fetch()
        self.icount += 1
        h = OPS[op]
        h(self)

    def adc(self, v):
        w = not self.m
        c = self.P & 1
        if self.P & 0x08:  # decimal
            a = self.A & (0xffff if w else 0xff)
            res = 0; carry = c
            for sh in range(0, 16 if w else 8, 4):
                d = ((a >> sh) & 15) + ((v >> sh) & 15) + carry
                carry = 1 if d > 9 else 0
                if carry: d -= 10
                res |= (d & 15) << sh
            r = res; mask = 0xffff if w else 0xff
            self.P = (self.P & ~0x41) | carry
            self.setA(r, w); self.nz(r, w); return
        mask = 0xffff if w else 0xff; sign = 0x8000 if w else 0x80
        a = self.A & mask
        r = a + v + c
        self.P = (self.P & ~0x41) | (1 if r > mask else 0) | (0x40 if (~(a ^ v) & (a ^ r) & sign) else 0)
        r &= mask
        self.setA(r, w); self.nz(r, w)

    def sbc(self, v):
        w = not self.m
        mask = 0xffff if w else 0xff
        if self.P & 0x08:
            a = self.A & mask; borrow = 1 - (self.P & 1); res = 0
            for sh in range(0, 16 if w else 8, 4):
                d = ((a >> sh) & 15) - ((v >> sh) & 15) - borrow
                borrow = 1 if d < 0 else 0
                if borrow: d += 10
                res |= (d & 15) << sh
            self.P = (self.P & ~0x41) | (1 - borrow)
            self.setA(res, w); self.nz(res, w); return
        self.adc(v ^ mask)

    def setA(self, v, w):
        if w: self.A = v & 0xffff
        else: self.A = (self.A & 0xff00) | (v & 0xff)

    def cmp(self, reg, v, w):
        mask = 0xffff if w else 0xff
        r = (reg & mask) - v
        self.P = (self.P & ~0x83) | (1 if r >= 0 else 0) | (2 if (r & mask) == 0 else 0) | ((r >> (8 if w else 0)) & 0x80)

    def branch(self, cond):
        off = self.fetch()
        if cond:
            self.PC = (self.PC + (off - 256 if off > 127 else off)) & 0xffff

    # ---------------- frame driver ----------------
    INSTR_PER_LINE = 50

    def run_frame(self, maxinstr=60000):
        # visible lines
        for line in range(262):
            self.line = line
            if line == 225:
                self.vblank = True
                self.rdnmi = 0x80
                self.render_hook()
                if self.nmitimen & 0x80:
                    self.interrupt(0xffea, 0xfffa)
            if line == 0:
                self.vblank = False; self.rdnmi = 0
            if (self.nmitimen & 0x20) and line == self.vtime:
                self.timeup = 0x80; self.irq_pending = True
            n = self.INSTR_PER_LINE
            for _ in range(n):
                if self.irq_pending and not (self.P & 0x04):
                    self.irq_pending = False
                    self.interrupt(0xffee, 0xfffe)
                if self.waiting or self.stopped:
                    break
                self.step()
        self.frame += 1

    def render_hook(self): pass


# ================= opcode implementations =================
OPS = [None] * 256
def opc(code):
    def d(f): OPS[code] = f; return f
    return d

ALU = {'ORA': 0x00, 'AND': 0x20, 'EOR': 0x40, 'ADC': 0x60, 'STA': 0x80, 'LDA': 0xA0, 'CMP': 0xC0, 'SBC': 0xE0}
AMODES = [(0x01, 'idx'), (0x03, 'sr'), (0x05, 'dp'), (0x07, 'idl'), (0x09, 'imm'), (0x0D, 'abs'), (0x0F, 'abl'),
          (0x11, 'idy'), (0x12, 'idp'), (0x13, 'sry'), (0x15, 'dpx'), (0x17, 'idly'), (0x19, 'aby'), (0x1D, 'abx'), (0x1F, 'alx')]

def mk_alu(name, mode):
    def f(c):
        w = not c.m
        if name == 'STA':
            c.wr(c.ea(mode), c.A, w); return
        v = c.operand(mode, w)
        mask = 0xffff if w else 0xff
        if name == 'ORA': r = (c.A | v) & mask; c.setA(r, w); c.nz(r, w)
        elif name == 'AND': r = (c.A & v) & mask; c.setA(r, w); c.nz(r, w)
        elif name == 'EOR': r = (c.A ^ v) & mask; c.setA(r, w); c.nz(r, w)
        elif name == 'LDA': c.setA(v, w); c.nz(v, w)
        elif name == 'CMP': c.cmp(c.A, v, w)
        elif name == 'ADC': c.adc(v)
        elif name == 'SBC': c.sbc(v)
    return f
for n, b in ALU.items():
    for o, m in AMODES:
        if n == 'STA' and m == 'imm': continue
        OPS[b + o] = mk_alu(n, m)

def mk_rmw(fn, mode):
    def f(c):
        w = not c.m
        if mode == 'acc':
            v = c.A & (0xffff if w else 0xff); r = fn(c, v, w); c.setA(r, w); return
        a = c.ea(mode); v = c.rd(a, w); r = fn(c, v, w); c.wr(a, r, w)
    return f
def _asl(c, v, w):
    mask = 0xffff if w else 0xff; top = 0x8000 if w else 0x80
    c.P = (c.P & ~1) | (1 if v & top else 0); r = (v << 1) & mask; c.nz(r, w); return r
def _lsr(c, v, w):
    c.P = (c.P & ~1) | (v & 1); r = v >> 1; c.nz(r, w); return r
def _rol(c, v, w):
    mask = 0xffff if w else 0xff; top = 0x8000 if w else 0x80
    r = ((v << 1) | (c.P & 1)) & mask; c.P = (c.P & ~1) | (1 if v & top else 0); c.nz(r, w); return r
def _ror(c, v, w):
    top = 0x8000 if w else 0x80
    r = (v >> 1) | (top if c.P & 1 else 0); c.P = (c.P & ~1) | (v & 1); c.nz(r, w); return r
def _inc(c, v, w):
    r = (v + 1) & (0xffff if w else 0xff); c.nz(r, w); return r
def _dec(c, v, w):
    r = (v - 1) & (0xffff if w else 0xff); c.nz(r, w); return r
def _tsb(c, v, w):
    c.P = (c.P & ~2) | (0 if (v & c.A & (0xffff if w else 0xff)) else 2); return v | c.A
def _trb(c, v, w):
    c.P = (c.P & ~2) | (0 if (v & c.A & (0xffff if w else 0xff)) else 2); return v & ~c.A
for base, fn in ((0x00, _asl), (0x40, _lsr), (0x20, _rol), (0x60, _ror)):
    OPS[base + 0x06] = mk_rmw(fn, 'dp'); OPS[base + 0x0A] = mk_rmw(fn, 'acc')
    OPS[base + 0x0E] = mk_rmw(fn, 'abs'); OPS[base + 0x16] = mk_rmw(fn, 'dpx'); OPS[base + 0x1E] = mk_rmw(fn, 'abx')
OPS[0xE6] = mk_rmw(_inc, 'dp'); OPS[0xEE] = mk_rmw(_inc, 'abs'); OPS[0xF6] = mk_rmw(_inc, 'dpx'); OPS[0xFE] = mk_rmw(_inc, 'abx'); OPS[0x1A] = mk_rmw(_inc, 'acc')
OPS[0xC6] = mk_rmw(_dec, 'dp'); OPS[0xCE] = mk_rmw(_dec, 'abs'); OPS[0xD6] = mk_rmw(_dec, 'dpx'); OPS[0xDE] = mk_rmw(_dec, 'abx'); OPS[0x3A] = mk_rmw(_dec, 'acc')
OPS[0x04] = mk_rmw(_tsb, 'dp'); OPS[0x0C] = mk_rmw(_tsb, 'abs'); OPS[0x14] = mk_rmw(_trb, 'dp'); OPS[0x1C] = mk_rmw(_trb, 'abs')

def mk_bit(mode):
    def f(c):
        w = not c.m
        v = c.operand(mode, w)
        z = (c.A & v & (0xffff if w else 0xff)) == 0
        if mode == 'imm':
            c.P = (c.P & ~2) | (2 if z else 0)
        else:
            top = 0x8000 if w else 0x80
            c.P = (c.P & ~0xc2) | (2 if z else 0) | (0x80 if v & top else 0) | (0x40 if v & (top >> 1) else 0)
    return f
OPS[0x89] = mk_bit('imm'); OPS[0x24] = mk_bit('dp'); OPS[0x2C] = mk_bit('abs'); OPS[0x34] = mk_bit('dpx'); OPS[0x3C] = mk_bit('abx')

def mk_ld(reg, mode):
    def f(c):
        w = not c.x
        v = c.operand(mode, w); setattr(c, reg, v); c.nz(v, w)
    return f
def mk_st(reg, mode):
    def f(c):
        w = not c.x
        c.wr(c.ea(mode), getattr(c, reg), w)
    return f
def mk_cp(reg, mode):
    def f(c):
        w = not c.x
        c.cmp(getattr(c, reg), c.operand(mode, w), w)
    return f
for code, mode in ((0xA2, 'imm'), (0xA6, 'dp'), (0xB6, 'dpy'), (0xAE, 'abs'), (0xBE, 'aby')): OPS[code] = mk_ld('X', mode)
for code, mode in ((0xA0, 'imm'), (0xA4, 'dp'), (0xB4, 'dpx'), (0xAC, 'abs'), (0xBC, 'abx')): OPS[code] = mk_ld('Y', mode)
for code, mode in ((0x86, 'dp'), (0x96, 'dpy'), (0x8E, 'abs')): OPS[code] = mk_st('X', mode)
for code, mode in ((0x84, 'dp'), (0x94, 'dpx'), (0x8C, 'abs')): OPS[code] = mk_st('Y', mode)
for code, mode in ((0xE0, 'imm'), (0xE4, 'dp'), (0xEC, 'abs')): OPS[code] = mk_cp('X', mode)
for code, mode in ((0xC0, 'imm'), (0xC4, 'dp'), (0xCC, 'abs')): OPS[code] = mk_cp('Y', mode)

def mk_stz(mode):
    def f(c): c.wr(c.ea(mode), 0, not c.m)
    return f
for code, mode in ((0x64, 'dp'), (0x74, 'dpx'), (0x9C, 'abs'), (0x9E, 'abx')): OPS[code] = mk_stz(mode)

for code, cond in ((0x10, lambda c: not c.P & 0x80), (0x30, lambda c: c.P & 0x80), (0x50, lambda c: not c.P & 0x40),
                   (0x70, lambda c: c.P & 0x40), (0x90, lambda c: not c.P & 1), (0xB0, lambda c: c.P & 1),
                   (0xD0, lambda c: not c.P & 2), (0xF0, lambda c: c.P & 2), (0x80, lambda c: True)):
    OPS[code] = (lambda cond: lambda c: c.branch(cond(c)))(cond)

@opc(0x82)
def _brl(c):
    o = c.fetch16(); c.PC = (c.PC + (o - 65536 if o > 32767 else o)) & 0xffff
@opc(0x4C)
def _jmp(c): c.PC = c.fetch16()
@opc(0x5C)
def _jml(c): a = c.fetch24(); c.PC = a & 0xffff; c.PB = a >> 16
@opc(0x6C)
def _jmpi(c): a = c.fetch16(); c.PC = c.r16(a)
@opc(0x7C)
def _jmpix(c): a = c.fetch16(); c.PC = c.r16((c.PB << 16) | ((a + c.X) & 0xffff))
@opc(0xDC)
def _jmli(c): a = c.fetch16(); c.PC = c.r16(a); c.PB = c.read(a + 2)
@opc(0x20)
def _jsr(c): a = c.fetch16(); c.push16((c.PC - 1) & 0xffff); c.PC = a
@opc(0xFC)
def _jsrix(c): a = c.fetch16(); c.push16((c.PC - 1) & 0xffff); c.PC = c.r16((c.PB << 16) | ((a + c.X) & 0xffff))
@opc(0x22)
def _jsl(c):
    a = c.fetch24(); c.push(c.PB); c.push16((c.PC - 1) & 0xffff); c.PC = a & 0xffff; c.PB = a >> 16
@opc(0x60)
def _rts(c): c.PC = (c.pull16() + 1) & 0xffff
@opc(0x6B)
def _rtl(c): c.PC = (c.pull16() + 1) & 0xffff; c.PB = c.pull()
@opc(0x40)
def _rti(c):
    c.setP(c.pull()); c.PC = c.pull16()
    if not c.E: c.PB = c.pull()
@opc(0x00)
def _brk(c):
    c.fetch(); print('BRK at %02X:%04X' % (c.PB, (c.PC - 2) & 0xffff)); c.interrupt(0xffe6, 0xfffe)
@opc(0x02)
def _cop(c):
    c.fetch(); c.interrupt(0xffe4, 0xfff4)
@opc(0x42)
def _wdm(c): c.fetch()
@opc(0xEA)
def _nop(c): pass
@opc(0xCB)
def _wai(c): c.waiting = True
@opc(0xDB)
def _stp(c): c.stopped = True; print('STP at', hex(c.PC))

for code, bit, val in ((0x18, 1, 0), (0x38, 1, 1), (0x58, 4, 0), (0x78, 4, 1), (0xB8, 0x40, 0), (0xD8, 8, 0), (0xF8, 8, 1)):
    OPS[code] = (lambda bit, val: lambda c: setattr(c, 'P', (c.P | bit) if val else (c.P & ~bit)))(bit, val)
@opc(0xC2)
def _rep(c): c.setP(c.P & ~c.fetch())
@opc(0xE2)
def _sep(c): c.setP(c.P | c.fetch())
@opc(0xFB)
def _xce(c):
    carry = c.P & 1; c.P = (c.P & ~1) | c.E; c.E = carry
    if c.E: c.P |= 0x30; c.S = 0x100 | (c.S & 0xff); c.X &= 0xff; c.Y &= 0xff

def tr(src, dst, flag):
    def f(c):
        if dst == 'S':
            c.S = c.A if not c.E else 0x100 | (c.A & 0xff); return
        if dst == 'D': c.D = c.A; c.nz16(c.D); return
        if src == 'D' or src == 'S':
            v = getattr(c, src); c.A = v; c.nz16(v); return
        w = not (c.m if flag == 'm' else c.x)
        v = getattr(c, src)
        if dst == 'A':
            c.setA(v, w); c.nz(v & (0xffff if w else 0xff), w)
        else:
            v &= 0xffff if w else 0xff
            setattr(c, dst, v); c.nz(v, w)
    return f
OPS[0xAA] = tr('A', 'X', 'x'); OPS[0xA8] = tr('A', 'Y', 'x'); OPS[0x8A] = tr('X', 'A', 'm'); OPS[0x98] = tr('Y', 'A', 'm')
OPS[0x9B] = tr('X', 'Y', 'x'); OPS[0xBB] = tr('Y', 'X', 'x'); OPS[0x1B] = tr('A', 'S', None); OPS[0x5B] = tr('A', 'D', None)
OPS[0x7B] = tr('D', 'A', None); OPS[0x3B] = tr('S', 'A', None)
@opc(0x9A)
def _txs(c): c.S = c.X if not c.E else 0x100 | (c.X & 0xff)
@opc(0xBA)
def _tsx(c):
    w = not c.x; v = c.S & (0xffff if w else 0xff); c.X = v; c.nz(v, w)
@opc(0xEB)
def _xba(c): c.A = ((c.A >> 8) | (c.A << 8)) & 0xffff; c.nz8(c.A & 0xff)
@opc(0xE8)
def _inx(c): w = not c.x; c.X = (c.X + 1) & (0xffff if w else 0xff); c.nz(c.X, w)
@opc(0xC8)
def _iny(c): w = not c.x; c.Y = (c.Y + 1) & (0xffff if w else 0xff); c.nz(c.Y, w)
@opc(0xCA)
def _dex(c): w = not c.x; c.X = (c.X - 1) & (0xffff if w else 0xff); c.nz(c.X, w)
@opc(0x88)
def _dey(c): w = not c.x; c.Y = (c.Y - 1) & (0xffff if w else 0xff); c.nz(c.Y, w)

@opc(0x48)
def _pha(c):
    if c.m: c.push(c.A)
    else: c.push16(c.A)
@opc(0x68)
def _pla(c):
    if c.m: v = c.pull(); c.setA(v, 0); c.nz8(v)
    else: v = c.pull16(); c.A = v; c.nz16(v)
@opc(0xDA)
def _phx(c):
    if c.x: c.push(c.X)
    else: c.push16(c.X)
@opc(0xFA)
def _plx(c):
    if c.x: c.X = c.pull(); c.nz8(c.X)
    else: c.X = c.pull16(); c.nz16(c.X)
@opc(0x5A)
def _phy(c):
    if c.x: c.push(c.Y)
    else: c.push16(c.Y)
@opc(0x7A)
def _ply(c):
    if c.x: c.Y = c.pull(); c.nz8(c.Y)
    else: c.Y = c.pull16(); c.nz16(c.Y)
@opc(0x08)
def _php(c): c.push(c.P)
@opc(0x28)
def _plp(c): c.setP(c.pull())
@opc(0x8B)
def _phb(c): c.push(c.DB)
@opc(0xAB)
def _plb(c): c.DB = c.pull(); c.nz8(c.DB)
@opc(0x4B)
def _phk(c): c.push(c.PB)
@opc(0x0B)
def _phd(c): c.push16(c.D)
@opc(0x2B)
def _pld(c): c.D = c.pull16(); c.nz16(c.D)
@opc(0xF4)
def _pea(c): c.push16(c.fetch16())
@opc(0xD4)
def _pei(c): p = (c.D + c.fetch()) & 0xffff; c.push16(c.r16(p))
@opc(0x62)
def _per(c): o = c.fetch16(); c.push16((c.PC + o) & 0xffff)

def mk_mv(step):
    def f(c):
        dst = c.fetch(); src = c.fetch()
        c.DB = dst
        c.write((dst << 16) | c.Y, c.read((src << 16) | c.X))
        mask = 0xff if c.x else 0xffff
        c.X = (c.X + step) & mask; c.Y = (c.Y + step) & mask
        c.A = (c.A - 1) & 0xffff
        if c.A != 0xffff: c.PC = (c.PC - 3) & 0xffff
    return f
OPS[0x54] = mk_mv(1); OPS[0x44] = mk_mv(-1)

assert all(OPS), [hex(i) for i, o in enumerate(OPS) if o is None]
