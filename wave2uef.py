#!/usr/bin/env python3

from struct import pack, unpack

import io
import sys


# Global variables, because why not.
stream = None
chunks = []
marker = None


class SyncError(Exception):
    pass


def secs(start_pos, end_pos):
    byte_count   = end_pos - start_pos
    sample_count = byte_count / 2
    return sample_count / 44100.0

class Chunk(object):
    def __init__(self, _=None):
        self.start = marker
        self.end   = stream.tell()

class Gap(Chunk):
    def __repr__(self):
        return '<Gap {:.1f} secs {}:{}>'.format(secs(self.start, self.end), self.start, self.end)

    def write(self, stream):
        duration = secs(self.start, self.end)
        if duration:
            stream.write(pack('<HIf', 0x116, 4, duration))

class Carrier(Chunk):
    def __repr__(self):
        return '<Carrier {:.1f} secs {}:{}>'.format(secs(self.start, self.end), self.start, self.end)

    def write(self, stream):
        cycles = int(secs(self.start, self.end) * 2400)
        if cycles:
            stream.write(pack('<HIH', 0x110, 2, cycles))

class Data(Chunk):
    def __init__(self, data=None):
        super().__init__()
        self.data = data or []

    def __repr__(self):
        return '<Data {} bytes "{}" {}:{}>'.format(len(self.data), self.filename, self.start, self.end)

    @property
    def filename(self):
        s = ''
        for x in self.data:
            if x == 0:
                break
            s += chr(x) if (32 <= x < 127) else '?'.format(x)
        return s

    def write(self, stream):
        if self.data:
            stream.write(pack('<HI', 0x100, len(self.data)))
            for byte in self.data:
                stream.write(pack('B', byte))


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

def byte(bits):
    n = 0
    for pos, bit in enumerate(bits):
        n += bit * 2**pos
    return n

def sample():
    sample = stream.read(2)
    if not sample:
        raise EOFError()

    return int(unpack('<h', sample)[0] / 327.0)  # round in [-100, 100]

def sign(x):
    if x < 0:
        return -1
    if x > 0:
        return +1
    return 0

def rewind(sample_count=1):
    stream.seek(-sample_count * 2, io.SEEK_CUR)

# A single 1200 Hz sine cycle takes 1/1200 of a second. Sampling it at 44100 Hz
# results in roughly 37 samples. Likewise, a 2400 Hz sine cycle results in about
# 18 samples. A pulse is half a sine wave, or half a period, and thus consists
# of roughly 37/2 = 18 and 18/2 = 9 samples. We could try to fit the signal
# onto perfect sine waves, but it should likely be good enough to treat the
# sine wave as a square one.
def pulse():

    # First skip any zero samples.
    total = 0
    while sign(sample()) == 0:
        total += 1
    rewind()

    # Consume the samples that are on one the same side of the y-axis, until we
    # cross over to the other side, indicating the start of the next pulse.
    sgn     = sign(sample())
    total  += 1
    samples = 1
    while sign(sample()) == sgn:
        total   += 1
        samples += 1

    # Restore the sample that is part of the next pulse.
    rewind()

    # Ok if we got a 2400 Hz pulse, should be ~9 samples.
    if 9 - 2 <= samples <= 9 + 2:
        return total, sgn, 2400

    # Ok if we got a 1200 Hz pulse, should be ~18 samples.
    if 18 - 2 <= samples <= 18 + 2:
        return total, sgn, 1200

    raise SyncError(f'pulse? {samples}')

def cycle(expected_freq):
    count1, sgn1, freq1 = pulse()
    count2, sgn2, freq2 = pulse()

    # Pulses must have opposite signs. If not, rewind to before the second
    # pulse.
    if sgn1 == sgn2:
        rewind(count2)
        raise SyncError('pulses with same sign')

    # Pulses must describe the same frequency. If not, rewind to before the
    # second pulse.
    if freq1 != freq2:
        rewind(count2)
        raise SyncError('pulses with different frequencies')

    # We read a valid pulse but not of the expected frequency. Rewind to the
    # beginning of the pulse for another attempt.
    if freq1 != expected_freq:
        rewind(count1 + count2)
        raise SyncError(f'cycle of {freq1} Hz')

    return count1 + count2

def peek(fn):
    start = stream.tell()
    try:
        fn()
        return True
    except (EOFError, SyncError) as e:
        return False
    finally:
        stream.seek(start)

def slow_cycle():
    cycle(1200)

def fast_cycle():
    cycle(2400)

def zero_bit():
    slow_cycle()

def one_bit():
    fast_cycle()
    fast_cycle()

def start_bit():
    zero_bit()

def stop_bit():
    one_bit()

def data_bit():
    if peek(zero_bit):
        zero_bit()
        return 0
    else:
        one_bit()
        return 1

def mark():
    global marker
    marker = stream.tell()

def sync():
    mark()
    while not peek(fast_cycle):
        sample()
    if stream.tell() > marker:
        chunks.append(Gap())

def carrier():
    mark()
    fast_cycle()
    while peek(fast_cycle):
        fast_cycle()
    chunks.append(Carrier())

def data():
    data = []
    mark()
    start_bit()
    while True:
        data.append(byte(data_bit() for _ in range(8)))
        stop_bit()
        if not peek(start_bit):
            break
        start_bit()
    if data:
        chunks.append(Data(data))

def carrier_or_data():
    if peek(start_bit):
        data()
    else:
        carrier()
    
def write_uef(stream):
    stream.write(b'UEF File!\x00')  # Magic value.
    stream.write(b'\x01\x00')       # Version 0.10.

    for chunk in chunks:
        chunk.write(stream)


skip_header(sys.stdin.buffer)
stream = io.BytesIO(sys.stdin.buffer.read())

try:
    while True:
        try:
            print('.', end='', flush=True, file=sys.stderr)
            carrier_or_data()
        except SyncError:
            sync()
except EOFError:
    pass

print(file=sys.stderr)    
for chunk in chunks:
    print(chunk, file=sys.stderr)

write_uef(sys.stdout.buffer)
