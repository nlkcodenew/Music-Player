"""Minimal QR Code generator (byte mode only, stdlib only).

Encodes short ASCII URLs such as ``http://192.168.1.10:8080/`` so the
TrimUI screen can show a scannable code with zero third-party
dependencies. Only versions 1-10 are supported, which is plenty for a
LAN URL (version 10 holds 271 byte-mode bytes at ECC level L).
"""

_ECC_FORMAT_BITS = (1, 0, 3, 2)  # L, M, Q, H
_ECC_LEVELS = ("L", "M", "Q", "H")

# Total data codewords per version (1-10) and ECC level (L, M, Q, H).
_DATA_CODEWORDS = (
    (19, 16, 13, 9),
    (34, 28, 22, 16),
    (55, 44, 34, 26),
    (80, 64, 48, 36),
    (108, 86, 62, 46),
    (136, 108, 76, 60),
    (156, 124, 88, 66),
    (194, 154, 110, 86),
    (232, 182, 132, 100),
    (274, 216, 154, 122),
)

# ECC codewords per block.
_ECC_PER_BLOCK = (
    (7, 10, 13, 17),
    (10, 16, 22, 28),
    (15, 26, 18, 22),
    (20, 18, 26, 16),
    (26, 24, 18, 22),
    (18, 16, 24, 28),
    (20, 18, 18, 26),
    (24, 22, 22, 26),
    (30, 22, 20, 24),
    (18, 26, 24, 28),
)

# Number of error correction blocks.
_NUM_BLOCKS = (
    (1, 1, 1, 1),
    (1, 1, 1, 1),
    (1, 1, 2, 2),
    (1, 2, 2, 4),
    (1, 2, 4, 4),
    (2, 4, 4, 4),
    (2, 4, 6, 5),
    (2, 4, 6, 6),
    (2, 5, 8, 8),
    (4, 5, 8, 8),
)

_REMAINDER_BITS = (0, 7, 7, 7, 7, 7, 7, 0, 0, 0)

_ALIGNMENT_POSITIONS = (
    (),
    (6, 18),
    (6, 22),
    (6, 26),
    (6, 30),
    (6, 34),
    (6, 22, 38),
    (6, 24, 42),
    (6, 26, 46),
    (6, 28, 50),
)


def _gf_multiply(x, y):
    result = 0
    for _ in range(8):
        if y & 1:
            result ^= x
        high = x & 0x80
        x = (x << 1) & 0xFF
        if high:
            x ^= 0x1D  # 0x11D without the x^8 term
        y >>= 1
    return result


def _reed_solomon_divisor(degree):
    coefficients = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for index in range(len(coefficients)):
            coefficients[index] = _gf_multiply(coefficients[index], root)
            if index + 1 < len(coefficients):
                coefficients[index] ^= coefficients[index + 1]
        root = _gf_multiply(root, 2)
    return coefficients


def _reed_solomon_remainder(data, divisor):
    result = [0] * len(divisor)
    for value in data:
        factor = value ^ result.pop(0)
        result.append(0)
        for index, coefficient in enumerate(divisor):
            result[index] ^= _gf_multiply(coefficient, factor)
    return result


def _format_bits(ecc_index, mask):
    data = (_ECC_FORMAT_BITS[ecc_index] << 3) | mask
    remainder = data
    for _ in range(10):
        remainder = (remainder << 1) ^ ((remainder >> 9) * 0x537)
    return ((data << 10) | remainder) ^ 0x5412


def _version_bits(version):
    remainder = version
    for _ in range(12):
        remainder = (remainder << 1) ^ ((remainder >> 11) * 0x1F25)
    return (version << 12) | remainder


