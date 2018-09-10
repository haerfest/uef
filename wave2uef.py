#!/usr/bin/env python3

from struct import unpack

import io
import sys


def get_sample(stream):
    return unpack('<h', stream.read(2))[0] / 32768.0


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
    length = 1

    # Figure out the sign of our pulse. If the first sample is zero,
    # we look at the next to figure out our sign, or whether we are
    # silence.
    sgn = sign(first)
    if sgn == 0:
        subsequent = get_sample(stream)
        length += 1
        if sign(subsequent) != 0:
            sgn = sign(subsequent)

    # Consume the pulse.
    subsequent = get_sample(stream)
    while sign(subsequent) == sgn:
        length += 1
        subsequent = get_sample(stream)

    # If the final sample is not zero, then its sign has flipped
    # and we unread it.
    if sign(subsequent) != 0:
        unget(stream)

    # print('{},{}'.format(sign(first), length), flush=True)
    return sign(first), length


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


def wait_first_pulse(stream):
    sgn, length = get_pulse(stream)
    while length not in [8, 9, 10, 16, 17, 18, 19] or sgn >= 0:
        sgn, length = get_pulse(stream)

    unget(stream, length)
    return 'ok'


def read_cycle(stream, expected_freq):
    sgn1, length1 = get_pulse(stream)
    sgn2, length2 = get_pulse(stream)

    if sgn2 != -sgn1:
        # Phase is wrong.
        unget(stream, length1 + length2)
        return 'phase'

    ratio = max(length1, length2) / min(length1, length2)
    if ratio > 1.6:
        # Pulse lengths don't match.
        unget(stream, length1 + length2)
        return 'pulse lengths'

    freq = 44100 / (length1 + length2)
    if abs(freq - expected_freq) > 500:
        unget(stream, length1 + length2)
        return 'not {}'.format(expected_freq)

    return 'ok'


def read_carrier(stream):
    # A byte consists of a start bit (0), eight data bits, and a stop bit (1).
    # That's at most nine one-bits, or eighteen fast cycles, in a row. If we
    # read nineteen or more fast cycles, we are in the carrier signal.
    for _ in range(19):
        result = read_cycle(stream, 2400)
        if result != 'ok':
            return result

    # Consume the remainder of the carrier.
    while read_cycle(stream, 2400) == 'ok':
        pass

    return 'ok'


def read_fast_cycle(stream):
    return read_cycle(stream, 2400)


def read_start_bit(stream):
    return read_cycle(stream, 1200)


def read_byte(stream):
    bits = []

    for _ in range(8):
        result = read_cycle(stream, 1200)
        if result == 'ok':
            # Slow cycle, a zero-bit.
            bits.append(0)
            continue

        # Need two fast cycles for a one-bit.
        result = read_cycle(stream, 2400)
        if result != 'ok':
            return result

        result = read_cycle(stream, 2400)
        if result != 'ok':
            return result

        bits.append(1)

    asc = 0
    for index, bit in enumerate(bits):
        asc += bit * 2**index

    if 32 <= asc <= 127:
        print(chr(asc), end='', flush=True)
    else:
        print('.', end='', flush=True)

    return 'ok'


def read_stop_bit(stream):
    result = read_cycle(stream, 2400)
    if result != 'ok':
        return result

    result = read_cycle(stream, 2400)
    if result != 'ok':
        return result

    return 'ok'


def read_carrier_or_start_bit(stream):
    result = read_carrier(stream)
    if result == 'ok':
        return 'carrier'

    result = read_start_bit(stream)
    if result == 'ok':
        return 'start bit'

    return 'no carrier or start bit'


def start_bit_or_end(stream):
    result = read_start_bit(stream)
    if result == 'ok':
        return 'start bit'

    print(result)
    print(get_pulse(stream))
    print(get_pulse(stream))
    return 'end'


states = {
    'start': (wait_first_pulse, {
        'ok': 'carrier',
    }),
    'carrier': (read_carrier, {
        'ok': 'start bit',
    }),
    'start bit': (read_start_bit, {
        'ok': 'byte',
    }),
    'byte': (read_byte, {
        'ok': 'stop bit',
    }),
    'stop bit': (read_stop_bit, {
        'ok': 'carrier or start bit',
    }),
    'carrier or start bit': (read_carrier_or_start_bit, {
        'carrier': 'start bit or end',
        'start bit': 'byte',
    }),
    'start bit or end': (start_bit_or_end, {
        'start bit': 'byte',
        'end': 'done',
    })
}

stream = skip_header(sys.stdin.buffer)
state = 'start'

while True:
    # print('state={}'.format(state))
    fn, transitions = states[state]
    result = fn(stream)
    if result not in transitions:
        raise Exception(
            'Error: result "{}" in state "{}" at pos {}'.format(
                result, state, stream.tell()))

    next_state = transitions[result]
    if next_state == 'done':
        break
    state = next_state
