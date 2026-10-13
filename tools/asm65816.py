"""Tiny two-pass 65816 assembler.
Syntax per line:  [label:] MNEMONIC [operand] [; comment]
Operands: #imm  $dp  $abs  $long  label  label,X  (dp),Y  [dp],Y  dp,S ...
Size rules: hex literal width decides dp/abs/long ($12 / $1234 / $123456).
Labels default to abs (16-bit); prefix with '>' for long (24-bit).
Immediate size follows tracked M/X state (REP/SEP), override with .m8/.m16/.x8/.x16 directives.
Directives: .org $addr24 ; .db b,b ; .dw w,w ; .dl l
Expressions: +,- of numbers/labels, and low/high/bank via <label >label ^label not needed.
"""
import re
from dis65816 import T, SZ

REV = {}
for code, (name, mode) in T.items():
    REV[(name, mode)] = code

def num(tok, labels, pass2):
    tok = tok.strip()
    # simple expression with + and -
    parts = re.split(r'(?=[+-])', tok)
    total = 0; width = 0
    for p in parts:
        p = p.strip()
        if not p: continue
        sign = 1
        if p[0] in '+-':
            sign = -1 if p[0] == '-' else 1; p = p[1:].strip()
        if p.startswith('$'):
            v = int(p[1:], 16); w = (len(p) - 1 + 1) // 2
        elif p.startswith('%'):
            v = int(p[1:], 2); w = 1
        elif p[0].isdigit():
            v = int(p); w = 1 if v < 256 else 2
        else:
            if p in labels: v = labels[p]
            elif pass2: raise Exception('undefined label ' + p)
            else: v = 0
            w = 4  # label marker
        total += sign * v
        width = max(width, w)
    return total, width

