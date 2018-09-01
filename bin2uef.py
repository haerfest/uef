import sys

from argparse import ArgumentParser
from struct import pack


def crc(bytes):
    crc = 0
    for c in bytes:
        crc = ((c ^ (crc >> 8)) << 8) | (crc & 0x00FF)
        for _ in range(8):
            if crc & 0x8000:
                crc = crc ^ 0x0810
                t = 1
            else:
                t = 0
            crc = (crc * 2 + t) & 0xFFFF
    return crc


def parse_args():
    parser = ArgumentParser()
    parser.add_argument('-n', '--name',
                        help='name to record on tape (default: FILE)',
                        default='FILE')
    parser.add_argument('-l', '--load', metavar='ADDRESS', dest='load_addr',
                        help='load address (prepend 0x for hex)',
                        required=True)
    parser.add_argument('-e', '--exec', metavar='ADDRESS', dest='exec_addr',
                        help='execution address (prepend 0x for hex)')
    args = parser.parse_args()

    args.exec_addr = args.exec_addr or args.load_addr
    args.load_addr = int(args.load_addr, 0)
    args.exec_addr = int(args.exec_addr, 0)

    return args


def main():
    args = parse_args()

    # magic value
    sys.stdout.buffer.write(b'UEF File!\x00')

    # spec version 0.1
    sys.stdout.buffer.write(b'\x01\x00')

    # carrier tone
    sys.stdout.buffer.write(pack('<HIH', 0x0110, 2, 1500))
    sys.stdout.buffer.write(pack('<HIB', 0x0100, 1, 0xdc))
    sys.stdout.buffer.write(pack('<HIH', 0x0110, 2, 1500))

    data = sys.stdin.buffer.read()

    block_nr = 0
    while block_nr * 256 < len(data):
        i = block_nr * 256
        j = min(i + 256, len(data))
        block = data[i:j]

        # mark last block
        block_flag = 0x80 if j == len(data) else 0

        # construct data header
        header = str.encode(args.name[:10])
        header += pack('<BIIHHBI', 0, args.load_addr, args.exec_addr, block_nr,
                       len(block), block_flag, 0)

        # write data chunk lead
        sys.stdout.buffer.write(
            pack('<HI', 0x0100, 1 + len(header) + 2 + len(block) + 2))

        # write data
        sys.stdout.buffer.write(b'*')
        sys.stdout.buffer.write(header)
        sys.stdout.buffer.write(pack('>H', crc(header)))
        sys.stdout.buffer.write(block)
        sys.stdout.buffer.write(pack('>H', crc(block)))

        # carrier tone
        sys.stdout.buffer.write(pack('<HIH', 0x0110, 2, 600))

        block_nr += 1

    # integer gap
    sys.stdout.buffer.write(pack('<HIH', 0x0112, 2, 600))

    
if __name__ == '__main__':
    main()
