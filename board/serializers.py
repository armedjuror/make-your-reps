from calendar import monthrange
from datetime import date, datetime

from django.utils import timezone
from rest_framework import serializers

from board.models import (
    Habit, Task, TaskGroup, UserDetail, DailyData, HabitLog,
    RoutineEntry, ReadingListItem, TimelineEvent, SearchEngine,
    AccountabilityPartner, Friend, FriendRequest,
    Achievement, UserAchievement,
)


def get_habit_log(habit, target_month, target_year):
    days_in_month = monthrange(target_year, target_month)[1]
    logs = {
        x.date.strftime('%Y-%m-%d'): {'is_done': x.is_done, "date": x.date.strftime('%d')}
        for x in
        HabitLog.objects.filter(
            habit=habit,
            date__year=target_year,
            date__month=target_month,
        ).order_by('date')
    }

    for i in range(1, days_in_month + 1):
        d = date(target_year, target_month, i)
        if str(d) not in logs:
            logs[d.strftime('%Y-%m-%d')] = {'is_done': False, "date": d.strftime('%d')}

    return dict(sorted(logs.items()))


class UserDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserDetail
        exclude = ('created_at', 'updated_at')


class TaskGroupSerializer(serializers.ModelSerializer):
    task_count = serializers.SerializerMethodField()
    pending_count = serializers.SerializerMethodField()

    class Meta:
        model = TaskGroup
        exclude = ('user',)
        read_only_fields = ['created_at', 'updated_at']

    def get_task_count(self, obj):
        return obj.tasks.filter(is_deleted=False).count()

    def get_pending_count(self, obj):
        return obj.tasks.filter(is_deleted=False, is_done=False).count()


class TaskSerializer(serializers.ModelSerializer):
    group_name = serializers.CharField(source='group.name', read_only=True, default=None)

    class Meta:
        model = Task
        exclude = ('user', 'is_deleted', 'updated_at')


class DailyDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = DailyData
        fields = '__all__'


class HabitLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = HabitLog
        fields = '__all__'


