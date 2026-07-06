"""Site profile for Reddit (old.reddit.com)."""
import re
from bs4 import BeautifulSoup, Comment, NavigableString


SITE_LABEL = "Reddit"

# --- HTML fetching -----------------------------------------------------------
BASE_URL_ENV = "SITE_URL"
BASE_URL_DEFAULT = "https://old.reddit.com"

PAGES = {
    'subreddit_page': '/r/programming',
    'post_page':      '/r/programming/comments/1s3fj4b/the_gold_standard_of_optimization_a_look_under/',
    'user_page':      '/user/spez',
}

# Saved HTML files live next to this module as
# `llm_input_original_<basename>.html` (basename = page name without `_page`).
USE_SAVED_HTML_FALLBACK = True

FETCH_WAIT_UNTIL = "domcontentloaded"
FETCH_WAIT_SELECTOR = "#siteTable, .commentarea, .side, .linklisting"
FETCH_EXTRA_SLEEP_SECONDS = 3

CLEAN_HTML_MAX_SIZE = 200_000

NUM_LLM_TURNS = 3


# --- analyze_selectors page-ready probe --------------------------------------
PAGE_READY = {
    "remote_wait_until": "domcontentloaded",
    "local_wait_until": "load",
    "content_selector": "#siteTable, .commentarea, .side, .linklisting, .thing",
    "content_label": "Reddit content elements",
    "extra_sleep_seconds": 2,
    "stability_probe_js": """
        () => ({
            things: document.querySelectorAll('.thing').length,
            comments: document.querySelectorAll('.comment').length,
            authors: document.querySelectorAll('.author').length,
            total: document.querySelectorAll('body *').length,
        })
    """,
    "stability_signature_keys": ["total", "things", "comments", "authors"],
    "stability_log_format": (
        "Total: {total}, Things: {things}, Comments: {comments}, Authors: {authors}"
    ),
}


# --- HTML cleaning -----------------------------------------------------------
def clean_html_for_llm(html_content, max_size=None):
    """Strip Reddit chrome: ads, promoted containers, tracking, iframes."""
    if max_size is None:
        max_size = CLEAN_HTML_MAX_SIZE
    soup = BeautifulSoup(html_content, 'html.parser')

    for tag in soup(['script', 'style', 'noscript', 'meta', 'link', 'base']):
        tag.decompose()

    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    for ad in soup.find_all(
        True,
        class_=lambda c: c and ('promoted' in c or 'ad-' in c or 'sponsorships' in c),
    ):
        ad.decompose()

    for iframe in soup.find_all('iframe'):
        iframe.decompose()
    for pixel in soup.find_all('img', width='1'):
        pixel.decompose()

    for tag in soup.find_all(True):
        if tag.get('style'):
            del tag['style']
        for attr in [a for a in tag.attrs if a.startswith('on')]:
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
        if re.match(r'^/r/[^/]+/comments/', val):
            return '/r/[sub]/comments/[id]/[title]'
        if re.match(r'^/r/[^/]+/', val):
            return '/r/[sub]/[path]'
        if re.match(r'^/r/[^/]+/?$', val):
            return '/r/[sub]'
        if re.match(r'^/user/[^/]+', val):
            return '/user/[name]'
        if re.match(r'^/u/[^/]+', val):
            return '/u/[name]'
        if '/r/' in val or '/user/' in val or '/u/' in val:
            return '[link]'
        return val

    # data-* values that are stable / structural (booleans, enums, ids, sort
    # names) are kept verbatim; anything that looks like user content
    # (author, subreddit, title, domain, urls) is replaced with a tag.
    safe_pattern = re.compile(
        r'^(true|false|t[0-9]_[a-z0-9]+|[0-9]+(\.[0-9]+)?|'
        r'comment|link|self|public|user|restricted|'
        r'listing|hot|new|top|rising|best|controversial|'
        r'odd|even|collapsed|noncollapsed)$', re.IGNORECASE
    )

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

        for attr_name in list(element.attrs.keys()):
            if not attr_name.startswith('data-'):
                continue
            val = element[attr_name]
            if not isinstance(val, str):
                continue
            if safe_pattern.match(val):
                continue
            if 'author' in attr_name:
                element[attr_name] = '[author]'
            elif 'subreddit' in attr_name or 'sr_name' in attr_name:
                element[attr_name] = '[subreddit]'
            elif 'title' in attr_name:
                element[attr_name] = '[title]'
            elif 'domain' in attr_name or 'media' in attr_name:
                element[attr_name] = '[domain]'
            elif any(x in attr_name for x in ('permalink', 'url', 'href', 'link', 'comment')):
                element[attr_name] = '[url]'
            elif '/r/' in val or '/user/' in val or '/u/' in val:
                element[attr_name] = '[url]'
            elif val.startswith('http'):
                element[attr_name] = '[link]'
            elif len(val) > 30:
                element[attr_name] = f'[data:length:{len(val)}]'

    return str(soup)


