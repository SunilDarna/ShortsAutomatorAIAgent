# 🚀 ShortsAutomatorAIAgent: The Autonomous Viral Content Factory

ShortsAutomatorAIAgent is a high-performance, self-sustaining AI engine designed to build and scale high-authority YouTube Shorts channels. It automates the entire content lifecycle—from deep media excavation and viral hook engineering to mobile-optimized cinematic rendering and intelligent global scheduling.

---

## 🧠 Core Architecture & Capabilities

### 1. Deep-Sourcing & Self-Healing Pipeline
The agent operates on an infinite sourcing loop, ensuring the production line never stops:
- **Deep Excavation**: Probes the top 5 most recent videos for every target channel to maximize content yield.
- **Autonomous Discovery**: When the source pool is exhausted, the LLM discovery agent identifies new high-authority channels in your niche and injects them into the `channels.json` database.
- **Context-Aware Extraction**: Maintains a persistent SQLite database (`pipeline.db`) of every segment ever clipped. The AI "remembers" used timestamps and actively explores untouched parts of long-form media to find secondary viral moments.

### 2. Viral Engineering (Gemini AI Brain)
Every clip is engineered for maximum retention and algorithm velocity:
- **Scroll-Stopping Hooks**: Generates high-impact text overlays using psychology-driven hook types (Counter-Intuitive, Curiosity Gap, etc.).
- **Affiliate Matching**: Automatically matches video content with high-ticket affiliate offers from `affiliate_offers.json` to maximize RPM.
- **SEO 2.0**: Generates optimized titles, descriptions, and synchronized SRT captions to enable YouTube's deep-search indexing.

### 3. Cinematic Video Processor
Built for high-retention mobile viewing:
- **Subject-Aware Rendering**: Uses computer vision to center subjects and applies a premium blurred-stack pillarbox for 9:16 vertical formatting.
- **Mobile-Responsive Typography**: Employs a hardened text engine that enforces safe-zones and multi-layer word wrapping to prevent clipping on small screens.
- **Performance Optimized**: Leverages hardware acceleration (VideoToolbox/NVENC) for ultra-fast encoding.

### 4. Intelligent Global Scheduler
The agent autonomously manages your channel's growth strategy:
- **Queue Management**: Checks your current YouTube schedule and maintains a strict 6-hour buffer between uploads.
- **Region-Specific Timing**: Uses LLM-driven recommendations to target high-traffic windows for specific geometries (e.g., IST/India) while converting to UTC for global publishing.
- **Hands-Off Execution**: Handles OAuth2 authentication, video uploading, and public scheduling without human intervention.

---

## 🛠 Setup & Requirements

### 1. Environment Configuration
Create a `local_secrets.json` in the root directory:
```json
{
  "llm_api_key": "YOUR_GEMINI_API_KEY",
  "youtube_api_key": "YOUR_YOUTUBE_DATA_API_V3_KEY",
  "youtube_client_id": "...",
  "youtube_client_secret": "...",
  "youtube_refresh_token": "..."
}
```

### 2. Source Management
Configure your initial authority tier in `channels.json`:
```json
{
  "channels": ["CHANNEL_ID_1", "CHANNEL_ID_2"]
}
```

### 3. Dependencies
- **FFmpeg**: Required with FreeType support for text overlays.
- **Python 3.10+**: Recommended for optimal `yt-dlp` performance.
- **Hardware**: Compatible with macOS (M1/M2/M3) and NVIDIA GPUs for accelerated rendering.

---

## 🚀 Usage

### Full Production Run
Execute the end-to-end pipeline (Discovery → Extraction → Rendering → Upload):
```bash
python3 local_production_pipeline.py run
```

### Targeted Mode
Produce a specific number of clips or target a specific niche:
```bash
python3 local_production_pipeline.py produce --count 5
```

---

## 🛡 Security & Best Practices
- **Private Staging**: By default, the system can be configured to upload as "Private" for final manual QC.
- **API Quotas**: Implements intelligent sleep cycles and batch processing to respect YouTube Data API limits.
- **Persistence**: All processed media is tracked in `pipeline.db` to prevent duplicate content flags.