def _apply_mask(mask, x, y):
    if mask == 0:
        return (x + y) % 2 == 0
    if mask == 1:
        return y % 2 == 0
    if mask == 2:
        return x % 3 == 0
    if mask == 3:
        return (x + y) % 3 == 0
    if mask == 4:
        return (x // 3 + y // 2) % 2 == 0
    if mask == 5:
        return (x * y) % 2 + (x * y) % 3 == 0
    if mask == 6:
        return ((x * y) % 2 + (x * y) % 3) % 2 == 0
    if mask == 7:
        return ((x + y) % 2 + (x * y) % 3) % 2 == 0
    raise ValueError("bad mask")


def _penalty(modules):
    size = len(modules)
    total = 0
    for first in range(size):
        dark = False
        run = 0
        for second in range(size):
            if modules[first][second] == dark:
                run += 1
            else:
                if run >= 5:
                    total += 3 + (run - 5)
                dark = not dark
                run = 1
        if run >= 5:
            total += 3 + (run - 5)
        dark = False
        run = 0
        for second in range(size):
            if modules[second][first] == dark:
                run += 1
            else:
                if run >= 5:
                    total += 3 + (run - 5)
                dark = not dark
                run = 1
        if run >= 5:
            total += 3 + (run - 5)
    for y in range(size - 1):
        for x in range(size - 1):
            color = modules[y][x]
            if (modules[y][x + 1] == color and modules[y + 1][x] == color
                    and modules[y + 1][x + 1] == color):
                total += 3
    for y in range(size):
        for x in range(size - 6):
            if (modules[y][x] and not modules[y][x + 1] and modules[y][x + 2]
                    and modules[y][x + 3] and modules[y][x + 4]
                    and not modules[y][x + 5] and modules[y][x + 6]):
                total += 40
    for x in range(size):
        for y in range(size - 6):
            if (modules[y][x] and not modules[y + 1][x] and modules[y + 2][x]
                    and modules[y + 3][x] and modules[y + 4][x]
                    and not modules[y + 5][x] and modules[y + 6][x]):
                total += 40
    dark = sum(row.count(True) for row in modules)
    total_modules = size * size
    kink = (abs(dark * 20 - total_modules * 10) + total_modules - 1) // total_modules - 1
    total += kink * 10
    return total


class QrCode(object):
    """A QR symbol: ``size`` modules wide, ``get(x, y)`` reads darkness."""

    def __init__(self, size, modules):
        self.size = size
        self._modules = modules

    def get(self, x, y):
        return self._modules[y][x]


def _make_function_modules(version):
    size = 21 + (version - 1) * 4
    modules = [[False] * size for _ in range(size)]
    marked = [[False] * size for _ in range(size)]

    def set_module(x, y, dark):
        modules[y][x] = dark
        marked[y][x] = True

    def finder(cx, cy):
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                x, y = cx + dx, cy + dy
                if 0 <= x < size and 0 <= y < size:
                    set_module(x, y, max(abs(dx), abs(dy)) != 2 and max(abs(dx), abs(dy)) != 4)

    finder(3, 3)
    finder(size - 4, 3)
    finder(3, size - 4)

    for index in range(size):
        if not marked[index][6]:
            set_module(6, index, index % 2 == 0)
        if not marked[6][index]:
            set_module(index, 6, index % 2 == 0)

    for positions in (_ALIGNMENT_POSITIONS[version - 1],):
        if not positions:
            continue
        first, last = positions[0], positions[-1]
        for cx in positions:
            for cy in positions:
                if (cx, cy) in ((first, first), (first, last), (last, first)):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        set_module(cx + dx, cy + dy, max(abs(dx), abs(dy)) != 1)

    set_module(4 * version + 9, 8, True)
    if not marked[size - 8][8]:
        set_module(8, size - 8, False)
    if version >= 7:
        bits = _version_bits(version)
        for index in range(18):
            dark = bool((bits >> index) & 1)
            set_module(size - 11 + index % 3, index // 3, dark)
            set_module(index // 3, size - 11 + index % 3, dark)
    return modules, marked


def _draw_format(modules, marked, size, bits):
    def set_module(x, y, dark):
        modules[y][x] = dark
        marked[y][x] = True

    for index in range(6):
        set_module(8, index, bool((bits >> index) & 1))
    set_module(8, 7, bool((bits >> 6) & 1))
    set_module(8, 8, bool((bits >> 7) & 1))
    set_module(7, 8, bool((bits >> 8) & 1))
    for index in range(9, 15):
        set_module(14 - index, 8, bool((bits >> index) & 1))
    for index in range(8):
        set_module(size - 1 - index, 8, bool((bits >> index) & 1))
    for index in range(8, 15):
        set_module(8, size - 15 + index, bool((bits >> index) & 1))
    set_module(size - 8, 8, True)


def encode(text, ecc="M"):
    """Encode ASCII ``text`` and return a QrCode (versions 1-10)."""
    if ecc not in _ECC_LEVELS:
        raise ValueError("bad ecc level")
    ecc_index = _ECC_LEVELS.index(ecc)
    try:
        data = text.encode("ascii")
    except (UnicodeEncodeError, AttributeError):
        raise ValueError("only ASCII text is supported")
    for version in range(1, 11):
        capacity = _DATA_CODEWORDS[version - 1][ecc_index] * 8
        count_bits = 8 if version < 10 else 16
        if 4 + count_bits + len(data) * 8 <= capacity:
            break
    else:
        raise ValueError("text too long")
    count_bits = 8 if version < 10 else 16
    out = [0, 1, 0, 0]
    for index in range(count_bits - 1, -1, -1):
        out.append((len(data) >> index) & 1)
    for byte in data:
        for index in range(7, -1, -1):
            out.append((byte >> index) & 1)
    capacity = _DATA_CODEWORDS[version - 1][ecc_index] * 8
    terminator = min(4, capacity - len(out))
    out.extend([0] * terminator)
    while len(out) % 8:
        out.append(0)
    codewords = []
    for index in range(0, len(out), 8):
        codewords.append(int("".join(str(bit) for bit in out[index:index + 8]), 2))
    pad = 0xEC
    while len(codewords) < _DATA_CODEWORDS[version - 1][ecc_index]:
        codewords.append(pad)
        pad ^= 0xEC ^ 0x11

    blocks = _NUM_BLOCKS[version - 1][ecc_index]
    ecc_len = _ECC_PER_BLOCK[version - 1][ecc_index]
    total_data = len(codewords)
    short_len = total_data // blocks
    num_long = total_data % blocks
    groups = []
    offset = 0
    for index in range(blocks):
        length = short_len + (1 if index >= blocks - num_long else 0)
        groups.append(codewords[offset:offset + length])
        offset += length
    divisor = _reed_solomon_divisor(ecc_len)
    ecc_blocks = [_reed_solomon_remainder(group, divisor) for group in groups]
    interleaved = []
    for index in range(max(len(group) for group in groups)):
        for group in groups:
            if index < len(group):
                interleaved.append(group[index])
    for index in range(ecc_len):
        for block in ecc_blocks:
            interleaved.append(block[index])
    final_bits = []
    for codeword in interleaved:
        for index in range(7, -1, -1):
            final_bits.append((codeword >> index) & 1)
    final_bits.extend([0] * _REMAINDER_BITS[version - 1])

    size = 21 + (version - 1) * 4
    best = None
    best_penalty = None
    for mask in range(8):
        modules, marked = _make_function_modules(version)
        _draw_format(modules, marked, size, _format_bits(ecc_index, mask))
        pending = list(final_bits)
        right = size - 1
        while right >= 1:
            if right == 6:
                right = 5
            upward = ((right + 1) & 2) == 0
            rows = range(size - 1, -1, -1) if upward else range(size)
            for y in rows:
                for x in (right, right - 1):
                    if not marked[y][x] and pending:
                        dark = bool(pending.pop(0))
                        if _apply_mask(mask, x, y):
                            dark = not dark
                        modules[y][x] = dark
            right -= 2
        score = _penalty(modules)
        if best_penalty is None or score < best_penalty:
            best_penalty = score
            best = modules
    return QrCode(size, best)
