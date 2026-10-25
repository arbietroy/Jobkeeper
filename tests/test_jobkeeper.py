import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from jobkeeper import pipeline
from jobkeeper.config import load_config
from jobkeeper.models import Item, clean_text
from jobkeeper.sources import boards, hackernews, parse_date, places, reddit
from jobkeeper.sources.websearch import parse_results
from jobkeeper.state import SeenStore
from jobkeeper.telegram import format_item

NOW = datetime.now(timezone.utc)
RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Acme: Senior Frontend Developer</title><link>https://wwr.example/1</link>
<pubDate>%s</pubDate><description>&lt;p&gt;React &amp;amp; Next.js&lt;/p&gt;</description></item>
<item><title>[For Hire] me, a designer</title><link>https://wwr.example/2</link><pubDate>%s</pubDate></item>
</channel></rss>""" % ((NOW.strftime("%a, %d %b %Y %H:%M:%S +0000").encode(),) * 2)


def mock_http(routes):
    def handler(request: httpx.Request):
        for prefix, body in routes.items():
            if str(request.url).startswith(prefix):
                return httpx.Response(200, content=body if isinstance(body, bytes) else json.dumps(body).encode())
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def cfg():
    c = load_config()
    c["profile"]["search_terms"] = ["web developer"]
    return c


def test_clean_text_and_dates():
    assert clean_text("<p>Hi&amp;<b>there</b></p>") == "Hi& there"
    assert parse_date("2026-10-01T10:00:00Z").year == 2026
    assert parse_date(1760000000000).year == 2025
    assert parse_date("Mon, 06 Oct 2026 10:00:00 +0000").day == 6
    assert parse_date("garbage") is None


def test_remotive_and_remoteok(cfg):
    http = mock_http({
        "https://remotive.com": {"jobs": [{"title": "Web Dev", "url": "https://r/1", "company_name": "A",
                                          "publication_date": "2026-10-10T00:00:00", "description": "<b>x</b>"}]},
        "https://remoteok.com": [{"legal": "notice"}, {"position": "Shopify Dev", "id": 5, "slug": "s", "company": "B",
                                                       "epoch": 1760000000, "tags": ["shopify"]}],
    })
    r = boards.remotive(cfg, http)
    assert r[0].title == "Web Dev" and r[0].company == "A" and r[0].description == "x"
    ok = boards.remoteok(cfg, http)
    assert len(ok) == 1 and ok[0].url == "https://remoteok.com/remote-jobs/s"


def test_weworkremotely_splits_company(cfg):
    items = boards.weworkremotely(cfg, mock_http({"https://weworkremotely.com": RSS}))
    assert items[0].company == "Acme" and items[0].title == "Senior Frontend Developer"
    assert items[0].age_days() < 1


def test_reddit_drops_for_hire_and_tags_leads(cfg, monkeypatch):
    monkeypatch.setattr(reddit.time, "sleep", lambda s: None)
    cfg["sources"]["reddit"] = {"job_subreddits": ["forhire"], "lead_searches": [{"sub": "smallbusiness", "query": "x"}]}
    items = reddit.fetch(cfg, mock_http({"https://www.reddit.com": RSS}))
    jobs = [i for i in items if i.kind == "job"]
    leads = [i for i in items if i.kind == "lead"]
    assert len(jobs) == 1 and len(leads) == 2


def test_hackernews_top_level_only(cfg):
    http = mock_http({
        "https://hn.algolia.com/api/v1/search_by_date?tags=story": {"hits": [
            {"objectID": "100", "title": "Ask HN: Who is hiring? (October 2026)"},
            {"objectID": "101", "title": "Ask HN: Who wants to be hired? (October 2026)"},
        ]},
        "https://hn.algolia.com/api/v1/search_by_date?tags=comment": {"hits": [
            {"objectID": "1", "parent_id": 100, "comment_text": "Acme | Frontend | Remote", "created_at_i": int(NOW.timestamp())},
            {"objectID": "2", "parent_id": 1, "comment_text": "reply", "created_at_i": int(NOW.timestamp())},
        ]},
    })
    items = hackernews.fetch(cfg, http)
    assert [i.url for i in items] == ["https://news.ycombinator.com/item?id=1"]


def test_places_keeps_businesses_without_site(cfg, monkeypatch):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "k")
    cfg["sources"]["google_places"] = {"queries": ["salons in town"], "min_reviews": 5}
    http = mock_http({"https://places.googleapis.com": {"places": [
        {"displayName": {"text": "No Site"}, "userRatingCount": 40, "googleMapsUri": "https://maps/1"},
        {"displayName": {"text": "IG Only"}, "userRatingCount": 9, "websiteUri": "https://instagram.com/x", "googleMapsUri": "https://maps/2"},
        {"displayName": {"text": "Has Site"}, "userRatingCount": 90, "websiteUri": "https://has.site", "googleMapsUri": "https://maps/3"},
        {"displayName": {"text": "Too new"}, "userRatingCount": 1, "googleMapsUri": "https://maps/4"},
    ]}})
    names = [i.company for i in places.fetch(cfg, http)]
    assert names == ["No Site", "IG Only"]


def test_parse_websearch_results():
    text = 'Here you go:\n```json\n[{"kind":"lead","title":"Bakery","url":"https://x.com/1"},{"title":"no url"}]\n```'
    assert parse_results(text) == [{"kind": "lead", "title": "Bakery", "url": "https://x.com/1"}]
    assert parse_results("nothing found") == []


def test_prefilter(cfg, tmp_path):
    seen = SeenStore(tmp_path / "s.json")
    good = Item("X", "AI Automation Specialist", "https://good", location="Worldwide", posted_at=NOW)
    old = Item("X", "AI Automation Specialist", "https://old", location="Worldwide", posted_at=NOW - timedelta(days=30))
    off = Item("X", "Accountant", "https://off", description="We use AI and automation and have a website")
    senior = Item("X", "Senior Automation Engineer", "https://senior", location="Worldwide")
    years = Item("X", "Automation Engineer", "https://years", location="Worldwide",
                 description="Requires 5+ years of experience with Zapier")
    us_only = Item("X", "n8n Automation Builder", "https://us", location="USA")
    auth = Item("X", "Zapier Expert Junior", "https://auth", location="Remote",
                description="Must be authorized to work in the US.")
    unclear = Item("X", "Junior Workflow Automation Developer", "https://unclear", location="Remote")
    lead = Item("Reddit", "Need help for my bakery", "https://lead", kind="lead")
    unpaid = Item("X", "Unpaid AI intern", "https://unpaid")
    dup = Item("Y", "AI Automation Specialist", "https://GOOD")
    already = Item("X", "AI Automation intern", "https://seen")
    seen.add(already.id)
    out = pipeline.prefilter(cfg, [good, old, off, senior, years, us_only, auth, unclear, lead, unpaid, dup, already], seen)
    assert [i.url for i in out] == ["https://good", "https://unclear", "https://lead"]
    assert out[0].extra["eligibility"] == "yes" and out[1].extra["eligibility"] == "unclear"


def test_keywords_match_whole_words_in_title(cfg, tmp_path):
    seen = SeenStore(tmp_path / "s.json")
    maintain = Item("X", "Maintenance Technician", "https://m", location="Worldwide")   # contains "ai" inside a word
    agent = Item("X", "Customer Support Agent", "https://a", location="Worldwide")
    chatbot = Item("X", "Chatbot Builder (GPT)", "https://c", location="Anywhere")
    assert [i.url for i in pipeline.prefilter(cfg, [maintain, agent, chatbot], seen)] == ["https://c"]


@pytest.mark.parametrize("location,description,expected", [
    ("Worldwide", "", "yes"),
    ("Anywhere in the World", "", "yes"),
    ("EMEA", "", "yes"),
    ("Africa", "", "yes"),
    ("Lagos, Nigeria", "", "yes"),
    ("USA Only", "", "no"),
    ("Europe", "", "no"),
    ("United States, Canada", "", "no"),
    ("", "REMOTE (US only) | Python", "no"),
    ("Remote", "Candidates must reside in the United States", "no"),
    ("Remote", "We hire from anywhere in the world", "yes"),
    ("Remote", "We are a global company", "unclear"),
    ("", "", "unclear"),
    ("Worldwide", "You must be legally able to work in the UK", "no"),
])
def test_nigeria_eligibility(location, description, expected):
    from jobkeeper.eligibility import nigeria_eligibility
    assert nigeria_eligibility(Item("X", "AI Automation Specialist", "https://x", location=location,
                                    description=description))[0] == expected


@pytest.mark.parametrize("title,description,ok", [
    ("Junior Automation Developer", "", True),
    ("AI Automation Intern", "", True),
    ("Automation Specialist", "1-2 years of experience", True),
    ("Senior Automation Engineer", "", False),
    ("Sr. n8n Developer", "", False),
    ("Automation Lead", "", False),
    ("Head of AI", "", False),
    ("Automation Engineer II", "", False),
    ("Automation Specialist", "5+ years of experience", False),
    ("Automation Specialist", "3-5 years of relevant experience", False),
    ("Automation Specialist", "2+ years experience with Make", True),
    ("Automation Specialist", "10 years of hands-on experience", False),
])
def test_seniority(title, description, ok):
    from jobkeeper.eligibility import seniority
    assert seniority(Item("X", title, "https://x", description=description))[0] is ok


def test_seen_store_roundtrip(tmp_path):
    s = SeenStore(tmp_path / "s.json")
    s.add("abc")
    s.save()
    assert "abc" in SeenStore(tmp_path / "s.json")


def test_format_item_escapes_html():
    item = Item("Reddit <r/x>", "Need <site> & shop", "https://a.com/?a=1&b=2", kind="lead", score=88,
                reason="Fits", pitch="Hi there", posted_at=NOW)
    msg = format_item(item)
    assert "&lt;site&gt; &amp; shop" in msg and 'href="https://a.com/?a=1&amp;b=2"' in msg
    assert "LEAD" in msg and "88/100" in msg


def test_run_end_to_end(cfg, monkeypatch, tmp_path):
    """Full run with sources, AI and Telegram stubbed out."""
    items = [Item("X", "AI Automation Specialist", f"https://job/{n}", location="Worldwide", posted_at=NOW) for n in range(4)]
    monkeypatch.setattr(pipeline, "collect", lambda c, h: items)
    monkeypatch.setattr(pipeline, "SeenStore", lambda: SeenStore(tmp_path / "seen.json"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")

    def fake_score(c, batch):
        for n, i in enumerate(batch):
            i.score = [90, 80, 70, 10][n]
        return batch
    monkeypatch.setattr(pipeline.ai, "score_items", fake_score)

    sent = []
    class FakeTG:
        def send(self, text): sent.append(text)
    monkeypatch.setattr(pipeline, "Telegram", FakeTG)
    cfg["telegram"]["max_messages_per_run"] = 2

    result = pipeline.run(cfg)
    assert [i.score for i in result] == [90, 80]
    assert len(sent) == 3 and "1 more queued" in sent[0]
    store = SeenStore(tmp_path / "seen.json")
    assert items[0].id in store and items[3].id in store   # sent + rejected
    assert items[2].id not in store                       # overflow retried next run


def _mock_anthropic(monkeypatch, reply_text, captured):
    import anthropic
    import httpx2
    from jobkeeper import ai
    from jobkeeper.sources import websearch

    def handler(request):
        captured.append((dict(request.headers), json.loads(request.content)))
        body = {"id": "m", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
                "content": [{"type": "text", "text": reply_text}], "stop_reason": "end_turn",
                "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}}
        if captured[-1][1].get("stream"):
            ev = [("message_start", {"type": "message_start", "message": {**body, "content": [], "stop_reason": None}}),
                  ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
                  ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": reply_text}}),
                  ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                  ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 1}}),
                  ("message_stop", {"type": "message_stop"})]
            sse = "".join(f"event: {e}\ndata: {json.dumps(d)}\n\n" for e, d in ev)
            return httpx2.Response(200, content=sse.encode(), headers={"content-type": "text/event-stream"})
        return httpx2.Response(200, json=body)

    real = anthropic.Anthropic
    factory = lambda: real(api_key="test", http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
    monkeypatch.setattr(ai.anthropic, "Anthropic", factory)
    monkeypatch.setattr(websearch.anthropic, "Anthropic", factory)


def test_ai_scoring_request(cfg, monkeypatch):
    from jobkeeper import ai
    item = Item("X", "React developer", "https://job/1")
    captured = []
    other = Item("X", "n8n developer", "https://job/2")
    reply = {"results": [
        {"id": item.id, "score": 150, "eligible": "yes", "eligibility_reason": "Worldwide", "reason": "r",
         "requirements": "Have: n8n · Gap: none", "pitch": ""},
        {"id": other.id, "score": 90, "eligible": "no", "eligibility_reason": "US only", "reason": "r",
         "requirements": "", "pitch": ""},
    ]}
    _mock_anthropic(monkeypatch, json.dumps(reply), captured)
    scored = ai.score_items(cfg, [item, other])
    assert scored[0].score == 100 and scored[0].extra["requirements"].startswith("Have")
    assert scored[1].score == 0
    headers, body = captured[0]
    assert body["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in headers["anthropic-beta"]
    assert body["output_config"]["format"]["type"] == "json_schema"


def test_websearch_request(cfg, monkeypatch):
    from jobkeeper.sources import websearch
    captured = []
    _mock_anthropic(monkeypatch, '[{"kind":"lead","title":"Bakery needs site","url":"https://instagram.com/p/1"}]', captured)
    items = websearch.fetch(cfg, None)
    assert items[0].kind == "lead" and items[0].source == "Web search"
    assert captured[0][1]["tools"][0]["type"] == "web_search_20260209"


def test_reddit_one_blocked_feed_does_not_drop_the_rest(cfg, monkeypatch):
    monkeypatch.setattr(reddit.time, "sleep", lambda s: None)
    cfg["sources"]["reddit"] = {"job_subreddits": ["blocked", "forhire"], "lead_searches": [{"sub": "x", "query": "q"}]}
    http = mock_http({"https://www.reddit.com/r/forhire": RSS})  # everything else 404s
    assert len(reddit.fetch(cfg, http)) == 1


def test_run_without_ai_sends_only_confirmed_eligible(cfg, monkeypatch, tmp_path):
    items = [Item("X", "AI Automation Specialist", f"https://job/{n}", location=loc, posted_at=NOW)
             for n, loc in enumerate(["Worldwide", "Africa", "Remote"])]
    monkeypatch.setattr(pipeline, "collect", lambda c, h: items)
    monkeypatch.setattr(pipeline, "SeenStore", lambda: SeenStore(tmp_path / "seen.json"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    sent = []
    monkeypatch.setattr(pipeline, "Telegram", lambda: type("T", (), {"send": lambda self, t: sent.append(t)})())
    assert [i.location for i in pipeline.run(cfg)] == ["Worldwide", "Africa"]
    assert "Open to Nigeria" in sent[1]
    assert items[2].id not in SeenStore(tmp_path / "seen.json")   # "unclear" waits for the AI
