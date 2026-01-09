#!/usr/bin/env python3

"""
Test script for script_to_video_dashscope function
"""

import json
from tools import script_to_video_dashscope

# Create a simple test Veo JSON prompt
veo_json = {
    "version": "1.0",
    "scenes": [
        {
            "text": "A beautiful landscape with mountains and a lake",
            "duration": 5
        }
    ]
}

veo_json_str = json.dumps(veo_json, ensure_ascii=False)

print("Testing script_to_video_dashscope...")
try:
    result = script_to_video_dashscope(veo_json_str, filename="test_video.mp4")
    print(f"Test successful: {result}")
except Exception as e:
    print(f"Test failed: {e}")
