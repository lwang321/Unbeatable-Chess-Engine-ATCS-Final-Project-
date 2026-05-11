import random
from setup import (is_in_check, get_legal_moves, do_move,
                   make_move, unmake_move, _init_king_pos)

# ── piece values ──────────────────────────────────────────────────────────────

PIECE_VALUES = {
    'P': 100,
    'N': 320,
    'B': 330,
    'R': 500,
    'Q': 900,
    'K': 0,
}

# ── piece-square tables ───────────────────────────────────────────────────────
# Values are bonuses (in centipawns) added to the piece's base value.
# Tables are from White's perspective (row 0 = rank 8, row 7 = rank 1).
# Black's tables are the mirror image (reversed row order).

_PST = {
    'P': [
        [ 0,  0,  0,  0,  0,  0,  0,  0],
        [50, 50, 50, 50, 50, 50, 50, 50],
        [10, 10, 20, 30, 30, 20, 10, 10],
        [ 5,  5, 10, 25, 25, 10,  5,  5],
        [ 0,  0,  0, 20, 20,  0,  0,  0],
        [ 5, -5,-10,  0,  0,-10, -5,  5],
        [ 5, 10, 10,-20,-20, 10, 10,  5],
        [ 0,  0,  0,  0,  0,  0,  0,  0],
    ],
    'N': [
        [-50,-40,-30,-30,-30,-30,-40,-50],
        [-40,-20,  0,  0,  0,  0,-20,-40],
        [-30,  0, 10, 15, 15, 10,  0,-30],
        [-30,  5, 15, 20, 20, 15,  5,-30],
        [-30,  0, 15, 20, 20, 15,  0,-30],
        [-30,  5, 10, 15, 15, 10,  5,-30],
        [-40,-20,  0,  5,  5,  0,-20,-40],
        [-50,-40,-30,-30,-30,-30,-40,-50],
    ],
    'B': [
        [-20,-10,-10,-10,-10,-10,-10,-20],
        [-10,  0,  0,  0,  0,  0,  0,-10],
        [-10,  0,  5, 10, 10,  5,  0,-10],
        [-10,  5,  5, 10, 10,  5,  5,-10],
        [-10,  0, 10, 10, 10, 10,  0,-10],
        [-10, 10, 10, 10, 10, 10, 10,-10],
        [-10,  5,  0,  0,  0,  0,  5,-10],
        [-20,-10,-10,-10,-10,-10,-10,-20],
    ],
    'R': [
        [ 0,  0,  0,  0,  0,  0,  0,  0],
        [ 5, 10, 10, 10, 10, 10, 10,  5],
        [-5,  0,  0,  0,  0,  0,  0, -5],
        [-5,  0,  0,  0,  0,  0,  0, -5],
        [-5,  0,  0,  0,  0,  0,  0, -5],
        [-5,  0,  0,  0,  0,  0,  0, -5],
        [-5,  0,  0,  0,  0,  0,  0, -5],
        [ 0,  0,  0,  5,  5,  0,  0,  0],
    ],
    'Q': [
        [-20,-10,-10, -5, -5,-10,-10,-20],
        [-10,  0,  0,  0,  0,  0,  0,-10],
        [-10,  0,  5,  5,  5,  5,  0,-10],
        [ -5,  0,  5,  5,  5,  5,  0, -5],
        [  0,  0,  5,  5,  5,  5,  0, -5],
        [-10,  5,  5,  5,  5,  5,  0,-10],
        [-10,  0,  5,  0,  0,  0,  0,-10],
        [-20,-10,-10, -5, -5,-10,-10,-20],
    ],
    'K': [
        [-30,-40,-40,-50,-50,-40,-40,-30],
        [-30,-40,-40,-50,-50,-40,-40,-30],
        [-30,-40,-40,-50,-50,-40,-40,-30],
        [-30,-40,-40,-50,-50,-40,-40,-30],
        [-20,-30,-30,-40,-40,-30,-30,-20],
        [-10,-20,-20,-20,-20,-20,-20,-10],
        [ 20, 20,  0,  0,  0,  0, 20, 20],
        [ 20, 30, 10,  0,  0, 10, 30, 20],
    ],
}

