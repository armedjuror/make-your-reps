from django.contrib import admin
from board.models import (
    UserDetail, Friend, Task, TaskGroup, DailyData,
    Habit, HabitLog, AccountabilityPartner,
    RoutineEntry, ReadingListItem, TimelineEvent, SearchEngine
)


@admin.register(UserDetail)
class UserDetailAdmin(admin.ModelAdmin):
    list_display = ('user', 'default_theme', 'default_search_engine', 'font_family', 'clock_format', 'sleep_time')
    list_filter = ('default_theme', 'clock_format')


@admin.register(Friend)
class FriendAdmin(admin.ModelAdmin):
    list_display = ('user', 'friend', 'is_active', 'created_at')
    list_filter = ('is_active',)


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ('user', 'task_name', 'group', 'deadline', 'is_done', 'is_deleted', 'created_at')
    list_filter = ('is_done', 'is_deleted', 'group')
    search_fields = ('task_name',)


@admin.register(TaskGroup)
class TaskGroupAdmin(admin.ModelAdmin):
    list_display = ('user', 'name', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name',)


@admin.register(DailyData)
class DailyDataAdmin(admin.ModelAdmin):
    list_display = ('user', 'date', 'sleep_hours')
    list_filter = ('date',)


@admin.register(Habit)
class HabitAdmin(admin.ModelAdmin):
    list_display = ('user', 'habit', 'status', 'notify_at', 'created_at')
    list_filter = ('status',)
    search_fields = ('habit',)


@admin.register(HabitLog)
class HabitLogAdmin(admin.ModelAdmin):
    list_display = ('habit', 'date', 'is_done')
    list_filter = ('is_done', 'date')


@admin.register(AccountabilityPartner)
class AccountabilityPartnerAdmin(admin.ModelAdmin):
    list_display = ('habit', 'partner', 'is_active')


@admin.register(RoutineEntry)
class RoutineEntryAdmin(admin.ModelAdmin):
    list_display = ('user', 'routine_type', 'time', 'title')
    list_filter = ('routine_type', )
    search_fields = ('title',)


@admin.register(ReadingListItem)
class ReadingListItemAdmin(admin.ModelAdmin):
    list_display = ('user', 'name', 'url', 'is_featured', 'is_active')
    list_filter = ('is_featured', 'is_active')
    search_fields = ('name', 'url')


@admin.register(TimelineEvent)
class TimelineEventAdmin(admin.ModelAdmin):
    list_display = ('user', 'event_type', 'event', 'timestamp', 'action_response')
    list_filter = ('event_type',)
    search_fields = ('event',)


@admin.register(SearchEngine)
class SearchEngineAdmin(admin.ModelAdmin):
    list_display = ('name', 'key', 'url_template', 'is_active')
    list_filter = ('is_active',)