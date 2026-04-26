"""
Gamification logic: points, levels, daily streak, achievements.
Call award_points() and update_daily_streak() on key user actions.
"""
from datetime import date, timedelta

from django.utils import timezone

LEVELS = [
    (1, 'Newcomer',         0),
    (2, 'Consistent',       500),
    (3, 'Focused',          1500),
    (4, 'Disciplined',      3500),
    (5, 'Dedicated',        7000),
    (6, 'Unstoppable',      13000),
    (7, 'Elite',            22000),
    (8, 'Legend',           35000),
]

POINTS = {
    'habit':       10,
    'todo':        5,
    'journal':     10,
    'sleep':       5,
    'pomodoro':    15,
    'achievement': 50,
}


def get_level_info(total_points):
    """Return (level_num, level_name, current_threshold, next_threshold)."""
    level_num, level_name, threshold = LEVELS[0]
    next_threshold = LEVELS[1][2]
    for i, (num, name, pts) in enumerate(LEVELS):
        if total_points >= pts:
            level_num, level_name, threshold = num, name, pts
            next_threshold = LEVELS[i + 1][2] if i + 1 < len(LEVELS) else pts
    return level_num, level_name, threshold, next_threshold


def _compute_streak_multiplier(streak):
    return 1.2 if streak >= 7 else 1.0


def award_points(user_id, action, multiplier=1.0):
    """
    Award points for an action. Returns dict with points_awarded and new_achievements.
    action: 'habit' | 'todo' | 'journal' | 'sleep' | 'pomodoro' | 'achievement'
    """
    from board.models import UserDetail
    base = POINTS.get(action, 0)
    if base == 0:
        return {'points_awarded': 0, 'new_achievements': []}

    user_detail, _ = UserDetail.objects.get_or_create(user_id=user_id)
    streak_mult = _compute_streak_multiplier(user_detail.current_streak)
    points = round(base * multiplier * streak_mult)

    user_detail.total_points = max(0, user_detail.total_points + points)
    new_level, _, _, _ = get_level_info(user_detail.total_points)
    user_detail.level = new_level
    user_detail.save(update_fields=['total_points', 'level'])

    new_achievements = check_and_award_achievements(user_id)
    return {'points_awarded': points, 'new_achievements': new_achievements}


def deduct_points(user_id, action, multiplier=1.0):
    """
    Deduct points when an action is reversed (e.g. habit unmarked, todo unchecked).
    Returns dict with points_deducted (negative number).
    """
    from board.models import UserDetail
    base = POINTS.get(action, 0)
    if base == 0:
        return {'points_awarded': 0, 'new_achievements': []}

    user_detail, _ = UserDetail.objects.get_or_create(user_id=user_id)
    streak_mult = _compute_streak_multiplier(user_detail.current_streak)
    points = round(base * multiplier * streak_mult)

    user_detail.total_points = max(0, user_detail.total_points - points)
    new_level, _, _, _ = get_level_info(user_detail.total_points)
    user_detail.level = new_level
    user_detail.save(update_fields=['total_points', 'level'])

    return {'points_awarded': -points, 'new_achievements': []}


def update_daily_streak(user_id):
    """
    Mark user as active today and update streak.
    Call on any meaningful action.
    """
    from board.models import UserDetail
    today = timezone.now().date()
    user_detail, _ = UserDetail.objects.get_or_create(user_id=user_id)

    last = user_detail.last_active_date
    if last == today:
        return  # already counted today

    if last == today - timedelta(days=1):
        user_detail.current_streak += 1
    else:
        user_detail.current_streak = 1

    if user_detail.current_streak > user_detail.longest_streak:
        user_detail.longest_streak = user_detail.current_streak

    user_detail.last_active_date = today
    user_detail.save(update_fields=['current_streak', 'longest_streak', 'last_active_date'])


def _unlock(user_id, key):
    """Unlock achievement by key. Returns achievement dict if newly unlocked, else None."""
    from board.models import Achievement, UserAchievement
    try:
        achievement = Achievement.objects.get(key=key)
    except Achievement.DoesNotExist:
        return None
    _, created = UserAchievement.objects.get_or_create(
        user_id=user_id, achievement=achievement
    )
    if created:
        # Award bonus points (no recursion — pass multiplier=1 directly)
        from board.models import UserDetail
        bonus = POINTS['achievement']
        ud, _ = UserDetail.objects.get_or_create(user_id=user_id)
        ud.total_points += bonus
        new_level, _, _, _ = get_level_info(ud.total_points)
        ud.level = new_level
        ud.save(update_fields=['total_points', 'level'])
        return {'key': key, 'name': achievement.name, 'icon': achievement.icon, 'points': bonus}
    return None


