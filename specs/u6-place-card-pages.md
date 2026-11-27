# U6 – Place card in three pages: where, how it looks, what others say

Branch: `ux-6-place-card-pages`
Tests: `tests/test_u6_place_card_pages.py` (new). Replaces the flip tests listed under "Reviewed tests that change".
Decision: `docs/decisions.md`, D29 (draft below). Proposal: Timo.

## Why
The rating card looks cheap: the facts are one line of plain text, and the useful parts (where the place is, opening hours) are missing or hidden behind a flip. A person deciding wants to see at a glance **where it is, what it looks like, when it is open and what others say**, plus a link to Google Maps.

## What

### Page 1 – Where and how good (the front, always visible first)
- [ ] A **map image** with one pin at the place, about the top half of the card. It is an `<img>` from our own route `/map/<token>`, never from Google directly (the key stays on the server).
- [ ] Below: a **small round photo** (the first photo, through `/photo/...`), the **name**, the **kind** (e.g. Italian Restaurant).
- [ ] **Rating** as `★ 4.6` plus five stars filled by CSS and `1,234 reviews` in small text.
- [ ] Chips, only for facts Google sent: **distance** (`1.2 km`), **price** (`€€`), **today's hours** (`Open today until 23:00` green / `Closed today` red).
- [ ] **Short address** (`shortFormattedAddress`).
- [ ] A button **Open in Google Maps** (`googleMapsUri`, new tab). It is the only Google Maps link on the page (keeps the "one menu link" rule).

### Page 2 – How it looks and when it is open
- [ ] One big photo and up to 3 small photos, each with its author line (Google terms), through `/photo/...`.
- [ ] **Opening hours of the week** (`currentOpeningHours.weekdayDescriptions`), today highlighted. Without hours: *No opening hours on Google.*

### Page 3 – What others say
- [ ] Up to 3 reviews: author photo, name (linked), stars, age, text. Each text is cut to 4 lines by CSS so the page never scrolls (a vertical drag would clash with "swipe up = Fine with me").
- [ ] Each review keeps its own *Read on Google Maps* link (Google terms). No second *Open in Google Maps* button: that one stays on page 1 only.

### Moving between pages
- [ ] Tap on the **right half** of the card: next page; **left half**: previous page (like Instagram stories). Three short bars at the top of the card show the page.
- [ ] Swiping still rates on every page (right yes, up fine, left no, down joker question). A tap is a touch that moves less than 10 px (as today).
- [ ] Without JavaScript: the bars are links to `#card-page-<option>-<n>` and CSS shows the targeted page (`:target`); page 1 is shown when nothing is targeted.
- [ ] The card no longer flips: no checkbox, no "back" labels.

### Map route `/map/<token>`
- [ ] `token` = place id, latitude and longitude, signed with `SECRET_KEY` (`itsdangerous`, already part of Flask: **no new dependency**). A wrong or changed token: 404.
- [ ] Only for a browser that has joined a room with that place (same check as `/photo/`), otherwise the same 404.
- [ ] One Maps Static API call (`size=600x300&scale=2`, one marker, 5 s timeout), answer cached like photos.
- [ ] No key or a Google error: 503 with a short text, and the card still shows the address (the map box has a calm background, so a missing image does not look broken).

### Google fields
- [ ] `BACK_FIELD_MASK` adds `currentOpeningHours,shortFormattedAddress,googleMapsUri` (location is already in it). Still one details call for the one card on the rating page. Cards on other pages keep `CARD_FIELD_MASK`.
- [ ] Only `place_id` is stored; nothing new is written to the database.

### Unchanged (keep the existing tests)
- Rating and joker forms, routes and fields; the joker question; escaping of Google text; the key never in the HTML (`key=` not in the page); viewing writes nothing; manual and "details missing" options get no pages.

## Reviewed tests that change (needs Timo's OK as owner of the fork)
These pin the flip and the old back, so they are replaced by tests for the three pages, as was done in D26:
- `tests/test_rating_card_back.py`: checkbox and labels, labels outside the swipe area, part order, back content order, menu link on the about page, `swipe.js` flip check.
- `tests/test_fullscreen_card.py`: three pages "about, photos, reviews", about page, dots, single back with close label, CSS scroll-snap back, `swipe.js` back tap.
- `tests/test_place_details_back.py`: the parts that expect description/offers on an about page and the old `BACK_FIELD_MASK` string.
The exact list is made when the new tests are written; no test is removed without a replacement.

