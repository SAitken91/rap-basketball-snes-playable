; ===================================================================
; Rap Basketball (Proto) - "playable" patch
;   B  = shoot (2 pts, 3 pts from long range)
;   Y  = steal attempt
;   A  = pass/throw (now only when you hold the ball)
;   X  = run (original)
;   Clock counts down from 3:00, live scores, CPU controls ICE T
;   unless controller 2 is used.
; Variables live in free WRAM $1000-$104F.
; ===================================================================

; ---------------- hooks into original code -------------------------
.org $8080BD
        JSL my_pads                 ; was JSL $80A80F (read joypads)

.org $809E5E
        JSR pass_check              ; was LDA $09EF (A = throw ball)

.org $91F085
        .dw my_ball                 ; ball object update (was $9B10)

.org $9680D9                        ; mode table entry 2 (gameplay)
        .dw my_init
        .db $80
        .dl my_nmi                  ; $11 hook (was RTL at $9AAB)
        .dl my_frame                ; $14 hook (was $9AAC)

; ---------------- new code ------------------------------------------
.org $80B000
.m16
.x16

; constants
; hoop target (ground x,y and rim height z)
; HX=$0178 HY=$00DC HZ=$0064

; ---- RAM ----
; $1000 shot_active  $1002 shot_t    $1004 bx  $1006 by  $1008 bz
; $100A vx  $100C vy  $100E vz  $1010 shooter  $1012 make  $1014 points
; $1016 scoreA (KOOL J, P1 slot 6)   $1018 scoreB (ICE T, slot 4)
; $101A clock secs  $101C clock frames  $101E hud_dirty  $1020 game_over
; $1022 check timer  $1024 check_to  $1026 p2_human  $1028 started
; $1034 steal cd slot4  $1036 steal cd slot6  $1038 ai hold timer
; $103A ai tx  $103C ai ty  $1042 rng  $1044 tmp  $1046 tmp2  $1048 dist
; $104A ai_new  $104C ai_held

; -------------------------------------------------------------------
my_init:
        JSL $80989F                 ; original gameplay init
        REP #$30
        LDX #$004E
mi_clr: STZ $1000,X
        DEX
        DEX
        BPL mi_clr
        LDA #$00B4                  ; 3:00
        STA $101A
        LDA #$003C
        STA $101C
        LDA #$1234
        STA $1042
        LDA $03FE+4                 ; ICE T's team uses sprite palette 1
        ORA #$0200
        STA $03FE+4
        LDA $03FE+8
        ORA #$0200
        STA $03FE+8
        RTL

; -------------------------------------------------------------------
rng:    ; returns A = new 16-bit random
        LDA $1042
        ASL
        ASL
        CLC
        ADC $1042
        CLC
        ADC #$3711
        EOR $0290
        STA $1042
        RTS

; -------------------------------------------------------------------
; A-button pass only allowed when this player (X) holds the ball
pass_check:
        CPX $09F1
        BNE pc_no
        LDA $09EF
        RTS
pc_no:  LDA #$0000
        RTS

; -------------------------------------------------------------------
; joypad read + CPU control of slot 4
my_pads:
        JSL $80A80F
        REP #$30
        LDA $1026
        BNE mp_ret
        LDA $06
        BEQ mp_ai
        LDA #$0001                  ; someone touched pad 2 -> human P2
        STA $1026
mp_ret: RTL
mp_idle: BRL mp_out
mp_ai:  STZ $104A
        STZ $104C
        LDA $1020
        BNE mp_idle                 ; game over: idle
        LDA $1028
        BEQ mp_idle
        LDA $1022
        BNE mp_idle                 ; waiting for check-ball
        LDA $1000
        BEQ mp_noshot
        ; ball in the air: crash the boards
        LDA #$0150
        STA $103A
        LDA #$00DC
        STA $103C
        STZ $1038
        BRL mp_move
mp_noshot:
        LDA $09F1
        CMP #$0004
        BNE mp_nothold
        ; ---- CPU has the ball ----
        LDA $1038
        BNE mp_h1
        JSR rng                     ; pick a shooting spot
        AND #$003F
        EOR #$FFFF
        SEC
        ADC #$0118                  ; x = $118 - (0..63)
        STA $103A
        JSR rng
        AND #$003F
        CLC
        ADC #$00BE                  ; y = $BE..$FD
        STA $103C
mp_h1:  INC $1038
        LDA $1038
        CMP #$00B4                  ; held 3s -> shoot anyway
        BCS mp_shoot
        LDA $039E+4
        SEC
        SBC $103A
        BPL mp_h2
        EOR #$FFFF
        INC
mp_h2:  CMP #$0008
        BCS mp_movj
        LDA $03BE+4
        SEC
        SBC $103C
        BPL mp_h3
        EOR #$FFFF
        INC
