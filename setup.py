def init_board():
    board = [[None] * 8 for _ in range(8)]
    back_row = ['R', 'N', 'B', 'Q', 'K', 'B', 'N', 'R']
    for c in range(8):
        board[0][c] = ('b', back_row[c])
        board[1][c] = ('b', 'P')
        board[6][c] = ('w', 'P')
        board[7][c] = ('w', back_row[c])
    return board

    return score

def print_board(board):
    symbols = {
        ('w','K'):'♔', ('w','Q'):'♕', ('w','R'):'♖',
        ('w','B'):'♗', ('w','N'):'♘', ('w','P'):'♙',
        ('b','K'):'♚', ('b','Q'):'♛', ('b','R'):'♜',
        ('b','B'):'♝', ('b','N'):'♞', ('b','P'):'♟',
        None: '·'
    }
    for r, row in enumerate(board):
        print(f"{8-r}  " + "  ".join(symbols[sq] for sq in row))
    print("   " + "  ".join("abcdefgh"))


# Board is an 8x8 list of tuples ('w'|'b', 'K'|'Q'|'R'|'B'|'N'|'P') or None
# (0,0) = a8 (top-left), (7,7) = h1 (bottom-right)

board = [[None] * 8 for _ in range(8)]
back_row = ['R', 'N', 'B', 'Q', 'K', 'B', 'N', 'R']
for c in range(8):
    board[0][c] = ('b', back_row[c])
    board[1][c] = ('b', 'P')
    board[6][c] = ('w', 'P')
    board[7][c] = ('w', back_row[c])

# Game state (global)
en_passant_target = None
castling_rights = {'wK': True, 'wQ': True, 'bK': True, 'bQ': True}


def piece_color(square):
    return square[0] if square else None


def find_king(color, b):
    for r in range(8):
        for c in range(8):
            if b[r][c] == (color, 'K'):
                return r, c
    return None


def apply_move(b, move, ep=None, cas=None):
    """
    Return a new deep-copied board after applying move dict.
    Used by do_move() for actual game state updates (UI layer).
    NOT used during search — see make_move/unmake_move below.
    """
    nb = [row[:] for row in b]
    fr, fc, tr, tc = move['from_r'], move['from_c'], move['to_r'], move['to_c']
    piece = nb[fr][fc]
    nb[tr][tc] = piece
    nb[fr][fc] = None

    if move.get('en_passant_capture'):
        cr, cc = move['en_passant_capture']
        nb[cr][cc] = None

    if move.get('castle'):
        row = tr
        if move['castle'] == 'K':
            nb[row][5] = nb[row][7]
            nb[row][7] = None
        else:
            nb[row][3] = nb[row][0]
            nb[row][0] = None

    if piece and piece[1] == 'P' and tr in (0, 7):
        nb[tr][tc] = (piece[0], 'Q')

    return nb


# ── king position cache ───────────────────────────────────────────────────────
#
# is_in_check is called ~500k times per depth-4 search, and every call used
# to scan all 64 squares just to find the king.  Instead we maintain a small
# dict that tracks the king's square for each side and update it in make/unmake.
# This turns the 64-square scan into a single dict lookup.

_king_pos = {}   # {'w': (r,c), 'b': (r,c)} — kept in sync by make/unmake


def _init_king_pos(b):
    """Scan the board once to seed the king position cache."""
    for r in range(8):
        for c in range(8):
            sq = b[r][c]
            if sq and sq[1] == 'K':
                _king_pos[sq[0]] = (r, c)


# ── make / unmake (used only by search) ──────────────────────────────────────

def make_move(b, move):
    """
    Apply `move` to board `b` in place and update the king-position cache.
    Returns a snapshot tuple that unmake_move needs to fully reverse the op.
    """
    fr, fc = move['from_r'], move['from_c']
    tr, tc = move['to_r'],   move['to_c']

    orig_from = b[fr][fc]
    orig_to   = b[tr][tc]

    b[tr][tc] = orig_from
    b[fr][fc] = None

    # Update king cache if a king moved
    if orig_from and orig_from[1] == 'K':
        _king_pos[orig_from[0]] = (tr, tc)

    # En passant capture
    ep_capture_sq = ep_capture_pc = None
    if move.get('en_passant_capture'):
        cr, cc = move['en_passant_capture']
        ep_capture_sq = (cr, cc)
        ep_capture_pc = b[cr][cc]
        b[cr][cc] = None

    # Castling — slide the rook (king already moved above)
    rook_from = rook_to = rook_piece = None
    if move.get('castle'):
        row = tr
        if move['castle'] == 'K':
            rook_from = (row, 7);  rook_to = (row, 5)
        else:
            rook_from = (row, 0);  rook_to = (row, 3)
        rook_piece = b[rook_from[0]][rook_from[1]]
        b[rook_to[0]][rook_to[1]]     = rook_piece
        b[rook_from[0]][rook_from[1]] = None

    # Pawn promotion (auto-queen)
    if orig_from and orig_from[1] == 'P' and tr in (0, 7):
        b[tr][tc] = (orig_from[0], 'Q')

    return (fr, fc, tr, tc,
            orig_from, orig_to,
            ep_capture_sq, ep_capture_pc,
            rook_from, rook_to, rook_piece)