class HabitSerializer(serializers.ModelSerializer):
    stats = serializers.SerializerMethodField()
    remark = serializers.SerializerMethodField()

    class Meta:
        model = Habit
        fields = ['id', 'habit', 'detail', 'identity', 'frequency',
                  'notify_at', 'status', 'created_at', 'stats', 'remark']
        read_only_fields = ['created_at', 'user']

    def _get_recent_logs(self, obj):
        """Get logs dict for the last 60 days, using prefetched data when available."""
        if hasattr(obj, 'recent_logs_prefetched'):
            return {
                x.date.strftime('%Y-%m-%d'): {'is_done': x.is_done, 'date': x.date}
                for x in obj.recent_logs_prefetched
            }
        now = timezone.localdate()
        start_date = now - timezone.timedelta(days=60)
        return {
            x.date.strftime('%Y-%m-%d'): {'is_done': x.is_done, 'date': x.date}
            for x in HabitLog.objects.filter(
                habit=obj, date__gte=start_date, date__lte=now
            ).order_by('date')
        }

    def _get_stats(self, obj):
        """Compute stats once and cache on the object to avoid double work."""
        if hasattr(obj, '_cached_stats'):
            return obj._cached_stats

        # Total reps: use annotation from view queryset if available, else query
        if hasattr(obj, 'total_reps_count'):
            total_reps = obj.total_reps_count
        else:
            total_reps = HabitLog.objects.filter(habit=obj, is_done=True).count()

        now = timezone.localdate()
        recent_logs = self._get_recent_logs(obj)

        # Build current-month display logs from the prefetched data (no extra query)
        if hasattr(obj, 'recent_logs_prefetched'):
            logs = self._build_month_logs(obj.recent_logs_prefetched, now.month, now.year)
        else:
            logs = get_habit_log(obj, now.month, now.year)

        obj._cached_stats = {
            'streak': obj.current_streak,
            'max_streak': obj.max_streak,
            'total_reps': total_reps,
            'logs': logs,
            'recent_logs': recent_logs,
        }
        return obj._cached_stats

    def _build_month_logs(self, prefetched_logs, target_month, target_year):
        """Build the full-month log dict from already-prefetched logs."""
        days_in_month = monthrange(target_year, target_month)[1]
        logs = {}
        for x in prefetched_logs:
            if x.date.year == target_year and x.date.month == target_month:
                logs[x.date.strftime('%Y-%m-%d')] = {'is_done': x.is_done, 'date': x.date.strftime('%d')}
        for i in range(1, days_in_month + 1):
            d = date(target_year, target_month, i)
            key = d.strftime('%Y-%m-%d')
            if key not in logs:
                logs[key] = {'is_done': False, 'date': d.strftime('%d')}
        return dict(sorted(logs.items()))

    def get_stats(self, obj):
        return self._get_stats(obj)

    def get_remark(self, obj):
        """
        Generate motivational coaching messages based on habit performance
        """
        stats = self._get_stats(obj)
        total_reps = stats['total_reps']
        streak = stats['streak']
        recent_logs = stats.get('recent_logs', {})

        now = timezone.localdate()
        created_date = obj.created_at.date()
        days_since_creation = (now - created_date).days

        # Get recent activity pattern
        last_done_date = self._get_last_done_date(recent_logs)
        missed_days = self._get_consecutive_missed_days(recent_logs)

        # Priority-based messaging system
        message = self._get_priority_message(
            total_reps=total_reps,
            streak=streak,
            max_streak=stats['max_streak'],
            days_since_creation=days_since_creation,
            missed_days=missed_days,
            last_done_date=last_done_date,
            now=now
        )

        return message

    def _get_last_done_date(self, logs):
        """Find the most recent date when habit was completed"""
        for date_str, log in sorted(logs.items(), reverse=True):
            if log.get('is_done', False):
                return datetime.strptime(date_str, "%Y-%m-%d").date()
        return None

    def _get_consecutive_missed_days(self, logs):
        """Count consecutive days missed from today backwards"""
        today = timezone.localdate()
        missed_count = 0

        # Sort logs by date in reverse order (most recent first)
        sorted_logs = sorted(logs.items(), key=lambda x: x[0], reverse=True)

        for date_str, log in sorted_logs:
            log_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            if log_date > today:
                continue
            if not log.get('is_done', False):
                missed_count += 1
            else:
                break

        return missed_count

    def _get_priority_message(self, total_reps, streak, max_streak, days_since_creation,
                              missed_days, last_done_date, now):
        """
        Generate messages based on priority hierarchy.
        Priority: Streak consistency > Recovery from breaks > Milestone celebrations
        """

        # 1. First-time user with no reps
        if total_reps == 0:
            if days_since_creation == 0:
                return "🌟 Welcome to your journey! Take the first step today - every expert was once a beginner."
            elif days_since_creation <= 3:
                return "💪 Let's start small! Just one rep today can build momentum for tomorrow."
            elif days_since_creation <= 7:
                return "🎯 It's been a few days - let's make today count! Small actions lead to big changes."
            else:
                return "🔧 It seems like this habit might be too challenging right now. Consider adjusting it to something smaller and more manageable."

        # 2. Active streak - celebrate and maintain
        if streak > 0:
            if streak >= 30:
                return f"🔥 {streak}-day streak! You're unstoppable! This is who you are now - keep being amazing!"
            elif streak >= 21:
                return f"💎 {streak}-day streak! You're in the habit formation zone. You're becoming the person you want to be!"
            elif streak >= 14:
                return f"⭐ {streak}-day streak! Two weeks of consistency - you're building something real here!"
            elif streak >= 7:
                return f"🚀 {streak}-day streak! One full week! You're proving consistency is your superpower!"
            elif streak >= 3:
                return f"💪 {streak}-day streak! Keep it going - you're building momentum!"
            else:
                return f"✨ {streak}-day streak! Every day counts. Let's keep this going!"

        # 3. Streak broken - use max_streak and missed_days to recover
        if streak == 0 and max_streak > 0:
            if missed_days == 1:
                if max_streak >= 14:
                    return f"⚡ You built a {max_streak}-day streak before! One missed day doesn't erase that. Bounce back today!"
                elif max_streak >= 7:
                    return f"🔄 You had a {max_streak}-day streak! Don't let one day become two. Get back on track now!"
                else:
                    return f"🎯 You missed yesterday, but you've done this {max_streak} days before. Start a new streak today!"

            elif missed_days == 2:
                if max_streak >= 14:
                    return f"🚨 Don't let 2 days become a week! You built a {max_streak}-day streak - you can do it again. Start NOW!"
                else:
                    return "⚠️ Two days missed - this is the critical moment! Don't let it become three. One rep today resets everything!"

            elif missed_days >= 3:
                if max_streak >= 21:
                    return f"💪 You once had a {max_streak}-day streak - that person is still you! Begin again today, one rep at a time."
                elif max_streak >= 7:
                    return f"🌱 Remember your {max_streak}-day streak? You've proven you can do this. Fresh start today!"
                else:
                    return f"🔄 You've completed this habit {total_reps} times before. Today is day one of your comeback story!"

        # 4. No streak and no max_streak - use reps to motivate
        if streak == 0 and max_streak == 0:
            if missed_days >= 2:
                return "🔄 Don't let two days become a habit! Today is a fresh start - one rep is all it takes to begin your streak!"
            elif missed_days == 1:
                return "🎯 You missed yesterday, but today is a new opportunity. Start your streak today!"
            else:
                # First attempt after creation
                return "🌟 Let's build your first streak! One day at a time, one rep at a time."

        # 5. Total reps milestones (secondary - when not covered by streak logic)
        if total_reps >= 100:
            if streak == 0:
                return f"🎉 You've done this {total_reps} times! That's proof you can build consistency. Start a fresh streak today!"
            else:
                return f"🏆 {total_reps} total reps AND a {streak}-day streak! You're crushing it! Consider hallmarking this habit!"

        elif total_reps >= 50:
            if streak == 0:
                return f"🌟 {total_reps} reps completed! You know how to do this. Time to build a streak that matches your effort!"
            else:
                return f"💫 {total_reps} reps with a {streak}-day streak! Consider hallmarking and starting a new challenge!"


