"""Idempotent patches for local pi (re-apply after every pi upgrade):
  python C:/Users/Berton/probe8765/patch_codemode_cap.py

PATCH 1 — codemode output cap 8k chars (was 10k tokens = 40k chars):
  DEFAULT_MAX_OUTPUT_TOKENS 10_000 -> 2_000 (x CHARS_PER_TOKEN=4) in the codemode
  executor source plus wherever that constant is inlined under dist/bundle/chunks
  (chunk file names are content-hashed and change between versions, so bundle
  copies are located by pattern, not by path).
  Existing truncateOutput still does head/tail keep + spill-to-file on overflow;
  scripts can raise per-run via `// @options: {"max_output_tokens": N}`.

PATCH 2 — summarization runs without thinking (2026-10-13):
  Covers every "reasoning from session thinkingLevel" request path EXCEPT normal
  chat (agent-loop builds its own reasoning from a per-turn snapshot, untouched):
    - compaction summaries (compaction.js createSummarizationOptions — history +
      turn-prefix; branch-summarization builds its own options and never set
      reasoning upstream, nothing to patch there);
    - bug-report summaries (bug-report.js builds requestOptions inline; same
      guard, maxTokens 4096 includes thinking so high could starve the summary).

PATCH 3 — stop historical thinking from occupying context (2026-10-13):
  With session thinking=high, pi resends every old assistant turn's thinking
  blocks on every request (anthropic serializer) AND counts them in its own
  context estimate (chars/4), so ~59% of the compaction trigger line was stale
  thinking. Three coordinated changes, one per occupancy surface:
    3a estimator   compaction.js estimateTokens: assistant thinking no longer
                   counted (chars/4). Footer % and compaction triggers now
                   reflect the stripped wire.
    3b serializer  pi-ai anthropic-messages.js convertMessages: thinking blocks
                   are only emitted for the LAST assistant message (tool-loop
                   continuation keeps its plan); older turns' thinking is dropped
                   from the wire. This is the CLIENT-SIDE EQUIVALENT of
                   Anthropic's clear_thinking context edit — it is NOT a match
                   of live API semantics. Current Anthropic models (Opus 4.5+,
                   Sonnet 4.6+, Haiku 5.5+) preserve and bill old-turn thinking,
                   and preserved-thinking prefix binding (default for accounts
                   registered after 2026-08-31) requires history before a kept
                   thinking block to stay byte-stable: this patch rewrites that
                   history on every request, so against the REAL Anthropic API
                   any request with >=2 historical assistant turns breaks
                   thinking signatures (400 errors / dropped blocks). Safe only
                   on endpoints that do not validate signatures (omlx / GLM).
                   Do not point a patched pi at real Anthropic with thinking on.
    3c summary     compaction/utils.js serializeConversation: [Assistant thinking]
                   text no longer serialized into compaction/bug-report summary
                   prompts (was a large share of the ~29k-token summary request).
  Note: first request after this patch takes a one-time full prefill (the wire
  text of old turns changed, prefix cache invalidates once).

Safety: idempotent; per-file backup (.bak-*) refreshed only when upstream content
changed; reads/writes with newline="" (CRLF-safe); node --check per file with
automatic rollback from the backup on failure; MISSING / PATTERN NOT FOUND exit 1.
"""
import glob
import os
import shutil
import subprocess
import sys

DIST = r"D:\scoop\persist\nodejs-lts\bin\node_modules\@earendil-works\pi-coding-agent\dist"
PI_AI = r"D:\scoop\persist\nodejs-lts\bin\node_modules\@earendil-works\pi-coding-agent\node_modules\@earendil-works\pi-ai\dist"
BAK_CAP = ".bak-20261013-codemodecap"
BAK_SUM = ".bak-20261013-sumnothink"
BAK_STRIP = ".bak-20261013-stripthink"

