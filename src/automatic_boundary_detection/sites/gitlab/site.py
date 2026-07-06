"""Site profile for GitLab (WebArena instance)."""
import re
from bs4 import BeautifulSoup, Comment, NavigableString


SITE_LABEL = "GitLab"

# --- HTML fetching -----------------------------------------------------------
BASE_URL_ENV = "GITLAB_URL"
BASE_URL_DEFAULT = "http://localhost:8103"

PAGES = {
    'project_page': '/byteblaze/a11y-syntax-highlighting',
    'issue_page':   '/byteblaze/a11y-syntax-highlighting/-/issues/1',
    'user_page':    '/byteblaze',
}

# GitLab evaluates against live pages — there's no cached-HTML fallback.
USE_SAVED_HTML_FALLBACK = False

FETCH_WAIT_UNTIL = "domcontentloaded"
FETCH_WAIT_SELECTOR = (
    '#content-body, .project-home-panel, .issuable-list, '
    '.user-profile, .file-content, .note-body, .tree-table'
)
FETCH_EXTRA_SLEEP_SECONDS = 3

# Source HTML is very large because GitLab pages embed SVG sprites and inline
# scripts; the hand-tuned ceiling avoids the LLM cutting off mid-structure.
CLEAN_HTML_MAX_SIZE = 10_000_000

NUM_LLM_TURNS = 3


# --- analyze_selectors page-ready probe --------------------------------------
PAGE_READY = {
    # GitLab is server-rendered behind localhost so the `load` event is enough
    # both locally and "remotely" (the proxy still counts as local).
    "remote_wait_until": "load",
    "local_wait_until": "load",
    "content_selector": (
        '#content-body, .project-home-panel, .issuable-list, '
        '.user-profile, .file-content, .note-body, .tree-table, '
        '.commit-row-message'
    ),
    "content_label": "GitLab content elements",
    "extra_sleep_seconds": 2,
    "stability_probe_js": """
        () => ({
            commits: document.querySelectorAll('.commit-row-message, .commit-title').length,
            files: document.querySelectorAll('.tree-item, .file-row').length,
            notes: document.querySelectorAll('.note-body').length,
            issues: document.querySelectorAll('.issue-title-text, .issuable-info .title').length,
            total: document.querySelectorAll('body *').length,
        })
    """,
    "stability_signature_keys": ["total", "commits", "files", "notes"],
    "stability_log_format": (
        "Total: {total}, Commits: {commits}, Files: {files}"
    ),
}


# --- HTML cleaning -----------------------------------------------------------
def clean_html_for_llm(html_content, max_size=None):
    """Strip marker artifacts, Vue.js scoped-CSS markers, scripts, styles."""
    if max_size is None:
        max_size = CLEAN_HTML_MAX_SIZE
    soup = BeautifulSoup(html_content, 'html.parser')

    for tag in soup(['script', 'style', 'noscript', 'meta', 'link', 'base']):
        tag.decompose()

    for svg_container in soup.find_all(
        ['svg', 'div'],
        id=lambda x: x and ('svg' in x.lower() or 'sprite' in x.lower()),
    ):
        svg_container.decompose()
    for svg in soup.find_all('svg'):
        symbols = svg.find_all('symbol')
        if len(symbols) > 0 and len(svg.get_text(strip=True)) == 0:
            svg.decompose()

    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    # Every marker that the reveal.js / gitlab-marker.js system adds
    MARKER_ATTRS = {
        'data-untrusted', 'data-trusted',                       # element labels
        'data-tag-name', 'data-qllm-id',                        # qllm ids
        'data-untrusted-element', 'data-reveal-placeholder',    # reveal hooks
        'data-reveal-processed', 'data-reveal-initialized',     # reveal state
        'data-reveal-hint', 'data-reveal-config',               # reveal config
    }
    MARKER_CLASSES = {'reveal-hidden', 'reveal-visible', 'reveal-text-wrap'}

    for tag in soup.find_all(True):
        for attr in MARKER_ATTRS:
            if tag.has_attr(attr):
                del tag[attr]

        # Strip marker classes from `class` list (but keep the attribute if other non-marker classes remain).
        cls = tag.get('class')
        if cls:
            kept = [c for c in cls if c not in MARKER_CLASSES]
            if kept:
                tag['class'] = kept
            else:
                del tag['class']

        vue_attrs = [a for a in tag.attrs if a.startswith('data-v-')]
        for attr in vue_attrs:
            del tag[attr]

        if tag.get('style'):
            del tag['style']
        for attr in [a for a in tag.attrs if a.startswith('on')]:
            del tag[attr]

        for attr in ['data-clipboard-text', 'data-qa-selector']:
            if tag.has_attr(attr):
                del tag[attr]

    for el in soup.find_all('gl-emoji'):
        el.decompose()

    cleaned = str(soup)
    if len(cleaned) > max_size:
        cleaned = cleaned[:max_size] + "\n<!-- [HTML truncated for size] -->"
    return cleaned


