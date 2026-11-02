"""Script ponctuel : convertit un modele Helsinki-NLP/opus-mt-XX-YY (HuggingFace,
format PyTorch) vers le format ctranslate2 (rapide, CPU, pour l'inference des
poids). A executer une fois par paire de langues necessaire -- le seul module
absent de l'image de prod a ce moment-la est huggingface_hub (telechargement du
modele source), voir requirements-convert.txt.

Usage : python -m app.scripts.convert_translation_model ru en
        python -m app.scripts.convert_translation_model mul en   # toutes langues -> anglais

⚠️ TROIS DEFAUTS CORRIGES LE 2026-09-21, trouves en installant `mul-en` :

1. **Ecriture non atomique.** La conversion ecrivait les poids directement dans
   le dossier final, PUIS copiait le tokenizer. Une interruption entre les deux
   laissait un dossier avec `model.bin` mais sans tokenizer -- constate. Or
   `translate._load_pair` ne verifiait que `model.bin` : le modele passait pour
   installe et chaque traduction aurait plante. → conversion dans un dossier
   temporaire, renomme seulement une fois COMPLET.
2. **« Deja converti » sur la seule existence du dossier** -- donc aussi sur
   un dossier a moitie ecrit. → on verifie les fichiers.
3. **Telechargement du depot ENTIER** pour recuperer quatre petits fichiers de
   tokenizer (poids PyTorch compris, des centaines de Mo). → `allow_patterns`.
"""

import shutil
import sys
from pathlib import Path

from ctranslate2.converters import TransformersConverter
from huggingface_hub import snapshot_download

MODELS_DIR = Path("/app/translation_models")

# Fichiers necessaires a MarianTokenizer.from_pretrained(output_dir) -- voir
# pipeline/enrich/translate.py. ct2-transformers-converter ne copie que les
# poids (model.bin) : le tokenizer (normalisation Moses + SentencePiece) doit
# etre copie a part pour que le dossier de sortie soit auto-suffisant.
_TOKENIZER_FILES = ["source.spm", "target.spm", "vocab.json", "tokenizer_config.json"]
REQUIRED_FILES = ["model.bin", *_TOKENIZER_FILES]


def is_complete(model_dir: Path) -> bool:
    return all((model_dir / name).exists() for name in REQUIRED_FILES)


def convert(source_lang: str, target_lang: str) -> None:
    hf_model = f"Helsinki-NLP/opus-mt-{source_lang}-{target_lang}"
    output_dir = MODELS_DIR / f"{source_lang}-{target_lang}"
    if is_complete(output_dir):
        print(f"Deja converti : {output_dir}")
        return

    temp_dir = MODELS_DIR / f".{source_lang}-{target_lang}.partiel"
    shutil.rmtree(temp_dir, ignore_errors=True)

    print(f"Conversion {hf_model} -> {output_dir}")
    TransformersConverter(hf_model).convert(str(temp_dir), quantization="int8")

    snapshot_dir = Path(snapshot_download(hf_model, allow_patterns=_TOKENIZER_FILES))
    for filename in _TOKENIZER_FILES:
        shutil.copy(snapshot_dir / filename, temp_dir / filename)

    if not is_complete(temp_dir):
        raise SystemExit(f"Conversion incomplete, rien d'installe : {temp_dir}")
    # Un dossier incomplet d'une tentative precedente est remplace.
    shutil.rmtree(output_dir, ignore_errors=True)
    temp_dir.rename(output_dir)
    print("OK")


if __name__ == "__main__":
    convert(sys.argv[1], sys.argv[2])
