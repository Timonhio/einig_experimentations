"""Tests for U6 – place card in three pages (specs/u6-place-card-pages.md, D29).

Page 1: map image, round photo, name, kind, rating, chips, short address, the one Google Maps button.
Page 2: photos with their authors and the opening hours of the week.
Page 3: up to three reviews, each cut to four lines by CSS.

Tapping and swiping run in the browser and are checked by hand on a phone. These tests check
what the server sends, the map route, and what the CSS and script files contain.
Google is never called: `requests.get` is replaced by a fake.
"""

import html as html_lib
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import pytest
from itsdangerous import URLSafeSerializer

from app.db import get_db
from app.services import places
from app.services.places import BACK_FIELD_MASK, CARD_FIELD_MASK

PROJECT_ROOT = Path(__file__).parent.parent
SWIPE_JS = PROJECT_ROOT / "app" / "static" / "js" / "swipe.js"
APP_CSS = PROJECT_ROOT / "app" / "static" / "css" / "app.css"
FAKE_KEY = "fake-key-for-tests-0123456789"
DETAILS_URL = "https://places.googleapis.com/v1/places/"
STATIC_MAP_URL = "https://maps.googleapis.com/maps/api/staticmap"
# The A10 test (tests/test_swipe_rating.py) pins this text and the place_page_url link;
# U6 shows it as the one Google Maps button on page 1 (see the spec, "Decisions for Timo").
MAPS_BUTTON_TEXT = "Menu & reviews on Google Maps"
READ_TEXT = "Read on Google Maps"
REVIEWS_LINE = "Reviews selected by Google"
NO_HOURS_TEXT = "No opening hours on Google."
NO_PHOTOS_TEXT = "No photos on Google."
NO_REVIEWS_TEXT = "No reviews on Google."
DETAILS_MISSING = "Details are not available right now."
ADDRESS = "Rua Augusta 1, Lisboa"
WEEK = [
    "Monday: 12:00 – 23:00",
    "Tuesday: 12:00 – 23:00",
    "Wednesday: 12:00 – 23:00",
    "Thursday: 12:00 – 23:00",
    "Friday: 12:00 – 23:00",
    "Saturday: 12:00 – 23:00",
    "Sunday: 12:00 – 23:00",
]
PAGE_TITLES = ["Where", "Photos and hours", "Reviews"]
# A Monday, 10:00 UTC (2026-11-30).
MONDAY_MORNING = datetime(2026, 11, 30, 10, 0, tzinfo=timezone.utc)


# --- Fake Google -----------------------------------------------------------

class FakeResponse:
    def __init__(self, status_code=200, body=None, content=b"", content_type="application/json"):
        self.status_code = status_code
        self.body = {} if body is None else body
        self.content = content
        self.headers = {"Content-Type": content_type}
        self.text = str(self.body)

    def json(self):
        return self.body


class FakeGet:
    """Replaces requests.get: answers by URL, records every call with its arguments."""

    def __init__(self):
        self.responses = {}
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self.responses.get(url, FakeResponse(status_code=404, body={"error": {}}))

    def detail_masks(self):
        return [
            call["headers"]["X-Goog-FieldMask"]
            for call in self.calls
            if call["url"].startswith(DETAILS_URL) and not call["url"].endswith("/media")
        ]

    def map_calls(self):
        return [call for call in self.calls if call["url"] == STATIC_MAP_URL]


def photo(place_id, number, author="Maria Silva"):
    return {
        "name": f"places/{place_id}/photos/ref-{number}",
        "authorAttributions": [{"displayName": author, "uri": "https://maps.google.com/maria"}],
    }


def review(number, **changes):
    body = {
        "relativePublishTimeDescription": f"{number} weeks ago",
        "rating": 4,
        "text": {"text": f"Review text {number}", "languageCode": "en"},
        "authorAttribution": {
            "displayName": f"Author {number}",
            "uri": f"https://www.google.com/maps/contrib/{number}",
            "photoUri": f"https://lh3.googleusercontent.com/a/{number}",
        },
        "googleMapsUri": f"https://www.google.com/maps/reviews/{number}",
    }
    body.update(changes)
    return body


def every_day(open_hour=12, close_hour=23):
    """Periods for all seven days (Google: 0 = Sunday), so 'today' is the same on any day."""
    return [
        {"open": {"day": day, "hour": open_hour, "minute": 0}, "close": {"day": day, "hour": close_hour, "minute": 0}}
        for day in range(7)
    ]


def full_answer(place_id="place-a", name="Pizza Roma"):
    """What Google sends for BACK_FIELD_MASK, with every field."""
    return {
        "displayName": {"text": name, "languageCode": "en"},
        "rating": 4.5,
        "userRatingCount": 1234,
        "priceLevel": "PRICE_LEVEL_MODERATE",
        "location": {"latitude": 38.74, "longitude": -9.153},
        "primaryTypeDisplayName": {"text": "Italian Restaurant", "languageCode": "en"},
        "photos": [photo(place_id, number) for number in range(1, 6)],
        "reviews": [review(1), review(2), review(3), review(4)],
        "shortFormattedAddress": ADDRESS,
        "currentOpeningHours": {"openNow": True, "periods": every_day(), "weekdayDescriptions": list(WEEK)},
        "utcOffsetMinutes": 0,
    }


