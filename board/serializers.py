from calendar import monthrange
from datetime import date, datetime

from django.utils import timezone
from rest_framework import serializers
from board.models import Habit, Task, UserDetail, DailyData, HabitLog

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
            logs[d.strftime('%Y-%m-%d')] =  {'is_done': False, "date": d.strftime('%d')}

    return dict(sorted(logs.items()))

def get_streak(habit):
    now = timezone.now().date()
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute("""
                            WITH RECURSIVE streak_calc AS (
                                SELECT 
                                    date,
                                    is_done,
                                    ROW_NUMBER() OVER (ORDER BY date DESC) as rn
                                FROM board_habitlog 
                                WHERE habit_id = %s 
                                AND date <= %s
                                ORDER BY date DESC
                            )
                            SELECT COUNT(*) as current_streak
                            FROM streak_calc
                            WHERE rn <= (
                                SELECT MIN(rn) 
                                FROM streak_calc 
                                WHERE is_done = false
                            ) - 1
                            AND is_done = true
                        """, [habit.id, now])
        result = cursor.fetchone()
        return result[0] if result else 0



class UserDetailSerializer(serializers.ModelSerializer):
    routines = serializers.SerializerMethodField()
    class Meta:
        model = UserDetail
        exclude = ('created_at', 'updated_at')

    def get_routines(self, obj):
        workdays_routine = [x.strip() for x in obj.workday_routine.split('\n') if x.strip()]
        holidays_routine = [x.strip() for x in obj.holiday_routine.strip().split('\n') if x.strip()]
        return {'workdays': workdays_routine, 'holidays': holidays_routine}


class TaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        exclude = ('user', 'is_deleted', 'updated_at')


class DailyDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = DailyData
        fields = '__all__'

class HabitSerializer(serializers.ModelSerializer):
    stats = serializers.SerializerMethodField()
    remark = serializers.SerializerMethodField()

    class Meta:
        model = Habit
        fields = ['id', 'habit', 'detail', 'identity', 'frequency',
                  'notify_at', 'status', 'created_at', 'stats', 'remark']
        read_only_fields = ['created_at', 'user']

    def get_stats(self, obj):
        total_reps = HabitLog.objects.filter(habit=obj, is_done=True).count()
        now = timezone.now().date()
        target_year = now.year
        target_month = now.month
        streak = get_streak(obj)
        logs = get_habit_log(obj, target_month, target_year)
        return {
            'streak': streak,
            'total_reps': total_reps,
            'logs': logs,
        }

    def get_remark(self, obj):
        """
        Generate motivational coaching messages based on habit performance
        """
        stats = self.get_stats(obj)
        total_reps = stats['total_reps']
        streak = stats['streak']
        logs = stats['logs']

        now = timezone.now().date()
        created_date = obj.created_at.date()
        days_since_creation = (now - created_date).days

        # Get recent activity pattern
        last_done_date = self._get_last_done_date(logs)
        missed_days = self._get_consecutive_missed_days(logs)

        # Priority-based messaging system
        message = self._get_priority_message(
            total_reps=total_reps,
            streak=streak,
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

    def _get_priority_message(self, total_reps, streak, days_since_creation,
                              missed_days, last_done_date, now):
        """
        Generate messages based on priority hierarchy
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

        # 2. Missed days handling
        if missed_days >= 2:
            if streak > 0:
                return "⚡ You had a great streak going! Remember: don't let two days become a week. Get back on track today!"
            else:
                return "🔄 Always remember: Don't miss twice in a row. Today is a fresh start - one rep is all it takes!"

        if missed_days == 1:
            if streak >= 7:
                return "🏆 You've built an amazing streak! One missed day doesn't define you - bounce back stronger today!"
            else:
                return "🎯 You missed yesterday, but today is a new opportunity. Don't let one day become two!"

        # 3. Performance-based encouragement
        if streak >= 21:
            return "🔥 Incredible! You're in the habit formation zone. You're becoming the person you want to be!"
        elif streak >= 14:
            return "⭐ Two weeks strong! You're building something amazing. Keep the momentum going!"
        elif streak >= 7:
            return "🚀 One week streak! You're proving to yourself that consistency is possible. Keep going!"
        elif streak >= 3:
            return "💎 Great consistency! You're building the foundation of lasting change."

        # 4. Milestone celebrations
        if total_reps >= 100:
            return "🎉 100+ reps! Champion You're! Hallmark this habit and start a new one if you feel like this one is already a habit!"
        elif total_reps >= 50:
            return "🌟 50+ reps achieved! Hallmark the habit and start a new one if you feel like this one is already a habit!"
        elif total_reps >= 30:
            return "💪 30+ reps! You're building serious momentum. Keep pushing forward!"
        elif total_reps >= 10:
            return "🎯 Double digits! You're proving that small actions create big results."

        # 5. Recent activity encouragement
        if last_done_date:
            days_since_last = (now - last_done_date).days
            if days_since_last <= 1:
                return "✨ Great job staying consistent! You're building a powerful habit."
            elif days_since_last <= 3:
                return "🔄 You were doing well! Let's get back into the rhythm today."
            else:
                return "🌱 It's been a while, but every day is a chance to restart. Begin again today!"

        # 6. Default encouraging message
        return "🌟 You're on a journey of growth! Every small step counts toward the person you're becoming."


class HabitLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = HabitLog
        exclude = ('created_at', 'updated_at')