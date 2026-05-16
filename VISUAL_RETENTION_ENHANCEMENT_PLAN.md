# Visual Retention Enhancement Plan

Goal: upgrade the current visual layer from static overlays into a smart retention system that improves scroll-stop power, watch time, replays, saves, comments, and subscriber conversion.

This plan covers three areas:

1. Thumbnail / first-frame system
2. Dynamic subscribe / follow CTA system
3. Premium animated captions system

## 1. Current Visual State

The current renderer uses FFmpeg `drawtext` for:

- A 0.1s thumbnail injection frame.
- A hook overlay for the first 3 seconds.
- A permanent `SUBSCRIBE` label.
- Transcript captions, when source captions are not detected.
- Bridge and affiliate CTA overlays near the end.

This works mechanically, but it has limitations:

- The thumbnail frame is not selected from the strongest visual moment.
- Text style is mostly fixed across all niches.
- Permanent `SUBSCRIBE` can feel spammy and can cover useful source content.
- Captions are chunk-based, static, and can become too long.
- Captions do not yet use word-level timing, keyword emphasis, or animation.
- The system does not store performance by visual style, CTA style, or caption style.

## 2. Target Outcome

The upgraded visual system should:

- Choose a high-impact first frame or thumbnail from the clip.
- Generate multiple thumbnail styles and pick the strongest candidate.
- Replace permanent `SUBSCRIBE` with late, contextual CTAs.
- Render captions as short, rhythmic, animated beats.
- Highlight keywords and current spoken words.
- Avoid covering faces, source text, screenshots, or YouTube UI zones.
- Track which visual styles produce the best retention and subscriber gain.

## 3. Thumbnail / First-Frame System

### 3.1 Candidate Frame Selection

Sample frames from the selected clip and score each one for:

- Face visibility and emotional expression.
- Presence of useful proof objects: charts, tweet/post, product UI, numbers, graphs.
- Contrast and brightness.
- Amount of empty space available for hook text.
- Motion clarity: avoid blurred transitional frames.
- Visual novelty compared with previous clips.

Output:

- `best_frame_timestamp`
- `thumbnail_frame_path`
- `thumbnail_visual_score`
- `safe_text_box`

### 3.2 Thumbnail Variants

Generate three variants per clip:

- `shock`: bold claim, high contrast, urgent color.
- `curiosity`: mystery/open loop phrasing.
- `proof`: number/chart/source-driven authority.

Examples:

- Finance: `BUFFETT METRIC BROKE`
- AI: `AI JUST CHANGED THIS`
- Business: `THIS STRATEGY FLIPPED`
- Mystery: `THE COVER-UP ENDED`

Rules:

- 3-6 words max.
- Do not repeat the full hook if it is too long.
- Large readable type.
- No cluttered text blocks.
- Avoid always using the same red-box style.

### 3.3 Thumbnail / First-Frame Scoring

Score variants for:

- Readability on mobile.
- Contrast ratio.
- Text fit.
- Face or proof-object visibility.
- Emotional / curiosity strength.
- Niche style match.

Store:

- `thumbnail_style`
- `thumbnail_score`
- `thumbnail_text`
- `thumbnail_frame_timestamp`

## 4. Dynamic Subscribe / Follow CTA System

### 4.1 Replace Permanent Subscribe Bug

Remove the always-on `SUBSCRIBE` label as the default behavior.

Instead, show CTA only after value delivery:

- Usually from 70-85% of clip duration.
- Never during the strongest spoken reveal.
- Duration: 1.5-2.5 seconds.
- Optional second CTA at the final 1.5 seconds only when it does not block source content.

### 4.2 Context-Aware CTA Copy

CTA should match topic and viewer intent:

- Finance: `Follow for market breakdowns`
- AI: `Follow for AI tools`
- Business: `Follow for growth systems`
- Marketing: `Save this strategy`
- Mystery/shock: `Follow before this disappears`
- Tutorial: `Save this checklist`

CTA types:

- `follow`
- `save`
- `comment`
- `part_2`
- `tool_link`

The system should not always ask for subscribe. For subscriber growth, a reason-based follow CTA usually feels better than a command.

### 4.3 CTA Timing

CTA timing should use transcript and hook structure:

- Do not appear before the reveal.
- Prefer after the main value point.
- Avoid overlapping important sentence peaks.
- If clip has strong final loop, keep CTA short and non-disruptive.

### 4.4 CTA Motion Styles

Supported effects:

- Slide-up.
- Pop-in.
- Pulse.
- Stamp.
- Minimal lower-third.

Style by niche:

- Finance: clean lower-third, white/yellow.
- AI/business: neon accent or slick pop.
- Mystery: red/white stamped reveal.
- Tutorial: save/checklist badge.

## 5. Premium Caption System

### 5.1 Move To ASS Subtitle Rendering

