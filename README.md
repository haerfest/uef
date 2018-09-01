# UEF

Contains Python 3 scripts to assist working with [UEF](https://en.wikipedia.org/wiki/Unified_Emulator_Format)
files, which are tape images of 8-bit Acorn microcomputers:

* `uef2wave`
* `bin2uef`

## `uef2wave`

Convert UEF files to audible `.wav` files. With the appropriate cable you can
play these back on your Mac or PC and load them via the cassette interface on
your Acorn.

You can read the [UEF specification](http://electrem.emuunlim.com/UEFSpecs.htm),
but note there seems to be a small mistake with the description of the carrier
wave (emphasis mine):

> output a **single** cycle at twice the current base frequency

This makes some games fail to load on an Electron, for example:

* [JetSetWilly_E.zip](https://www.stairwaytohell.com/electron/uefarchive/Tynesoft/JetSetWilly_E.zip)
* [Hopper-PIASRR_E.zip](https://www.stairwaytohell.com/electron/uefarchive/SuperiorReRelease/Hopper-PIASRR_E.zip)

Other implementations I've checked, including the [reference one](https://github.com/TomHarte/CLK/blob/master/Storage/Tape/Formats/TapeUEF.cpp),
treat one carrier cycle the same as a one-bit, which outputs _two_ cycles at a
time. With that fix in place, the above games load successfully.

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

### Dependencies

A vanilla Python 3.x.x. Tested on Mac OS X High Sierra with Python 3.6.5.

### Usage

Use `--help` to show help information:

```
$ python3 uef2wave.py --help
usage: uef2wave.py [-h] [-f {11025,22050,44100}] [-b {8,16}] [-v {0,1,2,3}]

optional arguments:
  -h, --help            show this help message and exit
  -f {11025,22050,44100}, --frequency {11025,22050,44100}
                        the sample frequency in Hz (default: 44100)
  -b {8,16}, --bits {8,16}
                        the sample resolution in bits (default: 16)
  -v {0,1,2,3}, --verbose {0,1,2,3}
                        set the verbosity level (default: 1)
```

The script reads the UEF file contents from standard input, and writes the
generated `.wav` to standard output.

Since UEF files are often gzipped, and [Stairway To Hell](https://www.stairwaytohell.com)
carries `.zip` files containing gzipped `.uef` files, you can pass along any of
such files. In case of a `.zip` file, the first `.uef` inside is processed.

Example:

```
$ python3 uef2wave.py < Elite_E.zip > Elite_E.wav
................................................................................
................................................................................
....................................................
Chunk IDs encountered ... 0100, 0110, 0112
Chunk IDs ignored ....... 0000
Total time .............. 04:55
Markers:
  00:02 ELITE
  00:09 ELITEdata
  01:11 ELITEcode
  04:53 V1
```

By default it prints which chunks it encountered and which ones, if any, it
ignored, which is really just for me to debug new UEF files. You can silence
it by passing along `--verbose 0`, or even output further debug information
by trying one of the higher verbosity levels.

It also prints out a list of files in the tape image and the timestamps of their
first data blocks, which is useful when virtually "rewinding" the tape.

### Shoutout

For far more convenience, check out [PlayUEF](http://www.8bitkick.cc/playuef.html),
which allows you to play back audio recordings of various games using nothing
but your browser.

## `bin2uef`

This is a simple script to store a binary file onto a UEF file, which you may
subsequently load into your Acorn micro using `uef2wave`.

### Usage

```
python3 bin2uef.py --help
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
