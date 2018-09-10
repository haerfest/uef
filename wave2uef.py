#!/usr/bin/env python

from struct import unpack

import sys


def read_wave(stream):
    assert stream.read(4) == b'RIFF'
    stream.read(4)
    assert stream.read(4) == b'WAVE'
    assert stream.read(4) == b'fmt '
    assert unpack('<I', stream.read(4))[0] == 16         # PCM
    assert unpack('<h', stream.read(2))[0] == 1          # PCM
    assert unpack('<h', stream.read(2))[0] == 1          # Channels
    assert unpack('<I', stream.read(4))[0] == 44100      # Sample rate
    assert unpack('<I', stream.read(4))[0] == 44100 * 2  # Byte rate
    assert unpack('<h', stream.read(2))[0] == 2          # Block align
    assert unpack('<h', stream.read(2))[0] == 16         # Bits per sample
    assert stream.read(4) == b'data'
    size = unpack('<I', stream.read(4))[0]

    # In POLYGON.WAV, the first complete 2400 Hz cycle with phase 180 starts
    # here:
    stream.read(15 * 2)

    # Print the samples for the first 2400 Hz cycle:
    #
    # -0.3 -0.5 -0.7 -0.8 -0.8 -0.8 -0.6 -0.5 -0.1 0.3 0.5 0.7 0.8 0.9 0.8 0.6 0.6 0.2
    for _ in range(int(round(44100 / 2400))):
        sample = unpack('<h', stream.read(2))[0]
        print('{:.1f}'.format(sample / 32767.0), end=' ')
    print()


read_wave(sys.stdin.buffer)
