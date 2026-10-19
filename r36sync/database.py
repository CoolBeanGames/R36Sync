"""
Database module for R36Sync.
Manages the local SQLite database storing Minerva Archive catalog and save backups.
"""
import sqlite3
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any
from .config import DB_FILE


def clean_game_title(raw_name: str) -> str:
    """Cleans up a ROM filename into a readable display title."""
    import html as html_module
    raw_name = html_module.unescape(raw_name)
    name = Path(raw_name).stem
    # Remove tags like (USA), [p], (Rev 1), etc. for clean searching
    cleaned = re.sub(r'[\(\[].*?[\)\]]', '', name)
    cleaned = re.sub(r'[\s_]+', ' ', cleaned).strip()
    return cleaned if cleaned else name


REGIONS_SET = {
    'USA', 'Europe', 'Japan', 'World', 'Asia', 'China', 'Korea', 'Australia',
    'Brazil', 'Canada', 'France', 'Germany', 'Spain', 'Italy', 'United Kingdom',
    'UK', 'Netherlands', 'Sweden', 'Russia', 'Denmark', 'Norway', 'Finland',
    'Poland', 'Taiwan', 'Hong Kong', 'Latin America', 'Scandinavia'
}

LANGUAGES_MAP = {
    'En': 'English', 'Fr': 'French', 'De': 'German', 'Es': 'Spanish',
    'It': 'Italian', 'Nl': 'Dutch', 'Pt': 'Portuguese', 'Sv': 'Swedish',
    'No': 'Norwegian', 'Da': 'Danish', 'Fi': 'Finnish', 'Ja': 'Japanese',
    'Ko': 'Korean', 'Zh': 'Chinese', 'Ru': 'Russian', 'Pl': 'Polish'
}


def parse_rom_region_and_language(filename: str) -> Tuple[str, str]:
    """
    Extracts (region, language) from a ROM filename.
    Handles standard No-Intro / Redump parenthesis tags:
      - '007 - Blood Stone (USA).zip' -> ('USA', 'En')
      - '007 - Everything or Nothing (USA, Europe) (En,Fr,De).zip' -> ('USA, Europe', 'En, Fr, De')
      - 'Chrono Trigger (Japan).zip' -> ('Japan', 'Ja')
    """
    stem = Path(filename).stem
    tags = re.findall(r'\((.*?)\)', stem)

    found_region = None
    found_langs = []

    for tag in tags:
        parts = [p.strip() for p in tag.split(',')]
        if any(p in REGIONS_SET for p in parts):
            if not found_region:
                found_region = tag
        if any(p in LANGUAGES_MAP for p in parts):
            found_langs.extend([p for p in parts if p in LANGUAGES_MAP])

    if not found_region:
        found_region = 'Global'

    if not found_langs:
        r_lower = found_region.lower()
        if 'japan' in r_lower:
            found_langs = ['Ja']
        elif 'france' in r_lower:
            found_langs = ['Fr']
        elif 'germany' in r_lower:
            found_langs = ['De']
        elif 'spain' in r_lower:
            found_langs = ['Es']
        elif 'italy' in r_lower:
            found_langs = ['It']
        elif 'china' in r_lower:
            found_langs = ['Zh']
        elif 'korea' in r_lower:
            found_langs = ['Ko']
        else:
            found_langs = ['En']

    return found_region, ', '.join(found_langs)


def parse_rom_disc_number(filename: str) -> Optional[str]:
    """
    Extracts the disc/disk/CD number or label from a ROM filename.
    Handles:
      - 'Thousand Arms (USA) (Disc 1).zip' -> '1'
      - 'Final Fantasy VII (USA) (Disc 3).bin' -> '3'
      - 'Lunar 2 (USA) (Disc A).iso' -> 'A'
      - 'Chrono Cross (USA) (Disc 1 of 2).chd' -> '1'
      - 'game_1-disc_2.chd' -> '2'
      - 'Super Mario 64.zip' -> None
    """
    stem = Path(filename).stem
    m = re.search(r'[\(\[]\s*(?:Disc|CD|Disk|Part)[\s_\-]*(\d{1,3}|[a-zA-Z]\b|IV|IX|V?I{1,3})(?:\s*of\s*[0-9]+)?[\)\]]', stem, re.IGNORECASE)
    if m:
        return m.group(1)
    m2 = re.search(r'(?:[\s_\-\.\(\[])(?:Disc|CD|Disk|Part)[\s_\-]*(\d{1,3}|[a-zA-Z]\b|IV|IX|V?I{1,3})(?:\s*of\s*[0-9]+)?(?:[\s_\-\.\)\]]|$)', stem, re.IGNORECASE)
    if m2:
        return m2.group(1)
    return None


