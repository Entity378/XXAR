

import tempfile
import shutil
import zipfile
import json
from pathlib import Path
from datetime import datetime
from PyQt5.QtCore import QObject, QThread, pyqtSignal
import src.core.app_config as app_config
from src.core.game_registry import DEFAULT_GAME_ID, detect_game_id_from_path, get_game

class ImportWorker(QThread):


    progress = pyqtSignal(str)
    progressPercent = pyqtSignal(int)
    finished = pyqtSignal(bool, str)

    def __init__(self, data, game_audio_dir, mod_package_manager):
        super().__init__()
        self.data = data
        self.game_audio_dir = game_audio_dir
        self.mod_package_manager = mod_package_manager
        self.game_id = detect_game_id_from_path(game_audio_dir, default=DEFAULT_GAME_ID)
        self.game = get_game(self.game_id)

    def _get_pck_priority(self, pck_name):
        name = str(pck_name or "")
        if name.startswith(self.game.soundbank_pck_prefix):
            return 1
        if name.startswith(self.game.streamed_pck_prefix):
            return 0
        return 0

    def _priority_label(self, priority):
        if priority == 1:
            return self.game.soundbank_pck_prefix or "Primary"
        return self.game.streamed_pck_prefix or "Streamed"

    def _priority_suffix(self, priority):
        return f" ({self._priority_label(priority)})"

    def _is_language_specific_candidate(self, relative_pck):
        rel = Path(relative_pck)
        if len(rel.parts) <= 1:
            return False
        top_dir = rel.parts[0]
        non_language_tabs = set(self.game.non_language_tabs or ())
        return top_dir not in non_language_tabs

    def run(self):

        try:
            result = self._convert_mod()
            self.finished.emit(True, result)
        except Exception as e:
            self.finished.emit(False, str(e))

    def _convert_mod(self):

        from src.wwise.pck_indexer import PCKIndexer
        from src.wwise.bnk_indexer import BNKIndexer
        from PIL import Image

        temp_dir = None

        try:

            from XXAR import get_temp_dir
            temp_dir = Path(tempfile.mkdtemp(prefix='mod_import_', dir=str(get_temp_dir())))

            wem_dir = temp_dir / 'wem_files'
            wem_dir.mkdir(parents=True, exist_ok=True)

            replacements = {}
            import_mode = self.data['import_mode']

            if import_mode in ['pck_file', 'pck_folder']:
                files = self.data['files']
                self.progress.emit("Extracting audio from PCK files...")
                self.progressPercent.emit(5)

                extracted_wem_ids = {}
                total_pcks_to_extract = len(files)
                for pck_idx, (pck_name, pck_info) in enumerate(files.items()):
                    pck_path = pck_info['path']

                    indexer = PCKIndexer(str(pck_path))
                    indexer.extract_all(str(temp_dir / 'extracted'), extract_bnk=True)

                    extracted_path = temp_dir / 'extracted'

                    wem_files = list(extracted_path.rglob('*.wem'))

                    bnk_files = list(extracted_path.rglob('*.bnk'))
                    for bnk_file in bnk_files:
                        try:
                            bnk_bytes = bnk_file.read_bytes()
                            bnk_indexer = BNKIndexer(bnk_bytes)
                            bnk_indexer.parse_didx()

                            for wem in bnk_indexer.wem_list:
                                wem_id = str(wem['wem_id'])
                                wem_data = bnk_indexer.extract_wem(wem['wem_id'])
                                if wem_data:
                                    embedded_wem = extracted_path / 'bnk_embedded' / f"{wem_id}.wem"
                                    embedded_wem.parent.mkdir(parents=True, exist_ok=True)
                                    embedded_wem.write_bytes(wem_data)
                                    wem_files.append(embedded_wem)
                        except Exception as e:
                            self.progress.emit(f"Warning: Could not parse BNK {bnk_file.name}: {e}")

                    self.progress.emit(f"Found {len(wem_files)} audio files in {pck_name}")
                    pck_progress = int(5 + ((pck_idx + 1) / max(total_pcks_to_extract, 1)) * 25)
                    self.progressPercent.emit(pck_progress)

                    for wem_file in wem_files:
                        file_id = wem_file.stem
                        dest_wem = wem_dir / f"{file_id}.wem"
                        shutil.copy2(wem_file, dest_wem)
                        extracted_wem_ids[file_id] = dest_wem

                extracted_path = temp_dir / 'extracted'
                if extracted_path.exists():
                    shutil.rmtree(extracted_path)

                game_audio_dir = Path(self.game_audio_dir)
                if not game_audio_dir.exists():
                    raise Exception("Game audio directory not set. Please set it in Settings first.")

                input_pck_names = set(f"{name}.pck" if not name.endswith('.pck') else name for name in files.keys())
                self.progress.emit(f"Scanning matching game PCKs ({', '.join(input_pck_names)}) to locate {len(extracted_wem_ids)} extracted WEM file(s)...")
                self.progressPercent.emit(30)

                target_wem_ids = set(extracted_wem_ids.keys())
                file_id_to_pck = {}
                skipped_bnks = 0
                skipped_wems = 0

                all_game_pcks = list(game_audio_dir.rglob('*.pck'))
                game_pck_files = [p for p in all_game_pcks if p.name in input_pck_names]
                total_game_pcks = len(game_pck_files)

                if total_game_pcks == 0:
                    self.progress.emit(f"Warning: No matching game PCKs found for {input_pck_names}. Searched {len(all_game_pcks)} game PCKs.")

                from XXAR import get_temp_dir
                with tempfile.TemporaryDirectory(prefix='mod_bnk_scan_', dir=str(get_temp_dir())) as _tbd:
                    temp_bnk_dir = Path(_tbd)

                    for idx, game_pck_path in enumerate(game_pck_files):
                        scan_progress = int(30 + ((idx + 1) / max(total_game_pcks, 1)) * 25)
                        self.progressPercent.emit(scan_progress)

                        if idx % 5 == 0:
                            self.progress.emit(f"Scanning {game_pck_path.name} ({idx+1}/{total_game_pcks})...")

                        try:
                            indexer = PCKIndexer(str(game_pck_path))
                            indexer.build_index()

                            try:
                                game_pck_name = str(game_pck_path.relative_to(game_audio_dir)).replace("\\", "/")
                            except ValueError:
                                game_pck_name = game_pck_path.name
                            priority = self._get_pck_priority(game_pck_path.name)

                            for bnk_info in indexer.index_data['banks']:
                                bnk_id = bnk_info['id']
                                try:
                                    bnk_bytes = indexer.extract_single_file(bnk_id, 'bnk', bnk_info['lang_id'])
                                    bnk_indexer = BNKIndexer(bnk_bytes)
                                    bnk_indexer.parse_didx()

                                    for wem in bnk_indexer.wem_list:
                                        file_id = str(wem['wem_id'])
                                        if file_id in target_wem_ids:
                                            original_wem = bnk_indexer.extract_wem(wem['wem_id'])
                                            modded_wem = extracted_wem_ids[file_id].read_bytes()
                                            if original_wem == modded_wem:
                                                continue
                                            lang_id = bnk_info['lang_id']
                                            if file_id not in file_id_to_pck or priority >= file_id_to_pck[file_id][3]:
                                                file_id_to_pck[file_id] = (game_pck_name, bnk_id, lang_id, priority)
                                except Exception:
                                    skipped_bnks += 1

                            for wem_info in indexer.index_data['sounds'] + indexer.index_data['externals']:
                                file_id = str(wem_info['id'])
                                lang_id = wem_info['lang_id']
                                if file_id in target_wem_ids:
                                    try:
                                        original_wem = indexer.extract_single_file(wem_info['id'], 'wem', lang_id)
                                        modded_wem = extracted_wem_ids[file_id].read_bytes()
                                        if original_wem == modded_wem:
                                            continue
                                    except Exception:
                                        skipped_wems += 1
                                    if file_id not in file_id_to_pck or priority >= file_id_to_pck[file_id][3]:
                                        file_id_to_pck[file_id] = (game_pck_name, None, lang_id, priority)

                        except Exception as e:
                            self.progress.emit(f"Warning: Could not scan {game_pck_path.name}: {e}")

                identical_count = len(extracted_wem_ids) - len(file_id_to_pck)
                self.progress.emit(f"Found {len(file_id_to_pck)} modified WEM file(s) ({identical_count} identical, skipped)")
                if skipped_bnks or skipped_wems:
                    self.progress.emit(
                        f"Warning: {skipped_bnks} BNK(s) and {skipped_wems} WEM(s) could not be parsed during scan "
                        f"and were skipped — some mod replacements may be missing their game-side target."
                    )
                self.progressPercent.emit(58)

                for file_id in list(extracted_wem_ids.keys()):
                    if file_id not in file_id_to_pck:
                        wem_path = wem_dir / f"{file_id}.wem"
                        wem_path.unlink(missing_ok=True)

                for file_id in file_id_to_pck:
                    game_pck_name, bnk_id, lang_id, priority = file_id_to_pck[file_id]

                    if bnk_id:
                        sub_dir = wem_dir / str(bnk_id)
                        wem_relative = f'wem_files/{bnk_id}/{file_id}.wem'
                        bnk_key = f"{bnk_id}.bnk"
                    else:
                        sub_dir = wem_dir / 'direct'
                        wem_relative = f'wem_files/direct/{file_id}.wem'
                        bnk_key = 'direct'

                    sub_dir.mkdir(parents=True, exist_ok=True)
                    src = wem_dir / f"{file_id}.wem"
                    if src.exists():
                        shutil.move(str(src), str(sub_dir / f"{file_id}.wem"))

                    if game_pck_name not in replacements:
                        replacements[game_pck_name] = {}
                    if bnk_key not in replacements[game_pck_name]:
                        replacements[game_pck_name][bnk_key] = {}

                    replacements[game_pck_name][bnk_key][file_id] = {
                        'wem_file': wem_relative,
                        'sound_name': '',
                        'lang_id': lang_id,
                        'file_type': 'bnk' if bnk_id else 'wem'
                    }

                for pck_name, pck_files_map in replacements.items():
                    file_count = sum(len(files) for files in pck_files_map.values())
                    self.progress.emit(f"  {pck_name}: {file_count} file(s)")

            elif import_mode in ['wem_file', 'wem_folder']:
                # Normalize 16-char hex IDs to decimal up front.
                files = {k if len(k) != 16 else str(int(k,16)): self.data['files'][k] for k in self.data['files']}

                self.progress.emit("Processing WEM files...")
                self.progressPercent.emit(5)

                game_audio_dir = Path(self.game_audio_dir)

                if not game_audio_dir.exists():
                    raise Exception("Game audio directory not set. Please set it in Settings first.")

                target_wem_ids = set(files.keys())
                target_id_to_key = {}
                for fid in files.keys():
                    try:
                        int_id = int(fid)
                        target_id_to_key[int_id] = fid
                    except (ValueError, TypeError):
                        pass
                self.progress.emit(f"Looking for {len(target_wem_ids)} WEM file(s) in game PCKs...")

                file_id_to_pck = {}

                pck_files = list(game_audio_dir.rglob('*.pck'))
                total_pcks = len(pck_files)

                from XXAR import get_temp_dir
                temp_bnk_dir = Path(tempfile.mkdtemp(prefix='mod_bnk_scan_', dir=str(get_temp_dir())))

                for idx, pck_path in enumerate(pck_files):
                    scan_progress = int(5 + ((idx + 1) / max(total_pcks, 1)) * 50)
                    self.progressPercent.emit(scan_progress)

                    if idx % 5 == 0:
                        self.progress.emit(f"Scanning {pck_path.name} ({idx+1}/{total_pcks})...")

                    try:

                        indexer = PCKIndexer(str(pck_path))
                        indexer.build_index()

                        try:
                            pck_name = str(pck_path.relative_to(game_audio_dir)).replace("\\", "/")
                        except ValueError:
                            pck_name = pck_path.name
                        priority = self._get_pck_priority(pck_path.name)

                        bnk_wems = 0
                        for bnk_info in indexer.index_data['banks']:
                            bnk_id = bnk_info['id']

                            try:
                                bnk_bytes = indexer.extract_single_file(bnk_id, 'bnk', bnk_info['lang_id'])
                                bnk_indexer = BNKIndexer(bnk_bytes)
                                bnk_indexer.parse_didx()

                                for wem in bnk_indexer.wem_list:
                                    wem_id = wem['wem_id']
                                    file_id = target_id_to_key.get(wem_id)

                                    if file_id is not None:
                                        lang_id = bnk_info['lang_id']

                                        if file_id not in file_id_to_pck or priority >= file_id_to_pck[file_id][3]:
                                            file_id_to_pck[file_id] = (pck_name, bnk_id, lang_id, priority)
                                        bnk_wems += 1
                            except Exception:
                                pass

                        standalone_wems = 0
                        for wem_info in indexer.index_data['sounds'] + indexer.index_data['externals']:
                            wem_id = wem_info['id']
                            file_id = target_id_to_key.get(wem_id)
                            lang_id = wem_info['lang_id']

                            if file_id is not None:

                                if file_id not in file_id_to_pck or priority >= file_id_to_pck[file_id][3]:
                                    file_id_to_pck[file_id] = (pck_name, None, lang_id, priority)
                                standalone_wems += 1

                        if standalone_wems > 0 or bnk_wems > 0:
                            priority_label = self._priority_label(priority)
                            self.progress.emit(f"  {pck_name} ({priority_label}): {standalone_wems} standalone + {bnk_wems} BNK-embedded")

                    except Exception as e:
                        self.progress.emit(f"Warning: Could not scan {pck_path.name}: {e}")

                if temp_bnk_dir.exists():
                    shutil.rmtree(temp_bnk_dir)

                self.progress.emit(f"Found {len(file_id_to_pck)} file IDs in {total_pcks} PCK files")
                self.progressPercent.emit(60)

                for file_id, wem_info in files.items():
                    wem_path = wem_info['path']

                    if file_id in file_id_to_pck:
                        pck_name, bnk_id, lang_id, priority = file_id_to_pck[file_id]
                        priority_str = self._priority_suffix(priority)
                        location_str = f" in BNK {bnk_id}" if bnk_id else ""
                        self.progress.emit(f"File {file_id} -> {pck_name}{priority_str}{location_str} (lang {lang_id})")
                    else:
                        all_game_pcks = [i.relative_to(game_audio_dir) for i in game_audio_dir.rglob('*.pck')]
                        candidates = [i for i in all_game_pcks if i.stem in str(wem_path)]
                        if len(candidates) > 1:
                            # Prefer language-folder candidates when multiple match.
                            language_candidates = [
                                i for i in candidates if self._is_language_specific_candidate(i)
                            ]
                            if language_candidates:
                                candidates = language_candidates
                        if len(candidates) == 1:
                            pck_name = str(candidates[0])
                        else:
                            pck_name = "Unknown.pck"
                        bnk_id = wem_path.split('_bnk')[0].split('/')[1] if '_bnk' in wem_path else None
                        lang_id = 0
                        self.progress.emit(f"Warning: File ID {file_id} not found in any game PCK")

                    if bnk_id:
                        sub_dir = wem_dir / str(bnk_id)
                        wem_relative = f'wem_files/{bnk_id}/{file_id}.wem'
                        bnk_key = f"{bnk_id}.bnk"
                    else:
                        sub_dir = wem_dir / 'direct'
                        wem_relative = f'wem_files/direct/{file_id}.wem'
                        bnk_key = 'direct'

                    sub_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(wem_path, sub_dir / f"{file_id}.wem")

                    if pck_name not in replacements:
                        replacements[pck_name] = {}
                    if bnk_key not in replacements[pck_name]:
                        replacements[pck_name][bnk_key] = {}

                    replacements[pck_name][bnk_key][file_id] = {
                        'wem_file': wem_relative,
                        'sound_name': '',
                        'lang_id': lang_id,
                        'file_type': 'bnk' if bnk_id else 'wem'
                    }

                self.progress.emit(f"Processed {len(files)} WEM files into {len(replacements)} PCK(s)")

                for pck_name, pck_files in replacements.items():
                    file_count = sum(len(files) for files in pck_files.values())
                    self.progress.emit(f"  {pck_name}: {file_count} file(s)")

            self.progress.emit(f"Creating {app_config.MOD_FILE_EXT} package...")
            self.progressPercent.emit(70)

            from XXAR import __version__ as app_version
            metadata_content = {
                'format_version': '3.0',
                'name': self.data['metadata']['name'],
                'author': self.data['metadata']['author'],
                'version': self.data['metadata'].get('version', '1.0.0'),
                'description': self.data['metadata'].get('description', ''),
                'created_date': datetime.now().isoformat(),
                'replacements': replacements,
                'app_version': app_version
            }

            if self.data.get('thumbnail'):
                try:
                    img = Image.open(self.data['thumbnail'])
                    thumbnail_path = temp_dir / 'thumbnail.png'
                    img.save(thumbnail_path, 'PNG')
                    metadata_content['thumbnail'] = 'thumbnail.png'
                except Exception as e:
                    self.progress.emit(f"Warning: Could not process thumbnail: {e}")

            with open(temp_dir / 'metadata.json', 'w') as f:
                json.dump(metadata_content, f, indent=2)

            save_path = Path(self.data['save_path'])
            with zipfile.ZipFile(save_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for file_path in temp_dir.rglob('*'):
                    if file_path.is_file():
                        arcname = file_path.relative_to(temp_dir)
                        zf.write(file_path, arcname)

            shutil.rmtree(temp_dir)
            temp_dir = None

            self.progress.emit(f"Created {app_config.MOD_FILE_EXT} package: {save_path.name}")
            self.progressPercent.emit(85)

            self.progress.emit("Installing mod...")
            install_result = self.mod_package_manager.install_mod(str(save_path))

            if install_result is None:
                return "Installation skipped: A newer version is already installed"

            mod_uuid = install_result['uuid']
            mod_name = install_result['mod_name']
            version = install_result['version']
            replaced = install_result['replaced']

            self.progressPercent.emit(100)

            if replaced:
                return f"Mod updated successfully!\n{mod_name} v{version}\nUUID: {mod_uuid}"
            else:
                return f"Mod imported and installed successfully!\n{mod_name} v{version}\nUUID: {mod_uuid}"

        except Exception as e:

            if temp_dir and temp_dir.exists():
                shutil.rmtree(temp_dir)
            raise Exception(f"Failed to convert mod: {e}")
