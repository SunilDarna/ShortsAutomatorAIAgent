import subprocess
import yt_dlp
import os

def download_video_section(url, start_time, end_time, output_path, unused_key=None):
    """Download a specific section of a YouTube video using local residential connection."""
    print(f"Local Acquisition: Downloading {url}...")
    
    ydl_opts = {
        'format': 'best',
        'outtmpl': output_path,
        'force_keyframes_at_cuts': True,
        'nocheckcertificate': True,
        'socket_timeout': 120,
        'retries': 15,
        'extractor_args': {'youtube': {'player_client': ['android', 'ios']}},
    }
    
    # Try a few times because connections can be flaky
    for attempt in range(3):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            print(f"Downloaded full video to {output_path}")
            return
        except Exception as e:
            print(f"Download attempt {attempt + 1} failed: {e}")
            if attempt == 2:
                raise e

def wrap_text(text, max_width=25):
    """Manually wrap text to fit in vertical video."""
    words = text.split()
    lines = []
    current_line = []
    
    for word in words:
        if len(" ".join(current_line + [word])) <= max_width:
            current_line.append(word)
        else:
            lines.append(" ".join(current_line))
            current_line = [word]
    lines.append(" ".join(current_line))
    return "\\\n".join(lines)

def parse_time(time_str):
    """ Converts MM:SS or HH:MM:SS to seconds """
    parts = list(map(int, time_str.split(':')))
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    elif len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return int(time_str)

def process_for_shorts(input_path, output_path, start_time, end_time, bridge_text, hook_text="", transcript_raw=None):
    print(f"Cutting from {start_time} to {end_time} and formatting for Shorts...")
    
    seg_start = parse_time(start_time)
    seg_end = parse_time(end_time)
    duration = seg_end - seg_start
    
    # Use a verified system font on macOS
    font_path = "/System/Library/Fonts/Supplemental/Verdana Bold.ttf"
    
    # Use the portable FFmpeg binary for the capability check
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    ffmpeg_bin = os.path.join(project_root, "node_modules/@ffmpeg-installer/darwin-arm64/ffmpeg")
    if not os.path.exists(ffmpeg_bin):
        ffmpeg_bin = 'ffmpeg'
        
    has_drawtext = False
    try:
        check_filters = subprocess.run([ffmpeg_bin, '-filters'], capture_output=True, text=True)
        if 'drawtext' in check_filters.stdout:
            has_drawtext = True
    except:
        pass
        
    if has_drawtext:
        # Escape single quotes and colons for ffmpeg drawtext filter
        safe_bridge = wrap_text(bridge_text.replace("'", "'\\\\''").replace(":", "\\:"), 30)
        safe_hook = wrap_text(hook_text.replace("'", "'\\\\''").replace(":", "\\:"), 20)
        
        # 1. Permanent Subscribe (Elevated to 30-40% Safety Zone)
        # 1920 - 600 = 1320 (Just above the bottom 30% line)
        sub_filter = f"drawtext=text='SUBSCRIBE':fontfile='{font_path}':fontcolor=white:fontsize=42:box=1:boxcolor=red@0.9:boxborderw=10:x=(w-text_w)/2:y=h-th-600"
        
        # 2. Hook & Bridge
        bridge_filter = f"drawtext=text='{safe_bridge}':fontfile='{font_path}':fontcolor=white:fontsize=48:box=1:boxcolor=black@0.5:boxborderw=10:x=(w-text_w)/2:y=h-th-150:enable='between(t,{duration-4},{duration})'"
        hook_filter = f"drawtext=text='{safe_hook}':fontfile='{font_path}':fontcolor=yellow:fontsize=64:box=1:boxcolor=black@0.7:boxborderw=15:x=(w-text_w)/2:y=200:enable='between(t,0,3)'"
        
        # 3. OPTION 1+2: THUMBNAIL INJECTION (The 'Invisible' Custom Thumbnail)
        # We create a 0.1s frame at the very start with HUGE text and higher saturation.
        # Fixed: Narrower wrap (12 chars) to prevent cropping on mobile screens.
        thumb_text = wrap_text(safe_hook.upper(), 12) 
        thumb_filter = f"drawtext=text='{thumb_text}':fontfile='{font_path}':fontcolor=white:fontsize=100:line_spacing=20:box=1:boxcolor=red@0.9:boxborderw=30:x=(w-text_w)/2:y=(h-text_h)/2:enable='between(t,0,0.1)',eq=saturation=1.5:brightness=0.1:enable='between(t,0,0.1)'"
        
        # 4. Smart Captions (Placed ABOVE Subscribe, within Bottom 40% zone)
        caption_filters = []
        last_cap_end = 0
        if transcript_raw:
            for entry in transcript_raw:
                # Robustly handle both dict and object types
                if isinstance(entry, dict):
                    e_start = entry.get('start', 0)
                    e_dur = entry.get('duration', 0)
                    e_text = entry.get('text', '')
                else:
                    e_start = getattr(entry, 'start', 0)
                    e_dur = getattr(entry, 'duration', 0)
                    e_text = getattr(entry, 'text', '')
                
                e_end = e_start + e_dur
                
                # Filter for entries within our segment
                if e_start >= seg_start and e_end <= seg_end:
                    rel_start = round(e_start - seg_start, 2)
                    rel_end = round(e_end - seg_start, 2)
                    
                    # Ensure no overlap with previous caption
                    if rel_start < last_cap_end:
                        rel_start = last_cap_end + 0.05
                    
                    # Cap duration to prevent text "sticking"
                    if (rel_end - rel_start) > 2.5:
                        rel_end = rel_start + 2.5
                        
                    # Update tracker
                    last_cap_end = rel_end
                    
                    # Clean text & Wrap
                    txt = wrap_text(e_text.replace("'", "").replace(":", "").strip().upper(), 25)
                    if txt and len(txt) < 100:
                        # Placed strictly above subscribe (y=h-th-750 is approx 1170)
                        f = f"drawtext=text='{txt}':fontfile='{font_path}':fontcolor=white:fontsize=56:box=1:boxcolor=black@0.6:x=(w-text_w)/2:y=h-th-750:enable='between(t,{rel_start},{rel_end})'"
                        caption_filters.append(f)
        
        all_filters = [thumb_filter, sub_filter, bridge_filter, hook_filter] + caption_filters[:40] # Cap at 40 to avoid too long cmd
        video_filter = f"split[v1][v2];[v1]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=40:10[bg];[v2]scale=1080:-1[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,{','.join(all_filters)}"
    else:
        print("WARNING: 'drawtext' filter not found in local ffmpeg. Skipping text overlay...")
        video_filter = "split[v1][v2];[v1]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=40:10[bg];[v2]scale=1080:-1[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2"
        
    # Final binary path check for execution
    if not os.path.exists(ffmpeg_bin):
        ffmpeg_bin = 'ffmpeg'
    
    cmd = [
        ffmpeg_bin,
        '-y',
        '-ss', start_time,
        '-i', input_path,
        '-t', str(duration),
        '-vf', video_filter,
        '-c:v', 'libx264',
        '-c:a', 'aac',
        output_path
    ]
    
    subprocess.run(cmd, check=True)
    print(f"Final video generated at {output_path}")

