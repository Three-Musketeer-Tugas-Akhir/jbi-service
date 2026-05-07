import re

def sanitize(filename):
    # This matches the updated logic in the services
    return re.sub(r'[^\w\s\-\.\[\]]', '_', filename)

test_cases = [
    ("[FULL] Video Title.mp4", "[FULL] Video Title.mp4"),
    ("Normal Video-123.mp4", "Normal Video-123.mp4"),
    ("Special! @Characters#.mp4", "Special__ _Characters_.mp4"),
    ("[PREVIEW] Part 1 (HD).mp4", "[PREVIEW] Part 1 _HD_.mp4"),
]

print("Verifying Filename Sanitization:")
for original, expected in test_cases:
    result = sanitize(original)
    status = "✅" if result == expected else "❌"
    print(f"{status} Original: '{original}' -> Result: '{result}'")

if __name__ == "__main__":
    pass
