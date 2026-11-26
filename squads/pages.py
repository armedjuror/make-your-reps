"""
Server-rendered pages: invite join page, public challenge page, Discover,
completion card, weekly recap, focus live room, RSVP landing, email login.
Public pages show display names only, never emails.
"""
import json
from datetime import date
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth.models import User
from django.core import signing
from django.http import Http404, HttpResponse, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt

from main.utils import get_client_ip
from squads import challenges as ch_mod, core, flags, focus as focus_mod, items, share
from squads.events import track
from squads.limits import LimitBlocked
from squads.models import Board, Challenge, ChallengeParticipant, FocusSession, Invite, ParticipantStatus


def _user_id(request):
    return request.session.get('user_id') or (request.user.id if request.user.is_authenticated else None)


def _login_url(next_path):
    return f'/login/email/?next={quote(next_path)}'


def _need_flag(name):
    if not flags.enabled(name):
        raise Http404()


# ──────────────────────────────────────
# Invite (B2, B3)
# ──────────────────────────────────────

@never_cache
def join_page(request, token):
    _need_flag('squads')
    inv = Invite.objects.select_related('board').filter(token=token).first()
    if inv is None:
        raise Http404()
    user_id = _user_id(request)
    track('invite_page_viewed', user_id, board_id=inv.board_id, logged_in=bool(user_id))
    error = None
    if request.method == 'POST':
        if not user_id:
            return redirect(_login_url(request.path))
        try:
            core.join_with_invite(token, User.objects.get(pk=user_id))
            return redirect(f'/board/#squad/{inv.board_id}/join')
        except core.SquadError as e:
            error = str(e)
        except LimitBlocked as e:
            error = 'This squad is full on its current plan. Ask the owner to upgrade.'
    already = bool(user_id and inv.board.active_memberships().filter(user_id=user_id).exists())
    return render(request, 'squads/join.html', {
        'invite': inv, 'preview': core.invite_preview(inv), 'logged_in': bool(user_id), 'already': already,
        'error': error, 'next': request.path, 'login_url': _login_url(request.path),
        'og_image': share.absolute(f'/j/{token}/og.png'), 'page_url': share.absolute(request.path),
    })


def join_og(request, token):
    inv = get_object_or_404(Invite.objects.select_related('board'), token=token)
    p = core.invite_preview(inv)
    return _png_response(share.invite_png(p['name'], p['emoji'], p['member_count'], p['streak']))


def _png_response(data):
    resp = HttpResponse(data, content_type='image/png')
    resp['Cache-Control'] = 'public, max-age=3600'
    return resp


# ──────────────────────────────────────
# Challenges (F2, F5, F7)
# ──────────────────────────────────────

@never_cache
def challenge_page(request, slug):
    _need_flag('challenges')
    ch = get_object_or_404(Challenge.objects.select_related('board', 'host'), slug=slug)
    user_id = _user_id(request)
    if not ch_mod.can_see(ch, user_id):
        if not user_id:
            return redirect(_login_url(request.path))
        raise Http404()
    error = None
    if request.method == 'POST':
        if not user_id:
            return redirect(_login_url(request.path))
        try:
            p = ChallengeParticipant.objects.filter(challenge=ch, user_id=user_id).first()
            if request.POST.get('action') == 'continue' and p:
                ch_mod.continue_unofficially(p)
            else:
                ch_mod.join(ch, user_id, tz=request.POST.get('tz') or None)
            return redirect(request.path)
        except ch_mod.ChallengeError as e:
            error = str(e)
    board = ch_mod.leaderboard(ch, user_id)
    me = ChallengeParticipant.objects.filter(challenge=ch, user_id=user_id).first() if user_id else None
    return render(request, 'squads/challenge.html', {
        'ch': ch, 'info': ch_mod.serialize(ch, user_id), 'board': board, 'me': me,
        'progress': ch_mod.progress(ch, me) if me else None, 'logged_in': bool(user_id), 'error': error,
        'login_url': _login_url(request.path), 'og_image': share.absolute(f'/c/{slug}/og.png'),
        'page_url': share.absolute(request.path),
    })


def challenge_og(request, slug):
    ch = get_object_or_404(Challenge, slug=slug)
    return _png_response(share.challenge_png(ch.title, ch.participants.count(), ch.days, ch.start_date))


def completion_card(request, slug, participant_id):
    _need_flag('share')
    ch = get_object_or_404(Challenge, slug=slug)
    p = get_object_or_404(ChallengeParticipant.objects.select_related('user'), pk=participant_id, challenge=ch,
                          status=ParticipantStatus.COMPLETED)
    return render(request, 'squads/card.html', {
        'ch': ch, 'p': p, 'name': items.display_name(p.user), 'image': f'/c/{slug}/card/{p.id}/image.png',
        'og_image': share.absolute(f'/c/{slug}/card/{p.id}/image.png'), 'page_url': share.absolute(request.path),
        'logged_in': bool(_user_id(request)),
    })


