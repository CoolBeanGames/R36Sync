"""
Automated Test Suite for R36Sync.
Tests database operations, Minerva directory parsing, SD card detection,
sync/unsync engine, and save backup mechanisms.
"""
from pathlib import Path
import shutil
import tempfile
import unittest

from r36sync.config import CONSOLES, ConsoleDef
from r36sync.database import Database, clean_game_title
from r36sync.sd_detector import SDDetector, SDCardInfo
from r36sync.sync_manager import SyncManager, LibraryGame
from r36sync.cover_art import CoverArtManager


class TestR36Sync(unittest.TestCase):

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="r36sync_test_"))
        self.db_path = self.test_dir / "test_r36sync.db"
        self.db = Database(self.db_path)
        self.library_dir = self.test_dir / "Library"
        self.library_dir.mkdir(parents=True)
        self.backup_dir = self.test_dir / "Backups"
        self.backup_dir.mkdir(parents=True)
        self.sd_root = self.test_dir / "SDCard"
        self.sd_root.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_clean_game_title(self):
        self.assertEqual(clean_game_title("Pokemon - Emerald Version (USA, Europe).zip"), "Pokemon - Emerald Version")
        self.assertEqual(clean_game_title("Super Mario World [p].sfc"), "Super Mario World")
        self.assertEqual(clean_game_title("The Legend of Zelda - Link's Awakening (Rev 1).gb"), "The Legend of Zelda - Link's Awakening")

    def test_database_upsert_and_search(self):
        sample_roms = [
            {
                "minerva_id": "101",
                "title": "Super Mario Land",
                "clean_title": "Super Mario Land",
                "file_name": "Super Mario Land (World).zip",
                "console_code": "gb",
                "console_name": "Game Boy",
                "group_name": "No-Intro",
                "size_str": "64.00 KB",
                "torrent_url": "https://minerva-archive.org/assets/test.torrent",
                "magnet_url": "magnet:?xt=urn:btih:123",
                "rom_url": "https://minerva-archive.org/rom?id=101",
                "torrent_file_idx": 1
            },
            {
                "minerva_id": "102",
                "title": "Pokemon Red",
                "clean_title": "Pokemon Red",
                "file_name": "Pokemon - Red Version (USA, Europe).zip",
                "console_code": "gb",
                "console_name": "Game Boy",
                "group_name": "No-Intro",
                "size_str": "512.00 KB",
                "torrent_url": "https://minerva-archive.org/assets/test.torrent",
                "magnet_url": "magnet:?xt=urn:btih:123",
                "rom_url": "https://minerva-archive.org/rom?id=102",
                "torrent_file_idx": 2
            },
            {
                "minerva_id": "103",
                "title": "Super Mario Advance",
                "clean_title": "Super Mario Advance",
                "file_name": "Super Mario Advance (USA, Europe).zip",
                "console_code": "gba",
                "console_name": "Game Boy Advance",
                "group_name": "No-Intro",
                "size_str": "2.00 MB",
                "torrent_url": "https://minerva-archive.org/assets/test.torrent",
                "magnet_url": "magnet:?xt=urn:btih:123",
                "rom_url": "https://minerva-archive.org/rom?id=103",
                "torrent_file_idx": 3
            }
        ]

        inserted = self.db.upsert_roms(sample_roms)
        self.assertEqual(inserted, 3)
        self.assertEqual(self.db.get_total_rom_count(), 3)

        # Search Mario (both GB and GBA)
        results = self.db.search_roms(query="Mario")
        self.assertEqual(len(results), 2)

        # Search Mario on GB only
        gb_mario = self.db.search_roms(query="Mario", console_code="gb")
        self.assertEqual(len(gb_mario), 1)
        self.assertEqual(gb_mario[0]["file_name"], "Super Mario Land (World).zip")

        # Search Pokemon
        pkmn = self.db.search_roms(query="Pokemon")
        self.assertEqual(len(pkmn), 1)
        self.assertEqual(pkmn[0]["clean_title"], "Pokemon Red")

        # Summary count
        summary = self.db.get_consoles_summary()
        self.assertTrue(any(s["console_code"] == "gb" and s["count"] == 2 for s in summary))
        self.assertTrue(any(s["console_code"] == "gba" and s["count"] == 1 for s in summary))

    def test_save_backup_recording(self):
        row_id = self.db.record_save_backup(
            game_title="Pokemon Red",
            console_code="gb",
            save_type="srm",
            file_name="Pokemon Red.srm",
            source_path="E:/gb/Pokemon Red.srm",
            backup_path=str(self.backup_dir / "Pokemon Red.srm"),
            file_size=32768
        )
        self.assertGreater(row_id, 0)
        self.assertEqual(self.db.get_total_saves_count(), 1)
        backups = self.db.get_save_backups()
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0]["file_name"], "Pokemon Red.srm")

    def test_sd_folder_detection_and_creation(self):
        # Fresh folder should have 0 matches initially
        _, matches, score = SDDetector.check_folder_structure(self.sd_root)
        self.assertEqual(len(matches), 0)

        # Create R36S structure
        created = SDDetector.create_r36s_folder_structure(self.sd_root)
        self.assertIn("gb", created)
        self.assertIn("gba", created)
        self.assertIn("snes", created)
        self.assertTrue((self.sd_root / "gba" / "images").exists())

        # Check again
        _, matches_after, score_after = SDDetector.check_folder_structure(self.sd_root)
        self.assertGreater(len(matches_after), 10)
        self.assertGreaterEqual(score_after, 50)

    def test_sync_and_unsync_lifecycle_with_save_backup(self):
        # 1. Setup local Library with 2 GBA games
        gba_lib = self.library_dir / "gba"
        gba_lib.mkdir(parents=True)
        game1_file = gba_lib / "Pokemon - FireRed.zip"
        game2_file = gba_lib / "Zelda - Minish Cap.zip"
        game1_file.write_bytes(b"TEST_ROM_1_DATA")
        game2_file.write_bytes(b"TEST_ROM_2_DATA")

        # Create cover art
        art_dir = gba_lib / "images"
        art_dir.mkdir(parents=True)
        (art_dir / "Pokemon - FireRed-image.png").write_bytes(b"FAKE_PNG_ART")

        # 2. Setup SD card with only game 1 and an existing save file (.srm)
        sd_gba = self.sd_root / "gba"
        sd_gba.mkdir(parents=True)
        (sd_gba / "Pokemon - FireRed.zip").write_bytes(b"TEST_ROM_1_DATA")
        save_file = sd_gba / "Pokemon - FireRed.srm"
        save_file.write_bytes(b"BATTERY_RAM_SAVE_DATA_12345")

        sm = SyncManager()

        # 3. Scan library: game1 should be marked on_handheld=True and checked=True
        # game2 should be on_handheld=False and checked=False
        games = sm.scan_library(str(self.library_dir), self.sd_root)
        self.assertEqual(len(games), 2)

        g1 = next(g for g in games if g.stem == "Pokemon - FireRed")
        g2 = next(g for g in games if g.stem == "Zelda - Minish Cap")

        self.assertTrue(g1.is_on_handheld)
        self.assertTrue(g1.is_checked)
        self.assertFalse(g2.is_on_handheld)
        self.assertFalse(g2.is_checked)

        # 4. Action: User wants to SYNC game2 (check game2), and UNSYNC game1 (uncheck game1)
        g1.is_checked = False
        g2.is_checked = True

        result = sm.sync_to_handheld(games, self.sd_root, str(self.backup_dir))

        # Check results
        self.assertEqual(result.synced_count, 1)    # Game 2 copied
        self.assertEqual(result.unsynced_count, 1)  # Game 1 removed
        self.assertEqual(result.saves_backed_up, 1) # Save file was backed up!

        # Verify on SD card: game2 is present, game1 is removed
        self.assertTrue((sd_gba / "Zelda - Minish Cap.zip").exists())
        self.assertFalse((sd_gba / "Pokemon - FireRed.zip").exists())

        # Verify save backup exists in PC backup folder
        latest_save = self.backup_dir / "latest" / "gba" / "Pokemon - FireRed.srm"
        self.assertTrue(latest_save.exists())
        self.assertEqual(latest_save.read_bytes(), b"BATTERY_RAM_SAVE_DATA_12345")

    def test_cover_art_fallback(self):
        cm = CoverArtManager()
        out_art = self.test_dir / "test_fallback.png"
        cm.generate_fallback_cover("Metroid Fusion", "gba", out_art)
        self.assertTrue(out_art.exists())
        self.assertGreater(out_art.stat().st_size, 500)


if __name__ == "__main__":
    unittest.main()