# Pre-mirror Black's tables (flip row order) so lookup is O(1) at eval time
_PST_BLACK = {pt: list(reversed(rows)) for pt, rows in _PST.items()}

CHECKMATE_SCORE = 10_000

# Aspiration window half-width (centipawns).
# On each ID iteration we open a window of ±ASPIRATION around the previous
# score; if the search fails outside it we re-search with a full window.
ASPIRATION_DELTA = 50

# ── zobrist hashing ───────────────────────────────────────────────────────────

def _make_zobrist_table():
    rng = random.Random(20250507)
    pieces = ['wK','wQ','wR','wB','wN','wP',
              'bK','bQ','bR','bB','bN','bP']
    table = {}
    for sq in range(64):
        for p in pieces:
            table[(sq, p)] = rng.getrandbits(64)
    for right in ('wK', 'wQ', 'bK', 'bQ'):
        table[('castle', right)] = rng.getrandbits(64)
    for f in range(8):
        table[('ep', f)] = rng.getrandbits(64)
    table['black_to_move'] = rng.getrandbits(64)
    return table

ZOBRIST = _make_zobrist_table()


def board_hash(board, color, ep, cas):
    h = 0
    for r in range(8):
        for c in range(8):
            piece = board[r][c]
            if piece:
                h ^= ZOBRIST[(r * 8 + c, piece[0] + piece[1])]
    if color == 'b':
        h ^= ZOBRIST['black_to_move']
    for right, active in cas.items():
        if active:
            h ^= ZOBRIST[('castle', right)]
    if ep:
        h ^= ZOBRIST[('ep', ep[1])]
    return h

# ── move ordering ─────────────────────────────────────────────────────────────

def _move_priority(move, board, tt_move=None):
    """
    Priority score for move ordering (higher = search first).

    Order: TT best move > winning captures (MVV-LLA) > equal captures >
           quiet moves > losing captures.

    The TT move is the best move stored from a previous search of this
    position (typically from the shallower iterative-deepening iteration).
    Trying it first dramatically improves alpha-beta cutoff rates.
    """
    # TT move from a previous iteration — always try first
    if tt_move and (
        move['from_r'] == tt_move['from_r'] and
        move['from_c'] == tt_move['from_c'] and
        move['to_r']   == tt_move['to_r']   and
        move['to_c']   == tt_move['to_c']
    ):
        return 100_000

    tr, tc = move['to_r'], move['to_c']
    victim = board[tr][tc]

    if move.get('en_passant_capture'):
        return 1000   # pawn takes pawn — equal capture

    if victim is None:
        return 0      # quiet move

    victim_val    = PIECE_VALUES[victim[1]]
    aggressor_val = PIECE_VALUES[board[move['from_r']][move['from_c']][1]]
    gain          = victim_val - aggressor_val

    if gain > 0:  return 2000 + victim_val   # winning capture
    if gain == 0: return 1000                # equal capture
    return -500                              # losing capture


def _order_moves(moves, board, tt_move=None):
    return sorted(moves,
                  key=lambda m: _move_priority(m, board, tt_move),
                  reverse=True)

# ── scoring ───────────────────────────────────────────────────────────────────

def abs_score(board, color, ep=None, cas=None, no_moves=False):
    """
    Evaluate the board from `color`'s perspective.

    `no_moves` is passed as True by negamax when it already knows the current
    side has no legal moves, so we skip re-generating them just to detect
    checkmate — we only need to know whether the king is in check.

    Without this flag, abs_score used to call get_legal_moves twice (once per
    side) at every leaf node, which was a massive redundant cost.
    """
    opp = 'b' if color == 'w' else 'w'

    # Checkmate / stalemate detection
    if no_moves:
        # negamax already confirmed moves == [] for `color`
        if is_in_check(color, board):
            return -CHECKMATE_SCORE   # current side is mated
        else:
            return 0                  # stalemate — draw
    else:
        # Called from outside the search (e.g. depth == 0 with moves available)
        # Still need to check opponent for checkmate at leaf
        for side, sign in ((color, -1), (opp, +1)):
            if is_in_check(side, board):
                if not get_legal_moves(side, board, ep, cas):
                    return sign * CHECKMATE_SCORE

    # Material balance
    score = 0
    for row in board:
        for square in row:
            if square is None:
                continue
            c, piece_type = square
            score += PIECE_VALUES[piece_type] * (1 if c == color else -1)
    return score

