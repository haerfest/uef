#!/usr/bin/env python

from __future__ import print_function

from argparse import ArgumentParser
from struct import pack, unpack

import io
import math
import os
import sys


class Chunk(object):
    def __init__(self, identifier, data):
        self.identifier = identifier
        self.data = data

    def __repr__(self):
        return '<Chunk &{:04x} {} bytes: {} ...>'.format(self.identifier, len(self.data), ' '.join('{:02x}'.format(x) for x in self.data[:10]))


def chunks(ueffile):
    with open(ueffile, 'rb') as uef:
        # Check the magic value, indicating it's a UEF file.
        magic = uef.read(10)
        if magic != b'UEF File!\x00':
            raise Exception('{}: not a UEF file'.format(ueffile))

        # Skip over the UEF version.
        uef.read(2)

        while True:
            # Read the chunk identifier and test for EOF.
            identifier = uef.read(2)
            if len(identifier) == 0:
                break
            identifier = unpack('<H', identifier)[0]

            # Read the length and data bytes.
            length = unpack('<I', uef.read(4))[0]
            data = uef.read(length)

            yield Chunk(identifier, data)


class Recordable(object):
    def record(self, recorder):
        raise Exception('{}; record() not implemented'.format(type(self)))


class LowPulse(Recordable):
    def __init__(self, bit):
        self.bit = bit

    def __repr__(self):
        return '<LowPulse {}>'.format(self.bit)

    def record(self, recorder):
        recorder.low_pulse(fast=bit)


class HighPulse(Recordable):
    def __init__(self, bit):
        self.bit = bit

    def __repr__(self):
        return '<HighPulse {}>'.format(self.bit)

    def record(self, recorder):
        recorder.high_pulse(fast=bit)


class SlowCycle(Recordable):
    '''
    Represents a single slow cycle.
    '''
    def __repr__(self):
        return '<SlowCycle>'

    def record(self, recorder):
        recorder.low_pulse()
        recorder.high_pulse()


class FastCycle(Recordable):
    '''
    Represents a single fast cycle.
    '''
    def __repr__(self):
        return '<FastCycle>'

    def record(self, recorder):
        recorder.low_pulse(fast=True)
        recorder.high_pulse(fast=True)


class ZeroBit(SlowCycle):
    '''
    Represents a zero-bit.
    '''
    def __repr__(self):
        return '<Bit 0>'


class OneBit(Recordable):
    '''
    Represents a one-bit.
    '''
    def __repr__(self):
        return '<Bit 1>'

    def record(self, recorder):
        recorder.low_pulse(fast=True)
        recorder.high_pulse(fast=True)
        recorder.low_pulse(fast=True)
        recorder.high_pulse(fast=True)


class StartBit(ZeroBit):
    '''
    Represents a start bit.
    '''
    def __repr__(self):
        return '<StartBit>'


class StopBit(OneBit):
    '''
    Represents a stop bit.
    '''
    def __repr__(self):
        return '<StopBit>'


class Carrier(Recordable):
    '''
    Represents a carrier tone of a certain cycle count.
    '''
    def __init__(self, cycle_count):
        self.cycle_count = cycle_count

    def __repr__(self):
        return '<Carrier {} cycles>'.format(self.cycle_count)

    def record(self, recorder):
        for _ in range(self.cycle_count):
            recorder.low_pulse(fast=True)
            recorder.high_pulse(fast=True)


class IntegerGap(Recordable):
    def __init__(self, n):
        self.n = n

    def __repr__(self):
        return '<IntegerGap {}>'.format(self.n)

    def record(self, recorder):
        for _ in range(self.n):
            recorder.low_pulse(fast=True, silent=True)
            recorder.high_pulse(fast=True, silent=True)


class FloatGap(Recordable):
    def __init__(self, seconds):
        self.seconds = seconds

    def __repr__(self):
        return '<FloatGap {:.1f} sec>'.format(self.seconds)

    def record(self, recorder):
        cycle_count = int(self.seconds * 2 * recorder.base_frequency)
        for _ in range(cycle_count):
            recorder.low_pulse(fast=True, silent=True)
            recorder.high_pulse(fast=True, silent=True)


