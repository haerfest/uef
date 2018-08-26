#!/usr/bin/env python

from __future__ import print_function

from argparse import ArgumentParser
from contextlib import contextmanager
from datetime import timedelta
from struct import pack, unpack

import gzip
import io
import math
import os
import string
import sys
import zipfile


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
    def __init__(self, cycle_count):
        self.cycle_count = cycle_count

    def __repr__(self):
        return '<IntegerGap {} cycles>'.format(self.cycle_count)

    def record(self, recorder):
        for _ in range(self.cycle_count):
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


class Marker(object):
    def __init__(self, microseconds, description):
        self.microseconds = microseconds
        self.description = description

    def __repr__(self):
        return '<Marker {}" {}">'.format(self.timestamp, self.printable)

    @property
    def timestamp(self):
        seconds = int(self.microseconds // 1000000)
        minutes = int(seconds // 60)
        seconds %= 60
        return '{:02d}:{:02d}'.format(minutes, seconds)

    @property
    def printable(self):
        return ''.join(c if ' ' <= c <= '~' else '?' for c in self.description)


class Chunk(object):
    '''
    Base chunk representation. Keeps track of its identifier and data, and
    specifies an interface for other chunks to turn themselves into a sequence
    of Recordables for recording on a Recorder.
    '''
    def __init__(self, identifier, data):
        self.identifier = identifier
        self.data = data

    @property
    def recordables(self):
        return []

    def record(self, recorder):
        for recordable in self.recordables:
            recordable.record(recorder)

    def bits(self, byte):
        '''
        Helper method to turn a byte into a sequence of recordable bits.
        '''
        return [OneBit() if byte & (1 << i) else ZeroBit() for i in range(8)]

    def __repr__(self):
        s = ' '.join('{:02x}'.format(x) for x in self.data[:10])
        return '<Chunk &{:04x} {} bytes: {} ...>'.format(self.identifier, len(self.data), s)


class Chunk0100(Chunk):
    '''
    Implicit start/stop bit tape data block.
    '''
    @property
    def recordables(self):
        recordables = []
        for byte in self.data:
            recordables.append(StartBit())
            recordables.extend(self.bits(byte))
            recordables.append(StopBit())

        return recordables

    def record(self, recorder):
        if self.data[0] == ord('*'):
            filename, block = self.parse_block()
            if block == 0:
                recorder.markers.append(Marker(recorder.microseconds, filename))

        super(Chunk0100, self).record(recorder)

    def parse_block(self):
        filename = ''
        for i in range(10):
            ascii = self.data[1 + i]
            if ascii == 0:
                break
            filename += chr(ascii)
        block = unpack('<H', self.data[i + 10:i + 12])[0]
        return filename, block

    def __repr__(self):
        return '<Chunk &0100 {} ...>'.format(self.data[:20])


class Chunk0104(Chunk):
    '''
    Defined tape format data block.
    '''
    @property
    def recordables(self):
        data_bit_count, parity, stop_bit_count = unpack('<Bcb', self.data[:3])

        recordables = []
        for byte in self.data[3:]:
            recordables.append(StartBit())

            bits = self.bits(byte)[:data_bit_count]
            recordables.extend(bits)

            odd_parity = False
            for bit in bits:
                odd_parity ^= isinstance(bit, OneBit)
            if parity == b'E':
                recordables.append(OneBit() if odd_parity else ZeroBit())
            elif parity == b'O':
                recordables.append(ZeroBit() if odd_parity else OneBit())

            recordables.extend([StopBit()] * abs(stop_bit_count))

            if stop_bit_count < 0:
                recordables.append(FastCycle())

        return recordables


class Chunk0110(Chunk):
    '''
    Carrier tone.
    '''
    @property
    def recordables(self):
        cycle_count = unpack('<H', self.data)[0]
        return [Carrier(cycle_count)]


class Chunk0111(Chunk):
    '''
    Carrier tone with dummy byte.
    '''
    @property
    def recordables(self):
        length1, length2 = unpack('<HH', self.data)
        return [Carrier(length1), StartBit()] + self.bits(0xAA) + [StopBit(), Carrier(length2)]


class Chunk0112(Chunk):
    '''
    Integer gap.
    '''
    @property
    def recordables(self):
        n = unpack('<H', self.data)[0]
        return [IntegerGap(n)]


class Chunk0113(Chunk):
    '''
    Change of base frequency.
    '''
    @property
    def recordables(self):
        frequency = unpack('<f', self.data)[0]
        return [BaseFrequencyChange(frequency)]


class Chunk0114(Chunk):
    '''
    Security cycles.
    '''
    @property
    def recordables(self):
        upper, lower = unpack('<HB', self.data[:3])
        cycle_count = upper << 8 + lower

        bits = []
        for byte in self.data[5:]:
            bits.extend(self.bits(byte))
        recordables = [FastCycle() if isinstance(bit, OneBit) else SlowCycle() for _, bit in zip(range(cycle_count), bits)]

        if recordables and self.data[3] == b'P':
            recordables[0] = HighPulse(recordables[0].value)
        if recordables and self.data[4] == b'P':
            recordables[-1] = LowPulse(recordables[-1].value)

        return recordables


class Chunk0115(Chunk):
    '''
    Phase change.
    '''
    @property
    def recordables(self):
        phase = unpack('<H', self.data)[0]
        return [PhaseChange(phase)]


class Chunk0116(Chunk):
    '''
    Floating point gap.
    '''
    @property
    def recordables(self):
        seconds = unpack('<f', self.data)[0]
        return [FloatGap(seconds)]


class ChunkFactory(object):
    @staticmethod
    def create(identifier, data):
        class_name = 'Chunk{:04x}'.format(identifier)
        class_ = getattr(sys.modules[__name__], class_name, None)
        return class_(identifier, data) if class_ else None


class FileReader(object):
    @staticmethod
    def open(filename):
        return open(filename, 'rb')


class ZipReader(object):
    @staticmethod
    def open(file):
        if not zipfile.is_zipfile(file):
            file.seek(0)
            return file

        zip = zipfile.ZipFile(file, 'r')
        uefs = [filename for filename in zip.namelist() if os.path.splitext(filename)[1].lower() == '.uef']
        if not uefs:
            raise Exception('no UEF files found in ZIP archive')
        return zip.open(uefs[0], 'r')


class GzipReader(object):
    @staticmethod
    def open(file):
        f = gzip.open(file)
        try:
            f.peek(2)
            return f
        except OSError:
            return file


class ChunkReader(object):
    def __init__(self, filename):
        self.filename = filename
        self.encountered = set()
        self.ignored = set()

    @property
    def chunks(self):
        with self.open() as uef:
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

                chunk = ChunkFactory.create(identifier, data)
                if not chunk:
                    self.ignored.add(identifier)
                    continue

                self.encountered.add(identifier)
                yield chunk

    def open(self):
        return GzipReader.open(ZipReader.open(FileReader.open(self.filename)))


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

        self._frequency = frequency
        self._bits = bits
        self._phase = phase

        self._samples = []
        self._sample_count = math.ceil(sample_frequency // frequency)

        for t in range(self._sample_count):
            y = math.sin(phase + 2 * math.pi * t / self._sample_count)
            self._samples.append(math.trunc(silence_level + amplitude * y))

    @property
    def pulse_duration(self):
        '''
        Returns the duration of a single pulse in microseconds.
        '''
        return 500000 // self._frequency

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
        return pack('<B', y) if self._bits == 8 else pack('<h', y)


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

        self._microseconds = 0
        self._markers = []

    @property
    def markers(self):
        return self._markers

    @property
    def microseconds(self):
        return self._microseconds

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
            sample = self._fast_silence if silent else self._fast_sine
        else:
            sample = self._base_silence if silent else self._base_sine

        self._sample.write(sample.low_pulse)
        self._microseconds += sample.pulse_duration

    def high_pulse(self, fast=False, silent=False):
        if self._recalculate:
            self.calculate_sines()
            self._recalculate = False

        if fast:
            sample = self._fast_silence if silent else self._fast_sine
        else:
            sample = self._base_silence if silent else self._base_sine

        self._sample.write(sample.high_pulse)
        self._microseconds += sample.pulse_duration

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
    parser.add_argument('--debug', help='enable debug output', action='store_true')
    parser.add_argument('--norecord', help='do not record a wave file', action='store_true')
    return parser.parse_args()


def main():
    args = parse_arguments()

    recorder = Recorder(args.frequency, args.bits)

    reader = ChunkReader(args.ueffile)
    print(os.path.basename(args.ueffile))
    for chunk in reader.chunks:
        if args.debug:
            print(chunk)
        if not args.norecord:
            chunk.record(recorder)

    print('Chunk IDs encountered ... ' + ', '.join(['&{:04x}'.format(i) for i in sorted(reader.encountered)]))
    print('Chunk IDs ignored ....... ' + ', '.join(['&{:04x}'.format(i) for i in sorted(reader.ignored)]))
    print('Markers:')
    for marker in recorder.markers:
        print('  {} {}'.format(marker.timestamp, marker.printable))

    if not args.norecord:
        outfile = os.path.splitext(os.path.basename(args.ueffile))[0] + '.wav'
        with open(outfile, 'wb') as f:
            recorder.write_riff(f)


if __name__ == '__main__':
    main()