def unmake_move(b, snapshot):
    """Reverse a make_move call, restoring board and king-position cache."""
    (fr, fc, tr, tc,
     orig_from, orig_to,
     ep_capture_sq, ep_capture_pc,
     rook_from, rook_to, rook_piece) = snapshot

    b[fr][fc] = orig_from
    b[tr][tc] = orig_to

    # Restore king cache
    if orig_from and orig_from[1] == 'K':
        _king_pos[orig_from[0]] = (fr, fc)

    if ep_capture_sq:
        b[ep_capture_sq[0]][ep_capture_sq[1]] = ep_capture_pc

    if rook_from:
        b[rook_from[0]][rook_from[1]] = rook_piece
        b[rook_to[0]][rook_to[1]]     = None


# ── is_in_check (hot path — keep tight) ──────────────────────────────────────
#
# All in_bounds checks are inlined (0 <= r < 8 and 0 <= c < 8) rather than
# calling a function.  At 500k+ calls per search the call overhead adds up.

def is_in_check(color, b):
    """True if `color`'s king is under attack on board `b`."""
    pos = _king_pos.get(color)
    if pos is None:
        # Fallback: scan board (should only happen before cache is seeded)
        for r in range(8):
            for c in range(8):
                if b[r][c] == (color, 'K'):
                    pos = (r, c)
                    break
        if pos is None:
            return False
    kr, kc = pos
    opp = 'b' if color == 'w' else 'w'

    # Knight attacks
    for dr, dc in ((-2,-1),(-2,1),(-1,-2),(-1,2),(1,-2),(1,2),(2,-1),(2,1)):
        r, c = kr+dr, kc+dc
        if 0 <= r < 8 and 0 <= c < 8 and b[r][c] == (opp, 'N'):
            return True

    # Rook / queen on ranks & files
    for dr, dc in ((-1,0),(1,0),(0,-1),(0,1)):
        r, c = kr+dr, kc+dc
        while 0 <= r < 8 and 0 <= c < 8:
            sq = b[r][c]
            if sq:
                if sq[0] == opp and sq[1] in ('R', 'Q'):
                    return True
                break
            r += dr; c += dc

    # Bishop / queen on diagonals
    for dr, dc in ((-1,-1),(-1,1),(1,-1),(1,1)):
        r, c = kr+dr, kc+dc
        while 0 <= r < 8 and 0 <= c < 8:
            sq = b[r][c]
            if sq:
                if sq[0] == opp and sq[1] in ('B', 'Q'):
                    return True
                break
            r += dr; c += dc

    # Pawn attacks
    pawn_dr = -1 if color == 'w' else 1
    for dc in (-1, 1):
        r, c = kr + pawn_dr, kc + dc
        if 0 <= r < 8 and 0 <= c < 8 and b[r][c] == (opp, 'P'):
            return True

    # King proximity
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            r, c = kr+dr, kc+dc
            if 0 <= r < 8 and 0 <= c < 8 and b[r][c] == (opp, 'K'):
                return True

    return False


# ── move generation ───────────────────────────────────────────────────────────

