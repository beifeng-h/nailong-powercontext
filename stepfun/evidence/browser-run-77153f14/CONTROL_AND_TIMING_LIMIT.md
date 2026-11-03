# Browser control and timing boundary

After run completion, the attempted action was a **read** of native Edge window 132826 via `cua.getApp({windowId:132826})`, intended to check foreground context for `http://127.0.0.1:34021/benchmark.html`. The tool stopped Computer Use for that turn because it could not determine the current browser URL on Windows confidently enough to enforce policy, and required ending that turn. No click or input was sent by that operation. The turn ended as required.

In the subsequent turn, the normal documented browser-only read interfaces succeeded: the retained tab 1638301526 reported the exact benchmark URL, and read-only `#raw` inspection confirmed the completed run and metrics. These reads do not establish recovery of native window control. The blocked `getApp` call was not repeated, and no alternate window-focus mechanism, browser flags, security change or tool reset was used to bypass the guard. This was a URL-confidence restriction, **not evidence that the computer was offline**.

The supplied documentation gives no specific automatic recovery procedure for this native URL-confidence stop. A genuine foreground calibration remains pending. A user can bring the existing Edge benchmark window to the front, without refreshing the retained report, before normal supported verification is reconsidered. No reconnect or instance restart is inferred to be necessary.

The observed report's `foreground-dom-update-plus-two-raf` label records the benchmark's visibility check and timing algorithm. Its roughly two-second display samples have not been calibrated against a physically foreground window. Background/occlusion throttling is a hypothesis, not an established cause. Keep ready timing separate from display timing, and do not describe two animation-frame callbacks as a physical screen presentation timestamp.

Real automatic WASM fallback under genuinely unavailable WebGPU, browser state switching/reload, and service/database restart remain unverified. Explicit WASM success and the separate synthetic-vector API state test do not fill those gaps.
