# Rap Basketball (Proto) – Technical Notes

These are my notes from reverse-engineering the prototype. All addresses are SNES LoROM addresses (`bank:addr`). "Slot" means an index into the object tables (0, 2, 4 … `$1E`).

## ROM overview

| | |
|---|---|
| Mapping | LoROM, FastROM (`$30`), 1 MiB, no SRAM, no coprocessor |
| Internal title | `TOYS` |
| Reset vector | `$80:8005` (through a `JML` stub at `$FFE0`) |
| NMI / IRQ | `$80:A851` / `$80:A826` |

Most of the ROM is empty. Only 9 of the 32 banks contain data:

| Bank | Used | Contents |
|---|---|---|
| `$80` | `$8000–$A8DF` | All game code (~10.5 KB). `$A8E0–$FFAF` is free; the patch lives at `$80:B000` |
| `$81` | `$8000–$847F` | Lookup tables (sin/cos), script opcode table, sprite tables |
| `$82` | `$8000–$838F` | Data |
| `$87`, `$88` | | Compressed graphics, palettes |
| `$90`, `$91` | | Sprite graphics, object descriptors, hitboxes (`$91:F09A`) |
| `$96` | | "TOYS Code Version 2.6" message, game mode table (`$96:80B5`) |
| `$9E`, `$9F` | | Sound driver (SPC700) and music/sample data |

## Boot and main loop

1. The reset code at `$80:8005` clears WRAM, initialises the PPU (`$80:A74B`), clears VRAM and OAM, uploads the SPC700 driver from bank `$9E`, and enables NMI.
2. `$80:A89D` starts a **game mode**. `$09B6` is the mode index into an 18-byte-per-entry table at `$96:80B5`:
   - bytes 0–2: init routine. It's jumped to using a push-and-`RTL` trick.
   - bytes 3–17: five 24-bit pointers copied to direct page `$11, $14, $17, $1A, $1D`. These are called with `JML [$xx]`:
     - `$11`: NMI hook (called from the NMI handler before OAM DMA)
     - `$14`: per-frame logic (main loop, after objects update)
     - `$17`: second NMI hook
     - `$1A`: IRQ hook
   - Mode 0 is the Bonsai logo, mode 2 is gameplay (init `$80:989F`, hooks `$9AAB/$9AAC/$9ABE/$9ABF`). The gameplay NMI hook was an empty `RTL`, which made it a convenient place for the HUD code.
3. Main loop (`$80:80A3`): wait for vblank (`$80:A7FD`), update RNG (`$80:A7E6` → `$02`), read controllers (`$80:A80F`), check pause (`$80:8132`), update objects (`$80:94EE`), then `JML [$14]`.

### Controllers
`$80:A80F` reads auto-joypad:

| | Pad 1 | Pad 2 |
|---|---|---|
| Held | `$04` | `$06` |
| Newly pressed | `$08` | `$0A` |

## Object system

There are 16 object slots (X = `$00`–`$1E`, step 2), stored as parallel 16-bit arrays:

| Array | Meaning |
|---|---|
| `$039E,X` | world X |
| `$03BE,X` | world Y (depth on the court) |
| `$03DE,X` | Z (height) |
| `$03FE,X` | OAM attributes (flip / priority / palette / VRAM slot) |
| `$043E,X` / `$045E,X` | update routine (16-bit address + bank) |
| `$047E–$04DE,X` | per-object scratch (AI targets, edit-mode flags) |
| `$04FE,X` | facing (0–14, 8 directions × 2) |
| `$051E,X` | walk-cycle counter |
| `$057E,X` | flags (bit 0 = active) |
| `$067A,X` | animation frame |
| `$078C,X` | horizontal speed (8.8) |
| `$07AC,X` | horizontal acceleration / friction |
| `$07CC,X` | max speed |
| `$07EC,X` | heading angle (`$00` = up, `$40` = right, `$80` = down, `$C0` = left) |
| `$094C,X` | vertical speed (8.8) |
| `$096C,X` | gravity (`$FFC0` for the ball) |
| `$098C,X` | terminal velocity |

Objects are created by `$80:8CBE` (A = descriptor address, Y = bank, X = slot) from 12-byte descriptors in bank `$91`:

| Descriptor | Init / Update | Used for |
|---|---|---|
| `$91:F052` | `$9C87` / `$9CAA` | Human-controlled player |
| `$91:F05E` | `$9F7F` / `$9F8C` | Player shadow (child at slot+8) |
| `$91:F06A` | `$9F8D` / `$9F8F` | **Unused**, both routines empty |
| `$91:F076` | `$9EE4` / `$9EF6` | AI teammate (follows slot−4) |
| `$91:F082` | `$9AC1` / `$9B10` | Ball |
| `$91:F08E` | `$9C79` / `$9C86` | Ball shadow |

Slots in gameplay:

| Slot | Object |
|---|---|
| 0 | ball |
| 2 | ball shadow |
| 4 | ICE T, **controller 2** |
| 6 | KOOL J, controller 1 |
| 8 | Ice T's teammate |
| 10 | Kool J's teammate |
| 12, 14 | player shadows |

The player update (`$80:9CAA`) picks its controller with `((slot−2) & 2)`, so slot 4 reads pad 2. That's why the opponent stands still in 1-player: nobody is pressing anything on controller 2.

The AI update (`$80:9EF6`) just walks toward its human teammate whenever it gets more than `$30` pixels away. It never touches the ball.

## Players

