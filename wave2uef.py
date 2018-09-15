#!/usr/bin/env python3

from struct import pack, unpack

import io
import sys


class SyncError(Exception):
    pass


def secs(start_pos, end_pos):
    byte_count = end_pos - start_pos
    sample_count = byte_count / 2
    return sample_count / 44100.0


class GapChunk(object):
    def __repr__(self):
        return '<Gap {:.1f} secs>'.format(secs(self.start, self.end))

    def write(self, stream):
        stream.write(pack('<HIf', 0x116, 4, secs(self.start, self.end)))


class CarrierChunk(object):
    def __repr__(self):
        return '<Carrier {:.1f} secs>'.format(secs(self.start, self.end))

    def write(self, stream):
        cycles = int(secs(self.start, self.end) * 2400)
        stream.write(pack('<HIH', 0x110, 2, cycles))


class DataChunk(object):
    def __repr__(self):
        return '<Data {} bytes "{}">'.format(len(self.bytes), self.filename)

    @property
    def filename(self):
        s = ''
        for x in self.bytes:
            if x == 0:
                break
            s += chr(x) if (32 <= x < 127) else '&{:02x}'.format(x)
        return s

    def write(self, stream):
        stream.write(pack('<HI', 0x100, len(self.bytes)))
        for byte in self.bytes:
            stream.write(pack('B', byte))


def byte(bits):
    n = 0
    for pos, bit in enumerate(bits):
        n += bit * 2**pos
    return n


def get_sample(stream):
    sample = stream.read(2)
    if not sample:
        raise EOFError()

    return unpack('<h', sample)[0] / 32768.0


def sign(x):
    if x < 0:
        return -1
    if x > 0:
        return +1
    return 0


def unget(stream, length=1):
    stream.seek(-length * 2, io.SEEK_CUR)


def get_pulse(stream):
    first = get_sample(stream)
    samples = [first]

    # Figure out the sign of our pulse. If the first sample is zero,
    # we look at the next to figure out our sign, or whether we are
    # silence.
    sgn = sign(first)
    if sgn == 0:
        sample = get_sample(stream)
        samples.append(sample)
        if sign(sample) != 0:
            sgn = sign(sample)

    # Consume the pulse.
    sample = get_sample(stream)
    while sign(sample) == sgn:
        samples.append(sample)
        sample = get_sample(stream)

    # If the final sample is not zero, then its sign has flipped
    # and we unread it.
    if sign(sample) != 0:
        unget(stream)

    return sgn, samples


def skip_header(stream):
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
    stream.read(4)


def read_cycle(stream, expected_freq):
    sgn1, samples1 = get_pulse(stream)
    sgn2, samples2 = get_pulse(stream)

    length1 = len(samples1)
    length2 = len(samples2)

    if sgn2 != -sgn1:
        unget(stream, length1 + length2)
        raise SyncError('phase')

    ratio = max(length1, length2) / min(length1, length2)
    if ratio > 1.6:
        unget(stream, length1 + length2)
        raise SyncError('ratio')

    freq = int(44100 / (length1 + length2))
    if abs(freq - expected_freq) > 500:
        unget(stream, length1 + length2)
        raise SyncError('frequency {} {}'.format(freq, expected_freq))


def read_zero(stream):
    read_cycle(stream, 1200)


def read_one(stream):
    read_cycle(stream, 2400)
    read_cycle(stream, 2400)


def state_sync(stream, chunks):
    chunks.append(GapChunk())
    chunks[-1].start = stream.tell()

    try:
        while True:
            sgn, samples = get_pulse(stream)
            if len(samples) not in [8, 9, 10, 16, 17, 18, 19]:
                # Too short or too long.
                continue
            if sgn >= 0:
                # Not phase 180.
                continue

            # Rewind and try to read a carrier tone.
            unget(stream, len(samples))
            try:
                read_cycle(stream, 2400)
                break
            except SyncError:
                # Skip over what we just read.
                for _ in samples:
                    get_sample(stream)

        chunks[-1].end = stream.tell()

        return 'state_carrier'

    except EOFError:
        chunks[-1].end = stream.tell()
        return None


def state_carrier(stream, chunks):
    chunks.append(CarrierChunk())
    chunks[-1].start = stream.tell()

    try:
        # A byte consists of a start bit (0), eight data bits, and a stop bit
        # (1). That's at most nine one-bits, or eighteen fast cycles, in a row.
        # If we read nineteen or more fast cycles, we are in the carrier
        # signal.
        for _ in range(19):
            read_cycle(stream, 2400)

        try:
            # Consume the remainder of the carrier tone.
            while True:
                read_cycle(stream, 2400)
        except SyncError:
            pass

        chunks[-1].end = stream.tell()

        # Read a start bit.
        read_zero(stream)

        return 'state_byte'

    except EOFError:
        chunks[-1].end = stream.tell()
        return None


def state_byte(stream, chunks):
    start = stream.tell()

    bits = []

    # Read all eight bits.
    for _ in range(8):
        try:
            read_zero(stream)
            bits.append(0)
        except SyncError:
            read_one(stream)
            bits.append(1)

    # Read the stop bit.
    read_one(stream)

    if not (chunks and isinstance(chunks[-1], DataChunk)):
        chunks.append(DataChunk())
        chunks[-1].start = start
        chunks[-1].bytes = []
    chunks[-1].end = stream.tell()
    chunks[-1].bytes.append(byte(bits))

    # Another start bit for the next byte, or a fast cycle for a
    # carrier.
    try:
        read_zero(stream)
        return 'state_byte'
    except SyncError:
        read_cycle(stream, 2400)
        return 'state_carrier'


def write_uef(chunks, stream):
    stream.write(b'UEF File!\x00')  # Magic value.
    stream.write(b'\x01\x00')       # Version 0.10.

    for chunk in chunks:
        chunk.write(stream)


skip_header(sys.stdin.buffer)
stream = io.BytesIO(sys.stdin.buffer.read())

state = 'state_sync'
chunks = []
while state:
    try:
        handler = globals().get(state)
        state = handler(stream, chunks)
    except SyncError as e:
        state = 'state_sync'

write_uef(chunks, sys.stdout.buffer)
for chunk in chunks:
    print(chunk, file=sys.stderr)
