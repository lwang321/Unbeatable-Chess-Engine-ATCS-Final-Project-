from setup import is_in_check, get_legal_moves

# ── piece values ──────────────────────────────────────────────────────────────

PIECE_VALUES = {
	'P': 1,
	'N': 3,
	'B': 3,
	'R': 5,
	'Q': 9,
	'K': 0,   # King has no material value; checkmate is handled separately
}

CHECKMATE_SCORE = 10_000

# ── scoring ───────────────────────────────────────────────────────────────────

def abs_score(board, ep=None, cas=None):
	"""
	Return a numeric evaluation of the board from White's perspective.

	Positive  → White is better.
	Negative  → Black is better.
	+/-10_000 → Checkmate (sign indicates who is mated).

	Steps:
	  1. Detect checkmate for either side.
	  2. Otherwise, sum piece values: white pieces add, black pieces subtract.
	"""
	# ── 1. Checkmate detection ────────────────────────────────────────────────
	# A side is in checkmate when it is in check AND has no legal moves.
	for color, sign in (('w', -1), ('b', +1)):
		if is_in_check(color, board):
			legal = get_legal_moves(color, board, ep, cas)
			if not legal:
				# `color` is mated → the *other* side wins
				# White mated → very negative; Black mated → very positive
				return sign * CHECKMATE_SCORE

	# ── 2. Material balance ───────────────────────────────────────────────────
	score = 0
	for row in board:
		for square in row:
			if square is None:
				continue
			color, piece_type = square
			value = PIECE_VALUES[piece_type]
			score += value if color == 'w' else -value

	return score


