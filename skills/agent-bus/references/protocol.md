# cic bus protocol

## Storage layout (`$CIC_HOME/bus`, default `~/.cic/bus`)
```
inbox/<agent>/tmp/   messages being written
inbox/<agent>/new/   delivered, unclaimed
inbox/<agent>/cur/   claimed (read) messages
threads/<thread>.jsonl   append-only transcript of every message on a thread
```
A `:` in an agent name is stored as `__` in directory names.

## Envelope
```json
{
  "id": "m-3f2a9c1b0d4e",
  "ts": "2026-10-06T21:30:00+05:30",
  "from": "codex",
  "to": ["reviewer"],
  "thread": "t-1006-213000-ab12",
  "kind": "task",
  "reply_to": null,
  "body": "free text (markdown or XML-tagged prompt)",
  "meta": {}
}
```
- `kind`: `message` (default), `task` (expects a reply), `reply`, `event` (status update, no reply expected), or `control` (`stop` / `shutdown` for bus agents).
- `reply_to`: the id of the message being answered. `cic bus ask` waits for exactly this.
- `meta` from bus agents: `{"ok": bool, "job": "<cic job id>", "model": "..."}`.

## Semantics
- **Delivery:** the message is written to `tmp/`, then renamed into `new/`. Rename is atomic, so readers never see partial messages.
- **Claiming:** `recv` renames `new/<file>` to `cur/<file>`. Only one reader can win the rename, so each message is processed once even with competing readers.
- **Ordering:** by send time (the filename starts with an epoch timestamp). There is no global ordering across inboxes.
- **Filtering:** `recv` can filter by `--thread` and `--from`. Non-matching messages stay unclaimed.
- **Waiting:** `recv --wait N` and `ask --wait N` poll with backoff (0.2 s up to 1 s) until a match arrives or the time expires (exit 3).
- **Durability:** files survive restarts. Transcripts are append-only and written under an exclusive lock.

## Bus agent (`cic serve`) loop
1. Claim the next message for its name, waiting up to `--poll` seconds.
2. Map `thread` to its own session: a Claude session id via `--resume`, or a Codex thread id via `codex exec resume`. Gemini is stateless, so it receives the last 8 thread messages as context.
3. Run the agent with the message wrapped as `<message from=… id=… thread=…>`, in chat mode, at its access level, with the bus addendum that lets it message peers.
4. Reply to the sender with `kind=reply` and `reply_to=<id>`.
5. Exit on a `control` message `stop`, on SIGTERM, or after `--idle-exit` idle seconds.

State and logs live in `~/.cic/serve/<name>.json` and `~/.cic/serve/<name>.log`.

## Interop from other languages
Any process can join without cic by writing envelope JSON files into `inbox/<agent>/tmp/` and renaming them into `new/`, then appending the same JSON line to `threads/<thread>.jsonl`.
