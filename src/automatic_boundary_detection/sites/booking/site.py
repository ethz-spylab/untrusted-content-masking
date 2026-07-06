"""Site profile for Booking.com.

Defines the data + functions the shared pipeline needs to drive the
Booking.com pipeline: which pages to fetch, how to clean / sanitize the
HTML (strip text → [text:length:N]), the LLM prompt, and the page-ready
probe used during selector evaluation.
"""
import re
from bs4 import BeautifulSoup, Comment, NavigableString


SITE_LABEL = "Booking.com"

# --- HTML fetching -----------------------------------------------------------
BASE_URL_ENV = "SITE_URL"
BASE_URL_DEFAULT = "https://www.booking.com"

PAGES = {
    'search_page':   '/searchresults.html?ss=Paris&dest_id=-1456928&dest_type=city&checkin=2025-07-01&checkout=2025-07-03',
    'hotel_page':    '/hotel/fr/pullman-paris-tour-eiffel.en-us.html?checkin=2025-07-01&checkout=2025-07-03',
    'homepage_page': '/index.html?lang=en-us&selected_currency=EUR',
}

# Saved HTML files live next to this module as
# `llm_input_original_<basename>.html` where basename is page_name with the
# trailing `_page` stripped (e.g. `search_page` → `search`).
USE_SAVED_HTML_FALLBACK = True

# fetch_pages settings (used when no saved HTML is available)
FETCH_WAIT_UNTIL = "networkidle"
FETCH_WAIT_SELECTOR = (
    "[data-testid='web-core-property-card'], "
    "[data-testid='property-description'], "
    "[data-testid='review-card']"
)
FETCH_EXTRA_SLEEP_SECONDS = 5

# clean_html_for_llm settings
CLEAN_HTML_MAX_SIZE = 200_000

# Number of LLM turns
NUM_LLM_TURNS = 3


# --- analyze_selectors page-ready probe --------------------------------------
PAGE_READY = {
    "remote_wait_until": "networkidle",
    "local_wait_until": "load",
    "content_selector": (
        '[data-testid="property-card"], '
        '[data-testid="web-core-property-card"], '
        '[data-testid="property-description"], '
        '[data-testid="review-card"], '
        'h2.pp-header__title'
    ),
    "content_label": "Booking.com content elements",
    "extra_sleep_seconds": 2,
    "stability_probe_js": """
        () => ({
            propertyCards: document.querySelectorAll('[data-testid="property-card"], [data-testid="web-core-property-card"]').length,
            reviews: document.querySelectorAll('[data-testid="review-card"]').length,
            testids: document.querySelectorAll('[data-testid]').length,
            total: document.querySelectorAll('body *').length,
        })
    """,
    "stability_signature_keys": ["total", "propertyCards", "reviews", "testids"],
    "stability_log_format": (
        "Total: {total}, Cards: {propertyCards}, Reviews: {reviews}"
    ),
}


# --- HTML cleaning -----------------------------------------------------------
def clean_html_for_llm(html_content, max_size=None):
    """Strip Booking.com chrome: tracking, ads, modals, React noise."""
    if max_size is None:
        max_size = CLEAN_HTML_MAX_SIZE
    soup = BeautifulSoup(html_content, 'html.parser')

    for tag in soup(['script', 'style', 'noscript', 'meta', 'link', 'base']):
        tag.decompose()

    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    for iframe in soup.find_all('iframe'):
        iframe.decompose()
    for pixel in soup.find_all('img', width='1'):
        pixel.decompose()

    for svg in soup.find_all('svg'):
        svg.decompose()

    def _safe_len(elem):
        # bs4 4.13 raises TypeError in _format_tag if any descendant has a
        # None tag name (happens on some malformed Booking inline scripts).
        # Treat unstringifiable elements as size-0 — they're unusable anyway.
        try:
            return len(str(elem))
        except Exception:
            return 0

    # Drop small modal/popup dialogs but keep large content-rich panels (e.g. review modals)
    for el in soup.find_all(attrs={'role': 'dialog'}):
        testids_inside = el.find_all(attrs={'data-testid': True})
        if len(testids_inside) < 5 and _safe_len(el) < 10000:
            el.decompose()
    for el in soup.find_all(attrs={'aria-hidden': 'true'}):
        testids_inside = el.find_all(attrs={'data-testid': True})
        if _safe_len(el) > 500 and len(testids_inside) < 3:
            el.decompose()

    for tag in soup.find_all(['div', 'span']):
        if (not tag.get_text(strip=True) and not tag.find_all(True)
                and not tag.get('data-testid') and not tag.get('role')):
            tag.decompose()

    for tag in soup.find_all(True):
        if tag.get('style'):
            del tag['style']
        attrs_to_remove = []
        for attr in list(tag.attrs.keys()):
            if attr.startswith('on'):  # event handlers
                attrs_to_remove.append(attr)
            elif attr.startswith('data-bui-'):  # Booking UI framework internals
                attrs_to_remove.append(attr)
            elif attr in ('tabindex', 'data-atlas-lm-key', 'data-et-click', 'data-et-view'):
                attrs_to_remove.append(attr)
        for attr in attrs_to_remove:
            del tag[attr]

    cleaned = str(soup)
    if len(cleaned) > max_size:
        cleaned = cleaned[:max_size] + "\n<!-- [HTML truncated for size] -->"
    return cleaned


