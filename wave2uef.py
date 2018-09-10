#!/usr/bin/env python3

from struct import unpack

import io
import sys


def get_sample(stream, threshold=0.1):
    sample = unpack('<h', stream.read(2))[0] / 32768.0
    return sample


def sign(x):
    if x < 0:
        return -1
    if x > 0:
        return +1
    return 0


def get_pulse(stream):
    first = get_sample(stream)

    length = 1
    subsequent = get_sample(stream)
    while sign(subsequent) == sign(first):
        length += 1
        subsequent = get_sample(stream)

    # Unread the last sample, which is not part of this pulse.
    stream.seek(-2, io.SEEK_CUR)

    # print('pulse ({},{})'.format(sign(first), length))
    return sign(first), length


def unget_pulse(stream, length):
    stream.seek(-length * 2, io.SEEK_CUR)


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

    unget_pulse(stream, length)
    return 'ok'


def read_cycle(stream):
    sgn1, length1 = get_pulse(stream)
    sgn2, length2 = get_pulse(stream)

    if sgn2 != -sgn1:
        # Phase is wrong.
        unget_pulse(stream, length2)
        return 'phase'

    if abs(length1 - length2) > 2:
        print('pulses {} and {}'.format(length1, length2))
        # Pulse lengths don't match.
        unget_pulse(stream, length2)
        return 'pulse lengths'

    return ('ok', length1, length2)


def read_slow_cycle(stream):
    result = read_cycle(stream)
    if isinstance(result, str):
        return result

    lengths = result[1:]
    frequency = 44100 / sum(lengths)
    if abs(frequency - 1200) > 500:
        # Not a slow cycle.
        unget_pulse(stream, sum(lengths))
        return 'not slow'

    return 'ok'


def read_fast_cycle(stream):
    result = read_cycle(stream)
    if isinstance(result, str):
        return result

    lengths = result[1:]
    frequency = 44100 / sum(lengths)
    if abs(frequency - 2400) > 500:
        # Not a fast cycle.
        unget_pulse(stream, sum(lengths))
        return 'not fast'

    return 'ok'


def read_carrier(stream):
    # A byte consists of a start bit (0), eight data bits, and a stop bit (1).
    # That's at most nine one-bits, or eighteen fast cycles, in a row. If we
    # read nineteen or more fast cycles, we are in the carrier signal.
    for _ in range(19):
        result = read_fast_cycle(stream)
        if result != 'ok':
            return result

    # Consume the remainder of the carrier.
    while read_fast_cycle(stream) == 'ok':
        pass

    return 'ok'


def read_start_bit(stream):
    return read_slow_cycle(stream)


def read_byte(stream):
    bits = []

    for _ in range(8):
        result = read_cycle(stream)
        if isinstance(result, str):
            return result

        length1, length2 = result[1:]
        frequency = 44100 / (length1 + length2)
        if abs(frequency - 1200) <= 500:
            # Slow cycle, a zero-bit.
            bits.append(0)
            continue

        if abs(frequency - 2400) > 500:
            # Not a fast cycle.
            return 'not fast'

        result = read_fast_cycle(stream)
        if result != 'ok':
            # Need another fast cycle for a one-bit.
            return 'not fast'

        bits.append(1)

    asc = 0
    for index, bit in enumerate(bits):
        asc += bit * 2**index

    if 32 <= asc <= 127:
        print(chr(asc), end='')
    else:
        print('<{:02x}>'.format(asc), end='')

    return 'ok'


def read_stop_bit(stream):
    result = read_fast_cycle(stream)
    if result != 'ok':
        return result

    result = read_fast_cycle(stream)
    if result != 'ok':
        return result

    return 'ok'


stream = skip_header(sys.stdin.buffer)
stream_pos = 0

states = {
    'start': (wait_first_pulse, {
        'ok': 'read_fast_cycle',
    }),
    'read_fast_cycle': (read_fast_cycle, {
        'phase': 'start',
        'pulse lengths': 'error',
        'ok': 'read_carrier',
        '*': 'read_fast_cycle',
    }),
    'read_carrier': (read_carrier, {
        'ok': 'read_start_bit',
        '*': 'read_fast_cycle',
    }),
    'read_start_bit': (read_start_bit, {
        'ok': 'read_byte',
        '*': 'error',
    }),
    'read_byte': (read_byte, {
        'ok': 'read_stop_bit',
        '*': 'error'
    }),
    'read_stop_bit': (read_stop_bit, {
        'ok': 'read_start_bit',
        '*': 'error',
    })
}

state = 'start'
while True:
    # print('state={}'.format(state))
    fn, transitions = states[state]
    result = fn(stream)
    if result in transitions:
        next_state = transitions[result]
    else:
        next_state = transitions['*']

    if next_state == 'done':
        break
    if next_state == 'error':
        raise Exception(
            'Error: result "{}" in state "{}" at pos {}'.format(
                result, state, stream.tell()))
    state = next_state