Replace large chains of FFmpeg `drawtext` captions with ASS subtitles.

Benefits:

- Better text wrapping.
- Stroke and shadow.
- Per-word highlight.
- Karaoke timing.
- Style definitions.
- Animation tags.
- Safer positioning.
- Cleaner FFmpeg commands.

### 5.2 Word-Level Timing

Use one of these sources:

- Whisper / WhisperX word timestamps.
- Forced alignment from source transcript.
- Fallback to phrase-level transcript timing if word-level timing is unavailable.

Caption units should be:

- 3-7 words per beat.
- 1-2 lines max.
- 1.0-2.2 seconds per caption block.
- Split on punctuation, pauses, and power words.

### 5.3 Dynamic Fit And Wrapping

Before rendering:

- Estimate text width.
- Rewrap to fit inside mobile safe zones.
- Dynamically reduce font size for long words.
- Reject caption blocks that still overflow.
- Avoid source text/post areas when detected.

### 5.4 Keyword Highlighting

Automatically highlight:

- Numbers: `230%`, `$1M`, `10x`
- Contrarian terms: `wrong`, `broken`, `nobody`, `stop`
- Value terms: `system`, `strategy`, `rule`
- Pain terms: `expensive`, `slow`, `mistake`
- Niche terms: `AI`, `market`, `sales`, `automation`

Highlight styles:

- Current spoken word: yellow/cyan.
- Power words: bigger or colored.
- Numbers: bold accent.
- Final reveal word: pop or stamp.

### 5.5 Caption Style Packs

Create reusable style packs:

- `clean_finance`
  - White text, yellow keyword, black stroke.
  - Minimal movement.

- `ai_neon`
  - White text, cyan/yellow keyword, glow shadow.
  - Subtle pop-in.

- `business_bold`
  - Bold white/yellow, strong black stroke.
  - Fast scale-in for power words.

- `shock_red`
  - White text, red keyword stamps.
  - Use sparingly for high-conflict clips.

- `tutorial_save`
  - Clean lower-third with checklist/save icon style.
  - Best for practical how-to clips.

### 5.6 Caption Effects

Allowed effects:

- Pop-in for keyword.
- Current-word color highlight.
- Subtle bounce on numbers.
- Slide-up for new phrase.
- Fade-out between beats.
- Stamp effect for one-word impact moments.

Avoid:

- Over-animated captions every second.
- Too many colors.
- Covering source screenshots or charts.
- Emojis unless they genuinely improve meaning.

## 6. Smart Placement

The visual engine should choose the safest zone:

- Top zone for clips with lower screenshots/captions.
- Lower-middle for face/talking-head clips.
- Side/upper layout when charts or posts dominate center.
- No captions over source text unless unavoidable.

Inputs:

- Face detection.
- Source text detection.
- Burned-in caption detection.
- YouTube UI safe zones.
- Hook and CTA positions.

Output:

- `caption_zone`
- `hook_zone`
- `cta_zone`
- `avoid_zones`

## 7. Performance Learning

Add fields to metadata and DB:

- `thumbnail_style`
- `thumbnail_score`
- `caption_style`
- `caption_effects`
- `cta_type`
- `cta_text`
- `cta_start`
- `visual_density_score`

Use analytics to compare:

- Views per thumbnail style.
- Average view percentage by caption style.
- Subscribers per 1,000 views by CTA type.
- Saves/comments by CTA copy.
- Retention impact of permanent subscribe vs late CTA.

## 8. Implementation Phases

### Phase 1: Remove Static Subscribe Default

- Make permanent subscribe optional.
- Add dynamic CTA planner.
- Render CTA near 70-85% of clip.
- Store CTA type and timing in metadata.

### Phase 2: Caption Style Engine

- Add caption style packs.
- Generate ASS subtitles from transcript chunks first.
- Add dynamic wrapping and font-size guard.
- Add keyword highlighting.

### Phase 3: Word-Level Captions

- Add Whisper or WhisperX alignment.
- Generate per-word highlights.
- Split captions into short beats.

### Phase 4: Thumbnail / First-Frame Builder

- Sample frames.
- Score candidate frames.
- Generate 3 thumbnail variants.
- Use best first frame overlay in render.
- Export thumbnail image.

### Phase 5: Visual Learning Loop

- Store visual style metadata.
- Add analytics grouping by thumbnail/caption/CTA style.
- Use top-performing styles to bias future renders.

## 9. Recommended First Build

For the next implementation round, build these first:

1. Replace permanent `SUBSCRIBE` with dynamic late CTA.
2. Add caption style packs with ASS rendering.
3. Add keyword highlighting and smarter wrapping.
4. Add first-frame text shortening and safe placement.
5. Store visual style metadata for future learning.

This gives the biggest visible quality lift without blocking on full word-level transcription.