# ──────────────────────────────────────
# New Serializers
# ──────────────────────────────────────

class RoutineEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = RoutineEntry
        exclude = ('user',)
        read_only_fields = ['created_at', 'updated_at']


class ReadingListItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReadingListItem
        exclude = ('user',)
        read_only_fields = ['created_at', 'updated_at']


class TimelineEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = TimelineEvent
        exclude = ('user',)
        read_only_fields = ['created_at', 'updated_at']


class SearchEngineSerializer(serializers.ModelSerializer):
    class Meta:
        model = SearchEngine
        fields = '__all__'


class AccountabilityPartnerSerializer(serializers.ModelSerializer):
    partner_name = serializers.SerializerMethodField()
    habit_name = serializers.CharField(source='habit.habit', read_only=True)
    owner_name = serializers.SerializerMethodField()

    class Meta:
        model = AccountabilityPartner
        fields = ['id', 'habit', 'habit_name', 'partner', 'partner_name', 'owner_name',
                  'invited_email', 'status', 'created_at']
        read_only_fields = ['created_at', 'status']

    def get_partner_name(self, obj):
        if obj.partner:
            return obj.partner.get_full_name() or obj.partner.username
        return obj.invited_email

    def get_owner_name(self, obj):
        owner = obj.habit.user
        return owner.get_full_name() or owner.username


class FriendSerializer(serializers.ModelSerializer):
    friend_name = serializers.SerializerMethodField()
    friend_username = serializers.CharField(source='friend.username', read_only=True)
    friend_email = serializers.EmailField(source='friend.email', read_only=True)

    class Meta:
        model = Friend
        fields = ['id', 'friend', 'friend_name', 'friend_username', 'friend_email', 'created_at']
        read_only_fields = ['created_at']

    def get_friend_name(self, obj):
        return obj.friend.get_full_name() or obj.friend.username


class FriendRequestSerializer(serializers.ModelSerializer):
    from_user_name = serializers.SerializerMethodField()
    to_user_name = serializers.SerializerMethodField()

    class Meta:
        model = FriendRequest
        fields = ['id', 'from_user', 'from_user_name', 'to_user', 'to_user_name', 'status', 'created_at']
        read_only_fields = ['created_at', 'status', 'from_user', 'to_user']

    def get_from_user_name(self, obj):
        return obj.from_user.get_full_name() or obj.from_user.username

    def get_to_user_name(self, obj):
        return obj.to_user.get_full_name() or obj.to_user.username


class AchievementSerializer(serializers.ModelSerializer):
    unlocked = serializers.SerializerMethodField()
    unlocked_at = serializers.SerializerMethodField()

    class Meta:
        model = Achievement
        fields = ['id', 'key', 'name', 'description', 'icon', 'category', 'unlocked', 'unlocked_at']

    def get_unlocked(self, obj):
        request_user_id = self.context.get('user_id')
        if not request_user_id:
            return False
        return UserAchievement.objects.filter(user_id=request_user_id, achievement=obj).exists()

    def get_unlocked_at(self, obj):
        request_user_id = self.context.get('user_id')
        if not request_user_id:
            return None
        ua = UserAchievement.objects.filter(user_id=request_user_id, achievement=obj).first()
        return ua.unlocked_at.isoformat() if ua else None