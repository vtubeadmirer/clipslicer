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
     They pile up in the list on the left, and every video keeps its own markers.
     The start screen lists <b>recent work</b> to continue with one click, and <b>Try a sample video</b> generates a 30-second practice clip.</li>
 <li><b>Find the spot</b> — <kbd>Space</kbd> plays/pauses. After pausing, <kbd>←</kbd> <kbd>→</kbd> step one frame at a time.
     Hovering the timeline shows a thumbnail of that position so scrubbing is easy.</li>
 <li><b>Drop a marker</b> — <kbd>S</kbd> or the <b>✂ Cut here</b> button. A red line appears and the timeline splits into coloured segments.</li>
 <li><b>Tidy up</b> — <kbd>Ctrl</kbd>+click a segment on the timeline (or untick it in the list) to turn it off.
     Double-click the file name column (or press <kbd>N</kbd> / <kbd>F2</kbd>) to rename a segment, and use the <b>Note</b> column for reminders like "funny part here".</li>
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
Open the same video again and your work comes back. It is only created once you add markers or rename/annotate segments (not for videos you just opened), and the previous save is kept in <code>%LOCALAPPDATA%\\ClipSlicer\\backups</code>, not next to the video.</div>

<h2>Layout</h2>
<table>
 <tr><th>Left</th><td>Video list. Click to switch, or <kbd>Ctrl+↑</kbd> <kbd>Ctrl+↓</kbd>.</td></tr>
 <tr><th>Centre top</th><td>Player. Click to play/pause. With no video open it shows the start screen (open file · URL · sample · recent work).</td></tr>
 <tr><th>Centre bottom</th><td>Timeline (thumbnails · waveform · chat reaction graph · segments · markers · keyframes), transport controls, volume and speed.</td></tr>
 <tr><th>Right</th><td>Segment list (notes · merge order) and export settings/progress. <kbd>Ctrl+Shift+R</kbd> collapses it to give the player more room.</td></tr>
</table>
<p>On the first launch a three-step guide appears; <b>Help ▸ Getting started…</b> shows it again. Features for streamers (bookmarks · chat reactions · captions · watermark · Discord …) are collected in the "For streamers" tab.</p>
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
 <tr><td><kbd>N</kbd> / <kbd>F2</kbd></td><td>Edit the segment name (N: segment under the cursor, F2: selected row)</td></tr>
 <tr><td><kbd>Ctrl+Shift+↑</kbd> <kbd>Ctrl+Shift+↓</kbd></td><td>Move the selected segment earlier / later in the <b>merge order</b> (when "Merge into one" is on)</td></tr>
 <tr><td><kbd>Ctrl+Shift+M</kbd></td><td>Markers at silence</td></tr>
 <tr><td><kbd>Ctrl+Shift+S</kbd></td><td>Markers at scene changes</td></tr>
 <tr><td><kbd>Ctrl+Shift+L</kbd></td><td>Markers at loud moments (laughter, cheering)</td></tr>
 <tr><td><kbd>Ctrl+Shift+V</kbd></td><td>Paste timestamps → markers</td></tr>
 <tr><td><kbd>Ctrl+Shift+C</kbd></td><td>Chat reaction graph · reaction/keyword markers</td></tr>
 <tr><td><kbd>Ctrl+Alt+B</kbd></td><td>Stream bookmark (global hotkey while the bookmark window is open · configurable)</td></tr>
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
 <tr><td><kbd>Ctrl+Shift+R</kbd></td><td>Collapse / expand the right panel (segments · export)</td></tr>
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
<p>When merging is on, an <b>Order</b> column appears in the segment list. Use the ▲ ▼ buttons (or <kbd>Ctrl+Shift+↑</kbd> <kbd>Ctrl+Shift+↓</kbd>) to change the join order,
for example to put the ending scene first in a highlight reel. The order is saved in the project file and can be undone.</p>

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

<h2>Video only (no sound)</h2>
<p>Set <b>Output</b> to "Video only (no sound)" to save the picture without audio. The chosen method (Fast, Smart, Precise), merging and captions still apply; the audio is dropped at the end, so the video quality is unchanged. Handy when you want to add new background music.</p>


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

<h3>Presets · scheduled publish · upload history</h3>
<p>The <b>Preset</b> list at the top of the upload window fills the title, description, tags and category of every item at once.
<b>Scheduled publish</b> uploads as private and lets YouTube make it public at the chosen time, and every upload is recorded in <b>File ▸ Upload history</b>. Details in the "For streamers" tab.</p>
"""),

("For streamers", """
<h2>Tools for stream and recording work</h2>
<p>These features shorten the path from a VOD to finished clips: bookmark moments while streaming, find highlights from chat and audio reactions,
add captions and a watermark, export as Shorts and send the result to YouTube or Discord, all in one program.</p>