def check_and_award_achievements(user_id):
    """Check all achievement conditions and unlock any newly earned ones. Returns list of new achievements."""
    from django.contrib.auth.models import User
    from board.models import (
        Habit, HabitStatus, HabitLog, Task, DailyData,
        Friend, AccountabilityPartner, AccountabilityPartnerStatus,
        UserDetail, UserAchievement, Achievement,
    )

    new = []
    today = timezone.now().date()

    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return new

    ud, _ = UserDetail.objects.get_or_create(user_id=user_id)

    def unlock(key):
        result = _unlock(user_id, key)
        if result:
            new.append(result)

    # ── Habits ──
    done_habits = HabitLog.objects.filter(habit__user_id=user_id, is_done=True)
    if done_habits.exists():
        unlock('first_habit_done')

    active_habits = Habit.objects.filter(user_id=user_id, status=HabitStatus.ACTIVE.value)
    if active_habits.count() >= 5:
        unlock('five_habits')

    # Per-habit streaks
    for habit in active_habits:
        streak = habit.current_streak
        if streak >= 7:
            unlock('streak_7')
        if streak >= 30:
            unlock('streak_30')
        if streak >= 100:
            unlock('streak_100')

    # Clean sweep: all habits done for each of last 7 days
    if active_habits.exists():
        all_sweep = True
        for i in range(7):
            check_date = today - timedelta(days=i)
            weekday = check_date.weekday()
            due = [h for h in active_habits if not h.frequency or weekday in h.frequency]
            if not due:
                continue
            done_ids = set(HabitLog.objects.filter(
                habit__in=due, date=check_date, is_done=True
            ).values_list('habit_id', flat=True))
            if set(h.id for h in due) != done_ids:
                all_sweep = False
                break
        if all_sweep:
            unlock('clean_sweep_7')

    # ── Todos ──
    total_done = Task.objects.filter(user_id=user_id, is_deleted=False, is_done=True).count()
    if total_done >= 1:
        unlock('first_todo_done')
    if total_done >= 100:
        unlock('todos_100')

    # Inbox zero: no pending tasks today
    pending = Task.objects.filter(user_id=user_id, is_deleted=False, is_done=False).count()
    if total_done > 0 and pending == 0:
        unlock('inbox_zero')

    # Overachiever: 10 todos done today
    done_today = Task.objects.filter(
        user_id=user_id, is_deleted=False, is_done=True, updated_at__date=today
    ).count()
    if done_today >= 10:
        unlock('overachiever')

    # ── Journal ──
    journal_days = DailyData.objects.filter(
        user_id=user_id
    ).exclude(journal='').exclude(journal__isnull=True).count()
    if journal_days >= 1:
        unlock('first_journal')
    if journal_days >= 10:
        unlock('journal_10')
    if journal_days >= 30:
        unlock('journal_30')

    # ── Sleep ──
    sleep_days = DailyData.objects.filter(
        user_id=user_id, sleep_hours__isnull=False
    ).count()
    if sleep_days >= 30:
        unlock('sleep_30_days')

    # Well Rested: 8+ hours sleep for 7 consecutive days
    sleep_streak = 0
    for i in range(7):
        d = DailyData.objects.filter(
            user_id=user_id, date=today - timedelta(days=i), sleep_hours__gte=8
        ).first()
        if d:
            sleep_streak += 1
        else:
            break
    if sleep_streak >= 7:
        unlock('sleep_7_streak')

    # ── Focus ──
    total_focus = DailyData.objects.filter(
        user_id=user_id
    ).values_list('focus_minutes', flat=True)
    total_focus_mins = sum(total_focus)
    if total_focus_mins >= 1000:
        unlock('grind_1000_minutes')

    # Check today's pomodoro data (stored in DailyData.focus_minutes — 1 cycle = 25 min)
    today_data = DailyData.objects.filter(user_id=user_id, date=today).first()
    today_focus = today_data.focus_minutes if today_data else 0
    cycles_today = today_focus // 25

    if cycles_today >= 1:
        unlock('first_pomodoro')
    if cycles_today >= 8:
        unlock('deep_work')

    # Night Owl: 4 cycles between 12am–6am — tracked via focus_minutes logged during those hours
    # We approximate: if focus logged today and current hour is in 0-5
    hour_now = timezone.now().hour
    if 0 <= hour_now < 6 and cycles_today >= 4:
        unlock('night_owl')

    # Early Bird: 4 cycles before 9am
    if hour_now < 9 and cycles_today >= 4:
        unlock('early_bird')

    # Focus streak: at least 1 pomodoro per day for 7 consecutive days
    focus_streak_days = 0
    for i in range(7):
        d = DailyData.objects.filter(
            user_id=user_id, date=today - timedelta(days=i), focus_minutes__gte=25
        ).first()
        if d:
            focus_streak_days += 1
        else:
            break
    if focus_streak_days >= 7:
        unlock('focus_streak_7')

    # ── Social ──
    if Friend.objects.filter(user_id=user_id).exists():
        unlock('first_friend')

    active_partnerships = AccountabilityPartner.objects.filter(
        partner_id=user_id, status=AccountabilityPartnerStatus.ACTIVE
    ).count()
    if active_partnerships >= 3:
        unlock('three_partners')

    if AccountabilityPartner.objects.filter(
        partner_id=user_id, status=AccountabilityPartnerStatus.ACTIVE
    ).exists():
        unlock('accountability_accepted')

    # ── Daily Streak ──
    if ud.current_streak >= 7:
        unlock('daily_streak_7')
    if ud.current_streak >= 30:
        unlock('daily_streak_30')
    if ud.current_streak >= 100:
        unlock('daily_streak_100')

    # ── Meta ──
    unlocked_count = UserAchievement.objects.filter(user_id=user_id).count()
    if unlocked_count >= 10:
        unlock('ten_achievements')

    account_age = (today - user.date_joined.date()).days
    if account_age >= 365:
        unlock('veteran')

    return new
