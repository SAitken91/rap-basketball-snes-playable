"""Simple SNES PPU renderer (modes 0-1-3, sprites) for screenshots."""
import numpy as np
from PIL import Image

BPP = {0: (2, 2, 2, 2), 1: (4, 4, 2, 0), 2: (4, 4, 0, 0), 3: (8, 4, 0, 0), 4: (8, 2, 0, 0), 5: (4, 2, 0, 0), 6: (4, 0, 0, 0), 7: (8, 0, 0, 0)}

def palette(cg):
    c = np.frombuffer(bytes(cg), dtype='<u2').astype(np.uint32)
    r = (c & 31) << 3; g = ((c >> 5) & 31) << 3; b = ((c >> 10) & 31) << 3
    return np.stack([r, g, b], -1).astype(np.uint8)

def decode_tile(vram, addr, bpp):
    # returns 8x8 array of color indices
    out = np.zeros((8, 8), np.uint8)
    for plane in range(0, bpp, 2):
        base = (addr + plane * 8) & 0xffff
        for row in range(8):
            lo = vram[(base + row * 2) & 0xffff]; hi = vram[(base + row * 2 + 1) & 0xffff]
            for col in range(8):
                bit = 7 - col
                out[row, col] |= (((lo >> bit) & 1) << plane) | (((hi >> bit) & 1) << (plane + 1))
    return out

