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

# b6 c0
# print(pack('>H', crc(bytes(int('0x' + s, 16)
#            for s in '41 52 43 41 44 49 41 4e 53 00 00 0e 00 00 23 80 00 00 00 00 00 01 00 00 00 00 00'.split()))))


parser = ArgumentParser()
parser.add_argument('--load_addr', help='load address of binary',
                    default='0x2000')
parser.add_argument('--exec_addr', help='execution address of binary')
parser.add_argument('--bin', help='the binary file to include')
parser.add_argument('--uef', help='the UEF file to write the binary to')
args = parser.parse_args()

args.exec_addr = args.exec_addr or args.load_addr
args.load_addr = int(args.load_addr, 0)
args.exec_addr = int(args.exec_addr, 0)

with open(args.bin, 'rb') as f:
    data = f.read()

with open(args.uef, 'wb') as uef:
    # magic value
    uef.write(b'UEF File!\x00')

    # spec version 0.1
    uef.write(b'\x01\x00')

    # carrier tone
    uef.write(pack('<HIH', 0x0110, 2, 1500))
    uef.write(pack('<HIB', 0x0100, 1, 0xdc))
    uef.write(pack('<HIH', 0x0110, 2, 1500))

    block_nr = 0
    while block_nr * 256 < len(data):
        i = block_nr * 256
        j = min(i + 256, len(data))
        block = data[i:j]
        block_size = j - i
        block_flag = 0x80 if j == len(data) else 0
        header = str.encode(args.bin[:10].upper())
        header += pack('<BIIHHBI', 0, args.load_addr, args.exec_addr, block_nr,
                       block_size, block_flag, 0)

        # data block
        uef.write(pack('<HI', 0x0100, 1 + len(header) + 2 + block_size + 2))
        uef.write(b'*')
        uef.write(header)
        uef.write(pack('>H', crc(header)))
        uef.write(block)
        uef.write(pack('>H', crc(block)))

        # carrier tone
        uef.write(pack('<HIH', 0x0110, 2, 600))

        block_nr += 1

    # integer gap
    uef.write(pack('<HIH', 0x0112, 2, 600))
