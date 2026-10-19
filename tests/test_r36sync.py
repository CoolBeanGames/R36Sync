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

    def test_browse_by_console_and_letter(self):
        sample_roms = [
            {
                "minerva_id": "201",
                "title": "Castlevania - Aria of Sorrow",
                "clean_title": "Castlevania - Aria of Sorrow",
                "file_name": "Castlevania - Aria of Sorrow (USA).zip",
                "console_code": "gba",
                "console_name": "Game Boy Advance",
                "group_name": "No-Intro",
                "size_str": "4.00 MB",
                "torrent_url": "https://minerva-archive.org/assets/test.torrent",
                "magnet_url": "magnet:?xt=urn:btih:123",
                "rom_url": "https://minerva-archive.org/rom?id=201"
            },
            {
                "minerva_id": "202",
                "title": "Crash Bandicoot - The Huge Adventure",
                "clean_title": "Crash Bandicoot - The Huge Adventure",
                "file_name": "Crash Bandicoot - The Huge Adventure (USA).zip",
                "console_code": "gba",
                "console_name": "Game Boy Advance",
                "group_name": "No-Intro",
                "size_str": "4.00 MB",
                "torrent_url": "https://minerva-archive.org/assets/test.torrent",
                "magnet_url": "magnet:?xt=urn:btih:123",
                "rom_url": "https://minerva-archive.org/rom?id=202"
            },
            {
                "minerva_id": "203",
                "title": "Doom",
                "clean_title": "Doom",
                "file_name": "Doom (USA).zip",
                "console_code": "gba",
                "console_name": "Game Boy Advance",
                "group_name": "No-Intro",
                "size_str": "4.00 MB",
                "torrent_url": "https://minerva-archive.org/assets/test.torrent",
                "magnet_url": "magnet:?xt=urn:btih:123",
                "rom_url": "https://minerva-archive.org/rom?id=203"
            }
        ]
        self.db.upsert_roms(sample_roms)

        # 1. Test letters list for GBA
        letters = self.db.get_console_letters("gba")
        self.assertIn("C", letters)
        self.assertIn("D", letters)

        # 2. Browse by letter 'C'
        c_games = self.db.get_games_by_console("gba", letter="C")
        self.assertEqual(len(c_games), 2)
        self.assertTrue(all(g["clean_title"].startswith("C") for g in c_games))

        # 3. Browse by letter 'D'
        d_games = self.db.get_games_by_console("gba", letter="D")
        self.assertEqual(len(d_games), 1)
        self.assertEqual(d_games[0]["clean_title"], "Doom")

        # 4. Search within GBA
        search_res = self.db.get_games_by_console("gba", search="Aria")
        self.assertEqual(len(search_res), 1)
        self.assertEqual(search_res[0]["clean_title"], "Castlevania - Aria of Sorrow")

    def test_multidisc_detection_and_m3u_creation(self):
        from r36sync.m3u_manager import M3UManager
        m_mgr = M3UManager()

        psx_dir = self.library_dir / "psx"
        psx_dir.mkdir(parents=True, exist_ok=True)

        # Create multi-disc files for Final Fantasy VII
        disc1 = psx_dir / "Final Fantasy VII (USA) (Disc 1).chd"
        disc2 = psx_dir / "Final Fantasy VII (USA) (Disc 2).chd"
        disc3 = psx_dir / "Final Fantasy VII (USA) (Disc 3).chd"
        single_game = psx_dir / "Crash Bandicoot (USA).chd"

        disc1.write_bytes(b"DISC_1_DATA")
        disc2.write_bytes(b"DISC_2_DATA")
        disc3.write_bytes(b"DISC_3_DATA")
        single_game.write_bytes(b"SINGLE_DATA")

        # Create Disc 1 cover art
        art_dir = psx_dir / "images"
        art_dir.mkdir(parents=True, exist_ok=True)
        (art_dir / "Final Fantasy VII (USA) (Disc 1)-image.png").write_bytes(b"FAKE_ART_PNG")

        # 1. Detect multi-disc sets
        sets = m_mgr.scan_directory_for_multidisc(psx_dir, "psx")
        self.assertEqual(len(sets), 1)
        ff7_set = sets[0]
        self.assertEqual(ff7_set.base_name, "Final Fantasy VII (USA)")
        self.assertEqual(ff7_set.disc_count, 3)
        self.assertFalse(ff7_set.has_playlist)

        # Verify correct ordering (Disc 1, Disc 2, Disc 3)
        self.assertEqual(ff7_set.disc_files[0].name, "Final Fantasy VII (USA) (Disc 1).chd")
        self.assertEqual(ff7_set.disc_files[1].name, "Final Fantasy VII (USA) (Disc 2).chd")
        self.assertEqual(ff7_set.disc_files[2].name, "Final Fantasy VII (USA) (Disc 3).chd")

        # 2. Create .m3u playlist
        pl_path = m_mgr.create_playlist(ff7_set, extension=".m3u")
        self.assertTrue(pl_path.exists())
        self.assertEqual(pl_path.name, "Final Fantasy VII (USA).m3u")

        # Read playlist content
        lines = [line.strip() for line in pl_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0], "Final Fantasy VII (USA) (Disc 1).chd")
        self.assertEqual(lines[1], "Final Fantasy VII (USA) (Disc 2).chd")
        self.assertEqual(lines[2], "Final Fantasy VII (USA) (Disc 3).chd")

        # Verify cover art was linked for the playlist
        pl_art = art_dir / "Final Fantasy VII (USA)-image.png"
        self.assertTrue(pl_art.exists())

        # 3. Create .m3a playlist format test
        re2_disc1 = psx_dir / "Resident Evil 2 (USA) (Disc 1) (Leon).chd"
        re2_disc2 = psx_dir / "Resident Evil 2 (USA) (Disc 2) (Claire).chd"
        re2_disc1.write_bytes(b"RE2_D1")
        re2_disc2.write_bytes(b"RE2_D2")

        sets_re2 = m_mgr.scan_directory_for_multidisc(psx_dir, "psx")
        re2_set = next(s for s in sets_re2 if "Resident Evil 2" in s.base_name)
        m3a_path = m_mgr.create_playlist(re2_set, extension=".m3a")
        self.assertTrue(m3a_path.exists())
        self.assertEqual(m3a_path.suffix, ".m3a")

    def test_multidisc_sync_lifecycle(self):
        from r36sync.m3u_manager import m3u_manager
        from r36sync.sync_manager import SyncManager

        psx_lib = self.library_dir / "psx"
        psx_lib.mkdir(parents=True, exist_ok=True)

        d1 = psx_lib / "Metal Gear Solid (USA) (Disc 1).chd"
        d2 = psx_lib / "Metal Gear Solid (USA) (Disc 2).chd"
        d1.write_bytes(b"MGS_D1_RAW")
        d2.write_bytes(b"MGS_D2_RAW")

        sets = m_mgr = m3u_manager.scan_directory_for_multidisc(psx_lib, "psx")
        pl_path = m3u_manager.create_playlist(sets[0], extension=".m3u")

        sm = SyncManager()

        # Scan library: only the .m3u should be listed as the primary game entry, not redundant loose discs
        games = sm.scan_library(str(self.library_dir), self.sd_root)
        psx_games = [g for g in games if g.console_code == "psx"]
        self.assertEqual(len(psx_games), 1)
        self.assertTrue(psx_games[0].is_playlist)
        self.assertEqual(psx_games[0].disc_count, 2)

        # Sync to handheld
        psx_games[0].is_checked = True
        result = sm.sync_to_handheld(psx_games, self.sd_root, str(self.backup_dir))
        self.assertEqual(result.synced_count, 1)

        # Verify on SD card: .m3u playlist AND both disc files were copied!
        sd_psx = self.sd_root / "psx"
        self.assertTrue((sd_psx / "Metal Gear Solid (USA).m3u").exists())
        self.assertTrue((sd_psx / "Metal Gear Solid (USA) (Disc 1).chd").exists())
        self.assertTrue((sd_psx / "Metal Gear Solid (USA) (Disc 2).chd").exists())

    def test_live_multidisc_lifecycle(self):
        """
        Tests user exact sequence:
        1.) download game_1-disc_1
        2.) download game_1-disc_2 -> creates game_1.m3a
        3.) download game_1-disc_3 -> adds disc 3 to same game_1.m3a
        4.) delete game_1-disc_2 -> deletes disc 2 entry from same game_1.m3a
        """
        from r36sync.m3u_manager import m3u_manager

        psx_dir = self.library_dir / "psx"
        psx_dir.mkdir(parents=True, exist_ok=True)

        # 1.) Download game_1-disc_1
        d1 = psx_dir / "game_1-disc_1.chd"
        d1.write_bytes(b"DISC_1_BYTES")
        res1 = m3u_manager.handle_disc_file_added(d1, preferred_ext=".m3a", console_code="psx")
        self.assertIsNone(res1)
        self.assertFalse((psx_dir / "game_1.m3a").exists())

        # 2.) Download game_1-disc_2 -> creates game_1.m3a
        d2 = psx_dir / "game_1-disc_2.chd"
        d2.write_bytes(b"DISC_2_BYTES")
        res2 = m3u_manager.handle_disc_file_added(d2, preferred_ext=".m3a", console_code="psx")
        self.assertIsNotNone(res2)
        m3a_path = psx_dir / "game_1.m3a"
        self.assertTrue(m3a_path.exists())
        lines2 = [l.strip() for l in m3a_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(lines2, ["game_1-disc_1.chd", "game_1-disc_2.chd"])

        # 3.) Download game_1-disc_3 -> adds disc 3 to same game_1.m3a
        d3 = psx_dir / "game_1-disc_3.chd"
        d3.write_bytes(b"DISC_3_BYTES")
        res3 = m3u_manager.handle_disc_file_added(d3, preferred_ext=".m3a", console_code="psx")
        self.assertIsNotNone(res3)
        lines3 = [l.strip() for l in m3a_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(lines3, ["game_1-disc_1.chd", "game_1-disc_2.chd", "game_1-disc_3.chd"])

        # 4.) Delete game_1-disc_2 -> deletes disc 2 entry from same game_1.m3a
        d2.unlink()
        res4 = m3u_manager.handle_disc_file_removed(d2)
        self.assertEqual(len(res4), 1)
        self.assertEqual(res4[0], m3a_path)
        lines4 = [l.strip() for l in m3a_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(lines4, ["game_1-disc_1.chd", "game_1-disc_3.chd"])

        # 5.) Delete all remaining discs -> cleans up empty m3a
        d1.unlink()
        m3u_manager.handle_disc_file_removed(d1)
        self.assertTrue(m3a_path.exists())

        d3.unlink()
        m3u_manager.handle_disc_file_removed(d3)
        self.assertFalse(m3a_path.exists())

    def test_library_watcher_live_updates(self):
        """Tests that the background LibraryWatcher live detects file addition/deletion."""
        import time
        from r36sync.library_watcher import LibraryWatcher

        watcher = LibraryWatcher(debounce_delay=0.1)
        events = []
        watcher.subscribe(lambda: events.append(time.time()))

        psx_dir = self.library_dir / "psx_watcher_test"
        psx_dir.mkdir(parents=True, exist_ok=True)

        watcher.start(str(psx_dir))
        try:
            time.sleep(0.15)

            # Add disc 1
            w1 = psx_dir / "rpg_game-disc_1.chd"
            w1.write_bytes(b"W1")
            time.sleep(0.25)
            self.assertFalse((psx_dir / "rpg_game.m3a").exists())

            # Add disc 2 -> should auto-create rpg_game.m3a
            w2 = psx_dir / "rpg_game-disc_2.chd"
            w2.write_bytes(b"W2")
            time.sleep(0.25)
            m3a_file = psx_dir / "rpg_game.m3a"
            self.assertTrue(m3a_file.exists())

            # Add disc 3 -> should auto-append disc 3
            w3 = psx_dir / "rpg_game-disc_3.chd"
            w3.write_bytes(b"W3")
            time.sleep(0.25)
            lines = [l.strip() for l in m3a_file.read_text(encoding="utf-8").splitlines() if l.strip()]
            self.assertEqual(lines, ["rpg_game-disc_1.chd", "rpg_game-disc_2.chd", "rpg_game-disc_3.chd"])

            # Delete disc 2 -> should remove disc 2
            w2.unlink()
            time.sleep(0.25)
            lines = [l.strip() for l in m3a_file.read_text(encoding="utf-8").splitlines() if l.strip()]
            self.assertEqual(lines, ["rpg_game-disc_1.chd", "rpg_game-disc_3.chd"])

            self.assertGreater(len(events), 0)
        finally:
            watcher.stop()

    def test_parse_rom_region_and_language(self):
        from r36sync.database import parse_rom_region_and_language
        r, l = parse_rom_region_and_language("007 - Blood Stone (USA).zip")
        self.assertEqual(r, "USA")
        self.assertEqual(l, "En")

        r, l = parse_rom_region_and_language("007 - Everything or Nothing (USA, Europe) (En,Fr,De).zip")
        self.assertEqual(r, "USA, Europe")
        self.assertEqual(l, "En, Fr, De")

        r, l = parse_rom_region_and_language("Chrono Trigger (Japan).zip")
        self.assertEqual(r, "Japan")
        self.assertEqual(l, "Ja")

    def test_downloader_unzip_and_delete_archive(self):
        import zipfile
        from r36sync.downloader import downloader, DownloadTask

        gba_dir = self.library_dir / "gba"
        gba_dir.mkdir(parents=True, exist_ok=True)
        zip_path = gba_dir / "test_game.zip"

        # Create a test zip file
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("test_game.gba", b"TEST_GBA_BINARY")

        task = DownloadTask({"console_code": "gba", "file_name": "test_game.zip"})
        task.dest_path = zip_path

        extracted = downloader._unzip_archive_if_needed(task)
        self.assertEqual(len(extracted), 1)
        self.assertEqual(extracted[0].name, "test_game.gba")
        self.assertTrue((gba_dir / "test_game.gba").exists())
        self.assertFalse(zip_path.exists())

    def test_preexisting_sd_games_in_library(self):
        from r36sync.sync_manager import sync_manager

        # Create pre-existing games on SD card only (not in PC library)
        sd_gba = self.sd_root / "gba"
        sd_gba.mkdir(parents=True, exist_ok=True)
        (sd_gba / "Golden Sun.gba").write_bytes(b"GOLDEN_SUN")

        sd_psx = self.sd_root / "psx"
        sd_psx.mkdir(parents=True, exist_ok=True)
        (sd_psx / "Tekken 3.chd").write_bytes(b"TEKKEN_3")

        # Scan library: should discover both pre-existing SD games!
        games = sync_manager.scan_library(str(self.library_dir), self.sd_root)
        sd_only_games = [g for g in games if not g.is_on_pc]
        self.assertEqual(len(sd_only_games), 2)

        titles = [g.stem for g in sd_only_games]
        self.assertIn("Golden Sun", titles)
        self.assertIn("Tekken 3", titles)

        # Verify they are marked on handheld and checked
        for g in sd_only_games:
            self.assertTrue(g.is_on_handheld)
            self.assertTrue(g.is_checked)
            self.assertFalse(g.is_on_pc)

        # Test Import to PC
        gs = next(g for g in sd_only_games if g.stem == "Golden Sun")
        success = sync_manager.import_sd_game_to_pc(gs, str(self.library_dir))
        self.assertTrue(success)
        self.assertTrue((self.library_dir / "gba" / "Golden Sun.gba").exists())
        self.assertTrue(gs.is_on_pc)

    def test_parse_rom_disc_number(self):
        from r36sync.database import parse_rom_disc_number

        self.assertEqual(parse_rom_disc_number("Thousand Arms (USA) (Disc 1).zip"), "1")
        self.assertEqual(parse_rom_disc_number("Thousand Arms (USA) (Disc 2).zip"), "2")
        self.assertEqual(parse_rom_disc_number("Final Fantasy VIII (USA) (Disc 4).bin"), "4")
        self.assertEqual(parse_rom_disc_number("Lunar 2 - Eternal Blue (USA) (Disc A).iso"), "A")
        self.assertEqual(parse_rom_disc_number("Chrono Cross (USA) (Disc 1 of 2).chd"), "1")
        self.assertEqual(parse_rom_disc_number("game_1-disc_3.zip"), "3")
        self.assertIsNone(parse_rom_disc_number("Super Mario 64 (USA).z64"))
        self.assertIsNone(parse_rom_disc_number("Pokemon Emerald (USA, Europe).gba"))

    def test_library_filtering_and_sorting_logic(self):
        from r36sync.sync_manager import LibraryGame

        # Create sample game objects
        g_zelda = LibraryGame(
            file_path=Path("gba/Zelda.gba"),
            file_name="Zelda.gba",
            stem="Zelda",
            console_code="gba",
            console_name="Game Boy Advance",
            size_bytes=10 * 1024 * 1024,
            has_cover_art=False,
            cover_art_path=None,
            is_on_handheld=True,
            is_checked=True,
            is_on_pc=True,
            is_playlist=False,
            disc_count=1
        )
        g_mario = LibraryGame(
            file_path=Path("snes/Mario.sfc"),
            file_name="Mario.sfc",
            stem="Mario",
            console_code="snes",
            console_name="Super Nintendo",
            size_bytes=50 * 1024 * 1024,
            has_cover_art=False,
            cover_art_path=None,
            is_on_handheld=True,
            is_checked=False,
            is_on_pc=True,
            is_playlist=False,
            disc_count=1
        )
        g_arms = LibraryGame(
            file_path=Path("psx/Thousand Arms.m3u"),
            file_name="Thousand Arms.m3u",
            stem="Thousand Arms",
            console_code="psx",
            console_name="Sony PlayStation",
            size_bytes=500 * 1024 * 1024,
            has_cover_art=False,
            cover_art_path=None,
            is_on_handheld=False,
            is_checked=True,
            is_on_pc=True,
            is_playlist=True,
            disc_count=2
        )
        g_tetris = LibraryGame(
            file_path=Path("gb/Tetris.gb"),
            file_name="Tetris.gb",
            stem="Tetris",
            console_code="gb",
            console_name="Game Boy",
            size_bytes=5 * 1024 * 1024,
            has_cover_art=False,
            cover_art_path=None,
            is_on_handheld=True,
            is_checked=False,
            is_on_pc=False,
            is_playlist=False,
            disc_count=1
        )

        all_games = [g_zelda, g_mario, g_arms, g_tetris]

        def filter_games(games, check_sel="All Checks", sync_sel="All Sync", type_sel="All Types", sort_sel="Sort: Title (A-Z)"):
            res = []
            for g in games:
                if check_sel == "Checked" and not g.is_checked:
                    continue
                elif check_sel == "Unchecked" and g.is_checked:
                    continue

                if sync_sel == "Synced" and not (g.is_on_handheld and g.is_on_pc):
                    continue
                elif sync_sel == "Not Synced" and (g.is_on_handheld and g.is_on_pc):
                    continue

                if type_sel == "Library Only" and (not g.is_on_pc or g.is_on_handheld):
                    continue
                elif type_sel == "SD Card Only" and (not g.is_on_handheld or g.is_on_pc):
                    continue
                elif type_sel == "Multi-Disc Only" and not (g.is_playlist or g.disc_count > 1):
                    continue
                elif type_sel == "Single Disc Only" and (g.is_playlist or g.disc_count > 1):
                    continue
                res.append(g)

            if sort_sel == "Sort: Title (A-Z)":
                res.sort(key=lambda g: g.stem.lower())
            elif sort_sel == "Sort: Title (Z-A)":
                res.sort(key=lambda g: g.stem.lower(), reverse=True)
            elif sort_sel == "Sort: Size (Largest)":
                res.sort(key=lambda g: g.size_bytes, reverse=True)
            elif sort_sel == "Sort: Size (Smallest)":
                res.sort(key=lambda g: g.size_bytes)
            elif sort_sel == "Sort: Platform (A-Z)":
                res.sort(key=lambda g: (g.console_name, g.stem.lower()))
            return res

        # 1. Check combinations
        self.assertEqual([g.stem for g in filter_games(all_games, check_sel="Checked")], ["Thousand Arms", "Zelda"])
        self.assertEqual([g.stem for g in filter_games(all_games, check_sel="Unchecked")], ["Mario", "Tetris"])

        # 2. Sync combinations
        self.assertEqual([g.stem for g in filter_games(all_games, sync_sel="Synced")], ["Mario", "Zelda"])
        self.assertEqual([g.stem for g in filter_games(all_games, sync_sel="Not Synced")], ["Tetris", "Thousand Arms"])

        # 3. Combo: Checked + Synced
        self.assertEqual([g.stem for g in filter_games(all_games, check_sel="Checked", sync_sel="Synced")], ["Zelda"])

        # 4. Combo: Checked + Not Synced
        self.assertEqual([g.stem for g in filter_games(all_games, check_sel="Checked", sync_sel="Not Synced")], ["Thousand Arms"])

        # 5. Combo: Unchecked + Synced
        self.assertEqual([g.stem for g in filter_games(all_games, check_sel="Unchecked", sync_sel="Synced")], ["Mario"])

        # 6. Combo: Unchecked + Not Synced
        self.assertEqual([g.stem for g in filter_games(all_games, check_sel="Unchecked", sync_sel="Not Synced")], ["Tetris"])

        # 7. Types
        self.assertEqual([g.stem for g in filter_games(all_games, type_sel="Library Only")], ["Thousand Arms"])
        self.assertEqual([g.stem for g in filter_games(all_games, type_sel="SD Card Only")], ["Tetris"])
        self.assertEqual([g.stem for g in filter_games(all_games, type_sel="Multi-Disc Only")], ["Thousand Arms"])
        self.assertEqual([g.stem for g in filter_games(all_games, type_sel="Single Disc Only")], ["Mario", "Tetris", "Zelda"])

        # 8. Sorting
        self.assertEqual([g.stem for g in filter_games(all_games, sort_sel="Sort: Title (A-Z)")], ["Mario", "Tetris", "Thousand Arms", "Zelda"])
        self.assertEqual([g.stem for g in filter_games(all_games, sort_sel="Sort: Title (Z-A)")], ["Zelda", "Thousand Arms", "Tetris", "Mario"])
        self.assertEqual([g.stem for g in filter_games(all_games, sort_sel="Sort: Size (Largest)")], ["Thousand Arms", "Mario", "Zelda", "Tetris"])
        self.assertEqual([g.stem for g in filter_games(all_games, sort_sel="Sort: Size (Smallest)")], ["Tetris", "Zelda", "Mario", "Thousand Arms"])
        self.assertEqual([g.stem for g in filter_games(all_games, sort_sel="Sort: Platform (A-Z)")], ["Tetris", "Zelda", "Thousand Arms", "Mario"])

    def test_browse_search_filter_queries(self):
        # Insert test roms with disc numbers across consoles
        test_roms = [
            {
                "minerva_id": "psx_ta1",
                "title": "Thousand Arms (USA) (Disc 1)",
                "clean_title": "Thousand Arms",
                "file_name": "Thousand Arms (USA) (Disc 1).zip",
                "console_code": "psx",
                "console_name": "Sony PlayStation",
                "group_name": "Redump",
                "size_str": "500 MB",
                "torrent_url": "https://minerva-archive.org/psx/1.torrent",
                "magnet_url": "magnet:?xt=1",
                "rom_url": "https://minerva-archive.org/psx/1",
                "torrent_file_idx": 0
            },
            {
                "minerva_id": "psx_ta2",
                "title": "Thousand Arms (USA) (Disc 2)",
                "clean_title": "Thousand Arms",
                "file_name": "Thousand Arms (USA) (Disc 2).zip",
                "console_code": "psx",
                "console_name": "Sony PlayStation",
                "group_name": "Redump",
                "size_str": "500 MB",
                "torrent_url": "https://minerva-archive.org/psx/2.torrent",
                "magnet_url": "magnet:?xt=2",
                "rom_url": "https://minerva-archive.org/psx/2",
                "torrent_file_idx": 1
            },
            {
                "minerva_id": "gba_mario",
                "title": "Super Mario Advance",
                "clean_title": "Super Mario Advance",
                "file_name": "Super Mario Advance.zip",
                "console_code": "gba",
                "console_name": "Game Boy Advance",
                "group_name": "No-Intro",
                "size_str": "8 MB",
                "torrent_url": "https://minerva-archive.org/gba/mario.torrent",
                "magnet_url": "magnet:?xt=3",
                "rom_url": "https://minerva-archive.org/gba/mario",
                "torrent_file_idx": 0
            },
            {
                "minerva_id": "snes_world",
                "title": "Super Mario World",
                "clean_title": "Super Mario World",
                "file_name": "Super Mario World.zip",
                "console_code": "snes",
                "console_name": "Super Nintendo",
                "group_name": "No-Intro",
                "size_str": "2 MB",
                "torrent_url": "https://minerva-archive.org/snes/world.torrent",
                "magnet_url": "magnet:?xt=4",
                "rom_url": "https://minerva-archive.org/snes/world",
                "torrent_file_idx": 0
            }
        ]
        self.db.upsert_roms(test_roms)

        from r36sync.database import parse_rom_disc_number

        # Search across all consoles for "Thousand Arms"
        results = self.db.search_roms("Thousand Arms", console_code=None)
        self.assertEqual(len(results), 2)
        disc_nums = [parse_rom_disc_number(r["file_name"]) for r in results]
        self.assertEqual(disc_nums, ["1", "2"])

        # Search with console filter: Mario across all vs Mario in SNES
        all_mario = self.db.search_roms("Mario", console_code=None)
        self.assertEqual(len(all_mario), 2)

        snes_mario = self.db.search_roms("Mario", console_code="snes")
        self.assertEqual(len(snes_mario), 1)
        self.assertEqual(snes_mario[0]["file_name"], "Super Mario World.zip")


if __name__ == "__main__":
    unittest.main()




