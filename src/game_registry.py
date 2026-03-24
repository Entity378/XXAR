from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


@dataclass(frozen=True)
class GameDefinition:
    id: str
    build_target: str
    display_name: str
    short_label: str
    data_dir_name: str
    install_dir_name: str
    game_audio_subpath: tuple[str, ...]
    persistent_audio_subpath: tuple[str, ...]
    gamebanana_game_id: Optional[int] = None
    soundbank_pck_glob: str = "*.pck"
    streamed_pck_glob: str = "*.pck"
    streamed_pck_prefix: str = "Streamed"
    soundbank_pck_prefix: str = "SoundBank"
    soundbank_pck_filter_prefix: str = "SoundBank"
    language_folders: tuple[tuple[str, str], ...] = ()
    audio_root_friendly_name: str = "Audio"
    subfolder_sort_priority: tuple[tuple[str, int], ...] = ()
    non_language_tabs: tuple[str, ...] = ("Full", "Common")
    check_streaming_pairing: bool = False
    merge_wem_default: bool = True
    hide_useless_pck_default: bool = True
    loop_point_patching_supported: bool = False
    loop_point_modes: tuple[str, ...] = ("auto", "manual", "disabled")
    special_audio_dirs: tuple[str, ...] = ()
    music_pck_regex: Optional[str] = None
    streamed_pck_regex: Optional[str] = None
    bank_pck_regex: Optional[str] = None


_ALL_GAMES: tuple[GameDefinition, ...] = (
    GameDefinition(
        id="zzz",
        build_target="ZZAR",
        display_name="Zenless Zone Zero",
        short_label="ZZZ",
        data_dir_name="ZenlessZoneZero_Data",
        install_dir_name="ZenlessZoneZero Game",
        game_audio_subpath=("StreamingAssets", "Audio", "Windows", "Full"),
        persistent_audio_subpath=("Persistent", "Audio", "Windows", "Full"),
        gamebanana_game_id=19567,
        soundbank_pck_glob="SoundBank_SFX_*.pck",
        streamed_pck_glob="Streamed_SFX_*.pck",
        streamed_pck_prefix="Streamed_SFX_",
        soundbank_pck_prefix="SoundBank_SFX_",
        soundbank_pck_filter_prefix="SoundBank_",
        language_folders=(
            ("En", "English"),
            ("Jp", "Japanese"),
            ("japanese(jp)", "Japanese"),
            ("Kr", "Korean"),
            ("Cn", "Chinese"),
        ),
        audio_root_friendly_name="SFX/Music",
        subfolder_sort_priority=(),
        non_language_tabs=("Full", "Common"),
        check_streaming_pairing=True,
        merge_wem_default=True,
        hide_useless_pck_default=True,
    ),
    GameDefinition(
        id="genshin",
        build_target="GIAR",
        display_name="Genshin Impact",
        short_label="GI",
        data_dir_name="GenshinImpact_Data",
        install_dir_name="Genshin Impact game",
        game_audio_subpath=("StreamingAssets", "AudioAssets"),
        persistent_audio_subpath=("Persistent", "AudioAssets"),
        gamebanana_game_id=8552,
        soundbank_pck_glob="Bank*.pck",
        streamed_pck_glob="Streamed*.pck",
        streamed_pck_prefix="Streamed",
        soundbank_pck_prefix="Bank",
        soundbank_pck_filter_prefix="Bank",
        language_folders=(),
        audio_root_friendly_name="AudioAssets",
        subfolder_sort_priority=(),
        non_language_tabs=("Full", "Common"),
        merge_wem_default=True,
        hide_useless_pck_default=True,
        loop_point_patching_supported=True,
        loop_point_modes=("auto", "manual", "disabled"),
        special_audio_dirs=("BeyondUGC", "MusicGame"),
        music_pck_regex=r"^[a-z]*music\d+\.pck$",
        streamed_pck_regex=r"^[a-z]*streamed\d+\.pck$",
        bank_pck_regex=r"^[a-z]*banks?\d*\.pck$",
    ),
    GameDefinition(
        id="hsr",
        build_target="SRAR",
        display_name="Honkai Star Rail",
        short_label="HSR",
        data_dir_name="StarRail_Data",
        install_dir_name="Honkai Star Rail Game",
        game_audio_subpath=("StreamingAssets", "Audio", "AudioPackage", "Windows"),
        persistent_audio_subpath=("Persistent", "Audio", "AudioPackage", "Windows"),
        gamebanana_game_id=18366,
        soundbank_pck_glob="Banks*.pck",
        streamed_pck_glob="Streamed*.pck",
        streamed_pck_prefix="Streamed",
        soundbank_pck_prefix="Banks",
        soundbank_pck_filter_prefix="Banks",
        language_folders=(
            ("English", "English"),
            ("Japanese", "Japanese"),
            ("Korean", "Korean"),
            ("Chinese(PRC)", "Chinese"),
            ("SFX", "SFX"),
        ),
        audio_root_friendly_name="Music",
        subfolder_sort_priority=(("SFX", 0),),
        non_language_tabs=("Full", "Common", "SFX"),
        merge_wem_default=False,
        hide_useless_pck_default=False,
    ),
)

DEFAULT_GAME_ID = "zzz"

