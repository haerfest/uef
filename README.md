# UEF

Contains a Python 3 script to convert tape images of 8-bit Acorn microcomputers
to `.wav` files. With the appropriate cable you can play these back on your Mac
or PC and load them via the cassette interface on your Acorn. I test on an
Electron.

The tape images should be in [UEF](https://en.wikipedia.org/wiki/Unified_Emulator_Format)
format.

You can [read its specification](http://electrem.emuunlim.com/UEFSpecs.htm), but
note there seems to be a small mistake with the description of the carrier wave
(emphasis mine):

> output a **single** cycle at twice the current base frequency

This makes some games fail to load on an Electron, notably [JetSetWilly_E.zip](https://www.stairwaytohell.com/electron/uefarchive/Tynesoft/JetSetWilly_E.zip)
and [Hopper-PIASRR_E.zip](https://www.stairwaytohell.com/electron/uefarchive/SuperiorReRelease/Hopper-PIASRR_E.zip).

Other implementations I've checked, including the [reference one](https://github.com/TomHarte/CLK/blob/master/Storage/Tape/Formats/TapeUEF.cpp),
treat one carrier cycle the same as a one-bit, which outputs _two_ cycles at a
time. With that fix in place, the above games load successfully.

## Supported chunks

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

## Dependencies

A vanilla Python 3.x.x. Tested on Mac OS X High Sierra with Python 3.6.5.

## Usage

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

Since UEF files are often gzipped, and [Stairway To Hell](https://www.stairwaytohell.com)
carries `.zip` files containing gzipped `.uef` files, you can pass along any of
such files. In case of a `.zip` file, the first `.uef` inside is processed.

Example:

```
$ python3 uef2wave.py < Elite_E.zip > Elite_E.wav
................................................................................
................................................................................
....................................................
Chunk IDs encountered ... &0100, &0110, &0112
Chunk IDs ignored ....... &0000
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

## Shoutout

For far more convenience, check out [PlayUEF](http://www.8bitkick.cc/playuef.html),
which allows you to play back audio recordings of various games using nothing
but your browser.
