from django.contrib import admin
from django.utils.html import format_html

from fitness.models import DayTemplate, Exercise, FitnessProfile, Phase, Program, ProgramTemplate


@admin.register(Exercise)
class ExerciseAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'pattern', 'level', 'intensity', 'retired', 'library_version', 'still_preview')
    list_filter = ('pattern', 'level', 'intensity', 'retired')
    search_fields = ('id', 'name')
    readonly_fields = ('library_version', 'updated_at', 'still_preview')

    @admin.display(description='Still')
    def still_preview(self, obj):
        from fitness.views import asset_url
        url = asset_url((obj.animation or {}).get('still'))
        return format_html('<img src="{}" style="height:64px">', url) if url else '-'


class DayInline(admin.TabularInline):
    model = DayTemplate
    extra = 0


@admin.register(Phase)
class PhaseAdmin(admin.ModelAdmin):
    list_display = ('program', 'order', 'name', 'week_from', 'week_to')
    inlines = [DayInline]


class PhaseInline(admin.TabularInline):
    model = Phase
    extra = 0


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = ('user', 'name', 'start_date', 'status')
    inlines = [PhaseInline]


admin.site.register(ProgramTemplate)
admin.site.register(FitnessProfile)
