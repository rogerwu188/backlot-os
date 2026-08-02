# AgentCut 0.9.17 migration: executable shot recipes

0.9.17 adds a versioned director-metadata layer for live-action and generated
short drama. It does not add Remotion as a renderer and does not import upstream
audio. Existing projects with no `shotRecipePolicy` or clip recipe reference
retain their previous behavior and report `coverage.shotRecipes.status` as
`NOT_REQUESTED`.

Shot recipes are per-shot director execution metadata, not global visual-style
templates. Existing project styles such as an American-drama look remain the
higher-level source of truth; a recipe may control motion/action timing but is
not allowed to overwrite character, wardrobe, location, palette, or style.

## Minimal clip reference

Enable the built-in registry and reference an exact recipe version:

```json
{
  "shotRecipePolicy": {
    "enabled": true,
    "registryId": "agentcut.short_drama.director_recipes",
    "registryVersion": "1.0.0"
  },
  "timeline": {
    "videoTracks": [{
      "id": "Video.Main",
      "clips": [{
        "id": "E21-SHOT-001",
        "source": "/absolute/media/shot.mp4",
        "start": 0,
        "duration": 4,
        "metadata": {
          "shot_recipe": {
            "recipe_id": "camera.slow_push_in",
            "version": "1.0.0",
            "override": {"camera_motion": {"intensity": 0.6}}
          }
        }
      }]
    }]
  }
}
```

Project-level overrides belong in `shotRecipePolicy.projectOverrides`. Neither
project nor clip overrides may replace `recipe_id`, `version`, `source`, or
`license`; those fields are immutable provenance.

## Timing and hard failures

Recipe time is expressed in seconds or normalized ratios, never both. Seconds
are authoritative. Compilation deterministically maps seconds to the output
frame grid using nearest-half-up rounding, including 720x1280 at 24 fps.

Validation and compilation fail for unknown recipes, absent/mismatched versions,
overlapping or out-of-clip motion phases, out-of-clip SFX cues, unlicensed bound
SFX files, and intentional black without exact reference frames, reason, and an
approved policy. AgentCut never invents an editorial justification.

All existing subtitle, dialogue coverage, narrative, cadence, near-freeze,
black-frame, source admission, audio and release gates remain active.

## Agent interfaces

```sh
agentcut shot-recipe-list
agentcut shot-recipe-repairs project.json --problems aggregate-problems.json
```

NDJSON methods are `listShotRecipes` and `mapShotRecipeRepairs`. Compile output
uses `directorRenderPlan`; validation uses `coverage.shotRecipes`; successful
render writes `<output>.shot-recipes.json`. Aggregate QA ranges are expanded to
the intersecting `clipId` and recipe phase. Every repair task is reversible and
sets `platformMutationAuthorized=false`.

Task2 should install the wheel only after independent acceptance:

```sh
/Users/rogerwu/qingshan_short_drama/.agentcut_env/bin/python -m pip install \
  --no-deps --force-reinstall /absolute/release_0.9.17/agentcut-0.9.17-py3-none-any.whl
/Users/rogerwu/qingshan_short_drama/tools/run_agentcut.sh health
```
