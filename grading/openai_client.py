# grading/openai_client.py
from __future__ import annotations

import base64
import io
import json
import mimetypes
import os
from pathlib import Path
from typing import Dict, Optional, Any, Tuple

from grading.utils import pokemon_cache

import cv2
import numpy as np
from PIL import Image
from openai import OpenAI
from datetime import datetime
import traceback

from grading.ml.vision_checks import run_vision_checks_img

# =========================
# Config
# =========================
OPENAI_MODEL_GRADE = os.getenv("OPENAI_GRADING_MODEL", "gpt-4o")
OPENAI_MODEL_CLASS = os.getenv("OPENAI_CLASSIFIER_MODEL", "gpt-4o-mini")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

REQUIRE_FRONT_FIRST = True

# Debugging
DEBUG = os.getenv("CARDGRADER_DEBUG", "0").strip() not in {"", "0", "false", "False"}
DEBUG_DIR = Path(os.getenv("CARDGRADER_DEBUG_DIR", "./debug_runs"))
if DEBUG:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

# CV blending (keep OFF until you train on more data)
BLEND_CV_ALPHA = float(os.getenv("CV_BLEND_ALPHA", "0.0"))  # 0.0 = disabled
CV_WEIGHTS = os.getenv("CARDGRADER_WEIGHTS", "grading/ml/models/cardgrader_v1.pt")

client = OpenAI(api_key=OPENAI_API_KEY)

# =========================
# Helpers: JSON + debug I/O
# =========================
def _json_sanitize(obj):
    """
    Recursively convert numpy/PIL/Path/etc. to plain Python types so JSON
    and Django JSONField can serialize them.
    """
    # NumPy scalars -> Python scalars
    if isinstance(obj, np.generic):
        return obj.item()

    # NumPy arrays -> lists
    if isinstance(obj, np.ndarray):
        return obj.tolist()

    # Path -> str; set/tuple -> list; bytes -> str
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, (set, tuple)):
        return list(obj)
    if isinstance(obj, (bytes, bytearray)):
        try:
            return obj.decode("utf-8", "ignore")
        except Exception:
            return str(obj)

    # Dicts / Lists
    if isinstance(obj, dict):
        return {str(k): _json_sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_sanitize(v) for v in obj]

    # Primitives (int/float/bool/None/str)
    return obj

def _coerce_set_images(imgs_obj) -> dict:
    """PTCG SetImage -> plain dict."""
    if isinstance(imgs_obj, dict):
        return imgs_obj
    return {
        "logo":   getattr(imgs_obj, "logo",   "") or "",
        "symbol": getattr(imgs_obj, "symbol", "") or "",
        "small":  getattr(imgs_obj, "small",  "") or "",
        "large":  getattr(imgs_obj, "large",  "") or "",
        "url":    getattr(imgs_obj, "url",    "") or "",
    }

def _coerce_card_images(imgs_obj) -> dict:
    """PTCG CardImage -> plain dict."""
    if isinstance(imgs_obj, dict):
        return imgs_obj
    return {
        "small": getattr(imgs_obj, "small", "") or "",
        "large": getattr(imgs_obj, "large", "") or "",
        "hires": getattr(imgs_obj, "hires", "") or "",
        "url":   getattr(imgs_obj, "url",   "") or "",
    }

def _nowts() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%S.%fZ")


def _dbg_path(name: str) -> Path:
    return DEBUG_DIR / f"{_nowts()}_{name}"