# Literal-path targets: (path, old, new, backup suffix)
LITERAL_TARGETS = [
    # PATCH 1
    (os.path.join(DIST, "extensions", "codemode", "execute.js"),
     "const DEFAULT_MAX_OUTPUT_TOKENS = 10_000;",
     "const DEFAULT_MAX_OUTPUT_TOKENS = 2_000; /* PATCH 2026-10-13: 8k chars cap (was 40k); reapply after pi upgrade */",
     BAK_CAP),
    # PATCH 2
    (os.path.join(DIST, "core", "compaction", "compaction.js"),
     'if (model.reasoning && thinkingLevel && thinkingLevel !== "off") {',
     'if (false && model.reasoning && thinkingLevel && thinkingLevel !== "off") { /* PATCH 2026-10-13: summarization runs without thinking (chat may be high); reapply after pi upgrade */',
     BAK_SUM),
    (os.path.join(DIST, "core", "bug-report.js"),
     '...(model.reasoning && options.thinkingLevel && options.thinkingLevel !== "off"',
     '...(!1 && model.reasoning && options.thinkingLevel && options.thinkingLevel !== "off" /* PATCH 2026-10-13 sumnothink */',
     BAK_SUM),
    # PATCH 3a estimator (readable copy)
    (os.path.join(DIST, "core", "compaction", "compaction.js"),
     "chars += block.thinking.length;",
     "chars += 0; /* PATCH 2026-10-13 stripthink: thinking no longer counted in context estimate */",
     BAK_STRIP),
    # PATCH 3b serializer (readable copy, two edits)
    (os.path.join(PI_AI, "api", "anthropic-messages.js"),
     "    const assistantLevels = new Map();",
     '    const assistantLevels = new Map();\n'
     '    // PATCH 2026-10-13 stripthink: only the LAST assistant turn keeps its thinking\n'
     '    // on the wire (tool-loop continuation); older turns\' thinking is dropped.\n'
     '    let lastAssistantIndex = -1;\n'
     '    for (let k = transformedMessages.length - 1; k >= 0; k--) {\n'
     '        if (transformedMessages[k].role === "assistant") {\n'
     '            lastAssistantIndex = k;\n'
     '            break;\n'
     '        }\n'
     '    }',
     BAK_STRIP),
    (os.path.join(PI_AI, "api", "anthropic-messages.js"),
     '                else if (block.type === "thinking") {\n'
     '                    // Redacted thinking: pass the opaque payload back as redacted_thinking',
     '                else if (block.type === "thinking") {\n'
     '                    if (i !== lastAssistantIndex)\n'
     '                        continue; /* PATCH 2026-10-13 stripthink: older turns\' thinking not resent */\n'
     '                    // Redacted thinking: pass the opaque payload back as redacted_thinking',
     BAK_STRIP),
    # PATCH 3c summary serializer (readable copy)
    (os.path.join(DIST, "core", "compaction", "utils.js"),
     "thinkingParts.push(block.thinking);",
     "if (false) thinkingParts.push(block.thinking); /* PATCH 2026-10-13 stripthink: thinking not serialized into summary prompts */",
     BAK_STRIP),
]

# Bundle targets: (old, new, backup suffix) — searched across dist/bundle/chunks/*.js
BUNDLE_TARGETS = [
    # PATCH 1
    ("DEFAULT_MAX_OUTPUT_TOKENS=1e4",
     "DEFAULT_MAX_OUTPUT_TOKENS=2e3",
     BAK_CAP),
    # PATCH 2
    ('model.reasoning&&thinkingLevel&&thinkingLevel!=="off"&&(options.reasoning=thinkingLevel)',
     '!1&&model.reasoning&&thinkingLevel&&thinkingLevel!=="off"&&(options.reasoning=thinkingLevel)/*PATCH 2026-10-13 sumnothink*/',
     BAK_SUM),
    ('model.reasoning&&options.thinkingLevel&&options.thinkingLevel!=="off"?{reasoning:options.thinkingLevel}:{}',
     '!1&&model.reasoning&&options.thinkingLevel&&options.thinkingLevel!=="off"?{reasoning:options.thinkingLevel}:{}/*PATCH 2026-10-13 sumnothink*/',
     BAK_SUM),
    # PATCH 3a estimator (bundle copy)
    ('block.type==="thinking"?chars+=block.thinking.length:',
     'block.type==="thinking"?chars+=0:/*PATCH 2026-10-13 stripthink*/',
     BAK_STRIP),
    # PATCH 3b serializer (bundle copy, two edits; IIFE keeps one statement)
    ('let params=[],assistantLevels=new Map,pendingSystemMessages=[]',
     'let params=[],assistantLevels=new Map,lastAssistantIndex=function(){for(let k2=transformedMessages.length-1;k2>=0;k2--)if(transformedMessages[k2].role==="assistant")return k2;return -1}(),pendingSystemMessages=[]',
     BAK_STRIP),
    ('else if(block.type==="thinking"){if(block.redacted)',
     'else if(block.type==="thinking"){if(i!==lastAssistantIndex)continue;/*PATCH 2026-10-13 stripthink*/if(block.redacted)',
     BAK_STRIP),
    # PATCH 3c summary serializer (bundle copy)
    ('if(block.type==="thinking")thinkingParts.push(block.thinking);',
     'if(!1&&block.type==="thinking")thinkingParts.push(block.thinking);/*PATCH 2026-10-13 stripthink*/',
     BAK_STRIP),
]

