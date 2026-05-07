import requests
import sys

def test_range_request(base_url, asset_path):
    url = f"{base_url}/api/v1/assets/{asset_path}"
    
    # 1. Test full request
    print(f"Testing full request for {url}...")
    r = requests.get(url)
    print(f"Status: {r.status_code}")
    print(f"Content-Type: {r.headers.get('Content-Type')}")
    print(f"Content-Length: {r.headers.get('Content-Length')}")
    print(f"Accept-Ranges: {r.headers.get('Accept-Ranges')}")
    
    if r.status_code != 200:
        print("❌ Full request failed")
        return
    
    total_size = int(r.headers.get('Content-Length', 0))
    print(f"Total size: {total_size}")
    
    # 2. Test range request (first 100 bytes)
    print("\nTesting range request (0-99)...")
    headers = {"Range": "bytes=0-99"}
    r = requests.get(url, headers=headers)
    print(f"Status: {r.status_code}")
    print(f"Content-Range: {r.headers.get('Content-Range')}")
    print(f"Content-Length: {r.headers.get('Content-Length')}")
    
    if r.status_code == 206 and r.headers.get('Content-Range') == f"bytes 0-99/{total_size}":
        print("✅ Range request successful!")
    else:
        print("❌ Range request failed")

if __name__ == "__main__":
    # Example usage: python verify_range.py http://localhost:8000 jobs/uuid/original/video.mp4
    if len(sys.argv) < 3:
        print("Usage: python verify_range.py <base_url> <asset_path>")
        sys.exit(1)
    
    test_range_request(sys.argv[1], sys.argv[2])
