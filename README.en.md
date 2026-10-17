# ClipSlicer

[![CI](https://github.com/vtubeadmirer/clipslicer/actions/workflows/ci.yml/badge.svg)](https://github.com/vtubeadmirer/clipslicer/actions/workflows/ci.yml) [![Release](https://github.com/vtubeadmirer/clipslicer/actions/workflows/release.yml/badge.svg)](https://github.com/vtubeadmirer/clipslicer/releases) [![Latest](https://img.shields.io/github/v/release/vtubeadmirer/clipslicer?label=download)](https://github.com/vtubeadmirer/clipslicer/releases/latest)

[한국어](README.md) · **English**

A lightweight Windows video cutter. Watch a long video, drop a marker wherever you think **"cut here"**, and every segment is saved as its own file.
Pull clips out of stream VODs and lectures, turn them into Shorts, and upload them to YouTube, all in one program.

- No installer, fully portable (copy the folder to a USB stick and it still runs)
- Cuts without re-encoding by default, so it finishes **in seconds** with zero quality loss
- Built on ffmpeg, libmpv and PySide6, so it plays and edits nearly every format
- For streamers: bookmark moments while live, find highlights from chat and audio reactions, captions and watermark, post to Discord (0.8)

> UI available in Korean and English (Settings ▸ Language; follows the system language by default).

```mermaid
flowchart LR
    A["🎬 Open<br/>files · folder · URL · recent"] --> B["▶ Scrub<br/>frame step · thumbnails · waveform · chat graph"]
    B --> C["✂ Mark<br/>S · I/O · auto markers · bookmarks"]
    C --> D["📦 Export<br/>per segment · merge · Shorts · caption"]
    D --> E["⬆ Publish<br/>YouTube · Discord"]
```

## Download

Grab `ClipSlicer-vX.Y.Z-win64.zip` from [Releases](https://github.com/vtubeadmirer/clipslicer/releases/latest), unzip, run `ClipSlicer.exe`. The current version is **0.8**.
Windows 10 (1809+) / 11, 64-bit. If SmartScreen warns on first launch, choose **More info → Run anyway**.

When a new version is published, an **⬆ update** button appears inside the app; one click downloads, verifies, swaps the files and restarts.
Releases that only change the code arrive as a **lite update** of about 20 MB that keeps the bundled ffmpeg and libmpv.

## 30-second tour

1. Drag a video into the window (several files, a folder, or a YouTube/Chzzk URL via `Ctrl+L`)
2. Play, and press **`S`** where you want to cut. A red marker appears and the timeline splits into segments.
   - To pull out just the good parts: **`I`** at the start, **`O`** at the end. Only that range stays on; everything else is turned off.
3. `Ctrl+click` a segment to turn it off
4. **`Ctrl+E`**. Every enabled segment is saved as `name_01.mp4`, `name_02.mp4`, …

## Features

| Area | What you get |
|---|---|
| Cutting | Split mode (`S`), clip mode (`I`/`O`), frame stepping, undo/redo, segment names (`N`/`F2`) and **notes**, **merge order** ▲▼, auto-saved project files (`.clipslicer.json` + `.bak`) |
| Timeline | Thumbnail strip, audio waveform, **chat reaction graph**, keyframe marks, `Ctrl+wheel` zoom, hover preview, analysis cache, collapsible right panel (`Ctrl+Shift+R`) |
| Auto markers | Silence detection, scene-change detection, **loud moments (laughter, cheering)**, paste timestamps (YouTube chapters, comments), **chat reaction peaks and keyword markers** (CHZZK and YouTube live replays) |
| Stream bookmarks | **Stream bookmark mode**: a global hotkey (`Ctrl+Alt+B` …) records moments while streaming or recording; open the recording and the bookmarks are offered as markers |
| Output | Fast (lossless copy), Smart (re-encode only the first second), Precise (full re-encode), **vertical 9:16 Shorts** (crop or **blur background**), video only (no sound), audio only (m4a/mp3), merge segments, filename patterns, GPU encoding (NVENC/QSV/AMF) |
| Output effects | **Loudness normalization** (-14 LUFS), **burned-in caption**, **burned-in subtitles** (srt/ass/vtt), **watermark** PNG, **intro/outro** videos |
| Import | **Open from URL** with built-in yt-dlp: YouTube, Chzzk, Twitch and more; download only a time range of long VODs; **Record from site** (sign in once in the built-in browser, the stream is detected when it plays, one-click live recording — e.g. rplay); **record several streams at once** (recordings & downloads list); **browser extension link** (one click sends the stream playing in Chrome/Edge/Whale to ClipSlicer, logged in as you are); direct m3u8 download; start screen with recent work and a sample video |
| Publish | **YouTube upload** of the cut files to your connected channel as private videos (title, description, tags, thumbnail, playlist, resumable, pre-upload limit checks), **upload presets**, **scheduled publish**, **upload history**, **Discord webhook** posting, copy chapter list, save current frame as PNG |
| Ops | Update notifications with self-replacement (**lite updates**), tray notifications, first-run guide, error log and dialogs, compatibility mode for GPU-less machines, portable settings (`settings.ini`) |

The full manual is in **[docs/index.html](docs/index.html)** (Korean) and in the in-app help (`F1`).

## Why three cutting modes

Compressed video stores a complete picture only every few seconds (a keyframe). Cutting without re-encoding therefore starts at the previous keyframe, usually 1–2 s early.

```
keyframes     K·····K·····K·····K·····
cut here            │
Fast          K═════│═══════════      ← starts at the previous keyframe (extra lead-in)
Smart             ▓▓▓K═══════════     ← only ▓ is re-encoded, the rest is copied
Precise           ▓▓▓▓▓▓▓▓▓▓▓▓▓▓     ← everything re-encoded
```

| Mode | Speed | Start point | Quality |
|---|---|---|---|
| **Fast** (default) | instant | pulled back to the previous keyframe | untouched |
| Smart | fast | frame-accurate | only the first 1–2 s re-encoded |
| Precise | slow | frame-accurate | full re-encode (CRF 18) |

Fast is enough most of the time; use Smart when the shifted start bothers you.

## Shortcuts

| Key | Action |
|---|---|
| Space / K | Play / pause |
| ← → · Shift+← → · Ctrl+← → | 1 frame · 1 s · 10 s |
| S | Cut marker |
| I / O | Clip start / end |
| E | Toggle current segment |
| N / F2 | Edit segment name (under the cursor / selected row) |
| Delete | Delete nearest marker |
| Ctrl+Z / Ctrl+Y | Undo / redo |
| R / L | Loop ±2 s around cursor / loop current segment |
| ↑ ↓ | Previous / next segment |
| Ctrl+Shift+↑ ↓ | Move earlier / later in the merge order |
| Ctrl+wheel / Ctrl+0 | Zoom timeline / fit |
| Ctrl+Shift+R | Collapse / expand the right panel |
| Ctrl+Shift+M / Ctrl+Shift+S / Ctrl+Shift+L | Auto markers: silence · scene change · loud moments |
| Ctrl+Shift+V / Ctrl+Shift+C | Paste timestamps / chat reaction graph & markers |
| Ctrl+Alt+B | Stream bookmark (global, while the bookmark window is open) |
| Ctrl+L / Ctrl+U / Ctrl+P | Open from URL / upload to YouTube / save frame as PNG |
| Ctrl+E | Export all |
| F1 | Help |

## For streamers (0.8)

- **Stream bookmark mode** (File menu): a small always-on-top window. Press the global hotkey while live to record the moment; when you open the recording, the bookmarks from that time range are offered as markers (file modified time = end of recording).
- **Chat reaction graph** (`Ctrl+Shift+C`): fetches CHZZK VOD or YouTube live-replay chat, draws it as an orange graph on the timeline and adds markers at reaction peaks and keyword bursts. Chat is cached as `video.clipslicer.chat.json`.
- **Loud-moment markers** (`Ctrl+Shift+L`): finds laughter, cheering and other spikes in the waveform (default 2 s lead).
- **Output effects**: loudness normalization, burned-in caption and subtitles, Shorts blur background, watermark, intro/outro (Settings ▸ Watermark / intro & outro…). A caption, subtitles or watermark forces a re-encode.
- **Publishing**: YouTube upload presets, scheduled publish and upload history; automatic **Discord webhook** posting when an export finishes (Settings ▸ Discord webhook…).
- **Convenience**: start screen (recent work, sample video), first-run guide, tray notifications, segment notes, merge order, `.bak` project backups, lite updates.

## About YouTube upload

Two limits come from the YouTube API itself:
- Videos uploaded through a personal, unverified Google Cloud project are **locked to private**. ClipSlicer fills in all metadata; you flip the visibility in YouTube Studio.
- The default API quota allows roughly **6 uploads per day**, regardless of file size or length.

You create a free OAuth client in Google Cloud Console once (about 10 minutes); the in-app settings dialog walks you through it.

## Architecture

```mermaid
flowchart TB
    subgraph UI["🖥 PySide6 UI"]
        MW["main window · timeline · dialogs"]
        PL["player (libmpv)"]
    end
    subgraph BG["⚙ background threads"]
        AN["analysis<br/>thumbnails · waveform · keyframes"]
        EX["export queue"]
        DL["download"]
        UP["YouTube upload"]
        CH["chat fetch"]
        DC["Discord post"]
        UD["updater"]
    end
    subgraph EXT["📦 bundled tools"]
        FF["ffmpeg / ffprobe"]
        MPV["libmpv-2.dll"]
        YD["yt-dlp (embedded module)"]
    end
    MW --> AN & EX & DL & UP & CH & DC & UD
    MW --> PL --> MPV
    AN & EX --> FF
    DL --> YD --> FF
    UP -->|OAuth · REST| YT[("YouTube Data API")]
    CH -->|REST · yt-dlp| CZ[("CHZZK · YouTube chat")]
    DC -->|Webhook| DS[("Discord")]
    UD -->|Releases| GH[("GitHub")]
```

## Run from source · build

```
git clone https://github.com/vtubeadmirer/clipslicer
cd clipslicer
pip install -r requirements.txt
python tools\get_ffmpeg.py        # bin\ffmpeg\  (shared build, pinned version)
python tools\get_libmpv.py        # bin\libmpv-2.dll  (needs 7-Zip or Bandizip)
python main.py
```

Build the exe with `.\build.ps1` → `dist\ClipSlicer\`. Pushing a `vX.Y.Z` tag makes GitHub Actions build and attach the zip plus its SHA-256 to a release.

```
main.py              entry point
app/mainwindow.py    main window
app/player.py        libmpv player widget
app/timeline.py      timeline widget (thumbnails, waveform, chat graph)
app/segments.py      marker/segment model, notes and merge order, undo, project files (.bak), loud-peak and bookmark maths
app/ffmpeg_tools.py  analysis, cutting, merging, caption/subtitle/watermark/intro rendering (ffmpeg)
app/workers.py       background jobs (analysis, export, download)
app/bookmarks.py     stream bookmarks (global hotkey, log, import)
app/chat.py          CHZZK / YouTube chat fetch, reaction and keyword peaks
app/discord.py       Discord webhook posting
app/startpanel.py    start screen            app/firstrun.py  first-run guide and sample video   app/notify.py  tray notifications
app/youtube.py       YouTube OAuth + upload   app/youtube_ui.py  upload dialogs and presets   app/upload_history.py  upload history
app/updater.py       update check and self-replacement (lite / full)
app/hls_section.py   HLS range download       app/ytdlp_patches.py  yt-dlp fixes
tests/               unit and integration tests (run in CI)
docs/index.html      user manual (Korean)
```

## Troubleshooting

Errors are written to `logs\clipslicer.log` and unhandled ones are shown in a dialog (Help ▸ Open log folder).
If the video area stays black (remote desktop, VMs), enable **Compatibility mode** in Settings and restart.
Please attach the log when opening an [issue](https://github.com/vtubeadmirer/clipslicer/issues).

## License

MIT. Bundled components keep their own licenses: ffmpeg (GPL), libmpv (GPL), yt-dlp (Unlicense), PySide6 (LGPL).
