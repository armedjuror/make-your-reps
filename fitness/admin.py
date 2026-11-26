import json

from django.contrib import admin
from django.templatetags.static import static
from django.utils.html import escape, format_html
from django.utils.safestring import mark_safe

from fitness.models import DayTemplate, Exercise, FitnessProfile, Phase, Program, ProgramTemplate


@admin.register(Exercise)
class ExerciseAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'pattern', 'level', 'intensity', 'retired', 'library_version', 'still_preview')
    list_filter = ('pattern', 'level', 'intensity', 'retired')
    search_fields = ('id', 'name')
    readonly_fields = ('library_version', 'updated_at', 'still_preview', 'live_preview')

    @admin.display(description='Live preview')
    def live_preview(self, obj):
        """The 3D clip (or the still) plus the guide, for spot fixes after an import."""
        from fitness.views import exercise_json
        data = json.dumps(exercise_json(obj, full=True)).replace('</', '<\\/')
        steps = ''.join(f'<li>{escape(s)}</li>' for s in obj.steps)
        avoid = ''.join(f'<li>{escape(s)}</li>' for s in obj.avoid)
        return mark_safe(f'''
            <script type="importmap">{{"imports": {{"three": "https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.min.js",
                "three/addons/": "https://cdn.jsdelivr.net/npm/three@0.170.0/examples/jsm/"}}}}</script>
            <div style="display:flex;gap:24px;flex-wrap:wrap">
              <div id="ex3d-admin" style="width:320px;height:320px;background:#222;border-radius:12px;position:relative"></div>
              <div><b>How to</b><ol>{steps}</ol><b>Avoid</b><ul>{avoid}</ul><p>{escape(obj.breathing)}</p></div>
            </div>
            <script src="{static('js/exercise3d.js')}"></script>
            <script>(function(){{var ex={data};var c=document.getElementById('ex3d-admin');
              if(ex.still)c.innerHTML='<img src="'+ex.still+'" style="width:100%;height:100%;object-fit:contain">';
              Exercise3D.mount(c,ex,{{}});}})();</script>''')

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
