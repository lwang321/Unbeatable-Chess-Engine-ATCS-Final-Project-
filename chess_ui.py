import pygame
import sys
import os
import io
from copy import deepcopy
from setup import (
    _init_king_pos,
    init_board, get_legal_moves, do_move,
    move_to_notation, square_name, is_in_check,
    castling_rights as default_castling
)
from openings import get_book, move_to_uci, uci_to_move
from chessbot1 import best_move

# ── constants ─────────────────────────────────────────────────────────────────
# These are computed dynamically in main() after pygame detects the display.
# The module-level values below are fallbacks; main() overwrites them globally.

SQ       = 80          # square size px  (overwritten at runtime)
BOARD_W  = SQ * 8
PANEL_W  = 220
WIN_W    = BOARD_W + PANEL_W
WIN_H    = BOARD_W


def _compute_layout():
    """
    Detect the desktop resolution and choose square/panel sizes so the window
    fills the screen without overflowing.  Returns (SQ, BOARD_W, PANEL_W,
    WIN_W, WIN_H) as ints.
    """
    info = pygame.display.Info()
    screen_w, screen_h = info.current_w, info.current_h

    # Leave a small margin for OS taskbars / title bars
    usable_h = int(screen_h * 0.97)
    usable_w = int(screen_w * 0.97)

    # Square size is limited by height (8 squares) and
    # must leave room for the side panel on the right.
    # We try panel_w = 15% of usable_w, min 200 px, max 320 px.
    panel_w = max(200, min(320, int(usable_w * 0.15)))

    sq = (usable_h) // 8                   # fit board vertically
    sq = min(sq, (usable_w - panel_w) // 8)  # and horizontally

    board_w = sq * 8
    win_w   = board_w + panel_w
    win_h   = board_w
    return sq, board_w, panel_w, win_w, win_h

LIGHT    = (240, 217, 181)
DARK     = (181, 136,  99)
SEL      = ( 20, 100, 200, 160)
LEGAL_DOT= ( 20, 100, 200,  90)
CAPTURE  = ( 20, 100, 200, 130)
CHECK    = (220,  40,  40, 160)
LAST_MOV = (205, 210,  55, 120)
PANEL_BG = ( 30,  30,  30)
TEXT_COL = (220, 220, 220)
TEXT_DIM = (130, 130, 130)

# ── bot settings ──────────────────────────────────────────────────────────────

BOT_COLOR  = 'b'          # which side the engine plays
BOT_DEPTH  = 4            # negamax search depth
BOT_DELAY  = 400          # ms pause before the bot plays (feels more natural)
BOT_MOVE_EVENT = pygame.USEREVENT + 1  # custom event to trigger bot move

# SVG filename mapping: (color, type) -> e.g. 'king-w.svg'
PNG_NAMES = {
    ('w','K'):'white-king',   ('w','Q'):'white-queen',  ('w','R'):'white-rook',
    ('w','B'):'white-bishop', ('w','N'):'white-knight', ('w','P'):'white-pawn',
    ('b','K'):'black-king',   ('b','Q'):'black-queen',  ('b','R'):'black-rook',
    ('b','B'):'black-bishop', ('b','N'):'black-knight', ('b','P'):'black-pawn',
}

UNICODE = {
    ('w','K'):'♔', ('w','Q'):'♕', ('w','R'):'♖',
    ('w','B'):'♗', ('w','N'):'♘', ('w','P'):'♙',
    ('b','K'):'♚', ('b','Q'):'♛', ('b','R'):'♜',
    ('b','B'):'♝', ('b','N'):'♞', ('b','P'):'♟',
}

def load_piece_images(png_dir, size):
    images = {}
    for key, name in PNG_NAMES.items():
        path = os.path.join(png_dir, f'{name}.png')
        if not os.path.exists(path):
            images[key] = None
            continue
        surf = pygame.image.load(path).convert_alpha()
        surf = pygame.transform.smoothscale(surf, (size, size))
        images[key] = surf
    return images

# ── helpers ───────────────────────────────────────────────────────────────────

def sq_to_px(r, c, flipped=False):
    if flipped:
        return ((7 - c) * SQ, (7 - r) * SQ)
    return (c * SQ, r * SQ)

def px_to_sq(x, y, flipped=False):
    c, r = x // SQ, y // SQ
    if flipped:
        return 7 - r, 7 - c
    return r, c

def draw_text(surf, text, font, color, x, y, anchor='topleft'):
    img = font.render(text, True, color)
    rect = img.get_rect(**{anchor: (x, y)})
    surf.blit(img, rect)

# ── bot logic ─────────────────────────────────────────────────────────────────

def bot_move(game):
    """
    Choose a move for BOT_COLOR.
    1. If the current position is in the opening book, play a weighted-random
       book move (same trie lookup used for the hint highlights).
    2. Once we leave book, delegate to best_move() (negamax + alpha-beta).
    Returns a move dict, or None if no legal moves.
    """
    book = game._book
    book_uci, _ = book.suggest(game.uci_log)

    if book_uci:
        # Convert UCI → move dict, then find the matching legal move so we get
        # all the extra fields (castle, en_passant_capture, sets_ep, etc.)
        partial = uci_to_move(book_uci)
        for m in game._legal:
            if (m['from_r'] == partial['from_r'] and
                m['from_c'] == partial['from_c'] and
                m['to_r']   == partial['to_r']   and
                m['to_c']   == partial['to_c']):
                return m          # book move found in legal list
        # book move wasn't legal (shouldn't happen, but fall through)

    # Off book — use the engine
    return best_move(BOT_COLOR, game.board, game.ep, game.cas, depth=BOT_DEPTH)


# ── game state ────────────────────────────────────────────────────────────────

class Game:
    def __init__(self):
        self._book = get_book()
        self.reset()

    def reset(self):
        self.board   = init_board()
        _init_king_pos(self.board)
        self.ep      = None
        self.cas     = default_castling.copy()
        self.turn    = 'w'
        self.history = []          # list of (board, ep, cas, notation)
        self.move_log= []          # notation strings
        self.uci_log = []          # UCI strings for book lookups
        self.status  = 'playing'   # 'playing' | 'checkmate' | 'stalemate'
        self.last_move = None      # (fr, fc, tr, tc)
        self.bot_thinking = False  # True while bot move is pending
        self._cache_legal()
        self._update_book()

    def _cache_legal(self):
        self._legal = get_legal_moves(self.turn, self.board, self.ep, self.cas)
        self._legal_for = {}
        for m in self._legal:
            key = (m['from_r'], m['from_c'])
            self._legal_for.setdefault(key, []).append(m)

    def _update_book(self):
        """Refresh book suggestion and opening name from the current move sequence."""
        book = self._book
        self.opening_name = book.best_name(self.uci_log) or ""
        uci, _ = book.suggest(self.uci_log)
        if uci:
            from openings import uci_to_move
            m = uci_to_move(uci)
            self.book_hint = (m['from_r'], m['from_c'], m['to_r'], m['to_c'])
            self.book_hint_uci = uci
        else:
            self.book_hint = None
            self.book_hint_uci = None

    def legal_for(self, r, c):
        return self._legal_for.get((r, c), [])

    def apply(self, move):
        note = move_to_notation(move, self.board)
        self.history.append((deepcopy(self.board), self.ep, deepcopy(self.cas), note, list(self.uci_log)))
        self.board, self.ep, self.cas = do_move(move, self.board, self.ep, self.cas)
        self.last_move = (move['from_r'], move['from_c'], move['to_r'], move['to_c'])
        self.uci_log.append(move_to_uci(move))
        self.turn = 'b' if self.turn == 'w' else 'w'
        self._cache_legal()
        # check game over
        if not self._legal:
            if is_in_check(self.turn, self.board):
                self.status = 'checkmate'
            else:
                self.status = 'stalemate'
        # annotate check
        if is_in_check(self.turn, self.board):
            note += '+'
        self.move_log.append(note)
        self._update_book()

    def undo(self):
        if not self.history:
            return
        self.board, self.ep, self.cas, _, saved_uci = self.history.pop()
        if self.move_log:
            self.move_log.pop()
        self.uci_log = saved_uci
        self.turn = 'b' if self.turn == 'w' else 'w'
        self.last_move = None
        self.status = 'playing'
        self._cache_legal()
        self._update_book()

# ── renderer ──────────────────────────────────────────────────────────────────

class Renderer:
    def __init__(self, screen, game, piece_images=None):
        self.screen       = screen
        self.game         = game
        self.flipped      = False
        self.piece_images = piece_images or {}   # (color,type) -> Surface|None

        # fallback unicode font (used if SVG unavailable for a piece)
        candidates = ['segoe ui', 'dejavusans', 'arial unicode ms',
                      'noto sans', 'freesans', 'liberationsans', None]
        self.piece_font = None
        for name in candidates:
            try:
                f = pygame.font.SysFont(name, int(SQ * 0.82), bold=False)
                if f.size('♔')[0] > 10:
                    self.piece_font = f
                    break
            except Exception:
                pass
        if not self.piece_font:
            self.piece_font = pygame.font.Font(None, int(SQ * 0.82))

        self.coord_font = pygame.font.SysFont('consolas,monospace', max(11, SQ // 6))
        self.ui_font    = pygame.font.SysFont('consolas,monospace', max(12, SQ // 6))
        self.big_font   = pygame.font.SysFont('consolas,monospace', max(16, SQ // 5), bold=True)

        # surfaces for tinted overlays
        self._sel_surf     = pygame.Surface((SQ, SQ), pygame.SRCALPHA)
        self._sel_surf.fill(SEL)
        self._cap_surf     = pygame.Surface((SQ, SQ), pygame.SRCALPHA)
        self._cap_surf.fill(CAPTURE)
        self._chk_surf     = pygame.Surface((SQ, SQ), pygame.SRCALPHA)
        self._chk_surf.fill(CHECK)
        self._last_surf    = pygame.Surface((SQ, SQ), pygame.SRCALPHA)
        self._last_surf.fill(LAST_MOV)

    def _draw_piece(self, surf, piece, px, py, cx_override=None, cy_override=None):
        """Blit a piece image (SVG) or fallback to unicode glyph."""
        img = self.piece_images.get(piece)
        if img:
            pad = 4
            scaled = pygame.transform.smoothscale(img, (SQ - pad*2, SQ - pad*2))
            x = (cx_override - (SQ - pad*2)//2) if cx_override else px + pad
            y = (cy_override - (SQ - pad*2)//2) if cy_override else py + pad
            surf.blit(scaled, (x, y))
        else:
            # unicode fallback
            sym = UNICODE[piece]
            glyph = self.piece_font.render(sym, True,
                    (255,255,255) if piece[0]=='w' else (20,20,20))
            shadow = self.piece_font.render(sym, True,
                     (80,80,80)   if piece[0]=='w' else (0,0,0))
            if cx_override:
                gx = cx_override - glyph.get_width()//2
                gy = cy_override - glyph.get_height()//2
            else:
                gx = px + (SQ - glyph.get_width()) // 2
                gy = py + (SQ - glyph.get_height()) // 2
            surf.blit(shadow, (gx+2, gy+2))
            surf.blit(glyph, (gx, gy))


    def draw(self, selected, drag_piece, drag_pos, hover_sq):
        g = self.game
        scr = self.screen
        scr.fill(PANEL_BG)

        # ── board squares ──
        for r in range(8):
            for c in range(8):
                px, py = sq_to_px(r, c, self.flipped)
                color = LIGHT if (r + c) % 2 == 0 else DARK
                pygame.draw.rect(scr, color, (px, py, SQ, SQ))

        # ── last move highlight ──
        if g.last_move:
            for (r, c) in [(g.last_move[0], g.last_move[1]),
                           (g.last_move[2], g.last_move[3])]:
                px, py = sq_to_px(r, c, self.flipped)
                scr.blit(self._last_surf, (px, py))

        # ── check highlight ──
        if g.status == 'playing' and is_in_check(g.turn, g.board):
            from setup import find_king
            kr, kc = find_king(g.turn, g.board)
            px, py = sq_to_px(kr, kc, self.flipped)
            scr.blit(self._chk_surf, (px, py))

        # ── selected square ──
        if selected:
            sr, sc = selected
            px, py = sq_to_px(sr, sc, self.flipped)
            scr.blit(self._sel_surf, (px, py))

            # legal move dots / rings
            for m in g.legal_for(sr, sc):
                tr, tc = m['to_r'], m['to_c']
                tx, ty = sq_to_px(tr, tc, self.flipped)
                cx, cy = tx + SQ//2, ty + SQ//2
                if g.board[tr][tc]:  # capture ring
                    scr.blit(self._cap_surf, (tx, ty))
                    pygame.draw.circle(scr, (*LEGAL_DOT[:3], 200),
                                       (cx, cy), SQ//2 - 3, 5)
                else:
                    dot_surf = pygame.Surface((SQ, SQ), pygame.SRCALPHA)
                    pygame.draw.circle(dot_surf, LEGAL_DOT, (SQ//2, SQ//2), SQ//5)
                    scr.blit(dot_surf, (tx, ty))

        # ── pieces (skip dragged piece) ──
        for r in range(8):
            for c in range(8):
                piece = g.board[r][c]
                if not piece:
                    continue
                if drag_piece and selected == (r, c):
                    continue
                px, py = sq_to_px(r, c, self.flipped)
                self._draw_piece(scr, piece, px, py)

        # ── dragged piece follows cursor ──
        if drag_piece and drag_pos:
            self._draw_piece(scr, drag_piece, 0, 0,
                             cx_override=drag_pos[0], cy_override=drag_pos[1])

        # ── coordinates ──
        files = 'abcdefgh'
        ranks = '87654321'
        if self.flipped:
            files = files[::-1]
            ranks = ranks[::-1]
        for i in range(8):
            col = DARK if i % 2 == 0 else LIGHT
            draw_text(scr, ranks[i], self.coord_font, col, 3, i*SQ+3)
            draw_text(scr, files[i], self.coord_font, col,
                      i*SQ + SQ - self.coord_font.size(files[i])[0] - 3,
                      BOARD_W - self.coord_font.get_height() - 3)

        # ── panel ──
        self._draw_panel()

        pygame.display.flip()

    def _draw_panel(self):
        g = self.game
        scr = self.screen
        px = BOARD_W + 10
        py = 10

        # turn indicator
        who = 'White' if g.turn == 'w' else 'Black'
        if g.status == 'checkmate':
            winner = 'Black' if g.turn == 'w' else 'White'
            draw_text(scr, 'CHECKMATE', self.big_font, (220,80,80), px, py)
            py += 28
            draw_text(scr, f'{winner} wins', self.ui_font, TEXT_COL, px, py)
        elif g.status == 'stalemate':
            draw_text(scr, 'STALEMATE', self.big_font, (180,180,80), px, py)
            py += 28
            draw_text(scr, 'Draw', self.ui_font, TEXT_COL, px, py)
        else:
            dot_col = (240,240,240) if g.turn=='w' else (40,40,40)
            dot_border = (180,180,180)
            pygame.draw.circle(scr, dot_border, (px+10, py+10), 11)
            pygame.draw.circle(scr, dot_col, (px+10, py+10), 9)
            draw_text(scr, f"{who} to move", self.ui_font, TEXT_COL, px+26, py+2)
            if is_in_check(g.turn, g.board):
                py += 22
                draw_text(scr, 'CHECK', self.ui_font, (220,80,80), px, py)
        py += 30

        # ── bot status ────────────────────────────────────────────────────────
        in_book = bool(g.book_hint_uci)
        if g.turn == BOT_COLOR and g.status == 'playing':
            if g.bot_thinking:
                label = 'Bot: Thinking...' if not in_book else 'Bot: Book move...'
                draw_text(scr, label, self.coord_font, (180, 180, 80), px, py)
            else:
                src = 'Book' if in_book else 'Engine'
                draw_text(scr, f'Bot ({src})', self.coord_font, (150, 150, 220), px, py)
        else:
            draw_text(scr, 'Your turn', self.coord_font, TEXT_DIM, px, py)
        py += 18

        # ── opening name ──────────────────────────────────────────────────────
        pygame.draw.line(scr, (70,70,70), (px, py), (px + PANEL_W - 20, py))
        py += 8
        if g.opening_name:
            # word-wrap the opening name to fit the panel
            words = g.opening_name.split()
            line1, line2 = "", ""
            for w in words:
                test = (line1 + " " + w).strip()
                if self.coord_font.size(test)[0] <= PANEL_W - 20:
                    line1 = test
                else:
                    line2 = (line2 + " " + w).strip()
            draw_text(scr, line1, self.coord_font, (100, 200, 130), px, py)
            py += 16
            if line2:
                draw_text(scr, line2, self.coord_font, (100, 200, 130), px, py)
                py += 16
        else:
            draw_text(scr, 'Off book', self.coord_font, TEXT_DIM, px, py)
            py += 16

        # book hint text
        if g.book_hint_uci and g.status == 'playing':
            draw_text(scr, f'Book: {g.book_hint_uci}', self.coord_font, (80,160,100), px, py)
            py += 16
        py += 4

        # divider
        pygame.draw.line(scr, (70,70,70), (px, py), (px + PANEL_W - 20, py))
        py += 10

        # move log
        draw_text(scr, 'Moves', self.coord_font, TEXT_DIM, px, py)
        py += 18
        log = g.move_log
        # show last 18 moves (9 pairs)
        pairs = []
        for i in range(0, len(log), 2):
            w = log[i]
            b = log[i+1] if i+1 < len(log) else ''
            pairs.append((i//2+1, w, b))
        visible = pairs[-12:]
        for num, w, b in visible:
            draw_text(scr, f"{num:>3}.", self.coord_font, TEXT_DIM, px, py)
            draw_text(scr, w, self.coord_font, TEXT_COL, px+32, py)
            draw_text(scr, b, self.coord_font, TEXT_COL, px+95, py)
            py += 17
        py += 6

        # buttons
        btn_w = max(90, SQ)
        self._btn_undo  = self._draw_button(scr, 'Undo',  px, WIN_H - 80)
        self._btn_reset = self._draw_button(scr, 'Reset', px, WIN_H - 46)
        self._btn_flip  = self._draw_button(scr, 'Flip',  px + btn_w + 15, WIN_H - 80)

    def _draw_button(self, surf, label, x, y):
        w, h = max(90, SQ), max(28, SQ // 3)
        rect = pygame.Rect(x, y, w, h)
        pygame.draw.rect(surf, (60,60,60), rect, border_radius=5)
        pygame.draw.rect(surf, (100,100,100), rect, width=1, border_radius=5)
        draw_text(surf, label, self.ui_font, TEXT_COL, x + w//2, y + h//2, anchor='center')
        return rect

    def hit_button(self, pos):
        if hasattr(self, '_btn_undo')  and self._btn_undo.collidepoint(pos):  return 'undo'
        if hasattr(self, '_btn_reset') and self._btn_reset.collidepoint(pos): return 'reset'
        if hasattr(self, '_btn_flip')  and self._btn_flip.collidepoint(pos):  return 'flip'
        return None

# ── main loop ─────────────────────────────────────────────────────────────────

def main():
    global SQ, BOARD_W, PANEL_W, WIN_W, WIN_H

    pygame.init()

    # Detect screen size before creating the window
    SQ, BOARD_W, PANEL_W, WIN_W, WIN_H = _compute_layout()

    # Open in borderless fullscreen (scaled to our computed size)
    screen = pygame.display.set_mode((WIN_W, WIN_H), pygame.NOFRAME)
    pygame.display.set_caption('Chess')
    clock = pygame.time.Clock()

    # Locate pieces-basic-svg/ folder: same dir as this script, or cwd
    script_dir = os.path.dirname(os.path.abspath(__file__))
    png_dir = None
    for candidate in [
        os.path.join(script_dir, 'pieces-basic-png'),
        os.path.join(os.getcwd(),  'pieces-basic-png'),
    ]:
        if os.path.isdir(candidate):
            png_dir = candidate
            break

    piece_images = {}
    if png_dir:
        print(f'Loading PNG pieces from: {png_dir}')
        piece_images = load_piece_images(png_dir, SQ)
        loaded = sum(1 for v in piece_images.values() if v)
        print(f'  {loaded}/12 pieces loaded')
    else:
        print('pieces-basic-svg/ folder not found — using unicode fallback')

    game     = Game()
    renderer = Renderer(screen, game, piece_images)

    selected   = None   # (r, c) of clicked square
    drag_piece = None   # piece being dragged
    drag_pos   = None   # current mouse pos while dragging
    drag_origin= None   # (r, c) where drag started
    hover_sq   = None

    def try_move(from_sq, to_sq):
        if not from_sq or not to_sq:
            return False
        moves = game.legal_for(from_sq[0], from_sq[1])
        for m in moves:
            if (m['to_r'], m['to_c']) == to_sq:
                game.apply(m)
                # Schedule bot reply if it's now the bot's turn
                if game.turn == BOT_COLOR and game.status == 'playing':
                    game.bot_thinking = True
                    pygame.time.set_timer(BOT_MOVE_EVENT, BOT_DELAY, loops=1)
                return True
        return False

    def schedule_bot_if_needed():
        """Fire bot immediately at game start if bot plays white."""
        if game.turn == BOT_COLOR and game.status == 'playing':
            game.bot_thinking = True
            pygame.time.set_timer(BOT_MOVE_EVENT, BOT_DELAY, loops=1)

    def on_board(pos):
        return pos[0] < BOARD_W

    running = True
    while running:
        mx, my = pygame.mouse.get_pos()
        if on_board((mx, my)):
            hover_sq = px_to_sq(mx, my, renderer.flipped)
        else:
            hover_sq = None

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_F1:
                    pygame.display.toggle_fullscreen()
                elif event.key == pygame.K_z and (event.mod & pygame.KMOD_META or event.mod & pygame.KMOD_CTRL):
                    pygame.time.set_timer(BOT_MOVE_EVENT, 0)  # cancel pending bot
                    game.undo()
                    # undo bot's last move too so human gets their position back
                    if game.turn == BOT_COLOR and game.history:
                        game.undo()
                    game.bot_thinking = False
                    selected = drag_piece = None
                elif event.key == pygame.K_r:
                    pygame.time.set_timer(BOT_MOVE_EVENT, 0)
                    game.reset()
                    game.bot_thinking = False
                    selected = drag_piece = None
                    schedule_bot_if_needed()
                elif event.key == pygame.K_f:
                    renderer.flipped = not renderer.flipped

            elif event.type == BOT_MOVE_EVENT:
                # Bot's turn — pick and apply a move
                if game.turn == BOT_COLOR and game.status == 'playing':
                    mv = bot_move(game)
                    if mv:
                        game.apply(mv)
                game.bot_thinking = False

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                pos = event.pos
                # panel buttons
                btn = renderer.hit_button(pos)
                if btn == 'undo':
                    pygame.time.set_timer(BOT_MOVE_EVENT, 0)
                    game.undo()
                    if game.turn == BOT_COLOR and game.history:
                        game.undo()
                    game.bot_thinking = False
                    selected = drag_piece = None; continue
                if btn == 'reset':
                    pygame.time.set_timer(BOT_MOVE_EVENT, 0)
                    game.reset()
                    game.bot_thinking = False
                    selected = drag_piece = None
                    schedule_bot_if_needed()
                    continue
                if btn == 'flip':
                    renderer.flipped = not renderer.flipped; continue

                if not on_board(pos) or game.status != 'playing':
                    continue
                # Block input while bot is thinking or it's the bot's turn
                if game.turn == BOT_COLOR or game.bot_thinking:
                    continue

                r, c = px_to_sq(pos[0], pos[1], renderer.flipped)
                piece = game.board[r][c]

                if piece and piece[0] == game.turn:
                    # start drag / selection
                    selected    = (r, c)
                    drag_piece  = piece
                    drag_origin = (r, c)
                    drag_pos    = pos
                elif selected:
                    # click-to-move
                    if not try_move(selected, (r, c)):
                        # clicked empty/own square — deselect
                        selected = None
                    else:
                        selected = None
                    drag_piece = None

            elif event.type == pygame.MOUSEMOTION:
                if drag_piece:
                    drag_pos = event.pos

            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                if drag_piece and on_board(event.pos):
                    r, c = px_to_sq(event.pos[0], event.pos[1], renderer.flipped)
                    dest = (r, c)
                    if dest != drag_origin:
                        if try_move(drag_origin, dest):
                            selected = None
                        # else keep selected for click-to-move
                drag_piece = None
                drag_pos   = None

        renderer.draw(selected, drag_piece, drag_pos, hover_sq)
        clock.tick(60)

    pygame.quit()
    sys.exit()

if __name__ == '__main__':
    main()