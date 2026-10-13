import sys
from emu import SNES
from ppu import Renderer
from PIL import Image
def w16(s,a): return s.wram[a]|s.wram[a+1]<<8
def s16(v): return v-65536 if v>32767 else v
def chase(s, me=6, target=0, pad=1):
    bx,by=w16(s,0x39e+target),w16(s,0x3be+target); px,py=w16(s,0x39e+me),w16(s,0x3be+me)
    j=0
    if bx>px+2: j|=0x100
    elif bx<px-2: j|=0x200
    if by>py+2: j|=0x400
    elif by<py-2: j|=0x800
    return j
def sheet(imgs,out,cols=4):
    rows=(len(imgs)+cols-1)//cols
    sh=Image.new('RGB',(256*cols,224*rows))
    for i,im in enumerate(imgs): sh.paste(im,((i%cols)*256,(i//cols)*224))
    sh.save(out)
if __name__=='__main__':
    if len(sys.argv) < 2: sys.exit('usage: bot.py ROM.sfc   (plays 700 frames, writes bot.png)')
    s=SNES(open(sys.argv[1],'rb').read()); r=Renderer(s)
    imgs=[]
    for f in range(700):
        s.joy=0
        if f>200: s.joy=chase(s)
        if f in (450,451,452): s.joy|=0x80
        s.run_frame()
        if f%20==0 and f>=200:
            print(f, 'ball',w16(s,0x39e),w16(s,0x3be),w16(s,0x3de),'p1',w16(s,0x3a4),w16(s,0x3c4),'holder',hex(w16(s,0x9f1)), 'f5',w16(s,0x9f5))
        if f in (260,320,380,440,455,470,500,600): imgs.append(r.render(scale=1))
    sheet(imgs,'bot.png')
