# UEF

Contains Python 3 scripts to assist working with [UEF](https://en.wikipedia.org/wiki/Unified_Emulator_Format)
files, which are tape images of 8-bit Acorn microcomputers:

* `uef2wave`
* `wave2uef`
* `bin2uef`

All scripts require Python 3. I tested them on macOS X and Python 3.7.0.

## `uef2wave`

Convert UEF files to audible `.wav` files. With the appropriate cable you can
play these back on your Mac or PC and load them via the cassette interface on
your Acorn.

You can read the [UEF specification](http://electrem.emuunlim.com/UEFSpecs.htm),
but note the specification of the carrier block (emphasis mine):

> output a **single** cycle at twice the current base frequency

This makes some games fail to load on an Electron, for example:

* [JetSetWilly_E.zip](https://www.stairwaytohell.com/electron/uefarchive/Tynesoft/JetSetWilly_E.zip)
* [Hopper-PIASRR_E.zip](https://www.stairwaytohell.com/electron/uefarchive/SuperiorReRelease/Hopper-PIASRR_E.zip)
* [Firetrack_E.zip](https://www.stairwaytohell.com/electron/uefarchive/Superior/Firetrack_E.zip)

Other implementations I've checked, including the [reference one](https://github.com/TomHarte/CLK/blob/master/Storage/Tape/Formats/TapeUEF.cpp),
treat one carrier cycle the same as a one-bit, which outputs _two_ cycles at a
time. That helps loading Jet Set Willy and Hopper, but Firetrack needs _four_
cycles.

To that end I have added boolean `DEVIATE_FROM_SPEC` which is `True` by default,
and which adds these fixes. Set it to `False` if you want to strictly adhere to
the specification.

### Supported chunks

The following UEF chunks are supported:

Chunk  | Description
-------|------------
`0100` | Implicit start/stop bit tape data block.
`0104` | Defined tape format data block.
`0110` | Carrier tone.
`0111` | Carrier tone with dummy byte.
`0112` | Integer gap.
`0113` | Change of base frequency.
`0114` | Security cycles.
`0116` | Floating point gap.

### Usage

The script reads the UEF file contents from standard input, and writes the
generated `.wav` to standard output.  For example:

```
$ python3 uef2wave.py < Elite_E.zip > Elite_E.wav
```

Two remarks:

* Since UEF files are often gzipped, and [Stairway To Hell](https://www.stairwaytohell.com)
  carries `.zip` files containing gzipped `.uef` files, you can pass along any
  of such files. In case of a `.zip` file, the first `.uef` inside is processed.
* The generated `.wav` file is always mono, sampled at 44,100 Hz and 16 bits.

### Shoutout

For far more convenience, check out [PlayUEF](http://www.8bitkick.cc/playuef.html),
which allows you to play back audio recordings of various games using nothing
but your browser.

## `wave2uef`

Basically the inverse of `uef2wave`: takes a 16-bit 44 kHz mono `.wav` file and
outputs a UEF file. A bit more limited in the chunks it supports.

### Supported chunks

The following UEF chunks are supported:

Chunk  | Description
-------|------------
`0100` | Implicit start/stop bit tape data block.
`0110` | Carrier tone.
`0116` | Floating point gap.

### Usage

The script reads the `.wav` file contents from standard input, and writes the
generated UEF file to standard output. Prints some debug information to
standard error at the moment. For example:

```
$ python3 wave2uef.py < PERSIAN.wav > PERSIAN.uef
<Gap 1.2 secs>
<Carrier 7.7 secs>
<Data 284 bytes "*PERSIAN">
<Carrier 5.3 secs>
<Gap 2.2 secs>
```

## `bin2uef`

This is a simple script to store a binary file onto a UEF file, which you may
subsequently load into your Acorn micro using `uef2wave`.

### Usage

```
$ python3 bin2uef.py --help
usage: bin2uef.py [-h] [-n NAME] -l ADDRESS [-e ADDRESS]

optional arguments:
  -h, --help            show this help message and exit
  -n NAME, --name NAME  name to record on tape (default: FILE)
  -l ADDRESS, --load ADDRESS
                        load address (prepend 0x for hex)
  -e ADDRESS, --exec ADDRESS
                        execution address (prepend 0x for hex)
```

The script reads the file contents from standard input and writes the UEF file
to standard output. This way you can easily chain it with `uef2wave`, should you
wish.

### Example

Using the [xa65](http://www.floodgap.com/retrotech/xa/) 6502 assembler, you can
write some machine code and have it execute on your Acorn micro as follows.

Save the following file as `hello.asm`:

```
  oswrch = $ffee

  * = $2000

  ldx #0
loop: 
  lda message,x
  beq done
  jsr oswrch
  inx
  jmp loop
  
done:
  rts

message:
  .asc "Hello, world!"
  .byte 0
```

Then execute the following from a command-line, specifying a name to appear on
the tape (`-n`), as well as the correct load address (`-l`):

```
$ xa hello.asm -o - | python bin2uef.py -n HELLO -l 0x2000 | python uef2wav.py > hello.wav
```

On your Acorn micro, load the `hello.wav` file, which you play back through the
line out of your Mac or PC, and run it:

```
> *LOAD "HELLO"
Searching

Loading

HELLO      00 001D

> CALL &2000
Hello, world!
```