class BaseFrequencyChange(Recordable):
    def __init__(self, frequency):
        self.frequency = frequency

    def __repr__(self):
        return '<BaseFrequencyChange {:.1f} Hz>'.format(self.frequency)

    def record(self, recorder):
        recorder.base_frequency = self.frequency


class PhaseChange(Recordable):
    def __init__(self, phase):
        self.phase = phase

    def __repr__(self):
        return '<PhaseChange {} deg>'.format(self.phase)

    def record(self, recorder):
        recorder.phase = self.phase


class Transformer(object):
    def __init__(self):
        self.ignored = set()

    def transform(self, chunk):
        method = 'transform_{:04x}'.format(chunk.identifier)
        transformer = getattr(self, method, None)
        if transformer and callable(transformer):
            recordables = transformer(chunk.data)
            if recordables:
                return recordables

        self.ignored.add(chunk.identifier)
        return []

    def transform_0000(self, data):
        print(data)
        return []

    def transform_0100(self, data):
        '''
        Implicit start/stop bit tape data block.
        '''
        return [StartBit()] + self.bits(data) + [StopBit()]

    def transform_0110(self, data):
        '''
        Carrier tone.
        '''
        cycle_count = unpack('<H', data)[0]
        return [Carrier(cycle_count)]

    def transform_0111(self, data):
        '''
        Carrier tone with dummy byte.
        '''
        length1, length2 = unpack('<HH', data)
        return [Carrier(length1), StartBit()] + self.bits(b'\xAA') + [StopBit(), Carrier(length2)]

    def transform_0112(self, data):
        '''
        Integer gap.
        '''
        n = unpack('<H', data)[0]
        return [IntegerGap(n)]

    def transform_0113(self, data):
        '''
        Change of base frequency.
        '''
        frequency = unpack('<f', data)[0]
        return [BaseFrequencyChange(frequency)]

    def transform_0114(self, data):
        '''
        Security cycles.
        '''
        upper, lower = unpack('<HB', data[:3])
        cycle_count = upper << 8 + lower

        recordables = [FastCycle() if isinstance(bit, OneBit) else SlowCycle() for _, bit in zip(range(cycle_count), self.bits(data[5:]))]

        if recordables and data[3] == b'P':
            recordables[0] = HighPulse(recordables[0].value)
        if recordables and data[4] == b'P':
            recordables[-1] = LowPulse(recordables[-1].value)

        return recordables

    def transform_0115(self, data):
        '''
        Phase change.
        '''
        phase = unpack('<H', data)[0]
        return [PhaseChange(phase)]

    def transform_0116(self, data):
        '''
        Floating point gap.
        '''
        seconds = unpack('<f', data)[0]
        return [FloatGap(seconds)]

    def bits(self, bytes):
        return [OneBit() if byte & (1 << i) else ZeroBit() for byte in bytes for i in range(8)]