def generate_srt(transcript_raw, start_time_str, end_time_str, srt_path):
    """Generates an SRT file for YouTube SEO indexing."""
    seg_start = parse_time(start_time_str)
    seg_end = parse_time(end_time_str)
    
    srt_content = ""
    counter = 1
    
    for entry in transcript_raw:
        e_start = entry.get('start', 0)
        e_dur = entry.get('duration', 0)
        e_text = entry.get('text', '')
        e_end = e_start + e_dur
        
        if e_start >= seg_start and e_end <= seg_end:
            # Relative timing for the clip
            r_start = e_start - seg_start
            r_end = e_end - seg_start
            
            # Format to HH:MM:SS,mmm
            def format_srt_time(seconds):
                hrs, rem = divmod(seconds, 3600)
                mins, secs = divmod(rem, 60)
                millis = int((secs - int(secs)) * 1000)
                return f"{int(hrs):02d}:{int(mins):02d}:{int(secs):02d},{millis:03d}"
            
            srt_content += f"{counter}\n"
            srt_content += f"{format_srt_time(r_start)} --> {format_srt_time(r_end)}\n"
            srt_content += f"{e_text}\n\n"
            counter += 1
            
    if srt_content:
        with open(srt_path, "w") as f:
            f.write(srt_content)
        return True
    return False

def create_short(url, start_time, end_time, bridge_text, output_path, hook_text="", transcript_raw=None):
    raw_path = "/tmp/full_video.mp4"
    if os.path.exists(raw_path):
        os.remove(raw_path)
    if os.path.exists(output_path):
        os.remove(output_path)
        
    download_video_section(url, "0", "0", raw_path) 
    process_for_shorts(raw_path, output_path, start_time, end_time, bridge_text, hook_text, transcript_raw)
    
    return output_path