## Out of scope
- An interactive (movable) map on the card: it would clash with swiping. Tapping *Open in Google Maps* gives the full map.
- Maps on other pages (room page, result) – the result already has its embed map.
- Description and "serves" chips: dropped from the card (Google's description is often missing); can come back on page 2 later.

## Where the build differs from the text above (decisions for Timo, all easy to undo)
1. **The Google Maps button keeps A10's text and link.** `tests/test_swipe_rating.py` (A10, reviewed, not in the list above) pins exactly one link with the text *Menu & reviews on Google Maps* pointing to `places.place_page_url(...)`, also for a card whose details failed. So page 1's button has that text and link (styled as a button, `class="maps-button"`), and `googleMapsUri` is **not** asked for (it would be a field nobody shows). To get *Open in Google Maps* with `googleMapsUri`: change the two A10 menu-link tests, add `googleMapsUri` to `BACK_FIELD_MASK`, read it in `read_back` and use it in `place_card_pages`.
2. **C2c's facts line stays on page 1.** `tests/test_cards_vote_result.py::test_next_google_card_is_loaded_alone` (reviewed) pins the text `4.5 ★ · €€ · 330 m` on the rating page. Page 1 therefore still shows it as one small grey line (`.place-facts`) under the chips, although the chips say the same. It can go once that test may change.
3. **`utcOffsetMinutes` is asked for as well**, so "today" (the chip and the highlighted day) is the day *at the place*, not on the server (UTC). Without it the server's UTC day is used. It costs nothing extra: the call is already billed at the highest level because of `reviews` and `currentOpeningHours`.
4. **Description and "serves" fields are no longer asked for** (`editorialSummary`, `serves…`, `goodForGroups`, `outdoorSeating`, `reservable`): the card no longer shows them, and AGENTS.md says the field mask holds only what the UI shows. `read_back` no longer reads them.
5. **With the back mask, `details["back"]` is always there** (its parts may be empty), so every Google card with details on the rating page gets its three pages; a page without content says *No photos on Google.*, *No opening hours on Google.* or *No reviews on Google.*
6. **"Open today until …"** uses the closing time of today's last period (lunch and dinner: the dinner's end); *Open 24 hours* for a period without closing time; no chip if Google sent the week's lines but no periods.

## Checks (one line = one test), `tests/test_u6_place_card_pages.py` (Google faked)
- [ ] Three pages `data-card-page="1|2|3"` with ids `card-page-<option>-<n>`; no checkbox, no flip labels, no back, no dots.
- [ ] All three pages are inside the one swipe area; no rating buttons or forms in it or on a page.
- [ ] Order in the card: bars, page 1, 2, 3, rating form, joker form. The joker question is in the card, not in the swipe area or on a page.
- [ ] Only the next card gets pages, with one `BACK_FIELD_MASK` call; manual and failed options get no pages, bars or map.
- [ ] Page 1: map `<img src="/map/…">` in a box `data-card-map`; round photo through `/photo/`, name, kind in this order; `★ 4.5`, stars filled to 90 % by CSS (`aria-hidden`), `1,234 reviews` (`1 review`); no stars without a rating.
- [ ] Chips distance, price, today's hours (`chip-open` / `chip-closed`), each only when Google sent the fact; the short address; no map image without a location, the address stays.
- [ ] The Google Maps button exactly once, on page 1, new tab.
- [ ] Page 2: big photo and up to three small ones, each with its author link; the seven week lines, today `aria-current="date"`; *No opening hours on Google.* / *No photos on Google.*
- [ ] Page 3: up to three reviews with every part and their *Read on Google Maps* links; each text whole in `.review-text`, which the CSS cuts to four lines; *No reviews on Google.*; description and offers are not shown.
- [ ] Three bars link to `#card-page-<option>-<n>` with names, the first `aria-current`; CSS shows the `:target` page, page 1 by default, and `.is-current` once `swipe.js` adds `pages-ready`.
- [ ] `swipe.js`: tap (< 10 px) on the right/left half changes the page, bars change the page without jumping, links are left alone, no flip; swipes still rate; A10's static check.
- [ ] Google text escaped on every page; the key never in the page (`key=`, `googleapis`).
- [ ] `BACK_FIELD_MASK == CARD_FIELD_MASK + ",reviews,currentOpeningHours,shortFormattedAddress,utcOffsetMinutes"`; the back has `reviews, photos, address, opening_hours`; unusable hours or address give `None`; other pages keep `CARD_FIELD_MASK`.
- [ ] `opening_hours_view`: last period's closing time, *Closed today*, past midnight, *Open 24 hours*, the place's day (UTC offset), no today text without periods, `None` without hours.
- [ ] `/map/<token>`: token signed with `SECRET_KEY` (itsdangerous); one Static Maps call (`600x300`, `scale=2`, one marker, 5 s), `Cache-Control: private, max-age=600`; wrong, changed, foreign or badly filled token: 404 without a Google call; a browser not in a room with the place: the same 404; no key: 503 without a call; Google error or unreachable: 503, never the key.
- [ ] Viewing the page and loading the map write nothing; no Google text in the database.