def _debug(msg: str):
    if not DEBUG:
        return
    line = f"[CARDGRADER DEBUG] {msg}"
    print(line)
    try:
        with open(_dbg_path("debug.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _save_json_debug(obj: Any, name: str):
    if not DEBUG:
        return
    try:
        p = _dbg_path(name)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(_json_sanitize(obj), f, ensure_ascii=False, indent=2, default=str)
        _debug(f"Saved JSON → {p}")
    except Exception:
        _debug("Failed to save JSON: " + traceback.format_exc())



def _save_text_debug(text: str, name: str):
    if not DEBUG:
        return
    try:
        p = _dbg_path(name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        _debug(f"Saved text → {p}")
    except Exception:
        _debug("Failed to save text: " + traceback.format_exc())


def _save_img_debug(img_bgr: Optional[np.ndarray], name: str):
    if not DEBUG or img_bgr is None:
        return
    try:
        p = _dbg_path(name)
        cv2.imwrite(str(p), img_bgr)
        _debug(f"Saved image → {p}")
    except Exception:
        _debug("Failed to save image: " + traceback.format_exc())

# =========================
# Optional PokémonTCG.io SDK
# =========================
POKEMONTCG_API_KEY = os.getenv("POKEMONTCG_IO_API_KEY", "").strip()
_PTCG_AVAILABLE = False
try:
    from pokemontcgsdk import Card as _PTCG_Card
    from pokemontcgsdk import Set as _PTCG_Set
    from pokemontcgsdk import RestClient as _PTCG_RestClient
    if POKEMONTCG_API_KEY:
        _PTCG_RestClient.configure(POKEMONTCG_API_KEY)
    _PTCG_AVAILABLE = True
except Exception:
    _PTCG_AVAILABLE = False

_PTCG_CACHE: Dict[str, Dict[str, Any]] = {}


def _ptcg_cache_get(k: str) -> Optional[Dict[str, Any]]:
    return _PTCG_CACHE.get(k)


def _ptcg_cache_put(k: str, v: Dict[str, Any]) -> None:
    _PTCG_CACHE[k] = v


def _ptcg_lookup_set(ptcgo_code: str) -> Optional[Dict[str, Any]]:
    """Find set by PTCGO code (e.g., SVI, PAL, TEF)."""
    if not _PTCG_AVAILABLE or not ptcgo_code:
        return None
    key = f"set::{ptcgo_code.upper()}"
    hit = _ptcg_cache_get(key)
    if hit:
        return hit
    try:
        sets = _PTCG_Set.where(q=f'ptcgoCode:{ptcgo_code}')
        if sets:
            s = sets[0]
            data = {
                "set_id": s.id,
                "set_name": s.name,
                "series": getattr(s, "series", ""),
                "releaseDate": getattr(s, "releaseDate", ""),
                "ptcgoCode": getattr(s, "ptcgoCode", ""),
                "images": getattr(s, "images", {}) or {},
            }
            _ptcg_cache_put(key, data)
            return data
    except Exception:
        return None
    return None


def _ptcg_lookup_card_in_set(set_id: str, number_or_name: str) -> Optional[Dict[str, Any]]:
    """Try to find a card in a set by collector number (preferred) or name."""
    if not _PTCG_AVAILABLE or not set_id:
        return None
    key = f"card::{set_id}::{(number_or_name or '').lower()}"
    hit = _ptcg_cache_get(key)
    if hit:
        return hit
    try:
        if number_or_name:
            # Prefer collector number
            cards = _PTCG_Card.where(q=f'set.id:{set_id} number:{number_or_name}')
            if not cards:
                # fallback: try name exact
                cards = _PTCG_Card.where(q=f'set.id:{set_id} name:"{number_or_name}"')
        else:
            cards = []
        if cards:
            c = cards[0]
            data = {
                "card_id": c.id,
                "name": c.name,
                "number": getattr(c, "number", ""),
                "rarity": getattr(c, "rarity", ""),
                "subtypes": getattr(c, "subtypes", []) or [],
                "supertype": getattr(c, "supertype", ""),
                "types": getattr(c, "types", []) or [],
                "regulationMark": getattr(c, "regulationMark", ""),
                "images": getattr(c, "images", {}) or {},
                "tcgplayer": getattr(c, "tcgplayer", {}) or {},
            }
            _ptcg_cache_put(key, data)
            return data
    except Exception:
        return None
    return None

# =========================
# Game back references (for the game-aware prompt)
# =========================
GAME_BACK_RULES = {
    "pokemon": "Back reference: blue background with Poké Ball and 'Pokémon' logo.",
    "one_piece": "Back reference: mostly blue (sometimes white or red) with 'ONE PIECE CARD GAME' text and a compass design.",
    "mtg": "Back reference: brown/sepia oval with five colored mana orbs and 'Magic: The Gathering'.",
}

GAME_LABELS = {
    "pokemon": "Pokémon",
    "one_piece": "One Piece",
    "mtg": "Magic: The Gathering",
}

# =========================
# Optional symbol resolver (your utils)
# =========================
_SYMBOL_UTILS_OK = False
try:
    from grading.utils.set_symbols import (
        resolve_set_info as _utils_resolve_set_info,
        detect_set_symbol_key as _utils_detect_set_symbol_key,
        resolve_from_symbol as _utils_resolve_from_symbol,
    )
    _SYMBOL_UTILS_OK = True
except Exception:
    _SYMBOL_UTILS_OK = False

# ===== Fallback symbol detection (ROI + template matching) =====
_SYMBOL_TEMPLATES: Dict[str, np.ndarray] = {}

def _load_symbol_templates():
    """Lazy-load small grayscale templates from grading/assets/symbols/*.png."""
    global _SYMBOL_TEMPLATES
    if _SYMBOL_TEMPLATES:
        return
    base = Path("grading/assets/symbols")
    if not base.exists():
        return
    for p in base.glob("*.png"):
        img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        if img is not None:
            _SYMBOL_TEMPLATES[p.stem] = img


def _crop_symbol_region(img_bgr: Optional[np.ndarray]) -> Optional[np.ndarray]:
    """Heuristic ROI where Pokémon set symbol/collector strip often lives (canvas=896x640)."""
    if img_bgr is None:
        return None
    h, w = img_bgr.shape[:2]
    y0 = int(h * 0.78); y1 = int(h * 0.95)
    x0 = int(w * 0.05); x1 = int(w * 0.45)
    roi = img_bgr[max(0, y0):min(h, y1), max(0, x0):min(w, x1)]
    return roi if roi.size else None


def _detect_symbol_by_template(roi_bgr: Optional[np.ndarray]) -> Tuple[Optional[str], float]:
    if roi_bgr is None:
        return (None, 0.0)
    _load_symbol_templates()
    if not _SYMBOL_TEMPLATES:
        return (None, 0.0)
    gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
    best_key, best_score = None, 0.0
    for key, tmpl in _SYMBOL_TEMPLATES.items():
        for s in (0.6, 0.8, 1.0, 1.2):
            th = max(8, int(tmpl.shape[0] * s)); tw = max(8, int(tmpl.shape[1] * s))
            t = cv2.resize(tmpl, (tw, th), interpolation=cv2.INTER_AREA)
            if gray.shape[0] < th or gray.shape[1] < tw:
                continue
            res = cv2.matchTemplate(gray, t, cv2.TM_CCOEFF_NORMED)
            _, maxVal, _, _ = cv2.minMaxLoc(res)
            if maxVal > best_score:
                best_score, best_key = float(maxVal), key
    return (best_key, best_score)


def _detect_set_symbol_key(img_bgr: np.ndarray) -> Tuple[Optional[str], float]:
    """Prefer utils; else ROI+template fallback."""
    if img_bgr is None:
        return (None, 0.0)
    if _SYMBOL_UTILS_OK:
        try:
            return _utils_detect_set_symbol_key(img_bgr)
        except Exception:
            pass
    roi = _crop_symbol_region(img_bgr)
    return _detect_symbol_by_template(roi)

# =========================
# Minimal set-code resolver + mappings
# =========================

def _norm_code(code: str) -> str:
    if not code:
        return ""
    code = code.strip()
    for ch in ".-_/\\|:;,":
        code = code.replace(ch, " ")
    code = " ".join(code.split()).lower()
    return code

SYMBOL_STYLE_MAP: Dict[str, Dict[str, str]] = {
    # Scarlet & Violet
    "svi en":   {"set_name": "Scarlet & Violet", "era": "SV", "border": "silver", "language": "en"},
    "pal en":   {"set_name": "Paldea Evolved", "era": "SV", "border": "silver", "language": "en"},
    "obf en":   {"set_name": "Obsidian Flames", "era": "SV", "border": "silver", "language": "en"},
    "par en":   {"set_name": "Paradox Rift", "era": "SV", "border": "silver", "language": "en"},
    "tef en":   {"set_name": "Temporal Forces", "era": "SV", "border": "silver", "language": "en"},
    "twm en":   {"set_name": "Twilight Masquerade", "era": "SV", "border": "silver", "language": "en"},
    "sfa en":   {"set_name": "Shrouded Fable", "era": "SV", "border": "silver", "language": "en"},
    "scr en":   {"set_name": "Stellar Crown", "era": "SV", "border": "silver", "language": "en"},
    "ssp en":   {"set_name": "Surging Sparks", "era": "SV", "border": "silver", "language": "en"},
    "pre en":   {"set_name": "Prismatic Evolutions", "era": "SV", "border": "silver", "language": "en"},
    "sv151 en": {"set_name": "Scarlet & Violet 151", "era": "SV", "border": "silver", "language": "en"},

    # Sword & Shield
    "ssh en": {"set_name": "Sword & Shield", "era": "SWSH", "border": "yellow", "language": "en"},
    "rcl en": {"set_name": "Rebel Clash", "era": "SWSH", "border": "yellow", "language": "en"},
    "daa en": {"set_name": "Darkness Ablaze", "era": "SWSH", "border": "yellow", "language": "en"},
    "viv en": {"set_name": "Vivid Voltage", "era": "SWSH", "border": "yellow", "language": "en"},
    "bst en": {"set_name": "Battle Styles", "era": "SWSH", "border": "yellow", "language": "en"},
    "cre en": {"set_name": "Chilling Reign", "era": "SWSH", "border": "yellow", "language": "en"},
    "evs en": {"set_name": "Evolving Skies", "era": "SWSH", "border": "yellow", "language": "en"},
    "fst en": {"set_name": "Fusion Strike", "era": "SWSH", "border": "yellow", "language": "en"},
    "brs en": {"set_name": "Brilliant Stars", "era": "SWSH", "border": "yellow", "language": "en"},
    "asr en": {"set_name": "Astral Radiance", "era": "SWSH", "border": "yellow", "language": "en"},
    "lor en": {"set_name": "Lost Origin", "era": "SWSH", "border": "yellow", "language": "en"},
    "sit en": {"set_name": "Silver Tempest", "era": "SWSH", "border": "yellow", "language": "en"},
    "pgo en": {"set_name": "Pokémon GO", "era": "SWSH", "border": "yellow", "language": "en"},
    "cel en": {"set_name": "Celebrations", "era": "SWSH", "border": "yellow", "language": "en"},
    "clc en": {"set_name": "Celebrations Classic Collection", "era": "SWSH", "border": "yellow", "language": "en"},
    "shf en": {"set_name": "Shining Fates", "era": "SWSH", "border": "yellow", "language": "en"},
    "cpp en": {"set_name": "Champion’s Path", "era": "SWSH", "border": "yellow", "language": "en"},
    "crz en": {"set_name": "Crown Zenith", "era": "SWSH", "border": "yellow", "language": "en"},

    # Sun & Moon
    "sm1 en":  {"set_name": "Sun & Moon", "era": "SM", "border": "yellow", "language": "en"},
    "sm2 en":  {"set_name": "Guardians Rising", "era": "SM", "border": "yellow", "language": "en"},
    "sm3 en":  {"set_name": "Burning Shadows", "era": "SM", "border": "yellow", "language": "en"},
    "sm4 en":  {"set_name": "Crimson Invasion", "era": "SM", "border": "yellow", "language": "en"},
    "sm5 en":  {"set_name": "Ultra Prism", "era": "SM", "border": "yellow", "language": "en"},
    "sm6 en":  {"set_name": "Forbidden Light", "era": "SM", "border": "yellow", "language": "en"},
    "sm7 en":  {"set_name": "Celestial Storm", "era": "SM", "border": "yellow", "language": "en"},
    "sm8 en":  {"set_name": "Lost Thunder", "era": "SM", "border": "yellow", "language": "en"},
    "sm9 en":  {"set_name": "Team Up", "era": "SM", "border": "yellow", "language": "en"},
    "sm10 en": {"set_name": "Unbroken Bonds", "era": "SM", "border": "yellow", "language": "en"},
    "sm11 en": {"set_name": "Unified Minds", "era": "SM", "border": "yellow", "language": "en"},
    "sm12 en": {"set_name": "Cosmic Eclipse", "era": "SM", "border": "yellow", "language": "en"},
    "drm en":  {"set_name": "Dragon Majesty", "era": "SM", "border": "yellow", "language": "en"},
    "hif en":  {"set_name": "Hidden Fates", "era": "SM", "border": "yellow", "language": "en"},
    "dep en":  {"set_name": "Detective Pikachu", "era": "SM", "border": "yellow", "language": "en"},

    # XY
    "xy en":   {"set_name": "XY Base Set", "era": "XY", "border": "yellow", "language": "en"},
    "flf en":  {"set_name": "Flashfire", "era": "XY", "border": "yellow", "language": "en"},
    "frf en":  {"set_name": "Furious Fists", "era": "XY", "border": "yellow", "language": "en"},
    "phf en":  {"set_name": "Phantom Forces", "era": "XY", "border": "yellow", "language": "en"},
    "prc en":  {"set_name": "Primal Clash", "era": "XY", "border": "yellow", "language": "en"},
    "ros en":  {"set_name": "Roaring Skies", "era": "XY", "border": "yellow", "language": "en"},
    "aor en":  {"set_name": "Ancient Origins", "era": "XY", "border": "yellow", "language": "en"},
    "bkt en":  {"set_name": "BREAKthrough", "era": "XY", "border": "yellow", "language": "en"},
    "bkp en":  {"set_name": "BREAKpoint", "era": "XY", "border": "yellow", "language": "en"},
    "gen en":  {"set_name": "Generations", "era": "XY", "border": "yellow", "language": "en"},
    "fac en":  {"set_name": "Fates Collide", "era": "XY", "border": "yellow", "language": "en"},
    "sts en":  {"set_name": "Steam Siege", "era": "XY", "border": "yellow", "language": "en"},
    "evo en":  {"set_name": "Evolutions", "era": "XY", "border": "yellow", "language": "en"},
    "dcr en":  {"set_name": "Double Crisis", "era": "XY", "border": "yellow", "language": "en"},

    # Black & White
    "bw en":   {"set_name": "Black & White", "era": "BW", "border": "yellow", "language": "en"},
    "emp en":  {"set_name": "Emerging Powers", "era": "BW", "border": "yellow", "language": "en"},
    "nvi en":  {"set_name": "Noble Victories", "era": "BW", "border": "yellow", "language": "en"},
    "nde en":  {"set_name": "Next Destinies", "era": "BW", "border": "yellow", "language": "en"},
    "dex en":  {"set_name": "Dark Explorers", "era": "BW", "border": "yellow", "language": "en"},
    "drx en":  {"set_name": "Dragons Exalted", "era": "BW", "border": "yellow", "language": "en"},
    "bcr en":  {"set_name": "Boundaries Crossed", "era": "BW", "border": "yellow", "language": "en"},
    "pls en":  {"set_name": "Plasma Storm", "era": "BW", "border": "yellow", "language": "en"},
    "plf en":  {"set_name": "Plasma Freeze", "era": "BW", "border": "yellow", "language": "en"},
    "plb en":  {"set_name": "Plasma Blast", "era": "BW", "border": "yellow", "language": "en"},
    "ltr en":  {"set_name": "Legendary Treasures", "era": "BW", "border": "yellow", "language": "en"},
    "drv en":  {"set_name": "Dragon Vault", "era": "BW", "border": "yellow", "language": "en"},

    # HeartGold & SoulSilver
    "hs en":   {"set_name": "HeartGold & SoulSilver", "era": "HGSS", "border": "yellow", "language": "en"},
    "ul en":   {"set_name": "Unleashed", "era": "HGSS", "border": "yellow", "language": "en"},
    "ud en":   {"set_name": "Undaunted", "era": "HGSS", "border": "yellow", "language": "en"},
    "tm en":   {"set_name": "Triumphant", "era": "HGSS", "border": "yellow", "language": "en"},
    "col en":  {"set_name": "Call of Legends", "era": "HGSS", "border": "yellow", "language": "en"},

    # Platinum
    "pl1 en":  {"set_name": "Platinum", "era": "Platinum", "border": "yellow", "language": "en"},
    "pl2 en":  {"set_name": "Rising Rivals", "era": "Platinum", "border": "yellow", "language": "en"},
    "pl3 en":  {"set_name": "Supreme Victors", "era": "Platinum", "border": "yellow", "language": "en"},
    "pl4 en":  {"set_name": "Arceus", "era": "Platinum", "border": "yellow", "language": "en"},

    # Diamond & Pearl
    "dp1 en":  {"set_name": "Diamond & Pearl", "era": "DP", "border": "yellow", "language": "en"},
    "dp2 en":  {"set_name": "Mysterious Treasures", "era": "DP", "border": "yellow", "language": "en"},
    "dp3 en":  {"set_name": "Secret Wonders", "era": "DP", "border": "yellow", "language": "en"},
    "dp4 en":  {"set_name": "Great Encounters", "era": "DP", "border": "yellow", "language": "en"},
    "dp5 en":  {"set_name": "Majestic Dawn", "era": "DP", "border": "yellow", "language": "en"},
    "dp6 en":  {"set_name": "Legends Awakened", "era": "DP", "border": "yellow", "language": "en"},
    "dp7 en":  {"set_name": "Stormfront", "era": "DP", "border": "yellow", "language": "en"},

    # EX Series
    "rs en":   {"set_name": "EX Ruby & Sapphire", "era": "EX", "border": "yellow", "language": "en"},
    "ss en":   {"set_name": "EX Sandstorm", "era": "EX", "border": "yellow", "language": "en"},
    "dr en":   {"set_name": "EX Dragon", "era": "EX", "border": "yellow", "language": "en"},
    "ma en":   {"set_name": "EX Team Magma vs Team Aqua", "era": "EX", "border": "yellow", "language": "en"},
    "hl en":   {"set_name": "EX Hidden Legends", "era": "EX", "border": "yellow", "language": "en"},
    "rg en":   {"set_name": "EX FireRed & LeafGreen", "era": "EX", "border": "yellow", "language": "en"},
    "rr en":   {"set_name": "EX Team Rocket Returns", "era": "EX", "border": "yellow", "language": "en"},
    "dx en":   {"set_name": "EX Deoxys", "era": "EX", "border": "yellow", "language": "en"},
    "em en":   {"set_name": "EX Emerald", "era": "EX", "border": "yellow", "language": "en"},
    "uf en":   {"set_name": "EX Unseen Forces", "era": "EX", "border": "yellow", "language": "en"},
    "ds en":   {"set_name": "EX Delta Species", "era": "EX", "border": "yellow", "language": "en"},
    "lm en":   {"set_name": "EX Legend Maker", "era": "EX", "border": "yellow", "language": "en"},
    "hp en":   {"set_name": "EX Holon Phantoms", "era": "EX", "border": "yellow", "language": "en"},
    "cg en":   {"set_name": "EX Crystal Guardians", "era": "EX", "border": "yellow", "language": "en"},
    "df en":   {"set_name": "EX Dragon Frontiers", "era": "EX", "border": "yellow", "language": "en"},
    "pk en":   {"set_name": "EX Power Keepers", "era": "EX", "border": "yellow", "language": "en"},

    # e-Card
    "exp en":  {"set_name": "Expedition Base Set", "era": "e-Card", "border": "yellow", "language": "en"},
    "aqu en":  {"set_name": "Aquapolis", "era": "e-Card", "border": "yellow", "language": "en"},
    "skyr en": {"set_name": "Skyridge", "era": "e-Card", "border": "yellow", "language": "en"},

    # Base/WotC
    "bs en":   {"set_name": "Base Set", "era": "Base/WotC", "border": "yellow", "language": "en"},
    "ju en":   {"set_name": "Jungle", "era": "Base/WotC", "border": "yellow", "language": "en"},
    "fo en":   {"set_name": "Fossil", "era": "Base/WotC", "border": "yellow", "language": "en"},
    "b2 en":   {"set_name": "Base Set 2", "era": "Base/WotC", "border": "yellow", "language": "en"},
    "tr en":   {"set_name": "Team Rocket", "era": "Base/WotC", "border": "yellow", "language": "en"},
    "g1 en":   {"set_name": "Gym Heroes", "era": "Base/WotC", "border": "yellow", "language": "en"},
    "g2 en":   {"set_name": "Gym Challenge", "era": "Base/WotC", "border": "yellow", "language": "en"},
    "n1 en":   {"set_name": "Neo Genesis", "era": "Base/WotC", "border": "yellow", "language": "en"},
    "n2 en":   {"set_name": "Neo Discovery", "era": "Base/WotC", "border": "yellow", "language": "en"},
    "n3 en":   {"set_name": "Neo Revelation", "era": "Base/WotC", "border": "yellow", "language": "en"},
    "n4 en":   {"set_name": "Neo Destiny", "era": "Base/WotC", "border": "yellow", "language": "en"},
    "lc en":   {"set_name": "Legendary Collection", "era": "Base/WotC", "border": "yellow", "language": "en"},
    "si en":   {"set_name": "Southern Islands", "era": "Base/WotC", "border": "yellow", "language": "en"},

    # POP & Promos
    "pop1 en": {"set_name": "POP Series 1", "era": "Promo", "border": "yellow", "language": "en"},
    "pop2 en": {"set_name": "POP Series 2", "era": "Promo", "border": "yellow", "language": "en"},
    "pop3 en": {"set_name": "POP Series 3", "era": "Promo", "border": "yellow", "language": "en"},
    "pop4 en": {"set_name": "POP Series 4", "era": "Promo", "border": "yellow", "language": "en"},
    "pop5 en": {"set_name": "POP Series 5", "era": "Promo", "border": "yellow", "language": "en"},
    "pop6 en": {"set_name": "POP Series 6", "era": "Promo", "border": "yellow", "language": "en"},
    "pop7 en": {"set_name": "POP Series 7", "era": "Promo", "border": "yellow", "language": "en"},
    "pop8 en": {"set_name": "POP Series 8", "era": "Promo", "border": "yellow", "language": "en"},
    "pop9 en": {"set_name": "POP Series 9", "era": "Promo", "border": "yellow", "language": "en"},
    "p en":    {"set_name": "Black Star Promos", "era": "Promo", "border": "yellow", "language": "en"},
}


SET_CODE_MAP = SYMBOL_STYLE_MAP





CODE_TO_PTCGO = {
    # Scarlet & Violet (examples)
    "SVI": "SVI", "PAL": "PAL", "OBF": "OBF", "PAR": "PAR", "TEF": "TEF",
    "TWM": "TWM", "SFA": "SFA", "SCR": "SCR", "SSP": "SSP", "PRE": "PRE", "SV151": "MEW",

    # Sword & Shield (examples)
    "SSH": "SSH", "RCL": "RCL", "DAA": "DAA", "VIV": "VIV", "BST": "BST",
    "CRE": "CRE", "EVS": "EVS", "FST": "FST", "BRS": "BRS", "ASR": "ASR",
    "LOR": "LOR", "SIT": "SIT", "PGO": "PGO", "CEL": "CEL", "CLC": "CLC",
    "SHF": "SHF", "CPP": "CPA", "CRZ": "CRZ",

    # Sun & Moon (examples)
    "SM1": "SUM", "SM2": "GRI", "SM3": "BUS", "SM4": "CIN", "SM5": "UPR",
    "SM6": "FLI", "SM7": "CES", "SM8": "LOT", "SM9": "TEU", "SM10": "UNB",
    "SM11": "UNM", "SM12": "CEC", "DRM": "DRM", "HIF": "HIF", "DEP": "DET",

    # XY (examples)
    "XY": "XY", "FLF": "FLF", "FRF": "FFI", "PHF": "PHF", "PRC": "PRC",
    "ROS": "ROS", "AOR": "AOR", "BKT": "BKT", "BKP": "BKP", "GEN": "GEN",
    "FAC": "FCO", "STS": "STS", "EVO": "EVO", "DCR": "DCR",

    # Base/WotC (examples)
    "BS": "BASE", "JU": "JNG", "FO": "FOS", "B2": "B2", "TR": "TR",
    "G1": "G1", "G2": "G2", "N1": "N1", "N2": "N2", "N3": "N3",
    "N4": "N4", "LC": "LC", "SI": "SI",

    # Promos / misc
    "POP1": "POP1", "POP2": "POP2", "POP3": "POP3", "POP4": "POP4", "POP5": "POP5",
    "POP6": "POP6", "POP7": "POP7", "POP8": "POP8", "POP9": "POP9",
    "P": "PR",  # generic promos
}



    # Enrich from local Pokémon cache (wrapping the API) if possible
    # Enrich from local Pokémon cache (wrapping the API) if possible
def _ptcgo_from_code(code: str) -> str:
        """
        Convert various OCR/typed codes into a PTCGO code if possible.
        Accepts things like 'SM12', 'sm12 en', 'EVS EN', 'PAR', etc.
        """
        if not code:
            return ""
        nc = (code or "").strip().upper()
        # take first token like 'SM12' or 'EVS'
        tok = nc.split()[0]
        # If already a known PTCGO code, return it; else try map
        if tok in CODE_TO_PTCGO.values():
            return tok
        return CODE_TO_PTCGO.get(tok, "")



def _fallback_resolve_set_info(code: str, lang_hint: str = "unknown") -> Dict[str, str]:
    nc = _norm_code(code)
    info = {}
    if nc in SET_CODE_MAP:
        info = dict(SET_CODE_MAP[nc])
    else:
        first = nc.split(" ")[0] if nc else ""
        info = dict(SET_CODE_MAP.get(first, {}))
        if not info and nc:
            toks = nc.split(" ")
            if len(toks) >= 2:
                two = " ".join(toks[:2])
                info = dict(SET_CODE_MAP.get(two, {}))
    info.setdefault("set_name", "")
    info.setdefault("era", "")
    info.setdefault("border", "")
    info["language"] = info.get("language") or (lang_hint if lang_hint in {"en", "jp"} else "unknown")
    info["set_code"] = code or ""
    return info


def _resolve_set_info(code: str, lang_hint: str = "unknown") -> Dict[str, str]:
    if _SYMBOL_UTILS_OK:
        try:
            return _utils_resolve_set_info(code, lang_hint)
        except Exception:
            pass
    return _fallback_resolve_set_info(code, lang_hint)


def _resolve_from_symbol(key: str) -> Dict[str, Any]:
    if _SYMBOL_UTILS_OK:
        try:
            return _utils_resolve_from_symbol(key)
        except Exception:
            pass
    return {"set_name": "", "era": "", "border": "", "style_flags": []}

# =========================
# Image I/O helpers
# =========================
def _file_to_data_url(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    if not mime:
        mime = "image/jpeg"
    b64 = base64.b64encode(Path(path).read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def _bgr_to_data_url(img_bgr: np.ndarray, mime="image/jpeg", quality=92) -> str:
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    pil = Image.fromarray(img_rgb)
    buf = io.BytesIO()
    pil.save(buf, format="JPEG", quality=quality)
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def _img_part(path: Path) -> Dict[str, Any]:
    return {"type": "image_url", "image_url": {"url": _file_to_data_url(path)}}


def _img_part_from_data_url(data_url: str) -> Dict[str, Any]:
    return {"type": "image_url", "image_url": {"url": data_url}}


def _safe_float(x, d=0.0):
    try:
        return float(x)
    except Exception:
        return d

# =========================
# Caps / labels / summaries
# =========================
def _apply_sanity_caps(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    If LLM summary/observations imply heavy flaws, cap overall grade accordingly.
    """
    text = (result.get("summary", "") + " " +
            " ".join(o.get("note", "") for o in (result.get("observations") or []))).lower()

    def cap(grade_cap: float, qualifier: Optional[str] = None):
        if result["predicted_grade"] > grade_cap:
            result["predicted_grade"] = float(grade_cap)
        if qualifier and qualifier not in (result.get("predicted_label") or ""):
            lbl = result.get("predicted_label") or ""
            result["predicted_label"] = (lbl + f" [{qualifier}]").strip()

    # Writing/ink/marker/scribble ⇒ MK qualifier + cap to 3
    # Do NOT cap purely from text; CV handles MK. If LLM strongly insists,
    # just soft-cap overall to 7.5 unless CV confirms.
    if any(k in text for k in ["ink", "writing", "written", "marker", "pen", "crayon"]):
        if result["predicted_grade"] > 7.5:
            result["predicted_grade"] = 7.5

    # Crease/bend/tear/paper loss ⇒ cap at 4
    if any(k in text for k in ["crease", "bent", "bend", "fold", "tear", "rip", "paper loss", "missing paper"]):
        cap(4.0, None)

    # Any “heavy/obvious/large/significant” ⇒ cap ≤7.5
    if any(k in text for k in ["heavy", "obvious", "large", "significant"]):
        cap(7.5, None)

    # Grades 9–10 require no visible wear
    if result["predicted_grade"] >= 9.0:
        visible = any(k in text for k in [
            "whitening", "chip", "scratch", "dent", "dimple", "stain", "ink", "marker", "corner wear", "edge wear"
        ])
        if visible:
            cap(8.0, None)

    return result


def _fit_to_canvas(img_bgr: np.ndarray, target_h: int = 896, target_w: int = 640) -> Optional[np.ndarray]:
    """
    Letterbox+resize the image to a stable canvas so downstream crops/OCR can work
    even when a precise 4-corner warp isn't possible.
    """
    if img_bgr is None:
        return None
    h, w = img_bgr.shape[:2]
    if h <= 0 or w <= 0:
        return None

    # scale to fit inside target, preserve aspect
    scale = min(target_w / float(w), target_h / float(h))
    nw, nh = int(w * scale), int(h * scale)
    resized = cv2.resize(img_bgr, (nw, nh), interpolation=cv2.INTER_CUBIC)

    # letterbox to target size (centered)
    canvas = np.zeros((target_h, target_w, 3), dtype=np.uint8)
    y0 = (target_h - nh) // 2
    x0 = (target_w - nw) // 2
    canvas[y0:y0 + nh, x0:x0 + nw] = resized

    # optional: try to auto-orient (brighter bottom heuristic)
    top_mean = canvas[:80, :, :].mean()
    bot_mean = canvas[-80:, :, :].mean()
    if bot_mean + 10 < top_mean:
        canvas = cv2.rotate(canvas, cv2.ROTATE_180)

    return canvas


def _four_point_warp(img_bgr: np.ndarray, pts: np.ndarray, target_h: int = 896, target_w: int = 640) -> Optional[np.ndarray]:
    """
    Given 4 points in image space (arbitrary order), do a perspective warp to the target size.
    """
    def _order_points_local(pts4):
        rect = np.zeros((4, 2), dtype="float32")
        s = pts4.sum(axis=1)
        rect[0] = pts4[np.argmin(s)]            # top-left
        rect[2] = pts4[np.argmax(s)]            # bottom-right
        diff = np.diff(pts4, axis=1)
        rect[1] = pts4[np.argmin(diff)]         # top-right
        rect[3] = pts4[np.argmax(diff)]         # bottom-left
        return rect

    if pts is None or len(pts) != 4:
        return None

    rect = _order_points_local(pts.astype("float32"))
    dst = np.array(
        [[0, 0], [target_w - 1, 0], [target_w - 1, target_h - 1], [0, target_h - 1]],
        dtype="float32"
    )
    M = cv2.getPerspectiveTransform(rect, dst)
    warp = cv2.warpPerspective(img_bgr, M, (target_w, target_h))
    return warp


def _warp_card(img_bgr, target_h=896, target_w=640):
    """
    Try hard to find a quadrilateral card; if we can't find an exact 4-pt contour,
    fall back to the minAreaRect box (4 points). If that still fails, return None.
    """
    try:
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    except Exception:
        return None

    gray_blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray_blur, 30, 100)
    thr = cv2.adaptiveThreshold(gray_blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                cv2.THRESH_BINARY_INV, 31, 5)
    combo = cv2.bitwise_or(edges, thr)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    combo = cv2.morphologyEx(combo, cv2.MORPH_CLOSE, kernel, iterations=2)

    cnts, _ = cv2.findContours(combo, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None

    cnt = max(cnts, key=cv2.contourArea)
    peri = cv2.arcLength(cnt, True)

    for eps in (0.02, 0.03, 0.04, 0.06):
        approx = cv2.approxPolyDP(cnt, eps * peri, True)
        if len(approx) == 4:
            pts = approx.reshape(4, 2).astype("float32")
            warp = _four_point_warp(img_bgr, pts, target_h=target_h, target_w=target_w)
            if warp is not None:
                return warp

    try:
        rect = cv2.minAreaRect(cnt)  # ((cx,cy),(w,h),angle)
        box = cv2.boxPoints(rect)    # 4 points
        warp = _four_point_warp(img_bgr, box, target_h=target_h, target_w=target_w)
        if warp is not None:
            return warp
    except Exception:
        pass

    return None


def _preprocess_card_to_data_url(path: Path) -> str:
    img_bgr = cv2.imread(str(path))
    if img_bgr is None:
        return _file_to_data_url(path)
    warped = _warp_card(img_bgr)
    if warped is None:
        warped = _fit_to_canvas(img_bgr)
    pil = Image.fromarray(cv2.cvtColor(warped, cv2.COLOR_BGR2RGB))
    return _to_data_url_from_pil(pil)


def _to_data_url_from_pil(img: Image.Image, mime="image/jpeg") -> str:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def _preprocess_card_to_np(path: Path) -> Optional[np.ndarray]:
    """
    Return a normalized front image (warped if possible; else letterboxed fallback)
    so downstream strips and OCR always have a stable 896x640 canvas.
    """
    img_bgr = cv2.imread(str(path))
    if img_bgr is None:
        return None
    warped = _warp_card(img_bgr)
    if warped is not None:
        return warped
    return _fit_to_canvas(img_bgr)

# =========================
# OCR-lite for set code & name (LLM)
# =========================
SET_CODE_PROMPT = (
    "You will see a cropped bottom border of a TCG card. "
    "Extract the SHORT printed set code near the set symbol/collector number. "
    "Examples: 'sv2a', 'TEF EN', 'PRE EN', 'SVI EN'. "
    "Return STRICT JSON ONLY with fields:\n"
    '{ "set_code": "string_or_empty", "language": "en|jp|unknown" }\n'
    "Rules:\n"
    "• Only letters/numbers/spaces in set_code (no punctuation), keep case as printed if Latin else lowercase.\n"
    "• If multiple strings present, choose the one that best matches a short set identifier (1–8 chars).\n"
    "• If unsure, set set_code=\"\" and language=\"unknown\"."
)

CARD_NAME_PROMPT = (
    "You will see a cropped top title bar of a TCG card. "
    "Extract the CARD NAME text only. Return STRICT JSON ONLY:\n"
    '{ "card_name": "string_or_empty" }'
)

def _crop_bottom_strip(img_bgr: Optional[np.ndarray], frac: float = 0.18) -> Optional[np.ndarray]:
    if img_bgr is None:
        return None
    h, w = img_bgr.shape[:2]
    strip_h = max(8, int(h * frac))
    y0 = max(0, h - strip_h)
    out = img_bgr[y0:h, 0:w].copy()
    _save_img_debug(out, "crop_bottom_strip.jpg")
    _debug(f"Crop bottom strip: shape={out.shape}")
    return out


def _crop_top_strip(img_bgr: Optional[np.ndarray], frac: float = 0.16) -> Optional[np.ndarray]:
    if img_bgr is None:
        return None
    h, w = img_bgr.shape[:2]
    strip_h = max(8, int(h * frac))
    out = img_bgr[0:strip_h, 0:w].copy()
    _save_img_debug(out, "crop_top_strip.jpg")
    _debug(f"Crop top strip: shape={out.shape}")
    return out


def _extract_set_code_via_llm(img_bgr: Optional[np.ndarray]) -> Dict[str, str]:
    if img_bgr is None:
        return {"set_code": "", "language": "unknown"}
    strip = _crop_bottom_strip(img_bgr, 0.18)
    if strip is None:
        return {"set_code": "", "language": "unknown"}
    strip_url = _bgr_to_data_url(strip, quality=95)
    try:
        _debug(f"LLM OCR set_code: model={OPENAI_MODEL_CLASS}")
        resp = client.chat.completions.create(
            model=OPENAI_MODEL_CLASS,
            temperature=0.0,
            messages=[
                {"role": "system", "content": SET_CODE_PROMPT},
                {"role": "user", "content": [
                    {"type": "text", "text": "Read the set code from this bottom strip."},
                    {"type": "image_url", "image_url": {"url": strip_url}}
                ]},
            ],
        )
        raw = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        _debug("LLM OCR set_code: exception → " + str(e))
        _debug(traceback.format_exc())
        return {"set_code": "", "language": "unknown"}

    _save_text_debug(raw, "llm_ocr_set_code_raw.txt")
    s, e = raw.find("{"), raw.rfind("}")
    if s != -1 and e != -1 and e > s:
        raw = raw[s:e + 1]
    try:
        data = json.loads(raw)
    except Exception:
        _debug("LLM OCR set_code: JSON parse failed; raw clipped text saved.")
        data = {}
    code = str(data.get("set_code") or "").strip()
    lang = str(data.get("language") or "unknown").strip().lower()
    code = code.replace(".", " ").replace("-", " ").strip()
    code = " ".join(code.split())
    parsed = {"set_code": code, "language": lang if lang in {"en", "jp"} else "unknown"}
    _save_json_debug(parsed, "llm_ocr_set_code_parsed.json")
    return parsed


def _extract_card_name_via_llm(img_bgr: Optional[np.ndarray]) -> str:
    if img_bgr is None:
        return ""
    strip = _crop_top_strip(img_bgr, 0.16)
    if strip is None:
        return ""
    strip_url = _bgr_to_data_url(strip, quality=95)
    try:
        _debug(f"LLM OCR card_name: model={OPENAI_MODEL_CLASS}")
        resp = client.chat.completions.create(
            model=OPENAI_MODEL_CLASS,
            temperature=0.0,
            messages=[
                {"role": "system", "content": CARD_NAME_PROMPT},
                {"role": "user", "content": [
                    {"type": "text", "text": "Read the card name from this top bar."},
                    {"type": "image_url", "image_url": {"url": strip_url}}
                ]},
            ],
        )
        raw = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        _debug("LLM OCR card_name: exception → " + str(e))
        _debug(traceback.format_exc())
        return ""

    _save_text_debug(raw, "llm_ocr_card_name_raw.txt")
    s, e = raw.find("{"), raw.rfind("}")
    if s != -1 and e != -1 and e > s:
        raw = raw[s:e + 1]
    try:
        data = json.loads(raw)
    except Exception:
        _debug("LLM OCR card_name: JSON parse failed; raw clipped text saved.")
        data = {}
    card_name = str(data.get("card_name") or "").strip()
    _save_json_debug({"card_name": card_name}, "llm_ocr_card_name_parsed.json")
    return card_name

# =========================
# Stage 1: gating / classification
# =========================
CLASSIFY_PROMPT = (
    "You are a strict intake checker for TCG card photos.\n"
    "You will receive two images. For each image, decide if it shows a card FRONT or card BACK.\n"
    "Rules of thumb for Pokémon: backs are the blue design with the Poké Ball and 'Pokémon' logo; "
    "fronts show the card artwork, text boxes, set symbol/number, etc.\n"
    "Rules of thumb for One Piece: backs have a compass emblem and 'ONE PIECE CARD GAME' text, usually on a blue (sometimes white/red) field.\n"
    "Rules of thumb for Magic: The Gathering: backs are brown/sepia with five mana orbs and 'Magic: The Gathering'.\n"
    "Also rate overall photo quality as 'low'|'medium'|'high'.\n"
    "Return STRICT JSON ONLY:\n"
    "{\n"
    '  "detected_sides": {"image_1":"front|back|unknown", "image_2":"front|back|unknown"},\n'
    '  "image_quality": "low|medium|high"\n'
    "}\n"
)

def _classify_images(img1: Path, img2: Optional[Path]) -> Dict[str, Any]:
    content = [{"type": "text", "text": "Classify these two images (order matters)."}]
    content.append(_img_part(img1))
    if img2:
        content.append(_img_part(img2))
    else:
        content.append({"type": "text", "text": "Second image is missing."})

    try:
        _debug(f"Classifier call: model={OPENAI_MODEL_CLASS}")
        resp = client.chat.completions.create(
            model=OPENAI_MODEL_CLASS,
            temperature=0.0,
            messages=[
                {"role": "system", "content": CLASSIFY_PROMPT},
                {"role": "user", "content": content},
            ],
        )
        raw = (resp.choices[0].message.content or "{}").strip()
    except Exception as e:
        _debug("Classifier exception: " + str(e))
        _debug(traceback.format_exc())
        raw = "{}"

    _save_text_debug(raw, "classifier_raw.txt")
    try:
        data = json.loads(raw)
    except Exception:
        s, e = raw.find("{"), raw.rfind("}")
        data = json.loads(raw[s:e + 1]) if s != -1 and e != -1 and e > s else {}
    ds = data.get("detected_sides") or {}
    data["detected_sides"] = {
        "image_1": str(ds.get("image_1", "unknown")),
        "image_2": str(ds.get("image_2", "unknown")),
    }
    data["image_quality"] = (data.get("image_quality") or "low").lower()
    _save_json_debug(data, "classifier_parsed.json")
    return data

# =========================
# Stage 2: grading prompts
# =========================
GRADE_PROMPT_GENERIC = (
    "You are a meticulous pre-grader for TCG cards using a PSA-like 1..10 scale (10=Gem Mint).\n"
    "You will receive FRONT then BACK images of the same card. Do not deduct unless you can name at least one "
    "concrete, visible observation.\n"
    "\n"
    "SEVERITY & HARD CAPS (must obey):\n"
    "• Any writing/ink/marker/scribble/crayon or foreign substance on the card surface ⇒ cap overall grade at 3 (Good) "
    "  and include the qualifier 'MK (marked)' in the predicted_label.\n"
    "• Any crease/bend/tear/paper loss ⇒ cap overall grade at 4 (VG-EX) or lower depending on severity.\n"
    "• Obvious edge whitening or chipped corners on multiple edges ⇒ typical cap around 6–7.\n"
    "• Grades 9–10 require NO obvious defects: only microscopic corner touches or trivial print lines are allowed; "
    "  if you see any visible wear, do not exceed 8.\n"
    "\n"
    "PROCESS (mandatory):\n"
    "• Split each image into a 5×5 grid; scan top→bottom, left→right.\n"
    "• Centering: estimate border thickness on all four sides—front weighted more, back too; report off-center directions.\n"
    "• Surface: look for print lines, scratches, stains, dents/dimples, ink/writing/marks, creases; distinguish true defects from glare.\n"
    "• Edges: zoom along all edges for whitening/chips; avoid confusing holo sparkles with wear.\n"
    "• Corners: zoom on all four corners for rounding, fray, whitening.\n"
    "• Color: check fading/yellowing/oversaturation/uneven tones.\n"
    "• If anything prevents accurate grading (blurry, glare, crop, two fronts/two backs), set needs_better_photos=true and "
    "  return zeroes for scores with clear photo_feedback.\n"
    "\n"
    "OUTPUT STRICT JSON ONLY:\n"
    "{\n"
    '  "scores": {"centering": number, "surface": number, "edges": number, "corners": number, "color": number},\n'
    '  "predicted_grade": number,\n'
    '  "predicted_label": string,\n'
    '  "needs_better_photos": boolean,\n'
    '  "photo_feedback": string,\n'
    '  "observations": [\n'
    '    {"category":"centering|surface|edges|corners|color","side":"front|back","note":"short detail","box":[x0,y0,x1,y1]}\n'
    "  ],\n"
    '  "summary": string\n'
    "}\n"
)

def _build_game_prompt(game: Optional[str]) -> str:
    g = (game or "").lower()
    if g not in GAME_LABELS:
        return GRADE_PROMPT_GENERIC
    return (
        f"You are a meticulous pre-grader for {GAME_LABELS[g]} TCG cards (PSA-like 1..10; 10=Gem Mint).\n"
        f"{GAME_BACK_RULES.get(g, '')}\n"
        "You will receive FRONT then BACK images of the same card. Do not deduct unless you can name at least one concrete, "
        "visible observation.\n"
        "SEVERITY & HARD CAPS (must obey):\n"
        "• Any writing/ink/marker/scribble/crayon or foreign substance on the card surface ⇒ cap overall grade at 3 (Good) "
        "  and include the qualifier 'MK (marked)'.\n"
        "• Any crease/bend/tear/paper loss ⇒ cap overall grade at 4 (VG-EX) or lower depending on severity.\n"
        "• Obvious edge whitening or chipped corners on multiple edges ⇒ typical cap around 6–7.\n"
        "• Grades 9–10 require NO obvious defects: only microscopic corner touches or trivial print lines are allowed; "
        "  if you see any visible wear, do not exceed 8.\n"
        "\n"
        "PROCESS (mandatory):\n"
        "• Split each image into a 5×5 grid; scan top→bottom, left→right.\n"
        "• Centering: estimate border thickness on all four sides—front weighted more, back too; report off-center directions.\n"
        "• Surface: look for print lines, scratches, stains, dents/dimples, ink/writing/marks, creases. IMPORTANT: Do NOT count factory texture on modern full-art/illustration/TERA/ex cards (SV era) as damage. Holo sparkle, parallel foil patterns, and embossed/etched texture lines are normal. Only deduct for defects that break the foil/ink in a non-uniform way (random directions, clusters, crossing the artwork), not uniform texture. Distinguish glare/reflections from actual scratches; if uncertain, prefer “no deduction” and ask for better photos. \n"
        "• Edges: zoom along all edges for whitening/chips; avoid confusing holo sparkles with wear.\n"
        "• Corners: zoom on all four corners for rounding, fray, whitening.\n"
        "• Color: check fading/yellowing/oversaturation/uneven tones.\n"
        "• If anything prevents accurate grading (blurry, glare, crop, two fronts/two backs), set needs_better_photos=true and "
        "  return zeroes for scores with clear photo_feedback.\n"
        "\n"
        "OUTPUT STRICT JSON ONLY:\n"
        "{\n"
        '  "scores": {"centering": number, "surface": number, "edges": number, "corners": number, "color": number},\n'
        '  "predicted_grade": number,\n'
        '  "predicted_label": string,\n'
        '  "needs_better_photos": boolean,\n'
        '  "photo_feedback": string,\n'
        '  "observations": [\n'
        '    {"category":"centering|surface|edges|corners|color","side":"front|back","note":"short detail","box":[x0,y0,x1,y1]}\n'
        "  ],\n"
        '  "summary": string\n'
        "}\n"
    )

# =========================
# Exemplar fetch (always try)
# =========================
def _best_exemplar_from_cache(card_name: str,
                              set_info: Dict[str, Any],
                              number_hint: str = "") -> Dict[str, str]:
    """
    Return {"card_large_url": "...", "set_logo_url": "...", "set_symbol_url": "..."}.
    Tries multiple strategies against pokemon_cache. Safe if functions are missing.
    """
    out = {
        "card_large_url": "",
        "set_logo_url": set_info.get("set_logo_url", ""),
        "set_symbol_url": set_info.get("set_symbol_url", "")
    }

    def _prefer(bigger: str, current: str) -> str:
        return bigger or current

    sid = (set_info.get("set_id") or "").strip()
    if sid and card_name:
        try:
            hit = pokemon_cache.get_card_in_set(sid, number_hint or card_name)
        except Exception:
            hit = None
        if hit:
            imgs = hit.get("images") or {}
            out["card_large_url"] = imgs.get("large", "") or imgs.get("small", "") or out["card_large_url"]
            return out

    ptcgo = (set_info.get("ptcgoCode") or "").strip()
    if (not sid) and ptcgo:
        try:
            sh = pokemon_cache.get_set_by_code(ptcgo) or {}
        except Exception:
            sh = {}
        if sh:
            sid = sh.get("id", "")
            simgs = (sh.get("images") or {})
            out["set_logo_url"] = _prefer(simgs.get("logo", ""), out["set_logo_url"])
            out["set_symbol_url"] = _prefer(simgs.get("symbol", ""), out["set_symbol_url"])
            if sid and card_name:
                try:
                    hit = pokemon_cache.get_card_in_set(sid, number_hint or card_name)
                except Exception:
                    hit = None
                if hit:
                    imgs = hit.get("images") or {}
                    out["card_large_url"] = imgs.get("large", "") or imgs.get("small", "") or out["card_large_url"]
                    return out

    # Name-only fallback (only if helper exists)
    if card_name and hasattr(pokemon_cache, "search_card_by_name"):
        try:
            hit = pokemon_cache.search_card_by_name(card_name)  # expected to return best match dict or None
        except Exception:
            hit = None
        if hit:
            imgs = hit.get("images") or {}
            out["card_large_url"] = imgs.get("large", "") or imgs.get("small", "") or out["card_large_url"]

    return out

# =========================
# Main entry
# =========================
def grade_with_openai(front_path: Path,
                      back_path: Optional[Path] = None,
                      game_hint: Optional[str] = None,
                      ptcgo_code: Optional[str] = None,
                      collector_number: Optional[str] = None) -> Dict[str, Any]:

    """Gate + crop + LLM grade (+ optional CV blend + set code/symbol + exemplar)."""

    _debug(f"grade_with_openai start | front={front_path} back={back_path} game_hint={game_hint}")
    _debug(f"Models | CLASS={OPENAI_MODEL_CLASS} GRADE={OPENAI_MODEL_GRADE}")

    # 1) Gate: sides & quality
    gate = _classify_images(front_path, back_path)
    sides = gate.get("detected_sides", {})
    q = (gate.get("image_quality") or "low").lower()
    _save_json_debug({"gate": gate}, "gate_output.json")

    # Enforce order
    if REQUIRE_FRONT_FIRST:
        if sides.get("image_1") != "front" or sides.get("image_2") != "back":
            _debug(f"Gating failed: require_front_first={REQUIRE_FRONT_FIRST} sides={sides}")
            return _json_sanitize({
                "scores": {"centering": 0.0, "surface": 0.0, "edges": 0.0, "corners": 0.0, "color": 0.0},
                "predicted_grade": 0.0,
                "predicted_label": "—",
                "needs_better_photos": True,
                "photo_feedback": "Upload the FRONT image first and the BACK image second.",
                "summary": "",
                "debug": gate if DEBUG else {},
            })
    else:
        pair = {sides.get("image_1"), sides.get("image_2")}
        if not ("front" in pair and "back" in pair):
            _debug(f"Gating failed: need exactly one front and one back. sides={sides}")
            return _json_sanitize({
                "scores": {"centering": 0.0, "surface": 0.0, "edges": 0.0, "corners": 0.0, "color": 0.0},
                "predicted_grade": 0.0,
                "predicted_label": "—",
                "needs_better_photos": True,
                "photo_feedback": "Please upload exactly one FRONT and one BACK image.",
                "summary": "",
                "debug": gate if DEBUG else {},
            })
        if sides.get("image_1") == "back" and sides.get("image_2") == "front":
            _debug("Order swap: received back then front; swapping.")
            front_path, back_path = back_path, front_path

    if q not in {"medium", "high"}:
        _debug(f"Gate image_quality={q} (too low).")
        return _json_sanitize({
            "scores": {"centering": 0.0, "surface": 0.0, "edges": 0.0, "corners": 0.0, "color": 0.0},
            "predicted_grade": 0.0,
            "predicted_label": "—",
            "needs_better_photos": True,
            "photo_feedback": "Photo quality is too low (blur, glare or cropping).",
            "summary": "",
            "debug": gate if DEBUG else {},
        })

    # 2) Preprocess → data URLs and warped np
    f_url = _preprocess_card_to_data_url(front_path)
    b_url = _preprocess_card_to_data_url(back_path) if back_path else None
    front_warp_bgr = _preprocess_card_to_np(front_path)
    _debug(f"Preprocess done: data URLs made; front_warp_bgr is None? {front_warp_bgr is None}")
    # --- NEW: if user supplied ptcgo_code + collector_number, trust and resolve via API/cache
    trusted_set_info = {}
    trusted_card_info = {}
    ptcgo_code = (ptcgo_code or "").strip().upper()
    collector_number = (collector_number or "").strip()

    s_hit = None

    if ptcgo_code and collector_number:
        try:
            s_hit = pokemon_cache.get_set_by_code(ptcgo_code)  # the wrapper around PTCG
        except Exception:
            s_hit = None
        if s_hit:
            simgs = _coerce_set_images(
                s_hit.get("images") if isinstance(s_hit, dict) else getattr(s_hit, "images", {})
            )

            trusted_set_info = {
                "set_name":     (s_hit.get("name") if isinstance(s_hit, dict) else getattr(s_hit, "name", "")) or "",
                "ptcgoCode":    (s_hit.get("ptcgoCode") if isinstance(s_hit, dict) else getattr(s_hit, "ptcgoCode", "")) or "",
                "set_id":       (s_hit.get("id") if isinstance(s_hit, dict) else getattr(s_hit, "id", "")) or "",
                "set_logo_url":   simgs.get("logo", ""),
                "set_symbol_url": simgs.get("symbol", "")
            }
            try:
                # prefer exact collector number match first; fallback to name search (inside helper)
                c_hit = pokemon_cache.get_card_in_set(trusted_set_info["set_id"], collector_number) or \
                        pokemon_cache.get_card_in_set(trusted_set_info["set_id"], collector_number.split("/")[0])
            except Exception:
                c_hit = None
            if c_hit:
                cimgs = _coerce_card_images((c_hit.get("images") if isinstance(c_hit, dict) else None))
                trusted_card_info = {
                    "card_name": c_hit.get("name", ""),
                    "number": c_hit.get("number", ""),
                    "rarity": c_hit.get("rarity", ""),
                    "subtypes": c_hit.get("subtypes", []) or [],
                    "supertype": c_hit.get("supertype", ""),
                    "types": c_hit.get("types", []) or [],
                    "regulationMark": c_hit.get("regulationMark", ""),
                    "card_large_url": cimgs.get("large", "") or cimgs.get("small", ""),
                }

        _save_json_debug({"trusted_set": trusted_set_info, "trusted_card": trusted_card_info}, "trusted_hints.json")

    # 2b) OCR: set code & card name from warped front
    set_code_info = {"set_code": "", "language": "unknown"}
    set_code_txt = ""
    set_lang_txt = "unknown"
    card_name = ""

    if not (ptcgo_code and collector_number and trusted_set_info and trusted_card_info):
        # Fall back to OCR discovery
        set_code_info = _extract_set_code_via_llm(front_warp_bgr)
        set_code_txt = set_code_info.get("set_code", "")
        set_lang_txt = set_code_info.get("language", "unknown")
        card_name = _extract_card_name_via_llm(front_warp_bgr)
    else:
        # Take the trusted values
        set_code_txt = trusted_set_info.get("ptcgoCode", ptcgo_code)
        card_name = trusted_card_info.get("card_name", "")

    _save_json_debug({"set_code_info": set_code_info, "card_name": card_name}, "ocr_meta.json")



    # Always try emblem detection; merge if it adds useful info
    # Start with trusted info if available
    set_info = {}
    
    if trusted_set_info or trusted_card_info:
        set_info = {
            "set_name": trusted_set_info.get("set_name", ""),
            "ptcgoCode": trusted_set_info.get("ptcgoCode", ptcgo_code),
            "set_id": trusted_set_info.get("set_id", ""),
            "set_logo_url":  trusted_set_info.get("set_logo_url", ""),
            "set_symbol_url": trusted_set_info.get("set_symbol_url", ""),
            "card_large_url": trusted_card_info.get("card_large_url", ""),
            "rarity": trusted_card_info.get("rarity", ""),
            "subtypes": trusted_card_info.get("subtypes", []),
            "supertype": trusted_card_info.get("supertype", ""),
            "types": trusted_card_info.get("types", []),
            "regulationMark": trusted_card_info.get("regulationMark", ""),
            "number": trusted_card_info.get("number", collector_number),
            "card_name": trusted_card_info.get("card_name", card_name),
            "language": set_lang_txt,
        }

    # If still empty (user didn’t supply hints), proceed with your previous code-based resolve
    if not set_info:
        set_info = _resolve_set_info(set_code_txt, set_lang_txt) if set_code_txt else {}
        _save_json_debug({"set_info_initial": set_info}, "set_info_initial.json")

        # emblem detection as a fallback enrichment
        sym_key, sym_score = (None, 0.0)
        if front_warp_bgr is not None:
            sym_key, sym_score = _detect_set_symbol_key(front_warp_bgr)
        _debug(f"Symbol detection: key={sym_key} score={sym_score}")
        if sym_key:
            sym_info = _resolve_from_symbol(sym_key) or {}
            if isinstance(sym_info, dict):
                merged = dict(set_info)
                for k in ["set_name", "era", "border"]:
                    if not merged.get(k) and sym_info.get(k):
                        merged[k] = sym_info.get(k)
                merged["symbol_key"] = sym_key
                merged["symbol_score"] = float(sym_score)
                set_info = merged

        if not set_info:
            set_info = {"set_name": "", "era": "", "border": "", "style_flags": [],
                        "set_code": set_code_txt, "language": set_lang_txt}

    _save_json_debug({"set_info_after_symbol": set_info}, "set_info_after_symbol.json")




    ptcgo = _ptcgo_from_code(set_code_txt)
    _debug(f"PTCGO derived from OCR: '{ptcgo}' from '{set_code_txt}'")
    if ptcgo:
        s_hit = pokemon_cache.get_set_by_code(ptcgo)
        _save_json_debug({"ptcgo_set_hit": s_hit}, "ptcgo_set_hit.json")
        if s_hit:
            set_info.setdefault("set_name", s_hit.get("name", ""))
            set_info["ptcgoCode"] = s_hit.get("ptcgoCode", "")
            set_info["set_id"] = s_hit.get("id", "")
            imgs = _coerce_set_images((s_hit.get("images") if isinstance(s_hit, dict) else None))
            set_info["set_logo_url"]   = imgs.get("logo",   "")

            set_info["set_symbol_url"] = imgs.get("symbol", "")
            # Try exemplar by name/number
            c_hit = pokemon_cache.get_card_in_set(set_info["set_id"], card_name)
            _save_json_debug({"ptcgo_card_hit": c_hit}, "ptcgo_card_hit.json")
            if c_hit:
                set_info["rarity"] = c_hit.get("rarity", "")
                set_info["subtypes"] = c_hit.get("subtypes", [])
                set_info["supertype"] = c_hit.get("supertype", "")
                set_info["types"] = c_hit.get("types", [])
                set_info["regulationMark"] = c_hit.get("regulationMark", "")
                cimgs = _coerce_card_images((c_hit.get("images") if isinstance(c_hit, dict) else None))

                set_info["card_large_url"] = cimgs.get("large", "") or cimgs.get("small","")

    set_info["card_name"] = card_name
    _save_json_debug({"set_info_final": set_info}, "set_info_final.json")

    # 2c) ALWAYS try to attach an exemplar (or at least set art)
    ex = _best_exemplar_from_cache(card_name, set_info, number_hint=set_info.get("number", ""))
    set_info["card_large_url"] = set_info.get("card_large_url") or ex["card_large_url"]
    set_info["set_logo_url"] = set_info.get("set_logo_url") or ex["set_logo_url"]
    set_info["set_symbol_url"] = set_info.get("set_symbol_url") or ex["set_symbol_url"]

    # 3) Choose prompt
    system_prompt = _build_game_prompt((game_hint or "").lower())
    game_label = GAME_LABELS.get((game_hint or "").lower(), "TCG")
    _save_text_debug(system_prompt, "system_prompt.txt")

    # 3b) Vision checks (front only here)
    cv_flags = {}
    try:
        raw_flags = run_vision_checks_img(front_warp_bgr) if front_warp_bgr is not None else {}
        cv_flags = _json_sanitize(raw_flags)
    except Exception:
        _debug("Vision checks threw an exception:\n" + traceback.format_exc())
        cv_flags = {}
    _save_json_debug({"cv_flags": cv_flags}, "cv_flags.json")

    # 4) LLM grade (pass hints + references)
    hint_parts = []
    if set_info.get("set_name"):  hint_parts.append(f"set:{set_info['set_name']}")
    if set_info.get("era"):       hint_parts.append(f"era:{set_info['era']}")
    if set_info.get("border"):    hint_parts.append(f"border:{set_info['border']}")
    if set_info.get("ptcgoCode"): hint_parts.append(f"ptcgo:{set_info['ptcgoCode']}")
    if set_info.get("rarity"):    hint_parts.append(f"rarity:{set_info['rarity']}")
    if set_info.get("card_name"): hint_parts.append(f'card:"{set_info["card_name"]}"')
    if cv_flags.get("centering"): hint_parts.append(f'centering_est:{cv_flags.get("centering")}')
    hint = " | " + " | ".join(hint_parts) if hint_parts else ""

    content = [{"type": "text", "text": f"FRONT then BACK of the same {game_label} card — grade per instructions.{hint}"}]
    content.append(_img_part_from_data_url(f_url))
    if b_url:
        content.append(_img_part_from_data_url(b_url))

    # Always attach some reference
    attached_ref = False
    if set_info.get("card_large_url"):
        content.append({"type": "text", "text": "Reference exemplar (database mint baseline):"})
        content.append({"type": "image_url", "image_url": {"url": set_info["card_large_url"]}})
        attached_ref = True
    else:
        # weaker but helpful: set logo/symbol
        logo = set_info.get("set_logo_url")
        symb = set_info.get("set_symbol_url")
        if logo or symb:
            content.append({"type": "text", "text": "Set reference (logo/symbol):"})
            if logo:
                content.append({"type": "image_url", "image_url": {"url": logo}})
            if symb:
                content.append({"type": "image_url", "image_url": {"url": symb}})
            attached_ref = True

    if attached_ref:
        _debug("Attached reference imagery to grader content.")
        _save_json_debug({"reference_attached": True}, "reference_attached.json")

    _save_json_debug({"user_content": content}, "grade_user_content.json")

    try:
        _debug(f"Grader call: model={OPENAI_MODEL_GRADE}")
        resp = client.chat_completions.create(  # alias-safe
            model=OPENAI_MODEL_GRADE,
            temperature=0.2,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
        ) if hasattr(client, "chat_completions") else client.chat.completions.create(
            model=OPENAI_MODEL_GRADE,
            temperature=0.2,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
        )
        raw = (resp.choices[0].message.content or "{}").strip()
    except Exception as e:
        _debug("Grader exception: " + str(e))
        _debug(traceback.format_exc())
        raw = "{}"

    _save_text_debug(raw, "grader_raw.txt")

    # Parse LLM
    try:
        data = json.loads(raw)
    except Exception:
        s, e = raw.find("{"), raw.rfind("}")
        data = json.loads(raw[s:e + 1]) if s != -1 and e != -1 and e > s else {}
    _save_json_debug({"grader_parsed": data}, "grader_parsed.json")  

    result = _normalize_grade_json(data)
    result = _enforce_observation_guard(result)
    result = _apply_observation_thresholds(result)
    result = _apply_sanity_caps(result)
    # If the LLM gave < 7 and provided < 2 concrete observations, lift to 7.5
    if (result.get("predicted_grade", 0) < 7.0) and len(result.get("observations") or []) < 2 and not result.get("needs_better_photos"):
        result["predicted_grade"] = 7.5
        # keep sub-scores consistent-ish
        for k in ("centering","surface","edges","corners","color"):
            result["scores"][k] = max(result["scores"].get(k, 7.5), 7.0)


    # === CV HARD/SOFT RULES (ink/scribble/glare/blur on FRONT) ===
    scrib = bool(cv_flags.get("scribble"))
    scrib_conf = float(cv_flags.get("scribble_conf", 0.0))

    if scrib and scrib_conf >= 0.88:
        result["scores"]["surface"] = min(result["scores"].get("surface", 10.0), 2.0)
        result["predicted_grade"] = min(result.get("predicted_grade", 10.0), 3.0)
        obs = result.get("observations") or []
        obs.append({
            "category": "surface", "side": "front",
            "note": "Detected pen/marker (high confidence CV).", "box": [0, 0, 1, 1]
        })
        result["observations"] = obs
    elif scrib and scrib_conf >= 0.55:
        result["scores"]["surface"] = max(0.0, result["scores"].get("surface", 10.0) - 1.0)
        obs = result.get("observations") or []
        obs.append({
            "category": "surface", "side": "front",
            "note": "Possible pen/marker (medium confidence CV).", "box": [0, 0, 1, 1]
        })
        result["observations"] = obs

    if cv_flags.get("glare"):
        fb = result.get("photo_feedback") or ""
        result["photo_feedback"] = (fb + " Glare detected; results may be conservative.").strip()

    if cv_flags.get("blur"):
        fb = result.get("photo_feedback") or ""
        result["photo_feedback"] = (fb + " Blur detected; results may be conservative.").strip()

    # 5) Optional CV blend (classical model)
    if BLEND_CV_ALPHA > 0.0 and os.path.exists(CV_WEIGHTS) and back_path:
        try:
            from grading.ml.cv_inference import CVGrader
            cv = CVGrader(weights_path=CV_WEIGHTS)
            cv_pred = cv.predict(front_path, back_path)  # dict with keys: centering,...,overall
            a = float(BLEND_CV_ALPHA)
            for k in ["centering", "surface", "edges", "corners", "color"]:
                result["scores"][k] = (1 - a) * result["scores"][k] + a * cv_pred.get(k, 0.0)
            result["predicted_grade"] = (1 - a) * result["predicted_grade"] + a * cv_pred.get("overall", 0.0)
            _save_json_debug({"cv_pred": cv_pred, "alpha": a}, "cv_blend.json")
        except Exception:
            _debug("CV blend failed; continuing LLM-only.\n" + traceback.format_exc())

    # 6) Attach detected metadata and make label/summary deterministic
    result["detected"] = {
        "set_code": set_info.get("set_code", set_code_txt),
        "set_name": set_info.get("set_name", ""),
        "era": set_info.get("era", ""),
        "border": set_info.get("border", ""),
        "language": set_info.get("language", set_lang_txt or "unknown"),
        "card_name": card_name or "",
        "style_flags": list(set_info.get("style_flags", [])),
        "symbol_key": set_info.get("symbol_key", ""),
        "symbol_score": float(set_info.get("symbol_score", 0.0)),
        "ptcgoCode": set_info.get("ptcgoCode", ""),
        "set_id": set_info.get("set_id", ""),
        "set_logo_url": set_info.get("set_logo_url", ""),
        "set_symbol_url": set_info.get("set_symbol_url", ""),
        "card_large_url": set_info.get("card_large_url", ""),
        "rarity": set_info.get("rarity", ""),
        "subtypes": set_info.get("subtypes", []),
        "supertype": set_info.get("supertype", ""),
        "types": set_info.get("types", []),
        "regulationMark": set_info.get("regulationMark", ""),
    }
    result = _coerce_label_and_summary(result, cv_flags, result["detected"])

    # Embed debug blob if enabled (handy when surfacing to UI)
    if DEBUG:
        result["debug"] = {
            "gate": gate,
            "ocr": {"set_code_info": set_code_info, "card_name": card_name},
            "set_info": set_info,
            "cv_flags": cv_flags,
            "models": {"classifier": OPENAI_MODEL_CLASS, "grader": OPENAI_MODEL_GRADE},
            "hint_parts": hint_parts,
        }
    _save_json_debug({"final_result": result}, "final_result.json")
    _debug("grade_with_openai done.")
    return _json_sanitize(result)

# =========================
# Normalization helpers
# =========================
def _compose_summary_from_scores(scores: dict, flags: Optional[dict] = None, detected: Optional[dict] = None) -> str:
    flags = flags or {}
    cent   = float(scores.get("centering", 10))
    surf   = float(scores.get("surface",   10))
    edges  = float(scores.get("edges",     10))
    corners= float(scores.get("corners",   10))
    color  = float(scores.get("color",     10))

    notes = []

    # Centering
    if cent < 5.5:
        notes.append("noticeable off-centering")
    elif cent < 7.5:
        notes.append("slight off-centering")

    # Surface
    if flags.get("scribble") or surf < 3.5:
        notes.append("heavy surface damage")
    elif surf < 5.5:
        notes.append("moderate surface wear")
    elif surf < 7.5:
        notes.append("light surface wear")

    # Edges / corners
    if edges < 5.5:
        notes.append("edge wear")
    elif edges < 7.5:
        notes.append("slight edge wear")

    if corners < 5.5:
        notes.append("corner wear")
    elif corners < 7.5:
        notes.append("slight corner wear")

    # Color
    if color < 6.5:
        notes.append("color fading/discoloration")

    # Base sentence
    if not notes:
        text = "The card presents very well with minimal visible wear."
    else:
        text = "The card shows " + (notes[0] if len(notes) == 1 else (", ".join(notes[:-1]) + f", and {notes[-1]}."))
    # Photo warnings
    photo_notes = []
    if flags.get("glare"): photo_notes.append("glare")
    if flags.get("blur"):  photo_notes.append("blur")
    if photo_notes:
        text += f" Photo quality issue detected ({', '.join(photo_notes)}); result may be conservative."

    # Append detected metadata line
    if detected:
        cname = (detected.get("card_name") or "").strip()
        sname = (detected.get("set_name") or "").strip()
        scode = (detected.get("set_code") or "").strip()
        extra = []
        if cname: extra.append(cname)
        if sname: extra.append(sname)
        if scode: extra.append(scode)
        if extra:
            text += " Detected: " + " — ".join(extra) + "."

    return text


def _coerce_label_and_summary(result: dict, flags: Optional[dict] = None, detected: Optional[dict] = None) -> dict:
    grade = float(result.get("predicted_grade", 0))
    result["predicted_label"] = _psa_bucket_text(grade)
    result["summary"] = _compose_summary_from_scores(result.get("scores", {}), flags, detected)
    return result


def _normalize_grade_json(data: Dict[str, Any]) -> Dict[str, Any]:
    s = data.get("scores", {}) or {}
    return {
        "scores": {
            "centering": _safe_float(s.get("centering"), 0.0),
            "surface":   _safe_float(s.get("surface"), 0.0),
            "edges":     _safe_float(s.get("edges"), 0.0),
            "corners":   _safe_float(s.get("corners"), 0.0),
            "color":     _safe_float(s.get("color"), 0.0),
        },
        "predicted_grade": _safe_float(data.get("predicted_grade"), 0.0),
        "predicted_label": str(data.get("predicted_label") or "").strip(),
        "needs_better_photos": bool(data.get("needs_better_photos", False)),
        "photo_feedback": str(data.get("photo_feedback") or "").strip(),
        "observations": data.get("observations") or [],
        "summary": str(data.get("summary") or "").strip(),
    }


def _enforce_observation_guard(result: Dict[str, Any]) -> Dict[str, Any]:
    if result.get("needs_better_photos"):
        return result
    obs = result.get("observations") or []
    has_concrete = any(isinstance(o, dict) and "category" in o for o in obs)
    if not has_concrete:
        result["scores"] = {k: 10.0 for k in ["centering", "surface", "edges", "corners", "color"]}
        result["predicted_grade"] = 10.0
        if not result.get("predicted_label"):
            result["predicted_label"] = "PSA 10 (Gem Mint)"
    return result


def _apply_observation_thresholds(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Require stronger evidence to drop below 9.5:
    - At least 2 concrete observations, or
    - One high-impact note (crease/dent/deep scratch).
    """
    obs = [o for o in (result.get("observations") or []) if isinstance(o, dict)]
    high_impact = {"crease", "dent", "deep scratch"}
    notes = " ".join((o.get("note", "") or "").lower() for o in obs)
    has_high = any(word in notes for word in high_impact)
    if len(obs) < 2 and not has_high:
        for k in ["surface", "edges", "corners", "color"]:
            result["scores"][k] = max(result["scores"][k], 9.5)
        result["predicted_grade"] = max(result["predicted_grade"], 9.5)
    return result


def _psa_bucket_text(grade: float) -> str:
    g = int(round(max(1.0, min(10.0, float(grade or 0)))))
    short = {
        10: "GEM MT", 9: "MINT", 8: "NM-MT", 7: "NM",
        6: "EX-MT", 5: "EX", 4: "VG-EX", 3: "VG", 2: "GOOD", 1: "POOR"
    }[g]
    long = {
        10: "Gem Mint", 9: "Mint", 8: "Near Mint-Mint", 7: "Near Mint",
        6: "Excellent-Mint", 5: "Excellent", 4: "Very Good-Excellent",
        3: "Very Good", 2: "Good", 1: "Poor"
    }[g]
    return f"{short} ({long})"