class Asm:
    def __init__(self):
        self.labels = {}

    def assemble(self, src):
        for pass2 in (False, True):
            out = {}  # addr -> bytes
            pc = 0; m = 1; x = 1
            for lineno, raw in enumerate(src.split('\n'), 1):
                line = raw.split(';')[0].rstrip()
                if not line.strip(): continue
                mlab = re.match(r'^\s*([A-Za-z_.][\w.]*):', line)
                if mlab:
                    lab = mlab.group(1)
                    if not pass2:
                        if lab in self.labels: raise Exception('dup label %s' % lab)
                        self.labels[lab] = pc
                    line = line[mlab.end():]
                line = line.strip()
                if not line: continue
                try:
                    pc, m, x = self.line(line, pc, m, x, out, pass2)
                except Exception as e:
                    raise Exception('line %d: %s: %s' % (lineno, raw, e))
        return out

    def emit(self, out, pc, bs):
        out[pc] = out.get(pc, b'') + bytes(bs)  # store per-start
        return pc + len(bs)

    def line(self, line, pc, m, x, out, pass2):
        L = self.labels
        if line.startswith('.'):
            d, _, rest = line.partition(' ')
            if d == '.org': pc = num(rest, L, pass2)[0]; return pc, m, x
            if d == '.m8': return pc, 1, x
            if d == '.m16': return pc, 0, x
            if d == '.x8': return pc, m, 1
            if d == '.x16': return pc, m, 0
            if d in ('.db', '.dw', '.dl'):
                n = {'.db': 1, '.dw': 2, '.dl': 3}[d]
                bs = []
                for t in rest.split(','):
                    v = num(t, L, pass2)[0]
                    bs += list((v & ((1 << (8 * n)) - 1)).to_bytes(n, 'little'))
                return self.emit(out, pc, bs), m, x
            if d == '.ascii':
                s = rest.strip().strip('"')
                return self.emit(out, pc, [c - 0x20 for c in s.encode()]), m, x
            raise Exception('bad directive ' + d)
        mn, _, op = line.partition(' ')
        mn = mn.upper(); op = op.strip()
        force_long = False
        if mn.endswith('.L'): mn = mn[:-2]; force_long = True
        if not op:
            mode = 'imp'
            if mn in ('ASL', 'LSR', 'ROL', 'ROR', 'INC', 'DEC') and (mn, 'imp') in REV: pass
            code = REV[(mn, 'imp')]
            return self.emit(out, pc, [code]), m, x
        if mn in ('BPL', 'BMI', 'BVC', 'BVS', 'BCC', 'BCS', 'BNE', 'BEQ', 'BRA'):
            tgt = num(op, L, pass2)[0]
            off = (tgt & 0xffff) - ((pc + 2) & 0xffff)
            if pass2 and not -128 <= off <= 127: raise Exception('branch out of range %d' % off)
            return self.emit(out, pc, [REV[(mn, 'rel')], off & 0xff]), m, x
        if mn in ('BRL', 'PER'):
            tgt = num(op, L, pass2)[0]
            off = (tgt & 0xffff) - ((pc + 3) & 0xffff)
            return self.emit(out, pc, [REV[(mn, 'rell')], off & 0xff, (off >> 8) & 0xff]), m, x
        if mn in ('MVN', 'MVP'):
            a, b = op.split(',')
            return self.emit(out, pc, [REV[(mn, 'bm')], num(a, L, pass2)[0], num(b, L, pass2)[0]]), m, x
        if op.startswith('#'):
            v, w = num(op[1:], L, pass2)
            if mn in ('REP', 'SEP', 'BRK', 'COP', 'WDM'):
                if mn == 'REP':
                    if v & 0x20: m = 0
                    if v & 0x10: x = 0
                if mn == 'SEP':
                    if v & 0x20: m = 1
                    if v & 0x10: x = 1
                return self.emit(out, pc, [REV[(mn, 'imm8')], v & 0xff]), m, x
            if (mn, 'immm') in REV:
                n = 1 if m else 2; code = REV[(mn, 'immm')]
            else:
                n = 1 if x else 2; code = REV[(mn, 'immx')]
            return self.emit(out, pc, [code] + list((v & ((1 << (8 * n)) - 1)).to_bytes(n, 'little'))), m, x
        # addressing modes
        pats = [
            (r'^\((.+),X\)$', 'idx', 'iax'),
            (r'^\((.+),S\),Y$', 'sry', None),
            (r'^\((.+)\),Y$', 'idy', None),
            (r'^\[(.+)\],Y$', 'idly', None),
            (r'^\((.+)\)$', 'idp', 'ind'),
            (r'^\[(.+)\]$', 'idl', 'ial'),
            (r'^(.+),S$', 'sr', None),
            (r'^(.+),X$', 'dpx', 'abx', 'alx'),
            (r'^(.+),Y$', 'dpy', 'aby'),
            (r'^(.+)$', 'dp', 'abs', 'abl'),
        ]
        for p in pats:
            mm = re.match(p[0], op, re.I)
            if not mm: continue
            expr = mm.group(1)
            longlab = expr.startswith('>')
            if longlab: expr = expr[1:]
            v, w = num(expr, L, pass2)
            if w == 4: w = 3 if (longlab or force_long or mn in ('JML', 'JSL')) else 2
            if mn in ('JML', 'JSL') and p[1] == 'dp': w = 3
            if mn in ('JMP', 'JSR') and p[1] == 'dp': w = max(w, 2)
            if mn == 'JMP' and p[1] == 'idp': w = 2
            if mn == 'JMP' and p[1] == 'idl': w = 2
            if mn in ('JMP', 'JSR') and p[1] == 'idx': w = 2
            if mn == 'PEA': w = 2
            if mn == 'PEI': w = 1
            if force_long: w = 3
            cands = [c for c in p[1:] if c]
            # choose by width
            order = {1: 0, 2: 1, 3: 2}
            mode = None
            for i in range(order[min(w, 3)], len(cands)):
                if (mn, cands[i]) in REV: mode = cands[i]; break
            if mode is None:
                for c in cands:
                    if (mn, c) in REV: mode = c; break
            if mode is None: raise Exception('no mode for %s %s' % (mn, op))
            n = SZ[mode]
            if mn == 'PEA': mode = 'abs'
            return self.emit(out, pc, [REV[(mn, mode)]] + list((v & ((1 << (8 * n)) - 1)).to_bytes(n, 'little'))), m, x
        raise Exception('cannot parse')

def lorom_off(addr):
    return ((addr >> 16) & 0x7f) * 0x8000 + (addr & 0x7fff)

def apply(rom, out):
    for a, bs in out.items():
        o = lorom_off(a)
        rom[o:o + len(bs)] = bs
