import yt_dlp

ydl_opts = {
    "quiet": False,
    "no_warnings": False,
    "js_runtimes": {"node": {}},
}
try:
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info("https://www.youtube.com/watch?v=fkNQvlAZbg4", download=False)
        print("SUCCESS:", info.get("title"))
except Exception as e:
    print("ERROR:", str(e))