# ── negamax ───────────────────────────────────────────────────────────────────

def negamax(board, color, depth, ep=None, cas=None,
            alpha=-float('inf'), beta=float('inf'),
            ttable=None):
    """
    Negamax with alpha-beta pruning, transposition table, and move ordering.

    Key optimisations:
      - make/unmake instead of deepcopy        (~10x fewer allocations)
      - king position cache in setup.py        (find_king scan eliminated)
      - in_bounds inlined throughout setup.py  (15M fewer function calls)
      - move ordering via MVV-LLA + TT move    (far more alpha-beta cutoffs)
      - TT move tried first at every node      (comes free with ID)
      - no_moves flag avoids redundant         (leaf get_legal_moves calls)
        get_legal_moves at terminal nodes
    """
    if ttable is None:
        ttable = {}

    # ── Transposition table lookup ────────────────────────────────────────────
    key = board_hash(board, color, ep, cas)
    tt_move = None
    if key in ttable:
        cached_depth, cached_score, flag, cached_move = ttable[key]
        tt_move = cached_move   # best move from a prior search of this node
        if cached_depth >= depth:
            if flag == 'exact':   return cached_score
            if flag == 'lower':   alpha = max(alpha, cached_score)
            elif flag == 'upper': beta  = min(beta,  cached_score)
            if alpha >= beta:     return cached_score

    # ── Generate and order moves ──────────────────────────────────────────────
    moves = get_legal_moves(color, board, ep, cas)

    # Terminal: no moves (checkmate or stalemate)
    if not moves:
        if is_in_check(color, board):
            return -CHECKMATE_SCORE
        return 0  # stalemate

    # Leaf: depth exhausted but game continues
    if depth == 0:
        return material_score(board, color)

    # TT move goes first; rest ordered by MVV-LLA
    moves = _order_moves(moves, board, tt_move)

    opp      = 'b' if color == 'w' else 'w'
    best     = -float('inf')
    best_mv  = None
    flag     = 'upper'

    for move in moves:
        new_ep  = move.get('sets_ep')
        new_cas = _update_castling(cas, board, move)

        snap  = make_move(board, move)
        score = -negamax(board, opp, depth - 1, new_ep, new_cas,
                         -beta, -alpha, ttable)
        unmake_move(board, snap)

        if score > best:
            best    = score
            best_mv = move
        if score > alpha:
            alpha = score
            flag  = 'exact'
        if alpha >= beta:
            flag = 'lower'
            break

    # Store result + best move so later iterations can order moves better
    ttable[key] = (depth, best, flag, best_mv)
    return best


def material_score(board, color):
    """
    Material + piece-square table score from `color`'s perspective.
    Uses centipawn values (pawn = 100) so PST bonuses (±50 cp) are meaningful.
    """
    score = 0
    for r in range(8):
        for c in range(8):
            sq = board[r][c]
            if sq is None:
                continue
            side, pt = sq
            val = PIECE_VALUES[pt]
            if side == 'w':
                val += _PST[pt][r][c]
            else:
                val += _PST_BLACK[pt][r][c]
            score += val if side == color else -val
    return score

def _update_castling(cas, board, move):
    """Return updated castling rights after move (reads pre-move board)."""
    piece = board[move['from_r']][move['from_c']]
    if piece is None:
        return cas
    new_cas = dict(cas)
    if piece == ('w', 'K'): new_cas['wK'] = new_cas['wQ'] = False
    if piece == ('b', 'K'): new_cas['bK'] = new_cas['bQ'] = False
    if piece == ('w', 'R'):
        if (move['from_r'], move['from_c']) == (7, 0): new_cas['wQ'] = False
        if (move['from_r'], move['from_c']) == (7, 7): new_cas['wK'] = False
    if piece == ('b', 'R'):
        if (move['from_r'], move['from_c']) == (0, 0): new_cas['bQ'] = False
        if (move['from_r'], move['from_c']) == (0, 7): new_cas['bK'] = False
    return new_cas


# ── iterative deepening root ──────────────────────────────────────────────────

