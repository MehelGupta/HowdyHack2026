import math
import os
import sys

import pygame

W, H = 960, 640
FPS = 60
BASE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(BASE, "assets")
MUSIC_DIR = os.path.join(BASE, "music")
MUSIC_END = pygame.USEREVENT + 1
BROWN = (70, 40, 20)
CREAM = (240, 230, 210)


def load(name, width=None, height=None):
    img = pygame.image.load(os.path.join(ASSETS, name)).convert_alpha()
    if width and not height:
        height = round(img.get_height() * width / img.get_width())
    elif height and not width:
        width = round(img.get_width() * height / img.get_height())
    if width and height:
        img = pygame.transform.smoothscale(img, (width, height))
    return img


def cover(img, w, h):
    """Scale image so it fills w x h completely, cropping the overflow."""
    scale = max(w / img.get_width(), h / img.get_height())
    scaled = pygame.transform.smoothscale(
        img, (round(img.get_width() * scale), round(img.get_height() * scale))
    )
    surf = pygame.Surface((w, h))
    surf.blit(scaled, ((w - scaled.get_width()) // 2, (h - scaled.get_height()) // 2))
    return surf


def wrap(text, font, max_w):
    lines, line = [], ""
    for word in text.split():
        test = f"{line} {word}".strip()
        if font.size(test)[0] <= max_w:
            line = test
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


class Button:
    def __init__(self, image, center):
        self.image = image
        self.rect = image.get_rect(center=center)

    def hovered(self):
        return self.rect.collidepoint(pygame.mouse.get_pos())

    def draw(self, screen):
        if self.hovered():
            big = pygame.transform.smoothscale(
                self.image,
                (round(self.rect.w * 1.12), round(self.rect.h * 1.12)),
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


class Playlist:
    def __init__(self):
        exts = (".mp3", ".ogg", ".wav")
        self.tracks = (
            sorted(f for f in os.listdir(MUSIC_DIR) if f.lower().endswith(exts))
            if os.path.isdir(MUSIC_DIR)
            else []
        )
        self.index = 0
        self.paused = False
        self.started = False
        if self.tracks:
            pygame.mixer.music.set_endevent(MUSIC_END)
            self.play_current()

    @property
    def title(self):
        if not self.tracks:
            return "No music yet"
        return os.path.splitext(self.tracks[self.index])[0]

    @property
    def playing(self):
        return bool(self.tracks) and self.started and not self.paused

    def play_current(self):
        pygame.mixer.music.load(os.path.join(MUSIC_DIR, self.tracks[self.index]))
        pygame.mixer.music.play()
        self.started = True
        self.paused = False

    def next(self):
        if self.tracks:
            self.index = (self.index + 1) % len(self.tracks)
            self.play_current()

    def toggle_pause(self):
        if not self.tracks:
            return
        if self.paused:
            pygame.mixer.music.unpause()
        else:
            pygame.mixer.music.pause()
        self.paused = not self.paused


def load_fish_frames(width):
    """Loads fish_frame1.png, fish_frame2.png, ... as long as they exist."""
    frames, i = [], 1
    while os.path.exists(os.path.join(ASSETS, f"fish_frame{i}.png")):
        frames.append(load(f"fish_frame{i}.png", width=width))
        i += 1
    return frames


def draw_page(screen, bg, title, subtitle, fonts, back_rect):
    screen.blit(bg, (0, 0))
    panel = pygame.Surface((W - 200, H - 200), pygame.SRCALPHA)
    panel.fill((20, 12, 8, 215))
    screen.blit(panel, (100, 100))
    t = fonts["big"].render(title, True, CREAM)
    screen.blit(t, t.get_rect(center=(W // 2, 220)))
    s = fonts["small"].render(subtitle, True, CREAM)
    screen.blit(s, s.get_rect(center=(W // 2, 290)))
    hover = back_rect.collidepoint(pygame.mouse.get_pos())
    pygame.draw.rect(screen, (90, 140, 90) if hover else (50, 100, 50), back_rect, border_radius=10)
    b = fonts["small"].render("< Back", True, CREAM)
    screen.blit(b, b.get_rect(center=back_rect.center))


def main():
    pygame.init()
    try:
        pygame.mixer.init()
    except pygame.error:
        print("Audio device not available; running without sound.")
    screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption("Lofi Fish")
    clock = pygame.time.Clock()
    fonts = {
        "big": pygame.font.SysFont("georgia", 44, bold=True),
        "med": pygame.font.SysFont("georgia", 22, bold=True),
        "small": pygame.font.SysFont("georgia", 20),
    }

    bg = cover(pygame.image.load(os.path.join(ASSETS, "brickBG.jpg")).convert(), W, H)
    books = load("books.png", height=270)
    plaque = load("woodBoard.png", width=230)
    fish_frames = load_fish_frames(430)

    btn = 64
    pause_btn = Button(load("pauseButton.png", btn, btn), (W - 50, 50))
    info_btn = Button(load("infoButton.png", btn, btn), (W - 130, 50))
    fish_btn = Button(load("fishButton.png", width=btn + 20), (W - 225, 50))
    back_rect = pygame.Rect(0, 0, 140, 44)
    back_rect.center = (W // 2, H - 150)

    playlist = Playlist()
    page = "main"  # "main", "fish", "info"
    t = 0.0
    mouth_timer = 0.0
    mouth_index = 0

    while True:
        dt = clock.tick(FPS) / 1000
        t += dt
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type == MUSIC_END:
                playlist.next()
            if page == "main":
                if pause_btn.clicked(event):
                    playlist.toggle_pause()
                elif info_btn.clicked(event):
                    page = "info"
                elif fish_btn.clicked(event):
                    page = "fish"
            else:
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and back_rect.collidepoint(event.pos):
                    page = "main"
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    page = "main"

        if page == "fish":
            draw_page(screen, bg, "Fish Page", "Placeholder: tell me what goes here!", fonts, back_rect)
        elif page == "info":
            draw_page(screen, bg, "Info", "Placeholder: tell me what goes here!", fonts, back_rect)
        else:
            screen.blit(bg, (0, 0))
            screen.blit(books, (30, H - books.get_height() - 10))

            # Now-playing plaque
            plaque_pos = (W - plaque.get_width() - 40, 150)
            screen.blit(plaque, plaque_pos)
            cx = plaque_pos[0] + plaque.get_width() // 2
            y = plaque_pos[1] + 70
            label = fonts["small"].render("Now Playing", True, BROWN)
            screen.blit(label, label.get_rect(center=(cx, y)))
            y += 36
            for line in wrap(playlist.title, fonts["med"], plaque.get_width() - 90)[:4]:
                surf = fonts["med"].render(line, True, BROWN)
                screen.blit(surf, surf.get_rect(center=(cx, y)))
                y += 28
            if playlist.paused:
                p = fonts["small"].render("(paused)", True, BROWN)
                screen.blit(p, p.get_rect(center=(cx, y + 10)))

            # Fish: bob + sway while music plays; mouth frames swap if you add more
            if fish_frames:
                singing = playlist.playing
                if singing and len(fish_frames) > 1:
                    mouth_timer += dt
                    if mouth_timer > 0.25:
                        mouth_timer = 0
                        mouth_index = (mouth_index + 1) % len(fish_frames)
                else:
                    mouth_index = 0
                speed = 2.2 if singing else 0.8
                amp = 12 if singing else 4
                bob = math.sin(t * speed) * amp
                sway = math.sin(t * speed * 0.7) * (4 if singing else 1)
                fish = pygame.transform.rotozoom(fish_frames[mouth_index], sway, 1.0)
                screen.blit(fish, fish.get_rect(center=(W // 2 - 20, H // 2 + bob)))

            fish_btn.draw(screen)
            info_btn.draw(screen)
            pause_btn.draw(screen)

        pygame.display.flip()


if __name__ == "__main__":
    main()