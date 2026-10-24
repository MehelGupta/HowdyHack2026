"""Lofi Fish: a singing-fish study timer built with pygame.

Pages: home (fish + timer), pause (books + current/next fish),
info (About the Game), living room (your top three fish),
gallery (every fish, scrollable; click an unlocked fish to save it to the living room).
"""
import json
import math
import os
import random
import sys
from types import SimpleNamespace

import pygame

try:
    from music_reader import MusicReader  # needs numpy; keep music_reader.py next to main.py
except ImportError as err:
    print("Music disabled:", err)
    MusicReader = None

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
W, H = 1100, 520
FPS = 60
BASE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(BASE, "assets")
MUSIC_DIR = os.path.join(BASE, "music")
SAVE_PATH = os.path.join(BASE, "save.json")
DEBUG_KEYS = True  # developer keys (testing only), work on any non-paused page:
#   T = add 15 minutes studied
#   L = add exactly the time left to unlock the next fish
#   R = reset ALL progress to 0 (also overwrites save.json!)

GREEN = (8, 43, 10)
MUSTARD = (203, 191, 112)
INK = (18, 18, 18)
CREAM = (245, 232, 200)
FONT_NAMES = "inter,helveticaneue,helvetica,arial,dejavusans"
CARD = (270, 150)
SING = [0, 1, 2, 1]  # order the mouth frames play in
TIMER_RECT = pygame.Rect(0, 0, 330, 100)  # click this area on the home page to flip the timer up/down
TIMER_RECT.center = (W // 2, 54)

# One entry per level, in unlock order. "file" is the prefix of assets/<file>_1.png, _2, _3...
# unlock_h = total hours studied needed to unlock that fish.
# song = the file name inside the music/ folder that plays while this fish is on the home screen,
#        e.g. song="bass theme.mp3". Leave it as None to use the Nth file in music/ (alphabetical).
FISH = [
    dict(name="Largemouth Bass", file="bass", unlock_h=0.0, song="bassTheme.mp3",
         fact="Largemouth bass feel vibrations in the water to find prey."),
    dict(name="Goldfish", file="goldfish", unlock_h=1.0, song="goldfishTheme.mp3",
         fact="Goldfish can remember things for months, not 3 seconds!"),
    dict(name="Salmon", file="salmon", unlock_h=3.0, song="salmonTheme.mp3",
         fact="Salmon swim back to the stream where they were born."),
    dict(name="Blue Tang", file = "bluetang", unlock_h = 5.0, song = "doryTheme.mp3",
         fact = "Dory in Finding Nemo is a blue tang."),
    dict(name = "Catfish", file="catfish", unlock_h = 8.0, song = "catfishTheme.mp3",
         fact = "Catfish have fullbody taste buds including on their whiskered barbels."),
    dict(name = "Clownfish", file = "clownfish", unlock_h = 10.0, song = "nemoTheme.mp3",
        fact = "Every clownfish starts as a male, and can undergo sex change based on social dynamics")

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
MAX_FAVORITES = len(SLOTS)  # how many fish can hang in the living room (one per slot above)

# Gallery layout: a scrolling grid under a 84px header
GALLERY_VIEW = pygame.Rect(0, 84, W, H - 84)  # the scrolling area
GALLERY_COLS = 4                              # fish per row
GALLERY_CELL_W = 250                          # horizontal space per fish
GALLERY_ROW_H = 200                           # vertical space per row
GALLERY_LEFT = (W - GALLERY_COLS * GALLERY_CELL_W) // 2

logo = pygame.image.load('Assets/appIcon.png') 

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


def draw_text_outlined(surf, text, fnt, color, outline, pos, width=2, anchor="center"):
    """Draw text with a solid outline around every letter (keeps it readable on busy backgrounds)."""
    img = fnt.render(text, True, color)
    edge = fnt.render(text, True, outline)
    rect = img.get_rect(**{anchor: pos})
    for dx in range(-width, width + 1):
        for dy in range(-width, width + 1):
            if (dx or dy) and dx * dx + dy * dy <= width * width + 1:  # roughly circular outline
                surf.blit(edge, rect.move(dx, dy))
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


def fmt_hm(sec):
    """Hours and minutes, e.g. "1h 05m". Minutes round UP so it never says 0h 00m before the unlock."""
    total_min = math.ceil(sec / 60)
    h, m = divmod(total_min, 60)
    return f"{h}h {m:02d}m"


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


def gray_keep_alpha(img):
    """Grayscale copy that keeps the original transparency exactly (for plaques and fish cut-outs)."""
    g = grayscale(img).convert_alpha()
    g.fill((0, 0, 0, 255), special_flags=pygame.BLEND_RGBA_MAX)       # make every pixel opaque...
    mask = img.copy()
    mask.fill((255, 255, 255, 0), special_flags=pygame.BLEND_RGBA_MAX)  # ...white with the original alpha
    g.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)        # ...then restore the original alpha
    return g


def locked_look(img):
    """Gray and slightly darkened: how locked fish appear in the gallery."""
    g = gray_keep_alpha(img)
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
        self.favorites = []     # fish indexes hanging in the living room (max 3), in slot order
        saved_favs = None
        try:
            with open(SAVE_PATH) as f:
                data = json.load(f)
            self.total = float(data.get("total", 0))
            self.max_session = float(data.get("max_session", 0))
            self.honors = list(data.get("honors", []))
            saved_favs = data.get("favorites")
        except (OSError, ValueError):
            pass
        if saved_favs is None:  # brand-new game or an older save: start with the first fish you own
            saved_favs = list(range(min(MAX_FAVORITES, self.level + 1)))
        self.favorites = saved_favs
        self.clean_favorites()
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

    def clean_favorites(self):
        """Drop anything invalid: unknown or still-locked fish, duplicates, or more than 3."""
        favs = self.favorites if isinstance(self.favorites, list) else []
        clean = []
        for i in favs:
            if isinstance(i, int) and 0 <= i < len(FISH) and i <= self.level and i not in clean:
                clean.append(i)
        self.favorites = clean[:MAX_FAVORITES]

    def toggle_favorite(self, i):
        """Add/remove fish i from the living room. Returns "added", "removed", "full" or "locked"."""
        if i > self.level:
            return "locked"
        if i in self.favorites:
            self.favorites.remove(i)
            return "removed"
        if len(self.favorites) >= MAX_FAVORITES:
            return "full"
        self.favorites.append(i)
        return "added"

    def auto_pin(self, i):
        """A newly unlocked fish takes a free living-room slot, if there is one."""
        if i not in self.favorites and len(self.favorites) < MAX_FAVORITES:
            self.favorites.append(i)

    def check_honors(self):
        new = []
        for name, cond in HONORS:
            if name not in self.honors and cond(self):
                self.honors.append(name)
                new.append(name)
        return new

    def reset(self):
        """Wipe all progress back to a brand-new game and save it (debug use)."""
        self.total = 0.0
        self.max_session = 0.0
        self.session = 0.0
        self.honors = []
        self.favorites = [0]  # the starter fish
        self.save()

    def save(self):
        try:
            with open(SAVE_PATH, "w") as f:
                json.dump(
                    {"total": self.total, "max_session": self.max_session,
                     "honors": self.honors, "favorites": self.favorites},
                    f,
                )
        except OSError:
            pass


# --------------------------------------------------------------------------
# Music
# --------------------------------------------------------------------------
def music_tracks():
    """Every song file in the music/ folder, alphabetical."""
    if not os.path.isdir(MUSIC_DIR):
        return []
    return sorted(f for f in os.listdir(MUSIC_DIR) if f.lower().endswith((".mp3", ".ogg", ".wav")))


def song_for_fish(idx):
    """The music file that belongs to fish number idx (or None if music/ is empty).

    Uses the fish's own "song" from the FISH list. If that's None (or the file is missing),
    falls back to the Nth file in music/, wrapping around if there are more fish than songs.
    """
    tracks = music_tracks()
    if not tracks:
        return None
    wanted = FISH[idx].get("song")
    if wanted:
        by_lower = {t.lower(): t for t in tracks}  # ignore capital letters when matching
        if wanted.lower() in by_lower:
            return by_lower[wanted.lower()]
        print(f"{FISH[idx]['name']}: song '{wanted}' not found in {MUSIC_DIR}. Using a default song instead.")
    return tracks[idx % len(tracks)]


def load_music(fish_idx=0):
    """Starts the song that belongs to fish number fish_idx with MusicReader (loops, tracks beats).
    Returns None if there is no music."""
    if MusicReader is None:
        return None
    song = song_for_fish(fish_idx)
    if song is None:
        return None
    try:
        reader = MusicReader(os.path.join(MUSIC_DIR, song))
        reader.unpause()  # starts playing
        return reader
    except Exception as err:  # bad file, no audio device, ...
        print("Could not load music:", err)
        return None


def mouth_index(music, n, ticks, offset=0):
    """Mouth frame: changes on every beat when music is playing, else on a timer."""
    if music is not None and len(music.beat_times) > 0:
        return SING[(music.total_beats + offset) % len(SING)] % n
    return SING[int(ticks + offset) % len(SING)] % n


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


def make_pill(label, w=150, h=48):
    """A rounded green text button (used for the Gallery button)."""
    s = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.rect(s, GREEN, s.get_rect(), border_radius=h // 2)
    pygame.draw.rect(s, CREAM, s.get_rect(), 2, border_radius=h // 2)
    draw_text(s, label, font(22, True), CREAM, s.get_rect().center)
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
    a.board_gray = locked_look(a.board_plaque)  # grayed-out plaque for locked fish in the gallery

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
    a.gallery_btn = make_pill("Gallery")
    a.pattern = make_pattern(fish_icon)

    a.fish = []
    for f in FISH:
        frames = load_fish_frames(f["file"])
        plaque = [fit(fr, 196, 96) for fr in frames]
        a.fish.append(SimpleNamespace(
            big=[fit(fr, 590, 270) for fr in frames],
            plaque=plaque,
            plaque_gray=[locked_look(pl) for pl in plaque],  # grayed-out version for the gallery
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
def draw_home(screen, a, prog, t, mouth_t, music, countdown=False):
    screen.blit(a.bg, (0, 0))

    # Timer: counts UP (this session) by default, or DOWN to the next fish when toggled
    if TIMER_RECT.collidepoint(pygame.mouse.get_pos()):  # soft highlight so it feels clickable
        hl = pygame.Surface(TIMER_RECT.size, pygame.SRCALPHA)
        pygame.draw.rect(hl, (255, 255, 255, 60), hl.get_rect(), border_radius=18)
        screen.blit(hl, TIMER_RECT)
    if countdown:
        hrs = prog.hours_to_next()
        secs = 0 if hrs is None else math.ceil(hrs * 3600)  # round up so 0:00 lands exactly on the unlock
        clock_text = fmt_clock(secs)
        caption = "All fish unlocked" if hrs is None else "Until next fish"
    else:
        clock_text = fmt_clock(prog.session)
        caption = "Studied this session"
    draw_text(screen, clock_text, font(66, True), INK, (W // 2, 46))
    draw_text(screen, caption, font(15, True), INK, (W // 2, 90))

    board_rect = a.board_home.get_rect(center=(W // 2, 268))
    screen.blit(a.board_home, board_rect)

    lvl = prog.level
    frames = a.fish[lvl].big
    idx = mouth_index(music, len(frames), mouth_t / 0.18)
    if music is not None and music.is_playing and music.base_bpm > 0:
        bob = -math.sin(music.beat_phase() * math.pi) * 8  # hops up on each beat
    else:
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
        "next": ("Time to next fish", "All unlocked!" if hrs is None else fmt_hm(hrs * 3600)),
        "total": ("Total studied", fmt_dur(prog.total)),
    }
    ox, oy = a.books_origin
    s = a.books_scale
    for cx, cy, key, light in SPINES:
        label, value = values[key]
        # Light cream text with a dark outline on the dark-red books,
        # dark text with a cream outline on the gold books.
        color = (255, 240, 200) if light else (30, 15, 5)
        outline = (45, 18, 8) if light else (255, 244, 214)
        px = bx + (cx - ox) * s
        py = by + (cy - oy) * s
        draw_text_outlined(screen, label, fit_font(label, 15, 210, True), color, outline, (px, py - 11))
        draw_text_outlined(screen, value, fit_font(value, 20, 210, True), color, outline, (px, py + 10))


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


def draw_living_room(screen, a, prog, t, music):
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

    # Fish plaques: the fish you saved from the Gallery, in the order you saved them
    for slot, pos in enumerate(SLOTS):
        fish_i = prog.favorites[slot] if slot < len(prog.favorites) else None
        board = a.board_plaque if fish_i is not None else a.board_locked
        rect = board.get_rect(center=pos)
        screen.blit(board, rect)
        if fish_i is not None:
            frames = a.fish[fish_i].plaque
            idx = mouth_index(music, len(frames), t * 4, slot * 3)
            screen.blit(frames[idx], frames[idx].get_rect(center=(pos[0], pos[1] - 2)))
            label = FISH[fish_i]["name"]
        else:
            draw_text(screen, "+", font(64, True), (200, 190, 170), pos)
            label = "Empty slot"
        plate = pygame.Rect(0, 0, 128, 20)
        plate.midtop = (pos[0], rect.bottom + 4)
        pygame.draw.rect(screen, (196, 160, 70), plate, border_radius=3)
        pygame.draw.rect(screen, (120, 90, 30), plate, 1, border_radius=3)
        draw_text(screen, label, fit_font(label, 13, 120, True), (50, 34, 10), plate.center)
        if fish_i is None:
            draw_text(screen, "Pick one in the Gallery", font(13), CREAM,
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


# --------------------------------------------------------------------------
# Gallery page: every fish in a scrolling grid
# --------------------------------------------------------------------------
def gallery_cells(n, scroll):
    """(fish index, plaque center x, plaque center y) for every fish, shifted up by the scroll amount."""
    cells = []
    for i in range(n):
        row, col = divmod(i, GALLERY_COLS)
        cx = GALLERY_LEFT + col * GALLERY_CELL_W + GALLERY_CELL_W // 2
        cy = GALLERY_VIEW.top + 10 + row * GALLERY_ROW_H + 75 - round(scroll)
        cells.append((i, cx, cy))
    return cells


def gallery_hit(pos, n, scroll):
    """Index of the fish under the mouse position, or None."""
    if not GALLERY_VIEW.collidepoint(pos):
        return None
    for i, cx, cy in gallery_cells(n, scroll):
        if pygame.Rect(cx - 105, cy - 75, 210, 178).collidepoint(pos):  # plaque + name plate
            return i
    return None


def gallery_content_h(n):
    rows = -(-n // GALLERY_COLS)  # ceiling division
    return rows * GALLERY_ROW_H + 20


def gallery_max_scroll(n):
    return max(0, gallery_content_h(n) - GALLERY_VIEW.height)


def gallery_scrollbar(n, scroll):
    """(track rect, thumb rect), or None when everything already fits on screen."""
    max_s = gallery_max_scroll(n)
    if max_s <= 0:
        return None
    track = pygame.Rect(W - 16, GALLERY_VIEW.top + 8, 10, GALLERY_VIEW.height - 16)
    thumb_h = max(40, round(track.height * GALLERY_VIEW.height / gallery_content_h(n)))
    thumb_y = track.top + round((track.height - thumb_h) * scroll / max_s)
    return track, pygame.Rect(track.left, thumb_y, track.width, thumb_h)


def gallery_scroll_from_mouse(n, mouse_y):
    """Scroll amount that puts the scrollbar thumb under the mouse (for dragging)."""
    bar = gallery_scrollbar(n, 0)
    if bar is None:
        return 0.0
    track, thumb = bar
    span = track.height - thumb.height
    frac = (mouse_y - track.top - thumb.height / 2) / span
    return max(0.0, min(1.0, frac)) * gallery_max_scroll(n)


def draw_gallery(screen, a, prog, t, music, scroll):
    screen.blit(a.bg, (0, 0))
    n = len(FISH)
    hover_i = gallery_hit(pygame.mouse.get_pos(), n, scroll)

    screen.set_clip(GALLERY_VIEW)  # nothing drawn below can leak over the header
    for i, cx, cy in gallery_cells(n, scroll):
        if cy + 110 < GALLERY_VIEW.top or cy - 90 > GALLERY_VIEW.bottom:
            continue  # off screen, skip
        unlocked = i <= prog.level
        board = a.board_plaque if unlocked else a.board_gray
        rect = board.get_rect(center=(cx, cy))
        screen.blit(board, rect)

        if unlocked:  # unlocked fish sing along with the music
            frames = a.fish[i].plaque
            idx = mouth_index(music, len(frames), t * 4, i * 3)
        else:         # locked fish are gray and still
            frames = a.fish[i].plaque_gray
            idx = 0
        screen.blit(frames[idx], frames[idx].get_rect(center=(cx, cy - 2)))

        if unlocked and i == hover_i:  # hover outline: this one is clickable
            pygame.draw.rect(screen, CREAM, rect.inflate(8, 8), 3, border_radius=14)

        if i in prog.favorites:  # gold badge = hanging in the living room, number = which slot
            badge = (rect.right - 14, rect.top + 14)
            pygame.draw.circle(screen, (232, 186, 64), badge, 15)
            pygame.draw.circle(screen, (120, 80, 20), badge, 15, 2)
            draw_text(screen, str(prog.favorites.index(i) + 1), font(18, True), INK, badge)

        plate = pygame.Rect(0, 0, 148, 20)
        plate.midtop = (cx, rect.bottom + 4)
        pygame.draw.rect(screen, (196, 160, 70) if unlocked else (128, 120, 104), plate, border_radius=3)
        pygame.draw.rect(screen, (120, 90, 30) if unlocked else (84, 78, 66), plate, 1, border_radius=3)
        name = FISH[i]["name"]
        draw_text(screen, name, fit_font(name, 13, 140, True),
                  (50, 34, 10) if unlocked else (60, 56, 48), plate.center)
        if not unlocked:
            draw_text(screen, f"Unlocks at {FISH[i]['unlock_h']:g} hrs", font(13), CREAM,
                      (cx, plate.bottom + 10), shadow=(0, 0, 0))
    screen.set_clip(None)

    bar = gallery_scrollbar(n, scroll)
    if bar:
        track, thumb = bar
        pygame.draw.rect(screen, (40, 25, 15), track, border_radius=5)
        pygame.draw.rect(screen, (225, 210, 175), thumb, border_radius=5)

    # Header
    head = pygame.Surface((W, GALLERY_VIEW.top), pygame.SRCALPHA)
    head.fill((20, 12, 8, 220))
    screen.blit(head, (0, 0))
    draw_text(screen, "Fish Gallery", font(34, True), CREAM, (W // 2, 31), shadow=(0, 0, 0))
    draw_text(screen,
              f"Click an unlocked fish to save it to your living room ({len(prog.favorites)}/{MAX_FAVORITES}). "
              "Gold badge = on display.",
              font(16), CREAM, (W // 2, 65))
    draw_text(screen, f"Collected {prog.level + 1} / {n}", font(18, True), CREAM, (W - 30, 31), anchor="midright")


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

    #logo app icon
    pygame.display.set_icon(logo)
    pygame.display.set_caption("School of Bass")
    
    clock = pygame.time.Clock()

    a = load_assets()
    prog = Progress()
    music = None        # the MusicReader that's playing (None = no music)
    music_song = None   # file name of the song that's loaded right now

    btn_info = Button(a.info, (70, H - 52))
    btn_pause = Button(a.pause, (W // 2, H - 50))
    btn_fish = Button(a.fish_btn, (W - 90, H - 52))
    btn_back = Button(a.back, (48, 48))
    btn_gallery = Button(a.gallery_btn, (W - 100, H - 52))  # on the living room page

    cur_rect = pygame.Rect(0, 0, *CARD)
    cur_rect.midtop = (300, 70)
    next_rect = pygame.Rect(0, 0, *CARD)
    next_rect.midtop = (300, 272)
    cards = {}
    for i in range(len(FISH)):
        cards[(i, False)] = make_card(a, i, False)
        cards[(i, True)] = make_card(a, i, True)

    # countdown False = count up (default); gscroll = gallery scroll in pixels; gdrag = dragging the scrollbar
    state = {"page": "home", "paused": False, "countdown": False, "gscroll": 0.0, "gdrag": False}
    toast = {"queue": [], "text": "", "ttl": 0.0}
    t = mouth_t = save_timer = 0.0
    just_reset = False  # True for one frame after pressing R

    def start_music(fish_idx):
        """Stop whatever is playing and start the song that belongs to this fish."""
        nonlocal music, music_song
        if music:
            music.stop()
        music = load_music(fish_idx)
        music_song = song_for_fish(fish_idx) if music else None
        if music and state["paused"]:
            music.pause()

    def notify(msg):
        """Show a short message right away (replaces whatever toast is showing)."""
        toast["text"] = msg
        toast["ttl"] = 2.5

    def click_fish(i):
        """Gallery click: save the fish to the living room, or take it back out."""
        name = FISH[i]["name"]
        result = prog.toggle_favorite(i)
        if result == "added":
            notify(f"{name} added to your living room")
            prog.save()
        elif result == "removed":
            notify(f"{name} removed from your living room")
            prog.save()
        elif result == "full":
            notify("Living room is full: click a fish with a gold badge to swap it out")
        else:
            notify(f"{name} unlocks at {FISH[i]['unlock_h']:g} hrs studied")

    def advance(sec):
        lvl_before = prog.level
        prog.add(sec)
        if prog.level > lvl_before:
            for new_i in range(lvl_before + 1, prog.level + 1):
                prog.auto_pin(new_i)  # a new fish takes a free living-room slot automatically
            toast["queue"].append(f"New fish unlocked: {FISH[prog.level]['name']}!")
            if song_for_fish(prog.level) != music_song:  # the new fish has its own song
                start_music(prog.level)
        for name in prog.check_honors():
            toast["queue"].append(f"Honor unlocked: {name}")

    def go_pause():
        state["paused"] = True
        state["page"] = "pause"
        if music:
            music.pause()
        prog.save()

    def go_resume():
        state["paused"] = False
        state["page"] = "home"
        if music:
            music.unpause()

    start_music(prog.level)  # play the song of the fish on the home screen

    while True:
        dt = min(clock.tick(FPS) / 1000, 0.1)
        just_reset = False
        t += dt

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                prog.save()
                if music:
                    music.stop()
                pygame.quit()
                sys.exit()
            page = state["page"]

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if page in ("info", "living"):
                        state["page"] = "home"
                    elif page == "gallery":
                        state["page"] = "living"
                    elif page == "pause":
                        go_resume()
                elif event.key == pygame.K_SPACE:
                    if page == "home":
                        go_pause()
                    elif page == "pause":
                        go_resume()
                elif page == "gallery" and event.key in (pygame.K_UP, pygame.K_DOWN,
                                                         pygame.K_PAGEUP, pygame.K_PAGEDOWN):
                    step = {pygame.K_UP: -60, pygame.K_DOWN: 60,
                            pygame.K_PAGEUP: -340, pygame.K_PAGEDOWN: 340}[event.key]
                    state["gscroll"] = max(0, min(gallery_max_scroll(len(FISH)), state["gscroll"] + step))
                elif DEBUG_KEYS and event.key == pygame.K_t and not state["paused"]:
                    advance(900)
                elif DEBUG_KEYS and event.key == pygame.K_l and not state["paused"]:
                    # Jump straight to the next fish's unlock time
                    hrs = prog.hours_to_next()
                    if hrs is not None:  # None means every fish is already unlocked
                        advance(hrs * 3600 + 1)  # +1 second so rounding can't leave us just short
                elif DEBUG_KEYS and event.key == pygame.K_r:
                    # Put EVERYTHING back to a fresh start
                    prog.reset()                       # total, max session, session clock, honors -> 0 (and saved)
                    mouth_t = save_timer = 0.0         # mouth animation + autosave timers
                    toast["queue"].clear()             # drop pending toasts...
                    toast["ttl"] = 0.0                 # ...and hide the one on screen
                    toast["text"] = ""
                    state["paused"] = False            # leave the pause screen if we were on it
                    state["page"] = "home"             # always return to the home page
                    state["countdown"] = False         # timer back to its default: counting up
                    state["gscroll"] = 0.0             # gallery back to the top
                    state["gdrag"] = False
                    start_music(prog.level)            # restart music from the beginning (starter fish's song)
                    just_reset = True                  # skip this frame's time tick so the clock reads 0
                    toast["queue"].append("Progress reset to 0")

            if page == "home":
                if btn_pause.clicked(event):
                    go_pause()
                elif btn_info.clicked(event):
                    state["page"] = "info"
                elif btn_fish.clicked(event):
                    state["page"] = "living"
                elif (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                        and TIMER_RECT.collidepoint(event.pos)):
                    state["countdown"] = not state["countdown"]  # flip count up <-> count down
            elif page == "pause":
                if (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                        and cur_rect.collidepoint(event.pos)):
                    go_resume()
            elif page == "living":
                if btn_back.clicked(event):
                    state["page"] = "home"
                elif btn_gallery.clicked(event):
                    state["page"] = "gallery"
                elif (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                        and any(a.board_plaque.get_rect(center=pos).collidepoint(event.pos) for pos in SLOTS)):
                    state["page"] = "gallery"  # clicking a plaque also opens the gallery
            elif page == "gallery":
                n = len(FISH)
                if btn_back.clicked(event):
                    state["page"] = "living"
                elif event.type == pygame.MOUSEWHEEL:  # event.y: +1 = wheel up, -1 = wheel down
                    state["gscroll"] = max(0, min(gallery_max_scroll(n), state["gscroll"] - event.y * 60))
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    bar = gallery_scrollbar(n, state["gscroll"])
                    if bar and bar[0].inflate(16, 0).collidepoint(event.pos):
                        state["gdrag"] = True  # grabbed the scrollbar
                        state["gscroll"] = gallery_scroll_from_mouse(n, event.pos[1])
                    else:
                        clicked_fish = gallery_hit(event.pos, n, state["gscroll"])
                        if clicked_fish is not None:
                            click_fish(clicked_fish)
                elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    state["gdrag"] = False
                elif event.type == pygame.MOUSEMOTION and state["gdrag"]:
                    state["gscroll"] = gallery_scroll_from_mouse(n, event.pos[1])
            elif btn_back.clicked(event):
                state["page"] = "home"

        if music:
            music.update()  # keeps the loop going and tracks beats

        # Time only counts while studying (not paused)
        if not state["paused"] and not just_reset:
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
            draw_home(screen, a, prog, t, mouth_t, music, state["countdown"])
            btn_info.draw(screen)
            btn_pause.draw(screen)
            btn_fish.draw(screen)
        elif page == "pause":
            draw_pause(screen, a, prog, cards, cur_rect, next_rect)
        elif page == "info":
            draw_info(screen, a)
            btn_back.draw(screen)
        elif page == "living":
            draw_living_room(screen, a, prog, t, music)
            btn_back.draw(screen)
            btn_gallery.draw(screen)
        else:  # gallery
            state["gscroll"] = min(state["gscroll"], gallery_max_scroll(len(FISH)))
            draw_gallery(screen, a, prog, t, music, state["gscroll"])
            btn_back.draw(screen)

        if page != "pause" and toast["ttl"] > 0:
            draw_toast(screen, toast["text"])

        pygame.display.flip()


if __name__ == "__main__":
    main()