mp_h3:  CMP #$0008
        BCS mp_movj
        LDA $1038
        CMP #$0020
        BCC mp_movj
mp_shoot:
        LDA #$8000
        STA $104A
        BRL mp_out
mp_movj: BRL mp_move
mp_nothold:
        STZ $1038
        CMP #$0006
        BNE mp_free
        ; ---- P1 has the ball: defend / steal ----
        LDA $039E+6
        CLC
        ADC #$0014                  ; stay between P1 and hoop
        STA $103A
        LDA $03BE+6
        STA $103C
        LDA $1034
        BNE mp_move
        LDA $039E+6
        SEC
        SBC $039E+4
        BPL mp_d1
        EOR #$FFFF
        INC
mp_d1:  CMP #$001C
        BCS mp_move
        LDA $03BE+6
        SEC
        SBC $03BE+4
        BPL mp_d2
        EOR #$FFFF
        INC
mp_d2:  CMP #$0010
        BCS mp_move
        JSR rng
        AND #$000F
        BNE mp_move
        LDA #$4000                  ; Y = steal
        STA $104A
        BRA mp_move
mp_free:
        ; ---- loose ball: chase it ----
        LDA $039E
        STA $103A
        LDA $03BE
        STA $103C
mp_move:
        LDX #$0000
        LDA $103A
        SEC
        SBC $039E+4
        STA $1044
        BPL mp_m1
        EOR #$FFFF
        INC
mp_m1:  STA $1048
        CMP #$0003
        BCC mp_m3
        LDX #$0100                  ; right
        LDA $1044
        BPL mp_m3
        LDX #$0200                  ; left
mp_m3:  STX $104C
        LDX #$0000
        LDA $103C
        SEC
        SBC $03BE+4
        STA $1044
        BPL mp_m4
        EOR #$FFFF
        INC
mp_m4:  PHA
        CLC
        ADC $1048
        STA $1048
        PLA
        CMP #$0003
        BCC mp_m6
        LDX #$0400                  ; down
        LDA $1044
        BPL mp_m6
        LDX #$0800                  ; up
mp_m6:  TXA
        ORA $104C
        STA $104C
        LDA $1048
        CMP #$0040
        BCC mp_out
        LDA $104C
        ORA #$0040                  ; run when far
        STA $104C
mp_out: LDA $104C
        ORA $104A
        STA $06
        LDA $104A
        STA $0A
        RTL

; -------------------------------------------------------------------
; per-frame game rules (after objects update)
my_frame:
        JSL $809AAC                 ; original (Start -> logos)
        REP #$30
        LDA $1028
        BNE mf_go
        LDA #$0001
        STA $1028
        STA $101E
mf_go:  LDA $1020
        BEQ mf_live
        RTL
mf_live:
        ; ---- clock ----
        DEC $101C
        BNE mf_c1
        LDA #$003C
        STA $101C
        LDA #$0001
        STA $101E
        DEC $101A
        BNE mf_c1
        LDA #$0001
        STA $1020                   ; time up
        STZ $1000
        RTL
mf_c1:  ; ---- cooldowns ----
        LDA $1034
        BEQ mf_c2
        DEC $1034
mf_c2:  LDA $1036
        BEQ mf_c3
        DEC $1036
mf_c3:  ; ---- check ball after a basket ----
        LDA $1022
        BEQ mf_c4
        DEC $1022
        BNE mf_c4
        JSR check_ball
mf_c4:  ; ---- player 1 (slot 6) ----
        LDX #$0006
        LDA $08
        JSR player_btn
        ; ---- player 2 / CPU (slot 4) ----
        LDX #$0004
        LDA $0A
        JSR player_btn
        RTL

; X = slot, A = new buttons
player_btn:
        STA $1046
        LDA $1022
        BNE pb_ret
        LDA $1046
        BIT #$8000                  ; B = shoot
        BEQ pb_steal
        CPX $09F1
        BNE pb_steal
        LDA $1000
        BNE pb_steal
        JMP start_shot
pb_steal:
        LDA $1046
        BIT #$4000                  ; Y = steal
        BEQ pb_ret
        LDA $1030,X
        BNE pb_ret
        LDA $09F1
        BMI pb_ret
        STA $1044                   ; holder
        CPX $1044
        BEQ pb_ret
        LDA #$001E
        STA $1030,X                 ; attempt cooldown
        LDY $1044
        LDA $039E,X
        SEC
        SBC $039E,Y
        BPL ps1
        EOR #$FFFF
        INC
ps1:    CMP #$0020
        BCS pb_ret
        LDA $03BE,X
        SEC
        SBC $03BE,Y
        BPL ps2
        EOR #$FFFF
        INC
