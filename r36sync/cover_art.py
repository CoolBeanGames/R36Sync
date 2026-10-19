"""
Cover art management module for R36Sync.
Fetches high-quality box art from Libretro's repository and caches it locally.
"""
import io
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional, Tuple
from PIL import Image, ImageDraw, ImageFont
from .config import CONSOLES, settings

LIBRETRO_BASE_URL = "https://thumbnails.libretro.com"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) R36Sync/1.0"


class CoverArtManager:
    """Handles fetching, caching, and loading game box arts."""

    def __init__(self):
        self._memory_cache = {}

    def get_cover_art_path(self, library_dir: str, console_code: str, rom_name: str) -> Path:
        """Returns standard ArkOS cover art path: <console>/images/<rom_stem>-image.png"""
        stem = Path(rom_name).stem
        console_folder = Path(library_dir) / console_code
        images_dir = console_folder / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        return images_dir / f"{stem}-image.png"

    def has_cover_art(self, library_dir: str, console_code: str, rom_name: str) -> bool:
        """Checks if cover art exists on disk."""
        target = self.get_cover_art_path(library_dir, console_code, rom_name)
        if target.exists():
            return True
        # Also check without -image suffix
        alt = target.parent / f"{Path(rom_name).stem}.png"
        return alt.exists()

    def download_cover_art(
        self,
        console_code: str,
        rom_name: str,
        destination_path: Optional[Path] = None,
        library_dir: Optional[str] = None
    ) -> Optional[Path]:
        """
        Attempts to download box art from Libretro thumbnails repo.
        Falls back to generated retro cover if unavailable.
        """
        if not destination_path:
            lib = library_dir or settings.library_dir
            destination_path = self.get_cover_art_path(lib, console_code, rom_name)

        if destination_path.exists():
            return destination_path

        console_def = CONSOLES.get(console_code)
        if not console_def or not console_def.libretro_name:
            self.generate_fallback_cover(rom_name, console_code, destination_path)
            return destination_path

        stem = Path(rom_name).stem

        # Candidate names to search on Libretro
        candidates = [
            stem,  # Exact full stem
            re.sub(r'[\(\[].*?[\)\]]', '', stem).strip(),  # Without tags
            re.sub(r'\s*\(USA.*?\)', '', stem).strip(),    # Without region
        ]

        # Deduplicate
        seen = set()
        unique_candidates = [c for c in candidates if c and not (c in seen or seen.add(c))]

        libretro_console = urllib.parse.quote(console_def.libretro_name)
        success = False

        for cand in unique_candidates:
            cand_quoted = urllib.parse.quote(f"{cand}.png")
            url = f"{LIBRETRO_BASE_URL}/{libretro_console}/Named_Boxarts/{cand_quoted}"

            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=8) as res:
                    if res.status == 200:
                        img_data = res.read()
                        destination_path.parent.mkdir(parents=True, exist_ok=True)
                        with open(destination_path, "wb") as f:
                            f.write(img_data)
                        success = True
                        break
            except Exception:
                continue

        if not success:
            # Generate a clean retro badge placeholder
            self.generate_fallback_cover(rom_name, console_code, destination_path)

        return destination_path

    def generate_fallback_cover(self, rom_name: str, console_code: str, output_path: Path):
        """Generates a stylish retro cart placeholder image when no online art is found."""
        try:
            width, height = 300, 400
            # Modern dark retro gradient / palette
            palette = {
                "gba": ((26, 42, 108), (178, 31, 31)),
                "gb": ((46, 117, 89), (13, 71, 161)),
                "gbc": ((92, 37, 141), (67, 137, 162)),
                "snes": ((74, 20, 140), (49, 27, 146)),
                "nes": ((183, 28, 28), (33, 33, 33)),
                "megadrive": ((33, 33, 33), (13, 71, 161)),
                "psx": ((33, 33, 33), (66, 66, 66)),
                "n64": ((27, 94, 32), (183, 28, 28))
            }
            c1, c2 = palette.get(console_code, ((30, 30, 45), (15, 15, 25)))

            img = Image.new("RGB", (width, height), color=c1)
            draw = ImageDraw.Draw(img)

            # Draw cart bevel border
            draw.rectangle([10, 10, width - 10, height - 10], outline=(80, 80, 100), width=3)
            draw.rectangle([20, 20, width - 20, height - 20], fill=c2)

            # Banner header
            display_console = CONSOLES.get(console_code, None)
            console_name = display_console.display_name if display_console else console_code.upper()

            draw.rectangle([20, 20, width - 20, 60], fill=(20, 20, 30))
            draw.text((30, 30), console_name[:24], fill=(240, 240, 240))

            # Game title in center
            stem = Path(rom_name).stem
            # Wrap text roughly
            words = stem.split()
            lines = []
            cur_line = []
            for w in words:
                cur_line.append(w)
                if len(" ".join(cur_line)) > 18:
                    lines.append(" ".join(cur_line))
                    cur_line = []
            if cur_line:
                lines.append(" ".join(cur_line))

            y = 120
            for line in lines[:6]:
                draw.text((30, y), line, fill=(255, 255, 255))
                y += 26

            output_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(output_path, "PNG")
        except Exception as e:
            print(f"Error generating fallback cover: {e}")

    def load_thumbnail_image(
        self,
        cover_path: Path,
        max_size: Tuple[int, int] = (64, 64)
    ) -> Optional[Image.Image]:
        """Loads and scales a PIL Image for UI display."""
        if not cover_path.exists():
            return None
        try:
            with Image.open(cover_path) as img:
                img = img.convert("RGBA")
                img.thumbnail(max_size, Image.Resampling.LANCZOS)
                return img.copy()
        except Exception as e:
            print(f"Error loading thumbnail {cover_path}: {e}")
            return None


# Global cover art manager
cover_manager = CoverArtManager()