def static_map_image():
    return FakeResponse(content=b"\x89PNG-fake-map", content_type="image/png")


@pytest.fixture(autouse=True)
def google(app, monkeypatch):
    app.config["GOOGLE_MAPS_API_KEY"] = FAKE_KEY
    fake = FakeGet()
    fake.responses[DETAILS_URL + "place-a"] = FakeResponse(body=full_answer())
    fake.responses[STATIC_MAP_URL] = static_map_image()
    monkeypatch.setattr(places.requests, "get", fake)
    return fake


# --- Reading the HTML --------------------------------------------------------

class ElementFinder(HTMLParser):
    """Collects the inner HTML of every element that has a given attribute."""

    VOID = {"input", "img", "br", "meta", "link", "hr", "source"}

    def __init__(self, attribute):
        super().__init__(convert_charrefs=False)
        self.attribute = attribute
        self.found = []
        self.open = []
        self.depth = 0

    def handle_starttag(self, tag, attrs):
        text = self.get_starttag_text()
        for element in self.open:
            element[2].append(text)
        if tag in self.VOID:
            return
        self.depth += 1
        if self.attribute in dict(attrs):
            self.open.append([tag, dict(attrs), [], self.depth])

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        for element in list(self.open):
            if element[3] == self.depth:
                self.found.append((element[1], "".join(element[2])))
                self.open.remove(element)
        for element in self.open:
            element[2].append(f"</{tag}>")
        self.depth -= 1

    def handle_data(self, data):
        for element in self.open:
            element[2].append(data)

    def handle_entityref(self, name):
        self.handle_data(f"&{name};")

    def handle_charref(self, name):
        self.handle_data(f"&#{name};")


class TagCollector(HTMLParser):
    """Collects the attributes of every start tag with a given name (also void tags like img)."""

    def __init__(self, tag):
        super().__init__(convert_charrefs=False)
        self.tag = tag
        self.found = []

    def handle_starttag(self, tag, attrs):
        if tag == self.tag:
            self.found.append({name: value for name, value in attrs})


def elements_with(page_html, attribute):
    finder = ElementFinder(attribute)
    finder.feed(page_html)
    return finder.found


def tags(fragment, tag):
    collector = TagCollector(tag)
    collector.feed(fragment)
    return collector.found


def links_in(fragment):
    """(href, target, rel, text) of every link in the fragment."""
    return [
        (html_lib.unescape(attributes["href"]), attributes.get("target"), attributes.get("rel"),
         html_lib.unescape(re.sub(r"<[^>]+>", "", inner)).strip())
        for attributes, inner in elements_with(fragment, "href")
    ]


def maps_buttons(fragment):
    return [href for href, _, _, text in links_in(fragment) if text == MAPS_BUTTON_TEXT]


