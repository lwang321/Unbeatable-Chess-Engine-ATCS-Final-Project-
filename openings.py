"""
openings.py  –  Chess Opening Book implemented as a Trie
=========================================================

Structure
---------
Each OpeningTrieNode represents a position reached after some sequence of moves.
Edges out of a node are keyed by UCI move strings (e.g. "e2e4").
Each node stores:
  • name        – opening name at this position (or None)
  • children    – dict[uci_str -> OpeningTrieNode]
  • weight      – how "recommended" this move is (higher = more mainline)

OpeningBook wraps the trie and exposes:
  • insert(moves, name, weight)   – add a line
  • lookup(moves)                 – return node (or None)
  • suggest(moves)                – best child move UCI + opening name
  • get_name(moves)               – name at exact position

Move encoding
-------------
We store moves as UCI strings: "from_sqto_sq", e.g. "e2e4".
The Game/setup layer uses (from_r, from_c, to_r, to_c) dicts.
Conversion helpers are provided.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import random


# ── Trie node ────────────────────────────────────────────────────────────────

@dataclass
class OpeningTrieNode:
    name: Optional[str] = None          # opening name reached at this node
    weight: int = 1                     # relative frequency / quality
    children: dict = field(default_factory=dict)   # uci_str -> OpeningTrieNode

    def is_leaf(self) -> bool:
        return len(self.children) == 0


# ── Trie / Book ───────────────────────────────────────────────────────────────

class OpeningBook:
    """
    A trie of chess opening lines keyed by sequences of UCI move strings.

    Usage
    -----
        book = build_opening_book()
        node = book.lookup(["e2e4", "e7e5", "g1f3"])
        uci, name = book.suggest(["e2e4", "e7e5"])
    """

    def __init__(self):
        self.root = OpeningTrieNode(name="Starting Position")

    # ── mutation ──────────────────────────────────────────────────────────────

    def insert(self, moves: list[str], name: str, weight: int = 1) -> None:
        """Insert a line (list of UCI strings) with an opening name."""
        node = self.root
        for uci in moves:
            if uci not in node.children:
                node.children[uci] = OpeningTrieNode()
            node = node.children[uci]
        # Only overwrite name if this is a more specific / heavier annotation
        if node.name is None or weight > node.weight:
            node.name = name
            node.weight = weight

    # ── query ─────────────────────────────────────────────────────────────────

    def lookup(self, moves: list[str]) -> Optional[OpeningTrieNode]:
        """Return the trie node after playing `moves`, or None if off-book."""
        node = self.root
        for uci in moves:
            node = node.children.get(uci)
            if node is None:
                return None
        return node

    def get_name(self, moves: list[str]) -> Optional[str]:
        """Return the opening name at exactly this position, or None."""
        node = self.lookup(moves)
        return node.name if node else None

    def best_name(self, moves: list[str]) -> Optional[str]:
        """
        Walk back up the move list to find the most recent named position.
        Useful for displaying the current opening even mid-line.
        """
        for i in range(len(moves), -1, -1):
            name = self.get_name(moves[:i])
            if name:
                return name
        return None

    def suggest(self, moves: list[str]) -> tuple[Optional[str], Optional[str]]:
        """
        Return (uci_move, opening_name) for the best book response after `moves`.
        Selects by weight (weighted random among top candidates).
        Returns (None, None) if off-book.
        """
        node = self.lookup(moves)
        if node is None or not node.children:
            return None, None

        candidates = list(node.children.items())   # [(uci, child_node), ...]
        total = sum(c.weight for _, c in candidates)
        r = random.randint(1, total)
        cumulative = 0
        chosen_uci, chosen_node = candidates[0]
        for uci, child in candidates:
            cumulative += child.weight
            if r <= cumulative:
                chosen_uci, chosen_node = uci, child
                break

        return chosen_uci, chosen_node.name

    def has_moves(self, moves: list[str]) -> bool:
        """True if there are book continuations after `moves`."""
        node = self.lookup(moves)
        return node is not None and bool(node.children)

    def all_moves(self, moves: list[str]) -> list[tuple[str, int, Optional[str]]]:
        """
        Return all book moves at this position as list of
        (uci, weight, child_name) sorted by weight descending.
        """
        node = self.lookup(moves)
        if node is None:
            return []
        return sorted(
            [(uci, child.weight, child.name) for uci, child in node.children.items()],
            key=lambda x: -x[1]
        )

    # ── stats ─────────────────────────────────────────────────────────────────

    def size(self) -> int:
        """Total number of nodes in the trie."""
        def count(node):
            return 1 + sum(count(c) for c in node.children.values())
        return count(self.root)

    def depth(self) -> int:
        """Maximum line length stored."""
        def max_depth(node):
            if not node.children:
                return 0
            return 1 + max(max_depth(c) for c in node.children.values())
        return max_depth(self.root)


# ── UCI ↔ board-dict conversion helpers ──────────────────────────────────────

def uci_to_move(uci: str) -> dict:
    """Convert UCI string 'e2e4' to a partial move dict {from_r,from_c,to_r,to_c}."""
    files = "abcdefgh"
    fc = files.index(uci[0])
    fr = 8 - int(uci[1])
    tc = files.index(uci[2])
    tr = 8 - int(uci[3])
    return {"from_r": fr, "from_c": fc, "to_r": tr, "to_c": tc}

def move_to_uci(move: dict) -> str:
    """Convert move dict to UCI string 'e2e4'."""
    files = "abcdefgh"
    return (files[move['from_c']] + str(8 - move['from_r']) +
            files[move['to_c']]   + str(8 - move['to_r']))

def moves_to_uci(move_log_dicts: list[dict]) -> list[str]:
    """Convert a list of move dicts to UCI strings."""
    return [move_to_uci(m) for m in move_log_dicts]


# ── Book data ─────────────────────────────────────────────────────────────────

def build_opening_book() -> OpeningBook:
    """
    Construct and return the full opening book trie.

    Lines are listed as (uci_sequence, name, weight).
    Weight 10 = main line, 7 = important variation, 4 = sideline, 1 = rare.
    """
    book = OpeningBook()

    lines = [

        # ══════════════════════════════════════════════════════════════════════
        # 1. e4
        # ══════════════════════════════════════════════════════════════════════

        (["e2e4"], "King's Pawn Opening", 10),

        # ── Ruy López ─────────────────────────────────────────────────────────
        (["e2e4","e7e5","g1f3","b8c6","f1b5"], "Ruy López", 10),

        # Morphy / Closed main trunk
        (["e2e4","e7e5","g1f3","b8c6","f1b5","a7a6"], "Ruy López: Morphy Defence", 10),
        (["e2e4","e7e5","g1f3","b8c6","f1b5","a7a6","b5a4","g8f6"], "Ruy López: Closed", 10),
        (["e2e4","e7e5","g1f3","b8c6","f1b5","a7a6","b5a4","g8f6","e1g1"], "Ruy López: Closed, Main Line", 9),
        (["e2e4","e7e5","g1f3","b8c6","f1b5","a7a6","b5a4","g8f6","e1g1","f8e7"], "Ruy López: Closed, 6…Be7", 9),
        (["e2e4","e7e5","g1f3","b8c6","f1b5","a7a6","b5a4","g8f6","e1g1","f8e7","f1e1","b7b5","a4b3","d7d6"], "Ruy López: Closed, Chigorin", 8),
        (["e2e4","e7e5","g1f3","b8c6","f1b5","a7a6","b5a4","g8f6","e1g1","b7b5","a4b3","f8c5"], "Ruy López: Archangel", 7),
        (["e2e4","e7e5","g1f3","b8c6","f1b5","a7a6","b5a4","g8f6","e1g1","g8e4"], "Ruy López: Open (Riga)", 7),

        # Exchange
        (["e2e4","e7e5","g1f3","b8c6","f1b5","a7a6","b5c6"], "Ruy López: Exchange Variation", 7),
        (["e2e4","e7e5","g1f3","b8c6","f1b5","a7a6","b5c6","d7c6","e1g1"], "Ruy López: Exchange, 5.0-0", 6),
        (["e2e4","e7e5","g1f3","b8c6","f1b5","a7a6","b5c6","d7c6","d2d4"], "Ruy López: Exchange, 5.d4", 6),

        # Berlin
        (["e2e4","e7e5","g1f3","b8c6","f1b5","g8f6"], "Ruy López: Berlin Defence", 8),
        (["e2e4","e7e5","g1f3","b8c6","f1b5","g8f6","e1g1","f6e4","d2d4"], "Ruy López: Berlin, Main Line", 8),
        (["e2e4","e7e5","g1f3","b8c6","f1b5","g8f6","e1g1","f6e4","d2d4","e4d6","b5c6","d7c6","d4e5","d6f5"], "Ruy López: Berlin Endgame", 7),

        # Classical / other 3rd-move replies
        (["e2e4","e7e5","g1f3","b8c6","f1b5","f8c5"], "Ruy López: Classical Defence", 7),
        (["e2e4","e7e5","g1f3","b8c6","f1b5","f8c5","c2c3","g8f6","d2d4"], "Ruy López: Classical, Centre Attack", 6),
        (["e2e4","e7e5","g1f3","b8c6","f1b5","d7d6"], "Ruy López: Steinitz Defence", 5),
        (["e2e4","e7e5","g1f3","b8c6","f1b5","g7g6"], "Ruy López: Smyslov Defence", 4),

        # ── Italian Game ──────────────────────────────────────────────────────
        (["e2e4","e7e5","g1f3","b8c6","f1c4"], "Italian Game", 10),

        # Giuoco Piano
        (["e2e4","e7e5","g1f3","b8c6","f1c4","f8c5"], "Giuoco Piano", 9),
        (["e2e4","e7e5","g1f3","b8c6","f1c4","f8c5","c2c3"], "Giuoco Piano: Main Line", 8),
        (["e2e4","e7e5","g1f3","b8c6","f1c4","f8c5","c2c3","g8f6","d2d4","e5d4","c3d4"], "Giuoco Piano: Centre Attack", 8),
        (["e2e4","e7e5","g1f3","b8c6","f1c4","f8c5","c2c3","g8f6","d2d4","e5d4","e4e5"], "Giuoco Piano: Greco Attack", 7),
        (["e2e4","e7e5","g1f3","b8c6","f1c4","f8c5","d2d3"], "Giuoco Piano: Quiet Game", 7),
        (["e2e4","e7e5","g1f3","b8c6","f1c4","f8c5","d2d3","g8f6","b1c3"], "Giuoco Piano: Giuoco Pianissimo", 7),

        # Evans Gambit
        (["e2e4","e7e5","g1f3","b8c6","f1c4","f8c5","b2b4"], "Evans Gambit", 7),
        (["e2e4","e7e5","g1f3","b8c6","f1c4","f8c5","b2b4","c5b4","c2c3"], "Evans Gambit: Main Line", 7),
        (["e2e4","e7e5","g1f3","b8c6","f1c4","f8c5","b2b4","c5b4","c2c3","b4a5","d2d4"], "Evans Gambit: 5.d4", 6),

        # Two Knights
        (["e2e4","e7e5","g1f3","b8c6","f1c4","g8f6"], "Two Knights Defence", 8),
        (["e2e4","e7e5","g1f3","b8c6","f1c4","g8f6","f3g5"], "Two Knights: Fried Liver Attack", 6),
        (["e2e4","e7e5","g1f3","b8c6","f1c4","g8f6","f3g5","d7d5","c4d5","c6a5"], "Two Knights: Fritz Variation", 5),
        (["e2e4","e7e5","g1f3","b8c6","f1c4","g8f6","d2d4","e5d4","e4e5"], "Two Knights: Modern Attack", 6),
        (["e2e4","e7e5","g1f3","b8c6","f1c4","g8f6","b1c3"], "Two Knights: 4.Nc3", 6),

        # ── Scotch Game ───────────────────────────────────────────────────────
        (["e2e4","e7e5","g1f3","b8c6","d2d4"], "Scotch Game", 8),
        (["e2e4","e7e5","g1f3","b8c6","d2d4","e5d4","f3d4"], "Scotch Game: Main Line", 8),
        (["e2e4","e7e5","g1f3","b8c6","d2d4","e5d4","f3d4","f8c5"], "Scotch Game: Classical", 7),
        (["e2e4","e7e5","g1f3","b8c6","d2d4","e5d4","f3d4","f8c5","c1e3"], "Scotch: Classical, 5.Be3", 6),
        (["e2e4","e7e5","g1f3","b8c6","d2d4","e5d4","f3d4","g8f6"], "Scotch: Schmidt Variation", 6),
        (["e2e4","e7e5","g1f3","b8c6","d2d4","e5d4","f3d4","d8h4"], "Scotch: Steinitz Variation", 5),
        (["e2e4","e7e5","g1f3","b8c6","d2d4","e5d4","c2c3"], "Göring Gambit", 5),
        (["e2e4","e7e5","g1f3","b8c6","d2d4","e5d4","c2c3","d4c3","b1c3"], "Göring Gambit Accepted", 5),

        # ── King's Gambit ─────────────────────────────────────────────────────
        (["e2e4","e7e5","f2f4"], "King's Gambit", 7),
        (["e2e4","e7e5","f2f4","e5f4"], "King's Gambit Accepted", 7),
        (["e2e4","e7e5","f2f4","e5f4","g1f3"], "KGA: King's Knight Gambit", 6),
        (["e2e4","e7e5","f2f4","e5f4","g1f3","g7g5"], "KGA: Fischer Defence", 6),
        (["e2e4","e7e5","f2f4","e5f4","g1f3","g7g5","f1c4","g5g4"], "KGA: Muzio Gambit", 5),
        (["e2e4","e7e5","f2f4","e5f4","g1f3","d7d6"], "KGA: Becker Defence", 5),
        (["e2e4","e7e5","f2f4","e5f4","f1c4"], "KGA: Bishop's Gambit", 5),
        (["e2e4","e7e5","f2f4","f8c5"], "King's Gambit Declined: Classical", 5),
        (["e2e4","e7e5","f2f4","d7d5"], "King's Gambit Declined: Falkbeer Counter", 5),
        (["e2e4","e7e5","f2f4","d7d5","e4d5","e5f4"], "Falkbeer Countergambit Accepted", 5),

        # ── Four Knights ──────────────────────────────────────────────────────
        (["e2e4","e7e5","g1f3","b8c6","b1c3","g8f6"], "Four Knights Game", 7),
        (["e2e4","e7e5","g1f3","b8c6","b1c3","g8f6","f1b5"], "Four Knights: Spanish Variation", 6),
        (["e2e4","e7e5","g1f3","b8c6","b1c3","g8f6","f1b5","f8b4"], "Four Knights: Double Spanish", 6),
        (["e2e4","e7e5","g1f3","b8c6","b1c3","g8f6","d2d4","e5d4"], "Four Knights: Scotch Variation", 5),
        (["e2e4","e7e5","g1f3","b8c6","b1c3","g8f6","f1c4"], "Four Knights: Italian Variation", 5),

        # ── Petrov's Defence ──────────────────────────────────────────────────
        (["e2e4","e7e5","g1f3","g8f6"], "Petrov's Defence", 8),
        (["e2e4","e7e5","g1f3","g8f6","f3e5"], "Petrov: Classical Attack", 7),
        (["e2e4","e7e5","g1f3","g8f6","f3e5","d7d6","e5f3","f6e4","d2d4"], "Petrov: Classical, Main Line", 7),
        (["e2e4","e7e5","g1f3","g8f6","f3e5","f6e4","d2d4","d7d5","f1d3"], "Petrov: Steinitz Attack", 6),
        (["e2e4","e7e5","g1f3","g8f6","d2d4"], "Petrov: Centre Attack", 6),

        # ── Philidor Defence ──────────────────────────────────────────────────
        (["e2e4","e7e5","g1f3","d7d6"], "Philidor Defence", 5),
        (["e2e4","e7e5","g1f3","d7d6","d2d4","g8f6"], "Philidor: Main Line", 5),
        (["e2e4","e7e5","g1f3","d7d6","d2d4","b8d7","f1c4"], "Philidor: Hanham Variation", 4),

        # ── Sicilian Defence ──────────────────────────────────────────────────
        (["e2e4","c7c5"], "Sicilian Defence", 10),
        (["e2e4","c7c5","g1f3"], "Sicilian: Open", 10),

        # Najdorf
        (["e2e4","c7c5","g1f3","d7d6","d2d4","c5d4","f3d4","g8f6","b1c3","a7a6"], "Sicilian: Najdorf", 10),
        (["e2e4","c7c5","g1f3","d7d6","d2d4","c5d4","f3d4","g8f6","b1c3","a7a6","c1g5"], "Sicilian: Najdorf, English Attack", 8),
        (["e2e4","c7c5","g1f3","d7d6","d2d4","c5d4","f3d4","g8f6","b1c3","a7a6","f1e2"], "Sicilian: Najdorf, Classical", 8),
        (["e2e4","c7c5","g1f3","d7d6","d2d4","c5d4","f3d4","g8f6","b1c3","a7a6","f2f4"], "Sicilian: Najdorf, Four Pawns", 7),
        (["e2e4","c7c5","g1f3","d7d6","d2d4","c5d4","f3d4","g8f6","b1c3","a7a6","g2g4"], "Sicilian: Najdorf, Perenyi Attack", 6),

        # Dragon
        (["e2e4","c7c5","g1f3","d7d6","d2d4","c5d4","f3d4","g8f6","b1c3","g7g6"], "Sicilian: Dragon", 8),
        (["e2e4","c7c5","g1f3","d7d6","d2d4","c5d4","f3d4","g8f6","b1c3","g7g6","c1e3","f8g7","f2f3"], "Sicilian: Dragon, Yugoslav Attack", 8),
        (["e2e4","c7c5","g1f3","d7d6","d2d4","c5d4","f3d4","g8f6","b1c3","g7g6","c1e3","f8g7","f2f3","e8g8","d1d2"], "Sicilian: Dragon, Yugoslav, 9.Qd2", 7),
        (["e2e4","c7c5","g1f3","d7d6","d2d4","c5d4","f3d4","g8f6","b1c3","g7g6","f1e2"], "Sicilian: Dragon, Classical", 6),

        # Scheveningen
        (["e2e4","c7c5","g1f3","d7d6","d2d4","c5d4","f3d4","g8f6","b1c3","e7e6"], "Sicilian: Scheveningen", 8),
        (["e2e4","c7c5","g1f3","d7d6","d2d4","c5d4","f3d4","g8f6","b1c3","e7e6","g2g4"], "Sicilian: Scheveningen, Keres Attack", 7),
        (["e2e4","c7c5","g1f3","d7d6","d2d4","c5d4","f3d4","g8f6","b1c3","e7e6","f1e2"], "Sicilian: Scheveningen, Classical", 7),
        (["e2e4","c7c5","g1f3","e7e6","d2d4","c5d4","f3d4","g8f6","b1c3","d7d6"], "Sicilian: Scheveningen (via Kan)", 7),

        # Classical
        (["e2e4","c7c5","g1f3","b8c6","d2d4","c5d4","f3d4"], "Sicilian: Classical", 8),
        (["e2e4","c7c5","g1f3","b8c6","d2d4","c5d4","f3d4","g8f6","b1c3","d7d6"], "Sicilian: Classical, Main Line", 8),
        (["e2e4","c7c5","g1f3","b8c6","d2d4","c5d4","f3d4","g8f6","b1c3","e7e6"], "Sicilian: Classical, Scheveningen", 7),
        (["e2e4","c7c5","g1f3","b8c6","d2d4","c5d4","f3d4","g8f6","b1c3","d8b6"], "Sicilian: Poisoned Pawn (Classical)", 6),

        # Kan / Taimanov
        (["e2e4","c7c5","g1f3","e7e6","d2d4","c5d4","f3d4","b8c6"], "Sicilian: Taimanov", 7),
        (["e2e4","c7c5","g1f3","e7e6","d2d4","c5d4","f3d4","a7a6"], "Sicilian: Kan", 7),
        (["e2e4","c7c5","g1f3","e7e6","d2d4","c5d4","f3d4","a7a6","b1c3","d8c7"], "Sicilian: Kan, Main Line", 6),

        # Closed & anti-Sicilian
        (["e2e4","c7c5","b1c3"], "Sicilian: Closed", 7),
        (["e2e4","c7c5","b1c3","b8c6","g2g3","g7g6","f1g2","f8g7"], "Sicilian: Closed, Fianchetto", 6),
        (["e2e4","c7c5","c2c3"], "Sicilian: Alapin", 7),
        (["e2e4","c7c5","c2c3","g8f6","e4e5","f6d5","d2d4","c5d4","g1f3"], "Sicilian: Alapin, Main Line", 6),
        (["e2e4","c7c5","c2c3","d7d5","e4d5","d8d5","d2d4"], "Sicilian: Alapin, 2…d5", 6),
        (["e2e4","c7c5","f2f4"], "Sicilian: Grand Prix Attack", 5),
        (["e2e4","c7c5","f2f4","b8c6","g1f3","g7g6","f1b5"], "Sicilian: Grand Prix, Main Line", 5),

        # ── French Defence ────────────────────────────────────────────────────
        (["e2e4","e7e6"], "French Defence", 9),
        (["e2e4","e7e6","d2d4","d7d5"], "French Defence: Main Line", 9),

        # Winawer
        (["e2e4","e7e6","d2d4","d7d5","b1c3","f8b4"], "French: Winawer Variation", 9),
        (["e2e4","e7e6","d2d4","d7d5","b1c3","f8b4","e4e5"], "French: Winawer, Advance", 8),
        (["e2e4","e7e6","d2d4","d7d5","b1c3","f8b4","e4e5","c7c5","a2a3","b4c3","b2c3"], "French: Winawer, Main Line", 8),
        (["e2e4","e7e6","d2d4","d7d5","b1c3","f8b4","e4e5","c7c5","d1g4"], "French: Winawer, Poisoned Pawn", 7),
        (["e2e4","e7e6","d2d4","d7d5","b1c3","f8b4","a2a3"], "French: Winawer, Spassky", 6),

        # Classical
        (["e2e4","e7e6","d2d4","d7d5","b1c3","g8f6"], "French: Classical Variation", 8),
        (["e2e4","e7e6","d2d4","d7d5","b1c3","g8f6","c1g5"], "French: Classical, Main Line", 7),
        (["e2e4","e7e6","d2d4","d7d5","b1c3","g8f6","c1g5","f8e7","e4e5"], "French: Classical, Steinitz", 7),
        (["e2e4","e7e6","d2d4","d7d5","b1c3","g8f6","c1g5","d5e4","c3e4"], "French: Rubinstein Variation", 6),

        # Advance
        (["e2e4","e7e6","d2d4","d7d5","e4e5"], "French: Advance Variation", 7),
        (["e2e4","e7e6","d2d4","d7d5","e4e5","c7c5","c2c3"], "French: Advance, Main Line", 7),
        (["e2e4","e7e6","d2d4","d7d5","e4e5","c7c5","c2c3","b8c6","g1f3"], "French: Advance, Nimzovich", 6),
        (["e2e4","e7e6","d2d4","d7d5","e4e5","c7c5","c2c3","d8b6"], "French: Advance, Milner-Barry", 6),

        # Tarrasch
        (["e2e4","e7e6","d2d4","d7d5","b1d2"], "French: Tarrasch Variation", 7),
        (["e2e4","e7e6","d2d4","d7d5","b1d2","g8f6","e4e5","f6d7"], "French: Tarrasch, Closed", 6),
        (["e2e4","e7e6","d2d4","d7d5","b1d2","c7c5","g1f3"], "French: Tarrasch, Open", 6),
        (["e2e4","e7e6","d2d4","d7d5","b1d2","c7c5","d4c5","b8c6"], "French: Tarrasch, Chistyakov", 5),

        # Exchange
        (["e2e4","e7e6","d2d4","d7d5","e4d5"], "French: Exchange Variation", 5),
        (["e2e4","e7e6","d2d4","d7d5","e4d5","e6d5","g1f3","g8f6"], "French: Exchange, Main Line", 5),

        # ── Caro-Kann Defence ─────────────────────────────────────────────────
        (["e2e4","c7c6"], "Caro-Kann Defence", 9),
        (["e2e4","c7c6","d2d4","d7d5"], "Caro-Kann: Main Line", 9),

        # Classical
        (["e2e4","c7c6","d2d4","d7d5","b1c3","d5e4","c3e4"], "Caro-Kann: Classical", 8),
        (["e2e4","c7c6","d2d4","d7d5","b1c3","d5e4","c3e4","c8f5"], "Caro-Kann: Classical, 4…Bf5", 8),
        (["e2e4","c7c6","d2d4","d7d5","b1c3","d5e4","c3e4","c8f5","e4g3","f5g6","h2h4","h7h6"], "Caro-Kann: Classical, Main Line", 7),
        (["e2e4","c7c6","d2d4","d7d5","b1d2","d5e4","d2e4"], "Caro-Kann: Tartakower Variation", 6),

        # Advance
        (["e2e4","c7c6","d2d4","d7d5","e4e5"], "Caro-Kann: Advance Variation", 7),
        (["e2e4","c7c6","d2d4","d7d5","e4e5","c8f5","g1f3"], "Caro-Kann: Advance, Short", 6),
        (["e2e4","c7c6","d2d4","d7d5","e4e5","c8f5","b1c3"], "Caro-Kann: Advance, 4.Nc3", 6),
        (["e2e4","c7c6","d2d4","d7d5","e4e5","c8f5","g1f3","e7e6","f1e2"], "Caro-Kann: Advance, Main Line", 6),

        # Panov Attack
        (["e2e4","c7c6","d2d4","d7d5","e4d5","c6d5","c2c4"], "Caro-Kann: Panov Attack", 7),
        (["e2e4","c7c6","d2d4","d7d5","e4d5","c6d5","c2c4","g8f6","b1c3"], "Caro-Kann: Panov, Main Line", 7),
        (["e2e4","c7c6","d2d4","d7d5","e4d5","c6d5","c2c4","g8f6","b1c3","e7e6","g1f3"], "Caro-Kann: Panov, 5.Nf3", 6),

        # Fantasy
        (["e2e4","c7c6","d2d4","d7d5","f2f3"], "Caro-Kann: Fantasy Variation", 4),
        (["e2e4","c7c6","d2d4","d7d5","f2f3","d5e4","f3e4"], "Caro-Kann: Fantasy, 4.fxe4", 4),

        # ── Pirc / Modern ─────────────────────────────────────────────────────
        (["e2e4","d7d6","d2d4","g8f6","b1c3","g7g6"], "Pirc Defence", 6),
        (["e2e4","d7d6","d2d4","g8f6","b1c3","g7g6","f2f4"], "Pirc: Austrian Attack", 6),
        (["e2e4","d7d6","d2d4","g8f6","b1c3","g7g6","f2f4","f8g7","g1f3"], "Pirc: Austrian, Main Line", 5),
        (["e2e4","d7d6","d2d4","g8f6","b1c3","g7g6","c1e3","f8g7","d1d2"], "Pirc: Classical System", 5),
        (["e2e4","g7g6"], "Modern Defence", 5),
        (["e2e4","g7g6","d2d4","f8g7","b1c3"], "Modern Defence: Main Line", 4),

        # ── Alekhine's Defence ────────────────────────────────────────────────
        (["e2e4","g8f6"], "Alekhine's Defence", 6),
        (["e2e4","g8f6","e4e5","f6d5","d2d4","d7d6"], "Alekhine: Modern Variation", 6),
        (["e2e4","g8f6","e4e5","f6d5","d2d4","d7d6","c2c4","d5b6","f2f4"], "Alekhine: Four Pawns Attack", 5),
        (["e2e4","g8f6","e4e5","f6d5","d2d4","d7d6","g1f3"], "Alekhine: Exchange Variation", 5),

        # ── Scandinavian ──────────────────────────────────────────────────────
        (["e2e4","d7d5"], "Scandinavian Defence", 6),
        (["e2e4","d7d5","e4d5","d8d5","b1c3"], "Scandinavian: Main Line", 6),
        (["e2e4","d7d5","e4d5","d8d5","b1c3","d5a5"], "Scandinavian: Mieses-Kotrč", 5),
        (["e2e4","d7d5","e4d5","g8f6"], "Scandinavian: Modern Variation", 5),

        # ══════════════════════════════════════════════════════════════════════
        # 1. d4
        # ══════════════════════════════════════════════════════════════════════

        (["d2d4"], "Queen's Pawn Opening", 10),

        # ── Queen's Gambit ────────────────────────────────────────────────────
        (["d2d4","d7d5","c2c4"], "Queen's Gambit", 10),

        # QGA
        (["d2d4","d7d5","c2c4","d5c4"], "Queen's Gambit Accepted", 8),
        (["d2d4","d7d5","c2c4","d5c4","g1f3"], "QGA: Main Line", 7),
        (["d2d4","d7d5","c2c4","d5c4","g1f3","g8f6","e2e3"], "QGA: Classical", 7),
        (["d2d4","d7d5","c2c4","d5c4","g1f3","g8f6","e2e3","e7e6","f1c4"], "QGA: Classical, 5.Bc4", 6),
        (["d2d4","d7d5","c2c4","d5c4","e2e4"], "QGA: Central Variation", 6),
        (["d2d4","d7d5","c2c4","d5c4","e2e4","g8f6","e4e5","f6d5","f1c4"], "QGA: Central, Main Line", 6),

        # QGD
        (["d2d4","d7d5","c2c4","e7e6"], "Queen's Gambit Declined", 9),
        (["d2d4","d7d5","c2c4","e7e6","b1c3","g8f6"], "QGD: Main Line", 9),
        (["d2d4","d7d5","c2c4","e7e6","b1c3","g8f6","c1g5"], "QGD: Orthodox", 8),
        (["d2d4","d7d5","c2c4","e7e6","b1c3","g8f6","c1g5","f8e7","e2e3"], "QGD: Orthodox, Main Line", 8),
        (["d2d4","d7d5","c2c4","e7e6","b1c3","g8f6","c1g5","f8e7","g1f3","e8g8","e1c1"], "QGD: Orthodox, Classical", 7),
        (["d2d4","d7d5","c2c4","e7e6","b1c3","g8f6","g1f3"], "QGD: Three Knights", 7),
        (["d2d4","d7d5","c2c4","e7e6","b1c3","g8f6","g1f3","f8e7","c1f4"], "QGD: Vienna Variation", 7),
        (["d2d4","d7d5","c2c4","e7e6","b1c3","g8f6","g1f3","c7c6"], "QGD: Semi-Slav Blend", 7),
        (["d2d4","d7d5","c2c4","e7e6","g1f3","g8f6","b1c3","f8e7","c1f4"], "QGD: Vienna", 7),

        # Ragozin
        (["d2d4","d7d5","c2c4","e7e6","b1c3","g8f6","g1f3","f8b4"], "QGD: Ragozin Variation", 7),
        (["d2d4","d7d5","c2c4","e7e6","b1c3","g8f6","g1f3","f8b4","c1g5"], "QGD: Ragozin, Main Line", 6),

        # Slav
        (["d2d4","d7d5","c2c4","c7c6"], "Slav Defence", 9),
        (["d2d4","d7d5","c2c4","c7c6","g1f3","g8f6"], "Slav: Main Line", 9),
        (["d2d4","d7d5","c2c4","c7c6","g1f3","g8f6","b1c3","d5c4"], "Slav: Czech Variation", 7),
        (["d2d4","d7d5","c2c4","c7c6","g1f3","g8f6","b1c3","d5c4","a2a4"], "Slav: Czech, 5.a4", 6),
        (["d2d4","d7d5","c2c4","c7c6","g1f3","g8f6","b1c3","c8f5"], "Slav: Exchange Variation", 6),
        (["d2d4","d7d5","c2c4","c7c6","b1c3","g8f6","g1f3","e7e6"], "Semi-Slav Defence", 8),
        (["d2d4","d7d5","c2c4","c7c6","b1c3","g8f6","g1f3","e7e6","c1g5"], "Semi-Slav: Anti-Moscow", 7),
        (["d2d4","d7d5","c2c4","c7c6","b1c3","g8f6","g1f3","e7e6","e2e3"], "Semi-Slav: Meran Variation", 7),
        (["d2d4","d7d5","c2c4","c7c6","b1c3","g8f6","g1f3","e7e6","e2e3","b8d7","f1d3","d5c4","d3c4"], "Semi-Slav: Meran, Main Line", 6),

        # ── King's Indian Defence ─────────────────────────────────────────────
        (["d2d4","g8f6","c2c4","g7g6","b1c3","f8g7"], "King's Indian Defence", 9),
        (["d2d4","g8f6","c2c4","g7g6","b1c3","f8g7","e2e4","d7d6","g1f3"], "KID: Main Line", 9),
        (["d2d4","g8f6","c2c4","g7g6","b1c3","f8g7","e2e4","d7d6","g1f3","e8g8"], "KID: Classical", 9),
        (["d2d4","g8f6","c2c4","g7g6","b1c3","f8g7","e2e4","d7d6","g1f3","e8g8","f1e2","e7e5"], "KID: Classical, 6…e5", 8),
        (["d2d4","g8f6","c2c4","g7g6","b1c3","f8g7","e2e4","d7d6","g1f3","e8g8","f1e2","e7e5","e1g1"], "KID: Classical, 7.0-0", 8),
        (["d2d4","g8f6","c2c4","g7g6","b1c3","f8g7","e2e4","d7d6","g1f3","e8g8","f1e2","e7e5","d4d5"], "KID: Classical, Mar del Plata", 8),
        (["d2d4","g8f6","c2c4","g7g6","b1c3","f8g7","e2e4","d7d6","f2f3"], "KID: Sämisch Variation", 7),
        (["d2d4","g8f6","c2c4","g7g6","b1c3","f8g7","e2e4","d7d6","f2f3","e8g8","c1e3"], "KID: Sämisch, Main Line", 6),
        (["d2d4","g8f6","c2c4","g7g6","b1c3","f8g7","e2e4","d7d6","c1g5"], "KID: Averbakh Variation", 6),
        (["d2d4","g8f6","c2c4","g7g6","b1c3","f8g7","e2e4","d7d6","c1g5","e8g8","d1d2"], "KID: Averbakh, Main Line", 5),
        (["d2d4","g8f6","c2c4","g7g6","b1c3","f8g7","e2e4","d7d6","g1e2"], "KID: Spassky System", 5),
        (["d2d4","g8f6","c2c4","g7g6","b1c3","f8g7","e2e4","d7d6","g1f3","e8g8","h2h3"], "KID: Petrosian System", 6),

        # ── Grünfeld Defence ──────────────────────────────────────────────────
        (["d2d4","g8f6","c2c4","g7g6","b1c3","d7d5"], "Grünfeld Defence", 8),
        (["d2d4","g8f6","c2c4","g7g6","b1c3","d7d5","c4d5","f6d5","e2e4"], "Grünfeld: Exchange Variation", 8),
        (["d2d4","g8f6","c2c4","g7g6","b1c3","d7d5","c4d5","f6d5","e2e4","d5c3","b2c3"], "Grünfeld: Exchange, Main Line", 8),
        (["d2d4","g8f6","c2c4","g7g6","b1c3","d7d5","c4d5","f6d5","e2e4","d5c3","b2c3","f8g7","f1c4"], "Grünfeld: Exchange, Classical", 7),
        (["d2d4","g8f6","c2c4","g7g6","b1c3","d7d5","g1f3"], "Grünfeld: Three Knights", 6),
        (["d2d4","g8f6","c2c4","g7g6","b1c3","d7d5","g1f3","f8g7","d1b3"], "Grünfeld: Taimanov Variation", 6),
        (["d2d4","g8f6","c2c4","g7g6","b1c3","d7d5","c1f4"], "Grünfeld: Bf4 System", 5),

        # ── Nimzo-Indian Defence ──────────────────────────────────────────────
        (["d2d4","g8f6","c2c4","e7e6","b1c3","f8b4"], "Nimzo-Indian Defence", 9),
        (["d2d4","g8f6","c2c4","e7e6","b1c3","f8b4","d1c2"], "Nimzo-Indian: Classical", 8),
        (["d2d4","g8f6","c2c4","e7e6","b1c3","f8b4","d1c2","e8g8"], "Nimzo-Indian: Classical, 4…0-0", 7),
        (["d2d4","g8f6","c2c4","e7e6","b1c3","f8b4","d1c2","d7d5"], "Nimzo-Indian: Classical, 4…d5", 7),
        (["d2d4","g8f6","c2c4","e7e6","b1c3","f8b4","e2e3"], "Nimzo-Indian: Rubinstein", 8),
        (["d2d4","g8f6","c2c4","e7e6","b1c3","f8b4","e2e3","e8g8","f1d3"], "Nimzo-Indian: Rubinstein, Main Line", 7),
        (["d2d4","g8f6","c2c4","e7e6","b1c3","f8b4","e2e3","c7c5","f1d3"], "Nimzo-Indian: Rubinstein, Simagin", 6),
        (["d2d4","g8f6","c2c4","e7e6","b1c3","f8b4","a2a3"], "Nimzo-Indian: Sämisch", 6),
        (["d2d4","g8f6","c2c4","e7e6","b1c3","f8b4","a2a3","b4c3","b2c3","e8g8"], "Nimzo-Indian: Sämisch, Main Line", 5),
        (["d2d4","g8f6","c2c4","e7e6","b1c3","f8b4","g1f3"], "Nimzo-Indian: Three Knights", 6),
        (["d2d4","g8f6","c2c4","e7e6","b1c3","f8b4","g1f3","e8g8","d1b3"], "Nimzo-Indian: Three Knights, Queenside", 5),

        # ── Queen's Indian Defence ────────────────────────────────────────────
        (["d2d4","g8f6","c2c4","e7e6","g1f3","b7b6"], "Queen's Indian Defence", 8),
        (["d2d4","g8f6","c2c4","e7e6","g1f3","b7b6","g2g3"], "QID: Fianchetto", 8),
        (["d2d4","g8f6","c2c4","e7e6","g1f3","b7b6","g2g3","c8b7","f1g2","f8e7"], "QID: Fianchetto, Main Line", 7),
        (["d2d4","g8f6","c2c4","e7e6","g1f3","b7b6","g2g3","c8b7","f1g2","f8b4","c1d2"], "QID: Fianchetto, Spassky", 6),
        (["d2d4","g8f6","c2c4","e7e6","g1f3","b7b6","e2e3"], "QID: Classical", 6),
        (["d2d4","g8f6","c2c4","e7e6","g1f3","b7b6","e2e3","c8b7","f1d3"], "QID: Classical, Main Line", 5),
        (["d2d4","g8f6","c2c4","e7e6","g1f3","b7b6","b1c3"], "QID: 4.Nc3", 5),

        # ── Catalan Opening ───────────────────────────────────────────────────
        (["d2d4","g8f6","c2c4","e7e6","g1f3","d7d5","g2g3"], "Catalan Opening", 8),
        (["d2d4","g8f6","c2c4","e7e6","g1f3","d7d5","g2g3","f8e7","f1g2"], "Catalan: Closed", 8),
        (["d2d4","g8f6","c2c4","e7e6","g1f3","d7d5","g2g3","d5c4"], "Catalan: Open", 7),
        (["d2d4","g8f6","c2c4","e7e6","g1f3","d7d5","g2g3","d5c4","f1g2","a7a6"], "Catalan: Open, Main Line", 7),
        (["d2d4","g8f6","c2c4","e7e6","b1c3","d7d5","g2g3"], "Catalan via Nc3", 6),

        # ── Dutch Defence ─────────────────────────────────────────────────────
        (["d2d4","f7f5"], "Dutch Defence", 6),
        (["d2d4","f7f5","g2g3","g8f6","f1g2","e7e6"], "Dutch: Fianchetto", 5),
        (["d2d4","f7f5","c2c4","g8f6","b1c3","e7e6","g2g3","f8e7","f1g2","e8g8"], "Dutch: Classical", 5),
        (["d2d4","f7f5","c2c4","g8f6","g2g3","g7g6","f1g2","f8g7","g1f3","e8g8"], "Dutch: Leningrad", 6),
        (["d2d4","f7f5","c2c4","g8f6","g2g3","g7g6","f1g2","f8g7","g1f3","e8g8","e1g1","d7d6"], "Dutch: Leningrad, Main Line", 5),
        (["d2d4","f7f5","c2c4","g8f6","g1f3","e7e6","g2g3","f8b4","c1d2"], "Dutch: Nimzo-Dutch", 4),

        # ── London System ─────────────────────────────────────────────────────
        (["d2d4","d7d5","g1f3","g8f6","c1f4"], "London System", 8),
        (["d2d4","d7d5","g1f3","g8f6","c1f4","e7e6","e2e3"], "London: Main Line", 7),
        (["d2d4","d7d5","g1f3","g8f6","c1f4","e7e6","e2e3","f8d6","c1d6"], "London: 4…Bd6", 6),
        (["d2d4","d7d5","g1f3","g8f6","c1f4","c7c5","e2e3","b8c6"], "London vs c5", 6),
        (["d2d4","g8f6","g1f3","d7d5","c1f4","e7e6","e2e3"], "London: via Nf3", 7),

        # ── Trompowsky Attack ─────────────────────────────────────────────────
        (["d2d4","g8f6","c1g5"], "Trompowsky Attack", 5),
        (["d2d4","g8f6","c1g5","e7e6"], "Trompowsky: 2…e6", 5),
        (["d2d4","g8f6","c1g5","d7d5","b1d2"], "Trompowsky: 2…d5", 4),
        (["d2d4","g8f6","c1g5","g8e4","f4h4","c7c5"], "Trompowsky: Raptor Variation", 4),

        # ══════════════════════════════════════════════════════════════════════
        # 1. c4 — English Opening
        # ══════════════════════════════════════════════════════════════════════

        (["c2c4"], "English Opening", 8),

        # vs …e5
        (["c2c4","e7e5"], "English: Reversed Sicilian", 7),
        (["c2c4","e7e5","b1c3"], "English: Reversed Sicilian, 2.Nc3", 7),
        (["c2c4","e7e5","b1c3","g8f6","g1f3"], "English: Reversed Sicilian, 3.Nf3", 6),
        (["c2c4","e7e5","b1c3","g8f6","g1f3","b8c6","g2g3"], "English: Four Knights, Fianchetto", 6),
        (["c2c4","e7e5","b1c3","b8c6","g2g3","g7g6","f1g2","f8g7"], "English: King's English", 6),

        # Symmetrical
        (["c2c4","c7c5"], "English: Symmetrical", 6),
        (["c2c4","c7c5","b1c3","b8c6","g1f3"], "English: Symmetrical, Three Knights", 5),
        (["c2c4","c7c5","b1c3","g8f6","g2g3","d7d5","c4d5","f6d5"], "English: Symmetrical, Rubinstein", 5),

        # vs …Nf6
        (["c2c4","g8f6","b1c3","d7d5"], "English: Anglo-Indian", 6),
        (["c2c4","g8f6","b1c3","d7d5","c4d5","f6d5","e2e4"], "English: Anglo-Indian, Romanishin", 5),
        (["c2c4","g8f6","b1c3","e7e6","g1f3","d7d5","d2d4"], "English → QGD transposition", 6),
        (["c2c4","g8f6","g1f3","g7g6","b2b4"], "English: Orangutan Gambit", 4),

        # ══════════════════════════════════════════════════════════════════════
        # 1. Nf3 — Réti Opening
        # ══════════════════════════════════════════════════════════════════════

        (["g1f3"], "Réti Opening", 7),
        (["g1f3","d7d5","g2g3"], "Réti: King's Indian Attack", 7),
        (["g1f3","d7d5","g2g3","g8f6","f1g2","c7c6"], "Réti: KIA vs Caro", 6),
        (["g1f3","d7d5","g2g3","g8f6","f1g2","e7e6","e1g1"], "Réti: KIA, Main Line", 6),
        (["g1f3","d7d5","c2c4"], "Réti: Queen's Gambit Transposition", 6),
        (["g1f3","d7d5","c2c4","d5c4","e2e3"], "Réti: Accepted", 5),
        (["g1f3","g8f6","c2c4","g7g6","b2b4"], "Réti: Catalan Fianchetto", 5),

        # ══════════════════════════════════════════════════════════════════════
        # Flank / Irregular
        # ══════════════════════════════════════════════════════════════════════

        (["g2g3"], "King's Fianchetto Opening", 4),
        (["g2g3","d7d5","f1g2","e7e5"], "King's Fianchetto: vs Centre", 4),
        (["b2b3"], "Nimzowitsch-Larsen Attack", 4),
        (["b2b3","e7e5","c1b2","b8c6","e2e3"], "Nimzowitsch-Larsen: Main Line", 4),
        (["b2b4"], "Polish Opening (Orangutan)", 3),
        (["b2b4","e7e5","c1b2","f8b4","e2e3"], "Polish: Main Line", 3),
        (["f2f4"], "Bird's Opening", 4),
        (["f2f4","d7d5","g1f3","g8f6","e2e3"], "Bird's: Main Line", 4),
        (["f2f4","e7e5"], "Bird's: From Gambit", 4),
        (["f2f4","e7e5","f4e5","d7d6","e5d6","f8d6"], "Bird's: From Gambit Accepted", 4),
    ]

    for moves, name, weight in lines:
        book.insert(moves, name, weight)

    return book


# ── Module-level singleton ────────────────────────────────────────────────────

_book: Optional[OpeningBook] = None

def get_book() -> OpeningBook:
    """Return the shared singleton opening book (lazy-initialised)."""
    global _book
    if _book is None:
        _book = build_opening_book()
    return _book


# ── Quick test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    book = build_opening_book()
    print(f"Book size: {book.size()} nodes, max depth: {book.depth()} plies")

    test_lines = [
        ["e2e4", "c7c5", "g1f3", "d7d6", "d2d4", "c5d4", "f3d4", "g8f6", "b1c3", "a7a6"],
        ["d2d4", "g8f6", "c2c4", "e7e6", "b1c3", "f8b4"],
        ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "f8c5"],
        ["c2c4"],
    ]
    for line in test_lines:
        name = book.best_name(line)
        uci, next_name = book.suggest(line)
        print(f"  {' '.join(line)}")
        print(f"    current: {name}  →  suggest: {uci} ({next_name})")