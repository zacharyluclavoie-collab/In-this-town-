# In This World — Leo videos

Short animated story videos for the **@inthisworld.story** TikTok. Every video is an
"In this world, ..." premise starring **Leo**, told by a narrator with bold captions,
blocky 3D characters and soft piano music. Two videos go out each day (2 PM and 8 PM
Vancouver time) through Buffer.

## Make a video

```bash
bash pipeline/setup.sh                                   # once per machine
python3 pipeline/make_video.py stories/FILE.json --stills   # check one frame per shot (1 min)
python3 pipeline/make_video.py stories/FILE.json            # full render -> videos/DATE/SLUG.mp4
```

Output: 1080x1920, 24 fps, H.264 + AAC, about 55-70 seconds. A full render takes about
1 hour on 4 CPU cores. Renders are cached in `build/`, so a stopped run resumes.

## Writing a story

A story is a JSON file in `stories/` named `DATE-slug.json`. Each shot is one narration
line; the shot lasts as long as the line takes to say.

Story recipe (what the reference videos do):
1. Hook: `In this *world*, ...` states the rule of the world.
2. Explain the rule with a quick example (2-3 shots).
3. Leo is different and nobody understands why (kids tease, friend worries).
4. The secret / reason is revealed (family, kindness, sacrifice).
5. Emotional payoff, then a question to the viewer: `What would *you* ...?`

Keep 23-28 lines (70-90 s), each under ~14 words. Wrap the key word in `*stars*` so the
caption shows it in CAPS (otherwise one word is picked automatically). Use only original ideas.

What makes these go viral (from the reference videos):
- The first 2 seconds SHOW the rule happening (sparkles, a speech bubble, a big reaction), not just say it.
- A rival (usually Tyler) who uses the rule selfishly, so Leo's choice stands out.
- A setup early that pays off at the end (e.g. "real ones are worth a fortune").
- Short comic speech bubbles (`"say": "NO."`) in 4-6 shots: insults, gasps, the key line.
- Fast pictures: long lines are cut automatically into 2-3 camera angles; add `tilt` for shock.
- Title in Title Case + one emoji, like `Every Compliment You Get Turns Into Gold Coins 😨`.
- Caption: the premise, a teaser (`Leo had ZERO… until`), "Wait for the end", then
  `#inthisworld #robloxstory #roblox #storytime #fyp`.

```json
{
  "slug": "short-name", "date": "YYYY-MM-DD",
  "caption": "TikTok caption with #inthisworld #story #storytime #emotional #fyp",
  "voice": "am_michael", "speed": 1.08, "mood": "emotional|hopeful|tense|mystery",
  "cast": {"leo": {"shirt": "#8a8f96"}},
  "shots": [
    {"line": "In this *world*, ...", "set": "schoolyard", "time": "day",
     "cast": {"leo": {"shirt": "#1f4fbf"}},
     "chars": [{"who": "leo", "at": "A", "face": "sad", "act": ["talk", "hold"], "talk": true,
                "look": "mia", "prop": "book", "to": "B", "fx": "sparkle"}],
     "cam": {"shot": "close", "on": "leo", "angle": 15, "height": "eye", "move": "push"},
     "hold": 0.3}
  ]
}
```

**Cast** (`cast.json`, story/shot `cast` overrides merge on top): `leo` (main character,
red hoodie, spiky brown hair), `mia` (best friend), `noah`, `tyler` (the mean kid), `kid1`,
`kid2`, `mom`, `dad`, `lily` (little sister), `grandpa`, `teacher`, `doctor`.
Appearance keys: `skin shirt pants shoes accent top(hoodie|tshirt|jacket|stripes|suit|dress|galaxy)
hair(spiky|short|messy|curly|long|bob|pigtails|bun|ponytail|cap|curlers|none) hair_color
acc[crown|glasses|headband|backpack|cape|bow] age(kid|teen|adult|baby) height`.

**Sets and slots** (`at`): every set has standing slots `A`-`E` (some `F`, `G`).
- `bedroom` (+`BED` lying, `DESK`), `nursery` (+`CRIB`), `livingroom` (+`SOFA`, `SOFA2`, `SOFA3` seats)
- `classroom` (desk seats `S1`-`S6`, teacher `T`, standing only `A`-`D`), `hallway`, `cafeteria` (bench seats `SL SR SL2 SR2`)
- `hospital` (`BED` lying), `schoolyard`, `street` (`ROAD`), `park` (`BENCH`)
- `at` can also be `[x, y, yaw_degrees]`. `time`: `day`, `sunset`, `night`.

**Faces**: neutral happy smile sad shocked angry worried crying smug sleepy determined scared blank laugh.
`talk: true` flaps the mouth while the line plays.

**Acts** (combine in a list): idle talk walk run jump cheer wave point hold hug cry sad shrug
shake scared angry dance float fall lie sit nod headshake lookaround turn.
`walk`/`run` need `to` (slot or [x, y]). Seat/bed slots sit or lie automatically
(`lie` for beds).

**Props** (`prop`, held in right hand): ball phone book tray trophy gift cake balloon paper
shoes letter icecream. **FX**: `"fx": "sparkle"` with optional `fx_color`. `"bubble": true`
shows a "..." speech bubble. `"say": "NO."` shows a comic speech bubble with text
above the character. `"tag": "3"` floats a number above the head (`tag_color`).

**Camera**: `shot` extreme|close|medium|full|wide, `on` a name or list of names,
`angle` degrees around the target, `height` eye|low|high|top (top = looking down, good
for beds), `move` drift|push|pull|pan_l|pan_r|orbit|zoom, `front: "scene"` to frame from the
set's front instead of the character's, `shake: true`, `tilt` degrees (dutch angle).
Lines longer than ~3 s are split into 2-3 cuts automatically (closer shot, new angle);
set `"nocut": true` on a shot to stop that, or give `"cams": [cam1, cam2]` to choose the cuts.
Hugs and shots with 4+ characters are never auto-cut. Every cut gets a whoosh; bubbles a pop;
sparkles a shimmer; `zoom`/`shake` a boom.

Always run `--stills` and look at the contact sheet before the full render: faces must
be visible, nobody cut off, captions readable.

## Posting

Videos are committed under `videos/DATE/` and served from
`https://raw.githubusercontent.com/zacharyluclavoie-collab/In-this-town-/refs/heads/BRANCH/videos/DATE/SLUG.mp4`.
They are added to the Buffer queue of the `inthisworld.story` TikTok channel, whose
queue slots are 14:00 and 20:00 every day.
