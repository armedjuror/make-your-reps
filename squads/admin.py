from django.contrib import admin

from squads.models import (
    Block, Board, BoardMembership, Challenge, ChallengeParticipant, Contribution, DayResult, Event, FocusSession,
    Invite, NotificationLog, Report, SquadGoal, UserPlan,
)


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    """The admin queue for reports on users, squads and public challenges."""
    list_display = ('created_at', 'target_type', 'target_id', 'reporter', 'status', 'short_reason')
    list_filter = ('status', 'target_type')
    list_editable = ('status',)
    search_fields = ('reason',)
    actions = ['mark_actioned', 'dismiss']

    def short_reason(self, obj):
        return obj.reason[:80]

    @admin.action(description='Mark actioned')
    def mark_actioned(self, request, qs):
        qs.update(status='actioned')

    @admin.action(description='Dismiss')
    def dismiss(self, request, qs):
        qs.update(status='dismissed')


class MembershipInline(admin.TabularInline):
    model = BoardMembership
    extra = 0
    raw_id_fields = ('user', 'added_by')


@admin.register(Board)
class BoardAdmin(admin.ModelAdmin):
    list_display = ('id', 'type', 'name', 'emoji', 'owner', 'status', 'created_at')
    list_filter = ('type', 'status', 'template')
    search_fields = ('name', 'owner__email')
    raw_id_fields = ('owner',)
    inlines = [MembershipInline]


@admin.register(Challenge)
class ChallengeAdmin(admin.ModelAdmin):
    list_display = ('title', 'kind', 'visibility', 'start_date', 'end_date', 'host', 'ended')
    list_filter = ('kind', 'visibility', 'ended')
    raw_id_fields = ('board', 'parent_board', 'host')


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'name', 'user', 'props')
    list_filter = ('name',)
    raw_id_fields = ('user',)


for model in (Invite, Contribution, DayResult, SquadGoal, FocusSession, ChallengeParticipant, Block,
              NotificationLog, UserPlan):
    admin.site.register(model)
