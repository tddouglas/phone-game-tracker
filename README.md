# gamechat

Scrapes daily-game shares (Wordle, Connections, Globle, whatever someone drops next) out of one iMessage group chat on your Mac, and publishes a scoreboard site to Vercel for the group.

```
Mac: ~/Library/Messages/chat.db ──► python3 -m gamechat sync ──► site/data.json ──► git push ──► Vercel
                                     │ built-in parsers
                                     │ learned rules (rules.json)
                                     └ Claude fallback for unknown games → writes a new rule
```

- **New people**: any new number or email that posts in the chat becomes a player automatically. Names come from your Contacts, from `gamechat name`, or show up masked as `•••1234`.
- **New games**: common formats like `Name #123 3/6` are picked up with no setup. Anything else that looks like a share (an emoji grid, a score, a link) goes to Claude once. Claude returns the result plus a regex rule, and the rule is checked against that message before it's saved to `rules.json`, so later shares of that game parse locally at no cost.
- **Site**: shows each day's game × player grid, who missed what, per-game leaderboards (avg / best / worst / fails / missed days / streak), score charts, and per-player history with highs, lows and missed days.

## Setup (one time)

1. **Full Disk Access.** In System Settings → Privacy & Security → Full Disk Access, turn it on for your terminal (Terminal, iTerm, Ghostty…), then restart the terminal. Without it, macOS blocks reads of `chat.db`.
2. **Config**
   ```sh
   cp config.example.json config.json
   python3 -m gamechat chats --groups     # find the group
   python3 -m gamechat use 42             # or: use "Game Chat"
   ```
3. **API key** (for unknown games): `export ANTHROPIC_API_KEY=sk-ant-...` in your shell profile. Without a key, unknown games queue up in `gamechat review`, and they get retried automatically once the key is set.
4. **First sync + local preview**
   ```sh
   python3 -m gamechat sync --no-publish
   python3 -m http.server -d site 8000    # open http://localhost:8000
   ```
5. **Name people**
   ```sh
   python3 -m gamechat players
   python3 -m gamechat name +15551234567 "Dave"
   python3 -m gamechat name dave@icloud.com "Dave"   # same name = merged into one player
   ```
6. **Deploy to Vercel**
   - `git init`, commit, and push to a **private** GitHub repo. `.gitignore` already keeps `config.json` and `state.db` (phone numbers, raw messages) out of the repo.
   - In Vercel: Add New → Project → import the repo. Set **Root Directory = `site`** and Framework = Other, with no build command.
   - Keep `"publish": "git"` in `config.json`. Every sync then commits `site/data.json` and pushes, and Vercel redeploys.
   - Alternative without GitHub: `npm i -g vercel`, run `vercel link` inside `site/`, and set `"publish": "vercel"`.

## Day to day

```sh
python3 -m gamechat sync        # pull new messages → parse → export → publish
```
Handy alias: `alias gc='cd ~/code/gamechat && python3 -m gamechat sync'`.

| Command | What it does |
|---|---|
| `sync --full` | Re-parse the whole chat history (after editing rules or aliases). LLM answers are cached, so this costs nothing extra. |
| `games` | Games found so far, and which parser handled each |
| `review` | Messages that looked like a share but didn't parse |
| `alias "Globle Capitals" "Globle: Capitals"` | Merge or rename a game |
| `players` / `name` | Map handles to display names |

## Fixing a game that parses wrong

Edit its entry in `rules.json`. Rules are tried before the built-ins, so a rule with the same `key` overrides a built-in parser. Then run `sync --full`.

```json
{
  "name": "Krillian", "key": "krillian",
  "detect": "Krillian\\s*#\\d+",
  "puzzle": "Krillian\\s*#(\\d+)",
  "score": "(?P<score>\\d+)\\s*krill",
  "direction": "higher", "unit": "points", "display": "{score} krill"
}
```
Other fields: `count` (score = number of times a symbol appears, e.g. `"💡"`), `fail` (regex that marks a failed attempt), `failed_score`, `max_score`.

## How scoring works

- Each game has a direction: lower is better (guesses, time, mistakes) or higher is better (points, stars). A fail is scored as one worse than the max (Wordle X/6 → 7), so averages still mean something.
- Day attribution: a numbered puzzle belongs to the day most people posted it, so a 12:30am Wordle still counts for the right day.
- Duplicates: if someone reposts, their first post counts.
- Missed day: a day someone in the chat played the game, on or after this player's first-ever play of it, where this player didn't post.

## Privacy

Only display names, an opaque player id, scores, and the share text (with links stripped) go into `data.json`. Phone numbers, emails and other chat messages stay in `state.db` on your Mac. Set `"export_raw": false` to drop share text too. The Vercel URL is public to anyone who has it. If that's a problem, use Vercel's deployment protection.

## Built-in parsers

Wordle, Connections, Strands, NYT Mini, Globle (+ Capitals), Worldle, Framed, Quordle, Waffle, plus a generic `Name #N X/Y` matcher (Tradle, Costcodle, Nerdle, Bandle, …).

## Tests

```sh
python3 tests/test_e2e.py     # fake chat.db, mocked LLM: parsers, rule learning, dedupe, no number leaks
python3 tests/fake_chatdb.py  # writes tests/fake_chat.db to point config at for a demo
```
Requires macOS with python3 3.9+ and nothing else, since it uses the standard library only.