def sanitize_html_content(html_content):
    """Replace text nodes with [text:length:N] and anonymize URLs/data-* values."""
    soup = BeautifulSoup(html_content, 'html.parser')

    for text_node in soup.find_all(string=True):
        if isinstance(text_node, NavigableString):
            parent = text_node.parent
            if parent and parent.name not in ['script', 'style']:
                text_content = str(text_node).strip()
                if text_content:
                    text_node.replace_with(f'[text:length:{len(text_content)}]')

    def anonymize_url(val):
        if not val or not isinstance(val, str):
            return val
        if val.startswith('http'):
            return '[link]'
        if '/hotel/' in val:
            return '[hotel-link]'
        if '/searchresults' in val:
            return '[search-link]'
        return val

    for element in soup.find_all(True):
        if element.name == 'img':
            if element.get('alt'):
                element['alt'] = '[image]'
            if element.get('src'):
                element['src'] = '[image]'
            if element.get('title'):
                element['title'] = '[title]'
        if element.name == 'a' and element.get('href'):
            element['href'] = anonymize_url(element['href'])
        if element.name == 'form' and element.get('action'):
            element['action'] = anonymize_url(element['action'])
        if element.name != 'img' and element.get('title'):
            element['title'] = '[title]'

        safe_pattern = re.compile(
            r'^(true|false|[0-9]+(\.[0-9]+)?|[a-f0-9\-]{8,36})$', re.IGNORECASE
        )
        for attr_name in list(element.attrs.keys()):
            if not attr_name.startswith('data-'):
                continue
            if attr_name == 'data-testid':
                continue
            val = element[attr_name]
            if not isinstance(val, str):
                continue
            if safe_pattern.match(val):
                continue
            if any(x in attr_name for x in ('url', 'href', 'link')):
                element[attr_name] = '[url]'
            elif val.startswith('http'):
                element[attr_name] = '[link]'
            elif len(val) > 30:
                element[attr_name] = f'[data:length:{len(val)}]'

    return str(soup)