ps2:    CMP #$0014
        BCS pb_ret
        JSR rng
        AND #$0003
        BEQ pb_ret                  ; 25% fail
        STX $09F1                   ; stolen!
        LDA #$0030
        STA $1030,X
        STA $1030,Y
pb_ret: RTS

; X = shooter slot
start_shot:
        STX $1010
        LDA #$FFFF
        STA $09F1
        STX $09F3
        STZ $078C
        STZ $07AC
        STZ $094C
        STZ $096C
        ; start position (ball, released overhead)
        LDA $039E
        ASL
        ASL
        ASL
        ASL
        STA $1004
        LDA $03BE
        ASL
        ASL
        ASL
        ASL
        STA $1006
        LDA #$0300                  ; z = 48
        STA $1008
        ; dist = |dx| + |dy|/2
        LDA #$0180
        SEC
        SBC $039E
        BPL ss1
        EOR #$FFFF
        INC
ss1:    STA $1048
        LDA #$00DC
        SEC
        SBC $03BE
        BPL ss2
        EOR #$FFFF
        INC
ss2:    LSR
        CLC
        ADC $1048
        STA $1048
        ; points
        LDY #$0002
        CMP #$00AA
        BCC ss3
        LDY #$0003
ss3:    STY $1014
        ; flight time T = 30 + dist/16 (max 70)
        LSR
        LSR
        LSR
        LSR
        CLC
        ADC #$001E
        CMP #$0046
        BCC ss4
        LDA #$0046
ss4:    STA $1002
        ; make chance
        LDY #$00DA
        LDA $1048
        CMP #$003C
        BCC ss5
        LDY #$00A6
        CMP #$0078
        BCC ss5
        LDY #$0080
        CMP #$00AA
        BCC ss5
        LDY #$005A
ss5:    STY $1044
        STZ $1012
        JSR rng
        AND #$00FF
        CMP $1044
        BCS ss6
        INC $1012
ss6:    ; vx = (HX*16 - bx) / T
        LDA #$1800
        SEC
        SBC $1004
        JSR sdiv
        STA $100A
        LDA #$0DC0
        SEC
        SBC $1006
        JSR sdiv
        STA $100C
        ; vz = (HZ*16 - bz)/T + 3*T/2
        LDA #$0640
        SEC
        SBC $1008
        JSR sdiv
        STA $1044
        LDA $1002
        ASL
        CLC
        ADC $1002
        LSR
        CLC
        ADC $1044
        STA $100E
        LDA #$0001
        STA $1000
        RTS

; signed A / T(=$1002) -> A
sdiv:   PHP
        STZ $1046
        CMP #$0000
        BPL sd1
        EOR #$FFFF
        INC
        INC $1046
sd1:    STA $4204
        SEP #$20
        LDA $1002
        STA $4206
        REP #$20
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        LDA $4214
        LDY $1046
        BEQ sd2
        EOR #$FFFF
        INC
sd2:    PLP
        RTS

; give the ball to the team that got scored on
check_ball:
        LDX $1024
        STX $09F1
        STZ $09F5
        STZ $1000
        LDA #$00C0
        STA $039E,X
        LDA #$00DC
        STA $03BE,X
        LDA #$00A0                  ; AI teammate
        STA $03A2,X
        LDA #$0108
        STA $03C2,X
        RTS

; -------------------------------------------------------------------
; ball object update
my_ball:
        LDA $1000
        BNE mb_shot
        JMP $9B10
mb_shot:
        LDA $1004
        CLC
        ADC $100A
        STA $1004
        LDA $1006
        CLC
        ADC $100C
        STA $1006
        LDA $1008
        CLC
        ADC $100E
        STA $1008
        LDA $100E
        SEC
        SBC #$0003
        STA $100E
        LDA $1004
        LSR
        LSR
        LSR
        LSR
        STA $039E
        LDA $1006
        LSR
        LSR
        LSR
        LSR
        STA $03BE
        LDA $1008
        BPL mb1
        LDA #$0000
mb1:    LSR
        LSR
        LSR
        LSR
        STA $03DE
        DEC $1002
        BNE mb_done
        JSR finish_shot
mb_done:
        JMP $9BC5

finish_shot:
        STZ $1000
        LDA #$0180
        STA $039E
        LDA #$00DC
        STA $03BE
        LDA #$0064
        STA $03DE
        LDA #$FFC0
        STA $096C
        LDA #$0800
        STA $098C
        STA $07CC
        LDA $1012
        BEQ fs_miss
        ; ---- swish ----
        STZ $094C
        STZ $078C
        LDA #$0028
        STA $09F5
        LDA $1010
        CMP #$0006
        BEQ fs_a
        LDA $1018
        CLC
        ADC $1014
        STA $1018
        LDA #$0006
        BRA fs_b