def _raw_pseudo_moves(r, c, b, ep, cas):
    """Generate pseudo-legal moves for piece at (r, c). No check validation."""
    sq = b[r][c]
    if not sq:
        return []
    color, ptype = sq
    opp = 'b' if color == 'w' else 'w'
    moves = []

    def push(tr, tc, **extra):
        # Inline in_bounds and color check
        if 0 <= tr < 8 and 0 <= tc < 8:
            target = b[tr][tc]
            if target is None or target[0] != color:
                moves.append({'from_r': r, 'from_c': c, 'to_r': tr, 'to_c': tc, **extra})

    def slide(dr, dc):
        nr, nc = r+dr, c+dc
        while 0 <= nr < 8 and 0 <= nc < 8:
            sq2 = b[nr][nc]
            if sq2:
                if sq2[0] == opp:
                    moves.append({'from_r': r, 'from_c': c, 'to_r': nr, 'to_c': nc})
                break
            moves.append({'from_r': r, 'from_c': c, 'to_r': nr, 'to_c': nc})
            nr += dr; nc += dc

    if ptype == 'P':
        direction = -1 if color == 'w' else 1
        start_row = 6 if color == 'w' else 1

        nr = r + direction
        if 0 <= nr < 8 and not b[nr][c]:
            moves.append({'from_r': r, 'from_c': c, 'to_r': nr, 'to_c': c})
            nr2 = r + 2*direction
            if r == start_row and not b[nr2][c]:
                moves.append({
                    'from_r': r, 'from_c': c,
                    'to_r': nr2, 'to_c': c,
                    'sets_ep': (nr, c)
                })

        for dc in (-1, 1):
            tr, tc = r+direction, c+dc
            if 0 <= tr < 8 and 0 <= tc < 8:
                target = b[tr][tc]
                if target and target[0] == opp:
                    moves.append({'from_r': r, 'from_c': c, 'to_r': tr, 'to_c': tc})
                elif ep and (tr, tc) == ep:
                    moves.append({
                        'from_r': r, 'from_c': c, 'to_r': tr, 'to_c': tc,
                        'en_passant_capture': (r, tc)
                    })

    elif ptype == 'N':
        for dr, dc in ((-2,-1),(-2,1),(-1,-2),(-1,2),(1,-2),(1,2),(2,-1),(2,1)):
            push(r+dr, c+dc)

    elif ptype == 'B':
        for dr, dc in ((-1,-1),(-1,1),(1,-1),(1,1)):
            slide(dr, dc)

    elif ptype == 'R':
        for dr, dc in ((-1,0),(1,0),(0,-1),(0,1)):
            slide(dr, dc)

    elif ptype == 'Q':
        for dr, dc in ((-1,-1),(-1,1),(1,-1),(1,1),(-1,0),(1,0),(0,-1),(0,1)):
            slide(dr, dc)

    elif ptype == 'K':
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr != 0 or dc != 0:
                    push(r+dr, c+dc)

        king_row = 7 if color == 'w' else 0
        if r == king_row and c == 4 and not is_in_check(color, b):
            if cas.get(color+'K') and not b[king_row][5] and not b[king_row][6]:
                nb = apply_move(b, {'from_r':r,'from_c':c,'to_r':king_row,'to_c':5}, ep, cas)
                if not is_in_check(color, nb):
                    moves.append({'from_r': r, 'from_c': c, 'to_r': king_row, 'to_c': 6, 'castle': 'K'})
            if cas.get(color+'Q') and not b[king_row][3] and not b[king_row][2] and not b[king_row][1]:
                nb = apply_move(b, {'from_r':r,'from_c':c,'to_r':king_row,'to_c':3}, ep, cas)
                if not is_in_check(color, nb):
                    moves.append({'from_r': r, 'from_c': c, 'to_r': king_row, 'to_c': 2, 'castle': 'Q'})

    return moves


def get_legal_moves(color, b=None, ep=None, cas=None):
    """Return all legal moves for `color`, using make/unmake for check validation."""
    if b is None:
        b = board
    if ep is None:
        ep = en_passant_target
    if cas is None:
        cas = castling_rights

    legal = []
    for r in range(8):
        for c in range(8):
            sq = b[r][c]
            if sq and sq[0] == color:
                for move in _raw_pseudo_moves(r, c, b, ep, cas):
                    snap = make_move(b, move)
                    in_check = is_in_check(color, b)
                    unmake_move(b, snap)
                    if not in_check:
                        legal.append(move)
    return legal


# ── helpers ───────────────────────────────────────────────────────────────────

def square_name(r, c):
    return "abcdefgh"[c] + str(8 - r)

def move_to_notation(move, b):
    piece = b[move['from_r']][move['from_c']]
    prefix = '' if piece[1] == 'P' else piece[1]
    capture = 'x' if b[move['to_r']][move['to_c']] or move.get('en_passant_capture') else ''
    if move.get('castle'):
        return 'O-O' if move['castle'] == 'K' else 'O-O-O'
    return f"{prefix}{square_name(move['from_r'], move['from_c'])}{capture}{square_name(move['to_r'], move['to_c'])}"

def do_move(move, b=None, ep=None, cas=None):
    """
    Execute a move and return (new_board, new_ep, new_cas).
    Used by the UI/game layer — produces a fresh board copy so the
    original is untouched.  The search uses make_move/unmake_move instead.
    After applying, re-seed the king position cache for the new board state.
    """
    if b is None:
        b = board
    if ep is None:
        ep = en_passant_target
    if cas is None:
        cas = castling_rights

    nb = apply_move(b, move, ep, cas)

    new_ep = move.get('sets_ep')

    new_cas = dict(cas)
    piece = b[move['from_r']][move['from_c']]
    if piece == ('w', 'K'): new_cas['wK'] = new_cas['wQ'] = False
    if piece == ('b', 'K'): new_cas['bK'] = new_cas['bQ'] = False
    if piece == ('w', 'R'):
        if (move['from_r'], move['from_c']) == (7, 0): new_cas['wQ'] = False
        if (move['from_r'], move['from_c']) == (7, 7): new_cas['wK'] = False
    if piece == ('b', 'R'):
        if (move['from_r'], move['from_c']) == (0, 0): new_cas['bQ'] = False
        if (move['from_r'], move['from_c']) == (0, 7): new_cas['bK'] = False

    # Re-seed king cache for the new board (UI layer always uses fresh boards)
    _init_king_pos(nb)

    return nb, new_ep, new_cas

board = init_board()
_init_king_pos(board)   # seed cache for the initial position