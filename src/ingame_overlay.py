"""In-game rating badge overlay for MTGA Draft.

Displays ML rating badges directly on top of each card in the MTGA game window.
Each badge is an independent borderless tkinter Toplevel with click-through
(WS_EX_LAYERED | WS_EX_TRANSPARENT) so the player can still interact with the game.
"""

import sys
import tkinter
from src import constants
from src.logger import create_logger

logger = create_logger()

# Win32 constants
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020

# Only import ctypes on Windows
if sys.platform == "win32":
    import ctypes
    import ctypes.wintypes

    user32 = ctypes.windll.user32
    shcore = ctypes.windll.shcore

    # Enable per-monitor DPI awareness so positions match the actual screen
    try:
        shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

# --- Layout tables ---
# Maps pack size -> (columns, rows)
# MTGA uses 8 cards per row for packs with more than 8 cards
GRID_LAYOUTS = {
    15: (8, 2), 14: (8, 2), 13: (8, 2), 12: (8, 2),
    11: (8, 2), 10: (8, 2), 9: (8, 2),
    8: (8, 1), 7: (7, 1), 6: (6, 1),
    5: (5, 1), 4: (4, 1), 3: (3, 1), 2: (2, 1), 1: (1, 1),
}

# --- MTGA draft pack sort (reverse-engineered from CardSorter / SortTypeFilters.DraftPack) ---
# Sort keys: MythicToCommon → LandLast → ColorOrder → Title

_RARITY_ORDER = {"mythic": 0, "rare": 1, "uncommon": 2, "common": 3}

# Color flags: W=1, U=2, B=4, R=8, G=16.  Table maps flag→sort position.
_COLOR_SORT_TABLE = [0] * 32
_COLOR_SORT_TABLE[1]  = 0   # W
_COLOR_SORT_TABLE[2]  = 1   # U
_COLOR_SORT_TABLE[4]  = 2   # B
_COLOR_SORT_TABLE[8]  = 3   # R
_COLOR_SORT_TABLE[16] = 4   # G
_COLOR_SORT_TABLE[3]  = 5   # WU
_COLOR_SORT_TABLE[5]  = 6   # WB
_COLOR_SORT_TABLE[6]  = 7   # UB
_COLOR_SORT_TABLE[10] = 8   # UR
_COLOR_SORT_TABLE[12] = 9   # BR
_COLOR_SORT_TABLE[20] = 10  # BG
_COLOR_SORT_TABLE[24] = 11  # RG
_COLOR_SORT_TABLE[9]  = 12  # WR
_COLOR_SORT_TABLE[17] = 13  # WG
_COLOR_SORT_TABLE[18] = 14  # UG
_COLOR_SORT_TABLE[7]  = 15  # WUB
_COLOR_SORT_TABLE[14] = 16  # UBR
_COLOR_SORT_TABLE[28] = 17  # BRG
_COLOR_SORT_TABLE[25] = 18  # WRG
_COLOR_SORT_TABLE[19] = 19  # WUG
_COLOR_SORT_TABLE[13] = 20  # WBR
_COLOR_SORT_TABLE[26] = 21  # URG
_COLOR_SORT_TABLE[21] = 22  # WBG
_COLOR_SORT_TABLE[11] = 23  # WUR
_COLOR_SORT_TABLE[22] = 24  # UBG
_COLOR_SORT_TABLE[15] = 25  # WUBR
_COLOR_SORT_TABLE[30] = 26  # UBRG
_COLOR_SORT_TABLE[29] = 27  # WBRG
_COLOR_SORT_TABLE[27] = 28  # WURG
_COLOR_SORT_TABLE[23] = 29  # WUBG
_COLOR_SORT_TABLE[31] = 30  # WUBRG
_COLOR_SORT_TABLE[0]  = 31  # Colorless

_COLOR_FLAG = {"W": 1, "U": 2, "B": 4, "R": 8, "G": 16}


