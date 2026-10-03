"""
scripts/bench_vision.py – Benchmark script for Frameline MiniCPM-V vision pass.
"""
import sys
import time
from pathlib import Path

# Ensure root directory is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app import config, store

from backend.app.video_index import generate_video_id
from backend.app.vision_pass import run_vision_pass


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/bench_vision.py <path_to_video.mp4>")
        sys.exit(1)

    video_path = Path(sys.argv[1]).resolve()
    if not video_path.exists():
        print(f"Error: Video file '{video_path}' not found.")
        sys.exit(1)

    video_id = f"bench-{generate_video_id()[:8]}"
    print("=" * 60)
    print(f"Frameline Vision Pass Benchmark")
    print(f"Video File       : {video_path.name}")
    print(f"Vision Model     : {config.VISION_MODEL}")
    print(f"Frame Interval   : {config.VISION_FRAME_INTERVAL_SEC} s")
    print(f"Max Edge         : {config.VISION_FRAME_MAX_EDGE} px")
    print(f"Think Budget     : {config.VISION_THINK_BUDGET_SEC} s")
    print(f"Dedup Threshold  : {config.VISION_DEDUP_THRESHOLD}")
    print(f"Mock Mode        : {config.MOCK_VISION_LLM}")
    print("=" * 60)

    def progress_callback(pct: float, msg: str):
        print(f"  [{pct:5.1f}%] {msg}")

    start_time = time.time()
    results = run_vision_pass(video_id, video_path, progress_cb=progress_callback)
    total_time = time.time() - start_time

    n_frames = len(results)
    reused_count = sum(1 for r in results if r.get("reused"))
    llm_count = n_frames - reused_count
    total_latency_ms = sum(r.get("latency_ms", 0) for r in results)
    avg_latency_ms = (total_latency_ms / n_frames) if n_frames > 0 else 0

    fps_proc = (n_frames / total_time) if total_time > 0 else 0

    print("\n" + "=" * 60)
    print("Benchmark Results Summary")
    print("=" * 60)
    print(f"Total Processed Frames : {n_frames}")
    print(f"LLM Inferences         : {llm_count}")
    print(f"Reused Frames (Dedup)  : {reused_count}")
    print(f"Total Elapsed Time     : {total_time:.2f} s")
    print(f"Processing Speed       : {fps_proc:.2f} frames/sec")
    print(f"Average Frame Latency  : {avg_latency_ms:.1f} ms")
    print("=" * 60)


if __name__ == "__main__":
    main()
