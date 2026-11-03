# Keep model and result state consistent after fallback

Scope: the browser UI state around the existing embedding client. The client, model, database and retrieval algorithm stay unchanged. This is an authorized contest bug fix; no browser control or real fallback is simulated as acceptance.

The original app/client code was run with explicitly offline VM DOM/Worker/API substitutes. One control passed: failed GPU initialization terminated its Worker and retried all five inputs on a new WASM Worker. Two regression assertions failed: a precision change removed the selected KB but retained its old result/timing without advancing the request generation; terminal fallback inference failure left `activeModel` non-null even though the client had dropped its state, so `ensureModel` did not reinitialize.

Use one view-invalidation helper: advance the generation, clear results and clear timing. Rebuilding the KB list, explicit mode changes and explicit KB changes use that same operation. This follows the existing working manual-KB-change behavior and covers programmatic selection changes. It does not reset generation values or revive old request tokens.

On a failed client status, clear the ready model, selected context and result view. A subsequent ready status rebuilds compatible options only if the previous model was absent or its precision changed. This conditional matters: a fatal Worker event can emit failed before a successful same-precision fallback, while a normal same-precision fallback should preserve the still-valid search token. Recovered options do not restore a cancelled token or silently select a different KB.

Alternatives were considered: a new application-state framework would add unnecessary scope; reloading the page would hide the state bug and lose its in-memory evidence. The small shared invalidation operation keeps the existing architecture and precision guard.

Verify one fix at a time against the original failing assertions, then verify the fatal/nonfatal same-precision ready boundary and existing pure tests. Keep all offline results labelled as substitutes. Actual WebGPU-unavailable fallback, browser switching/reload and foreground timing still require supported real-browser verification.
