#!/usr/bin/env python

from argparse  import ArgumentParser
from functools import reduce
from math      import pi, radians, sin
from operator  import xor
from struct    import pack, unpack

import gzip
import io
import os
import sys
import zipfile


args = None


def parse_args():
    parser = ArgumentParser()
    parser.add_argument('-s', '--stretch', metavar='FACTOR', type=int,
                        help='stretch carrier tone duration (default: 1)',
                        default=1)
    args = parser.parse_args()

    args.stretch = max(1, args.stretch)

    return args


def open_zip(file):
    if not zipfile.is_zipfile(file):
        file.seek(0)
        return file
    zip = zipfile.ZipFile(file, 'r')
    uefs = [filename for filename in zip.namelist()
            if os.path.splitext(filename)[1].lower() == '.uef']
    assert uefs
    return zip.open(uefs[0], 'r')


def open_gzip(file):
    try:
        f = gzip.open(file)
        f.peek(6)
        return f
    except OSError:
        file.seek(0)
        return file


def open_uef(stream):
    return open_gzip(open_zip(io.BytesIO(stream.read())))


def as_bits(byte):
    return [1 if byte & (1 << i) else 0 for i in range(8)]


def read_chunks(stream):
    frequency = 1200
    phase = radians(180)

    def sample(freq, ph0, ph1, amp=32767):
        n = int(round(44100 * (ph1 - ph0) / (2 * pi) // freq))
        points = [amp * sin(phase + ph0 + 2 * pi * freq * t / 44100)
                  for t in range(n)]
        fmt = '<' + 'h' * n
        return pack(fmt, *[int(p) for p in points])

    def wave(x):
        if x == 'SL':  # Slow Low pulse.
            return sample(frequency, 0, pi)

        if x == 'SH':  # Slow High pulse.
            return sample(frequency, pi, 2 * pi)

        if x == 'FL':  # Fast Low pulse.
            return sample(2 * frequency, 0, pi)

        if x == 'FH':  # Fast High pulse.
            return sample(2 * frequency, pi, 2 * pi)

        if x == 'SC':  # Slow Cycle.
            return sample(frequency, 0, 2 * pi)

        if x == 'FC':  # Fast Cycle.
            return sample(2 * frequency, 0, 2 * pi)

        if x == 1:  # 1-bit
            return sample(2 * frequency, 0, 4 * pi)

        if x == 0:  # 0-bit
            return sample(frequency, 0, 2 * pi)

        if x == '.':  # Silence.
            return sample(frequency, 0, 2 * pi, 0)

    data = io.BytesIO()
    with open_uef(stream) as uef:
        assert uef.read(10) == b'UEF File!\x00'
        uef.read(2)
        while True:
            header = uef.read(6)
            if len(header) == 0:
                break

            identifier, length = unpack('<HI', header)
            chunk = uef.read(length)

            if identifier == 0x100:  # Implicit start/stop bit tape data block.
                for byte in chunk:
                    data.write(wave(0))
                    for bit in as_bits(byte):
                        data.write(wave(bit))
                    data.write(wave(1))

            elif identifier == 0x104:  # Defined tape format data block.
                data_bits, parity, stop_bits = unpack('<Bcb', chunk[:3])
                for byte in chunk[3:]:
                    data.write(wave(0))
                    bits = as_bits(byte)[:data_bits]
                    for bit in bits:
                        data.write(wave(bit))
                    if parity == b'E':
                        data.write(wave(reduce(xor, bits, 0)))
                    elif parity == b'O':
                        data.write(wave(1 - reduce(xor, bits, 0)))
                    data.write(wave(1) * abs(stop_bits))
                if stop_bits < 0:
                    data.write(wave('FC'))

            elif identifier == 0x110:  # Carrier tone.
                cycles = unpack('<H', chunk)[0]
                data.write(wave('FC') * cycles * args.stretch)

            elif identifier == 0x111:  # Carrier tone with dummy byte.
                n, m = unpack('<HH', chunk)
                data.write(wave(1) * n)
                for b in [0, 1, 0, 1, 0, 1, 0, 1, 0, 1]:
                    data.write(wave(b))
                data.write(wave(1) * m)

            elif identifier == 0x112:  # Integer gap.
                cycles = unpack('<H', chunk)[0]
                data.write(wave('.') * cycles)

            elif identifier == 0x113:  # Change of base frequency.
                frequency = unpack('<f', chunk)[0]

            elif identifier == 0x114:  # Security cycles.
                lower, upper = unpack('<BH', chunk[:3])
                cycles = upper << 8 + lower
                bits = reduce(lambda bs, b: bs + as_bits(b), chunk[5:], [])
                index = 0
                if chunk[3] == b'P':
                    data.write(wave('FH' if data[0] else 'SH'))
                    index += 1
                    cycles -= 1
                for _ in range(cycles, 1, -1):
                    data.write(wave('FC' if bits[index] else 'SC'))
                    index += 1
                    cycles -= 1
                if cycles == 1:
                    if chunk[4] == b'P':
                        data.write(wave('FL' if bits[index] else 'SL'))
                    else:
                        data.write(wave('FC' if bits[index] else 'SC'))

            elif identifier == 0x115:  # Phase change.
                phase = radians(unpack('<H', chunk)[0])

            elif identifier == 0x116:  # Floating point gap.
                secs = unpack('<f', chunk)[0]
                data.write(wave('.') * int(round(frequency * secs)))

        data.seek(0)
        return data.read()


def write_wav(data, stream):
    stream.write(b'RIFF')
    stream.write(pack('<I', 4 + 8 + 16 + 8 + len(data)))
    stream.write(b'WAVE')
    stream.write(b'fmt ')
    stream.write(pack('<I', 16))         # PCM
    stream.write(pack('<h', 1))          # PCM
    stream.write(pack('<h', 1))          # Channels
    stream.write(pack('<I', 44100))      # Sample rate
    stream.write(pack('<I', 44100 * 2))  # Byte rate
    stream.write(pack('<h', 2))          # Block align
    stream.write(pack('<h', 16))         # Bits per sample
    stream.write(b'data')
    stream.write(pack('<I', len(data)))
    stream.write(data)


def main():
    global args
    args = parse_args()
    write_wav(read_chunks(sys.stdin.buffer), sys.stdout.buffer)


if __name__ == '__main__':
    main()
