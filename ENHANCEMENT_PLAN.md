# ShortsAutomatorAIAgent Enhancement Plan

Goal: turn the current autonomous Shorts pipeline into a practical experimentation engine capable of learning from real performance, finding multiple strong clips from the same source video, producing cleaner mobile edits, and scheduling by audience evidence rather than generic time guesses.

The target of 3 million views and 50K subscribers in 1 month requires both production volume and disciplined feedback. The system should not only create clips; it should rank opportunities, reject weak renders, learn from published performance, and double down on formats that convert viewers into subscribers.

## 1. Current State

The existing pipeline already supports:

- Source-channel iteration through `channels.json`.
- Transcript retrieval through `youtube_transcript_api`.
- Two-pass LLM extraction for segment selection and hook generation.
- SQLite tracking for used source ranges.
- FFmpeg rendering into 9:16 Shorts.
- SRT generation and YouTube upload.
- Basic schedule spacing from LLM-recommended time slots.

Critical limitations:

- Clip selection is mostly transcript/LLM based, with little quantitative evidence.
- Performance learning is not active because `Performance_Log` is empty unless populated manually.
- Scheduling does not use channel-specific analytics or prior slot performance.
- Caption rendering does not detect burned-in captions in the source video.
- Metadata can contradict itself when the LLM suggests one affiliate and local matching chooses another.
- QA is manual; the pipeline does not reject black frames, unreadable text, missing audio, or likely caption collisions.

## 2. Target Architecture

The upgraded pipeline should run this sequence:

1. Source intelligence
   - Pull candidate videos from known channels.
   - Gather source metadata: views, likes, comments, duration, channel, age, and velocity.
   - Favor videos outperforming their channel baseline or gaining attention quickly.

2. Viral candidate scoring
   - Build transcript windows across the full video.
   - Score each window using transcript signals, source velocity, novelty, narrative completeness, and reuse distance.
   - Pass ranked candidates to the LLM instead of giving it only a raw transcript.

3. LLM clip architecture
   - Generate multiple possible clip specs.
   - Validate hook clarity, loop quality, and subscriber intent.
   - Enforce exact duration, semantic uniqueness, and affiliate consistency.

4. Render intelligence
   - Detect whether the source already has burned-in captions.
   - Choose overlay layout based on free visual zones.
   - Generate captions through a safer subtitle path.
   - Run automated render QA before staging/upload.

5. Metadata and monetization
   - Match affiliate offer using full context, not hook text alone.
   - Keep description, pinned comment, CTA overlay, and affiliate fields consistent.
   - Add topical tags but avoid misleading metadata.

6. Smart scheduling
   - Normalize LLM schedules into a stable schema.
   - Query existing scheduled uploads.
   - Use prior slot performance by geography, topic, and hour.
   - Allocate slots using an explore/exploit policy.

7. Analytics feedback
   - Pull YouTube Analytics metrics at 1h, 24h, 48h, and 7d.
   - Store views, engaged views, APV, average view duration, subscribers gained, shares, likes, comments, geography, and publish hour.
   - Update hook, topic, source, caption style, and schedule weights.

## 3. Implementation Phases

### Phase 1: Data Model And Learning Loop

Add durable tables:

- `Source_Intelligence`: stores source video stats, velocity, duration, channel, and scoring context.
- `Candidate_Segments`: stores pre-LLM candidate windows and feature scores.
- `Render_QA`: stores post-render checks and whether a clip is safe to upload.
- `Schedule_Performance`: stores publish slot outcomes by geography, topic, hour, and clip.
- Extend `Shorts_Clips` with candidate score, source score, topic, geography, schedule slot, render QA status, and failure reason.

### Phase 2: Candidate Scoring

Add a scoring module that:

- Builds overlapping transcript windows.
- Scores hooks with measurable features:
  - Numbers/statistics
  - Contradiction or surprise
  - Named entities
  - Direct second-person value
  - Pain point intensity
  - Clean independent narrative
  - Question or reveal phrasing
  - Comment/source velocity boost