_GAME_BY_ID = {game.id: game for game in _ALL_GAMES}
_DATA_DIR_TO_GAME = {game.data_dir_name: game for game in _ALL_GAMES}
_BUILD_TARGET_TO_GAME_ID = {game.build_target: game.id for game in _ALL_GAMES}
_GAME_MODE_ALIASES = {
    "zzz": "zzz",
    "zzar": "zzz",
    "genshin": "genshin",
    "gi": "genshin",
    "giar": "genshin",
    "hsr": "hsr",
    "srar": "hsr",
}


def get_game_id_for_build_target(build_target, default: str = DEFAULT_GAME_ID) -> str:
    key = str(build_target or "").strip().upper()
    return _BUILD_TARGET_TO_GAME_ID.get(key, default)


def get_game_for_build_target(build_target, default: str = DEFAULT_GAME_ID) -> GameDefinition:
    return get_game(get_game_id_for_build_target(build_target, default=default))


def get_game_mode_aliases() -> dict[str, str]:
    return dict(_GAME_MODE_ALIASES)


def get_data_dir_to_game_id_map() -> dict[str, str]:
    return {name: game.id for name, game in _DATA_DIR_TO_GAME.items()}


def get_supported_games(build_target=None) -> tuple[GameDefinition, ...]:
    if build_target is None:
        return _ALL_GAMES
    return (get_game_for_build_target(build_target),)


def get_supported_game_ids(build_target=None) -> tuple[str, ...]:
    return tuple(game.id for game in get_supported_games(build_target))


def get_supported_game_short_labels(build_target=None) -> dict[str, str]:
    return {game.id: game.short_label for game in get_supported_games(build_target)}


def get_known_data_dir_names() -> tuple[str, ...]:
    return tuple(game.data_dir_name for game in _ALL_GAMES)


def normalize_game_mode(game_mode, default: str = DEFAULT_GAME_ID) -> str:
    key = str(game_mode or "").strip().lower()
    canonical = _GAME_MODE_ALIASES.get(key, key)
    return normalize_game_id(canonical, default=default)


def normalize_game_id(game_id, default: str = DEFAULT_GAME_ID) -> str:
    candidate = str(game_id or "").strip().lower()
    return candidate if candidate in _GAME_BY_ID else default


def get_game(game_id, default: str = DEFAULT_GAME_ID) -> GameDefinition:
    return _GAME_BY_ID[normalize_game_id(game_id, default=default)]


def get_game_display_name(game_id, default: str = DEFAULT_GAME_ID) -> str:
    return get_game(game_id, default=default).display_name


def get_gamebanana_game_id(game_id, default=None):
    game = get_game(game_id)
    return game.gamebanana_game_id if game.gamebanana_game_id is not None else default


def get_game_language_folders(game_id) -> dict[str, str]:
    return dict(get_game(game_id).language_folders)


def get_game_subfolder_sort_priority(game_id) -> dict[str, int]:
    return dict(get_game(game_id).subfolder_sort_priority)


def get_audio_settings_keys(game_id) -> tuple[str, str]:
    normalized = normalize_game_id(game_id)
    return (f"{normalized}_game_audio_dir", f"{normalized}_persistent_audio_dir")


def get_conflict_preferences_key(game_id) -> str:
    return f"{normalize_game_id(game_id)}_conflict_preferences"


def build_audio_paths(game_id, game_data_path) -> tuple[Path, Path]:
    game = get_game(game_id)
    root = Path(game_data_path)
    return (
        root.joinpath(*game.game_audio_subpath),
        root.joinpath(*game.persistent_audio_subpath),
    )


def normalize_game_data_dir(path) -> Path:
    candidate = Path(path)
    if candidate.name in _DATA_DIR_TO_GAME:
        return candidate

    for game in _ALL_GAMES:
        nested = candidate / game.data_dir_name
        if nested.exists():
            return nested

    return candidate


def resolve_game_data_dir(path):
    if not path:
        return None

    candidate = normalize_game_data_dir(path)
    if is_valid_game_data_dir(candidate):
        return candidate

    candidate = Path(path)
    for parent in [candidate, *candidate.parents]:
        if parent.name in _DATA_DIR_TO_GAME and is_valid_game_data_dir(parent):
            return parent

    return None


def is_valid_game_data_dir(path) -> bool:
    candidate = Path(path)
    if not candidate.exists():
        return False
    if candidate.name not in _DATA_DIR_TO_GAME:
        return False
    return (candidate / "StreamingAssets").exists()


def detect_game_id_from_path(path, default: Optional[str] = DEFAULT_GAME_ID):
    if not path:
        return default

    candidate = Path(path)
    if candidate.name in _DATA_DIR_TO_GAME:
        return _DATA_DIR_TO_GAME[candidate.name].id

    path_parts = set(candidate.parts)
    for game in _ALL_GAMES:
        if game.data_dir_name in path_parts:
            return game.id

    return default


def extract_game_data_dir_from_audio_path(audio_dir) -> str:
    if not audio_dir:
        return ""

    audio_path = Path(audio_dir)
    for parent in [audio_path, *audio_path.parents]:
        if parent.name in _DATA_DIR_TO_GAME:
            return str(parent)
    return str(audio_path)


def iter_windows_autodetect_data_dirs() -> Iterable[Path]:
    for game in _ALL_GAMES:
        for drive in ("C", "D", "E"):
            yield (
                Path(f"{drive}:/Program Files/HoYoPlay/games")
                / game.install_dir_name
                / game.data_dir_name
            )
        yield Path.home() / "Games" / game.install_dir_name / game.data_dir_name