def sanitize_html_content(html_content):
    """Replace text nodes with [text:length:N] and anonymize GitLab URLs."""
    soup = BeautifulSoup(html_content, 'html.parser')

    for text_node in soup.find_all(string=True):
        if isinstance(text_node, NavigableString):
            parent = text_node.parent
            if parent and parent.name not in ['script', 'style']:
                text_content = str(text_node).strip()
                if text_content:
                    text_node.replace_with(f'[text:length:{len(text_content)}]')

    for element in soup.find_all(True):
        if element.name == 'img':
            if element.get('alt'):
                element['alt'] = '[image]'
            if element.get('src'):
                src = element.get('src', '')
                if '/' in src:
                    parts = src.split('/')
                    parts[-1] = '[image]'
                    element['src'] = '/'.join(parts)
                else:
                    element['src'] = '[image]'
            if element.get('title'):
                element['title'] = '[title]'

        if element.name == 'a' and element.get('href'):
            href = element.get('href', '')
            if href.startswith('http'):
                element['href'] = '[link]'
            elif href.startswith('/'):
                if re.match(r'^/[^/]+/[^/]+/-/issues/\d+', href):
                    element['href'] = '/[namespace]/[project]/-/issues/[id]'
                elif re.match(r'^/[^/]+/[^/]+/-/merge_requests/\d+', href):
                    element['href'] = '/[namespace]/[project]/-/merge_requests/[id]'
                elif re.match(r'^/[^/]+/[^/]+/-/blob/', href):
                    element['href'] = '/[namespace]/[project]/-/blob/[ref]/[path]'
                elif re.match(r'^/[^/]+/[^/]+/-/commit/', href):
                    element['href'] = '/[namespace]/[project]/-/commit/[sha]'
                elif re.match(r'^/[^/]+/[^/]+/-/tree/', href):
                    element['href'] = '/[namespace]/[project]/-/tree/[ref]/[path]'
                elif re.match(r'^/users/[^/]+', href):
                    element['href'] = '/users/[user]'
                elif re.match(r'^/[^/]+/[^/]+/?$', href):
                    element['href'] = '/[namespace]/[project]'
                elif re.match(r'^/[^/]+/?$', href):
                    element['href'] = '/[user-or-group]'
                else:
                    element['href'] = '[link]'
            else:
                element['href'] = '[link]'

    for tag in soup.find_all(True):
        for attr_name in list(tag.attrs.keys()):
            if (attr_name.startswith('data-')
                    and isinstance(tag[attr_name], str)
                    and len(tag[attr_name]) > 100):
                tag[attr_name] = f'[data:length:{len(tag[attr_name])}]'

    return str(soup)