## Reviewed tests that changed (exact list; Timo's OK as owner of the fork)
Each removed test is replaced by the named tests in `tests/test_u6_place_card_pages.py`; the removed test leaves a one-line note in its file. Every other test in the three files stays unchanged.

`tests/test_rating_card_back.py` (C10):
| Removed | Replaced by |
|---|---|
| `test_card_has_checkbox_labels_and_back` | `test_the_card_has_three_pages_and_no_flip` |
| `test_labels_sit_outside_the_swipe_area_and_the_open_label_outside_the_back` | `test_every_page_is_inside_the_one_swipe_area_and_has_no_rating_buttons` |
| `test_parts_of_the_card_come_in_the_specified_order` | `test_parts_of_the_card_come_in_order_bars_pages_rating_form_joker_form` |
| `test_back_shows_description_offers_and_the_reviews_line` | `test_description_and_offers_are_no_longer_shown`, `test_page_three_has_three_reviews_with_every_part_unchanged` |
| `test_back_shows_three_reviews_with_every_part_unchanged` | `test_page_three_has_three_reviews_with_every_part_unchanged` |
| `test_back_shows_the_extra_photos_through_the_proxy_with_authors` | `test_page_two_has_one_big_photo_and_up_to_three_small_ones_with_authors` |
| `test_rating_buttons_stay_below_the_card_for_both_sides` | `test_rating_and_joker_buttons_sit_in_the_card_but_on_no_page` |
| `test_front_shows_kind_and_rating_count` | `test_page_one_has_round_photo_name_and_kind_in_order`, `test_page_one_shows_the_rating_with_stars_and_the_review_count` |
| `test_the_rating_page_still_has_exactly_one_menu_link_now_on_the_about_page_of_the_back` | `test_the_google_maps_button_is_on_page_one_only_and_only_once` |
| `test_a_place_without_back_details_says_so_on_the_back` | `test_without_hours_page_two_says_so`, `test_without_any_photo_page_two_says_so_and_still_shows_hours`, `test_without_reviews_page_three_says_so` |
| `test_only_the_next_card_gets_a_back` | `test_only_the_next_card_gets_pages_and_one_details_call` |
| `test_review_text_names_and_description_are_escaped` | `test_text_from_google_is_escaped_on_every_page` |
| `test_swipe_js_turns_the_card_on_a_short_tap_and_leaves_links_alone` | `test_swipe_js_changes_the_page_on_a_tap_left_or_right_and_leaves_links_alone` |

