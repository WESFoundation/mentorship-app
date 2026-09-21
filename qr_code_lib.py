"""
Standalone QR Code Generator in pure Python (zero external dependencies).
Generates valid QR code matrices and exports as PNG or SVG.
"""
import zlib
import struct


class QRCode:
    def __init__(self, data, error_correction='M'):
        self.data = data.encode('utf-8') if isinstance(data, str) else data
        self.ec_level = error_correction.upper()
        self.version, self.matrix = self._generate()

    # Generator polynomials & GF(256) math
    GF_EXP = [0] * 512
    GF_LOG = [0] * 256
    _initialized = False

    @classmethod
    def _init_gf(cls):
        if cls._initialized:
            return
        x = 1
        for i in range(255):
            cls.GF_EXP[i] = x
            cls.GF_EXP[i + 255] = x
            cls.GF_LOG[x] = i
            x <<= 1
            if x >= 256:
                x ^= 0x11d
        cls._initialized = True

    @classmethod
    def _gf_mul(cls, x, y):
        if x == 0 or y == 0:
            return 0
        return cls.GF_EXP[cls.GF_LOG[x] + cls.GF_LOG[y]]

    @classmethod
    def _rs_poly(cls, nsym):
        g = [1]
        for i in range(nsym):
            g = cls._poly_mul(g, [1, cls.GF_EXP[i]])
        return g

    @classmethod
    def _poly_mul(cls, p, q):
        r = [0] * (len(p) + len(q) - 1)
        for i, pi in enumerate(p):
            for j, qj in enumerate(q):
                r[i + j] ^= cls._gf_mul(pi, qj)
        return r

    @classmethod
    def _rs_encode(cls, msg, nsym):
        cls._init_gf()
        gen = cls._rs_poly(nsym)
        msg_out = list(msg) + [0] * nsym
        for i in range(len(msg)):
            coef = msg_out[i]
            if coef != 0:
                for j in range(len(gen)):
                    msg_out[i + j] ^= cls._gf_mul(gen[j], coef)
        return msg_out[len(msg):]

    # Capacity table: (version, ec_level) -> (data_bytes, ec_bytes_per_block, num_blocks)
    # Supporting Versions 1 to 5, which handles URLs up to 106 characters in M error correction
    TABLE = {
        # Version 1 (21x21)
        (1, 'L'): (19, 7, 1), (1, 'M'): (16, 10, 1), (1, 'Q'): (13, 13, 1), (1, 'H'): (9, 17, 1),
        # Version 2 (25x25)
        (2, 'L'): (34, 10, 1), (2, 'M'): (28, 16, 1), (2, 'Q'): (22, 22, 1), (2, 'H'): (16, 28, 1),
        # Version 3 (29x29)
        (3, 'L'): (55, 15, 1), (3, 'M'): (44, 26, 1), (3, 'Q'): (34, 18, 2), (3, 'H'): (26, 22, 2),
        # Version 4 (33x33)
        (4, 'L'): (80, 20, 1), (4, 'M'): (64, 18, 2), (4, 'Q'): (48, 26, 2), (4, 'H'): (36, 16, 4),
        # Version 5 (37x37)
        (5, 'L'): (108, 26, 1), (5, 'M'): (86, 24, 2), (5, 'Q'): (62, 18, 4), (5, 'H'): (46, 22, 4),
        # Version 6 (41x41)
        (6, 'L'): (136, 18, 2), (6, 'M'): (108, 16, 4), (6, 'Q'): (76, 24, 4), (6, 'H'): (60, 28, 4),
    }

    # Format info bits: (ec_level, mask) -> 15 bits
    FORMAT_INFO = {
        ('M', 0): 0x5412, ('M', 1): 0x5125, ('M', 2): 0x5e7c, ('M', 3): 0x5b4b,
        ('M', 4): 0x45f9, ('M', 5): 0x40ce, ('M', 6): 0x4f97, ('M', 7): 0x4aa0,
        ('L', 0): 0x77c4, ('L', 1): 0x72f3, ('L', 2): 0x7daa, ('L', 3): 0x789d,
        ('L', 4): 0x662f, ('L', 5): 0x6318, ('L', 6): 0x6c41, ('L', 7): 0x6976,
    }

    ALIGNMENT_PATTERNS = {
        2: [6, 18],
        3: [6, 22],
        4: [6, 26],
        5: [6, 30],
        6: [6, 34],
    }

    def _generate(self):
        # Choose version
        chosen_version = None
        for v in range(1, 7):
            capacity, _, _ = self.TABLE.get((v, self.ec_level), (0, 0, 0))
            if len(self.data) + 2 <= capacity:  # byte mode overhead: 4 bits mode + 8 bits length = 12 bits <= 2 bytes
                chosen_version = v
                break
        if not chosen_version:
            chosen_version = 6

        total_data_bytes, ec_bytes_per_block, num_blocks = self.TABLE[(chosen_version, self.ec_level)]

        # Encode data in 8-bit byte mode
        bits = []
        # Mode indicator: 0100 for Byte mode
        bits.extend([0, 1, 0, 0])
        # Character count indicator (8 bits for version 1-9)
        char_count = len(self.data)
        for i in range(7, -1, -1):
            bits.append((char_count >> i) & 1)
        # Data bytes
        for b in self.data:
            for i in range(7, -1, -1):
                bits.append((b >> i) & 1)

        # Terminator
        bit_capacity = total_data_bytes * 8
        for _ in range(min(4, bit_capacity - len(bits))):
            bits.append(0)

        # Pad to multiple of 8
        while len(bits) % 8 != 0:
            bits.append(0)

        # Pad bytes 0xEC, 0x11
        pad_bytes = [0xEC, 0x11]
        pad_idx = 0
        while len(bits) < bit_capacity:
            pb = pad_bytes[pad_idx % 2]
            for i in range(7, -1, -1):
                bits.append((pb >> i) & 1)
            pad_idx += 1

        # Convert bits to bytes
        data_bytes = []
        for i in range(0, len(bits), 8):
            val = 0
            for bit in bits[i:i+8]:
                val = (val << 1) | bit
            data_bytes.append(val)

        # Split into blocks and calculate RS code
        block_len = total_data_bytes // num_blocks
        data_blocks = []
        ec_blocks = []
        for i in range(num_blocks):
            block = data_bytes[i * block_len : (i + 1) * block_len]
            data_blocks.append(block)
            ec_blocks.append(self._rs_encode(block, ec_bytes_per_block))

        # Interleave
        final_bytes = []
        for i in range(block_len):
            for b in data_blocks:
                final_bytes.append(b[i])
        for i in range(ec_bytes_per_block):
            for eb in ec_blocks:
                final_bytes.append(eb[i])

        # Convert to bit stream
        final_bits = []
        for b in final_bytes:
            for i in range(7, -1, -1):
                final_bits.append((b >> i) & 1)

        # Build matrix
        size = 17 + 4 * chosen_version
        matrix = [[None] * size for _ in range(size)]
        reserved = [[False] * size for _ in range(size)]

        # Place finder patterns
        def place_finder(x0, y0):
            for r in range(7):
                for c in range(7):
                    val = 1 if (r in (0, 6) or c in (0, 6) or (2 <= r <= 4 and 2 <= c <= 4)) else 0
                    matrix[y0 + r][x0 + c] = val
                    reserved[y0 + r][x0 + c] = True

        place_finder(0, 0)
        place_finder(size - 7, 0)
        place_finder(0, size - 7)

        # Separators
        for i in range(8):
            for (x, y) in [(7, i), (i, 7), (size - 8, i), (size - 1 - i, 7), (7, size - 8 + i), (i, size - 8)]:
                if 0 <= x < size and 0 <= y < size and not reserved[y][x]:
                    matrix[y][x] = 0
                    reserved[y][x] = True

        # Alignment patterns for version >= 2
        if chosen_version in self.ALIGNMENT_PATTERNS:
            coords = self.ALIGNMENT_PATTERNS[chosen_version]
            for cx in coords:
                for cy in coords:
                    if reserved[cy][cx]:
                        continue
                    for r in range(-2, 3):
                        for c in range(-2, 3):
                            val = 1 if (abs(r) == 2 or abs(c) == 2 or (r == 0 and c == 0)) else 0
                            matrix[cy + r][cx + c] = val
                            reserved[cy + r][cx + c] = True

        # Timing patterns
        for i in range(8, size - 8):
            val = 1 if i % 2 == 0 else 0
            if not reserved[6][i]:
                matrix[6][i] = val
                reserved[6][i] = True
            if not reserved[i][6]:
                matrix[i][6] = val
                reserved[i][6] = True

        # Dark module
        matrix[size - 8][8] = 1
        reserved[size - 8][8] = True

        # Reserve format info areas
        for i in range(9):
            if not reserved[8][i]: reserved[8][i] = True
            if not reserved[i][8]: reserved[i][8] = True
        for i in range(8):
            if not reserved[8][size - 1 - i]: reserved[8][size - 1 - i] = True
            if not reserved[size - 1 - i][8]: reserved[size - 1 - i][8] = True

        # Place data bits
        bit_idx = 0
        direction = -1  # up
        x = size - 1
        while x > 0:
            if x == 6:
                x -= 1  # skip vertical timing pattern
            y_range = range(size - 1, -1, -1) if direction == -1 else range(size)
            for y in y_range:
                for c in [x, x - 1]:
                    if not reserved[y][c]:
                        bit = final_bits[bit_idx] if bit_idx < len(final_bits) else 0
                        matrix[y][c] = bit
                        bit_idx += 1
            direction = -direction
            x -= 2

        # Apply Mask 0: (row + column) % 2 == 0
        mask_idx = 0
        for y in range(size):
            for x in range(size):
                if not reserved[y][x]:
                    if (y + x) % 2 == 0:
                        matrix[y][x] ^= 1

        # Place format info
        fmt = self.FORMAT_INFO.get((self.ec_level, mask_idx), 0x5412)
        # 15 bits of format info
        fmt_bits = [(fmt >> (14 - i)) & 1 for i in range(15)]

        # Around top-left
        seq1 = [(8, 0), (8, 1), (8, 2), (8, 3), (8, 4), (8, 5), (8, 7), (8, 8),
                (7, 8), (5, 8), (4, 8), (3, 8), (2, 8), (1, 8), (0, 8)]
        for idx, (px, py) in enumerate(seq1):
            matrix[py][px] = fmt_bits[idx]

        # Bottom-left (bits 0-6) & top-right (bits 7-14)
        seq2 = [(8, size - 1 - i) for i in range(7)] + [(size - 8 + i, 8) for i in range(8)]
        for idx, (px, py) in enumerate(seq2):
            matrix[py][px] = fmt_bits[idx]

        return chosen_version, matrix

    def to_svg(self, box_size=8, border=4, color="#1e40af"):
        size = len(self.matrix)
        total_size = (size + border * 2) * box_size
        rects = []
        for y in range(size):
            for x in range(size):
                if self.matrix[y][x] == 1:
                    rx = (x + border) * box_size
                    ry = (y + border) * box_size
                    rects.append(f'<rect x="{rx}" y="{ry}" width="{box_size}" height="{box_size}" fill="{color}"/>')
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total_size} {total_size}" '
            f'width="{total_size}" height="{total_size}">\n'
            f'<rect width="{total_size}" height="{total_size}" fill="#ffffff"/>\n'
            + '\n'.join(rects) +
            '\n</svg>'
        )

    def to_png(self, box_size=8, border=4, color=(30, 64, 175)):
        matrix_size = len(self.matrix)
        img_size = (matrix_size + border * 2) * box_size
        
        # Build RGB pixel buffer
        pixels = []
        white = bytes([255, 255, 255])
        fg = bytes(color)
        
        for y in range(img_size):
            my = y // box_size - border
            row = []
            for x in range(img_size):
                mx = x // box_size - border
                if 0 <= my < matrix_size and 0 <= mx < matrix_size and self.matrix[my][mx] == 1:
                    row.append(fg)
                else:
                    row.append(white)
            pixels.append(b''.join(row))

        def chunk(tag, data):
            return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)

        raw = b''.join(b'\x00' + row for row in pixels)
        idat = zlib.compress(raw, 9)
        ihdr = struct.pack('>IIBBBBB', img_size, img_size, 8, 2, 0, 0, 0)
        return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr) + chunk(b'IDAT', idat) + chunk(b'IEND', b'')