- Penalizes windows too close to prior clips.
- Produces top candidates with feature explanations for the LLM.

### Phase 3: Multiple Clips From Same Video

For every source video:

- Store all candidate windows.
- Cluster by concept/topic.
- Avoid semantic duplicate hooks.
- Require distance from already used clips.
- Allow a strong source video to produce 3-6 Shorts only when each clip has a different angle.

### Phase 4: Caption And Overlay Intelligence

Add a caption intelligence layer:

- Sample frames from the selected segment.
- Detect text-like regions, especially in bottom and center safe zones.
- If the source already has captions, suppress generated captions or reposition overlay text.
- Use safe zones:
  - Hook: upper third unless face/text conflict exists.
  - Captions: mid-lower free zone.
  - CTA: final seconds, away from YouTube controls.
- Add QA checks for unreadable text, likely collisions, blank frames, and missing audio.

### Phase 5: Scheduling Intelligence

Replace generic slot selection with:

- Schedule recommendation normalization (`recommended_slots`, `utc_offset`, geography).
- Existing queue inspection.
- Historical slot scoring from `Schedule_Performance`.
- Upload density rules by channel size.
- Geography-aware slot packs:
  - India: 08:00-09:30, 13:00-14:30, 20:00-22:30 IST.
  - US: 07:00-09:00, 12:00-14:00, 18:00-22:00 local.
  - Global/business: stagger India evening and US morning/evening.

### Phase 6: Analytics Ingestion

Add a collector that can run daily:

- Query YouTube Analytics API for published videos.
- Store metrics in `Performance_Log`.
- Store slot performance in `Schedule_Performance`.
- Recompute winning hook types and publishing windows.

Important metrics:

- `views`
- `engagedViews`
- `averageViewDuration`
- `averageViewPercentage`
- `estimatedMinutesWatched`
- `subscribersGained`
- `likes`
- `comments`
- `shares`

### Phase 7: Quality Gates

Before upload:

- Reject output if duration is outside Shorts target.
- Reject if video dimensions are not 1080x1920.
- Warn/reject if audio stream is missing.
- Warn if burned-in captions and generated captions both appear in same zone.
- Warn if hook text exceeds safe line count.
- Store QA result in DB and metadata JSON.

## 4. Growth Operating System

Recommended production cadence:

- Produce 4-8 Shorts/day once QA is reliable.
- Start with 3 content pillars maximum.
- Run hook-style tests in balanced groups:
  - Counter-intuitive
  - Immediate reward
  - Shock statistic
  - Contrarian reframe
  - Question hook
- Review every 48 hours.
- Kill formats below 60-70% average view percentage.
- Scale topics and editing styles that produce subscribers, not just views.

Subscriber-focused metrics:

- Subscribers per 1,000 views.
- Average view percentage.
- Replay rate proxy: APV above 100%.
- Shares per 1,000 views.
- Comments per 1,000 views.

## 5. Practical Delivery Checklist

- [x] Document the end-to-end architecture.
- [x] Extend database schema safely.
- [x] Add source and segment scoring.
- [x] Feed ranked candidates into LLM extraction.
- [x] Normalize scheduling recommendations.
- [x] Add schedule performance table.
- [x] Add burned-in caption detection.
- [x] Add render QA.
- [x] Fix affiliate consistency.
- [x] Add analytics ingestion scaffold.
- [x] Add CLI action for analytics collection.

## 6. Expected Outcome

After implementation, the agent should move from producing isolated Shorts to running an iterative growth system:

- Better source videos enter the pipeline.
- Better moments are chosen from those videos.
- More than one high-quality clip can be mined from a strong source.
- Videos look cleaner and less spammy.
- Schedule choices become evidence-based.
- The system learns which hooks, source channels, topics, editing styles, and time slots actually generate views and subscribers.
