#!/usr/bin/env python3

from struct import unpack

import io
import sys


class SyncError(Exception):
    pass


def print_byte(bits):
    asc = 0
    for index, bit in enumerate(bits):
        asc += bit * 2**index

    if 32 <= asc <= 127:
        print(chr(asc), end='', flush=True)
    else:
        print('.', end='', flush=True)


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


def get_pulse(stream, verbose=False):
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

    if verbose:
        print('pulse(sgn={}, samples={})'.format(
            sign(first), samples), flush=True)

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
    return io.BytesIO(stream.read())


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


def state_sync(stream):
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

        return 'state_carrier'

    except EOFError:
        # Done.
        return None


def state_carrier(stream):
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

        # Read a start bit.
        read_zero(stream)

        return 'state_byte'

    except EOFError:
        # Done.
        return None


def state_byte(stream):
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

    print_byte(bits)

    # Another start bit for the next byte.
    read_zero(stream)

    return 'state_byte'


stream = skip_header(sys.stdin.buffer)
state = 'state_sync'

while state:
    try:
        handler = globals().get(state)
        state = handler(stream)
    except SyncError as e:
        state = 'state_sync'
