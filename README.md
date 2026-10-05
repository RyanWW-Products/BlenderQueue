# BlenderQueue

Queue up Blender files and render them one after another, unattended.

Each job renders either with the settings saved in the `.blend`, or with
per-group overrides you set in the app. Follow Path constraints can be
retargeted per job — so one crash scene with two paths becomes two queued
renders, one following each path. Any file can also be analysed to see what
will make it slow before you commit to rendering it.

## The two downloads

| | What it is | Where its settings live |
| --- | --- | --- |
| `BlenderQueue-1.1.0-Setup.exe` | Normal installer. Start Menu entry, optional desktop shortcut and `.bqueue` file association, proper uninstaller. Installs per-user, so no administrator rights. | `%APPDATA%\BlenderQueue` |
| `BlenderQueue-1.1.0-portable.zip` | Unzip and run. Nothing is installed and nothing is written outside the folder. | `BlenderQueueData` beside the .exe |

Both contain the same application. The portable build is marked by a
`portable.txt` file next to the executable; delete it and that copy starts
behaving like an installed one.

Keep the `_internal` folder next to the executable in both cases.

**Tools → Updates** checks the latest public release on
[GitHub](https://github.com/ryanw341/BlenderQueue), compares it with the installed
version, and links to the latest release downloads and repository. Download
the installer or portable build there, then close BlenderQueue before replacing
your installed copy. The links remain available if the update check fails.

Blender itself is **not** bundled. The app finds your existing installs
automatically (Program Files, Steam, PATH, and the file association in the
registry) and you can point it at any other build from the Render tab.

## The queue

Add files with **Queue → Add Files**, **Add Folder**, or by dragging `.blend`
files (or whole folders) onto the window.

| Action | How |
| --- | --- |
| Reorder | Drag rows, or `Ctrl+Up` / `Ctrl+Down` / `Ctrl+Home` / `Ctrl+End` |
| Rename | Double-click the name, or `F2` |
| Duplicate | `Ctrl+D` |
| Delete | `Del` |
| Include / skip without deleting | The checkbox on each row, or `Space` |

Queues save to `.bqueue` files (**Queue → Save As**), and the current queue is
restored automatically next time you open the app.

The list shows, per job: status, progress, frame range, **average time per
frame**, **estimated time left**, analysis rating, scene, which overrides are
active, and which Blender build it will use. The status bar carries the ETA for
the job currently rendering.

### While a job is rendering

The job being rendered is locked. It cannot be renamed, reordered, disabled,
re-targeted or have its settings changed while Blender is working on it, and
its Render Settings tab shows a notice instead of editable controls. Every
other job in the queue stays fully editable. The lock lifts as soon as the job
finishes, is skipped, or the queue is stopped.

## Render settings

Leave **Override the render settings saved in this file** off and the job
renders exactly as the file is set up.

Turn it on and you get eight collapsible groups, each with its own switch:

- **Scene and Camera** — scene, camera, world, single view layer
- **Frame Range** — animation range and step, or a single still
- **Output** — folder, file name, format, colour depth, FFmpeg codec settings
- **Format and Dimensions** — resolution, scale, frame rate, pixel aspect
- **Render Engine** — Cycles / EEVEE / Workbench, samples, denoising, bounces, motion blur
- **Performance and Simplify** — threads, persistent data, tile size, subdivision limits
- **Colour Management** — view transform, look, exposure, gamma
- **Metadata Stamp** — burn frame numbers, dates and notes into the image

A group that is off changes nothing. Switching a group on seeds it with the
values actually read out of your `.blend`, so you always start from something
real — the ↻ button re-seeds it at any time.

Fields appear and disappear based on what is relevant: pick FFmpeg and the
codec options appear, pick Cycles and the EEVEE sampling row goes away.

### Output tokens

`Output Folder` and `File Name` understand these:

`{job}` `{blend}` `{scene}` `{date}` `{time}` `{index}`

So `D:\renders\{date}\{job}\` gives each job its own dated folder.

## Per Job Visibility

Select a job and open **Per Job Visibility** beside Render Settings. Use
**Read File** to load or refresh the outliner, including jobs restored from older
queues, then enable **Override visibility for this job**.

The expandable tree shows nested collections, objects, and object parenting.
Search finds objects and collections while retaining their parent hierarchy;
**Expand All** and **Collapse All** control the tree. Objects and collections
linked in several places appear in each location.

| Control | Effect |
| --- | --- |
| Render | Allow an object or collection to render, across all view layers |
| Include | Include a collection in the selected view layer |
| Holdout | Use a collection as a holdout mask in that layer |
| Indirect | Restrict a collection to indirect lighting in that layer (Cycles) |
| Render this layer | Include the selected view layer in the render |

The scene follows **Render Settings → Scene and Camera**. The view-layer picker
chooses which layer's controls you are editing; it does not switch the render to
that layer. Collection inclusion is specific to each location in the hierarchy.
An object's Render switch is shared across its collection links. Hidden parent
collections still hide their contents; hiding a parent object does not hide its
child objects. The State column describes restrictions at that location, rather
than predicting camera framing, materials, or other rendering effects.

Bold controls are explicit job overrides. Right-click rows to show or hide
selected entries, or restore their file settings. **Reset Scene** clears all
visibility overrides for the current scene. Turning off the master switch
temporarily disables the overrides while keeping your choices.

Visibility settings work independently of the Render Settings master switch.
They save with the queue, follow duplicated jobs, and are included by **Copy
Settings**. The running job is locked. Overrides apply only to Blender's render
process, including animated render visibility; the original `.blend` is never
saved or changed. Missing or renamed entries are reported in the render log.

## Analysis

**Analysis → Analyse** (`F7`) opens the `.blend` read-only and measures what
will make it expensive, then rates the whole job out of 100 and says what is
worth changing. Nothing in your file is modified.

The score is anchored on a deliberately ordinary render — 1920x1080, 128 Cycles
samples, 100 frames — which scores 50. So the number means "compared with a
normal job", and the panel also states the load as a plain multiple, e.g.
*about 316x the work of a typical 1080p, 128-sample, 100-frame job*.

| Score | Rating |
| --- | --- |
| 0-24 | Light |
| 25-44 | Moderate |
| 45-64 | Heavy |
| 65-84 | Very Heavy |
| 85-100 | Extreme |

Below the score is a ranked **Worth changing first** list, then a dropdown per
category, each with its own load percentage:

- **Sampling** — sample count, adaptive sampling, denoising, light bounces, caustics, CPU vs GPU
- **Geometry** — triangles at render time, the heaviest objects by name, render-time subdivision
- **Output Settings** — resolution, frame count, view layers, motion blur, persistent data
- **Textures** — total image memory, 4K/8K counts, missing files, float images
- **Lighting** — light count, large soft shadows, HDRI resolution, world volumes
- **Materials and Shading** — glass, refraction, subsurface, volumes, true displacement
- **Effects and Simulation** — volumes, particles and hair, compositor nodes

Individual findings read like this:

> **Max samples**  2,000 — Render load: 83%
>
> Consider 256-512 samples with Adaptive Sampling and Denoising on. Beyond a
> few hundred samples the noise drops very slowly for a linear increase in time.

Geometry is called out by object, so a scene of three models where one is a
million triangles gets flagged by name with its share of the scene. Render-time
subdivision is resolved too — a 12-triangle cube with subdivision level 6 is
reported as the 49,152 triangles it actually becomes.

**Analyse All** does the whole queue. **Export Report** writes the full report,
including every measured number, to a text file.

Analysis results are saved with the queue, so they survive restarts.

## Rendering

**Render → Start** (`F5`) works down the queue. Per-frame progress shows in
the row and the status bar, with Blender's own log on the Log tab.

- **Pause** stops after the current job rather than mid-frame
- **Stop** ends the run immediately
- **Skip Job** abandons the current file and moves to the next
- **Dry Run** applies everything and reports what *would* render, without rendering

**Render → Reset Selected** (also in the row's right-click menu) resets selected
jobs to Pending and enables them for another run. It clears progress, elapsed
times, errors and the old log while preserving render settings, visibility,
Follow Path choices, and files already written. Rendering or encoding jobs are
locked. **Start** runs enabled Pending jobs; completed, failed, stopped and
skipped jobs can be queued again with Reset Selected.

### Stopping a video render

Video jobs first write lossless EXR frames in a `.blenderqueue-frames-*` folder
beside the output video. Blender then encodes those frames with the job's video
settings and audio. The final video path is published only after encoding has
finished, so stopping cannot leave an unfinished movie at that path.

After **Stop**, **Skip Job**, or an unexpected Blender exit, the app asks whether
to **Encode Rendered Frames** or **Keep Frames Only** when complete frames exist.
Encoding saves a separately named `-partial-` video without rerendering the scene
or replacing a previous finished video. The frame folder remains available in
either case. Closing the app during a render offers the same choice and waits
for encoding before closing. If encoding fails or is stopped, the frames are
retained and the failure is reported.

Complete video renders automatically remove their frame cache after the movie
is saved. Interrupted renders retain it, so allow extra disk space for lossless
frames. The Output action opens retained frames when there is no finished video.
Existing corrupt movies cannot be reconstructed without saved frames; this
protection applies to new renders. Stereo/multiview jobs should use image-sequence
output; recovery-safe video currently supports single-view output.

Time per frame is averaged over the last 25 finished frames, so the estimate
tracks a render that speeds up or slows down rather than being dragged by the
first frame's scene-build cost.

Optional finishing behaviour: stop the queue on an error, open the output
folder, or shut the PC down (with a 60-second cancel window).

### "Ignore add-ons and preferences"

On by default, and worth keeping on. It runs Blender with `--factory-startup`,
which skips your user preferences and add-ons. Some add-ons — BlenderKit and
MCP bridges especially — stall Blender badly in background mode, and a stalled
background render looks exactly like a hung queue.

Cycles is enabled explicitly by the app, so it still works with this on. Turn
it off only if a scene genuinely needs an add-on to render.

## Follow Path targets

**Tools → Follow Paths** (`Ctrl+P`) lists every Follow Path constraint in the
job's scene — on objects *and* on pose bones — and lets you change:

- which curve it targets
- Follow Curve on/off and the forward axis
- offset factor and influence

**Create one job per path…** is the shortcut for the common case: pick a
constraint, tick the curves you care about, and the app clones the job once per
curve, naming each from a pattern like `{job} - {path}`. Your overrides come
along with every copy.

Note that Follow Path is a *constraint* in Blender (Object Properties →
Constraints), not a modifier. Curve *modifiers* are read too and shown under
File Contents.

## Building from source

```text
pip install -r requirements.txt
python main.py
```

To build both distributions:

```text
pip install pyinstaller
python build.py
```

`build.py` compiles the sources, runs PyInstaller, makes the packaged
executable run its own self-test, then produces the portable folder, its zip,
and the installer. `--portable` / `--installer` build just one; `--no-build`
reuses the existing `dist\BlenderQueue`.

The installer needs [Inno Setup 6](https://jrsoftware.org/isdl.php); without it
the portable build is still produced and the installer step is skipped with a
note.

This is deliberately a one-folder PyInstaller build. A one-file build has to
unpack ~110 MB into `%TEMP%` on every launch, which Defender then rescans;
startup went from one second to nearly two minutes on this machine.

## When something goes wrong

Every launch writes a startup log with a timestamped line for each step, plus
any unhandled exception. It is in `%APPDATA%\BlenderQueue\startup.log`, or
`BlenderQueueData\startup.log` for the portable build. If the app opens but
never finds Blender, or hangs before the queue is usable, that file says how
far it got.

Blender's own output for each job is on the **Log** tab, including the exact
command line used, so you can reproduce any job by hand.

## How it works

The app never links against Blender. It launches `blender.exe -b <file>
--factory-startup --python <script>` and talks to scripts that run
inside Blender's own interpreter:

- `bq_inspect.py` reports scenes, cameras, curves, Follow Path constraints and
  every current render setting as JSON
- `bq_render.py` applies a job's overrides and renders, reporting progress as
  `BQ>>{...}` lines
- `bq_encode.py` encodes completed recovery frames after an interrupted render;
  `bq_video.py` manages the shared frame cache and video encoding
- `bq_analyze.py` measures geometry, textures, lighting, materials, volumes,
  particles and sampling

Scoring lives in `blenderqueue/analysis.py`, separate from the measuring, so
the ratings can be retuned without re-reading every `.blend`.

Which render settings exist is declared once in `blenderqueue/schema.py`. The
editor UI, the saved job files and the apply step are all generated from that
table, so adding a setting means adding one line there.

`bq_visibility.py` is shared by inspection and rendering. It identifies linked
datablocks by name and library and view-layer collections by their full paths.

Run the model and offscreen Qt regression tests with:

```text
python -m unittest discover -s tests -v
```

The Blender integration test generates a small scene, checks hierarchy and
layer settings, renders visibility variants, and verifies the output pixels:

```text
blender -b --factory-startup --python-exit-code 1 --python tests/blender_visibility_smoke.py -- --out build/visibility-smoke
```

To test actual interrupted video renders, recovery encoding, audio, and output
decoding (requires `ffmpeg` and `ffprobe` on PATH for verification only):

```text
python tests/run_video_smoke.py --blender "C:/path/to/blender.exe" --out build/video-smoke
```