`tests/test_fullscreen_card.py` (C11):
| Removed | Replaced by |
|---|---|
| `test_the_back_has_three_pages_in_the_order_about_photos_reviews` | `test_the_card_has_three_pages_and_no_flip` |
| `test_about_page_has_description_offers_and_the_one_menu_link` | `test_page_one_has_the_map_image_from_our_own_route`, `test_page_one_shows_the_short_address`, `test_the_google_maps_button_is_on_page_one_only_and_only_once`, `test_description_and_offers_are_no_longer_shown` |
| `test_photos_page_has_the_extra_photos_with_their_authors` | `test_page_two_has_one_big_photo_and_up_to_three_small_ones_with_authors` |
| `test_reviews_page_has_the_reviews_line_and_three_reviews_unchanged` | `test_page_three_has_three_reviews_with_every_part_unchanged` |
| `test_the_back_stays_a_single_back_with_the_close_label` | `test_the_card_has_three_pages_and_no_flip` |
| `test_a_page_without_content_says_so_and_the_back_keeps_three_pages_and_dots` | `test_without_any_photo_page_two_says_so_and_still_shows_hours`, `test_without_reviews_page_three_says_so`, `test_three_bars_at_the_top_link_to_the_three_pages` |
| `test_when_google_sends_no_back_details_the_empty_pages_say_so` | `test_without_hours_page_two_says_so`, `test_without_reviews_page_three_says_so` |
| `test_three_dots_link_to_the_three_pages_and_the_first_is_current` | `test_three_bars_at_the_top_link_to_the_three_pages` |
| `test_the_dots_come_after_the_pages_inside_the_back` | `test_three_bars_at_the_top_link_to_the_three_pages` (bars now come before the pages) |
| `test_exactly_one_menu_link_on_the_rating_page_and_it_is_on_the_about_page` | `test_the_google_maps_button_is_on_page_one_only_and_only_once` |
| `test_the_front_is_the_only_swipe_area_and_the_back_has_no_rating_buttons` | `test_every_page_is_inside_the_one_swipe_area_and_has_no_rating_buttons` |
| `test_the_joker_question_is_inside_the_card_but_not_in_the_swipe_area_or_the_back` | `test_the_joker_question_is_in_the_card_but_not_in_the_swipe_area_or_on_a_page` |
| `test_text_from_google_is_escaped_on_every_page_of_the_back` | `test_text_from_google_is_escaped_on_every_page` |
| `test_the_css_makes_the_back_a_horizontal_scroll_snap_container` | `test_without_javascript_css_shows_the_targeted_page_and_page_one_by_default`, `test_the_css_cuts_review_texts_to_four_lines` |
| `test_swipe_js_handles_the_joker_question_the_dots_and_the_tap_on_the_back` | `test_swipe_js_changes_the_page_on_a_tap_left_or_right_and_leaves_links_alone`, `test_swipe_js_still_rates_on_every_page_and_passes_the_a10_static_check` |

`tests/test_place_details_back.py` (C10; also the module docstring and the unused `BACK_KEYS` constant):
| Removed | Replaced by |
|---|---|
| `test_field_masks_are_built_from_each_other_and_never_use_a_star` | `test_back_field_mask_adds_hours_address_and_time_zone_and_drops_description_and_offers` |
| `test_description_comes_from_the_editorial_summary` | `test_the_back_has_reviews_photos_address_and_hours_and_no_description_or_offers` |
| `test_without_a_usable_summary_there_is_no_description` | `test_an_unusable_address_gives_none` |
| `test_missing_summary_gives_no_description` | `test_the_back_has_reviews_photos_address_and_hours_and_no_description_or_offers` |
| `test_offers_contain_only_true_fields_in_the_fixed_order` | `test_the_back_has_reviews_photos_address_and_hours_and_no_description_or_offers` |
| `test_all_offers_have_their_label` | `test_the_back_has_reviews_photos_address_and_hours_and_no_description_or_offers` |
| `test_no_true_field_means_no_offers` | `test_unusable_opening_hours_give_none_and_never_raise` |

Kept unchanged in these files because they still describe valid behaviour: the one-call/back-mask tests, manual and failed options without pages, the overview/room/result pages with the card mask only, key never in the page, viewing writes nothing, rating and joker by the forms, hidden-but-focusable buttons, joker question, no-scroll class, slim line and menu, A10's static check, and every reading test for reviews, photos, kind and rating count.

## Done when
- All tests pass (`uv run pytest`), output pasted.
- On a phone: tap right/left moves through the three pages, swipes still rate.
- AGENTS.md updated: `swipe.js` description (tap changes page instead of flipping), Maps Static API now used for the rating card, new field mask.

## D29 draft – U6: place card in three pages
Proposal by Timo. The rating card shows a map image, rating, chips and the Google Maps link first; photos and opening hours second; reviews third. Tap left/right changes the page, swiping still rates. The map image goes through `/map/<signed token>` so the key stays on the server. The flip and its tests are replaced (Timo's OK as owner of the fork).
