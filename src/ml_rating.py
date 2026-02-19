"""ML Rating module - Uses ONNX models to calculate synergy-based card ratings"""

import os
import sys
import logging
from typing import Dict, List, Optional
import numpy as np
import pandas as pd

try:
    import onnxruntime as ort
    ONNX_AVAILABLE = True
except ImportError:
    ONNX_AVAILABLE = False

logger = logging.getLogger(__name__)


def is_ml_rating_available() -> bool:
    """Check if ONNX runtime is available for ML rating calculations"""
    return ONNX_AVAILABLE


def _find_appdata_model_directory() -> str:
    """Find the AppData models directory with downloaded model updates."""
    from src.model_update import get_appdata_models_dir
    appdata_dir = get_appdata_models_dir()
    # Check that it actually contains model files
    onnx_dir = os.path.join(appdata_dir, "onnx")
    if os.path.isdir(onnx_dir) and any(f.endswith(".onnx") for f in os.listdir(onnx_dir)):
        return appdata_dir
    return ""


def _find_bundled_model_directory() -> str:
    """Find the bundled models/ directory next to the executable or script."""
    # PyInstaller: next to the exe
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidate = os.path.join(base, "models")
    if os.path.isdir(candidate):
        return candidate
    return ""


def find_best_model_directory() -> str:
    """Find the best available model directory.

    Priority:
    1. AppData downloaded models (if they exist)
    2. Bundled models (fallback)
    """
    appdata = _find_appdata_model_directory()
    if appdata:
        return appdata
    return _find_bundled_model_directory()


class MLModelManager:
    """Manages ONNX model loading and caching"""

    def __init__(self, model_directory: str = ""):
        self.model_directory = model_directory or find_best_model_directory()
        self._sessions: Dict[str, ort.InferenceSession] = {} if ONNX_AVAILABLE else {}
        self._cardnames: Dict[str, List[str]] = {}

    def set_model_directory(self, path: str):
        """Set the model directory and clear cached models"""
        self.model_directory = path
        self._sessions.clear()
        self._cardnames.clear()

    def get_model(self, set_code: str, mode: str = "Premier") -> Optional["ort.InferenceSession"]:
        """Load or retrieve cached ONNX model for a set/mode combination"""
        if not ONNX_AVAILABLE:
            return None

        cache_key = f"{set_code}_{mode}"
        if cache_key in self._sessions:
            return self._sessions[cache_key]

        # Try Premier first, then PickTwo as fallback
        modes_to_try = [mode, "PickTwo"] if mode == "Premier" else [mode]

        for try_mode in modes_to_try:
            model_path = os.path.join(self.model_directory, "onnx", f"{set_code}_{try_mode}.onnx")
            if os.path.exists(model_path):
                try:
                    session = ort.InferenceSession(model_path)
                    self._sessions[cache_key] = session
                    logger.info(f"Loaded ML model: {model_path}")
                    return session
                except Exception as e:
                    logger.error(f"Failed to load ONNX model {model_path}: {e}")
                    return None

        logger.warning(f"No ML model found for {set_code}")
        return None

    def get_cardnames(self, set_code: str) -> Optional[List[str]]:
        """Load card names list from CSV for a set"""
        if set_code in self._cardnames:
            return self._cardnames[set_code]

        csv_path = os.path.join(self.model_directory, "cards", f"{set_code}.csv")
        if not os.path.exists(csv_path):
            logger.warning(f"Card CSV not found: {csv_path}")
            return None

        try:
            df = pd.read_csv(csv_path)
            cardnames = df["name"].tolist()
            self._cardnames[set_code] = cardnames
            logger.info(f"Loaded {len(cardnames)} card names for {set_code}")
            return cardnames
        except Exception as e:
            logger.error(f"Failed to load card CSV {csv_path}: {e}")
            return None


class MLRatingCalculator:
    """Calculates ML-based card ratings using ONNX models"""

    def __init__(self, model_manager: MLModelManager):
        self.model_manager = model_manager
        self._current_ratings: Dict[str, float] = {}
        self._current_set: str = ""
        self._current_mode: str = ""

    def compute_ratings(self, pool_names: List[str], set_code: str, mode: str = "Premier") -> Dict[str, float]:
        """
        Compute ML ratings for all cards based on the current pool.

        Args:
            pool_names: List of card names in the current pool (cards already drafted)
            set_code: The set code (e.g., "DSK", "FDN")
            mode: Draft mode ("Premier" or "PickTwo")

        Returns:
            Dictionary mapping card names to ratings (0-100 scale)
        """
        if not ONNX_AVAILABLE:
            return {}

        session = self.model_manager.get_model(set_code, mode)
        if session is None:
            return {}

        cardnames = self.model_manager.get_cardnames(set_code)
        if cardnames is None:
            return {}

        try:
            # Build collection vector from pool
            collection_vector = np.zeros((1, len(cardnames)), dtype=np.float32)
            for name in pool_names:
                if name in cardnames:
                    idx = cardnames.index(name)
                    collection_vector[0, idx] += 1

            # Create pack vector (all ones - consider all cards)
            pack_vector = np.ones((1, len(cardnames)), dtype=np.float32)

            # Run ONNX inference
            input_names = [inp.name for inp in session.get_inputs()]
            outputs = session.run(None, {
                input_names[0]: collection_vector,
                input_names[1]: pack_vector
            })

            # Get raw scores
            raw_scores = outputs[0].flatten()

            # Apply sigmoid normalization to 0-100 scale
            # Same formula as draftassistant.py
            mean = np.mean(raw_scores)
            std = np.std(raw_scores)
            if std > 0:
                ratings = 100 / (1 + np.exp(-1.2 * (raw_scores - mean) / std))
            else:
                ratings = np.full_like(raw_scores, 50.0)

            # Build result dictionary
            self._current_ratings = {
                name: round(float(ratings[i]), 1)
                for i, name in enumerate(cardnames)
            }
            self._current_set = set_code
            self._current_mode = mode

            return self._current_ratings

        except Exception as e:
            logger.error(f"ML rating computation failed: {e}")
            return {}

    def get_rating(self, card_name: str) -> Optional[float]:
        """Get the ML rating for a specific card"""
        return self._current_ratings.get(card_name)

    def has_ratings(self) -> bool:
        """Check if ratings have been computed"""
        return len(self._current_ratings) > 0

    def clear_ratings(self):
        """Clear cached ratings"""
        self._current_ratings.clear()
        self._current_set = ""
        self._current_mode = ""
