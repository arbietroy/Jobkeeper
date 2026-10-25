# Jobkeeper 🔎

An AI agent that hunts the internet for **jobs** and **website clients** for you, and sends the good ones to your **Telegram**.

Every 3 hours it:

1. **Searches lots of places at once**
   - Remote job boards: Remotive, RemoteOK, We Work Remotely, Jobicy, Himalayas, Arbeitnow
   - Hacker News "Who is hiring?" and "Seeking freelancer?" threads
   - Reddit hiring subreddits, plus posts from people saying *"I need a website"*
   - **Claude web search**: digs through public LinkedIn posts, X/Twitter, Instagram, Facebook, forums, Indie Hackers, niche boards and tenders
   - **Google Maps**: established local businesses with **no website** (or only an Instagram page). These are ready-made pitch targets *(optional)*
   - Any RSS feed you add, for example a LinkedIn job search or an X search turned into RSS with rss.app *(optional)*
2. **Throws out** duplicates, old posts, and anything off-topic
3. **Has Claude read each one** and score how well it fits *you* (0–100). For leads, Claude also drafts an opening pitch message
4. **Sends you the best matches on Telegram**, and remembers them so you never get the same one twice

A Telegram message looks like this:

```
🎯 LEAD — pitch them · fit 86/100
Sweet Crumbs Bakery has no website
Sweet Crumbs Bakery · 12 Allen Ave
📍 Google Maps

🧠 Busy bakery (210 reviews) taking orders only by phone. A site with online ordering would pay off fast.

✍️ Hi! I came across Sweet Crumbs on Google Maps and your reviews are amazing. I build simple websites
with online ordering for bakeries. Would you be open to a quick chat about taking orders online?

Open →
```

---

## Setup (about 15 minutes, no server needed)

The agent runs free on **GitHub Actions**, so your computer doesn't need to stay on.

### 1. Create your Telegram bot

1. In Telegram, open **@BotFather** and send `/newbot`. Pick any name.
2. BotFather gives you a **token** like `123456:ABC-xyz`. Keep it.
3. Open your new bot and send it any message, like "hi".
4. Get your chat ID. Pick one way:
   - Open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser and copy the number after `"chat":{"id":`
   - Or run it locally: `TELEGRAM_BOT_TOKEN=... python -m jobkeeper chat-id`

### 2. Get an Anthropic API key

Create one at <https://console.anthropic.com/> (Settings → API Keys). The AI scoring and the web-search hunter use this key.

### 3. Add the secrets to GitHub

In this repo, go to **Settings → Secrets and variables → Actions → New repository secret** and add:

| Secret | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | the token from BotFather |
| `TELEGRAM_CHAT_ID` | your chat ID |
| `ANTHROPIC_API_KEY` | your Anthropic key |
| `GOOGLE_MAPS_API_KEY` | *(optional)* for the Google Maps lead finder |

### 4. Tell it about yourself

Edit **`config.yaml`**, especially `profile.about` and `profile.preferences`. The AI judges every opportunity against this text, so the more specific you are (skills, rates, where you can work from, the kinds of clients you like), the better the matches.

### 5. Turn it on

Go to the **Actions** tab, enable workflows if GitHub asks, and open **Jobkeeper hunt**. Click **Run workflow**, choose `ping` to send a Telegram test message, or choose `hunt` to search right away. Your first opportunities should arrive on Telegram within a few minutes. After that it runs automatically every 3 hours. To change the schedule, edit the `cron` line in `.github/workflows/jobkeeper.yml`.

---

## Optional extras

**Google Maps lead finder** finds local businesses with no website. Enable "Places API (New)" in the Google Cloud console, create an API key, add it as `GOOGLE_MAPS_API_KEY`, then in `config.yaml` set `google_places.enabled: true` and replace `<your city>` in the queries.

**LinkedIn / X / Instagram feeds.** These sites have no free API and block bots, so there are two ways to cover them:
- The built-in Claude web search already looks for their public posts on every run.
- For a direct feed, make an RSS link of a search with [rss.app](https://rss.app), FetchRSS or Zapier, then add it under `sources.rss.feeds` and set `rss.enabled: true`.

## Run it on your own computer

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=... TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=...
python -m jobkeeper ping        # test message to Telegram
python -m jobkeeper run --dry   # hunt and print results without sending
python -m jobkeeper run         # the real thing
```

Run the tests with `pip install pytest && pytest`.

## Cost

- GitHub Actions: free for this amount of use.
- Telegram: free.
- Anthropic: you pay for scoring (up to 120 posts per run) and for web searches (up to 20 per run). To lower the cost, set `ai.model` to `claude-sonnet-5-5` or `claude-haiku-5-5`, reduce `web_search.max_searches`, or run less often. Check your usage in the Anthropic console after the first day.

## Tuning

| Want… | Change in `config.yaml` |
|---|---|
| Fewer, better messages | raise `filters.min_score` (e.g. 75) |
| More messages | lower `filters.min_score`, raise `telegram.max_messages_per_run` |
| Only fresh posts | lower `filters.max_age_days` |
| Allow mid-level roles too | set `filters.entry_level_only: false` |
| Include jobs that don't say who can apply | set `filters.require_nigeria_eligible: false` (not recommended) |
| See what it would send, without sending | Actions → Run workflow → mode `preview` |
| Different roles | edit `profile`, `search_terms`, `include_keywords` |
| Turn a source off | set its `enabled: false` |

## How it's built

```
jobkeeper/
  sources/        one file per place it searches (boards, reddit, hackernews, websearch, places, rss)
  pipeline.py     collect → dedupe → filter → AI score → send
  ai.py           Claude scoring and pitch drafting (structured JSON output)
  telegram.py     message formatting and sending
  state.py        remembers what was already sent (state/seen.json, committed by the workflow)
config.yaml       your profile, filters and source settings
```

Each source handles its own errors. If a site is down or changes its format, the run carries on with the other sources and logs a warning.