def text_of(fragment):
    """The visible text of a fragment, tags removed, spaces collapsed."""
    return " ".join(html_lib.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def card_of(html):
    return elements_with(html, "data-swipe-card")[0][1]


def pages_of(html):
    """[(attributes, inner html)] of the three pages, in page order."""
    return elements_with(card_of(html), "data-card-page")


def page_html(html, number):
    return pages_of(html)[number - 1][1]


def chips_of(html):
    """{chip name: (class, text)} of the chips on page 1."""
    return {
        attributes["data-chip"]: (attributes.get("class", ""), text_of(inner))
        for attributes, inner in elements_with(page_html(html, 1), "data-chip")
    }


def css_rules():
    """[(selector, body)] of the CSS file, comments removed (also inside @media blocks)."""
    text = re.sub(r"/\*.*?\*/", "", APP_CSS.read_text(), flags=re.S)
    return [(selector.strip(), rule.strip()) for selector, rule in re.findall(r"([^{}]+)\{([^{}]*)\}", text)]


def map_token_of(html):
    sources = [item["src"] for item in tags(page_html(html, 1), "img") if item.get("src", "").startswith("/map/")]
    assert len(sources) == 1
    return sources[0][len("/map/"):]


# --- Helpers ---------------------------------------------------------------

def create_room(client, nickname="Anna"):
    response = client.post("/rooms", data={"title": "Dinner", "mode": "nearby", "nickname": nickname})
    assert response.status_code in (302, 303)
    return response.headers["Location"].rsplit("/rooms/", 1)[1]


def add_options(app, room_id, place_ids=(), labels=()):
    """Store options directly and return {place id or label: option id}."""
    with app.app_context():
        connection = get_db()
        for place_id in place_ids:
            connection.execute(
                "INSERT INTO options (room_id, source, place_id, category) VALUES (?, 'google', ?, 'restaurant')",
                (room_id, place_id),
            )
        for label in labels:
            connection.execute(
                "INSERT INTO options (room_id, source, label) VALUES (?, 'manual', ?)", (room_id, label)
            )
        connection.commit()
        rows = connection.execute("SELECT id, place_id, label FROM options WHERE room_id = ?", (room_id,))
        return {row["place_id"] or row["label"]: row["id"] for row in rows}


def set_status(app, room_id, status):
    with app.app_context():
        connection = get_db()
        connection.execute("UPDATE rooms SET status = ? WHERE id = ?", (status, room_id))
        connection.commit()


def set_centre(app, room_id, latitude, longitude):
    with app.app_context():
        connection = get_db()
        connection.execute(
            "UPDATE rooms SET search_center_lat = ?, search_center_lng = ? WHERE id = ?",
            (latitude, longitude, room_id),
        )
        connection.commit()


def page(client, path):
    response = client.get(path)
    assert response.status_code == 200
    return response.data.decode()


def voting_room(app, client, place_ids=("place-a",), labels=()):
    room_id = create_room(client)
    ids = add_options(app, room_id, place_ids, labels)
    set_status(app, room_id, "voting")
    return room_id, ids


def rating_page(app, client, place_ids=("place-a",), labels=()):
    room_id, ids = voting_room(app, client, place_ids=place_ids, labels=labels)
    return page(client, f"/rooms/{room_id}/vote"), room_id, ids


def answer_with(google, **changes):
    """Let Google send the full answer with some fields changed (None removes a field)."""
    body = full_answer()
    for field, value in changes.items():
        if value is None:
            body.pop(field, None)
        else:
            body[field] = value
    google.responses[DETAILS_URL + "place-a"] = FakeResponse(body=body)


def database_snapshot(app):
    with app.app_context():
        connection = get_db()
        names = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        return {name: [tuple(row) for row in connection.execute(f"SELECT * FROM {name}")] for name in sorted(names)}


def signed_token(secret, place_id="place-a", latitude=38.74, longitude=-9.153):
    """A map token as the app makes it: place id, latitude, longitude, signed with SECRET_KEY."""
    return places.map_token(secret, place_id, latitude, longitude)


# --- Three pages, no flip ----------------------------------------------------------

def test_the_card_has_three_pages_and_no_flip(app, client):
    html, room_id, ids = rating_page(app, client)
    option_id = ids["place-a"]
    pages = pages_of(html)
    assert [attributes["data-card-page"] for attributes, _ in pages] == ["1", "2", "3"]
    assert [attributes["id"] for attributes, _ in pages] == [f"card-page-{option_id}-{n}" for n in (1, 2, 3)]
    # The card no longer turns over: no checkbox, no labels, no back.
    assert "data-flip-toggle" not in html and 'type="checkbox"' not in card_of(html)
    assert "data-flip-open" not in html and "data-flip-close" not in html
    assert "More about this place" not in html and "Back to the card" not in html
    assert "data-card-back" not in html and "data-card-dot" not in html


def test_every_page_is_inside_the_one_swipe_area_and_has_no_rating_buttons(app, client):
    html, room_id, ids = rating_page(app, client)
    areas = elements_with(html, "data-swipe-area")
    assert len(areas) == 1
    area_html = areas[0][1]
    assert len(elements_with(area_html, "data-card-page")) == 3
    assert 'name="rating"' not in area_html and "<form" not in area_html


def test_parts_of_the_card_come_in_order_bars_pages_rating_form_joker_form(app, client):
    html, room_id, ids = rating_page(app, client)
    card = card_of(html)
    order = [
        card.index("data-card-bar"),
        card.index('data-card-page="1"'),
        card.index('data-card-page="2"'),
        card.index('data-card-page="3"'),
        card.index('name="rating"'),
        card.index(f'action="/rooms/{room_id}/veto"'),
    ]
    assert order == sorted(order)


def test_rating_and_joker_buttons_sit_in_the_card_but_on_no_page(app, client):
    html, room_id, ids = rating_page(app, client)
    for value in ("yes", "ok", "no"):
        assert f'name="rating" value="{value}"' in card_of(html)
    for _, inner in pages_of(html):
        assert 'name="rating"' not in inner and "<form" not in inner


def test_the_joker_question_is_in_the_card_but_not_in_the_swipe_area_or_on_a_page(app, client):
    html, room_id, ids = rating_page(app, client)
    assert "data-joker-question" in card_of(html)
    assert "data-joker-question" not in elements_with(html, "data-swipe-area")[0][1]
    for _, inner in pages_of(html):
        assert "data-joker-question" not in inner


def test_only_the_next_card_gets_pages_and_one_details_call(app, client, google):
    google.responses[DETAILS_URL + "place-b"] = FakeResponse(body=full_answer("place-b", "Taco Bar"))
    html, room_id, ids = rating_page(app, client, place_ids=("place-a", "place-b"))
    assert len(pages_of(html)) == 3
    assert len(elements_with(html, "data-card-pages")) == 1
    assert google.detail_masks() == [BACK_FIELD_MASK]


def test_a_manual_option_and_a_failed_google_option_get_no_pages(app, client, google):
    html, room_id, ids = rating_page(app, client, place_ids=(), labels=("Burger Bar",))
    assert "data-card-page" not in html and "data-card-bar" not in html and "/map/" not in html
    assert len(elements_with(html, "data-swipe-area")) == 1

    google.responses[DETAILS_URL + "place-a"] = FakeResponse(status_code=500, body={})
    other = app.test_client()
    html, room_id, ids = rating_page(app, other)
    assert DETAILS_MISSING in html
    assert "data-card-page" not in html and "data-card-bar" not in html and "/map/" not in html


# --- Page 1: where and how good ------------------------------------------------------

def test_page_one_has_the_map_image_from_our_own_route(app, client):
    html, room_id, ids = rating_page(app, client)
    first = page_html(html, 1)
    maps = [item for item in tags(first, "img") if item.get("src", "").startswith("/map/")]
    assert len(maps) == 1
    assert "googleapis" not in first and "maps.google" not in maps[0]["src"]
    assert maps[0].get("alt") == "Map of Pizza Roma"
    # The map sits in a box that keeps a calm background when the image is missing.
    assert len(elements_with(first, "data-card-map")) == 1
    assert "/map/" in elements_with(first, "data-card-map")[0][1]


def test_page_one_has_round_photo_name_and_kind_in_order(app, client):
    html, room_id, ids = rating_page(app, client)
    first = page_html(html, 1)
    photos = [item for item in tags(first, "img") if item.get("src", "").startswith("/photo/")]
    assert [item["src"] for item in photos] == ["/photo/places/place-a/photos/ref-1"]
    assert "place-avatar" in photos[0].get("class", "").split()
    text = text_of(first)
    assert "Pizza Roma" in text and "Italian Restaurant" in text
    assert first.index("/map/") < first.index("/photo/") < first.index("<h3") < first.index("Italian Restaurant")


def test_page_one_shows_the_rating_with_stars_and_the_review_count(app, client):
    html, room_id, ids = rating_page(app, client)
    first = page_html(html, 1)
    text = text_of(first)
    assert "★ 4.5" in text
    assert "1,234 reviews" in text
    stars = [attributes for attributes, _ in elements_with(first, "data-stars")]
    assert len(stars) == 1
    assert stars[0].get("aria-hidden") == "true"
    assert "90%" in stars[0]["style"]  # 4.5 of 5 stars filled by CSS


def test_one_review_is_counted_in_the_singular_and_no_rating_means_no_stars(app, client, google):
    answer_with(google, userRatingCount=1)
    html, room_id, ids = rating_page(app, client)
    assert "1 review" in text_of(page_html(html, 1)) and "1 reviews" not in text_of(page_html(html, 1))

    answer_with(google, rating=None, userRatingCount=None)
    html, room_id, ids = rating_page(app, app.test_client())
    first = page_html(html, 1)
    assert "★" not in text_of(first) and "data-stars" not in first


def test_page_one_shows_distance_price_and_todays_hours_as_chips(app, client, google):
    room_id, ids = voting_room(app, client)
    set_centre(app, room_id, 38.73, -9.15)
    html = page(client, f"/rooms/{room_id}/vote")
    chips = chips_of(html)
    assert list(chips) == ["distance", "price", "hours"]
    expected_distance = places.format_distance(places.distance_m(38.73, -9.15, 38.74, -9.153))
    assert chips["distance"][1] == expected_distance
    assert chips["price"][1] == "€€"
    assert chips["hours"][1] == "Open today until 23:00"
    assert "chip-open" in chips["hours"][0].split()


def test_closed_today_is_a_red_chip(app, client, google):
    closed_week = [line.split(":")[0] + ": Closed" for line in WEEK]
    answer_with(google, currentOpeningHours={"openNow": False, "periods": [], "weekdayDescriptions": closed_week})
    html, room_id, ids = rating_page(app, client)
    chips = chips_of(html)
    assert chips["hours"][1] == "Closed today"
    assert "chip-closed" in chips["hours"][0].split()


def test_chips_only_for_facts_google_sent(app, client, google):
    # No centre (so no distance), no price level, no opening hours.
    answer_with(google, priceLevel=None, currentOpeningHours=None)
    html, room_id, ids = rating_page(app, client)
    assert chips_of(html) == {}
    assert "data-card-chips" not in page_html(html, 1)


def test_page_one_shows_the_short_address(app, client):
    html, room_id, ids = rating_page(app, client)
    assert ADDRESS in text_of(page_html(html, 1))


def test_without_a_location_there_is_no_map_image_but_the_address_stays(app, client, google):
    answer_with(google, location=None)
    html, room_id, ids = rating_page(app, client)
    first = page_html(html, 1)
    assert "/map/" not in first
    assert ADDRESS in text_of(first)


def test_the_google_maps_button_is_on_page_one_only_and_only_once(app, client):
    html, room_id, ids = rating_page(app, client)
    expected = places.place_page_url("place-a", "Pizza Roma")
    assert maps_buttons(html) == [expected]
    assert maps_buttons(page_html(html, 1)) == [expected]
    link = [item for item in links_in(page_html(html, 1)) if item[3] == MAPS_BUTTON_TEXT][0]
    assert link[1:3] == ("_blank", "noopener noreferrer")
    assert maps_buttons(page_html(html, 2)) == [] and maps_buttons(page_html(html, 3)) == []


# --- Page 2: how it looks and when it is open ----------------------------------------------

def test_page_two_has_one_big_photo_and_up_to_three_small_ones_with_authors(app, client):
    html, room_id, ids = rating_page(app, client)
    second = page_html(html, 2)
    sources = [item["src"] for item in tags(second, "img")]
    assert sources == [f"/photo/places/place-a/photos/ref-{number}" for number in (1, 2, 3, 4)]
    images = tags(second, "img")
    assert "photo-big" in images[0].get("class", "").split()
    assert all("photo-small" in item.get("class", "").split() for item in images[1:])
    assert all(item.get("loading") == "lazy" for item in images)
    authors = [link for link in links_in(second) if link[3] == "Maria Silva"]
    assert len(authors) == 4
    assert all(link[0] == "https://maps.google.com/maria" and link[1:3] == ("_blank", "noopener noreferrer") for link in authors)


def test_page_two_shows_the_opening_hours_of_the_week_with_today_highlighted(app, client):
    html, room_id, ids = rating_page(app, client)
    second = page_html(html, 2)
    items = elements_with(second, "data-hours-day")
    assert [text_of(inner) for _, inner in items] == WEEK
    today = [attributes for attributes, _ in items if attributes.get("aria-current") == "date"]
    assert len(today) == 1
    assert "today" in today[0].get("class", "").split()
    # Monday is index 0 in Google's list; Python's weekday() counts the same way.
    expected = WEEK[datetime.now(timezone.utc).weekday()]
    assert [text_of(inner) for attributes, inner in items if attributes.get("aria-current") == "date"] == [expected]


def test_without_hours_page_two_says_so(app, client, google):
    answer_with(google, currentOpeningHours=None)
    html, room_id, ids = rating_page(app, client)
    assert NO_HOURS_TEXT in text_of(page_html(html, 2))
    assert "data-hours-day" not in page_html(html, 2)


def test_without_any_photo_page_two_says_so_and_still_shows_hours(app, client, google):
    answer_with(google, photos=None)
    html, room_id, ids = rating_page(app, client)
    second = page_html(html, 2)
    assert NO_PHOTOS_TEXT in text_of(second)
    assert len(elements_with(second, "data-hours-day")) == 7


# --- Page 3: what others say ----------------------------------------------------------------

def test_page_three_has_three_reviews_with_every_part_unchanged(app, client):
    html, room_id, ids = rating_page(app, client)
    third = page_html(html, 3)
    text = text_of(third)
    assert REVIEWS_LINE in text
    for number in (1, 2, 3):
        assert f"Review text {number}" in text
        assert f"{number} weeks ago" in text
        assert f"Author {number}" in text
    assert "Review text 4" not in text
    links = links_in(third)
    for number in (1, 2, 3):
        assert (f"https://www.google.com/maps/contrib/{number}", "_blank", "noopener noreferrer", f"Author {number}") in links
        assert (f"https://www.google.com/maps/reviews/{number}", "_blank", "noopener noreferrer", READ_TEXT) in links
    pictures = [item for item in tags(third, "img") if "googleusercontent" in item.get("src", "")]
    assert [item["src"] for item in pictures] == [f"https://lh3.googleusercontent.com/a/{n}" for n in (1, 2, 3)]
    for item in pictures:
        assert item["alt"] == "" and item["loading"] == "lazy" and item["referrerpolicy"] == "no-referrer"
    assert maps_buttons(third) == []


def test_each_review_text_is_marked_for_the_four_line_cut_and_kept_whole(app, client, google):
    long_text = "Very long review. " * 60
    answer_with(google, reviews=[review(1, text={"text": long_text})])
    html, room_id, ids = rating_page(app, client)
    texts = [inner for attributes, inner in elements_with(page_html(html, 3), "class")
             if "review-text" in attributes["class"].split()]
    assert len(texts) == 1
    assert html_lib.unescape(texts[0]).strip() == long_text.strip()  # the server never shortens it


def test_the_css_cuts_review_texts_to_four_lines():
    rules = [rule for selector, rule in css_rules() if ".review-text" in selector]
    joined = " ".join(rules)
    assert "line-clamp: 4" in joined
    assert "overflow: hidden" in joined


def test_without_reviews_page_three_says_so(app, client, google):
    answer_with(google, reviews=None)
    html, room_id, ids = rating_page(app, client)
    assert NO_REVIEWS_TEXT in text_of(page_html(html, 3))
    assert READ_TEXT not in text_of(page_html(html, 3))


def test_description_and_offers_are_no_longer_shown(app, client, google):
    answer_with(google, editorialSummary={"text": "Wood-fired pizza near the river."}, servesDinner=True)
    html, room_id, ids = rating_page(app, client)
    assert "Wood-fired" not in html and "Dinner ·" not in html


# --- Moving between pages -------------------------------------------------------------------

def test_three_bars_at_the_top_link_to_the_three_pages(app, client):
    html, room_id, ids = rating_page(app, client)
    option_id = ids["place-a"]
    bars = elements_with(card_of(html), "data-card-bar")
    assert len(bars) == 3
    for (attributes, _), number, title in zip(bars, (1, 2, 3), PAGE_TITLES):
        assert attributes["href"] == f"#card-page-{option_id}-{number}"
        assert attributes["aria-label"] == f"Page {number} of 3: {title}"
    assert bars[0][0].get("aria-current") == "true"
    assert all("aria-current" not in attributes for attributes, _ in bars[1:])
    # The bars come before the first page.
    card = card_of(html)
    assert card.index("data-card-bar") < card.index("data-card-page")


def test_without_javascript_css_shows_the_targeted_page_and_page_one_by_default():
    rules = css_rules()
    selectors = [selector for selector, _ in rules]
    assert any(":target" in selector and "card-page" in selector for selector in selectors)
    assert any(":first-child" in selector and "card-page" in selector for selector in selectors)
    # The pages are hidden by default (display: none) and one is shown.
    hidden = [selector for selector, rule in rules if "card-page" in selector and "display: none" in rule]
    assert hidden
    # Once swipe.js runs, it shows the page itself (class pages-ready on the pages).
    assert any("pages-ready" in selector for selector in selectors)


def test_swipe_js_changes_the_page_on_a_tap_left_or_right_and_leaves_links_alone():
    source = SWIPE_JS.read_text()
    assert "var TAP_DISTANCE = 10;" in source
    assert "getBoundingClientRect" in source and "width / 2" in source
    assert "[data-card-page]" in source and "[data-card-bar]" in source
    assert "aria-current" in source
    assert "pages-ready" in source and "is-current" in source
    assert "preventDefault" in source  # a bar click changes the page without jumping
    assert 'closest("a")' in source
    # The card no longer flips.
    assert "flip" not in source.lower()
    assert "[data-card-back]" not in source and "[data-card-dot]" not in source


def test_swipe_js_still_rates_on_every_page_and_passes_the_a10_static_check():
    source = SWIPE_JS.read_text()
    assert "var SWIPE_DISTANCE = 110;" in source
    assert "buttons[choice].click()" in source
    assert "question.hidden = false;" in source
    for forbidden in ("fetch(", "XMLHttpRequest", "import ", "http"):
        assert forbidden not in source


# --- Escaping and the key -----------------------------------------------------------------

def test_text_from_google_is_escaped_on_every_page(app, client, google):
    answer_with(
        google,
        displayName={"text": "<b>Bold</b> Pizza"},
        shortFormattedAddress="<script>alert(1)</script>",
        currentOpeningHours={"periods": every_day(), "weekdayDescriptions": ["<i>Monday</i>"] + WEEK[1:]},
        reviews=[review(1, text={"text": "<b>Great</b> & cheap"},
                        authorAttribution={"displayName": "<i>Eve</i>", "uri": "https://www.google.com/maps/contrib/1"})],
    )
    html, room_id, ids = rating_page(app, client)
    for raw in ("<b>Bold</b>", "<script>alert(1)</script>", "<i>Monday</i>", "<b>Great</b>", "<i>Eve</i>"):
        assert raw not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page_html(html, 1)
    assert "&lt;i&gt;Monday&lt;/i&gt;" in page_html(html, 2)
    assert "&lt;b&gt;Great&lt;/b&gt; &amp; cheap" in page_html(html, 3)


def test_the_api_key_never_appears_in_the_rating_page(app, client):
    html, room_id, ids = rating_page(app, client)
    assert FAKE_KEY not in html
    assert "key=" not in html
    assert "googleapis" not in html


# --- Google fields ---------------------------------------------------------------------------

def test_back_field_mask_adds_hours_address_and_time_zone_and_drops_description_and_offers():
    # The two smaller masks are unchanged (C10).
    assert places.DETAILS_FIELD_MASK == "displayName,rating,priceLevel,location,photos"
    assert CARD_FIELD_MASK == places.DETAILS_FIELD_MASK + ",userRatingCount,primaryTypeDisplayName"
    assert "*" not in places.DETAILS_FIELD_MASK and "*" not in CARD_FIELD_MASK
    assert BACK_FIELD_MASK == CARD_FIELD_MASK + ",reviews,currentOpeningHours,shortFormattedAddress,utcOffsetMinutes"
    for dropped in ("editorialSummary", "servesDinner", "servesWine", "goodForGroups", "outdoorSeating", "reservable"):
        assert dropped not in BACK_FIELD_MASK
    assert "*" not in BACK_FIELD_MASK
    assert "location" in BACK_FIELD_MASK


def test_the_back_has_reviews_photos_address_and_hours_and_no_description_or_offers(google):
    body = full_answer()
    body.update({"editorialSummary": {"text": "Wood-fired pizza."}, "servesDinner": True})
    google.responses[DETAILS_URL + "place-a"] = FakeResponse(body=body)
    back = places.get_place_details(FAKE_KEY, "place-a", BACK_FIELD_MASK)["back"]
    assert set(back) == {"reviews", "photos", "address", "opening_hours"}
    assert back["address"] == ADDRESS
    assert back["opening_hours"]["weekday_descriptions"] == WEEK
    assert back["opening_hours"]["utc_offset_minutes"] == 0
    assert len(back["opening_hours"]["periods"]) == 7


@pytest.mark.parametrize("hours", [None, "x", 5, [], {"periods": "x"}, {"weekdayDescriptions": [1, 2]}, {}])
def test_unusable_opening_hours_give_none_and_never_raise(google, hours):
    body = full_answer()
    body["currentOpeningHours"] = hours
    google.responses[DETAILS_URL + "place-a"] = FakeResponse(body=body)
    back = places.get_place_details(FAKE_KEY, "place-a", BACK_FIELD_MASK)["back"]
    assert back["opening_hours"] is None


@pytest.mark.parametrize("address", [None, 5, "", {"text": "x"}])
def test_an_unusable_address_gives_none(google, address):
    body = full_answer()
    body["shortFormattedAddress"] = address
    google.responses[DETAILS_URL + "place-a"] = FakeResponse(body=body)
    assert places.get_place_details(FAKE_KEY, "place-a", BACK_FIELD_MASK)["back"]["address"] is None


def test_other_pages_keep_the_card_mask(app, client, google):
    room_id, ids = voting_room(app, client)
    set_status(app, room_id, "collecting")
    google.calls.clear()
    page(client, f"/rooms/{room_id}")
    assert set(google.detail_masks()) == {CARD_FIELD_MASK}


# --- Today's hours, worked out on the server -------------------------------------------------

def hours_with(periods, offset=0):
    return {"weekday_descriptions": list(WEEK), "periods": periods, "utc_offset_minutes": offset}


def monday_only():
    """Open on Monday (Google day 1) from 12:00 to 22:30."""
    return [{"open_day": 1, "open_minutes": 12 * 60, "close_day": 1, "close_minutes": 22 * 60 + 30}]


def test_today_is_open_until_the_closing_time_of_todays_last_period():
    lunch_and_dinner = [
        {"open_day": 1, "open_minutes": 12 * 60, "close_day": 1, "close_minutes": 15 * 60},
        {"open_day": 1, "open_minutes": 19 * 60, "close_day": 1, "close_minutes": 23 * 60},
    ]
    view = places.opening_hours_view(hours_with(lunch_and_dinner), MONDAY_MORNING)
    assert view["today_text"] == "Open today until 23:00"
    assert view["open_today"] is True


def test_a_day_without_period_is_closed_today():
    tuesday = datetime(2026, 12, 1, 10, 0, tzinfo=timezone.utc)
    view = places.opening_hours_view(hours_with(monday_only()), tuesday)
    assert view["today_text"] == "Closed today"
    assert view["open_today"] is False
    assert [day["is_today"] for day in view["week"]] == [False, True, False, False, False, False, False]


def test_a_period_past_midnight_shows_its_closing_time():
    late = [{"open_day": 1, "open_minutes": 20 * 60, "close_day": 2, "close_minutes": 2 * 60}]
    assert places.opening_hours_view(hours_with(late), MONDAY_MORNING)["today_text"] == "Open today until 02:00"


def test_always_open_says_open_24_hours():
    always = [{"open_day": 0, "open_minutes": 0, "close_day": None, "close_minutes": None}]
    view = places.opening_hours_view(hours_with(always), MONDAY_MORNING)
    assert view["today_text"] == "Open 24 hours"
    assert view["open_today"] is True


def test_today_is_the_day_at_the_place_not_on_the_server():
    # 23:30 UTC on Sunday is already Monday in a place two hours ahead of UTC.
    sunday_night = datetime(2026, 11, 29, 23, 30, tzinfo=timezone.utc)
    view = places.opening_hours_view(hours_with(monday_only(), offset=120), sunday_night)
    assert view["today_text"] == "Open today until 22:30"
    assert view["week"][0]["is_today"] is True


def test_without_periods_but_with_week_lines_there_is_no_today_text():
    view = places.opening_hours_view({"weekday_descriptions": list(WEEK), "periods": None, "utc_offset_minutes": None}, MONDAY_MORNING)
    assert view["today_text"] is None
    assert [day["text"] for day in view["week"]] == WEEK


def test_no_opening_hours_give_no_view():
    assert places.opening_hours_view(None, MONDAY_MORNING) is None


# --- The map route ------------------------------------------------------------------------------

def test_the_map_token_is_signed_with_the_secret_key_by_itsdangerous(app, client):
    html, room_id, ids = rating_page(app, client)
    token = map_token_of(html)
    assert places.read_map_token(app.config["SECRET_KEY"], token) == ("place-a", 38.74, -9.153)
    assert places.read_map_token("another-secret", token) is None
    # itsdangerous, already part of Flask: the token is a URL-safe signed value.
    assert re.fullmatch(r"[A-Za-z0-9_\-.]+", token)


def test_the_map_route_loads_one_static_map_and_caches_it(app, client, google):
    html, room_id, ids = rating_page(app, client)
    google.calls.clear()
    response = client.get(f"/map/{map_token_of(html)}")
    assert response.status_code == 200
    assert response.data == b"\x89PNG-fake-map"
    assert response.content_type == "image/png"
    assert response.headers["Cache-Control"] == "private, max-age=600"
    calls = google.map_calls()
    assert len(calls) == 1
    params = calls[0]["params"]
    assert params["size"] == "600x300"
    assert str(params["scale"]) == "2"
    assert params["markers"].endswith("38.74,-9.153")
    assert params["markers"].count("38.74,-9.153") == 1
    assert params["key"] == FAKE_KEY
    assert calls[0]["timeout"] == 5
    assert FAKE_KEY not in response.data.decode("latin-1")


@pytest.mark.parametrize("token", ["", "garbage", "abc.def", "a" * 300])
def test_a_wrong_token_gives_404(app, client, google, token):
    rating_page(app, client)
    google.calls.clear()
    response = client.get(f"/map/{token}")
    assert response.status_code == 404
    assert google.map_calls() == []


def test_a_changed_or_foreign_token_gives_404(app, client, google):
    html, room_id, ids = rating_page(app, client)
    token = map_token_of(html)
    changed = token[:-1] + ("A" if token[-1] != "A" else "B")
    forged = URLSafeSerializer("not-our-secret").dumps(["place-a", 38.74, -9.153])
    google.calls.clear()
    assert client.get(f"/map/{changed}").status_code == 404
    assert client.get(f"/map/{forged}").status_code == 404
    assert google.map_calls() == []


def test_a_signed_token_with_bad_content_gives_404(app, client, google):
    rating_page(app, client)
    secret = app.config["SECRET_KEY"]
    serializer = URLSafeSerializer(secret, salt=places.MAP_TOKEN_SALT)
    for content in (["../x", 1, 2], ["place-a", 999, 0], ["place-a", "x", 0], "place-a", ["place-a", 1]):
        assert client.get(f"/map/{serializer.dumps(content)}").status_code == 404
    assert google.map_calls() == []


def test_the_map_route_answers_404_to_a_browser_not_in_a_room_with_that_place(app, client, google):
    html, room_id, ids = rating_page(app, client)
    token = map_token_of(html)
    secret = app.config["SECRET_KEY"]
    # A visitor who has not joined any room.
    assert app.test_client().get(f"/map/{token}").status_code == 404
    # A participant of another room without this place.
    other = app.test_client()
    other_room = create_room(other, "Ben")
    add_options(app, other_room, place_ids=["place-z"])
    assert other.get(f"/map/{token}").status_code == 404
    # A valid token, but for a place that is not in the joined room.
    assert client.get(f"/map/{signed_token(secret, 'place-q')}").status_code == 404
    assert google.map_calls() == []


def test_the_map_route_without_a_key_answers_503_and_calls_nobody(app, client, google):
    html, room_id, ids = rating_page(app, client)
    app.config["GOOGLE_MAPS_API_KEY"] = ""
    google.calls.clear()
    response = client.get(f"/map/{map_token_of(html)}")
    assert response.status_code == 503
    assert response.content_type.startswith("text/plain")
    assert response.data.decode() == "Map not available."
    assert google.calls == []


@pytest.mark.parametrize("google_answer", [
    FakeResponse(status_code=500),
    FakeResponse(status_code=403),
    FakeResponse(content=b"<html>", content_type="text/html"),
])
def test_the_map_route_answers_503_when_google_fails(app, client, google, google_answer):
    html, room_id, ids = rating_page(app, client)
    google.responses[STATIC_MAP_URL] = google_answer
    response = client.get(f"/map/{map_token_of(html)}")
    assert response.status_code == 503
    assert FAKE_KEY not in response.data.decode()


def test_the_map_route_answers_503_when_google_cannot_be_reached(app, client, monkeypatch):
    html, room_id, ids = rating_page(app, client)

    def unreachable(url, **kwargs):
        raise places.requests.ConnectionError(f"cannot reach {url}?key={FAKE_KEY}")

    monkeypatch.setattr(places.requests, "get", unreachable)
    response = client.get(f"/map/{map_token_of(html)}")
    assert response.status_code == 503
    assert FAKE_KEY not in response.data.decode()


# --- Nothing new in the database ---------------------------------------------------------------

def test_viewing_the_page_and_loading_the_map_write_nothing(app, client):
    room_id, ids = voting_room(app, client)
    before = database_snapshot(app)
    html = page(client, f"/rooms/{room_id}/vote")
    assert client.get(f"/map/{map_token_of(html)}").status_code == 200
    after = database_snapshot(app)
    assert after == before
    stored = repr(after)
    for google_text in (ADDRESS, "Monday: 12:00", "Review text 1", "Pizza Roma"):
        assert google_text not in stored
