import hashlib
import json
from datetime import datetime
from pathlib import Path

from src.core.config_manager import get_sound_database_file
from src.core.logger import get_logger

logger = get_logger(__name__)


class SoundDatabase:

    def __init__(self, db_path=None):

        if db_path is None:
            self.db_path = get_sound_database_file()
        else:
            self.db_path = db_path

        self.database = {}
        self._loaded = False
        self._by_file_id = None

    def ensure_loaded(self):
        # Deferred to first access — the JSON read isn't needed at app boot.
        if self._loaded:
            return
        self.load()
        self._loaded = True

    def calculate_hash(self, file_bytes):

        return hashlib.sha256(file_bytes).hexdigest()

    def add_sound(self, file_bytes, name, tags=None, notes="", file_id=None):
        self.ensure_loaded()
        sound_hash = self.calculate_hash(file_bytes)
        now = datetime.now().isoformat()

        if sound_hash in self.database:
            entry = self.database[sound_hash]
            entry['name'] = name
            entry['tags'] = tags or []
            entry['notes'] = notes
            entry['date_modified'] = now

            if file_id is not None and file_id not in entry['file_ids']:
                entry['file_ids'].append(file_id)
        else:

            self.database[sound_hash] = {
                'name': name,
                'tags': tags or [],
                'notes': notes,
                'file_ids': [file_id] if file_id is not None else [],
                'date_added': now,
                'date_modified': now
            }

        self.save()
        return sound_hash

    def get_sound_info(self, file_bytes):
        self.ensure_loaded()
        sound_hash = self.calculate_hash(file_bytes)
        return self.database.get(sound_hash)

    def search_by_name(self, query):
        self.ensure_loaded()
        query_lower = query.lower()
        results = {}

        for sound_hash, info in self.database.items():
            name = str(info.get('name', ''))
            if query_lower in name.lower():
                results[sound_hash] = info

        return results

    def search_by_tag(self, tag):
        self.ensure_loaded()
        tag_lower = tag.lower()
        results = {}

        for sound_hash, info in self.database.items():
            tags = info.get('tags', []) or []
            if any(tag_lower in str(t).lower() for t in tags):
                results[sound_hash] = info

        return results

    @staticmethod
    def _file_id_key(value):
        # Ids arrive as int from the pck index and as str from JSON, so both collapse to one key.
        return str(value).strip()

    def _file_id_index(self):
        # Scanning every entry per lookup made the browser O(entries x wems) when expanding a pck.
        if self._by_file_id is None:
            index = {}
            for sound_hash, info in self.database.items():
                for file_id in (info.get('file_ids') or []):
                    index.setdefault(self._file_id_key(file_id), {})[sound_hash] = info
            self._by_file_id = index
        return self._by_file_id

    def search_by_id(self, file_id):
        self.ensure_loaded()
        results = dict(self._file_id_index().get(self._file_id_key(file_id), {}))

        return results

    def delete_sound(self, sound_hash):
        self.ensure_loaded()
        if sound_hash in self.database:
            del self.database[sound_hash]
            self.save()
            return True
        return False

    def load(self):

        self._by_file_id = None
        try:
            if self.db_path.exists():
                with open(self.db_path, 'r', encoding='utf-8') as f:
                    self.database = json.load(f)
        except Exception as e:
            logger.error(f"Warning: Failed to load sound database: {e}")
            self.database = {}

    def save(self):

        self._by_file_id = None
        try:
            with open(self.db_path, 'w', encoding='utf-8') as f:
                json.dump(self.database, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Warning: Failed to save sound database: {e}")

    def export_to_file(self, export_path):
        self.ensure_loaded()
        export_path = Path(export_path)
        with open(export_path, 'w', encoding='utf-8') as f:
            json.dump(self.database, f, indent=2, ensure_ascii=False)

    def import_from_file(self, import_path, merge=True):
        self.ensure_loaded()
        import_path = Path(import_path)

        with open(import_path, 'r', encoding='utf-8') as f:
            imported_data = json.load(f)

        if merge:

            count = 0
            for sound_hash, info in imported_data.items():
                if sound_hash not in self.database:
                    count += 1
                self.database[sound_hash] = info
        else:

            count = len(imported_data)
            self.database = imported_data

        self.save()
        return count

    def get_stats(self):
        self.ensure_loaded()
        total_sounds = len(self.database)
        tagged_sounds = sum(1 for info in self.database.values() if info['tags'])
        total_tags = set()
        for info in self.database.values():
            total_tags.update(info['tags'])

        return {
            'total_sounds': total_sounds,
            'tagged_sounds': tagged_sounds,
            'total_unique_tags': len(total_tags),
            'all_tags': sorted(list(total_tags))
        }

    def get_all_tags(self):
        self.ensure_loaded()
        all_tags = set()
        for info in self.database.values():
            all_tags.update(info['tags'])
        return sorted(list(all_tags))