def _card_color_flags(card):
    """Compute color flag bitmask.  For artifacts/lands use color_identity if available."""
    types = card.get("types", [])
    is_artifact_or_land = any(t in ("Artifact", "Land") for t in types)
    # Prefer color_identity for artifacts/lands (matches MTGA behavior)
    if is_artifact_or_land and "color_identity" in card:
        colors = card["color_identity"]
    else:
        colors = card.get("colors", [])
    flag = 0
    for c in colors:
        flag |= _COLOR_FLAG.get(c, 0)
    return flag


def mtga_draft_sort_key(card):
    """Return a sort key tuple matching MTGA's DraftPack sort order."""
    name = card.get(constants.DATA_FIELD_NAME, "")
    # Unknown cards (name is numeric arena ID) are basic lands — sort last
    if name.isdigit():
        return (3, 1, 32, name)
    rarity = _RARITY_ORDER.get(card.get("rarity", "common"), 3)
    is_land = 1 if "Land" in card.get("types", []) else 0
    color_order = _COLOR_SORT_TABLE[_card_color_flags(card) & 0x1F]
    return (rarity, is_land, color_order, name)


# --- Color tiers ---
def _tier_colors(rating, is_best):
    """Return (background, foreground) for a given rating value."""
    if is_best:
        return "#FFD700", "#000000"
    if rating >= 90:
        return "#FF4500", "#FFFFFF"  # 火焰红
    if rating >= 75:
        return "#22AA22", "#FFFFFF"  # 绿色
    if rating >= 65:
        return "#3399DD", "#FFFFFF"  # 亮蓝
    if rating >= 58:
        return "#5577AA", "#FFFFFF"  # 钢蓝
    if rating >= 52:
        return "#778899", "#FFFFFF"  # 蓝灰
    if rating >= 45:
        return "#888888", "#FFFFFF"  # 灰色
    if rating >= 30:
        return "#AA4444", "#FFFFFF"  # 暗红
    return "#553333", "#998888"


class RatingBadge:
    """A small borderless toplevel window that shows one rating number."""

    def __init__(self, root):
        self.top = tkinter.Toplevel(root)
        self.top.wm_overrideredirect(True)
        self.top.attributes("-topmost", True)
        self.top.withdraw()

        self.label = tkinter.Label(
            self.top,
            text="",
            font=("Arial", 13, "bold"),
            padx=4,
            pady=1,
        )
        self.label.pack()

        self._visible = False
        self._click_through_set = False

    def _ensure_click_through(self):
        """Apply WS_EX_LAYERED | WS_EX_TRANSPARENT so clicks pass through."""
        if self._click_through_set or sys.platform != "win32":
            return
        try:
            self.top.update_idletasks()
            hwnd = int(self.top.wm_frame(), 16) if self.top.wm_frame() else self.top.winfo_id()
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT)
            self._click_through_set = True
        except Exception as e:
            logger.error("Failed to set click-through: %s", e)

    def show(self, x, y, rating, is_best=False, debug_info=None):
        """Position the badge at (x, y) screen coords and display the rating."""
        bg, fg = _tier_colors(rating, is_best)
        text = f"{rating:.1f}"
        if debug_info is not None:
            idx, name = debug_info
            short_name = name[:10] if len(name) > 10 else name
            text = f"{text} [{idx}:{short_name}]"

        self.label.config(text=text, bg=bg, fg=fg)
        self.top.config(bg=bg)
        self.top.geometry(f"+{x}+{y}")

        if not self._visible:
            self.top.deiconify()
            self._visible = True

        self._ensure_click_through()

    def hide(self):
        if self._visible:
            self.top.withdraw()
            self._visible = False

    def destroy(self):
        try:
            self.top.destroy()
        except Exception:
            pass


