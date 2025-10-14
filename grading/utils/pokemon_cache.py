# grading/utils/pokemon_cache.py
import os, json
from pathlib import Path
from typing import Any, Dict, Optional
from pokemontcgsdk import Card as _PTCG_Card, Set as _PTCG_Set, RestClient as _PTCG_RestClient

POKEMONTCG_API_KEY = os.getenv("POKEMONTCG_IO_API_KEY", "").strip()
if POKEMONTCG_API_KEY:
    _PTCG_RestClient.configure(POKEMONTCG_API_KEY)

CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)
SET_CACHE_FILE = CACHE_DIR / "sets.json"
CARD_CACHE_FILE = CACHE_DIR / "cards.json"

_sets: Dict[str, Dict[str, Any]] = {}
_cards: Dict[str, Dict[str, Any]] = {}

def _load_cache():
    global _sets, _cards
    if SET_CACHE_FILE.exists():
        _sets.update(json.loads(SET_CACHE_FILE.read_text()))
    if CARD_CACHE_FILE.exists():
        _cards.update(json.loads(CARD_CACHE_FILE.read_text()))

def _save_cache():
    SET_CACHE_FILE.write_text(json.dumps(_sets, indent=2))
    CARD_CACHE_FILE.write_text(json.dumps(_cards, indent=2))

_load_cache()

def get_set_by_code(code: str) -> Optional[Dict[str, Any]]:
    """Look up set by ptcgoCode (e.g., TEF, SVI). Cache results."""
    code = (code or "").upper()
    if not code:
        return None
    if code in _sets:
        return _sets[code]
    try:
        sets = _PTCG_Set.where(q=f'ptcgoCode:{code}')
        if sets:
            s = sets[0]
            data = {
                "id": s.id,
                "name": s.name,
                "series": getattr(s, "series", ""),
                "releaseDate": getattr(s, "releaseDate", ""),
                "ptcgoCode": getattr(s, "ptcgoCode", ""),
                "images": getattr(s, "images", {}) or {},
            }
            _sets[code] = data
            _save_cache()
            return data
    except Exception:
        return None
    return None

def get_card_in_set(set_id: str, number_or_name: str) -> Optional[Dict[str, Any]]:
    """Look up a card by set.id and number (preferred) or name. Cache results."""
    key = f"{set_id}::{(number_or_name or '').lower()}"
    if key in _cards:
        return _cards[key]
    try:
        cards = []
        if number_or_name:
            cards = _PTCG_Card.where(q=f'set.id:{set_id} number:{number_or_name}')
            if not cards:
                cards = _PTCG_Card.where(q=f'set.id:{set_id} name:\"{number_or_name}\"')
        if cards:
            c = cards[0]
            data = {
                "id": c.id,
                "name": c.name,
                "number": getattr(c, "number", ""),
                "rarity": getattr(c, "rarity", ""),
                "subtypes": getattr(c, "subtypes", []) or [],
                "supertype": getattr(c, "supertype", ""),
                "types": getattr(c, "types", []) or [],
                "regulationMark": getattr(c, "regulationMark", ""),
                "images": getattr(c, "images", {}) or {},
            }
            _cards[key] = data
            _save_cache()
            return data
    except Exception:
        return None
    return None