<h2>Record from site (streams that need a login)</h2>
<p><b>File ▸ Record from site</b> (<kbd>Ctrl+Alt+L</kbd>). Streams whose page URL yt-dlp does not support, or that need a login (such as rplay),
open in a small browser inside ClipSlicer. Sign in there once and it is remembered; as soon as the broadcast plays, the stream URL and login cookies
are detected and <b>● Start recording</b> lights up. <b>■ Stop recording</b> saves what was recorded as mp4 and opens it for editing.
Pasting an rplay page URL into Open from URL, or pressing <b>🌐 Open in browser and record</b>, opens the same window.</p>
<p>If you already have the m3u8 URL you can paste it into <b>Open from URL</b> (login cookies: Firefox or cookies.txt; Referer filled automatically).
DRM-protected streams cannot be downloaded. Use it to archive your own streams or streams you have permission for.</p>

<h2>Browser extension link (Chrome, Edge, Whale)</h2>
<p>When Google sign-in is blocked in the built-in browser (Google blocks sign-in inside apps) or a site can't be downloaded from its address,
play it in <b>your everyday browser</b> and send it with the <b>ClipSlicer 연결</b> extension. It reuses that browser's login and request details,
so members-only or age-restricted streams you can watch can also be saved.</p>
<p><b>Install (once)</b>: <b>File ▸ Browser extension link…</b> → <b>Open extension folder</b>. Type <code>chrome://extensions</code>
(Edge: <code>edge://extensions</code>) in the address bar → turn on <b>Developer mode</b> → <b>Load unpacked</b> → choose that folder.</p>
<p><b>Use</b>: <b>play</b> the stream or video → ClipSlicer icon in the toolbar (a red number shows how many streams were found) → <b>녹화/받기</b> (Record/Get; the extension popup is in Korean).
ClipSlicer comes to the front and starts right away; live streams record until you press <b>● Stop recording (save)</b>.
For sites with address support such as YouTube or Chzzk, <b>이 페이지 주소 보내기</b> (Send this page, with login) downloads it with your login cookies.</p>
<div class="tip">Data only travels inside this PC (127.0.0.1) and ClipSlicer only accepts requests from this extension. ClipSlicer must be running.
DRM-protected videos can't be downloaded. Use it to archive your own streams or streams you have permission to keep.</div>

<h2>Recordings &amp; downloads (record several at once)</h2>
<p><b>File ▸ Recordings &amp; downloads…</b> (<kbd>Ctrl+J</kbd>). Streams sent from the browser extension and videos from <b>Open from URL</b> each get a row here
and <b>run at the same time</b>. Stop each live recording with its own <b>■ Stop recording (save)</b>; when done, use <b>Open in editor</b> or <b>Folder</b>.
If you are editing a video, finished files are only added to the file list so your editor view is not taken over. Sending the same stream twice is blocked.</p>
<div class="tip">If recordings are running when you close ClipSlicer, it asks whether to save what was recorded so far. Updates are not applied while recording.
Several downloads at once need that much more bandwidth and disk space (one 1080p stream is roughly 3–4 GB per hour).</div>

<h2>Stream bookmark mode</h2>
<p><b>File ▸ Stream bookmark mode…</b>. A small always-on-top window appears. While streaming or recording, press the <b>global hotkey</b> (default <kbd>Ctrl+Alt+B</kbd>)
whenever a moment is worth clipping and the time is recorded. It works even when OBS or a game is in front. Choose between <kbd>Ctrl+Alt+B</kbd> / <kbd>Ctrl+Alt+M</kbd> / <kbd>Ctrl+Shift+B</kbd> / <kbd>F9</kbd> / <kbd>F10</kbd>;
if another program already uses the combination you are told. The <b>● Bookmark now</b> button does the same thing.</p>
<p>When the recording is done, open the file in ClipSlicer. If bookmarks were recorded during that time you are <b>asked whether to import them as markers</b>,
and you can do it later with <b>Edit ▸ Import bookmarks…</b>. The file's modified time is taken as the end of the recording to map "bookmark time → position in the video",
so import from the untouched original file (not a re-encoded or copied one) for accurate positions.</p>
<div class="tip">The log lives in a single <code>bookmarks.jsonl</code> file; "Clear log" empties it. Global hotkeys work on Windows only.</div>

<h2>Markers at loud moments (laughter · cheering)</h2>
<p><b>Edit ▸ Markers at loud moments…</b> (<kbd>Ctrl+Shift+L</kbd>). Uses the analysed waveform to find places that are much louder than usual (laughter, shouting, cheering, sound effects) and adds markers there.
The waveform is not re-read, so it finishes instantly.</p>
<table>
 <tr><th>Setting</th><th>Description</th></tr>
 <tr><td>Threshold factor</td><td>How many times the usual (median) level counts as "loud". Default 3x; lower finds more.</td></tr>
 <tr><td>Minimum gap</td><td>Loud moments closer than this count as one. Default 10 s.</td></tr>
 <tr><td>Lead</td><td>Places the marker this far before the loud moment (default 2 s) so the clip starts just before the reaction.</td></tr>
</table>
<p>Up to 50 markers, one per moment (start only). Press <kbd>O</kbd> after a marker to set the clip end, or use the range up to the next marker as the segment. <kbd>Ctrl+Z</kbd> undoes all of them.</p>

<h2>Chat reaction graph · keyword markers</h2>
<p><b>Edit ▸ Chat reaction graph & markers…</b> (<kbd>Ctrl+Shift+C</kbd>). Paste a CHZZK VOD or YouTube live-replay URL and press <b>Fetch chat</b>:
the chat is downloaded and drawn as an <b>orange reaction graph</b> under the thumbnail strip. Peaks are the moments when chat exploded, and the timeline hover popup shows the chat count for that moment.</p>
<ul>
 <li><b>Markers at reaction peaks</b> — picks the busiest chat moments (up to N, default 20). Peaks closer than the minimum gap (default 60 s) count as one.</li>
 <li><b>Keyword reaction markers</b> — counts only chats containing comma-separated words such as <code>lol, insane, clip, legend</code> and puts markers where they peak. Case-insensitive, emoji allowed.</li>
</ul>
<p>The expected number of markers is shown at the bottom; <b>Add markers</b> inserts both kinds combined. The chat is saved as <code>video.clipslicer.chat.json</code>,
so the graph appears immediately the next time and nothing is downloaded again. Videos opened from a URL remember their address and pre-fill the dialog.</p>
<div class="warn">CHZZK works for VODs with public chat replay; YouTube only for live-stream replays that have a chat replay. Comments on regular uploads are not supported.</div>

<h2>Segment notes · merge order</h2>
<p>Double-click the <b>Note</b> column in the segment list to write reminders like "funny part here" or "check after the ad". Notes do not affect file names or export and are stored in the project file.
Besides double-clicking, <kbd>N</kbd> (segment under the cursor) and <kbd>F2</kbd> (selected row) start editing the name directly.</p>
<p>With <b>Merge into one</b> on, the <b>Order</b> column appears. Use ▲ ▼ to change the join order (<kbd>Ctrl+Shift+↑</kbd> <kbd>Ctrl+Shift+↓</kbd>). Only enabled segments are numbered; untouched, the order is chronological.</p>

<h2>Output effects: loudness · caption · subtitles · Shorts layout</h2>
<table>
 <tr><th>Option</th><th>Description</th></tr>
 <tr><td>Normalize loudness</td><td>Evens out the volume with loudnorm (-14 LUFS, YouTube's target). Only the audio is re-encoded to AAC; the video is copied, so it stays fast. When merging it is applied once at the end.</td></tr>
 <tr><td>Caption</td><td>Burns the text into the bottom centre of the video (white text, black outline, translucent box). The same text goes into every clip, so it suits a channel name or "full video on the channel".</td></tr>
 <tr><td>Subtitles</td><td>Pick a <code>.srt</code> / <code>.ass</code> / <code>.vtt</code> file timed to the source video; the times are shifted to each cut segment and burned in.</td></tr>
 <tr><td>Vertical layout</td><td>For "Vertical 9:16 Shorts" output choose <b>Crop</b> (keep part of the frame, set with Crop position…) or <b>Blur background</b> (the whole 16:9 frame in the middle, top and bottom filled with a blurred zoomed copy).</td></tr>
</table>
<div class="warn">With a caption, subtitles or a watermark the video is <b>re-encoded</b> even in "Fast" mode (output is mp4). Normalize loudness alone keeps the video copy.</div>

<h2>Watermark · intro / outro</h2>
<p><b>Settings ▸ Watermark / intro & outro…</b>. Overlay a PNG logo in one of the four corners with the opacity you want, and prepend/append intro and outro videos.
The watermark applies to every re-encoded output; the intro/outro only to outputs that are re-encoded anyway (Precise · vertical · caption · subtitles · watermark), never to files copied with Fast or Smart.
Intro and outro are converted to the main clip's resolution and frame rate, and silent videos get a silent track. The settings are shared by all videos; leave a field empty to skip it.</p>

<h2>YouTube presets · scheduled publish · upload history</h2>
<ul>
 <li><b>Presets</b> — at the top of the upload window. "Manage…" bundles a name, title template, description template, tags, category and #Shorts; picking one fills every item at once.
     The title template accepts <code>{title}</code> <code>{source}</code> <code>{start}</code> <code>{end}</code> <code>{n}</code>; empty keeps the file name. The last preset is remembered.</li>
 <li><b>Scheduled publish</b> — enable "Scheduled publish" in the common settings and pick a time (your computer's local time): the video is uploaded as private and YouTube makes it public at that time. Past times are rejected.
     Unverified projects may ignore the schedule and leave the video private.</li>
 <li><b>Upload history</b> — <b>File ▸ Upload history…</b>. Date, title, file and link of every upload, with open/copy link and a button for the Studio edit page.
     Stored in <code>youtube_uploads.jsonl</code>.</li>
</ul>

<h2>Send to Discord</h2>
<p>Enter a webhook URL in <b>Settings ▸ Discord webhook…</b> (in Discord: Channel settings ▸ Integrations ▸ Webhooks ▸ New webhook ▸ Copy URL) and enable <b>Send to Discord</b> in the export panel:
when the export finishes the cut files are posted to that channel. The message template accepts <code>{title}</code> (file name) and <code>{source}</code> (source name); "Send a test message" checks the connection.</p>
<p>Choose the file size limit (10 / 25 / 50 / 100 MB) to match your server's boost level. Files above the limit are skipped and noted in the log. Shorts-length clips usually fit.</p>

<h2>Start screen · notifications · getting started</h2>
<ul>
 <li><b>Start screen</b> — with no video open you get Open file · Open from URL · Sample video buttons and <b>Continue recent work</b> (the last 5 projects with marker and segment counts).</li>
 <li><b>Sample video</b> — generates a 30-second practice video with ffmpeg (scene changes and a silent gap included). Good for trying the auto-marker features.</li>
 <li><b>Getting started</b> — a three-step guide on the first launch. Untick "Don't show again" to see it next time, or open <b>Help ▸ Getting started…</b> any time.</li>
 <li><b>Tray notifications</b> — when a long export, download or YouTube upload finishes while ClipSlicer is in the background or minimised, a taskbar notification tells you. In the foreground only the status bar message appears.</li>
</ul>
"""),

("Settings · files", """
<h2>Settings menu</h2>
<table>
 <tr><th>Item</th><th>Description</th></tr>
 <tr><td>Snap markers to keyframes</td><td>Markers stick to a keyframe within 0.5 s. Makes Fast mode exact.</td></tr>
 <tr><td>Use GPU encoding</td><td>Uses the detected hardware encoder for re-encoding. The menu shows which one was found.</td></tr>
 <tr><td>Auto-save project</td><td>Saves markers and segments to <code>.clipslicer.json</code> next to the video. Off = work is lost when you close.</td></tr>
 <tr><td>Cache analysis results</td><td>Stores thumbnails, waveform and keyframes in <code>%LOCALAPPDATA%\\ClipSlicer\\cache</code> (not in the video folder) so the video opens instantly next time. Old entries are pruned above 2 GB.</td></tr>
 <tr><td>Check for updates at startup</td><td>Queries GitHub releases (at most hourly). A green button appears when a new version exists. Nothing else is sent.</td></tr>
 <tr><td>Compatibility mode</td><td>Renders without GPU acceleration. For black video areas. Restart required.</td></tr>
 <tr><td>Connect YouTube account…</td><td>OAuth client registration and sign-in. See the "YouTube upload" tab.</td></tr>
 <tr><td>YouTube description template…</td><td>Pre-filled description text.</td></tr>
 <tr><td>Discord webhook…</td><td>Webhook URL, size limit and message template for posting exported files to a Discord channel. See "For streamers".</td></tr>
 <tr><td>Filename pattern…</td><td>Output file name pattern.</td></tr>
 <tr><td>Watermark / intro & outro…</td><td>PNG logo (position, opacity) for re-encoded output and videos to prepend/append.</td></tr>
 <tr><td>Language</td><td>Korean / English / follow the system. Takes effect after a restart.</td></tr>
 <tr><td>View ▸ Right panel</td><td>Collapses or expands the segment list / export panel (<kbd>Ctrl+Shift+R</kbd>). The state is remembered.</td></tr>
 <tr><td>Help ▸ Getting started…</td><td>Shows the first-launch guide again.</td></tr>
</table>

<h2>Export panel options</h2>
<p>Besides mode, output, merge and open-folder, the <b>Upload to YouTube when done</b>, <b>Send to Discord</b>, <b>Normalize loudness</b> and vertical <b>layout</b> (crop / blur background) choices are remembered across runs.
The <b>Caption</b> and <b>Subtitles</b> fields are per export and not remembered.</p>

<h2>Project file (.clipslicer.json)</h2>
<p>Saved next to the video as <code>video.mp4.clipslicer.json</code>: markers, enabled segments, custom names, notes, merge order, clip ranges, crop position, source URL and the last playback position.
Move it together with the video to keep your work. It is plain text.</p>
<p>Saves are written to a temporary file and swapped in, so a crash never leaves a broken file; if the project file is damaged it is restored from the previous save in <code>%LOCALAPPDATA%\\ClipSlicer\\backups</code>. Old <code>.bak</code> files next to videos are cleaned up on the next save.
Chat is stored separately as <code>video.mp4.clipslicer.chat.json</code> and the analysis cache in <code>%LOCALAPPDATA%\\ClipSlicer\\cache</code>. Right-click a recent item on the start screen ▸ <b>Delete project files and analysis cache</b> to clear one video's work (the video is kept).</p>

<h2>Data in the program folder</h2>
<table>
 <tr><th>File</th><th>Content</th></tr>
 <tr><td><code>settings.ini</code></td><td>All settings (window size, export options, presets, webhook URL …).</td></tr>
 <tr><td><code>bookmarks.jsonl</code></td><td>Stream bookmark log.</td></tr>
 <tr><td><code>youtube_uploads.jsonl</code></td><td>YouTube upload history.</td></tr>
 <tr><td><code>youtube_token.bin</code></td><td>Encrypted YouTube sign-in.</td></tr>
 <tr><td><code>samples\\\\sample.mp4</code></td><td>The practice video made by "Try a sample video" (recreated if deleted).</td></tr>
 <tr><td><code>logs\\\\clipslicer.log</code></td><td>Error log.</td></tr>
</table>
<p>If the program folder is not writable, <code>%LOCALAPPDATA%\\ClipSlicer</code> is used instead.</p>

<h2>Updates</h2>
<p>When a new version exists a <b>⬆ Update</b> button appears at the bottom right. It shows the release notes and offers <b>Update now / Later / Skip this version</b>.
Update now downloads the zip, verifies its checksum, closes the app, replaces the files and restarts. <code>settings.ini</code>, logs and project files are kept and the previous version stays in <code>_backup</code>.
In read-only locations only the download page is offered.</p>
<p><b>Lite updates</b>: releases that only change the code download a lite zip of about 20 MB and keep the bundled ffmpeg and libmpv (the update dialog says "lite").
Releases that change ffmpeg or libmpv download the full zip. The choice is automatic.</p>

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

<h3>I chose "Fast" but the file was re-encoded</h3>
<p>A caption, subtitles or a watermark has to be drawn into the picture, so those force a re-encode (the log says so). Clear the caption and subtitle fields and remove the watermark in Settings to get a pure copy. Normalize loudness alone does not re-encode the video.</p>

<h3>"No bookmarks" when importing</h3>
<p>The file's modified time is taken as the end of the recording. If the file was copied or converted afterwards the times no longer line up; import from the original file written by the recording software. The bookmark window lists the recorded times.</p>

<h3>The bookmark hotkey cannot be registered</h3>
<p>Another program uses the same global hotkey. Pick a different combination (F9, F10 …) in the bookmark window. Global hotkeys work on Windows only.</p>

<h3>Chat cannot be fetched</h3>
<p>CHZZK needs a VOD with public chat replay; YouTube only supports live-stream replays. If the URL is right, try again in a moment (a missing server response is retried three times automatically).</p>

<h3>Nothing arrives in Discord</h3>
<p>Check the URL with "Send a test message" in Settings ▸ Discord webhook…. Files above the server limit are skipped; set the limit to match your server's boost level.</p>

<h2>About</h2>
<p>ClipSlicer """ + __version__ + """ — Python · PySide6 · libmpv · ffmpeg · yt-dlp.<br>
Source: <a href="https://github.com/vtubeadmirer/clipslicer">github.com/vtubeadmirer/clipslicer</a></p>
"""),
]
