"""Central artifact paths.

Skills and baselines live in language/ (the language as delivered artifact).
Runners resolve prompts through PROMPT_FILES / load_skill(); never hardcode
prompt paths.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LANGUAGE_DIR = REPO_ROOT / "language"
SKILLS_DIR = LANGUAGE_DIR / "skills"
VARIANTS_DIR = SKILLS_DIR / "variants"
BASELINES_DIR = LANGUAGE_DIR / "baselines"

# arm -> path relative lookup table (checked in order)
_PROMPT_LOOKUP = [SKILLS_DIR, VARIANTS_DIR, BASELINES_DIR, Path(__file__).resolve().parent]

# canonical names (new) with legacy aliases
PROMPT_FILES = {
    "tahoe": "tahoe-93.txt",
    "triz-implicit": "triz-implicit.txt",
    "tahoe-50": "variants/tahoe-50.txt",
    "tahoe-150": "variants/tahoe-150.txt",
    "tahoe-200": "variants/tahoe-200.txt",
    "triz-implicit-50": "variants/triz-implicit-50.txt",
    "triz-implicit-150": "variants/triz-implicit-150.txt",
    "triz-explicit": "variants/triz-explicit.txt",
    "cot": "cot.txt",
    "cod": "cod.txt",
    "tot": "tot.txt",
    "react": "react.txt",
    # legacy aliases (old filenames) resolve to the same artifacts
    "tahoe_skill_prompt.txt": "tahoe-93.txt",
    "tahoe_triz_implicit.txt": "triz-implicit.txt",
    "tahoe_skill_50.txt": "variants/tahoe-50.txt",
    "tahoe_skill_150.txt": "variants/tahoe-150.txt",
    "tahoe_skill_200.txt": "variants/tahoe-200.txt",
    "triz_implicit_50.txt": "variants/triz-implicit-50.txt",
    "triz_implicit_150.txt": "variants/triz-implicit-150.txt",
    "tahoe_triz_skill.txt": "variants/triz-explicit.txt",
    "cot_prompt.txt": "cot.txt",
    "cod_prompt.txt": "cod.txt",
    "tot_prompt.txt": "tot.txt",
    "react_prompt.txt": "react.txt",
}


def resolve_prompt(name: str) -> Path:
    """Resolve a prompt by new name, legacy filename, or relative path."""
    if name in PROMPT_FILES:
        rel = PROMPT_FILES[name]
    else:
        rel = name
    for base in _PROMPT_LOOKUP:
        candidate = base / rel
        if candidate.exists():
            return candidate
        # legacy alias may itself be relative to a different base
        if name in PROMPT_FILES:
            candidate2 = base / PROMPT_FILES[name]
            if candidate2.exists():
                return candidate2
    raise FileNotFoundError(f"prompt not found: {name}")


def load_skill(name: str = "tahoe") -> str:
    return resolve_prompt(PROMPT_FILES.get(name, name)).read_text()
