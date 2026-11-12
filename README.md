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

Output: 1080x1920, 30 fps, H.264 CRF 18 + AAC 192k 48 kHz stereo, 40-55 seconds. A full render takes about
1 hour on 4 CPU cores. Renders are cached in `build/`, so a stopped run resumes.

## Sound

New videos use a warm storyteller voice, Microsoft Edge neural `en-US-AndrewMultilingualNeural`
(free, via `edge-tts`; the network must allow `speech.platform.bing.com`). Each sentence is
spoken separately at about 0.92x speed and stitched with pauses (0.45 s between sentences,
0.55 s after a line, 1.1 s before the shot marked `"twist": true`); the last line is slower
and softer. Captions follow the voice's own word timings.

Mastering (`pipeline/mastering.py`): voice highpass 80 Hz, light denoise, de-esser, gentle
compression, +3 dB at 3 kHz; piano bed ~8 dB under the voice and sidechain-ducked by it,
+4 dB swell from the twist, 1.5 s fade-in and 2 s fade-out; quiet whoosh/chime/heartbeat
effects; two-pass loudnorm to -14 LUFS / -1.5 dBTP, 48 kHz stereo AAC 192k. Each render
writes `build/SLUG/audio_report.json` (final LUFS, true peak, voice vs music).
Older stories carry `"tts": "kokoro"` so re-rendering them keeps their original sound.
`"narrator"` and `"rate"` in a story override the voice and speed.

## Writing a story

A story is a JSON file in `stories/` named `DATE-slug.json`. Each shot is one narration
line; the shot lasts as long as the line takes to say.

Format for reach (new videos, 40-55 s, 12-15 lines):
1. Hook, first 2 s: line 1 is `In this *world*, [strange rule]...` and the picture SHOWS the
   rule happening. `hook_text` (6 words or fewer) is shown big in the first ~3 s; a
   "WAIT FOR THE END" tag appears at 2-5.5 s.
2. Setup (2-3 lines), then a problem for Leo (he's different / mocked by the rival).
3. Twist at about 80% of the video: mark it `"twist": true` (pause + heartbeat + music swell).
4. Short emotional landing (1 line), shown with a close-up of Leo's face, not extra words.
5. Last line: a question that makes people tag or share ("Who would you tag?"). A
   "FOLLOW FOR THE NEXT STORY" card shows on the last shot. Make the last shot use the same
   set and a similar camera as the first so the video loops.
Cut every line that doesn't move the story. `python3 pipeline/make_video.py FILE --stills`
prints the length and where the twist lands; aim for 45-52 s and 76-84%.

Write the lines to be spoken: short sentences, everyday words that are easy to say, commas
and `...` where a breath belongs ("And then... something glowed.").

Caption (under 250 characters, Canadian spelling): keyword first, `In this world, [rule]...
Leo ... 🥹` + a question, then 3-5 hashtags: `#inthisworld #storytime` + 2-3 story tags such as
`#emotionalstory #kindness #friendship #family`. Never #fyp, #foryou or #viral.
Title in Title Case + one emoji.

After rendering, `python3 pipeline/check_video.py stories/FILE.json` must pass (length,
1080x1920 30 fps, 48 kHz stereo, -14 LUFS, true peak, voice over music, pauses, twist
position, hook and caption rules) before the video is posted.

```json
{
  "slug": "short-name", "date": "YYYY-MM-DD",
  "caption": "TikTok caption with #inthisworld #story #storytime #emotional #fyp",
  "mood": "emotional|hopeful|tense|mystery",
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
