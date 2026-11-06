from PIL import Image, ImageDraw

def render(size):
    # Antialias the silhouette, but snap the white bars to the final pixel grid.
    image = Image.new("RGBA", (size * 4, size * 4))
    draw = ImageDraw.Draw(image)
    scale = size * 4 / 256
    draw.rounded_rectangle(tuple(round(v * scale) for v in (8, 8, 248, 248)),
                           radius=round(64 * scale), fill="#5965F5")
    image = image.resize((size, size), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(image)
    width = max(1, round(size / 16))
    for x, height in [(60, 46), (94, 92), (128, 144), (162, 92), (196, 46)]:
        left = round(x * size / 256 - width / 2)
        top = round((128 - height / 2) * size / 256)
        bottom = round((128 + height / 2) * size / 256)
        draw.rounded_rectangle((left, top, left + width - 1, bottom),
                               radius=width // 2, fill="white")
    return image


sizes = (16, 20, 24, 28, 32, 40, 48, 64, 96, 128, 256)
frames = [render(size) for size in sizes]
frames[-1].save("app.ico", sizes=[(size, size) for size in sizes], append_images=frames[:-1])