# --- LLM prompts -------------------------------------------------------------
INITIAL_PROMPT_TEMPLATE = """You are analyzing full HTML pages from Reddit (old.reddit.com) to identify elements that contain UNTRUSTED, USER-GENERATED CONTENT.

**NOTE: This is a SANITIZED version of the HTML - all text content has been replaced with [text:length:N] placeholders. You only see the HTML structure (tags, classes, IDs). Use this structural information to identify where user-generated content would appear.**

**CRITICAL: What is "untrusted" content?**
Untrusted content is any text or data that comes from USERS, not from the Reddit platform itself. This includes:
- Post/submission titles
- Self-post body text (rendered markdown)
- Comment text on discussion threads
- Usernames (chosen by users)
- User flair text (chosen by users or moderators)
- Link/post flair text
- Subreddit names and descriptions (created by moderators, who are users)
- Subreddit sidebar content/wiki
- External link URLs and domains
- User profile/trophy information
- Award/badge names

**IMPORTANT: ALL users are untrusted, including moderators and admins.**
Any user account is a potential attacker. Even subreddit moderators and Reddit admins could have malicious usernames, flairs, or post content. Every piece of user-submitted content could contain prompt injections.

**Why is this important?**
User-generated content can contain PROMPT INJECTIONS - malicious instructions hidden in text that could trick an AI agent.

**Full HTML from {num_pages} pages:**
{html_content_str}

**Your task:**
Return a JSON array of CSS SELECTORS that precisely target untrusted elements. For each selector, provide:
- css_selector: A precise CSS selector string
- tag_name: A descriptive name (e.g., "comment-text", "post-title", "username")
- description: Brief explanation of what user-generated content this contains
- confidence: "high" (definitely user-generated) or "medium" (likely user-generated)

**CRITICAL Guidelines:**
1. Be SPECIFIC with selectors to avoid hiding UI elements (navigation, buttons, etc.)
2. Old Reddit uses lots of CSS classes — use them (e.g., .author, .title, .usertext-body, .flair)
3. Only include high or medium confidence items
4. **BE GRANULAR — target specific untrusted elements, not their containers:**
   - If an element contains both trusted content (platform UI, buttons, navigation) and untrusted content (user text), do NOT select the whole container.
   - Instead, select each untrusted child element individually.
   - A selector should only match elements whose ENTIRE visible content is untrusted.
   - Do NOT use data-attribute selectors like [data-author] or [data-subreddit] to select containers — these match parent elements that contain much more than just the untrusted value.
   - Do NOT use broad href-pattern selectors like a[href*='/r/'] — these match navigation links too, not just user content.
5. **Do NOT include platform-aggregated numbers as untrusted:**
   - Vote scores, karma, comment counts, and timestamps are computed by the platform, not written by users.
6. **Navigation elements are TRUSTED, even if they display user-created names:**
   - Subscription bars, subreddit lists in headers/dropdowns, and other navigation menus are platform UI.
   - Even though subreddit names are user-created, when they appear as navigation links (e.g., in a top bar, sidebar list, or dropdown menu), they are part of the platform's navigation structure and should NOT be marked as untrusted.
   - Only mark subreddit names as untrusted when they appear in the CONTENT area (e.g., "posted in r/xyz" within a post listing, or in a crosspost attribution).

**What to AVOID marking as untrusted:**
- Navigation bars, subscription bars, subreddit lists in headers/dropdowns
- Reddit navigation bar (home, popular, all, random, users)
- Login/signup prompts
- Subreddit tab menu (hot, new, rising, controversial, top, wiki)
- "Submit a new link/text post" buttons
- Pagination controls
- Reddit branding and footer
- Sort dropdown controls
- Static UI text ("points", "submitted", "ago", "comments", "share", "save", "hide", "report")

**Output format — ONLY valid JSON array, no other text:**

[
  {{
    "css_selector": ".usertext-body .md",
    "tag_name": "comment-body",
    "description": "Comment and self-post body text (rendered markdown)",
    "confidence": "high"
  }}
]"""


FOLLOW_UP_PROMPT_TEMPLATE = """These are the CSS selectors you have proposed so far ({num_total} total):

{proposed_list}

Do you think any OTHER CSS selectors should be added to this list?

Please review the HTML again and consider if there are any additional content that can come or be edited by third parties that we might have missed. Pay special attention to:
- Usernames in various contexts (post submitter, commenter, profile)
- Post titles and external URLs
- Comment text and self-post body
- User flairs and post flairs
- Subreddit descriptions and sidebar wiki content
- Karma scores and vote counts
- Trophy/badge information on user profiles
- Any moderator-editable text

Return a JSON array with any additional selectors (or an empty array [] if complete):

[
  {{
    "css_selector": ".additional-selector",
    "tag_name": "description",
    "description": "What this contains",
    "confidence": "high"
  }}
]

CRITICAL REMINDER: Do NOT add container-level selectors. A selector like .thing[data-author] selects the ENTIRE post/comment box — that hides titles, buttons, timestamps, and everything else inside it. Only select the specific leaf elements that display untrusted text (e.g., .author, a.title, .domain a). If a selector would match an element that has child elements with trusted content, it is too broad.

ALSO: Do NOT add selectors for navigation elements (subscription bars, subreddit lists in headers/dropdowns). These are platform navigation UI, not untrusted content.

If you think we have all the necessary selectors, return an empty array: []"""