def completion_png(request, slug, participant_id):
    ch = get_object_or_404(Challenge, slug=slug)
    p = get_object_or_404(ChallengeParticipant.objects.select_related('user'), pk=participant_id, challenge=ch,
                          status=ParticipantStatus.COMPLETED)
    return _png_response(share.completion_png(ch.title, items.display_name(p.user), p.days_done, ch.days, ch.kind))


def discover_page(request):
    _need_flag('challenges')
    soon, popular = ch_mod.discover()
    user_id = _user_id(request)
    return render(request, 'squads/discover.html', {
        'starting_soon': [ch_mod.serialize(c, user_id) for c in soon],
        'most_joined': [ch_mod.serialize(c, user_id) for c in popular], 'logged_in': bool(user_id),
    })


# ──────────────────────────────────────
# Weekly recap (I1)
# ──────────────────────────────────────

def _recap_from_token(token):
    try:
        data = share.read_token(token, 'recap')
    except signing.BadSignature:
        raise Http404()
    board = get_object_or_404(Board, pk=data['b'])
    return board, date.fromisoformat(data['w'])


def recap_page(request, token):
    _need_flag('share')
    board, ws = _recap_from_token(token)
    return render(request, 'squads/recap.html', {
        'data': share.recap(board, ws), 'image': f'/s/recap/{token}/image.png',
        'og_image': share.absolute(f'/s/recap/{token}/image.png'), 'page_url': share.absolute(request.path),
        'logged_in': bool(_user_id(request)),
    })


def recap_png(request, token):
    board, ws = _recap_from_token(token)
    return _png_response(share.recap_png(share.recap(board, ws)))


# ──────────────────────────────────────
# Focus (E2, E3)
# ──────────────────────────────────────

@never_cache
def focus_room_page(request, session_id):
    _need_flag('focus')
    user_id = _user_id(request)
    if not user_id:
        return redirect(_login_url(request.path))
    s = get_object_or_404(FocusSession.objects.select_related('board'), pk=session_id)
    from squads.scoping import is_member
    if not is_member(s.board, user_id):
        raise Http404()
    return render(request, 'squads/focus_room.html', {'session': s, 'state': json.dumps(focus_mod.room_state(s, user_id))})


def rsvp_landing(request, token):
    try:
        data = focus_mod.read_rsvp_token(token)
    except signing.BadSignature:
        raise Http404()
    s = get_object_or_404(FocusSession.objects.select_related('board'), pk=data['s'])
    focus_mod.set_rsvp(s, data['u'], data['r'])
    return render(request, 'squads/rsvp.html', {'session': s, 'response': data['r']})


# ──────────────────────────────────────
# Email OTP (A1)
# ──────────────────────────────────────

def _safe_next(value):
    return value if value and value.startswith('/') and not value.startswith('//') else '/board/'


@never_cache
def email_login_page(request):
    _need_flag('otp_login')
    nxt = _safe_next(request.GET.get('next'))
    if _user_id(request):
        return redirect(nxt)
    return render(request, 'squads/email_login.html', {'next': nxt, 'google_next': quote(nxt)})


def _json(request):
    try:
        return json.loads(request.body or b'{}')
    except ValueError:
        return {}


@csrf_exempt   # JSON-only: a cross-site form can't send application/json without a CORS preflight
def otp_request(request):
    from main.otp import OTPError, request_code
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    if not flags.enabled('otp_login'):
        return JsonResponse({'status': 'failed', 'error': 'Email login is not available yet'}, status=404)
    if not request.content_type.startswith('application/json'):
        return JsonResponse({'status': 'failed', 'error': 'Send JSON'}, status=415)
    try:
        email = request_code(_json(request).get('email'), ip=get_client_ip(request))
    except OTPError as e:
        return JsonResponse({'status': 'failed', 'error': str(e)}, status=e.status)
    return JsonResponse({'status': 'success', 'data': {'email': email, 'ttl_minutes': settings.OTP_TTL_MINUTES}})


@csrf_exempt
def otp_verify(request):
    from main.otp import OTPError, sign_in, verify_code
    from main.utils import RefreshToken
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    if not flags.enabled('otp_login'):
        return JsonResponse({'status': 'failed', 'error': 'Email login is not available yet'}, status=404)
    if not request.content_type.startswith('application/json'):
        return JsonResponse({'status': 'failed', 'error': 'Send JSON'}, status=415)
    body = _json(request)
    try:
        user, created = verify_code(body.get('email'), body.get('code'))
    except OTPError as e:
        return JsonResponse({'status': 'failed', 'error': str(e)}, status=e.status)
    client = body.get('client_type') or 'web'
    if client == 'extension':
        request.session['client_type'] = 'extension'   # AuthMiddleware sets the extension's refresh cookie
    sign_in(request, user, created)
    out = {'user_id': user.id, 'created': created, 'next': _safe_next(body.get('next'))}
    if client == 'app':
        token, _ = RefreshToken.generate_token(user, request, device_id=body.get('device_id'))
        out['refresh_token'] = token
    track('otp_login', user.id, created=created, client=client)
    return JsonResponse({'status': 'success', 'data': out})
