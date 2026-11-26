# Fitness and focus mode

Server-side plans, rotating habit subtasks, a full-screen player for workouts and Pomodoro, and an
onboarding rule engine. Spec: *Make Your Reps — Workout & Focus Mode PRD*.

## Commands

```
python manage.py import_exercises [path] [--dry-run] [--keep-missing]   # default path: fitness/fixtures/exercises.json
python manage.py seed_my_plan --user <id> --start YYYY-MM-DD           # hand-written plan for one user
```

Onboarding (`POST /board/api/fitness/onboarding/`) creates the launch templates on first use.

## Exercise library contract

`exercises.json` is an array of objects validated by `schemas/exercise.schema.json` (additional
properties are rejected). Assets live under `static/fitness/`:

| File | Required | Notes |
|---|---|---|
| `stills/<id>.png` | yes | Lists, "Up next", reduced motion and the fallback for a missing clip |
| `clips/<id>.glb` | no | One animation per exercise; the still shows until it exists |
| `mannequin.glb` | no | Shared model. When present, every muscle name must have a mesh (`quads`, `quads_l`/`quads_r`, `muscle_quads`; `core` is drawn as `abs`) |

- `animation = {clip, loop_ms, camera, peak, still, side?}`. `camera` is a preset (`front`, `side`,
  `back`, `three_quarter`, `top`) or `{yaw, pitch, distance?}`. `peak` is the 0–1 point of the loop the
  still is taken from.
- `side`: `"right"` for unilateral clips (the player mirrors the model for the left side), `"both"` for
  bilateral and alternating moves (dead bug, bird dog), which are never mirrored.
- `avoid` and `steps` are lists of strings.
- Import upserts by `id`, checks regression/progression links, bumps `library_version` and never deletes:
  ids missing from the file are marked `retired` (use `--keep-missing` for partial batches).

## Map to the PRD

| PRD | Code |
|---|---|
| Habit kinds health / activity | `board.Habit.kind` |
| Subtasks, rotating | `board.HabitStep` (stable `key`, `rule`) + `fitness.program.expand()` |
| TrackerLog, source | `board.MetricEntry.source` |
| SubtaskLink | `HabitStep.metric` + `HabitStep.rule`, evaluated in `fitness.links` |
| Program → Phase → DayTemplate | `fitness.models` (weeks are calendar weeks from the start date's Monday) |
| Step list / FocusPlayer | `fitness/steps.py`, `static/board/js/focus-player.js` |
| Renderer | `static/js/exercise3d.js` (three.js 0.170.0 via the page's import map) |
| Rule engine / builder | `fitness/rules.py`, `fitness/builder.py`, `fitness/templates_data.py` |
| Timeline items | `fitness/timeline.py` (computed, never stored) |
| Pomodoro focus mode | `focus` app |