# --- LLM prompts -------------------------------------------------------------
INITIAL_PROMPT_TEMPLATE = """You are analyzing full HTML pages from a web application (GitLab instance) to identify elements that contain UNTRUSTED, USER-GENERATED CONTENT.

**NOTE: This is a SANITIZED version of the HTML - all text content has been replaced with [text:length:N] placeholders. You only see the HTML structure (tags, classes, IDs). Use this structural information to identify where user-generated content would appear.**

**CRITICAL: What is "untrusted" content?**
Untrusted content is any text or data that comes from USERS, not from the GitLab platform itself. This includes:
- Project/repository names and descriptions
- Issue titles and descriptions
- Merge request titles and descriptions
- Comments/notes on issues and merge requests
- Commit messages and descriptions
- Code/file contents and file names in the repository
- README and wiki content (rendered markdown)
- User display names, usernames, and bios (including the profile owner's own name)
- Branch and tag names
- Label names
- Snippet titles and content
- Release titles and notes
- Activity feed entries
- Search result titles and descriptions
- Issue/MR reference strings (e.g., "namespace/project#1")
- Any text that users can create, edit, or upload

**IMPORTANT: ALL users are untrusted, including the page owner.**
In GitLab, every user account is a potential attacker. This means:
- On a user profile page, the user's OWN display name, username, and bio are untrusted
- On a project page, the project owner's name is untrusted
- Repository names, namespace names, and organization names are ALL untrusted
- There is NO "trusted" user — any user could embed malicious prompt injections in their username, project name, bio, commit messages, or any other content they control

**Why is this important?**
User-generated content can contain PROMPT INJECTIONS - malicious instructions hidden in text that could trick an AI agent. Even a profile page displaying "Byte Blaze" as the username must treat that name as untrusted because the user chose it themselves.

**Full HTML from {num_pages} pages:**
{html_content_str}

**Your task:**
Return a JSON array of FULL CSS SELECTORS that precisely target untrusted elements. For each selector, provide:
- css_selector: A precise CSS selector string. Examples:
  * ".note-body .md" (descendant)
  * ".commit-row-message" (simple class)
  * "h1.home-panel-title" (tag with class)
  * ".issue-title-text a" (descendant)
  * ".file-content .code" (code content)
- tag_name: A descriptive name (e.g., "commit-message", "issue-title", "user-name")
- description: Brief explanation of what user-generated content this contains
- confidence: "high" (definitely user-generated) or "medium" (likely user-generated)

**CRITICAL Guidelines:**
1. Be SPECIFIC with selectors to avoid hiding UI elements (buttons, navigation, settings)
2. Use parent-child relationships when needed (e.g., ".note-body .md" not just ".md")
3. Use multiple classes when needed (e.g., ".title.raw-topic-link")
4. Only include high or medium confidence items
5. Pay special attention to: project names, issue/MR titles, commit messages, comments, usernames, file names, branch names, code content, rendered markdown

**What to AVOID marking as untrusted:**
- GitLab navigation sidebar (project menu, group menu items)
- GitLab UI controls (buttons, form inputs, dropdowns, modals)
- System-generated status badges (open/closed/merged)
- Static help text and documentation links
- Pagination controls and count badges
- Settings and configuration UI

**CRITICAL - Output format:**
You MUST return ONLY a valid JSON array. No explanatory text, no markdown. Start with [ and end with ]:

[
  {{
    "css_selector": ".note-body .md",
    "tag_name": "comment-content",
    "description": "Comment/note content on issues and merge requests",
    "confidence": "high"
  }}
]"""


FOLLOW_UP_PROMPT_TEMPLATE = """These are the CSS selectors you have proposed so far ({num_total} total):

{proposed_list}

Do you think any OTHER CSS selectors should be added to this list?

Please review the HTML again and consider if there are any additional content that can come or be edited by third parties that we might have missed. Pay special attention to:
- Usernames and display names in various contexts
- Branch/tag names
- File names in repository trees
- Project descriptions
- Avatar images
- Activity feed items
- Labels and milestones
- Any other user-editable text

Return a JSON array with any additional selectors (or an empty array [] if complete):

[
  {{
    "css_selector": ".additional-selector",
    "tag_name": "description",
    "description": "What this contains",
    "confidence": "high"
  }}
]

If you think we have all the necessary selectors, return an empty array: []"""
