import zlib, struct, math

def create_png(width, height, rgba_data, output_path):
    def make_chunk(chunk_type, data):
        chunk = chunk_type + data
        crc = zlib.crc32(chunk) & 0xffffffff
        return struct.pack('>I', len(data)) + chunk + struct.pack('>I', crc)
    png = b'\x89PNG\r\n\x1a\n'
    ihdr = struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)
    png += make_chunk(b'IHDR', ihdr)
    raw = b''
    stride = width * 4
    for y in range(height):
        raw += b'\x00'
        raw += bytes(rgba_data[y * stride : (y + 1) * stride])
    compressed = zlib.compress(raw, 9)
    png += make_chunk(b'IDAT', compressed)
    png += make_chunk(b'IEND', b'')
    with open(output_path, 'wb') as f:
        f.write(png)
    print(f'Created {output_path} ({width}x{height}, {len(png)} bytes)')

# === 256x256 App Icon ===
W, H = 256, 256
pixels = bytearray(W * H * 4)
for y in range(H):
    for x in range(W):
        idx = (y * W + x) * 4
        dx, dy = x - 128, y - 128
        dist = math.sqrt(dx*dx + dy*dy)
        in_rect = abs(x - 128) <= 80 and abs(y - 128) <= 80
        if in_rect:
            pixels[idx] = 15 + int(10 * (x / 256))
            pixels[idx+1] = 23 + int(7 * (y / 256))
            pixels[idx+2] = 42 + int(8 * ((x+y) / 512))
            pixels[idx+3] = 255
        else:
            pixels[idx+3] = 0
        if 92 < dist < 96:
            angle = (math.atan2(dy, dx) * 4 / math.pi) % 2
            if angle < 0.5:
                pixels[idx] = 129
                pixels[idx+1] = 140
                pixels[idx+2] = 248
                pixels[idx+3] = 180

for y in range(H):
    for x in range(W):
        idx = (y * W + x) * 4
        dx, dy = x - 128, y - 128
        dist = math.sqrt(dx*dx + dy*dy)
        if dist <= 16:
            pixels[idx] = 56
            pixels[idx+1] = 189
            pixels[idx+2] = 248
            pixels[idx+3] = 255

for angle_deg in [0, 45, 90, 135, 180, 225, 270, 315]:
    angle = math.radians(angle_deg)
    for r in range(100, 106):
        x = int(128 + r * math.cos(angle))
        y2 = int(128 + r * math.sin(angle))
        if 0 <= x < W and 0 <= y2 < H:
            idx = (y2 * W + x) * 4
            pixels[idx] = 56
            pixels[idx+1] = 189
            pixels[idx+2] = 248
            pixels[idx+3] = 200

create_png(W, H, pixels, 'D:/CreoDevo/SF2AIS/probe-app/assets/icon.png')

# === 32x32 Tray Icon ===
W2, H2 = 32, 32
pixels2 = bytearray(W2 * H2 * 4)
for y in range(H2):
    for x in range(W2):
        idx = (y * W2 + x) * 4
        dx, dy = x - 16, y - 16
        dist = math.sqrt(dx*dx + dy*dy)
        if dist <= 15:
            pixels2[idx] = 56
            pixels2[idx+1] = 189
            pixels2[idx+2] = 248
            pixels2[idx+3] = 255
        elif 14 < dist <= 15:
            pixels2[idx] = 129
            pixels2[idx+1] = 140
            pixels2[idx+2] = 248
            pixels2[idx+3] = 255
        else:
            pixels2[idx+3] = 0
create_png(W2, H2, pixels2, 'D:/CreoDevo/SF2AIS/probe-app/assets/tray-icon.png')

# === tray-icon-template.png (white version) ===
pixels3 = bytearray(pixels2)
for i in range(0, len(pixels3), 4):
    if pixels3[i+3] > 0:
        pixels3[i] = 255
        pixels3[i+1] = 255
        pixels3[i+2] = 255
create_png(W2, H2, pixels3, 'D:/CreoDevo/SF2AIS/probe-app/assets/tray-icon-template.png')
print('All PNGs created successfully')