# --- LLM prompts ----------------------------------------------------------
# Placeholders: {num_pages}, {html_content_str}
INITIAL_PROMPT_TEMPLATE = """You are analyzing full HTML pages from Booking.com (www.booking.com) to identify elements that contain UNTRUSTED, THIRD-PARTY/USER-GENERATED CONTENT.

**NOTE: This is a SANITIZED version of the HTML — all text content has been replaced with [text:length:N] placeholders. You only see the HTML structure (tags, classes, attributes, roles). Use that structure to find where third-party content would appear.**

**CORE PRINCIPLE — where did the text come from?**

For every region you consider marking, ask: *"Did Booking.com (or a tool Booking integrates with) produce this text, or did a property owner / guest type it in?"*

- **Trusted (do NOT mark)** — text that Booking computes, aggregates, or pulls from a structured tool/source. This includes anything sourced from a geocoder (street names, addresses, district names, location text under property names), a review aggregator (review scores, star counts, grade labels like "8.7", "Very Good", review-count text like "6,750 reviews"), a map/distance engine (distances "450 m", "1.2 km"), Booking's pricing/availability system (prices, currency, occupancy counts, dates, free-cancellation badges), Booking's facility taxonomy ("Free WiFi", "Pool", "Parking", bed types, restaurant cuisine types), or Booking's own marketing system (Genius badges, deal badges, hero banners, section headers, navigation chrome, breadcrumbs, sort/pagination/filter controls, "Book now" / "Reserve" buttons).
- **Untrusted (DO mark)** — text a property owner or a guest typed in themselves. If a human could type ANYTHING they wanted there, it's untrusted.

If a region looks structured (a number, a badge, a fixed-vocabulary label, a count, an icon-plus-distance) — it almost certainly came from a Booking tool and is trusted. If a region is free-form text or a free-form image upload (hotel description paragraph, review quote, property photo, FAQ answer that embeds the hotel name) — it's untrusted.

**SPECIFIC REMINDER — the address line under a property name is TRUSTED.** A property listing card typically shows the property name as a heading, followed immediately by a smaller line containing the street, neighborhood, district, or city. That smaller line is **not** something the property owner typed — it is **rendered from coordinates by Booking's geocoder** and is trusted platform-computed text. Property owners cannot inject content there. Do **not** propose a selector for the location/address text that appears under a property name on listing cards, search results, or carousels — even though it visually sits inside the same card as the (untrusted) property name. Mark only the property name itself, not the location line beneath it.

**Anatomy of a property listing card.** A typical hotel/property card on a travel-search site is a small block that bundles owner-supplied content with platform-rendered displays. Walking through the slots you usually find inside one card:
- A **property image / thumbnail** at the top — uploaded by the owner → UNTRUSTED.
- The **property name** as a heading-level element (the most prominent text) → UNTRUSTED.
- A **location / address line** in smaller type just under the name (street, district, city) → TRUSTED (geocoded).
- A **review score badge** with a number and/or grade label ("8.7", "Very Good") → TRUSTED (aggregated).
- A **review count** ("6,750 reviews") near the score → TRUSTED (aggregated).
- One or more **amenity badges** ("Free WiFi", "Pool") drawn from Booking's fixed taxonomy → TRUSTED.
- A **distance-from-landmark** chip ("450 m from city center") → TRUSTED (computed).
- A **price block** with currency and per-night rate → TRUSTED.
- A **"Select" / "See availability" button** → TRUSTED (platform UI).
- Optionally, an **owner-written description blurb** — one or two sentences of free text the property manager typed in → UNTRUSTED.
- Optionally, a **"deal" or promotional badge** ("Getaway Deal", "Genius") → TRUSTED (Booking marketing).

When walking through a property card, mark only the property image(s), the property name heading, and any owner-written description text. Everything else inside the card is platform-rendered and trusted. The same anatomy applies on carousels (each carousel slide is a smaller version of a card) and on hotel detail pages (the property name is a large heading; the address line beneath it is geocoded; review scores/counts in the sidebar are aggregated).

**What is "untrusted" content?**
Untrusted content is free-text content that a PROPERTY OWNER or GUEST has written/uploaded and that could contain prompt injection attacks. It falls into three categories:

**A. Property-owner content** — text that hotel/property managers type in themselves:
hotel and property names; "about this property" descriptions; free-form blurbs in search result cards; room type names; property and gallery photos (image content uploaded by the owner); promotional offer banners (titles, subtitles, captions, banner images); brand or chain names associated with the property.

**B. Guest/user-generated content** — anything written or chosen by a traveler:
review text (positive and negative quotes — the primary prompt-injection vector); "what guests loved" excerpts; reviewer display names; reviewer country / nationality shown next to a review; traveler-submitted questions in Q&A or "Travelers are asking" sections; management replies to reviews (written by the property, still untrusted).

**C. Content that LOOKS platform-generated but embeds owner/user text**:
FAQ question headings and answers (they embed the hotel name, which is owner-supplied);
nearby point-of-interest (POI) NAMES in the surroundings/area section (names of third-party businesses and landmarks — note: the *distances* shown next to POIs are platform-computed and trusted, but the names themselves are not);
sustainability or environmental certification names (third-party certifications, not Booking labels).

If unsure whether some text is free-form vs platform-generated, ask: "Could a property owner or a guest have typed this?" If yes, it's untrusted.

**Why this matters:**
Third-party content can contain PROMPT INJECTIONS — instructions hidden in text that could manipulate an AI agent browsing the page.

**Full HTML from {num_pages} pages:**
{html_content_str}

**Your task:**
Return a JSON array of CSS selectors that precisely target untrusted elements. For each selector provide:
- css_selector: a precise CSS selector string
- tag_name: a short descriptive name (e.g. "hotel-name", "review-text", "reviewer-name")
- description: one sentence explaining what third-party content it captures
- confidence: "high" (definitely third-party sourced) or "medium" (likely third-party sourced)

**General guidance for writing selectors on Booking.com:**

1. Booking.com uses `data-testid` attributes broadly throughout its component tree. They are the most stable anchor for semantic regions and you should prefer them over CSS classes when one is available. Selector syntax is `[data-testid='value']` — for example, the platform filter sidebar carries `[data-testid='filters-sidebar']` (that example is a TRUSTED region, shown only to illustrate the attribute shape; you must still identify the right testids for untrusted regions yourself by reading the HTML). Aria-labels and semantic tags are also reliable anchors.

2. BE GRANULAR. If a container holds a mix of trusted (UI controls, prices, ratings, buttons) and untrusted (review text, descriptions, names) content, target only the untrusted leaf children, not the whole container. A selector should only match elements whose entire visible content is untrusted — if a selector matches a parent whose descendants include buttons, action links, or numeric scores, it's too broad.

3. HARD RULE — DO NOT EMIT BARE CLASS SELECTORS. Class names on Booking.com are obfuscated hashes (short alphanumeric strings like a 9-10 character mixed alphanumeric token) that change between builds AND are reused in dozens of unrelated contexts on the same page (navigation, filters, footer, room tables, listings). A selector whose only handle is a CSS class — even chained classes like `.aaaa.bbbb.cccc` — WILL match elements in many sections at once and is an error. **Every selector you emit must include at least one of: a `data-testid` anchor, an `aria-label` constraint, a `role` constraint, or a semantic tag chain with no hashed classes.** To scope a hashed class inside a section, combine: `[data-testid='filters-sidebar'] label` (matches labels inside the filter sidebar — same trusted example as above, shown here to illustrate the SCOPING shape). If you cannot find a `data-testid`, `aria-label`, or `role` that contains the untrusted region you want to mark, skip that region rather than emit a bare class selector for it.

4. Property photos and gallery images are uploaded by the owner — they are untrusted. Target the `<img>` element specifically rather than its container, so you don't sweep in surrounding platform UI. Distinguish between platform stock photos (category browsing, destination imagery, illustrative banners) which are trusted, and owner-uploaded property images which are not.

5. The search page and the homepage each use a different DOM structure for property listings; be careful that homepage carousels also contain destination / category cards which look similar to listings but are platform content — don't sweep those in.

6. Be conservative on UI chrome. If you see a tag that looks like a button, a tab, a chip, a badge, a form input, a numeric counter, a dropdown toggle, a progress bar, or a calendar / date control, it is almost certainly platform UI even if it sits inside a property card. Skip those even when you're not sure. False positives on these are common.

**What is TRUSTED — do NOT mark these as untrusted:**

- Booking.com branding, navigation bar, header, hero banner, footer
- Search form (destination, dates, guests) and filter sidebar/controls
- Sort dropdown, pagination, tabs, breadcrumbs
- Section headers like "Guest reviews", "Facilities", "House rules", "Fine print"
- Static booking labels ("Free cancellation", "No prepayment needed", "Breakfast included")
- "Book now" / "Reserve" / "See availability" / "Select" buttons
- ALL review scores, star counts, grade labels ("8.7", "Very Good", "Excellent") and review-count text ("6,750 reviews") — these are platform-aggregated
- Property addresses, street names, and location text under property names (platform-verified geo data, not free text)
- Standardized amenities and facility lists (Booking has a fixed taxonomy: "Free WiFi", "Pool", "Parking" etc.)
- House-rules content (check-in/out times, smoking policy, child policy) — platform-structured fields
- Bed-type descriptions ("1 king bed", "2 twin beds") and restaurant cuisine types ("American • French")
- POI distances ("450 m", "1.2 km") — platform-computed (only the POI *name* is untrusted)
- Deal/offer badges, Genius program banners and loyalty badges (Booking marketing)
- Map tiles and map controls
- Platform-generated highlight blurbs ("Located in the best-rated area…")

**Output format — ONLY a valid JSON array, no surrounding text:**

[
  {{
    "css_selector": ".some-precise-selector",
    "tag_name": "review-text",
    "description": "Guest review text",
    "confidence": "high"
  }}
]"""


# Placeholders: {num_total}, {proposed_list}
FOLLOW_UP_PROMPT_TEMPLATE = """You have proposed {num_total} selectors so far:

{proposed_list}

Review the HTML once more. Are there any untrusted regions you missed? Think through the categories: property-owner free text (names, descriptions, blurbs, photos, promo banners, room names, brand names); guest-generated text (reviews, reviewer names, reviewer countries, traveler-submitted Q&A, management replies); and content that LOOKS platform-generated but embeds owner/user text (FAQ questions/answers, POI names, certification names).

Return a JSON array with any additional selectors (or an empty array [] if you are complete):

[
  {{
    "css_selector": ".some-precise-selector",
    "tag_name": "review-text",
    "description": "Guest review text",
    "confidence": "high"
  }}
]

Reminders:
- Do NOT add container-level selectors. If a selector would match an element whose children include trusted UI, it's too broad.
- Do NOT add selectors for platform navigation, filters, search controls, prices, ratings, or scores.

If you have everything, return: []"""