def read_src(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()

def patch_text(path, old, new, bak):
    """Apply one patch. Returns True on success (patched or already applied)."""
    src = read_src(path)
    marker = new.split("/*")[0].strip()
    # Marker check first: for prepended/fused patches the old pattern remains a
    # substring of the patched text, so old-absence is NOT a patched signal.
    if marker in src:
        print(f"already patched: {os.path.basename(path)}")
        return True
    if old not in src:
        print(f"PATTERN NOT FOUND in {os.path.basename(path)} — pi internals changed, inspect manually")
        return False
    bak_path = path + bak
    if not os.path.exists(bak_path):
        shutil.copy2(path, bak_path)
    else:
        bak_src = read_src(bak_path)
        # Refresh only when the backup matches NEITHER the old nor the patched
        # form, i.e. it belongs to a dead upstream version. A backup that still
        # contains the old form is the pristine pre-patch original of a live
        # version (e.g. when several targets hit the same chunk file) — never
        # overwrite it mid-run.
        if old not in bak_src and marker not in bak_src:
            shutil.copy2(path, bak_path)
            print(f"backup refreshed (stale upstream version): {os.path.basename(bak_path)}")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(src.replace(old, new, 1))
    check = subprocess.run(["node", "--check", path], capture_output=True, text=True)
    if check.returncode != 0:
        if os.path.exists(bak_path):
            shutil.copy2(bak_path, path)
            print(f"syntax FAIL, rolled back from backup: {os.path.basename(path)}")
        else:
            print(f"syntax FAIL, no backup to roll back: {os.path.basename(path)}")
        print(check.stderr[:400])
        return False
    print(f"patched+syntax-ok: {os.path.basename(path)}")
    return True

def main():
    rc = 0
    for path, old, new, bak in LITERAL_TARGETS:
        if not os.path.exists(path):
            print(f"MISSING (pi moved?): {path}")
            rc = 1
            continue
        if not patch_text(path, old, new, bak):
            rc = 1
    chunk_files = sorted(glob.glob(os.path.join(DIST, "bundle", "chunks", "*.js")))
    if not chunk_files:
        print("MISSING: no files under bundle/chunks — pi layout changed")
        rc = 1
    for old, new, bak in BUNDLE_TARGETS:
        marker = new.split("/*")[0].strip()
        hits = [p for p in chunk_files if old in read_src(p)]
        if not hits:
            dones = [p for p in chunk_files if marker in read_src(p)]
            if dones:
                print(f"already patched (bundle): {', '.join(os.path.basename(p) for p in dones)}")
            else:
                print("PATTERN NOT FOUND in bundle/chunks — pi internals changed, inspect manually")
                rc = 1
            continue
        for path in hits:
            if not patch_text(path, old, new, bak):
                rc = 1
    print("done" if rc == 0 else "DONE WITH ERRORS")
    sys.exit(rc)

if __name__ == "__main__":
    main()
