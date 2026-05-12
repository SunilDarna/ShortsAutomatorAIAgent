# 🚀 ShortsAutomatorAIAgent

An autonomous AI workstation engineered to scale YouTube Shorts channels to millions of views through viral segment discovery, high-retention video editing, and automated multi-layer text overlays.

## 🛠 Core Capabilities
- **Viral Discovery**: Leverages **Local Residential Acquisition** to scan high-velocity channels for trending high-intent segments.
- **AI Brain (Gemini)**: Engineers scroll-stopping hooks and matches segments with high-yield affiliate offers.
- **Cinematic Rendering**: Applies vertical 9:16 formatting, blurred-stack background, and mobile-optimized word-wrapping.
- **Growth Overlays**: Injects permanent high-contrast "SUBSCRIBE" triggers and synchronized "Smart Captions".
- **Safe-Sync**: Automated uploads to YouTube as **Private** videos for quality control review.

## 🔑 Input Requirements (`local_secrets.json`)
The agent expects the following keys to be present in `local_secrets.json`:
- `llm_api_key`: Google Gemini API key for content strategy.
- `youtube_api_key`: YouTube Data API v3 key for video discovery.
- `youtube_client_id/secret/refresh_token`: OAuth2 credentials for automated publishing.

## 🕹 Usage Actions
Run the pipeline using:
```bash
python3 local_production_pipeline.py [ACTION]
```
- **`produce`**: Discover, download, and edit a video. Stages result in `output/pending/`.
- **`sync`**: Checks `output/pending/` and uploads the latest video to YouTube as Private.
- **`run`**: Full end-to-end execution (Produce + Sync).

## ⏰ Automation
The agent is designed to run via Cron. Recommended schedule:
- **Morning (9:30 AM IST)**: Commuter peak.
- **Lunch (1:30 PM IST)**: High-intent window.
- **Evening (8:00 PM IST)**: Relaxed browsing.

---
*Autonomous Workforce by sunildarna*