- Movement limits: X `$18–$1CF`, Y `$AC–$12B`. Speed is 2 px/frame, or 4 with **X** held.
- **A** (new press) launches the ball. In the original it doesn't check whether you're holding the ball, so it can knock the ball from anywhere.
- **Select** toggles bit 15 of `$049E,X`, the hidden **animation viewer**. In that mode A/B step `$067A` through frames 0–34 (with auto-repeat) and Y toggles horizontal flip.
- **Start** (held, pad 1) sets mode 0, which shows the logo and then restarts the game. The real pause toggle in `$80:8132` is disabled because `$09C4` starts at `$8000`.

## Ball

- `$09F1` = holder slot (`$FFFF` = loose), `$09F3` = last holder, `$09F5` = pickup cooldown.
- When loose, `$80:9B10` builds the ball's 3D hitbox (`$80:8FE9`) and tests it against slots 4 and 6 (`$80:9067` + the AABB test at `$80:9163`). Only the two human players can ever hold the ball.
- When held, `$80:9BF4` places the ball beside the holder (offset by facing, tables at `$80:9C31/$9C41`) and keeps it bouncing for the dribble.
- Physics: speed and angle use the sine/cosine tables at `$81:8028/$81:8068` with the hardware multiplier. Height is integrated by `$80:9422`. On landing, vertical speed is negated minus `$80`, which is the bounce.

## Screen / coordinate system

Projection is a simple oblique view:

```
screen_x = world_x − camera_x ($0372)
screen_y = world_y − world_z − camera_y ($0374)
```

The camera follows the ball (`$80:9C51` copies the ball position to `$0376/$0378`). BG1 is the scenery, BG2 is the court (both 64×32 tiles), and BG3 is the HUD.

The rim sits at about **world (384, 220), height 100**. Players are roughly 64 px tall, so the rim is about 1.5× player height, which fits a 10-foot hoop.

## HUD

The HUD is BG3 with its tilemap at VRAM word `$6400`. Digits are two tiles tall:

| Part | Tile number |
|---|---|
| Top | `$3D + digit` |
| Bottom | `$47 + digit` (the "4" bottom is tile `$58`) |

Letters use `ASCII − $20` (e.g. "A" = `$21`). Attribute bits are `$3C00`. In the original, the score and clock are **static** parts of the decompressed tilemap.

## Sound

The SPC700 driver is uploaded from bank `$9E` using the standard IPL handshake. Its API is a jump table at `$9E:8000` (entry 0 returns `$1C04`, probably a version number).

`$80:A2EC` plays sound effect *n* and `$80:A33F–$80:A740` hold small stub functions for IDs `$00–$25` (play effect / play music). Only a few IDs are used by the prototype.

## Other code

- `$80:8255` is a tiny bytecode interpreter. It has 29 opcodes, with a jump table at `$81:80A8` and script data in bank `$81`.
- `$80:A000`-ish is the graphics decompressor (bit-stream based). Courts, the HUD and sprites are all compressed.
- A fair amount of code never executes during play (about 1,300 instructions). Most of it is script opcodes, alternate collision helpers, the disabled pause, and sound stubs.

---

## What the patch changes

### Hooks into the original code

| Address | Original | Patched |
|---|---|---|
| `$80:80BD` | `JSL $80A80F` (read pads) | `JSL my_pads`: reads pads, then the CPU writes fake pad-2 input |
| `$80:9E5E` | `LDA $09EF` | `JSR pass_check`: A only throws if you hold the ball |
| `$91:F085` | ball update `$9B10` | `my_ball`: scripted shot flight, otherwise the original routine |
| `$96:80D9` | mode 2 init / `$11` / `$14` | `my_init` / `my_nmi` (HUD + team palette) / `my_frame` (rules) |

All new code is at `$80:B000–$80:B6AF`. The header checksum is recalculated.

### New RAM (`$1000–$104F`, unused by the original game)

| Address | Use |
|---|---|
| `$1000` | shot in flight |
| `$1002` | frames left |
| `$1004–$100E` | ball X/Y/Z and velocity, 12.4 fixed point |
| `$1010` | shooter |
| `$1012` | make/miss |
| `$1014` | points (2 or 3) |
| `$1016` / `$1018` | scores (Kool J / Ice T) |
| `$101A` / `$101C` | clock seconds / frame counter |
| `$101E` | HUD needs redraw |
| `$1020` | game over |
| `$1022` / `$1024` | check-ball timer / team to receive |
| `$1026` | player 2 is human |
| `$1028` | game started |
| `$1034` / `$1036` | steal cooldowns |
| `$1038–$103C` | CPU hold timer / target |
| `$1042` | RNG |

### Shot model

Flight time is `30 + distance/16` frames (max 70). The ball follows a parabola with gravity 3/16 px/frame² and lands exactly on the rim.

Make chance:

| Distance from hoop | Chance |
|---|---|
| < 60 | 85% |
| < 120 | 65% |
| < 170 | 50% |
| further | 35% |

Distance is measured as |dx| + |dy|/2. Shots from 170 or more count as **3 points**.

A make drops through the net. A miss bounces off the rim at a random angle and speed, back toward the court.

### CPU (Ice T, while controller 2 is idle)

The CPU writes pad-2 input each frame, so it plays by exactly the same rules as a human:

- **Loose ball:** run to the ball.
- **Player 1 has the ball:** stay between them and the hoop, and occasionally try a steal (Y) when close.
- **CPU has the ball:** walk to a random spot in range and shoot. It always shoots after 3 seconds.
- **Ball in the air:** crash the boards for the rebound.

Pressing anything on controller 2 switches Ice T to human control for the rest of the game.
