import sys
ROM = b''

def load(path):
    global ROM
    ROM = open(path, 'rb').read()

def lorom(addr):
    bank = (addr >> 16) & 0x7f
    off = addr & 0xffff
    if off < 0x8000:
        return None
    return bank * 0x8000 + (off - 0x8000)

# opcode table: name, mode
# modes: imp, immm (depends M), immx (depends X), imm8, dp, dpx, dpy, idp, idx, idy, idl, idly, sr, sry, abs, abx, aby, abl, alx, ind, iax, ial, rel, rell, bm (block move)
T = {}
def op(code, name, mode): T[code] = (name, mode)
groups = {
 'ORA':0x00,'AND':0x20,'EOR':0x40,'ADC':0x60,'STA':0x80,'LDA':0xA0,'CMP':0xC0,'SBC':0xE0}
for n,b in groups.items():
    for o,m in [(0x01,'idx'),(0x03,'sr'),(0x05,'dp'),(0x07,'idl'),(0x09,'immm'),(0x0D,'abs'),(0x0F,'abl'),
                (0x11,'idy'),(0x12,'idp'),(0x13,'sry'),(0x15,'dpx'),(0x17,'idly'),(0x19,'aby'),(0x1D,'abx'),(0x1F,'alx')]:
        if n=='STA' and o==0x09: continue
        op(b+o,n,m)
op(0x89,'BIT','immm')
misc = """00 BRK imm8;02 COP imm8;04 TSB dp;06 ASL dp;08 PHP imp;0A ASL imp;0B PHD imp;0C TSB abs;0E ASL abs;
10 BPL rel;14 TRB dp;16 ASL dpx;18 CLC imp;1A INC imp;1B TCS imp;1C TRB abs;1E ASL abx;
20 JSR abs;22 JSL abl;24 BIT dp;26 ROL dp;28 PLP imp;2A ROL imp;2B PLD imp;2C BIT abs;2E ROL abs;
30 BMI rel;34 BIT dpx;36 ROL dpx;38 SEC imp;3A DEC imp;3B TSC imp;3C BIT abx;3E ROL abx;
40 RTI imp;42 WDM imm8;44 MVP bm;46 LSR dp;48 PHA imp;4A LSR imp;4B PHK imp;4C JMP abs;4E LSR abs;
50 BVC rel;54 MVN bm;56 LSR dpx;58 CLI imp;5A PHY imp;5B TCD imp;5C JML abl;5E LSR abx;
60 RTS imp;62 PER rell;64 STZ dp;66 ROR dp;68 PLA imp;6A ROR imp;6B RTL imp;6C JMP ind;6E ROR abs;
70 BVS rel;74 STZ dpx;76 ROR dpx;78 SEI imp;7A PLY imp;7B TDC imp;7C JMP iax;7E ROR abx;
80 BRA rel;82 BRL rell;84 STY dp;86 STX dp;88 DEY imp;8A TXA imp;8B PHB imp;8C STY abs;8E STX abs;
90 BCC rel;94 STY dpx;96 STX dpy;98 TYA imp;9A TXS imp;9B TXY imp;9C STZ abs;9E STZ abx;
A0 LDY immx;A2 LDX immx;A4 LDY dp;A6 LDX dp;A8 TAY imp;AA TAX imp;AB PLB imp;AC LDY abs;AE LDX abs;
B0 BCS rel;B4 LDY dpx;B6 LDX dpy;B8 CLV imp;BA TSX imp;BB TYX imp;BC LDY abx;BE LDX aby;
C0 CPY immx;C2 REP imm8;C4 CPY dp;C6 DEC dp;C8 INY imp;CA DEX imp;CB WAI imp;CC CPY abs;CE DEC abs;
D0 BNE rel;D4 PEI dp;D6 DEC dpx;D8 CLD imp;DA PHX imp;DB STP imp;DC JML ial;DE DEC abx;
E0 CPX immx;E2 SEP imm8;E4 CPX dp;E6 INC dp;E8 INX imp;EA NOP imp;EB XBA imp;EC CPX abs;EE INC abs;
F0 BEQ rel;F4 PEA abs;F6 INC dpx;F8 SED imp;FA PLX imp;FB XCE imp;FC JSR iax;FE INC abx"""
for item in misc.replace('\n','').split(';'):
    c,n,m = item.split()
    op(int(c,16),n,m)
assert len(T)==256, len(T)

FMT = {'imp':'','imm8':'#${:02X}','dp':'${:02X}','dpx':'${:02X},X','dpy':'${:02X},Y','idp':'(${:02X})','idx':'(${:02X},X)',
 'idy':'(${:02X}),Y','idl':'[${:02X}]','idly':'[${:02X}],Y','sr':'${:02X},S','sry':'(${:02X},S),Y','abs':'${:04X}',
 'abx':'${:04X},X','aby':'${:04X},Y','abl':'${:06X}','alx':'${:06X},X','ind':'(${:04X})','iax':'(${:04X},X)','ial':'[${:04X}]'}
SZ = {'imp':0,'imm8':1,'dp':1,'dpx':1,'dpy':1,'idp':1,'idx':1,'idy':1,'idl':1,'idly':1,'sr':1,'sry':1,
      'abs':2,'abx':2,'aby':2,'abl':3,'alx':3,'ind':2,'iax':2,'ial':2,'rel':1,'rell':2,'bm':2}

def dis(addr, count=40, m=1, x=1, stop=True):
    out=[]
    for _ in range(count):
        o = lorom(addr)
        b = ROM[o]
        name, mode = T[b]
        if mode=='immm': n = 1 if m else 2
        elif mode=='immx': n = 1 if x else 2
        else: n = SZ[mode]
        arg = int.from_bytes(ROM[o+1:o+1+n],'little')
        pc = addr & 0xffff
        if mode in ('immm','immx'): s = '#$%0*X' % (n*2, arg)
        elif mode=='rel': s = '$%04X' % ((pc+2+(arg-256 if arg>127 else arg)) & 0xffff)
        elif mode=='rell': s = '$%04X' % ((pc+3+(arg-65536 if arg>32767 else arg)) & 0xffff)
        elif mode=='bm': s = '$%02X,$%02X' % (arg & 0xff, arg>>8)
        else: s = FMT[mode].format(arg)
        if name=='REP':
            if arg & 0x20: m=0
            if arg & 0x10: x=0
        if name=='SEP':
            if arg & 0x20: m=1
            if arg & 0x10: x=1
        hexb = ROM[o:o+1+n].hex(' ')
        out.append('%02X:%04X  %-12s %s %s' % (addr>>16, pc, hexb, name, s))
        addr = (addr & 0xff0000) | ((pc + 1 + n) & 0xffff)
        if stop and name in ('RTS','RTL','RTI','JMP','JML','BRA','BRL','STP'):
            out.append('---')
            if stop is True: break
    return '\n'.join(out)

if __name__ == '__main__':
    if len(sys.argv) < 3:
        sys.exit('usage: dis65816.py ROM.sfc ADDR [COUNT] [M] [X] [stop]   e.g. dis65816.py rap.sfc 808000 60')
    load(sys.argv[1]); sys.argv = sys.argv[1:]
    a = int(sys.argv[1],16); c = int(sys.argv[2]) if len(sys.argv)>2 else 60
    m = int(sys.argv[3]) if len(sys.argv)>3 else 1
    x = int(sys.argv[4]) if len(sys.argv)>4 else 1
    st = sys.argv[5] if len(sys.argv)>5 else '1'
    print(dis(a,c,m,x, True if st=='1' else 'cont'))