class InGameOverlay:
    """Manages a set of RatingBadge windows positioned over the MTGA client."""

    def __init__(self, root, configuration):
        self.root = root
        self.configuration = configuration
        self._badges = []  # list of RatingBadge
        self._poll_id = None
        self._last_mtga_rect = None
        self._last_pack_cards = []
        self._last_ratings = {}
        self._last_pick_number = -1

        # Start the MTGA-tracking poll loop
        self._start_polling()

    # ------------------------------------------------------------------
    # MTGA window detection (Win32)
    # ------------------------------------------------------------------

    def _find_mtga_window(self):
        """Return HWND of the MTGA window, or None."""
        if sys.platform != "win32":
            return None
        try:
            # Try known window titles
            for title in ("MTGA", "Magic: The Gathering Arena"):
                hwnd = user32.FindWindowW(None, title)
                if hwnd and hwnd != 0:
                    return hwnd
            # Enumerate windows to find one containing "Magic" or "MTGA"
            found_hwnd = None
            @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
            def enum_callback(h, _):
                nonlocal found_hwnd
                buf = ctypes.create_unicode_buffer(256)
                user32.GetWindowTextW(h, buf, 256)
                title = buf.value
                if title and ("MTGA" in title or "Magic" in title):
                    logger.info("Found candidate MTGA window: '%s' (hwnd=%s)", title, h)
                    if user32.IsWindowVisible(h):
                        found_hwnd = h
                        return False  # stop enumeration
                return True
            user32.EnumWindows(enum_callback, 0)
            if found_hwnd:
                return found_hwnd
        except Exception as e:
            logger.error("Error finding MTGA window: %s", e)
        return None

    def _get_mtga_rect(self, hwnd):
        """Return (left, top, right, bottom) client rect in screen coords."""
        try:
            rect = ctypes.wintypes.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(rect))
            point_tl = ctypes.wintypes.POINT(rect.left, rect.top)
            point_br = ctypes.wintypes.POINT(rect.right, rect.bottom)
            user32.ClientToScreen(hwnd, ctypes.byref(point_tl))
            user32.ClientToScreen(hwnd, ctypes.byref(point_br))
            return (point_tl.x, point_tl.y, point_br.x, point_br.y)
        except Exception:
            return None

    def _is_minimized(self, hwnd):
        try:
            return bool(user32.IsIconic(hwnd))
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Card position calculation
    # ------------------------------------------------------------------

    def _calculate_card_positions(self, num_cards, window_rect):
        """Return list of (x, y) screen positions for each card badge.

        The positions are derived from the MTGA client rect and calibration
        parameters stored in configuration.features.
        """
        if num_cards <= 0 or num_cards > 15:
            return []

        left, top, right, bottom = window_rect
        w = right - left
        h = bottom - top

        if w <= 0 or h <= 0:
            return []

        cols, rows = GRID_LAYOUTS.get(num_cards, (8, 2))

        # Calibration parameters (fraction of client area)
        feat = self.configuration.features
        grid_left = getattr(feat, "ingame_grid_left", 0.16)
        grid_right = getattr(feat, "ingame_grid_right", 0.826)
        grid_top = getattr(feat, "ingame_grid_top", 0.32)
        grid_bottom = getattr(feat, "ingame_grid_bottom", 0.654)

        grid_w = (grid_right - grid_left) * w
        grid_h = (grid_bottom - grid_top) * h
        grid_x0 = left + grid_left * w
        grid_y0 = top + grid_top * h

        # MTGA uses fixed 8-column spacing — card size/spacing never changes
        cell_w = grid_w / 8
        cell_h = grid_h / 2
        y_offset = cell_h * 0.08

        positions = []
        for idx in range(num_cards):
            row_idx = idx // cols
            col_idx = idx % cols

            # Incomplete last row aligns to the left (same as MTGA)
            cx = grid_x0 + col_idx * cell_w + cell_w / 2
            cy = grid_y0 + row_idx * cell_h + y_offset

            # Offset badge so it is centered horizontally
            badge_x = int(cx - 15)
            badge_y = int(cy)

            positions.append((badge_x, badge_y))

        return positions

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, pack_cards, ratings_dict, pick_number):
        """Create / update / hide badges for the current pack.

        Args:
            pack_cards: list of card dicts (from log_scanner) in Arena order
            ratings_dict: {card_name: float} ML ratings (0-100)
            pick_number: current pick number (for cache-checking)
        """
        if not self.configuration.settings.ingame_overlay_enabled:
            self._hide_all()
            return

        if sys.platform != "win32":
            return

        self._last_pack_cards = pack_cards
        self._last_ratings = ratings_dict
        self._last_pick_number = pick_number

        self._position_badges()

    def _position_badges(self):
        """Internal: position badges using current cached state."""
        pack_cards = sorted(self._last_pack_cards, key=mtga_draft_sort_key) if self._last_pack_cards else []
        ratings_dict = self._last_ratings

        if not pack_cards or not ratings_dict:
            logger.debug("No pack_cards (%d) or ratings (%d), hiding badges",
                         len(pack_cards) if pack_cards else 0,
                         len(ratings_dict) if ratings_dict else 0)
            self._hide_all()
            return

        hwnd = self._find_mtga_window()
        if hwnd is None:
            logger.debug("MTGA window not found, hiding badges")
            self._hide_all()
            return
        if self._is_minimized(hwnd):
            self._hide_all()
            return

        rect = self._get_mtga_rect(hwnd)
        if rect is None:
            self._hide_all()
            return

        self._last_mtga_rect = rect
        num_cards = len(pack_cards)
        positions = self._calculate_card_positions(num_cards, rect)

        if len(positions) != num_cards:
            self._hide_all()
            return

        # Ensure we have enough badge objects
        while len(self._badges) < num_cards:
            self._badges.append(RatingBadge(self.root))

        # Determine which card has the best rating
        card_ratings = []
        for card in pack_cards:
            name = card.get(constants.DATA_FIELD_NAME, "") if isinstance(card, dict) else str(card)
            r = ratings_dict.get(name, 0.0)
            card_ratings.append((name, r))

        best_rating = max((r for _, r in card_ratings), default=0)
        debug_mode = getattr(self.configuration.features, "ingame_overlay_debug", False)

        for idx, (pos, (name, rating)) in enumerate(zip(positions, card_ratings)):
            is_best = (rating == best_rating and rating > 0)
            if debug_mode:
                self._badges[idx].show(pos[0], pos[1], rating, is_best, debug_info=(idx, name))
            else:
                self._badges[idx].show(pos[0], pos[1], rating, is_best)

        # Hide extra badges
        for idx in range(num_cards, len(self._badges)):
            self._badges[idx].hide()

    def hide_all(self):
        """Public method to hide all badges and clear cached state."""
        self._last_pack_cards = []
        self._last_ratings = {}
        self._hide_all()

    def _hide_all(self):
        for badge in self._badges:
            badge.hide()

    def destroy(self):
        """Destroy all badge windows and stop polling."""
        self._stop_polling()
        for badge in self._badges:
            badge.destroy()
        self._badges.clear()

    # ------------------------------------------------------------------
    # Polling loop: reposition badges when MTGA moves / resizes
    # ------------------------------------------------------------------

    def _start_polling(self):
        self._poll_tick()

    def _stop_polling(self):
        if self._poll_id is not None:
            try:
                self.root.after_cancel(self._poll_id)
            except Exception:
                pass
            self._poll_id = None

    def _poll_tick(self):
        """Re-check MTGA window position every 500ms."""
        try:
            if (
                self.configuration.settings.ingame_overlay_enabled
                and self._last_pack_cards
                and self._last_ratings
            ):
                self._position_badges()
        except Exception as e:
            logger.error("Overlay poll error: %s", e)

        try:
            self._poll_id = self.root.after(500, self._poll_tick)
        except Exception:
            pass
