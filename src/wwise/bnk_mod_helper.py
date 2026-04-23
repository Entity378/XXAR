

import sys
from pathlib import Path

from src.wwise.pck_packer import PCKPacker

import src.core.app_config as app_config

from src.core.logger import get_logger
logger = get_logger(__name__)

def prepare_bnk_structure(wem_files_dir, bnk_id, output_structure_dir):

    wem_files_dir = Path(wem_files_dir)
    output_structure_dir = Path(output_structure_dir)

    bnk_dir = output_structure_dir / f"{bnk_id}_bnk"
    bnk_dir.mkdir(parents=True, exist_ok=True)

    wem_files = list(wem_files_dir.glob('*.wem'))

    if not wem_files:
        raise FileNotFoundError(f"No .wem files found in {wem_files_dir}")

    logger.info(f"\nPreparing BNK structure...")
    logger.info(f"  BNK ID: {bnk_id}")
    logger.info(f"  WEM files: {len(wem_files)}")

    for wem_file in wem_files:
        dest = bnk_dir / wem_file.name
        import shutil
        shutil.copy2(wem_file, dest)
        logger.info(f"    Copied: {wem_file.name}")

    logger.info(f"\n[OK] Structure created: {output_structure_dir}")
    return output_structure_dir

def mod_soundbank_pck(original_pck, wem_files_dir, bnk_id, output_pck, lang_id=0):

    logger.info("=" * 60)
    logger.info("BNK Modding Workflow: WEM -> BNK -> PCK")
    logger.info("=" * 60)

    temp_dir = Path("./temp_bnk_structure")
    structure_dir = prepare_bnk_structure(wem_files_dir, bnk_id, temp_dir)

    logger.info(f"\nLoading original PCK: {original_pck}")
    packer = PCKPacker(original_pck, output_pck)
    packer.load_original_pck()

    packer.replace_files_from_directory(structure_dir, lang_id)

    packer.pack(use_patching=True)
    packer.close()

    import shutil
    shutil.rmtree(temp_dir)

    logger.info("\n" + "=" * 60)
    logger.info("[OK] BNK Modding Complete!")
    logger.info("=" * 60)
    logger.info(f"\nModded PCK: {output_pck}")
    logger.info(f"BNK ID: {bnk_id}")
    logger.info(f"Modified WEMs: {len(list(Path(wem_files_dir).glob('*.wem')))}")
    logger.info("\nInstall to:")
    logger.info(f"  {app_config.GAME_DATA_FOLDER}/Persistent/Audio/Windows/Full/")

def main():

    if len(sys.argv) < 5:
        logger.info("Usage: python bnk_mod_helper.py <original_pck> <wem_files_dir> <bnk_id> <output_pck>")
        logger.info("")
        logger.info("Example:")
        logger.info("  python bnk_mod_helper.py SoundBank_SFX_1.pck ./my_wems 428903628 SoundBank_SFX_1_MODDED.pck")
        logger.info("")
        logger.info("This will:")
        logger.info("  1. Take WEM files from ./my_wems/")
        logger.info("  2. Embed them in BNK 428903628")
        logger.info("  3. Repack into SoundBank_SFX_1_MODDED.pck")
        sys.exit(1)

    original_pck = sys.argv[1]
    wem_files_dir = sys.argv[2]
    bnk_id = int(sys.argv[3])
    output_pck = sys.argv[4]

    mod_soundbank_pck(original_pck, wem_files_dir, bnk_id, output_pck)

if __name__ == "__main__":
    main()