class Renderer:
    def __init__(self, s):
        self.s = s
        self.cache = {}

    def tile(self, addr, bpp):
        key = (addr, bpp)
        t = self.cache.get(key)
        if t is None:
            t = decode_tile(self.s.vram, addr, bpp); self.cache[key] = t
        return t

    def bg_layer(self, n, bpp, mode):
        s = self.s; p = s.ppu
        sc = p.get(0x2107 + n, 0)
        mapbase = (sc & 0xfc) << 9
        msize = sc & 3
        nba = p.get(0x210b + n // 2, 0)
        charbase = ((nba >> (4 * (n & 1))) & 15) << 13
        big = (p.get(0x2105, 0) >> (4 + n)) & 1
        ts = 16 if big else 8
        mw = 64 if msize & 1 else 32; mh = 64 if msize & 2 else 32
        hs = s.bgofs.get(0x210d + n * 2, 0); vs = s.bgofs.get(0x210e + n * 2, 0)
        palbase = n * 32 if mode == 0 else 0
        pw = mw * ts; ph = mh * ts
        img = np.zeros((ph, pw), np.int16) - 1  # palette index or -1
        pri = np.zeros((ph, pw), np.uint8)
        for ty in range(mh):
            for tx in range(mw):
                q = 0
                if tx >= 32: q += 1
                if ty >= 32: q += (2 if msize == 3 else 1)
                ea = mapbase + q * 0x800 + ((ty & 31) * 32 + (tx & 31)) * 2
                e = s.vram[ea & 0xffff] | (s.vram[(ea + 1) & 0xffff] << 8)
                ch = e & 0x3ff; pal = (e >> 10) & 7; pr = (e >> 13) & 1; hf = (e >> 14) & 1; vf = e >> 15
                block = np.zeros((ts, ts), np.uint8)
                for sy in range(ts // 8):
                    for sx in range(ts // 8):
                        c = ch + sy * 16 + sx
                        block[sy * 8:sy * 8 + 8, sx * 8:sx * 8 + 8] = self.tile((charbase + c * bpp * 8) & 0xffff, bpp)
                if hf: block = block[:, ::-1]
                if vf: block = block[::-1, :]
                block = block.astype(np.int16)
                blk = np.where(block > 0, palbase + pal * (1 << bpp) + block, -1) if bpp < 8 else np.where(block > 0, block, -1)
                img[ty * ts:(ty + 1) * ts, tx * ts:(tx + 1) * ts] = blk
                pri[ty * ts:(ty + 1) * ts, tx * ts:(tx + 1) * ts] = pr
        ys = (np.arange(224) + vs) % ph; xs = (np.arange(256) + hs) % pw
        return img[np.ix_(ys, xs)], pri[np.ix_(ys, xs)]

    def sprites(self):
        s = self.s; p = s.ppu
        obsel = p.get(0x2101, 0)
        base = (obsel & 7) << 14; gap = ((obsel >> 3) & 3) << 13
        sizes = [(8, 16), (8, 32), (8, 64), (16, 32), (16, 64), (32, 64), (16, 32), (16, 32)][obsel >> 5]
        out = np.zeros((4, 224, 256), np.int16) - 1
        for i in range(127, -1, -1):
            o = s.oam[i * 4:i * 4 + 4]
            hi = (s.oam[512 + i // 4] >> ((i & 3) * 2)) & 3
            x = o[0] | ((hi & 1) << 8)
            if x >= 256: x -= 512
            y = o[1]; ch = o[2] | ((o[3] & 1) << 8); pal = (o[3] >> 1) & 7; pr = (o[3] >> 4) & 3
            hf = (o[3] >> 6) & 1; vf = o[3] >> 7
            sz = sizes[hi >> 1]
            block = np.zeros((sz, sz), np.uint8)
            for ty in range(sz // 8):
                for tx in range(sz // 8):
                    c = (((ch >> 4) + ty) & 15) * 16 + (((ch & 15) + tx) & 15) | (ch & 0x100)
                    addr = base + (c & 0xff) * 32 + ((gap + 0x2000) if c & 0x100 else 0)
                    block[ty * 8:ty * 8 + 8, tx * 8:tx * 8 + 8] = self.tile(addr & 0xffff, 4)
            if hf: block = block[:, ::-1]
            if vf: block = block[::-1, :]
            for yy in range(sz):
                sy = (y + yy) & 0xff
                if sy >= 224: continue
                for xx in range(sz):
                    sx = x + xx
                    if 0 <= sx < 256 and block[yy, xx]:
                        out[pr, sy, sx] = 128 + pal * 16 + block[yy, xx]
        return out

    def render(self, path=None, scale=2):
        self.cache = {}
        s = self.s; p = s.ppu
        mode = p.get(0x2105, 0) & 7
        tm = p.get(0x212c, 0) | p.get(0x212d, 0)
        pal = palette(s.cgram)
        frame = np.zeros((224, 256), np.int16)  # backdrop index 0
        layers = []
        for n in range(4):
            bpp = BPP[mode][n]
            if bpp and tm & (1 << n):
                layers.append((n, self.bg_layer(n, bpp, mode)))
        spr = self.sprites() if tm & 0x10 else None
        # crude priority order for mode 1: BG3lo, BG4lo?, spr0, BG1lo/BG2lo... keep simple
        order = []
        L = dict(layers)
        def bg(n, pr): order.append(('bg', n, pr))
        def sp(pr): order.append(('sp', pr))
        if mode == 1:
            seq = [('bg', 2, 0), ('sp', 0), ('bg', 1, 0), ('bg', 0, 0), ('sp', 1), ('bg', 1, 1), ('bg', 0, 1), ('sp', 2), ('sp', 3)]
            seq = [('bg', 3, 0), ('bg', 2, 0), ('bg', 3, 1)] + seq[1:] + []
            seq.insert(seq.index(('bg', 3, 1)) + 1, ('bg', 2, 1)) if not (p.get(0x2105, 0) & 8) else seq.append(('bg', 2, 1))
        else:
            seq = [('bg', 3, 0), ('bg', 2, 0), ('sp', 0), ('bg', 3, 1), ('bg', 2, 1), ('sp', 1), ('bg', 1, 0), ('bg', 0, 0), ('sp', 2), ('bg', 1, 1), ('bg', 0, 1), ('sp', 3)]
        for it in seq:
            if it[0] == 'bg':
                if it[1] in L:
                    img, pri = L[it[1]]
                    m = (img >= 0) & (pri == it[2])
                    frame[m] = img[m]
            elif spr is not None:
                m = spr[it[1]] >= 0
                frame[m] = spr[it[1]][m]
        rgb = pal[frame]
        bright = p.get(0x2100, 0x0f)
        if bright & 0x80: rgb = rgb * 0
        else: rgb = (rgb.astype(np.uint16) * ((bright & 15) + 1) // 16).astype(np.uint8)
        im = Image.fromarray(rgb, 'RGB')
        if scale != 1: im = im.resize((256 * scale, 224 * scale), Image.NEAREST)
        if path: im.save(path)
        return im
