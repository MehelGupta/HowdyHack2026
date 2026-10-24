"""Lofi Fish: a singing-fish study timer built with pygame.

Pages: home (fish + timer), pause (books + current/next fish),
info (About the Game), living room (all collected fish).
"""
import json
import math
import os
import random
import sys
from types import SimpleNamespace

import pygame

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
W, H = 1100, 520
FPS = 60
BASE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(BASE, "assets")
MUSIC_DIR = os.path.join(BASE, "music")
SAVE_PATH = os.path.join(BASE, "save.json")
MUSIC_END = pygame.USEREVENT + 1
DEBUG_KEYS = True  # press T on any non-paused page to add 15 minutes (for testing)

GREEN = (8, 43, 10)
MUSTARD = (203, 191, 112)
INK = (18, 18, 18)
CREAM = (245, 232, 200)
FONT_NAMES = "inter,helveticaneue,helvetica,arial,dejavusans"
CARD = (270, 150)
SING = [0, 1, 2, 1]  # order the mouth frames play in

# One entry per level, in unlock order. "file" is the prefix of assets/<file>_1.png, _2, _3...
# unlock_h = total hours studied needed to unlock that fish.
FISH = [
    dict(name="Largemouth Bass", file="bass", unlock_h=0.0,
         fact="Largemouth bass feel vibrations in the water to find prey."),
    dict(name="Goldfish", file="goldfish", unlock_h=1.0,
         fact="Goldfish can remember things for months, not 3 seconds!"),
    dict(name="Salmon", file="salmon", unlock_h=3.0,
         fact="Salmon swim back to the stream where they were born."),
]

# Honors, shown on the books page. Order = display order of the "latest honor".
HONORS = [
    ("Goldfish Friend", lambda p: p.level >= 1),
    ("Deep Focus", lambda p: p.max_session >= 45 * 60),
    ("Marathon Swimmer", lambda p: p.max_session >= 2 * 3600),
    ("Super Fish", lambda p: p.level >= len(FISH) - 1),
]

# Where each fish plaque hangs in the living room (same order as FISH).
SLOTS = [(550, 135), (190, 150), (910, 150)]


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
_fonts = {}


def font(size, bold=False):
    key = (size, bold)
    if key not in _fonts:
        _fonts[key] = pygame.font.SysFont(FONT_NAMES, size, bold=bold)
    return _fonts[key]


def fit_font(text, size, max_w, bold=False):
    while size > 10 and font(size, bold).size(text)[0] > max_w:
        size -= 1
    return font(size, bold)


def draw_text(surf, text, fnt, color, pos, anchor="center", shadow=None):
    img = fnt.render(text, True, color)
    rect = img.get_rect(**{anchor: pos})
    if shadow:
        surf.blit(fnt.render(text, True, shadow), rect.move(2, 2))
    surf.blit(img, rect)
    return rect


def wrap(text, fnt, max_w):
    lines, line = [], ""
    for word in text.split():
        test = f"{line} {word}".strip()
        if fnt.size(test)[0] <= max_w:
            line = test
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def fmt_clock(sec):
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def fmt_dur(sec):
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m {s:02d}s"


def load_img(name):
    return pygame.image.load(os.path.join(ASSETS, name)).convert_alpha()


def crop(img):
    rect = img.get_bounding_rect()
    return img.subsurface(rect).copy(), rect


def scale_to(img, w=None, h=None):
    if w and not h:
        h = round(img.get_height() * w / img.get_width())
    elif h and not w:
        w = round(img.get_width() * h / img.get_height())
    return pygame.transform.smoothscale(img, (w, h))


def fit(img, bw, bh):
    s = min(bw / img.get_width(), bh / img.get_height())
    return pygame.transform.smoothscale(
        img, (round(img.get_width() * s), round(img.get_height() * s))
    )


