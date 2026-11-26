"""
Share surfaces: the weekly recap image, the challenge completion card and
link previews. Every card carries a makeyourreps join link.

Public URLs carry a signed token, so a recap can be shared without exposing
the squad's id or anything beyond what the card shows.
"""
import io
from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.db.models import Sum

from squads import items
from squads.ledger import goal_progress, points_by_user
from squads.models import DayResult, DayStatus, LeaderboardWeek, SquadGoal

SALT = 'squads.share'


def token_for(kind, **data):
    return signing.dumps({'k': kind, **data}, salt=SALT, compress=True)


def read_token(token, kind):
    data = signing.loads(token, salt=SALT, max_age=60 * 60 * 24 * 365)
    if data.get('k') != kind:
        raise signing.BadSignature('wrong kind')
    return data


def recap(board, week_start):
    end = week_start + timedelta(days=6)
    results = list(DayResult.objects.filter(board=board, day__gte=week_start, day__lte=end))
    totals = points_by_user(board, week_start, end)
    team = sum(totals.values())
    mvp_row = LeaderboardWeek.objects.filter(board=board, week_start=week_start, is_mvp=True).select_related('user').first()
    if mvp_row is None and totals:
        from django.contrib.auth.models import User
        uid = max((u for u in totals if u), key=lambda u: totals[u], default=None)
        mvp = items.member_label(board, User.objects.filter(pk=uid).first()) if uid else None
    else:
        mvp = items.member_label(board, mvp_row.user) if mvp_row else None
    best = max(results, key=lambda r: (r.pct_in, r.members_in), default=None)
    goal = SquadGoal.objects.filter(board=board, period_end__gte=week_start).order_by('period_end').first()
    goal_pct = None
    if goal and goal.target:
        total, _ = goal_progress(goal)
        goal_pct = min(100, round(100 * float(total) / float(goal.target)))
    streak = getattr(board, 'streak', None)
    return {
        'board': {'name': board.name, 'emoji': board.emoji},
        'week_start': week_start.isoformat(), 'week_end': end.isoformat(),
        'streak': streak.current if streak else 0, 'team_score': team, 'mvp': mvp,
        'days_survived': sum(1 for r in results if r.status == DayStatus.SURVIVED),
        'best_day': best.day.strftime('%A') if best else None, 'goal_pct': goal_pct,
        'goal_title': goal.title if goal else None,
    }


# ──────────────────────────────────────
# PNG cards (1080 x 1080, for WhatsApp / Instagram)
# ──────────────────────────────────────

INK, PAPER, ACCENT, MUTED = (34, 34, 34), (250, 247, 240), (196, 120, 60), (120, 112, 100)


def _font(size, bold=False):
    from PIL import ImageFont
    for path in ('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else
                 '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def _png(draw_fn, size=(1080, 1080)):
    from PIL import Image, ImageDraw
    img = Image.new('RGB', size, PAPER)
    d = ImageDraw.Draw(img)
    d.rectangle([24, 24, size[0] - 24, size[1] - 24], outline=INK, width=4)
    draw_fn(d, size)
    d.text((60, size[1] - 110), 'makeyourreps.com', font=_font(34, True), fill=INK)
    d.text((60, size[1] - 66), 'Join us: build habits together', font=_font(26), fill=MUTED)
    buf = io.BytesIO()
    img.save(buf, 'PNG', optimize=True)
    return buf.getvalue()


def _stat(d, x, y, label, value):
    d.text((x, y), str(value), font=_font(84, True), fill=INK)
    d.text((x, y + 100), label.upper(), font=_font(26, True), fill=MUTED)


def recap_png(data):
    def draw(d, size):
        d.text((60, 70), 'WEEKLY RECAP', font=_font(30, True), fill=ACCENT)
        d.text((60, 115), f"{data['board']['name']}"[:28], font=_font(70, True), fill=INK)
        d.text((60, 205), f"{data['week_start']} → {data['week_end']}", font=_font(30), fill=MUTED)
        _stat(d, 60, 300, 'day streak', data['streak'])
        _stat(d, 560, 300, 'team score', data['team_score'])
        _stat(d, 60, 520, 'days survived', f"{data['days_survived']}/7")
        _stat(d, 560, 520, 'goal', f"{data['goal_pct']}%" if data['goal_pct'] is not None else '—')
        if data['mvp']:
            d.text((60, 750), f"MVP: {data['mvp']}"[:40], font=_font(48, True), fill=INK)
        if data['best_day']:
            d.text((60, 820), f"Best day: {data['best_day']}", font=_font(36), fill=MUTED)
    return _png(draw)


def completion_png(title, name, days_done, days, kind):
    def draw(d, size):
        d.text((60, 70), 'CHALLENGE COMPLETE', font=_font(30, True), fill=ACCENT)
        d.text((60, 130), title[:26], font=_font(72, True), fill=INK)
        d.text((60, 330), name[:30], font=_font(56, True), fill=INK)
        d.text((60, 410), 'finished it', font=_font(40), fill=MUTED)
        _stat(d, 60, 520, 'days done', f'{days_done}/{days}')
        _stat(d, 560, 520, 'kind', kind)
    return _png(draw)


def invite_png(name, emoji, member_count, streak):
    def draw(d, size):
        d.text((60, 70), 'JOIN MY SQUAD', font=_font(30, True), fill=ACCENT)
        d.text((60, 130), name[:26], font=_font(76, True), fill=INK)
        _stat(d, 60, 360, 'members', member_count)
        _stat(d, 560, 360, 'day streak', streak)
        d.text((60, 640), 'Free to join', font=_font(48, True), fill=INK)
    return _png(draw)


def challenge_png(title, participants, days, start):
    def draw(d, size):
        d.text((60, 70), 'JOIN THE CHALLENGE', font=_font(30, True), fill=ACCENT)
        d.text((60, 130), title[:26], font=_font(72, True), fill=INK)
        _stat(d, 60, 360, 'days', days)
        _stat(d, 560, 360, 'taking part', participants)
        d.text((60, 640), f'Starts {start:%d %b}', font=_font(48, True), fill=INK)
    return _png(draw)


def absolute(path):
    return f'{settings.SITE_URL}{path}'
