import json
from tools import script_to_video_dashscope, log_info, log_error
from logging_utils import configure_logging
from datetime import datetime

# Configure logging
configure_logging()

# Test Veo JSON prompt
veo_json_str = '''{
  "version": "1.0",
  "scenes": [
    {
      "script": "Welcome to CES 2026. Let's explore the latest innovations in technology.",
      "visual": "A futuristic cityscape with flying cars and holographic displays, showcasing CES exhibition hall entrance with the year 2026 visible.",
      "audio": "Upbeat, tech-inspired background music with subtle futuristic sound effects."
    },
    {
      "script": "The main hall features cutting-edge AI and robotics technologies.",
      "visual": "Inside CES exhibition hall with various tech booths, robots demonstrating capabilities, people interacting with AI interfaces.",
      "audio": "Same background music continues."
    }
  ]
}'''

# Generate test video
try:
    log_info("test.video_generation.start")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"test_video_{timestamp}.mp4"
    
    result = script_to_video_dashscope(
        veo_json_str,
        filename=filename,
        # Using default size (1280*720) and duration (15s) which should be supported
    )
    
    log_info("test.video_generation.success", result=result)
    print(f"Video generation successful! Result: {result}")
except Exception as e:
    log_error("test.video_generation.error", error=str(e))
    print(f"Video generation failed: {e}")
