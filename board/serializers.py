from calendar import monthrange
from datetime import date, datetime

from django.utils import timezone
from rest_framework import serializers

from board.models import (
    Habit, Task, TaskGroup, UserDetail, DailyData, HabitLog,
    RoutineEntry, ReadingListItem, TimelineEvent, SearchEngine
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

    def _get_recent_logs(self, obj, days=60):
        """Get logs for the last N days for accurate message calculation"""
        now = timezone.now().date()
        start_date = now - timezone.timedelta(days=days)

        logs = {
            x.date.strftime('%Y-%m-%d'): {'is_done': x.is_done, 'date': x.date}
            for x in HabitLog.objects.filter(
                habit=obj,
                date__gte=start_date,
                date__lte=now
            ).order_by('-date')
        }
        return logs

    def get_stats(self, obj):
        total_reps = HabitLog.objects.filter(habit=obj, is_done=True).count()
        now = timezone.now().date()
        target_year = now.year
        target_month = now.month
        streak = obj.current_streak

        # Get current month logs for display
        logs = get_habit_log(obj, target_month, target_year)

        # Get recent logs for accurate message calculation (last 60 days)
        recent_logs = self._get_recent_logs(obj, days=60)

        return {
            'streak': streak,
            'max_streak': obj.max_streak,
            'total_reps': total_reps,
            'logs': logs,
            'recent_logs': recent_logs,  # Add this for message calculation
        }

    def get_remark(self, obj):
        """
        Generate motivational coaching messages based on habit performance
        """
        stats = self.get_stats(obj)
        total_reps = stats['total_reps']
        streak = stats['streak']
        recent_logs = stats.get('recent_logs', {})  # Use recent_logs instead of logs

        now = timezone.now().date()
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
        today = timezone.now().date()
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