fs_a:   LDA $1016
        CLC
        ADC $1014
        STA $1016
        LDA #$0004
fs_b:   STA $1024
        LDA #$0046
        STA $1022
        LDA #$0001
        STA $101E
        JSL $80A3EA                 ; sfx
        RTS
fs_miss:
        JSR rng
        AND #$00FF
        CLC
        ADC #$0180
        STA $078C
        JSR rng
        AND #$003F
        CLC
        ADC #$00A0
        STA $07EC
        LDA #$FFFC
        STA $07AC
        LDA #$0280
        STA $094C
        LDA #$000A
        STA $09F5
        JSL $80A3B1                 ; sfx (rim)
        RTS

; -------------------------------------------------------------------
; NMI hook: redraw HUD when dirty (VRAM word $6400 = BG3 map)
my_nmi:
        REP #$30
        LDA $1028
        BEQ mn_nopal
        SEP #$20
        LDA #$90                    ; CGRAM OBJ palette 1
        STA $2121
        REP #$20
        LDX #$0000
mn_p1:  LDA >pal_teamb,X
        SEP #$20
        STA $2122
        XBA
        STA $2122
        REP #$20
        INX
        INX
        CPX #$0020
        BCC mn_p1
mn_nopal:
        LDA $101E
        BNE mn_go
        RTL
mn_go:  STZ $101E
        SEP #$20
        LDA #$80
        STA $2115
        REP #$20
        LDA $1016
        LDX #$6724                  ; row 25 col 4
        LDY #$0000
        JSR draw2
        LDA $1018
        LDX #$673A                  ; row 25 col 26
        LDY #$0000
        JSR draw2
        ; clock m:ss
        LDA $101A
        STA $4204
        SEP #$20
        LDA #$3C
        STA $4206
        REP #$20
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        LDA $4216
        PHA
        LDA $4214
        LDX #$64AD                  ; row 5 col 13 (" m")
        LDY #$0000
        JSR draw2
        PLA
        LDX #$64B0                  ; row 5 col 16
        LDY #$0001
        JSR draw2
        LDA $1020
        BEQ mn_ret
        ; game over text
        LDA #$658B                  ; row 12 col 11
        STA $2116
        LDX #txt_over
mn_t1:  LDA $800000,X
        AND #$00FF
        CMP #$00FF
        BEQ mn_t2
        ORA #$3C00
        STA $2118
        INX
        BRA mn_t1
mn_t2:  LDA $1016
        CMP $1018
        BEQ mn_tie
        BCC mn_b
        LDY #txt_kool
        BRA mn_t3
mn_b:   LDY #txt_ice
        BRA mn_t3
mn_tie: LDY #txt_tie
mn_t3:  LDA #$65CA                  ; row 14 col 10
        STA $2116
        TYX
mn_t4:  LDA $800000,X
        AND #$00FF
        CMP #$00FF
        BEQ mn_ret
        ORA #$3C00
        STA $2118
        INX
        BRA mn_t4
mn_ret: RTL

; A = value 0..99, X = vram word addr of top-left, Y=1 -> keep leading zero
draw2:  STY $1046
        STX $1044
        STA $4204
        SEP #$20
        LDA #$0A
        STA $4206
        REP #$20
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        LDA $4214                   ; tens
        TAY
        LDA $4216                   ; ones
        STA $1048
        LDA $1044
        STA $2116
        TYA
        BNE d2_t
        LDA $1046
        BNE d2_t
        STZ $2118                   ; blank tens
        BRA d2_o
d2_t:   TYA
        CLC
        ADC #$3C3D
        STA $2118
d2_o:   LDA $1048
        CLC
        ADC #$3C3D
        STA $2118
        LDA $1044
        CLC
        ADC #$0020
        STA $2116
        TYA
        BNE d2_tb
        LDA $1046
        BNE d2_tb
        STZ $2118
        BRA d2_ob
d2_tb:  TYX
        LDA >digit_bot,X
        AND #$00FF
        ORA #$3C00
        STA $2118
d2_ob:  LDX $1048
        LDA >digit_bot,X
        AND #$00FF
        ORA #$3C00
        STA $2118
        RTS

pal_teamb:
        .dw $7C1F,$1D79,$1934,$1512,$14EF,$10CD,$0888,$7EEB
        .dw $65E0,$4D60,$139F,$0A98,$023B,$1CE7,$2D5F,$7FFF
digit_bot:
        .db $47,$48,$49,$4A,$58,$4C,$4D,$4E,$4F,$50
txt_over:
        .ascii "GAME OVER"
        .db $FF
txt_kool:
        .ascii " KOOL J WINS"
        .db $FF
txt_ice:
        .ascii "  ICE T WINS"
        .db $FF
txt_tie:
        .ascii "  TIE GAME"
        .db $FF
