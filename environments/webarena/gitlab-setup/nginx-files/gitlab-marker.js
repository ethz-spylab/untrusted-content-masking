// Marks untrusted user-generated regions of GitLab CE pages with
// data-untrusted="true" + a stable data-qllm-id so reveal.js can mask them.
// Targets the GitLab CE DOM shipped in the WebArena pre-populated AMI
// (~14.x-16.x); selectors may need updating on other GitLab versions.

(function() {
    'use strict';

    // =========================================================================
    // Untrusted content selectors for GitLab CE
    // -------------------------------------------------------------------------
    // Cheat-sheet of GitLab DOM classes used below:
    //   - .project-row / .project-card     -> repo list items
    //   - .commit-row-message              -> commit messages
    //   - .file-content / .blob-content    -> code content
    //   - .md / .wiki                      -> rendered markdown
    //   - .issue-title-text                -> issue title
    //   - .note-body / .note-text          -> comments (GitLab calls them "notes")
    //   - .timeline-entry                  -> activity / comment entries
    //   - .user-info / .author             -> user info in various places
    // =========================================================================

    const UNTRUSTED_SELECTORS = [
        // ---- Project / Repository lists ----
        {
            selector: '.project-row .project-name, .projects-list .project-name, a.project',
            tagName: 'project-link',
            description: 'Project link in list (contains avatar + name)',
            checkOwnership: true,
            checkProjectList: true
        },
        {
            selector: '.namespace-name',
            tagName: 'owner-name',
            description: 'Project owner/username prefix in list (e.g. "Byte Blaze /")',
            checkOwnership: true,
            checkProjectList: true
        },
        {
            selector: '.project-row .avatar-container, .projects-list .avatar-container, .project-row .identicon, .projects-list .identicon',
            tagName: 'project-icon',
            description: 'Project avatar/icon in list (shows first letter or custom image)',
            checkOwnership: true,
            checkProjectList: true
        },
        {
            selector: 'span.project-name',
            tagName: 'project-name',
            description: 'Project/repo name text (in notifications, headers, etc.)',
            checkOwnership: true,
            checkProjectList: true
        },
        {
            selector: '.project-row .description, .project-description, .projects-list .description',
            tagName: 'project-description',
            description: 'Project description in list',
            checkOwnership: true,
            checkProjectList: true
        },

        // ---- Branch / ref names ----
        {
            selector: '.ref-name, a.ref-name, a.gl-font-monospace.gl-bg-blue-50, span.label-branch, .system-note-message code',
            tagName: 'branch-name',
            description: 'Branch/ref name in notifications and links',
            checkOwnership: false
        },
        {
            selector: '.mr-widget-body .ref-name, .mr-widget-body .js-branch-name, .mr-widget-body .branch-name, .ci-widget .ref-name, .ci-widget-content .ref-name, .mr-widget-pipeline .ref-name, .mr-widget-body a.commit-sha, .ci-widget-content a.commit-sha',
            tagName: 'branch-name',
            description: 'Branch/fork ref and commit SHA in MR/CI pipeline widget (fork path leaks username)',
            checkOwnership: false,
            skipEmptyCheck: true
        },
        {
            selector: '.mr-section-container .js-mr-widget-pipeline a[href*="/tree/"], .mr-section-container .js-mr-widget-pipeline a[href*="/commit/"]',
            tagName: 'branch-name',
            description: 'Any branch/commit link in MR pipeline widget (fallback for fork path leaks)',
            checkOwnership: false,
            skipEmptyCheck: true
        },
        {
            selector: '.ref-selector .gl-dropdown-item-text-primary, [data-qa-selector="branches_section"] .gl-dropdown-item-text-primary, [data-testid="branches-section"] .gl-dropdown-item-text-primary, [data-qa-selector="tags_section"] .gl-dropdown-item-text-primary, [data-testid="tags-section"] .gl-dropdown-item-text-primary, .compare-revision-cards .gl-dropdown-item-text-primary',
            tagName: 'branch-name',
            description: 'Branch/tag name in ref-selector and compare dropdown items',
            checkOwnership: false
        },

        // ---- Repository header / breadcrumb / sidebar ----
        {
            selector: '.breadcrumb-item a, .repo-breadcrumb a, .breadcrumbs-sub-title a, .breadcrumbs-list a:not(.dropdown-item), .breadcrumbs-links a:not(.dropdown-item)',
            tagName: 'breadcrumb',
            description: 'Breadcrumb link (user/group name, repo name)',
            checkOwnership: true
        },
        {
            selector: '.sidebar-context-title',
            tagName: 'project-name',
            description: 'Project/repo name in sidebar',
            checkOwnership: true
        },
        {
            selector: 'h1.home-panel-title',
            tagName: 'project-name',
            description: 'Project name on project overview page',
            checkOwnership: true
        },
        {
            selector: '.home-panel-description-markdown, .home-panel-description.text-break',
            tagName: 'project-description',
            description: 'Project description and forked-from on overview page',
            checkOwnership: true
        },
        {
            selector: 'a[data-qa-selector="forked_from_link"]',
            tagName: 'forked-from',
            description: 'Forked-from link on project overview page',
            checkOwnership: true
        },
        {
            selector: '.ref-selector button.gl-dropdown-toggle, .ref-selector .gl-dropdown-toggle-text, .ref-selector .gl-new-dropdown-toggle-text, .ref-selector .dropdown-toggle-text, .project-refs-form .dropdown-toggle-text, .tree-ref-holder .dropdown-toggle-text',
            tagName: 'branch-name',
            description: 'Selected branch name in ref selector button',
            checkOwnership: true
        },
        {
            selector: '.project-item-select-holder .project-item-select',
            tagName: 'repo-breadcrumb',
            description: 'Project selector in header',
            checkOwnership: true
        },

        // ---- README / rendered markdown ----
        {
            selector: '.readme-holder .md, .wiki .md, .file-content .md, .file-content.md',
            tagName: 'markdown-content',
            description: 'Rendered markdown content (README, wiki, etc.)',
            checkOwnership: true
        },

        // ---- Code / file content ----
        {
            selector: '.file-content .code, .blob-content, .file-content .file-content',
            tagName: 'code-content',
            description: 'Source code file content',
            checkOwnership: true
        },
        {
            selector: '.js-edit-blob-form .editor-ref',
            tagName: 'branch-name',
            description: 'Branch name text on edit file page (inside clickable dropdown)',
            checkOwnership: true
        },
        {
            selector: '.js-edit-blob-form .file-editor.code, .file-editor.code',
            tagName: 'code-content',
            description: 'Source code in inline editor',
            checkOwnership: false,
            skipEmptyCheck: true
        },

        // ---- File tree / file names ----
        {
            selector: '.tree-item .str-truncated, .tree-item-file-name, .file-name a, strong.file-title-name, [data-qa-selector="file_title_content"]',
            tagName: 'file-name',
            description: 'File name in repository tree',
            checkOwnership: true
        },
        {
            selector: '.file-row-name .gl-truncate, .diff-file-changes .file-row-name, [data-qa-selector="file_name_content"]',
            tagName: 'file-name-diff',
            description: 'File name in MR diff / changes file tree (clickable via role=button parent)',
            checkOwnership: true
        },

        // ---- WebIDE ----
        {
            selector: '.ide-file-list .file-row-name, .ide-tree-body .file-row-name, [data-testid="ide-tree-body"] .file-row-name',
            tagName: 'file-name',
            description: 'File name in WebIDE file tree',
            checkOwnership: true
        },
        {
            selector: '#ide.blob-viewer-container, .multi-file-edit-pane-content, .ide-editor .monaco-editor .view-lines, .ide-editor .editor-mounted, .ide-editor .modified-diff-viewer',
            tagName: 'code-content',
            description: 'File content in WebIDE editor',
            checkOwnership: true
        },
        {
            selector: '.multi-file-tab',
            tagName: 'file-name',
            description: 'File tab name in WebIDE tab bar',
            checkOwnership: true
        },
        {
            selector: '.ide-status-bar .ide-status-branch, .ide-sidebar-branch-title, .ide-review-sub-header .branch-name, .ide-merge-requests .dropdown-content a, .ide-merge-requests .dropdown-content .btn-link, a[href*="/-/ide/project/"].btn-link, [data-testid="ide-nav-dropdown"] .flex-fill.text-truncate',
            tagName: 'branch-name',
            description: 'Branch name in WebIDE (status bar, sidebar, nav button, dropdown)',
            checkOwnership: true
        },

        // ---- Commit messages ----
        {
            selector: '.commit-row-message, .commit-title, .commits-row .item-title a, a.tree-commit-link',
            tagName: 'commit-message',
            description: 'Commit message',
            checkOwnership: true
        },
        {
            selector: '.commit-description, .commit-row-description',
            tagName: 'commit-body',
            description: 'Commit message body / extended description',
            checkOwnership: true
        },
        {
            selector: '.committer',
            tagName: 'commit-author',
            description: 'Commit author info (name + authored date)',
            checkOwnership: false
        },
        {
            selector: '.contributors-charts .row h4, .contributors-charts .row p',
            tagName: 'contributor-info',
            description: 'Contributor name and email on contributors page',
            checkOwnership: false
        },
        {
            selector: '.network-graph, .project-network .controls',
            tagName: 'network-graph',
            description: 'Network graph (commits, avatars, branch names)',
            checkOwnership: false
        },

        // ---- Compare / MR creation page dropdowns (repo vs branch) ----
        {
            selector: '.js-source-project .dropdown-toggle-text, .js-target-project .dropdown-toggle-text',
            tagName: 'repo-selector',
            description: 'Selected repo/project name in compare/MR project dropdown',
            checkOwnership: false
        },
        {
            selector: '.js-source-branch .dropdown-toggle-text, .js-target-branch .dropdown-toggle-text, .compare-revision-cards span.gl-dropdown-button-text, .ref-selector span.gl-dropdown-button-text',
            tagName: 'branch-selector',
            description: 'Selected branch name in compare/MR branch dropdown',
            checkOwnership: false
        },
        {
            selector: '.dropdown-source-project .dropdown-content a, .dropdown-target-project .dropdown-content a',
            tagName: 'repo-option',
            description: 'Repo/project dropdown items on compare/MR pages',
            checkOwnership: false
        },
        {
            selector: '.js-source-branch-dropdown .dropdown-content a, .js-target-branch-dropdown .dropdown-content a, .git-revision-dropdown .dropdown-content a',
            tagName: 'branch-option',
            description: 'Branch dropdown items on compare/MR pages',
            checkOwnership: false
        },

        // ---- Issue titles ----
        {
            selector: '.issue-title-text a, .merge-request-title a, .issuable-header-text a, h1[data-qa-selector="title_content"], .title-container h1.title',
            tagName: 'issue-title',
            description: 'Issue or merge request title',
            checkOwnership: true
        },
        // Issue titles in list view
        {
            selector: '.issue-title-text, .issuable-info .title',
            tagName: 'issue-title-list',
            description: 'Issue title in list view',
            checkOwnership: true
        },

        // ---- Search results ----
        {
            selector: '.search-results a[data-track-property="search_result"] span.term, .search-results .str-truncated.gl-font-weight-bold',
            tagName: 'search-result-title',
            description: 'Issue/MR/etc. title in search results',
            checkOwnership: true
        },
        {
            selector: '.search-results .description.term',
            tagName: 'search-result-description',
            description: 'Description snippet in search results',
            checkOwnership: true
        },
        {
            selector: '.search-results .gl-text-gray-500.gl-my-3',
            tagName: 'search-result-meta',
            description: 'Project/issue reference line in search results',
            checkOwnership: true
        },

        // ---- Issue / MR body (first note is the description) ----
        {
            selector: '.detail-page-description .md, .issuable-details .description .md',
            tagName: 'issue-body',
            description: 'Issue/MR description',
            checkOwnership: false,
            checkNoteAuthor: true
        },

        // ---- Comments / notes on issues and MRs ----
        {
            selector: '.note-body .md, .timeline-entry .note-text',
            tagName: 'comment-content',
            description: 'Comment (note) content on issues/MRs',
            checkOwnership: false,
            checkNoteAuthor: true
        },

        // ---- Avatars ----
        // NOTE: Don't target img.avatar directly — replaced elements don't support ::before placeholder
        {
            selector: '.avatar-cell, .avatar-container, .js-avatar-container, .avatar-holder, .system-note-image.user-avatar, .gl-card-body > img.gl-avatar, .todo-avatar, .well-segment img.gl-avatar',
            tagName: 'user-avatar',
            description: 'User/commit author avatar container',
            checkOwnership: false
        },

        // ---- Issue / MR references ----
        {
            selector: '.issuable-reference',
            tagName: 'issue-reference',
            description: 'Issue/MR reference (e.g. namespace/project#123)',
            checkOwnership: true
        },

        // ---- User profiles / info ----
        {
            selector: '.user-info .user-name, .author-name, .commit-author-link, .author-link, .author, a.js-user-link, .dropdown-user-details',
            tagName: 'user-name',
            description: 'User display name',
            checkOwnership: false,
            checkUserLink: true
        },
        {
            selector: '.user-info .user-username, .author-username, span.username',
            tagName: 'user-username',
            description: 'User username',
            checkOwnership: false,
            checkUserLink: true
        },

        // ---- User popover (hover card) ----
        {
            selector: '[data-testid="user-popover"], .gl-popover .user-popover, .popover .user-popover',
            tagName: 'user-popover',
            description: 'User profile hover popover (name, bio, avatar, location)',
            checkOwnership: false
        },

        // ---- User profile page ----
        {
            selector: '.user-profile .cover-title',
            tagName: 'profile-name',
            description: 'User profile display name',
            checkOwnership: false,
            checkUserProfile: true
        },
        {
            selector: '.user-info .gl-text-gray-900',
            tagName: 'profile-info',
            description: 'User profile info rows (location, org, website, followers)',
            checkOwnership: false
        },
        {
            selector: '.user-profile .cover-desc, .profile-user-bio',
            tagName: 'user-bio',
            description: 'User biography on profile',
            checkOwnership: false,
            checkUserProfile: true
        },

        // ---- Snippets ----
        {
            selector: '.snippet-title, .snippet-header .title',
            tagName: 'snippet-title',
            description: 'Snippet title',
            checkOwnership: true
        },
        {
            selector: '.snippet-file-content .code, .snippet-file-content .blob-content',
            tagName: 'snippet-content',
            description: 'Snippet code content',
            checkOwnership: true
        },

        // ---- Merge request diff / changes ----
        {
            selector: '.diff-content .code, .diff-file .code',
            tagName: 'diff-content',
            description: 'Diff / code changes',
            checkOwnership: true
        },

        // ---- Labels in issue lists ----
        {
            selector: '.issuable-show-labels .label, .gl-label-text',
            tagName: 'label',
            description: 'Issue/MR labels',
            checkOwnership: true
        },

        // ---- Activity feed / events ----
        {
            selector: '.event-feed .event-title, .event-item .event-title',
            tagName: 'activity-title',
            description: 'Activity feed event title',
            checkOwnership: false
        },
        {
            selector: '.event-feed .event-body, .event-item .event-body',
            tagName: 'activity-body',
            description: 'Activity feed event body',
            checkOwnership: false
        },

        // ---- To-Do list page ----
        {
            selector: 'span.todo-target-title',
            tagName: 'todo-title',
            description: 'To-Do item title (MR/issue name)',
            checkOwnership: false
        },

        // ---- Dropdown menus (author filters, assignee filters, etc.) ----
        {
            selector: 'strong.dropdown-menu-user-full-name, .dropdown-menu-user-full-name',
            tagName: 'user-name',
            description: 'User full name in dropdown menus',
            checkOwnership: false
        },
        {
            selector: 'span.dropdown-menu-user-username, .dropdown-menu-user-username',
            tagName: 'user-username',
            description: 'Username in dropdown menus',
            checkOwnership: false
        },
        {
            selector: '.dropdown-menu-user-link > span.gl-relative',
            tagName: 'user-avatar',
            description: 'User avatar container in dropdown menus',
            checkOwnership: false
        },
        {
            selector: '.gl-dropdown-item img.gl-avatar',
            tagName: 'user-avatar',
            description: 'User avatar image in Vue gl-dropdown items (author filter, assignee filter, etc.)',
            checkOwnership: false
        },
        {
            selector: '.gl-dropdown-item .gl-dropdown-item-text-wrapper .gl-dropdown-item-text-primary',
            tagName: 'user-name',
            description: 'User/author name in Vue gl-dropdown items',
            checkOwnership: false,
            checkDropdownAvatar: true
        },
        {
            selector: '.gl-dropdown-item .gl-dropdown-item-text-wrapper .gl-dropdown-item-text-secondary',
            tagName: 'user-username',
            description: 'User/author secondary text in Vue gl-dropdown items',
            checkOwnership: false,
            checkDropdownAvatar: true
        },

        // ---- Search filter token values (e.g. Assignee = "Byte Blaze") ----
        {
            selector: '.js-visual-token .value-container, .filtered-search-token .value-container',
            tagName: 'filter-value',
            description: 'Filter token value (user/project name in search bar)',
            checkOwnership: false
        },

        // ---- Label filter dropdown items ----
        {
            selector: '#js-dropdown-label span.label-title, #js-dropdown-label .dropdown-label-box, .filter-dropdown-item span.label-title, .filter-dropdown-item .dropdown-label-box, .gl-filtered-search-suggestion-list .label-title, .gl-filtered-search-suggestion-list .dropdown-label-box, .gl-filtered-search-suggestion-list .gl-label-text, .gl-filtered-search-suggestion-list .dropdown-label-box + span, .gl-filtered-search-suggestion-list .dropdown-label-box ~ span',
            tagName: 'label-name',
            description: 'Label name and color in filter dropdown',
            checkOwnership: false
        },

        // ---- Filter dropdown items (project/group only, not action/type) ----
        {
            selector: '.dropdown-menu-project .dropdown-content li > a, .dropdown-menu-group .dropdown-content li > a',
            tagName: 'dropdown-project',
            description: 'Project/group names in filter dropdowns',
            checkOwnership: false
        },

        // ---- Deploy tokens / keys (settings pages) ----
        {
            selector: '.deploy-tokens .token-name, .deploy-keys .title',
            tagName: 'deploy-token-name',
            description: 'Deploy token or key name',
            checkOwnership: true
        },

        // ---- Wiki content ----
        {
            selector: '.wiki-page-content .md, .wiki .md',
            tagName: 'wiki-content',
            description: 'Wiki page content',
            checkOwnership: true
        },

        // ---- Release / tag notes ----
        {
            selector: '.release-block .release-header a, .release-block-title',
            tagName: 'release-title',
            description: 'Release title',
            checkOwnership: true
        },
        {
            selector: '.release-block .release-body .md',
            tagName: 'release-content',
            description: 'Release description/notes',
            checkOwnership: true
        },

        // ---- Members list ----
        {
            selector: '.member .user-info, .members-list .member-name',
            tagName: 'member-name',
            description: 'Project member name',
            checkOwnership: false,
            checkUserLink: true
        },
        {
            selector: 'td.col-meta a[href*="/"]',
            tagName: 'user-name',
            description: 'User name link in members table metadata (e.g. "by Byte Blaze")',
            checkOwnership: false,
            checkUserLink: true
        },

        // ---- Invite / autocomplete user dropdowns ----
        {
            selector: '.gl-avatar-labeled-label',
            tagName: 'user-name',
            description: 'User display name in avatar-labeled dropdowns (invite, autocomplete)',
            checkOwnership: false,
            checkUserLink: true
        },
        {
            selector: '.gl-avatar-labeled-sublabel',
            tagName: 'username',
            description: 'Username in avatar-labeled dropdowns (invite, autocomplete)',
            checkOwnership: false,
            checkUserLink: true
        },
        {
            selector: '.gl-avatar-labeled .gl-avatar',
            tagName: 'user-avatar',
            description: 'User avatar in avatar-labeled dropdowns (invite, autocomplete)',
            checkOwnership: false,
            checkUserLink: true
        },

        // ---- @-mention autocomplete dropdown (atwho plugin) ----
        {
            selector: '.atwho-view li',
            tagName: 'user-name',
            description: '@-mention autocomplete suggestion item (username + display name)',
            checkOwnership: false,
            skipEmptyCheck: true
        }
    ];

    let observer = null;
    let markedElements = new WeakSet();
    let currentUser = null;
    let projectOwner = null;

    console.log('[GitLab Marker] Initialized with', UNTRUSTED_SELECTORS.length, 'selectors');

    // =========================================================================
    // User / ownership detection helpers
    // =========================================================================

    /**
     * Get the currently logged-in GitLab user.
     * GitLab CE stores user info in the page's meta tags and the top-nav avatar.
     */
    function getCurrentUser() {
        if (currentUser) return currentUser;

        // Method 1: GitLab meta tag (available in CE 14+)
        const metaUser = document.querySelector('meta[name="current-user-username"]');
        if (metaUser) {
            currentUser = metaUser.content;
            console.log('[GitLab Marker] Current user (meta):', currentUser);
            return currentUser;
        }

        // Method 2: data attribute on body
        const body = document.body;
        if (body && body.dataset.currentUsername) {
            currentUser = body.dataset.currentUsername;
            console.log('[GitLab Marker] Current user (body data):', currentUser);
            return currentUser;
        }

        // Method 3: Top-nav avatar dropdown (common in GL CE)
        const avatar = document.querySelector('.header-user-avatar, .header-user .avatar, .js-nav-user-dropdown');
        if (avatar) {
            // The dropdown link text or data-user
            const parent = avatar.closest('a[href]');
            if (parent) {
                const match = parent.pathname.match(/^\/([^\/]+)$/);
                if (match) {
                    currentUser = match[1];
                    console.log('[GitLab Marker] Current user (avatar link):', currentUser);
                    return currentUser;
                }
            }
        }

        // Method 4: Look for user dropdown that contains "Signed in as"
        const signedInText = document.querySelector('.current-user .username, .sidebar-top-level-items .username');
        if (signedInText) {
            currentUser = signedInText.textContent.trim().replace('@', '');
            console.log('[GitLab Marker] Current user (sidebar):', currentUser);
            return currentUser;
        }

        // Method 5: WebArena/WASP default user - byteblaze
        // The VWA GitLab image logs in as byteblaze by default
        // This is a fallback; the agent should be logged in
        console.log('[GitLab Marker] Could not detect current user');
        return null;
    }

    /**
     * Get the project/namespace owner from the current URL.
     * GitLab URLs: /<namespace>/<project>/...
     */
    function getProjectOwner() {
        if (projectOwner) return projectOwner;

        // Try URL path: /<owner>/<project>/...
        const pathMatch = window.location.pathname.match(/^\/([^\/\-]+)\/([^\/]+)/);
        if (pathMatch && pathMatch[1] !== 'explore' && pathMatch[1] !== 'admin' &&
            pathMatch[1] !== 'dashboard' && pathMatch[1] !== 'users' &&
            pathMatch[1] !== 'groups' && pathMatch[1] !== 'search' &&
            pathMatch[1] !== 'help' && pathMatch[1] !== 'snippets') {
            projectOwner = pathMatch[1];
        }

        // Alternative: breadcrumb
        if (!projectOwner) {
            const breadcrumb = document.querySelector('.breadcrumbs-list li:first-child a');
            if (breadcrumb) {
                const match = breadcrumb.pathname.match(/^\/([^\/]+)/);
                if (match) {
                    projectOwner = match[1];
                }
            }
        }

        console.log('[GitLab Marker] Project owner:', projectOwner || 'unknown');
        return projectOwner;
    }

    /**
     * Should we hide content? (viewing someone else's project)
     */
    function shouldHideContent() {
        const user = getCurrentUser();
        const owner = getProjectOwner();

        if (!user) {
            console.log('[GitLab Marker] Not logged in - hiding all content');
            return true;
        }

        if (!owner) {
            return false; // No project context, let per-selector config decide
        }

        const shouldHide = user.toLowerCase() !== owner.toLowerCase();
        console.log('[GitLab Marker] User:', user, 'Owner:', owner, 'Hide:', shouldHide);
        return shouldHide;
    }

    /**
     * Get author of a GitLab note (comment) element.
     * GitLab uses .note elements with .note-header containing author info.
     */
    function getNoteAuthor(element) {
        // Walk up to the nearest .note or .timeline-entry
        const note = element.closest('.note, .timeline-entry');
        if (!note) return null;

        // Method 1: author link
        const authorLink = note.querySelector('.note-header .author-link, .note-header-author-name a');
        if (authorLink) {
            const match = authorLink.pathname.match(/^\/([^\/]+)/);
            if (match) {
                return match[1];
            }
            // Fallback: link text
            return authorLink.textContent.trim();
        }

        // Method 2: data attribute
        if (note.dataset.author) {
            return note.dataset.author;
        }

        // Method 3: avatar title
        const avatar = note.querySelector('.note-header img.avatar, .author img.avatar');
        if (avatar && avatar.alt) {
            return avatar.alt.replace("'s avatar", '').trim();
        }

        return null;
    }

    /**
     * Should we hide a note/comment? (from another user)
     */
    function shouldHideNote(element) {
        const user = getCurrentUser();
        if (!user) return true;

        const author = getNoteAuthor(element);
        if (!author) return true; // Can't determine, hide to be safe

        const shouldHide = user.toLowerCase() !== author.toLowerCase();
        console.log('[GitLab Marker] Note check - User:', user, 'Author:', author, 'Hide:', shouldHide);
        return shouldHide;
    }

    /**
     * Check if a user info element refers to another user.
     */
    function shouldHideUserInfo(element) {
        const currentUser = getCurrentUser();
        if (!currentUser) return true;

        let targetUser = null;

        // Try to get from link href
        const link = element.closest('a[href]') || element.querySelector('a[href]');
        if (link) {
            const match = link.pathname.match(/^\/([^\/]+)$/);
            if (match) {
                targetUser = match[1];
            }
        }

        // Try element text as username
        if (!targetUser) {
            const text = element.textContent.trim().replace('@', '');
            if (text && !text.includes(' ') && text.length < 40) {
                targetUser = text;
            }
        }

        if (!targetUser) return true;

        const shouldHide = currentUser.toLowerCase() !== targetUser.toLowerCase();
        console.log('[GitLab Marker] User info check - Current:', currentUser, 'Target:', targetUser, 'Hide:', shouldHide);
        return shouldHide;
    }

    /**
     * Check if viewing another user's profile page.
     */
    function shouldHideUserProfile(element) {
        const currentUser = getCurrentUser();
        if (!currentUser) return true;

        // Profile URL is /username or /users/username
        let profileUser = null;
        const match1 = window.location.pathname.match(/^\/users\/([^\/]+)/);
        const match2 = window.location.pathname.match(/^\/([^\/]+)$/);
        if (match1) {
            profileUser = match1[1];
        } else if (match2) {
            profileUser = match2[1];
        }

        if (!profileUser) return true;

        const shouldHide = currentUser.toLowerCase() !== profileUser.toLowerCase();
        console.log('[GitLab Marker] Profile check - Current:', currentUser, 'Profile:', profileUser, 'Hide:', shouldHide);
        return shouldHide;
    }

    /**
     * Check if a project in a list is owned by another user.
     */
    function shouldHideProjectInList(element) {
        const currentUser = getCurrentUser();
        if (!currentUser) return true;

        // Find the closest project row and extract owner from the project link
        const row = element.closest('.project-row, .project-card, li');
        if (!row) return true;

        const projectLink = row.querySelector('a.project, a[href*="/"]');
        if (!projectLink) return true;

        const match = projectLink.pathname.match(/^\/([^\/]+)\//);
        if (!match) return true;

        const owner = match[1];
        const shouldHide = currentUser.toLowerCase() !== owner.toLowerCase();
        console.log('[GitLab Marker] Project list check - Current:', currentUser, 'Owner:', owner, 'Hide:', shouldHide);
        return shouldHide;
    }

    // =========================================================================
    // Core marking logic
    // =========================================================================

    function markUntrustedElements() {
        let markedCount = 0;

        UNTRUSTED_SELECTORS.forEach(function(config) {
            const elements = document.querySelectorAll(config.selector);

            if (elements.length > 0) {
                console.log('[GitLab Marker] Found', elements.length, 'elements for:', config.description);
            }

            elements.forEach(function(element) {
                // Skip if already marked
                if (markedElements.has(element)) return;

                // Skip if already has reveal attributes
                if (element.hasAttribute('data-untrusted-element')) {
                    markedElements.add(element);
                    return;
                }

                // Skip if a parent is already marked (prevents nested double-hiding)
                var parent = element.parentElement;
                var parentMarked = false;
                while (parent) {
                    if (parent.hasAttribute('data-untrusted-element')) {
                        parentMarked = true;
                        break;
                    }
                    parent = parent.parentElement;
                }
                if (parentMarked) {
                    markedElements.add(element);
                    return;
                }

                // Skip empty elements (but not avatars/images/user-links which may wrap only an img,
                // and not elements with skipEmptyCheck like async-loaded editors)
                var hasImageContent = config.tagName === 'user-avatar' || config.tagName === 'project-icon'
                    || element.querySelector('img') !== null;
                if (!hasImageContent && !config.skipEmptyCheck && (!element.textContent || element.textContent.trim().length === 0)) return;

                // Determine if this element should be hidden
                let shouldHide = false;

                if (config.checkDropdownAvatar) {
                    // Hide only if this dropdown row is actually a user row with avatar.
                    // This avoids masking non-user dropdown entries (e.g., Label values).
                    const item = element.closest('.gl-dropdown-item');
                    shouldHide = !!(item && item.querySelector('img.gl-avatar, .gl-avatar'));
                } else if (config.checkNoteAuthor) {
                    shouldHide = shouldHideNote(element);
                } else if (config.checkUserLink) {
                    shouldHide = shouldHideUserInfo(element);
                } else if (config.checkUserProfile) {
                    shouldHide = shouldHideUserProfile(element);
                } else if (config.checkProjectList) {
                    shouldHide = shouldHideProjectInList(element);
                } else if (config.checkOwnership === false) {
                    shouldHide = true; // Always hide
                } else {
                    shouldHide = shouldHideContent(); // Check project ownership
                }

                // Only mark if should be hidden
                if (!shouldHide) {
                    markedElements.add(element);
                    return;
                }

                // Determine tag name — override to user-avatar if element has only an image, no text
                var effectiveTagName = config.tagName;
                if (config.tagName === 'user-name' && element.querySelector('img') && (!element.textContent || element.textContent.trim().length === 0)) {
                    effectiveTagName = 'user-avatar';
                }

                // Wrap bare <img> elements in a <span> so ::before placeholder works
                if (element.tagName === 'IMG') {
                    var wrapper = document.createElement('span');
                    wrapper.style.display = 'inline-block';
                    element.parentNode.insertBefore(wrapper, element);
                    wrapper.appendChild(element);
                    element = wrapper;
                }

                // Mark as untrusted
                element.setAttribute('data-untrusted', 'true');
                element.setAttribute('data-untrusted-element', 'true');
                element.setAttribute('data-tag-name', effectiveTagName);

                // Strip title/aria-label to prevent content leaking via hover tooltips
                // Check element, its children, AND its ancestors up to 3 levels
                if (element.hasAttribute('title')) element.removeAttribute('title');
                if (element.hasAttribute('aria-label')) element.removeAttribute('aria-label');
                element.querySelectorAll('[title], [aria-label]').forEach(function(child) {
                    child.removeAttribute('title');
                    child.removeAttribute('aria-label');
                });
                var ancestor = element.parentElement;
                for (var i = 0; i < 3 && ancestor; i++) {
                    if (ancestor.hasAttribute('title')) ancestor.removeAttribute('title');
                    if (ancestor.hasAttribute('aria-label')) ancestor.removeAttribute('aria-label');
                    ancestor = ancestor.parentElement;
                }

                markedElements.add(element);
                markedCount++;
            });
        });

        if (markedCount > 0) {
            console.log('[GitLab Marker] Marked', markedCount, 'untrusted elements');
        }

        return markedCount;
    }

    function setupObserver() {
        observer = new MutationObserver(function(mutations) {
            let shouldMark = false;
            mutations.forEach(function(mutation) {
                mutation.addedNodes.forEach(function(node) {
                    if (node.nodeType === 1) {
                        // Strip stale reveal attributes from cloned/re-inserted nodes
                        // so they get fresh QLLM IDs assigned by reveal.js
                        var staleEls = node.querySelectorAll ? 
                            node.querySelectorAll('[data-reveal-processed]') : [];
                        staleEls.forEach(function(el) {
                            el.removeAttribute('data-reveal-processed');
                            el.removeAttribute('data-qllm-id');
                            el.removeAttribute('data-reveal-placeholder');
                        });
                        if (node.hasAttribute && node.hasAttribute('data-reveal-processed')) {
                            node.removeAttribute('data-reveal-processed');
                            node.removeAttribute('data-qllm-id');
                            node.removeAttribute('data-reveal-placeholder');
                        }
                        shouldMark = true;
                    }
                });
            });
            if (shouldMark) {
                markUntrustedElements();
            }
        });

        observer.observe(document.body, {
            childList: true,
            subtree: true
        });

        console.log('[GitLab Marker] Observer setup complete');
    }

    // Periodically strip title/aria-label from marked elements (GitLab re-adds them)
    function setupTooltipCleaner() {
        setInterval(function() {
            document.querySelectorAll('[data-untrusted="true"]').forEach(function(el) {
                if (el.hasAttribute('title')) el.removeAttribute('title');
                if (el.hasAttribute('aria-label')) el.removeAttribute('aria-label');
                el.querySelectorAll('[title], [aria-label]').forEach(function(child) {
                    child.removeAttribute('title');
                    child.removeAttribute('aria-label');
                });
            });
        }, 1000);
    }

    // =========================================================================
    // Initialization
    // =========================================================================

    function init() {
        // Check if reveal_all is enabled
        const urlParams = new URLSearchParams(window.location.search);
        const revealAll = urlParams.get('reveal_all') === 'true';
        const storedMode = localStorage.getItem('reveal_mode');
        const revealAllFromStorage = storedMode === 'all';

        if (revealAll || revealAllFromStorage) {
            console.log('[GitLab Marker] reveal_all=true - SKIPPING ALL MARKING');
            // Remove pre-hide CSS since we're revealing everything
            var prehide = document.getElementById('gitlab-prehide-css');
            if (prehide) prehide.remove();
            return;
        }

        console.log('[GitLab Marker] Starting marking');
        projectOwner = null; // Reset on page load
        const count = markUntrustedElements();
        setupObserver();
        setupTooltipCleaner();

        // Dispatch event so reveal.js processes marked elements and removes pre-hide CSS.
        // reveal.js will: 1) add reveal-hidden class to marked elements, 2) remove pre-hide CSS.
        document.dispatchEvent(new CustomEvent('gitlab-marked', { detail: { count: count } }));
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Re-run on Turbolinks/PJAX navigation (GitLab uses these for in-app navigation)
    document.addEventListener('turbolinks:load', init);
    document.addEventListener('page:change', init);
    document.addEventListener('ajax:complete', function() {
        setTimeout(markUntrustedElements, 200);
    });

    // =========================================================================
    // Task tracking (issue creation, comment submission, etc.)
    // =========================================================================

    function trackIssueCreation() {
        // GitLab uses form with #new_issue or action containing /issues
        const issueForms = document.querySelectorAll('form[action*="/issues"], form#new_issue');
        issueForms.forEach(form => {
            if (form.dataset.issueFormTracked) return;
            form.dataset.issueFormTracked = 'true';

            form.addEventListener('submit', function(e) {
                const titleInput = form.querySelector('input[name="issue[title]"], input[name="title"]');
                const descArea = form.querySelector('textarea[name="issue[description]"], textarea[name="description"]');

                const title = titleInput ? titleInput.value : '';
                const desc = descArea ? descArea.value : '';

                console.log('[GitLab Marker] Issue form submitted, title:', title);

                if (window.SecurityTracker && typeof window.SecurityTracker.onTaskComplete === 'function') {
                    window.SecurityTracker.onTaskComplete({
                        action: 'issue_created',
                        url: window.location.href,
                        title: title,
                        description_length: desc.length
                    });
                }
            }, true);
        });
    }

    function trackCommentSubmission() {
        // GitLab note (comment) forms
        const noteForms = document.querySelectorAll('form.new-note, form[action*="/notes"], form.js-main-target-form');
        noteForms.forEach(form => {
            if (form.dataset.commentFormTracked) return;
            form.dataset.commentFormTracked = 'true';

            form.addEventListener('submit', function(e) {
                const textarea = form.querySelector('textarea[name="note[note]"], textarea.note-textarea');
                const commentText = textarea ? textarea.value : '';

                console.log('[GitLab Marker] Comment form submitted, length:', commentText.length);

                if (window.SecurityTracker && typeof window.SecurityTracker.onTaskComplete === 'function') {
                    window.SecurityTracker.onTaskComplete({
                        action: 'comment_submitted',
                        url: window.location.href,
                        comment_text_length: commentText.length
                    });
                }
            }, true);
        });
    }

    function trackSettingsChanges() {
        // Track deploy token/key forms
        const deployForms = document.querySelectorAll(
            'form[action*="/deploy_tokens"], form[action*="/deploy_keys"]'
        );
        deployForms.forEach(form => {
            if (form.dataset.settingsTracked) return;
            form.dataset.settingsTracked = 'true';

            form.addEventListener('submit', function(e) {
                console.log('[GitLab Marker] Settings form submitted:', form.action);

                if (window.SecurityTracker && typeof window.SecurityTracker.onTaskComplete === 'function') {
                    window.SecurityTracker.onTaskComplete({
                        action: 'settings_changed',
                        url: window.location.href,
                        form_action: form.action
                    });
                }
            }, true);
        });
    }

    // Track forms initially and periodically
    trackIssueCreation();
    trackCommentSubmission();
    trackSettingsChanges();
    setInterval(function() {
        markUntrustedElements();
        trackIssueCreation();
        trackCommentSubmission();
        trackSettingsChanges();
    }, 2000);

})();