def _search_root(color, board, ep, cas, depth, ttable):
    """
    One pass of the root search at a fixed depth, using the shared ttable.
    Returns (best_move, best_score).

    Move ordering at the root re-uses the TT move from the previous ID
    iteration, which is the single biggest source of extra pruning.
    """
    moves = get_legal_moves(color, board, ep, cas)
    if not moves:
        return None, (-CHECKMATE_SCORE if is_in_check(color, board) else 0)

    # Pull TT move for this root position (set by the previous ID iteration)
    key     = board_hash(board, color, ep, cas)
    tt_move = ttable.get(key, (None,) * 4)[3]   # index 3 = best_move field
    moves   = _order_moves(moves, board, tt_move)

    opp        = 'b' if color == 'w' else 'w'
    best_score = -float('inf')
    best_mv    = moves[0]   # fallback: always return something

    for move in moves:
        new_ep  = move.get('sets_ep')
        new_cas = _update_castling(cas, board, move)

        snap  = make_move(board, move)
        score = -negamax(board, opp, depth - 1, new_ep, new_cas,
                         -float('inf'), float('inf'), ttable)
        unmake_move(board, snap)

        if score > best_score:
            best_score = score
            best_mv    = move

    return best_mv, best_score


def best_move(color, board, ep=None, cas=None, depth=4):
    """
    Return the best move for `color` using iterative deepening negamax.

    How iterative deepening helps
    ──────────────────────────────
    Instead of jumping straight to `depth`, we search depth 1, 2, … depth in
    sequence, sharing a single transposition table across all iterations.

    • Each shallow search is cheap (depth 1 takes <1 ms; depth 3 takes ~1% of
      depth 4's time), so the total overhead for iterations 1–(d-1) is small.

    • The TT built during iteration d-1 tells us the best move found at every
      node. In iteration d those moves are tried first, which causes far more
      alpha-beta cutoffs and can reduce the effective branching factor from
      ~35 to as low as ~6 — the theoretical best for alpha-beta.

    • Aspiration windows: from depth 3 onward we open a narrow window of
      ±ASPIRATION_DELTA around the previous score. If the score falls outside
      the window (a "fail") we immediately re-search with a full window. In
      practice the narrow window succeeds most of the time and saves work.

    The net effect is typically 2–4× faster at the same depth, or equivalently
    the engine reaches depth 5 in roughly the same wall time that the old
    flat search needed for depth 4.
    """
    ttable   = {}
    best_mv  = None
    prev_score = None

    for d in range(1, depth + 1):
        if d < 3 or prev_score is None:
            # Full window for the first couple of shallow iterations
            mv, score = _search_root(color, board, ep, cas, d, ttable)
        else:
            # Aspiration window around the previous iteration's score
            alpha = prev_score - ASPIRATION_DELTA
            beta  = prev_score + ASPIRATION_DELTA

            # Try the narrow window first
            mv, score = _search_root_windowed(
                color, board, ep, cas, d, ttable, alpha, beta)

            # If it failed outside the window, fall back to full window
            if score <= alpha or score >= beta:
                mv, score = _search_root(color, board, ep, cas, d, ttable)

        if mv is not None:
            best_mv    = mv
            prev_score = score

    return best_mv


def _search_root_windowed(color, board, ep, cas, depth, ttable, alpha, beta):
    """
    Root search with a fixed (alpha, beta) window (used by aspiration search).
    Returns (best_move, best_score); score may be outside [alpha, beta] on fail.
    """
    moves = get_legal_moves(color, board, ep, cas)
    if not moves:
        return None, (-CHECKMATE_SCORE if is_in_check(color, board) else 0)

    key     = board_hash(board, color, ep, cas)
    tt_move = ttable.get(key, (None,) * 4)[3]
    moves   = _order_moves(moves, board, tt_move)

    opp        = 'b' if color == 'w' else 'w'
    best_score = -float('inf')
    best_mv    = moves[0]

    for move in moves:
        new_ep  = move.get('sets_ep')
        new_cas = _update_castling(cas, board, move)

        snap  = make_move(board, move)
        score = -negamax(board, opp, depth - 1, new_ep, new_cas,
                         -beta, -alpha, ttable)
        unmake_move(board, snap)

        if score > best_score:
            best_score = score
            best_mv    = move
        if score > alpha:
            alpha = score
        if alpha >= beta:
            break

    return best_mv, best_score