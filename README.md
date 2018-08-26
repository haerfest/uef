# UEF

Contains a Python 3 script to convert tape images of 8-bit Acorn microcomputers
to `.wav` files. With the appropriate cable you can play these back on your Mac
or PC and load them via the cassette interface on your Acorn. I test on an
Electron.

The tape images should be in [UEF](https://en.wikipedia.org/wiki/Unified_Emulator_Format)
format. You can [read its specification](http://electrem.emuunlim.com/UEFSpecs.htm).

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
usage: uef2wave.py [-h] [--frequency {11025,22050,44100}] [--bits {8,16}]
                   [--debug] [--norecord]
                   ueffile

positional arguments:
  ueffile               the UEF file to convert, (g)zipped or not

optional arguments:
  -h, --help            show this help message and exit
  --frequency {11025,22050,44100}
                        the sample frequency in Hz (default 44100)
  --bits {8,16}         the sample resolution in bits (default 16)
  --debug               enable debug output
  --norecord            do not record a wave file
```

Since UEF files are often gzipped, and [Stairway To Hell](https://www.stairwaytohell.com)
carries `.zip` files containing gzipped `.uef` files, you can pass along any of
such files. In case of a `.zip` file, the first `.uef` inside is processed.

Example:

```
$ python3 uef2wave.py Elite_E.zip
Elite_E.zip
................................................................................
................................................................................
....................................................
Chunk IDs encountered ... &0100, &0110, &0112
Chunk IDs ignored ....... &0000
Markers:
  00:01 ELITE
  00:06 ELITEdata
  01:01 ELITEcode
  04:22 V1
```

It prints which chunks it encountered and which one it ignored, which is really
just for me to debug new UEF files.

It also prints out a list of files in the tape image and the timestamps of their
first data blocks, which is useful when virtually "rewinding" the tape.

## Shoutout

For far more convenience, check out [PlayUEF](http://www.8bitkick.cc/playuef.html),
which allows you to play back audio recordings of various games using nothing
but your browser.