def cover(img, w, h):
    s = max(w / img.get_width(), h / img.get_height())
    scaled = pygame.transform.smoothscale(
        img, (round(img.get_width() * s), round(img.get_height() * s))
    )
    out = pygame.Surface((w, h))
    out.blit(scaled, ((w - scaled.get_width()) // 2, (h - scaled.get_height()) // 2))
    return out


def grayscale(img):
    if hasattr(pygame.transform, "grayscale"):
        return pygame.transform.grayscale(img)
    g = img.copy()
    g.fill((150, 150, 150), special_flags=pygame.BLEND_RGB_MULT)
    return g


def glow_surface(radius, color, max_alpha):
    s = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
    steps = 24
    for i in range(steps, 0, -1):
        r = int(radius * i / steps)
        a = int(max_alpha * (1 - i / steps) ** 2)
        pygame.draw.circle(s, (*color, a), (radius, radius), r)
    return s


def leaf(surf, base, angle_deg, length, width, color):
    a = math.radians(angle_deg)
    dx, dy = math.cos(a), -math.sin(a)
    px, py = -dy, dx
    mid = (base[0] + dx * length * 0.5, base[1] + dy * length * 0.5)
    tip = (base[0] + dx * length, base[1] + dy * length)
    pts = [
        base,
        (mid[0] + px * width / 2, mid[1] + py * width / 2),
        tip,
        (mid[0] - px * width / 2, mid[1] - py * width / 2),
    ]
    pygame.draw.polygon(surf, color, pts)


# --------------------------------------------------------------------------
# Progress (saved between runs)
# --------------------------------------------------------------------------
class Progress:
    def __init__(self):
        self.total = 0.0        # all-time seconds studied (unlocks fish)
        self.max_session = 0.0  # longest single session, seconds
        self.session = 0.0      # this run's timer
        self.honors = []
        try:
            with open(SAVE_PATH) as f:
                data = json.load(f)
            self.total = float(data.get("total", 0))
            self.max_session = float(data.get("max_session", 0))
            self.honors = list(data.get("honors", []))
        except (OSError, ValueError):
            pass
        self.check_honors()

    @property
    def level(self):
        lvl = 0
        for i, f in enumerate(FISH):
            if self.total >= f["unlock_h"] * 3600:
                lvl = i
        return lvl

    def add(self, sec):
        self.total += sec
        self.session += sec
        self.max_session = max(self.max_session, self.session)

    def hours_to_next(self):
        nxt = self.level + 1
        if nxt >= len(FISH):
            return None
        return max(0.0, FISH[nxt]["unlock_h"] * 3600 - self.total) / 3600

    def check_honors(self):
        new = []
        for name, cond in HONORS:
            if name not in self.honors and cond(self):
                self.honors.append(name)
                new.append(name)
        return new

    def save(self):
        try:
            with open(SAVE_PATH, "w") as f:
                json.dump(
                    {"total": self.total, "max_session": self.max_session, "honors": self.honors},
                    f,
                )
        except OSError:
            pass


# --------------------------------------------------------------------------
# Music
# --------------------------------------------------------------------------
class Playlist:
    def __init__(self):
        self.ok = pygame.mixer.get_init() is not None
        self.tracks = []
        self.index = 0
        exts = (".mp3", ".ogg", ".wav")
        if self.ok and os.path.isdir(MUSIC_DIR):
            self.tracks = sorted(f for f in os.listdir(MUSIC_DIR) if f.lower().endswith(exts))
        if self.tracks:
            pygame.mixer.music.set_endevent(MUSIC_END)
            self.play_current()

    def play_current(self):
        pygame.mixer.music.load(os.path.join(MUSIC_DIR, self.tracks[self.index]))
        pygame.mixer.music.play()

    def next(self):
        if self.tracks:
            self.index = (self.index + 1) % len(self.tracks)
            self.play_current()

    def pause(self):
        if self.tracks:
            pygame.mixer.music.pause()

    def resume(self):
        if self.tracks:
            pygame.mixer.music.unpause()


# --------------------------------------------------------------------------
# Buttons
# --------------------------------------------------------------------------
class Button:
    def __init__(self, image, center):
        self.image = image
        self.rect = image.get_rect(center=center)

    def hovered(self):
        return self.rect.collidepoint(pygame.mouse.get_pos())

    def draw(self, screen):
        if self.hovered():
            big = pygame.transform.smoothscale(
                self.image, (round(self.rect.w * 1.12), round(self.rect.h * 1.12))
            )
            screen.blit(big, big.get_rect(center=self.rect.center))
        else:
            screen.blit(self.image, self.rect)

    def clicked(self, event):
        return (
            event.type == pygame.MOUSEBUTTONDOWN
            and event.button == 1
            and self.rect.collidepoint(event.pos)
        )


# --------------------------------------------------------------------------
# Assets
# --------------------------------------------------------------------------
def load_fish_frames(prefix):
    raw, i = [], 1
    while os.path.exists(os.path.join(ASSETS, f"{prefix}_{i}.png")):
        raw.append(load_img(f"{prefix}_{i}.png"))
        i += 1
    if not raw:
        raise FileNotFoundError(f"No frames found: assets/{prefix}_1.png")
    # Crop every frame to the same box so the fish doesn't jump between frames.
    box = raw[0].get_bounding_rect()
    for r in raw[1:]:
        box = box.union(r.get_bounding_rect())
    return [r.subsurface(box).copy() for r in raw]


def make_pattern(fish_icon):
    mask = pygame.mask.from_surface(fish_icon)
    tint = mask.to_surface(setcolor=(186, 174, 96, 255), unsetcolor=(0, 0, 0, 0))
    tint = scale_to(tint, w=120)
    pat = pygame.Surface((W, H), pygame.SRCALPHA)
    row = 0
    for y in range(-20, H + 120, 118):
        xoff = 95 if row % 2 else 0
        for x in range(-120 + xoff, W + 120, 190):
            pat.blit(tint, (x, y))
        row += 1
    return pat


def make_back_button():
    s = pygame.Surface((56, 56), pygame.SRCALPHA)
    pygame.draw.circle(s, GREEN, (28, 28), 28)
    pygame.draw.lines(s, (255, 255, 255), False, [(32, 16), (20, 28), (32, 40)], 6)
    return s


def build_room(a):
    """Static layer of the living room (everything that doesn't animate)."""
    s = pygame.Surface((W, H))
    rng = random.Random(7)
    floor_top = 384

    # Wall + stripes + wainscot
    s.fill((47, 78, 74))
    for x in range(0, W, 46):
        pygame.draw.rect(s, (51, 84, 79), (x, 0, 23, H))
    pygame.draw.rect(s, (36, 63, 59), (0, 288, W, floor_top - 288))
    pygame.draw.rect(s, (214, 196, 160), (0, 284, W, 7))
    for x in range(30, W, 150):
        pygame.draw.rect(s, (52, 88, 82), (x, 302, 110, 62), 2)

    # Wood floor
    for row in range(5):
        yy = floor_top + row * 28
        x = -rng.randint(0, 120)
        while x < W:
            shade = rng.randint(-9, 9)
            pygame.draw.rect(s, (146 + shade, 98 + shade, 60 + shade), (x, yy, 170, 28))
            pygame.draw.line(s, (104, 66, 38), (x, yy), (x, yy + 28), 2)
            x += 170
        pygame.draw.line(s, (104, 66, 38), (0, yy), (W, yy), 2)
    pygame.draw.rect(s, (214, 196, 160), (0, floor_top - 10, W, 10))

    # Rug
    rug = pygame.Rect(0, 0, 600, 86)
    rug.center = (560, 452)
    pygame.draw.ellipse(s, (122, 62, 60), rug)
    pygame.draw.ellipse(s, (224, 190, 130), rug.inflate(-40, -18), 3)
    pygame.draw.ellipse(s, (224, 190, 130), rug.inflate(-120, -40), 2)

    # Brick chimney breast
    cx0, cw = 410, 280
    chim = cover(a.brick, cw, floor_top).copy()
    chim.fill((205, 190, 180), special_flags=pygame.BLEND_RGB_MULT)
    s.blit(chim, (cx0, 0))
    for i in range(14):
        shade = pygame.Surface((1, floor_top), pygame.SRCALPHA)
        shade.fill((0, 0, 0, max(90 - 6 * i, 0)))
        s.blit(shade, (cx0 + i, 0))
        s.blit(shade, (cx0 + cw - 1 - i, 0))

    # Mantel, firebox, hearth
    pygame.draw.rect(s, (112, 70, 40), (385, 260, 330, 20), border_radius=4)
    pygame.draw.rect(s, (158, 106, 66), (385, 260, 330, 5), border_radius=4)
    under = pygame.Surface((330, 14), pygame.SRCALPHA)
    under.fill((0, 0, 0, 70))
    s.blit(under, (385, 280))
    pygame.draw.rect(s, (78, 68, 64), (452, 296, 196, 90),
                     border_top_left_radius=70, border_top_right_radius=70)
    pygame.draw.rect(s, (20, 14, 12), (464, 308, 172, 76),
                     border_top_left_radius=60, border_top_right_radius=60)
    pygame.draw.rect(s, (120, 108, 100), (430, 384, 240, 12), border_radius=3)

    # Candles on the mantel
    for cx in (435, 665):
        pygame.draw.rect(s, (240, 228, 200), (cx - 5, 236, 10, 24), border_radius=2)

    # Couch
    pygame.draw.rect(s, (150, 80, 56), (80, 300, 290, 92), border_radius=24)
    pygame.draw.rect(s, (176, 96, 66), (96, 318, 258, 60), border_radius=14)
    pygame.draw.rect(s, (190, 104, 72), (70, 352, 310, 46), border_radius=14)
    pygame.draw.rect(s, (160, 86, 60), (48, 326, 50, 76), border_radius=18)
    pygame.draw.rect(s, (160, 86, 60), (352, 326, 50, 76), border_radius=18)
    pygame.draw.rect(s, (60, 40, 30), (66, 398, 12, 14))
    pygame.draw.rect(s, (60, 40, 30), (372, 398, 12, 14))
    pygame.draw.rect(s, (228, 184, 88), (112, 318, 54, 46), border_radius=12)

    # Floor lamp
    pygame.draw.line(s, (60, 44, 34), (770, 292), (770, 404), 5)
    pygame.draw.ellipse(s, (60, 44, 34), (748, 398, 44, 12))
    pygame.draw.polygon(s, (246, 222, 160), [(742, 296), (798, 296), (786, 252), (754, 252)])

    # Books + plant
    s.blit(a.books_small, (872, 404 - a.books_small.get_height()))
    pygame.draw.polygon(s, (170, 92, 60), [(955, 372), (1015, 372), (1005, 410), (965, 410)])
    for ang, ln, col in ((100, 70, (70, 130, 80)), (60, 80, (86, 150, 92)),
                         (140, 78, (60, 118, 74)), (80, 92, (96, 160, 100)),
                         (118, 84, (78, 140, 86)), (42, 66, (66, 126, 78))):
        leaf(s, (985, 374), ang, ln, 26, col)
    return s


def build_vignette():
    v = pygame.Surface((W, H), pygame.SRCALPHA)
    for i in range(60):
        al = int(110 * (1 - i / 60) ** 2)
        pygame.draw.rect(v, (0, 0, 0, al), (i, i, W - 2 * i, H - 2 * i), 1)
    return v


def load_assets():
    a = SimpleNamespace()
    a.brick = pygame.image.load(os.path.join(ASSETS, "brickBG.jpg")).convert()
    a.bg = cover(a.brick, W, H)

    board, _ = crop(load_img("woodBoard.png"))
    board_land = pygame.transform.rotate(board, 90)  # grain runs sideways like the mockup
    a.board_home = pygame.transform.smoothscale(board_land, (560, 330))
    a.board_card = pygame.transform.smoothscale(board_land, (250, 140))
    a.board_plaque = pygame.transform.smoothscale(board_land, (210, 150))
    a.board_locked = a.board_plaque.copy()
    a.board_locked.fill((90, 90, 90), special_flags=pygame.BLEND_RGB_MULT)

    books, rect = crop(load_img("books.png"))
    a.books_origin = (rect.x, rect.y)
    a.books = scale_to(books, h=416)
    a.books_scale = a.books.get_width() / rect.w
    a.books_small = scale_to(books, h=100)

    a.pause = scale_to(load_img("pauseButton.png"), w=84)
    a.info = scale_to(load_img("infoButton.png"), w=66)
    fish_icon = load_img("fishButton.png")
    a.fish_btn = scale_to(fish_icon, w=104)
    a.back = make_back_button()
    a.pattern = make_pattern(fish_icon)

    a.fish = []
    for f in FISH:
        frames = load_fish_frames(f["file"])
        a.fish.append(SimpleNamespace(
            big=[fit(fr, 590, 270) for fr in frames],
            plaque=[fit(fr, 196, 96) for fr in frames],
            card=[fit(fr, 250, 112) for fr in frames],
        ))

    a.glow_fire = glow_surface(300, (255, 140, 50), 120)
    a.glow_lamp = glow_surface(150, (255, 210, 130), 80)
    a.glow_bulb = glow_surface(14, (255, 220, 140), 120)
    a.vignette = build_vignette()
    a.room = build_room(a)
    return a


def make_card(a, idx, locked):
    card = pygame.Surface(CARD)
    card.fill((250, 246, 238))
    cx, cy = CARD[0] // 2, CARD[1] // 2
    card.blit(a.board_card, a.board_card.get_rect(center=(cx, cy)))
    fr = a.fish[idx].card[0]
    card.blit(fr, fr.get_rect(center=(cx, cy - 4)))
    if locked:
        card = grayscale(card)
    pygame.draw.rect(card, (40, 25, 15), card.get_rect(), 3)
    return card


# --------------------------------------------------------------------------
# Page drawing
# --------------------------------------------------------------------------
def draw_home(screen, a, prog, t, mouth_t):
    screen.blit(a.bg, (0, 0))
    draw_text(screen, fmt_clock(prog.session), font(66, True), INK, (W // 2, 46))

    board_rect = a.board_home.get_rect(center=(W // 2, 268))
    screen.blit(a.board_home, board_rect)

    lvl = prog.level
    frames = a.fish[lvl].big
    idx = SING[int(mouth_t / 0.18) % len(SING)] % len(frames)
    bob = math.sin(t * 2.0) * 5
    ang = math.sin(t * 1.3) * 1.5
    img = pygame.transform.rotozoom(frames[idx], ang, 1.0)
    screen.blit(img, img.get_rect(center=(W // 2, 240 + bob)))

    # One-line fun fact on the lower edge of the board
    fact = FISH[lvl]["fact"]
    fnt = fit_font(fact, 17, board_rect.width - 90)
    tw, th = fnt.size(fact)
    strip = pygame.Surface((tw + 30, th + 10), pygame.SRCALPHA)
    pygame.draw.rect(strip, (0, 0, 0, 140), strip.get_rect(), border_radius=10)
    bottom = board_rect.bottom - 14
    screen.blit(strip, strip.get_rect(midbottom=(W // 2, bottom)))
    draw_text(screen, fact, fnt, CREAM, (W // 2, bottom - strip.get_height() // 2))


SPINES = [  # (cx, cy in books.png pixels, key, light text on dark-red book?)
    (232, 142, "fish", True),
    (197, 215, "honors", True),
    (202, 343, "max", False),
    (232, 413, "time", False),
    (248, 472, "next", False),
    (220, 539, "total", True),
]


def draw_pause(screen, a, prog, cards, cur_rect, next_rect):
    screen.blit(a.bg, (0, 0))
    shadow = (40, 20, 10)
    lvl = prog.level

    # Current / next fish cards (left)
    draw_text(screen, "Current Fish", font(24, True), CREAM, (cur_rect.centerx, cur_rect.top - 22), shadow=shadow)
    screen.blit(cards[(lvl, False)], cur_rect)
    ov = pygame.Surface((70, 70), pygame.SRCALPHA)
    pygame.draw.circle(ov, (0, 0, 0, 120), (35, 35), 35)
    pygame.draw.polygon(ov, (255, 255, 255, 235), [(28, 20), (28, 50), (52, 35)])
    screen.blit(ov, ov.get_rect(center=cur_rect.center))
    hovered = cur_rect.collidepoint(pygame.mouse.get_pos())
    pygame.draw.rect(screen, (255, 255, 255) if hovered else (40, 25, 15), cur_rect.inflate(8, 8), 3)

    draw_text(screen, "Next Fish", font(24, True), CREAM, (next_rect.centerx, next_rect.top - 22), shadow=shadow)
    if lvl + 1 < len(FISH):
        screen.blit(cards[(lvl + 1, True)], next_rect)
    else:
        pygame.draw.rect(screen, (250, 246, 238), next_rect)
        pygame.draw.rect(screen, (40, 25, 15), next_rect, 3)
        draw_text(screen, "Every fish unlocked!", font(20, True), INK, next_rect.center)
    draw_text(screen, "Click the fish or press Space to keep studying",
              font(18, True), CREAM, (cur_rect.centerx, next_rect.bottom + 34), shadow=shadow)

    # Books (right) with stats written on the spines
    bx = W - 60 - a.books.get_width()
    by = (H - a.books.get_height()) // 2
    screen.blit(a.books, (bx, by))

    hrs = prog.hours_to_next()
    values = {
        "fish": ("Fish collected", f"{lvl + 1} / {len(FISH)}"),
        "honors": (f"Honors ({len(prog.honors)})", prog.honors[-1] if prog.honors else "None yet"),
        "max": ("Max time studied", fmt_dur(prog.max_session)),
        "time": ("Time studied", fmt_dur(prog.session)),
        "next": ("Hours to next fish", "All unlocked!" if hrs is None else f"{max(hrs, 0.1):.1f} hrs"),
        "total": ("Total studied", fmt_dur(prog.total)),
    }
    ox, oy = a.books_origin
    s = a.books_scale
    for cx, cy, key, light in SPINES:
        label, value = values[key]
        color = (250, 235, 190) if light else (35, 20, 8)
        px = bx + (cx - ox) * s
        py = by + (cy - oy) * s
        draw_text(screen, label, fit_font(label, 13, 220), color, (px, py - 10))
        draw_text(screen, value, fit_font(value, 18, 220, True), color, (px, py + 9))


def draw_info(screen, a):
    screen.fill(MUSTARD)
    screen.blit(a.pattern, (0, 0))
    for i, line in enumerate(("About", "the Game")):
        draw_text(screen, line, font(60), INK, (int(W * 0.2), int(H * 0.5 + (i - 0.5) * 68)))

    x0, text_w = int(W * 0.375), 420
    panel = pygame.Surface((text_w + 60, 215), pygame.SRCALPHA)
    pygame.draw.rect(panel, (*MUSTARD, 228), panel.get_rect(), border_radius=18)
    screen.blit(panel, (x0 - 30, int(H * 0.30)))

    draw_text(screen, "Earn fish for studying!", font(26), (255, 255, 255), (x0 + text_w // 2, int(H * 0.385)))
    body = ("Check out the living room to see all of the fish you have collected. "
            "Pause the song and see how many hours you need to get to the next fish!")
    y = int(H * 0.455)
    for line in wrap(body, font(22), text_w):
        draw_text(screen, line, font(22), (255, 255, 255), (x0, y), anchor="topleft")
        y += 28


def draw_living_room(screen, a, prog, t):
    screen.blit(a.room, (0, 0))

    lamp = a.glow_lamp
    screen.blit(lamp, (770 - lamp.get_width() // 2, 275 - lamp.get_height() // 2))

    # Fire
    fire = pygame.Rect(464, 308, 172, 76)
    screen.set_clip(fire)
    base = fire.bottom - 2
    for i in range(7):
        x = fire.x + 22 + i * 21 + math.sin(t * 3 + i * 1.3) * 3
        hgt = 38 + 26 * (0.5 + 0.5 * math.sin(t * 6.2 + i * 2.1)) + 8 * math.sin(t * 13 + i * 0.7)
        for sc, col in ((1.0, (214, 72, 24)), (0.72, (246, 150, 34)), (0.42, (255, 226, 140))):
            hw = 17 * sc + 2
            tip = (x + math.sin(t * 7 + i) * 5 * sc, base - hgt * sc)
            pygame.draw.polygon(screen, col, [
                (x - hw, base), (x - hw * 0.4, base - hgt * sc * 0.55), tip,
                (x + hw * 0.4, base - hgt * sc * 0.55), (x + hw, base)])
    pygame.draw.rect(screen, (88, 54, 32), (478, 366, 84, 16), border_radius=7)
    pygame.draw.rect(screen, (104, 64, 38), (540, 360, 92, 18), border_radius=8)
    screen.set_clip(None)

    flick = 0.8 + 0.12 * math.sin(t * 9) + 0.08 * math.sin(t * 23)
    g = a.glow_fire
    g.set_alpha(int(255 * min(1.0, flick)))
    screen.blit(g, (550 - g.get_width() // 2, 350 - g.get_height() // 2))

    # Candle flames
    for cx in (435, 665):
        r = 4 + int(1.5 * math.sin(t * 11 + cx))
        pygame.draw.circle(screen, (255, 200, 90), (cx, 230), r)
        pygame.draw.circle(screen, (255, 245, 200), (cx, 231), max(r - 2, 1))

    # Fish plaques
    for i, f in enumerate(FISH):
        pos = SLOTS[i]
        unlocked = i <= prog.level
        board = a.board_plaque if unlocked else a.board_locked
        rect = board.get_rect(center=pos)
        screen.blit(board, rect)
        if unlocked:
            frames = a.fish[i].plaque
            idx = SING[int(t * 4 + i * 3) % len(SING)] % len(frames)
            screen.blit(frames[idx], frames[idx].get_rect(center=(pos[0], pos[1] - 2)))
        else:
            draw_text(screen, "?", font(64, True), (200, 190, 170), pos)
        plate = pygame.Rect(0, 0, 128, 20)
        plate.midtop = (pos[0], rect.bottom + 4)
        pygame.draw.rect(screen, (196, 160, 70), plate, border_radius=3)
        pygame.draw.rect(screen, (120, 90, 30), plate, 1, border_radius=3)
        draw_text(screen, f["name"] if unlocked else "???", font(13, True), (50, 34, 10), plate.center)
        if not unlocked:
            draw_text(screen, f"Unlocks at {f['unlock_h']:g} hrs", font(13), CREAM,
                      (pos[0], plate.bottom + 12), shadow=(0, 0, 0))

    # String lights
    pts = [(x, 16 + 12 * math.sin(x / 70.0)) for x in range(0, W + 1, 46)]
    pygame.draw.lines(screen, (28, 38, 36), False, pts, 2)
    for i, (x, y) in enumerate(pts):
        tw = 0.65 + 0.35 * math.sin(t * 2.2 + i * 0.9)
        a.glow_bulb.set_alpha(int(255 * tw))
        screen.blit(a.glow_bulb, (int(x) - 14, int(y) - 10))
        pygame.draw.circle(screen, (255, int(200 + 40 * tw), int(110 + 60 * tw)), (int(x), int(y) + 4), 4)

    screen.blit(a.vignette, (0, 0))
    draw_text(screen, f"Fish collected: {prog.level + 1} / {len(FISH)}", font(20, True), CREAM,
              (W - 24, 34), anchor="midright", shadow=(0, 0, 0))


def draw_toast(screen, text):
    fnt = font(20, True)
    tw, th = fnt.size(text)
    pill = pygame.Surface((tw + 40, th + 16), pygame.SRCALPHA)
    pygame.draw.rect(pill, (*GREEN, 235), pill.get_rect(), border_radius=18)
    screen.blit(pill, pill.get_rect(center=(W // 2, 122)))
    draw_text(screen, text, fnt, CREAM, (W // 2, 122))


# --------------------------------------------------------------------------
# Main loop
# --------------------------------------------------------------------------
def main():
    pygame.init()
    try:
        pygame.mixer.init()
    except pygame.error:
        print("Audio device not available; running without sound.")
    screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption("Lofi Fish")
    clock = pygame.time.Clock()

    a = load_assets()
    prog = Progress()
    playlist = Playlist()

    btn_info = Button(a.info, (70, H - 52))
    btn_pause = Button(a.pause, (W // 2, H - 50))
    btn_fish = Button(a.fish_btn, (W - 90, H - 52))
    btn_back = Button(a.back, (48, 48))

    cur_rect = pygame.Rect(0, 0, *CARD)
    cur_rect.midtop = (300, 70)
    next_rect = pygame.Rect(0, 0, *CARD)
    next_rect.midtop = (300, 272)
    cards = {}
    for i in range(len(FISH)):
        cards[(i, False)] = make_card(a, i, False)
        cards[(i, True)] = make_card(a, i, True)

    state = {"page": "home", "paused": False}
    toast = {"queue": [], "text": "", "ttl": 0.0}
    t = mouth_t = save_timer = 0.0

    def advance(sec):
        lvl_before = prog.level
        prog.add(sec)
        if prog.level > lvl_before:
            toast["queue"].append(f"New fish unlocked: {FISH[prog.level]['name']}!")
        for name in prog.check_honors():
            toast["queue"].append(f"Honor unlocked: {name}")

    def go_pause():
        state["paused"] = True
        state["page"] = "pause"
        playlist.pause()
        prog.save()

    def go_resume():
        state["paused"] = False
        state["page"] = "home"
        playlist.resume()

    while True:
        dt = min(clock.tick(FPS) / 1000, 0.1)
        t += dt

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                prog.save()
                pygame.quit()
                sys.exit()
            if event.type == MUSIC_END:
                playlist.next()
            page = state["page"]

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if page in ("info", "living"):
                        state["page"] = "home"
                    elif page == "pause":
                        go_resume()
                elif event.key == pygame.K_SPACE:
                    if page == "home":
                        go_pause()
                    elif page == "pause":
                        go_resume()
                elif DEBUG_KEYS and event.key == pygame.K_t and not state["paused"]:
                    advance(900)

            if page == "home":
                if btn_pause.clicked(event):
                    go_pause()
                elif btn_info.clicked(event):
                    state["page"] = "info"
                elif btn_fish.clicked(event):
                    state["page"] = "living"
            elif page == "pause":
                if (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                        and cur_rect.collidepoint(event.pos)):
                    go_resume()
            elif btn_back.clicked(event):
                state["page"] = "home"

        # Time only counts while studying (not paused)
        if not state["paused"]:
            mouth_t += dt
            advance(dt)
            save_timer += dt
            if save_timer > 30:
                save_timer = 0.0
                prog.save()

        # Toast queue
        if toast["ttl"] > 0:
            toast["ttl"] -= dt
        elif toast["queue"]:
            toast["text"] = toast["queue"].pop(0)
            toast["ttl"] = 4.0

        page = state["page"]
        if page == "home":
            draw_home(screen, a, prog, t, mouth_t)
            btn_info.draw(screen)
            btn_pause.draw(screen)
            btn_fish.draw(screen)
        elif page == "pause":
            draw_pause(screen, a, prog, cards, cur_rect, next_rect)
        elif page == "info":
            draw_info(screen, a)
            btn_back.draw(screen)
        else:
            draw_living_room(screen, a, prog, t)
            btn_back.draw(screen)

        if page != "pause" and toast["ttl"] > 0:
            draw_toast(screen, toast["text"])

        pygame.display.flip()


if __name__ == "__main__":
    main()