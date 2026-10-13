"""English help pages (mirror of help.py PAGES)."""
from . import __version__

PAGES_EN = [
("Getting started", """
<h2>What ClipSlicer does</h2>
<p>Watch a long video and drop a cut marker wherever you think <b>"cut here"</b>. The gaps between markers become segments,
and each segment is saved as its own file. Unlike an editor with In/Out points, <b>one marker = one cut</b>, so the mental model stays simple.</p>

<h2>Five steps</h2>
<ol>
 <li><b>Open a video</b> — drop it anywhere on the window or press <kbd>Ctrl+O</kbd>. Several files or a whole folder work too.
     They pile up in the list on the left, and every video keeps its own markers.</li>
 <li><b>Find the spot</b> — <kbd>Space</kbd> plays/pauses. After pausing, <kbd>←</kbd> <kbd>→</kbd> step one frame at a time.
     Hovering the timeline shows a thumbnail of that position so scrubbing is easy.</li>
 <li><b>Drop a marker</b> — <kbd>S</kbd> or the <b>✂ Cut here</b> button. A red line appears and the timeline splits into coloured segments.</li>
 <li><b>Tidy up</b> — <kbd>Ctrl</kbd>+click a segment on the timeline (or untick it in the list) to turn it off.
     Double-click the file name column to rename a segment.</li>
 <li><b>Export</b> — <kbd>Ctrl+E</kbd>. Every enabled segment is saved as a file.
     The default location is the <code>name_cuts</code> folder next to the source.</li>
</ol>

<h2>Two ways of working</h2>
<ul>
 <li><b>Split mode (S)</b> — for dividing a long video into pieces. Markers add segments and everything is on by default.</li>
 <li><b>Clip mode (I / O)</b> — for pulling out just the good parts. <kbd>I</kbd> at the start, <kbd>O</kbd> at the end: only that range stays on and the rest is turned off.
     Repeat to collect clips, and enable <b>Merge into one</b> to make a highlight reel.</li>
</ul>
<div class="tip">Markers and segment settings are <b>auto-saved</b> next to the video as <code>video.clipslicer.json</code>.
Open the same video again and your work comes back.</div>

<h2>Layout</h2>
<table>
 <tr><th>Left</th><td>Video list. Click to switch, or <kbd>Ctrl+↑</kbd> <kbd>Ctrl+↓</kbd>.</td></tr>
 <tr><th>Centre top</th><td>Player. Click to play/pause.</td></tr>
 <tr><th>Centre bottom</th><td>Timeline (thumbnails · waveform · segments · markers · keyframes), transport controls, volume and speed.</td></tr>
 <tr><th>Right</th><td>Segment list and export settings/progress.</td></tr>
</table>
"""),

("Shortcuts", """
<h2>Playback · navigation</h2>
<table>
 <tr><th>Key</th><th>Action</th></tr>
 <tr><td><kbd>Space</kbd> / <kbd>K</kbd></td><td>Play · pause</td></tr>
 <tr><td><kbd>←</kbd> <kbd>→</kbd></td><td>One frame back / forward (pauses)</td></tr>
 <tr><td><kbd>Shift</kbd>+<kbd>←</kbd> <kbd>→</kbd></td><td>1 second</td></tr>
 <tr><td><kbd>Ctrl</kbd>+<kbd>←</kbd> <kbd>→</kbd></td><td>10 seconds</td></tr>
 <tr><td><kbd>J</kbd></td><td>5 seconds back</td></tr>
 <tr><td><kbd>Home</kbd> / <kbd>End</kbd></td><td>Start / end</td></tr>
 <tr><td><kbd>↑</kbd> <kbd>↓</kbd></td><td>Previous / next segment start</td></tr>
 <tr><td><kbd>[</kbd> <kbd>]</kbd></td><td>Slower / faster (0.25x – 4x), <kbd>\\</kbd> back to 1x</td></tr>
 <tr><td><kbd>M</kbd></td><td>Mute</td></tr>
 <tr><td><kbd>R</kbd></td><td><b>Loop ±2 s</b> around the current position (press again to stop)</td></tr>
 <tr><td><kbd>L</kbd></td><td>Loop the current segment on/off</td></tr>
</table>

<h2>Markers · segments</h2>
<table>
 <tr><th>Key</th><th>Action</th></tr>
 <tr><td><kbd>S</kbd></td><td>Cut marker at the current position</td></tr>
 <tr><td><kbd>I</kbd> / <kbd>O</kbd></td><td><b>Clip mode</b>: start / end. O keeps only the range and turns the rest off. <kbd>Esc</kbd> cancels</td></tr>
 <tr><td><kbd>Delete</kbd></td><td>Delete the marker nearest to the cursor</td></tr>
 <tr><td><kbd>Ctrl+Z</kbd> / <kbd>Ctrl+Y</kbd></td><td>Undo / redo (all marker and segment changes)</td></tr>
 <tr><td><kbd>E</kbd></td><td>Toggle the segment under the cursor</td></tr>
 <tr><td><kbd>Ctrl+Shift+M</kbd></td><td>Markers at silence</td></tr>
 <tr><td><kbd>Ctrl+Shift+S</kbd></td><td>Markers at scene changes</td></tr>
 <tr><td><kbd>Ctrl+Shift+V</kbd></td><td>Paste timestamps → markers</td></tr>
</table>

<h2>Timeline (mouse)</h2>
<table>
 <tr><th>Action</th><th>Effect</th></tr>
 <tr><td>Click · drag</td><td>Seek (thumbnail preview while dragging)</td></tr>
 <tr><td>Drag a marker</td><td>Move it</td></tr>
 <tr><td>Right-click</td><td>Empty area: add marker / on a marker: delete it</td></tr>
 <tr><td><kbd>Ctrl</kbd>+click</td><td>Toggle that segment</td></tr>
 <tr><td>Double-click</td><td>Loop that segment</td></tr>
 <tr><td><kbd>Ctrl</kbd>+wheel</td><td>Zoom in / out around the mouse</td></tr>
 <tr><td>Wheel</td><td>Scroll when zoomed in</td></tr>
 <tr><td><kbd>Ctrl</kbd>+<kbd>0</kbd></td><td>Fit the whole video</td></tr>
</table>

<h2>Files · other</h2>
<table>
 <tr><td><kbd>Ctrl+O</kbd></td><td>Open video</td></tr>
 <tr><td><kbd>Ctrl+L</kbd></td><td>Open from URL (YouTube · Chzzk · Twitch …)</td></tr>
 <tr><td><kbd>Ctrl+P</kbd></td><td>Save the current frame as PNG (next to the video)</td></tr>
 <tr><td><kbd>Ctrl+U</kbd></td><td>Upload to YouTube (choose files)</td></tr>
 <tr><td><kbd>Ctrl+E</kbd></td><td>Export all videos</td></tr>
 <tr><td><kbd>Ctrl+Shift+E</kbd></td><td>Export the current video only</td></tr>
 <tr><td><kbd>Ctrl+↑</kbd> <kbd>Ctrl+↓</kbd></td><td>Previous / next video</td></tr>
 <tr><td><kbd>F1</kbd></td><td>This help</td></tr>
</table>
"""),

("Timeline", """
<h2>Reading the timeline</h2>
<p>From the top: the <b>thumbnail strip</b>, a translucent <b>audio waveform</b> (teal) on top of it, <b>segment blocks</b> in different colours,
and the <b>time ruler</b> below. Thumbnails, waveform and keyframes are generated in the background, so the strip may be empty for a few seconds.</p>
<ul>
 <li><b>White line</b> — current position (playhead)</li>
 <li><b>Red line with a triangle</b> — cut marker. Drag to move.</li>
 <li><b>Coloured block with a number</b> — segment. Disabled segments are dark and marked with ✕.</li>
 <li><b>Yellow border</b> — the segment currently looping</li>
 <li><b>Small white dots under the ruler</b> — keyframes (see "Cutting modes")</li>
</ul>

<h2>Zoom in to be precise</h2>
<p>In a one-hour video one pixel is about three seconds. Zoom with <kbd>Ctrl</kbd>+wheel around the mouse; a scrollbar appears when zoomed in.
During playback the view follows the playhead. <kbd>Ctrl</kbd>+<kbd>0</kbd> fits the whole video again.</p>

<h2>Thumbnail preview</h2>
<p>Hovering or dragging on the timeline pops up the thumbnail and time of that position, so you see the scene before the player catches up.</p>

<h2>Finding quiet parts with the waveform</h2>
<p>Low parts of the waveform are pauses or silence. Pause near one and fine-tune with <kbd>←</kbd> <kbd>→</kbd>, or use <b>Edit ▸ Markers at silence</b>.</p>

<h2>Typing a time</h2>
<p>Click the time display in the transport bar to type a time: <code>1:23.5</code>, <code>01:02:03</code>, <code>83.5</code> or <code>1h2m3s</code>, then <kbd>Enter</kbd>.</p>
"""),

("Cutting modes", """
<h2>Three modes</h2>
<table>
 <tr><th>Mode</th><th>Speed</th><th>Accuracy</th><th>Quality</th><th>Use when</th></tr>
 <tr><td><b>Fast (default)</b></td><td>instant</td><td>start may move back to the previous keyframe (usually 1–2 s)</td><td>untouched</td><td>almost always; cuts the original without re-encoding</td></tr>
 <tr><td><b>Smart</b></td><td>fast (reads the file once more)</td><td>frame-accurate</td><td>only the first 1–2 s re-encoded</td><td>the shifted start bothers you</td></tr>
 <tr><td><b>Precise</b></td><td>slow (faster with a GPU)</td><td>frame-accurate</td><td>full re-encode (CRF 18, near lossless)</td><td>Smart fails or the codec is unusual</td></tr>
</table>

<h2>Why "Fast" shifts the start — keyframes</h2>
<p>Compressed video stores a complete picture (<b>keyframe</b>) only every few seconds; the frames in between store just what changed.
Cutting without re-encoding can therefore only start at a keyframe. Fast mode copies from the keyframe just before the requested point,
so <b>the start is extended by up to one keyframe interval</b> (usually 1–2 s, up to 5–10 s for screen recordings). The end is exact. Nothing you asked for is lost.</p>
<p>The white dots under the ruler are keyframes. Enable <b>Settings ▸ Snap markers to keyframes</b> and markers stick to the nearest keyframe,
which makes Fast mode exact as well.</p>

<h2>What Smart mode does</h2>
<ol>
 <li>Re-encodes only from the requested start to the next keyframe (usually 1–2 s)</li>
 <li>Copies the rest of the segment untouched</li>
 <li>Joins the two pieces</li>
</ol>
<p>Fast, accurate and nearly lossless. Works with H.264 / HEVC; other codecs, or ranges without a keyframe, fall back to a full re-encode.
The export log shows which method was actually used (copy / smart / re-encode).</p>
<div class="warn">Because the two pieces have slightly different encoder settings, a few players may show a brief glitch at the join. Re-export such a file in Precise mode.</div>

<h2>GPU encoding</h2>
<p>NVIDIA (NVENC), Intel (QSV) and AMD (AMF) encoders are detected at startup. With <b>Settings ▸ Use GPU encoding</b> on, the re-encoding parts of Precise and Smart run 5–10x faster.
CPU encoding (libx264) gives slightly better quality at the same size.</p>
"""),

("Auto markers · merge · audio", """
<h2>Markers at silence</h2>
<p><b>Edit ▸ Markers at silence</b> (<kbd>Ctrl+Shift+M</kbd>). Finds parts where the sound stays below the threshold (default -35 dB) for at least the minimum length (default 1 s).</p>
<ul>
 <li><b>One marker in the middle</b> — clean split in the middle of each silence. For splitting lectures by topic.</li>
 <li><b>Two markers at both ends + disable the silence</b> — removes the silence itself. Combined with "Merge into one" you get a silence-free video.</li>
</ul>
<p>Adjust the threshold if too many or too few are found: about -25 dB for noisy recordings, down to -45 dB for clean ones. Auto markers can be undone with <kbd>Ctrl+Z</kbd>.</p>

<h2>Markers at scene changes</h2>
<p><b>Edit ▸ Markers at scene changes</b> (<kbd>Ctrl+Shift+S</kbd>). Finds hard cuts and transitions. The whole video is scanned at low resolution,
so a one-hour video takes 1–3 minutes; progress is shown in the export panel. Lower sensitivity values catch smaller changes; 0.3–0.5 is typical.</p>

<h2>Paste timestamps</h2>
<p><b>Edit ▸ Paste timestamps</b> (<kbd>Ctrl+Shift+V</kbd>). Paste YouTube chapters or comments like "12:34 highlight" and every
<code>12:34</code>, <code>1:02:03</code> or <code>0:45.5</code> becomes a marker. The clipboard is pre-filled.</p>

<h2>Copy chapters</h2>
<p>The <b>Copy chapters</b> button above the segment list copies the enabled segments as <code>00:00 name</code> lines. Paste them into a YouTube description to get chapters.</p>

<h2>Merge into one</h2>
<p>With <b>Merge into one</b> enabled in the export panel the enabled segments are joined in order into a single file named <code>name_merged</code>.
For "everything except the ads and chatter". The cutting mode still applies.</p>

<h2>Vertical 9:16 Shorts</h2>
<p>Set <b>Output</b> to "Vertical 9:16 Shorts" to re-encode each segment as a 1080×1920 vertical video (YouTube Shorts, Reels, TikTok).
<b>Crop position…</b> lets you drag a yellow box over the current frame to choose what to keep; the position is remembered per video.
This always re-encodes, so the cutting mode is ignored and the GPU encoder is used when available.</p>

<h2>Open from URL</h2>
<p><b>File ▸ Open from URL</b> (<kbd>Ctrl+L</kbd>). Paste a URL supported by yt-dlp (YouTube, Chzzk, Twitch VODs …) and it is downloaded and added to the list.
Choose the quality (best / 1080p / 720p / 480p) and the folder; the default is <code>Videos\\\\ClipSlicer</code>.
Downloaded files are not deleted. Videos that require a login cannot be downloaded.</p>
<div class="tip"><b>Download a range only</b>: VODs several hours long are tens of GB. Enable "Download a range only" and enter
<code>1:02:00 – 1:15:30</code> to get just that part (trimmed with a few seconds of margin). Recommended for Chzzk VODs.</div>

<h2>Audio only</h2>
<p>Set <b>Output</b> to "Audio only (m4a)" or "(mp3)". m4a copies the audio losslessly when the source is AAC, otherwise it converts to AAC 192 kbps. mp3 always converts (high-quality VBR).</p>

<h2>Filename pattern</h2>
<p><b>Settings ▸ Filename pattern</b>. <code>{name}</code> source name, <code>{n}</code> number, <code>{start}</code> <code>{end}</code> <code>{dur}</code> times.
Example: <code>{name}_{start}-{end}</code> → <code>stream_12m05s-15m40s.mp4</code>. A name typed in the segment list always wins.</p>

<h2>Existing files</h2>
<p>Before exporting you are asked whether to <b>overwrite</b>, <b>save with a number</b> or <b>cancel</b>.</p>
"""),

("YouTube upload", """
<h2>Upload the cut files straight to YouTube</h2>
<p>Enable <b>Upload to YouTube when done</b> in the export panel and the upload window opens when the export finishes.
Fill in the title (segment name), description (template), tags and thumbnail per file, choose visibility, category and playlist, then <b>Upload</b>.
Files you already have can be uploaded with <b>File ▸ Upload to YouTube</b> (<kbd>Ctrl+U</kbd>).</p>

<h3>One-time setup: connect the account</h3>
<p><b>Settings ▸ Connect YouTube account</b>. The YouTube API needs an OAuth client issued by Google, so follow the steps in that window:
create a project in Google Cloud Console, download <code>client_secret.json</code>, register it, and press "Connect account" (about 10 minutes, free).
Sign in and allow in the browser. The sign-in is encrypted by Windows and stored in the program folder (never in settings.ini).</p>

<div class="warn"><b>Uploads are private only.</b> Videos uploaded through a project that has not passed Google's verification are locked to private.
Upload with everything filled in, then <b>change the visibility in YouTube Studio</b> ("Open YouTube Studio" in the upload window).
After verification public and unlisted uploads work directly.</div>

<h3>Limits (checked automatically before uploading)</h3>
<ul>
 <li>Files over <b>12 hours</b> or <b>256 GB</b> are rejected by YouTube → blocked with an explanation. Split them in ClipSlicer.</li>
 <li>Videos over <b>15 minutes</b> need a phone-verified channel → warning.</li>
 <li><b>Shorts</b> are limited to 3 minutes → warning that longer videos become regular uploads.</li>
 <li>The daily count is shown as <code>(today n/6)</code> in the log and you are warned before exceeding it. It counts uploads, not size or length.</li>
</ul>
<p>The API quota is 10,000 units per day and one upload costs 1,600, so about <b>6 uploads per day</b>. Beyond that you get a "quota" error until the next day (midnight Pacific time).
You can request a higher quota in Google Cloud Console. Custom thumbnails need a phone-verified channel.</p>

<h3>Description template</h3>
<p><b>Settings ▸ YouTube description template</b>. <code>{title}</code>, <code>{source}</code>, <code>{start}</code>, <code>{end}</code>. Default: <code>Clip from {source} ({start} – {end})</code></p>

<h3>Shorts</h3>
<p>Vertical 9:16 exports become Shorts when "Append #Shorts to the title" is enabled (max 3 minutes).</p>

<h3>If the upload drops</h3>
<p>Uploads are resumable, so a brief network outage continues from the same place. If it fails completely, use "Retry failed items".</p>
"""),

("Settings · files", """
<h2>Settings menu</h2>
<table>
 <tr><th>Item</th><th>Description</th></tr>
 <tr><td>Snap markers to keyframes</td><td>Markers stick to a keyframe within 0.5 s. Makes Fast mode exact.</td></tr>
 <tr><td>Use GPU encoding</td><td>Uses the detected hardware encoder for re-encoding. The menu shows which one was found.</td></tr>
 <tr><td>Auto-save project</td><td>Saves markers and segments to <code>.clipslicer.json</code> next to the video. Off = work is lost when you close.</td></tr>
 <tr><td>Cache analysis results</td><td>Stores thumbnails, waveform and keyframes in <code>.clipslicer.cache</code> so the video opens instantly next time.</td></tr>
 <tr><td>Check for updates at startup</td><td>Queries GitHub releases (at most hourly). A green button appears when a new version exists. Nothing else is sent.</td></tr>
 <tr><td>Compatibility mode</td><td>Renders without GPU acceleration. For black video areas. Restart required.</td></tr>
 <tr><td>Connect YouTube account…</td><td>OAuth client registration and sign-in. See the "YouTube upload" tab.</td></tr>
 <tr><td>YouTube description template…</td><td>Pre-filled description text.</td></tr>
 <tr><td>Filename pattern…</td><td>Output file name pattern.</td></tr>
 <tr><td>Language</td><td>Korean / English / follow the system. Takes effect after a restart.</td></tr>
</table>

<h2>Project file (.clipslicer.json)</h2>
<p>Saved next to the video as <code>video.mp4.clipslicer.json</code>: markers, enabled segments, custom names, clip ranges, crop position and the last playback position.
Move it together with the video to keep your work. It is plain text.</p>

<h2>Updates</h2>
<p>When a new version exists a <b>⬆ Update</b> button appears at the bottom right. It shows the release notes and offers <b>Update now / Later / Skip this version</b>.
Update now downloads the zip, verifies its checksum, closes the app, replaces the files and restarts. <code>settings.ini</code>, logs and project files are kept and the previous version stays in <code>_backup</code>.
In read-only locations only the download page is offered.</p>

<h2>Portable</h2>
<p>No installer; settings live in <code>settings.ini</code> next to the program. Nothing is written to the registry, so you can <b>copy the folder to a USB stick</b> and use it anywhere.</p>

<h2>Output folder</h2>
<p>Leave it empty to create <code>name_cuts</code> next to each source, or set one folder to collect everything there. An option opens the folder when done.</p>

<h2>Command line · file association</h2>
<p><code>ClipSlicer.exe video1.mp4 video2.mkv</code> opens the files directly. In Explorer, right-click a video → Open with → choose ClipSlicer.exe to open videos by double-clicking.</p>
"""),

("Troubleshooting", """
<h2>Frequently asked</h2>
<h3>The video does not open or the picture is black</h3>
<p>libmpv plays nearly everything, but corrupt or DRM-protected files will not work. If only the picture is black (remote desktop, VMs, old GPUs) enable <b>Settings ▸ Compatibility mode</b> and restart.</p>

<h3>"Fast" cuts start too early</h3>
<p>Expected: keyframes (see "Cutting modes"). Use <b>Smart</b> mode or enable <b>Snap markers to keyframes</b>.</p>

<h3>The first seconds of a cut look broken</h3>
<p>A join problem from Smart mode in some players. Re-export in "Precise" mode.</p>

<h3>Export fails</h3>
<p>The log at the bottom right shows the ffmpeg error. Common causes: no write permission in the output folder, no disk space,
or MKV subtitle/attachment streams that cannot go into MP4 (use "Precise" then).</p>

<h3>No thumbnails or waveform</h3>
<p>Very long videos take tens of seconds. Videos without audio have no waveform. ffmpeg must be in the bin folder or on PATH.</p>

<h3>Shortcuts do not work</h3>
<p>If you are editing a file name in the segment list the keys go there. Press <kbd>Esc</kbd> or click the player once.</p>

<h3>"Required files are missing"</h3>
<p><code>ffmpeg.exe</code>, <code>ffprobe.exe</code> and <code>libmpv-2.dll</code> must be in the program folder (or its <code>bin</code>).
From source, run <code>python tools\\\\get_libmpv.py</code> and <code>python tools\\\\get_ffmpeg.py</code>.</p>

<h3>When an error appears</h3>
<p>Unhandled errors are shown in a dialog and every error is written to <code>logs\\\\clipslicer.log</code> (<b>Help ▸ Open log folder</b>).
Attach that file when reporting a problem. It contains the paths of the files you opened.</p>

<h2>About</h2>
<p>ClipSlicer """ + __version__ + """ — Python · PySide6 · libmpv · ffmpeg · yt-dlp.<br>
Source: <a href="https://github.com/vtubeadmirer/clipslicer">github.com/vtubeadmirer/clipslicer</a></p>
"""),
]