class Cycle(object):
    '''
    Represents a single cycle of a given frequency and phase, sampled at a certain
    sample frequency, number of bits, and amplitude.
    '''
    def __init__(self, frequency, phase=0, sample_frequency=44100, bits=16, amplitude=1):
        if bits == 8:
            silence_level = 127
            amplitude *= 127
        else:
            silence_level = 0
            amplitude *= 32767

        self._bits = bits
        self._phase = phase

        self._samples = []
        self._sample_count = math.ceil(sample_frequency // frequency)

        for t in range(self._sample_count):
            y = math.sin(phase + 2 * math.pi * t / self._sample_count)
            self._samples.append(math.trunc(silence_level + amplitude * y))

    @property
    def low_pulse(self):
        i = 0
        j = self._sample_count // 2
        return b''.join(self.pack(y) for y in self._samples[i:j])

    @property
    def high_pulse(self):
        i = self._sample_count // 2
        j = self._sample_count
        return b''.join(self.pack(y) for y in self._samples[i:j])

    def pack(self, y):
        return pack('<B', y) if self._bits ==8 else pack('<h', y)


class Recorder(object):
    def __init__(self, frequency=44100, bits=16):
        self._sample = io.BytesIO()
        self._sample_frequency = frequency
        self._bits = bits

        self._base_frequency = 1200.0
        self._phase = math.radians(180)

        self._base_sine = None
        self._fast_sine = None
        self._base_silence = None
        self._fast_silence = None
        self._recalculate = True

    def set_base_frequency(self, frequency):
        self._base_frequency = frequency
        self._recalculate = True

    def get_base_frequency(self):
        return self._base_frequency

    base_frequency = property(get_base_frequency, set_base_frequency)

    def set_phase(self, phase):
        self._phase = math.radians(phase)
        self._recalculate = True

    def get_phase(self):
        return self._phase

    phase = property(get_phase, set_phase)

    def low_pulse(self, fast=False, silent=False):
        if self._recalculate:
            self.calculate_sines()
            self._recalculate = False

        if fast:
            if silent:
                self._sample.write(self._fast_silence.low_pulse)
            else:
                self._sample.write(self._fast_sine.low_pulse)
        else:
            if silent:
                self._sample.write(self._base_silence.low_pulse)
            else:
                self._sample.write(self._base_sine.low_pulse)

    def high_pulse(self, fast=False, silent=False):
        if self._recalculate:
            self.calculate_sines()
            self._recalculate = False

        if fast:
            if silent:
                self._sample.write(self._fast_silence.high_pulse)
            else:
                self._sample.write(self._fast_sine.high_pulse)
        else:
            if silent:
                self._sample.write(self._base_silence.high_pulse)
            else:
                self._sample.write(self._base_sine.high_pulse)

    def calculate_sines(self):
        self._base_sine = Cycle(self._base_frequency, self._phase, self._sample_frequency, self._bits)
        self._fast_sine = Cycle(2 * self._base_frequency, self._phase, self._sample_frequency, self._bits)
        self._base_silence = Cycle(self._base_frequency, self._phase, self._sample_frequency, self._bits, amplitude=0)
        self._fast_silence = Cycle(2 * self._base_frequency, self._phase, self._sample_frequency, self._bits, amplitude=0)

    def write_riff(self, stream):
        size = self._sample.tell()

        stream.write(b'RIFF')
        stream.write(pack('<I', 4 + 8 + 16 + 8 + size))

        # 4 bytes
        stream.write(b'WAVE')

        # 8 bytes
        stream.write(b'fmt ')
        stream.write(pack('<I', 16))

        # 16 bytes
        stream.write(pack('<h', 1))
        stream.write(pack('<h', 1))
        stream.write(pack('<I', self._sample_frequency))
        stream.write(pack('<I', self._sample_frequency * (1 if self._bits == 8 else 2)))
        stream.write(pack('<h', self._bits // 8))
        stream.write(pack('<h', self._bits))

        # 8 bytes
        stream.write(b'data')
        stream.write(pack('<I', size))

        # size bytes
        stream.write(self._sample.getbuffer())


def parse_arguments():
    parser = ArgumentParser()
    parser.add_argument('ueffile', help='the UEF file to convert')
    parser.add_argument('--frequency', help='the sample frequency in Hz', type=int, choices=[11025, 22050, 44100], default=44100)
    parser.add_argument('--bits', help='the sample resolution in bits', type=int, choices=[8, 16], default=16)
    return parser.parse_args()


def main():
    args = parse_arguments()

    recordables = []
    transformer = Transformer()
    for chunk in chunks(args.ueffile):
        recordables.extend(transformer.transform(chunk))

    print('ignored: ' + ', '.join(['&{:04x}'.format(i) for i in transformer.ignored]))

    recorder = Recorder(args.frequency, args.bits)
    for r in recordables:
        #print(r)
        r.record(recorder)

    with open(args.ueffile + '.wav', 'wb') as f:
        recorder.write_riff(f)


if __name__ == '__main__':
    main()
