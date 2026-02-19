"""Model update module - checks for and downloads ML model updates from GitHub Releases."""

import json
import os
import shutil
import ssl
import sys
import tempfile
import urllib.request
import zipfile
from src.logger import create_logger

logger = create_logger()

MODELS_RELEASE_URL = (
    "https://api.github.com/repos/im20a/statistical-drafting/releases/latest"
)


def get_appdata_models_dir() -> str:
    """Return the platform-specific AppData directory for downloaded models."""
    app_name = "MTGA_Draft_Tool"
    if sys.platform == "win32":
        base_path = os.getenv("APPDATA")
    elif sys.platform == "darwin":
        base_path = os.path.expanduser("~/Library/Application Support")
    else:
        base_path = os.path.expanduser("~/.config")

    models_dir = os.path.join(base_path, app_name, "models")
    if not os.path.exists(models_dir):
        os.makedirs(models_dir)
    return models_dir


class ModelUpdate:
    """Checks for and downloads ML model updates from GitHub Releases."""

    def __init__(self):
        self.context: ssl.SSLContext = ssl.SSLContext(protocol=ssl.PROTOCOL_TLS_CLIENT)
        self.context.load_default_certs()

    def check_for_update(self, current_tag: str):
        """Check if a newer model release is available.

        Args:
            current_tag: The currently installed model version tag (e.g. "models-2026-02-19").

        Returns:
            Tuple of (new_tag, download_url) if an update is available, otherwise None.
        """
        try:
            req = urllib.request.Request(
                MODELS_RELEASE_URL,
                headers={"Accept": "application/vnd.github.v3+json"},
            )
            response = urllib.request.urlopen(req, context=self.context)
            release = json.loads(response.read())

            tag = release.get("tag_name", "")
            if not tag or tag == current_tag:
                return None

            # Find the models.zip asset
            for asset in release.get("assets", []):
                if asset["name"].endswith(".zip"):
                    return tag, asset["browser_download_url"]

            logger.warning("Model release %s has no ZIP asset", tag)
            return None

        except Exception as error:
            logger.error("Failed to check for model updates: %s", error)
            return None

    def download_and_install(self, download_url: str) -> bool:
        """Download a model ZIP and extract it to the AppData models directory.

        Args:
            download_url: The browser_download_url from the GitHub Release asset.

        Returns:
            True if successful, False otherwise.
        """
        try:
            models_dir = get_appdata_models_dir()

            # Download to a temp file
            with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
                tmp_path = tmp.name
                logger.info("Downloading models from %s", download_url)
                with urllib.request.urlopen(download_url, context=self.context) as resp:
                    shutil.copyfileobj(resp, tmp)

            # Clear existing downloaded models before extracting
            for subdir in ("onnx", "cards"):
                target = os.path.join(models_dir, subdir)
                if os.path.exists(target):
                    shutil.rmtree(target)

            # Extract
            with zipfile.ZipFile(tmp_path, "r") as zf:
                zf.extractall(models_dir)

            logger.info("Models installed to %s", models_dir)
            return True

        except Exception as error:
            logger.error("Failed to download/install models: %s", error)
            return False

        finally:
            try:
                os.remove(tmp_path)
            except (OSError, UnboundLocalError):
                pass