class Database:
    """Encapsulates SQLite database operations for ROMs and save backups."""

    def __init__(self, db_path: Path = DB_FILE):
        self.db_path = db_path
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        """Initializes tables and indexes."""
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute("""
            CREATE TABLE IF NOT EXISTS roms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                minerva_id TEXT,
                title TEXT,
                clean_title TEXT,
                file_name TEXT,
                console_code TEXT,
                console_name TEXT,
                group_name TEXT,
                size_str TEXT,
                torrent_url TEXT,
                magnet_url TEXT,
                rom_url TEXT,
                torrent_file_idx INTEGER DEFAULT 0,
                scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(file_name, console_code)
            );
            """)

            c.execute("""
            CREATE TABLE IF NOT EXISTS save_backups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                backup_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                game_title TEXT,
                console_code TEXT,
                save_type TEXT,
                file_name TEXT,
                source_path TEXT,
                backup_path TEXT,
                file_size INTEGER
            );
            """)

            c.execute("CREATE INDEX IF NOT EXISTS idx_roms_search ON roms(clean_title, console_code);")
            c.execute("CREATE INDEX IF NOT EXISTS idx_roms_filename ON roms(file_name);")
            c.execute("CREATE INDEX IF NOT EXISTS idx_roms_console ON roms(console_code);")
            c.execute("CREATE INDEX IF NOT EXISTS idx_roms_console_title ON roms(console_code, clean_title);")
            c.execute("CREATE INDEX IF NOT EXISTS idx_saves_console ON save_backups(console_code);")
            conn.commit()

    def upsert_roms(self, rom_list: List[Dict[str, Any]]) -> int:
        """Batch inserts or replaces rom entries."""
        if not rom_list:
            return 0
        with self.get_connection() as conn:
            c = conn.cursor()
            tuples = []
            for r in rom_list:
                file_name = r.get("file_name", "")
                title = r.get("title", file_name)
                clean_title = r.get("clean_title") or clean_game_title(title)
                tuples.append((
                    r.get("minerva_id", ""),
                    title,
                    clean_title,
                    file_name,
                    r.get("console_code", ""),
                    r.get("console_name", ""),
                    r.get("group_name", ""),
                    r.get("size_str", ""),
                    r.get("torrent_url", ""),
                    r.get("magnet_url", ""),
                    r.get("rom_url", ""),
                    r.get("torrent_file_idx", 0)
                ))
            c.executemany("""
            INSERT INTO roms (
                minerva_id, title, clean_title, file_name, console_code,
                console_name, group_name, size_str, torrent_url, magnet_url,
                rom_url, torrent_file_idx
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(file_name, console_code) DO UPDATE SET
                minerva_id = excluded.minerva_id,
                title = excluded.title,
                clean_title = excluded.clean_title,
                size_str = excluded.size_str,
                torrent_url = excluded.torrent_url,
                magnet_url = excluded.magnet_url,
                rom_url = excluded.rom_url,
                torrent_file_idx = excluded.torrent_file_idx,
                scanned_at = CURRENT_TIMESTAMP;
            """, tuples)
            conn.commit()
            return len(tuples)

    def search_roms(
        self,
        query: str = "",
        console_code: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Searches the stored database without making network requests.
        Fast instant filtering by title, filename, and console.
        """
        with self.get_connection() as conn:
            c = conn.cursor()
            conditions = []
            params = []

            if query:
                # Split query into words to match each word
                words = query.strip().split()
                for word in words:
                    conditions.append("(clean_title LIKE ? OR file_name LIKE ?)")
                    params.extend([f"%{word}%", f"%{word}%"])

            if console_code and console_code.lower() != "all":
                conditions.append("console_code = ?")
                params.append(console_code.lower())

            where_clause = ""
            if conditions:
                where_clause = "WHERE " + " AND ".join(conditions)

            sql = f"""
            SELECT * FROM roms
            {where_clause}
            ORDER BY clean_title ASC
            LIMIT ? OFFSET ?
            """
            params.extend([limit, offset])

            c.execute(sql, params)
            rows = c.fetchall()
            return [dict(row) for row in rows]

    def count_search_results(self, query: str = "", console_code: Optional[str] = None) -> int:
        """Counts matching search results for pagination."""
        with self.get_connection() as conn:
            c = conn.cursor()
            conditions = []
            params = []

            if query:
                words = query.strip().split()
                for word in words:
                    conditions.append("(clean_title LIKE ? OR file_name LIKE ?)")
                    params.extend([f"%{word}%", f"%{word}%"])

            if console_code and console_code.lower() != "all":
                conditions.append("console_code = ?")
                params.append(console_code.lower())

            where_clause = ""
            if conditions:
                where_clause = "WHERE " + " AND ".join(conditions)

            sql = f"SELECT COUNT(*) FROM roms {where_clause}"
            c.execute(sql, params)
            return c.fetchone()[0]

    def get_total_rom_count(self) -> int:
        """Returns total games indexed in database."""
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM roms")
            return c.fetchone()[0]

    def get_consoles_summary(self) -> List[Dict[str, Any]]:
        """Returns list of consoles with count of cached games."""
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute("""
            SELECT console_code, console_name, COUNT(*) as count
            FROM roms
            GROUP BY console_code, console_name
            ORDER BY count DESC
            """)
            return [dict(row) for row in c.fetchall()]

    def get_console_letters(self, console_code: str) -> List[str]:
        """Returns list of starting letters/digits available for a console."""
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute("""
            SELECT DISTINCT UPPER(SUBSTR(clean_title, 1, 1)) as letter
            FROM roms
            WHERE console_code = ?
            ORDER BY letter ASC
            """, (console_code,))
            letters = [r[0] for r in c.fetchall() if r[0]]
            return letters

    def get_games_by_console(
        self,
        console_code: str,
        letter: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Queries games for a specific console with optional letter and search filters."""
        with self.get_connection() as conn:
            c = conn.cursor()
            conditions = ["console_code = ?"]
            params: List[Any] = [console_code]

            if letter and letter != "ALL":
                if letter == "#":
                    conditions.append("(SUBSTR(clean_title, 1, 1) GLOB '[0-9]*' OR SUBSTR(clean_title, 1, 1) NOT GLOB '[A-Za-z]*')")
                else:
                    conditions.append("clean_title LIKE ?")
                    params.append(f"{letter}%")

            if search:
                words = search.strip().split()
                for word in words:
                    conditions.append("(clean_title LIKE ? OR file_name LIKE ?)")
                    params.extend([f"%{word}%", f"%{word}%"])

            where_clause = "WHERE " + " AND ".join(conditions)
            sql = f"""
            SELECT * FROM roms
            {where_clause}
            ORDER BY clean_title ASC
            LIMIT ? OFFSET ?
            """
            params.extend([limit, offset])
            c.execute(sql, params)
            return [dict(row) for row in c.fetchall()]

    def count_games_by_console(
        self,
        console_code: str,
        letter: Optional[str] = None,
        search: Optional[str] = None
    ) -> int:
        """Counts games matching browse criteria for a console."""
        with self.get_connection() as conn:
            c = conn.cursor()
            conditions = ["console_code = ?"]
            params: List[Any] = [console_code]

            if letter and letter != "ALL":
                if letter == "#":
                    conditions.append("(SUBSTR(clean_title, 1, 1) GLOB '[0-9]*' OR SUBSTR(clean_title, 1, 1) NOT GLOB '[A-Za-z]*')")
                else:
                    conditions.append("clean_title LIKE ?")
                    params.append(f"{letter}%")

            if search:
                words = search.strip().split()
                for word in words:
                    conditions.append("(clean_title LIKE ? OR file_name LIKE ?)")
                    params.extend([f"%{word}%", f"%{word}%"])

            where_clause = "WHERE " + " AND ".join(conditions)
            sql = f"SELECT COUNT(*) FROM roms {where_clause}"
            c.execute(sql, params)
            return c.fetchone()[0]

    def record_save_backup(
        self,
        game_title: str,
        console_code: str,
        save_type: str,
        file_name: str,
        source_path: str,
        backup_path: str,
        file_size: int
    ) -> int:
        """Records a completed save backup in the database."""
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute("""
            INSERT INTO save_backups (
                game_title, console_code, save_type, file_name,
                source_path, backup_path, file_size
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                game_title, console_code, save_type, file_name,
                source_path, backup_path, file_size
            ))
            conn.commit()
            return c.lastrowid

    def get_save_backups(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Retrieves recent save backups."""
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute("""
            SELECT * FROM save_backups
            ORDER BY backup_time DESC
            LIMIT ?
            """, (limit,))
            return [dict(row) for row in c.fetchall()]

    def get_total_saves_count(self) -> int:
        """Returns total number of backed up saves."""
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM save_backups")
            return c.fetchone()[0]


# Global database instance
db = Database()
