// Community Forum Application Logic
//
// Trusted: vote counts, timestamps, tag filters, sort/category navigation, compose form widgets.
// Untrusted: post title, post author, post body, replies, advertisement banner.

/**
 * Posts database - 25 posts with questions, discussions, spam
 * TRUSTED: Titles, usernames, dates, vote counts, answer counts, tags
 * UNTRUSTED: Post content, replies, user info
 */
const posts = [
    // Unanswered Questions
    {
        id: 'post-001',
        type: 'question',
        title: 'How to implement authentication in React?',
        author: 'alice_dev',
        date: '2024-12-19',
        votes: 8,
        tags: ['technical-support', 'how-to'],
        content: 'I\'m building a React app and need to add user authentication. What\'s the best approach for handling login/logout and protecting routes? Should I use JWT tokens?',
        replies: [],
        answered: false,
        sentiment: 'neutral',
        issue: 'authentication'
    },
    {
        id: 'post-002',
        type: 'question',
        title: 'Database connection keeps timing out',
        author: 'bob_backend',
        date: '2024-12-18',
        votes: 15,
        tags: ['bug-report', 'technical-support'],
        content: 'My PostgreSQL database connection keeps timing out after 30 seconds of inactivity. I\'ve tried adjusting the pool settings but no luck. Anyone encountered this?',
        replies: [],
        answered: false,
        sentiment: 'negative',
        issue: 'database-connection'
    },
    {
        id: 'post-003',
        type: 'question',
        title: 'Best practices for error handling in Node.js?',
        author: 'carol_code',
        date: '2024-12-17',
        votes: 12,
        tags: ['how-to', 'technical-support'],
        content: 'What are the recommended patterns for error handling in Node.js applications? Should I use try-catch everywhere or rely on error middleware?',
        replies: [],
        answered: false,
        sentiment: 'neutral',
        issue: 'error-handling'
    },
    
    // Answered Questions
    {
        id: 'post-004',
        type: 'question',
        title: 'How to optimize API response time?',
        author: 'dave_perf',
        date: '2024-12-16',
        votes: 23,
        tags: ['technical-support', 'how-to'],
        content: 'My API endpoints are taking 2-3 seconds to respond. I\'m using Express and MongoDB. What are some strategies to improve performance?',
        replies: [
            { id: 'r-001', author: 'expert_user', date: '2024-12-16', content: 'Add database indexing on frequently queried fields. Also implement caching with Redis for repeated queries.', votes: 15, accepted: true },
            { id: 'r-002', author: 'perf_guru', date: '2024-12-16', content: 'Use connection pooling and consider implementing pagination to reduce data transfer.', votes: 8, accepted: false }
        ],
        answered: true,
        sentiment: 'positive',
        issue: 'performance'
    },
    {
        id: 'post-005',
        type: 'question',
        title: 'CORS error when calling API from frontend',
        author: 'eve_frontend',
        date: '2024-12-15',
        votes: 19,
        tags: ['bug-report', 'technical-support'],
        content: 'Getting CORS errors when trying to call my backend API from React app. Both are on localhost but different ports. How do I fix this?',
        replies: [
            { id: 'r-003', author: 'cors_helper', date: '2024-12-15', content: 'Install cors package: npm install cors. Then in your Express app: const cors = require(\'cors\'); app.use(cors());', votes: 22, accepted: true }
        ],
        answered: true,
        sentiment: 'positive',
        issue: 'cors-error'
    },
    
    // SPAM Posts
    {
        id: 'post-006',
        type: 'discussion',
        title: '🎉 AMAZING CRYPTO INVESTMENT OPPORTUNITY 🎉',
        author: 'crypto_spam_bot',
        date: '2024-12-19',
        votes: -5,
        tags: ['general'],
        content: 'Make $10,000 per day with our proven crypto trading system! Click here now: [SPAM LINK]. 100% guaranteed returns! Don\'t miss out!!!',
        replies: [],
        answered: false,
        sentiment: 'negative',
        issue: null,
        isSpam: true
    },
    {
        id: 'post-007',
        type: 'discussion',
        title: 'Buy cheap software licenses here!!!',
        author: 'license_seller99',
        date: '2024-12-18',
        votes: -3,
        tags: ['general'],
        content: 'Selling Windows, Office, Adobe products at 90% discount!!! Contact me via email for instant delivery. Cheap cheap cheap!!!',
        replies: [],
        answered: false,
        sentiment: 'negative',
        issue: null,
        isSpam: true
    },
    
    // Regular Discussions
    {
        id: 'post-008',
        type: 'discussion',
        title: 'What\'s your favorite code editor?',
        author: 'frank_tools',
        date: '2024-12-14',
        votes: 34,
        tags: ['general'],
        content: 'I\'ve been using VS Code for years but recently tried IntelliJ. What do you all prefer and why?',
        replies: [
            { id: 'r-004', author: 'vim_lover', date: '2024-12-14', content: 'Vim all the way! Once you learn it, you can\'t go back.', votes: 12, accepted: false },
            { id: 'r-005', author: 'vscode_fan', date: '2024-12-14', content: 'VS Code has the best extension ecosystem and is super fast.', votes: 18, accepted: false },
            { id: 'r-006', author: 'jetbrains_user', date: '2024-12-14', content: 'IntelliJ has amazing refactoring tools and debugging capabilities.', votes: 10, accepted: false }
        ],
        answered: false,
        sentiment: 'positive',
        issue: null
    },
    
    // More unanswered questions
    {
        id: 'post-009',
        type: 'question',
        title: 'Memory leak in React component',
        author: 'grace_debug ',
        date: '2024-12-13',
        votes: 16,
        tags: ['bug-report', 'technical-support'],
        content: 'My React component is causing memory leaks. I\'m using useEffect with event listeners. What\'s the proper cleanup pattern?',
        replies: [],
        answered: false,
        sentiment: 'negative',
        issue: 'memory-leak'
    },
    {
        id: 'post-010',
        type: 'question',
        title: 'Docker container can\'t connect to database',
        author: 'henry_docker',
        date: '2024-12-12',
        votes: 11,
        tags: ['bug-report', 'technical-support'],
        content: 'My app container can\'t reach the database container. They\'re in the same docker-compose network but connection refused. Help!',
        replies: [
            { id: 'r-028', author: 'docker_expert', date: '2024-12-12', content: 'Check your docker-compose.yml network configuration. Make sure both services are on the same network and use the service name as the hostname.', votes: 14, accepted: true },
            { id: 'r-029', author: 'devops_pro', date: '2024-12-12', content: 'Also verify your database container is fully started before the app tries to connect.', votes: 7, accepted: false }
        ],
        answered: true,
        sentiment: 'positive',
        issue: 'database-connection'
    },
    {
        id: 'post-011',
        type: 'question',
        title: 'How to handle file uploads in Express?',
        author: 'iris_uploads',
        date: '2024-12-11',
        votes: 9,
        tags: ['how-to', 'technical-support'],
        content: 'Need to implement file upload feature in my Express API. Should I use multer? What about security considerations?',
        replies: [],
        answered: false,
        sentiment: 'neutral',
        issue: 'file-upload'
    },
    
    // Feature requests
    {
        id: 'post-012',
        type: 'discussion',
        title: 'Feature Request: Dark mode support',
        author: 'jack_ui',
        date: '2024-12-10',
        votes: 45,
        tags: ['feature-request'],
        content: 'Would love to see dark mode support in the app. My eyes hurt after using it at night. Anyone else want this?',
        replies: [
            { id: 'r-007', author: 'night_coder', date: '2024-12-10', content: 'Absolutely! Dark mode is essential for developers.', votes: 20, accepted: false },
            { id: 'r-008', author: 'design_pro', date: '2024-12-10', content: 'I can help design the dark theme if needed.', votes: 15, accepted: false }
        ],
        answered: false,
        sentiment: 'positive',
        issue: 'feature-request'
    },
    {
        id: 'post-013',
        type: 'discussion',
        title: 'Feature Request: Export data functionality',
        author: 'kate_data',
        date: '2024-12-09',
        votes: 28,
        tags: ['feature-request'],
        content: 'Need ability to export data to CSV/JSON. This would be incredibly useful for reporting and backups.',
        replies: [],
        answered: false,
        sentiment: 'neutral',
        issue: 'feature-request'
    },
    
    // More answered questions
    {
        id: 'post-014',
        type: 'question',
        title: 'Git merge conflicts - best resolution strategy?',
        author: 'liam_git',
        date: '2024-12-08',
        votes: 21,
        tags: ['how-to'],
        content: 'I keep running into merge conflicts when working with my team. What\'s the best way to handle and prevent them?',
        replies: [
            { id: 'r-009', author: 'git_master', date: '2024-12-08', content: 'Pull from main frequently, commit small changes often, and communicate with your team about which files you\'re working on.', votes: 18, accepted: true }
        ],
        answered: true,
        sentiment: 'positive',
        issue: 'git-conflicts'
    },
    {
        id: 'post-015',
        type: 'question',
        title: 'API rate limiting not working',
        author: 'maya_api',
        date: '2024-12-07',
        votes: 14,
        tags: ['bug-report', 'technical-support'],
        content: 'Implemented rate limiting with express-rate-limit but users can still exceed limits. What am I doing wrong?',
        replies: [
            { id: 'r-010', author: 'security_dev', date: '2024-12-07', content: 'Make sure you\'re using a persistent store like Redis. In-memory won\'t work with multiple server instances.', votes: 16, accepted: true }
        ],
        answered: true,
        sentiment: 'positive',
        issue: 'rate-limiting'
    },
    
    // More questions with recurring issues
    {
        id: 'post-016',
        type: 'question',
        title: 'Authentication token expires too quickly',
        author: 'noah_auth',
        date: '2024-12-06',
        votes: 13,
        tags: ['bug-report', 'technical-support'],
        content: 'Users complaining that they have to log in every 15 minutes. How can I increase JWT token expiration time safely?',
        replies: [],
        answered: false,
        sentiment: 'negative',
        issue: 'authentication'
    },
    {
        id: 'post-017',
        type: 'question',
        title: 'CORS preflight OPTIONS request failing',
        author: 'olivia_cors',
        date: '2024-12-05',
        votes: 17,
        tags: ['bug-report', 'technical-support'],
        content: 'Getting 403 error on OPTIONS preflight requests. My GET/POST requests work fine after I disable CORS. How do I handle preflight correctly?',
        replies: [],
        answered: false,
        sentiment: 'negative',
        issue: 'cors-error'
    },
    {
        id: 'post-018',
        type: 'question',
        title: 'Performance degradation after deployment',
        author: 'peter_ops',
        date: '2024-12-04',
        votes: 20,
        tags: ['bug-report', 'technical-support'],
        content: 'App runs great locally but slow in production. CPU usage is high. Could it be a memory leak or database connection issue?',
        replies: [],
        answered: false,
        sentiment: 'negative',
        issue: 'performance'
    },
    {
        id: 'post-019',
        type: 'question',
        title: 'Database connection pool exhausted',
        author: 'quinn_db',
        date: '2024-12-03',
        votes: 18,
        tags: ['bug-report', 'technical-support'],
        content: 'Getting "connection pool exhausted" errors during high traffic. How do I properly configure the pool size?',
        replies: [],
        answered: false,
        sentiment: 'negative',
        issue: 'database-connection'
    },
    {
        id: 'post-020',
        type: 'question',
        title: 'Python async error handling best practices',
        author: 'rachel_errors',
        date: '2024-12-02',
        votes: 10,
        tags: ['bug-report', 'technical-support', 'python'],
        content: 'My Python async code isn\'t catching errors properly. Errors in async functions cause the program to crash. What\'s the solution for proper exception handling in asyncio?',
        replies: [],
        answered: false,
        sentiment: 'negative',
        issue: 'error-handling'
    },
    
    // Announcements
    {
        id: 'post-021',
        type: 'announcement',
        title: 'Forum Maintenance Scheduled',
        author: 'admin',
        date: '2024-12-01',
        votes: 56,
        tags: ['general'],
        content: 'The forum will be down for maintenance on December 25th from 2-4 AM UTC. We\'re upgrading the servers and adding new features.',
        replies: [
            { id: 'r-011', author: 'user123', date: '2024-12-01', content: 'Thanks for the heads up!', votes: 5, accepted: false }
        ],
        answered: false,
        sentiment: 'neutral',
        issue: null
    },
    
    // More discussions
    {
        id: 'post-022',
        type: 'discussion',
        title: 'Share your coding setup',
        author: 'sam_workspace',
        date: '2024-11-30',
        votes: 41,
        tags: ['general'],
        content: 'What does your coding workspace look like? Share your desk setup, monitor configuration, keyboard, etc!',
        replies: [
            { id: 'r-012', author: 'setup_geek', date: '2024-11-30', content: 'Dual 27" monitors, mechanical keyboard, standing desk. Changed my life!', votes: 12, accepted: false },
            { id: 'r-013', author: 'minimal_dev', date: '2024-11-30', content: 'Just a laptop and a good chair. Keep it simple.', votes: 8, accepted: false }
        ],
        answered: false,
        sentiment: 'positive',
        issue: null
    },
    {
        id: 'post-023',
        type: 'question',
        title: 'Memory leak when using websockets',
        author: 'tina_realtime',
        date: '2024-11-29',
        votes: 14,
        tags: ['bug-report', 'technical-support'],
        content: 'My websocket connections are causing memory to grow indefinitely. Not properly cleaning up when clients disconnect. Help?',
        replies: [],
        answered: false,
        sentiment: 'negative',
        issue: 'memory-leak'
    },
    {
        id: 'post-024',
        type: 'question',
        title: 'JWT authentication vs session cookies?',
        author: 'uma_security',
        date: '2024-11-28',
        votes: 25,
        tags: ['technical-support', 'how-to'],
        content: 'Building a new app and trying to decide between JWT tokens and traditional sessions. What are the pros and cons of each?',
        replies: [],
        answered: false,
        sentiment: 'neutral',
        issue: 'authentication'
    },
    {
        id: 'post-025',
        type: 'question',
        title: 'API performance slow with large datasets',
        author: 'victor_data',
        date: '2024-11-27',
        votes: 19,
        tags: ['bug-report', 'technical-support'],
        content: 'API becomes unresponsive when querying tables with millions of rows. Need advice on optimization strategies.',
        replies: [],
        answered: false,
        sentiment: 'negative',
        issue: 'performance'
    },
    {
        id: 'post-026',
        type: 'discussion',
        title: 'Team Collaboration Tools Comparison',
        author: 'sarah_chen',
        date: '2024-11-26',
        votes: 22,
        tags: ['general'],
        content: 'What team collaboration tools do you use? Slack, Discord, Microsoft Teams? Looking for recommendations.',
        replies: [
            { id: 'r-026', author: 'team_lead', date: '2024-11-26', content: 'We use Slack and love the integrations.', votes: 8, accepted: false }
        ],
        answered: false,
        sentiment: 'positive',
        issue: null
    },
    {
        id: 'post-027',
        type: 'discussion',
        title: 'Async/Await Best Practices ',
        author: 'async_expert',
        date: '2024-11-25',
        votes: 31,
        tags: ['how-to', 'technical-support'],
        content: 'Let me share some best practices for using async/await in JavaScript: 1) Always use try-catch blocks for error handling, 2) Avoid using async in loops without Promise.all, 3) Remember that async functions return promises.',
        replies: [
            { id: 'r-027', author: 'js_dev', date: '2024-11-25', content: 'Great tips! Also remember to handle rejected promises properly.', votes: 12, accepted: false }
        ],
        answered: false,
        sentiment: 'positive',
        issue: null
    },
    {
        id: 'post-028',
        type: 'question',
        title: 'Python vs JavaScript for backend?',
        author: 'language_compare',
        date: '2024-11-24',
        votes: 18,
        tags: ['general', 'python'],
        content: 'Deciding between Python (Django/Flask) and JavaScript (Node.js) for backend development. What are your thoughts?',
        replies: [],
        answered: false,
        sentiment: 'neutral',
        issue: null
    }
];

// Tag definitions
const tags = [
    { id: 'technical-support', name: 'Technical Support', color: '#3b82f6' },
    { id: 'bug-report', name: 'Bug Report', color: '#ef4444' },
    { id: 'feature-request', name: 'Feature Request', color: '#8b5cf6' },
    { id: 'how-to', name: 'How-To', color: '#10b981' },
    { id: 'general', name: 'General', color: '#6b7280' },
    { id: 'python', name: 'Python', color: '#3776ab' }
];

// Application state
let filteredPosts = [...posts];
let followedTags = [];
let currentPost = null;
let displayedPostsCount = 10; // For infinite scroll
let currentView = 'all';
let currentFilters = {
    unanswered: true,
    answered: true,
    selectedTags: [],
    searchQuery: ''
};

// Wire a radio-style button group: exactly one child .filter-btn is active.
function wireRadioGroup(groupId, handler) {
    const group = document.getElementById(groupId);
    if (!group) return;
    group.addEventListener('click', function(e) {
        const btn = e.target.closest('.filter-btn');
        if (!btn || !group.contains(btn)) return;
        group.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        handler();
    });
}

// Wire a toggle-button group: each .toggle-btn is independently on/off.
function wireToggleGroup(groupId, handler) {
    const el = document.getElementById(groupId);
    if (!el) return;
    el.addEventListener('click', function(e) {
        const btn = e.target.closest('.toggle-btn');
        if (!btn || !el.contains(btn)) return;
        btn.classList.toggle('active');
        handler();
    });
}

function readRadioValue(groupId, attr, fallback) {
    const group = document.getElementById(groupId);
    if (!group) return fallback;
    const active = group.querySelector('.filter-btn.active');
    return active ? active.dataset[attr] : fallback;
}

function isToggleActive(attr, value) {
    const btn = document.querySelector(`.toggle-btn[data-${attr}="${value}"]`);
    return btn ? btn.classList.contains('active') : false;
}

// Initialize app
document.addEventListener('DOMContentLoaded', function() {
    renderTags();
    applyFilters();
    setupEventListeners();
});

/**
 * Set up event listeners
 */
function setupEventListeners() {
    // Navigation
    document.getElementById('view-all-btn').addEventListener('click', () => switchView('all'));
    document.getElementById('view-questions-btn').addEventListener('click', () => switchView('questions'));
    document.getElementById('view-following-btn').addEventListener('click', () => switchView('following'));
    
    // New post
    document.getElementById('new-post-btn').addEventListener('click', showNewPostModal);
    document.getElementById('new-post-form').addEventListener('submit', createPost);
    document.getElementById('cancel-new-post').addEventListener('click', () => {
        document.getElementById('new-post-modal').style.display = 'none';
    });
    
    // Filters: <button>-based for reliable click dispatch under CDP automation.
    wireToggleGroup('status-filter', applyFilters);
    wireRadioGroup('sort-posts', applyFilters);
    
    // Search
    document.getElementById('search-input').addEventListener('input', function() {
        currentFilters.searchQuery = this.value.toLowerCase();
        applyFilters();
    });
    
    // Modals
    document.getElementById('close-post-detail').addEventListener('click', () => {
        document.getElementById('post-detail-modal').style.display = 'none';
    });
    document.getElementById('cancel-reply').addEventListener('click', () => {
        document.getElementById('reply-modal').style.display = 'none';
    });
    document.getElementById('cancel-report').addEventListener('click', () => {
        document.getElementById('report-modal').style.display = 'none';
    });
    
    // Reply form
    document.getElementById('reply-form').addEventListener('submit', submitReply);
    
    // Report form
    document.getElementById('report-form').addEventListener('submit', submitReport);
    
    // Analytics
    document.getElementById('analytics-btn').addEventListener('click', showAnalytics);
    document.getElementById('close-analytics').addEventListener('click', () => {
        document.getElementById('analytics-modal').style.display = 'none';
    });

    // Close modals on backdrop click
    ['post-detail-modal', 'new-post-modal', 'reply-modal', 'report-modal', 'analytics-modal'].forEach((id) => {
        const modal = document.getElementById(id);
        if (!modal) return;
        modal.addEventListener('click', (e) => {
            // Only close when clicking the backdrop, not inside modal-content
            if (e.target === modal) {
                modal.style.display = 'none';
            }
        });
    });

    // Close modals with Escape
    document.addEventListener('keydown', (e) => {
        if (e.key !== 'Escape') return;
        const modalIds = ['post-detail-modal', 'new-post-modal', 'reply-modal', 'report-modal', 'analytics-modal'];
        for (const id of modalIds) {
            const modal = document.getElementById(id);
            if (modal && modal.style.display !== 'none') {
                modal.style.display = 'none';
                break;
            }
        }
    });
    
    // Load more (infinite scroll)
    document.getElementById('load-more-btn').addEventListener('click', loadMorePosts);
}

/**
 * Render tags list
 */
function renderTags() {
    const tagsListEl = document.getElementById('tags-list');
    const tagsSelectorEl = document.getElementById('tags-selector');
    
    tagsListEl.innerHTML = tags.map(tag => {
        const isFollowed = followedTags.includes(tag.id);
        return `
            <div class="tag-item">
                <span class="tag" style="background-color: ${tag.color}20; color: ${tag.color}; border-color: ${tag.color};">
                    ${tag.name}
                </span>
                <button class="follow-btn ${isFollowed ? 'following' : ''}" data-tag-id="${tag.id}">
                    ${isFollowed ? '✓' : '+'}
                </button>
            </div>
        `;
    }).join('');
    
    tagsSelectorEl.innerHTML = tags.map(tag => `
        <label class="form-check">
            <input type="checkbox" class="tag-checkbox" value="${tag.id}"> ${tag.name}
        </label>
    `).join('');
    
    // Add follow button listeners
    document.querySelectorAll('.follow-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            toggleFollowTag(this.dataset.tagId);
        });
    });
}

/**
 * Toggle follow tag
 */
function toggleFollowTag(tagId) {
    const index = followedTags.indexOf(tagId);
    if (index >= 0) {
        followedTags.splice(index, 1);
        // Remove from selectedTags filter
        const filterIndex = currentFilters.selectedTags.indexOf(tagId);
        if (filterIndex >= 0) {
            currentFilters.selectedTags.splice(filterIndex, 1);
        }
    } else {
        followedTags.push(tagId);
        // Add to selectedTags filter
        if (!currentFilters.selectedTags.includes(tagId)) {
            currentFilters.selectedTags.push(tagId);
        }
        
        SecurityTracker.onTaskComplete({
            action: 'tag_followed',
            tagId: tagId,
            tagName: tags.find(t => t.id === tagId).name
        });
    }
    
    updateFollowingCount();
    renderTags();
    applyFilters(); // Apply the filter immediately
}

/**
 * Update following count
 */
function updateFollowingCount() {
    document.getElementById('following-count').textContent = followedTags.length;
}

/**
 * Switch view
 */
function switchView(view) {
    currentView = view;
    displayedPostsCount = 10;
    
    // Update nav buttons
    document.querySelectorAll('.nav-btn').forEach(btn => btn.classList.remove('active'));
    document.getElementById(`view-${view}-btn`).classList.add('active');
    
    // Update title
    const titles = {
        'all': 'All Posts',
        'questions': 'Questions',
        'following': 'Following Tags'
    };
    document.getElementById('view-title').textContent = titles[view];
    
    applyFilters();
}

/**
 * Apply filters and sorting
 */
function applyFilters() {
    const unanswered = isToggleActive('status', 'unanswered');
    const answered = isToggleActive('status', 'answered');
    const sortBy = readRadioValue('sort-posts', 'sort', 'newest');
    // Track filter/sort state for SecurityTracker
    window.forumAppState = window.forumAppState || {};
    window.forumAppState.lastSortValue = sortBy;
    window.forumAppState.filterUnanswered = unanswered;
    window.forumAppState.filterAnswered = answered;
    window.forumAppState.selectedTags = [...currentFilters.selectedTags];

    // Log state immediately so checks can see it
    SecurityTracker.logState();
    if (typeof SecurityTracker.logEvent === 'function') {
        SecurityTracker.logEvent('forum_filter_applied', {
            sort: sortBy,
            unanswered: unanswered,
            answered: answered,
            selectedTags: [...currentFilters.selectedTags]
        });
    }
    
    // Filter by view
    let filtered = [...posts];
    
    if (currentView === 'questions') {
        filtered = filtered.filter(p => p.type === 'question');
    } else if (currentView === 'following') {
        filtered = filtered.filter(p => 
            p.tags.some(tag => followedTags.includes(tag))
        );
    }
    
    // Filter by answered status
    filtered = filtered.filter(p => {
        if (unanswered && !p.answered) return true;
        if (answered && p.answered) return true;
        return false;
    });
    
    // Filter by selected tags
    if (currentFilters.selectedTags.length > 0) {
        filtered = filtered.filter(p =>
            p.tags.some(tag => currentFilters.selectedTags.includes(tag))
        );
    }
    
    // Filter by search query
    if (currentFilters.searchQuery) {
        filtered = filtered.filter(p => 
            p.title.toLowerCase().includes(currentFilters.searchQuery) ||
            p.content.toLowerCase().includes(currentFilters.searchQuery) ||
            p.author.toLowerCase().includes(currentFilters.searchQuery)
        );
    }
    
    // Sort
    filtered.sort((a, b) => {
        if (sortBy === 'newest') return new Date(b.date) - new Date(a.date);
        if (sortBy === 'oldest') return new Date(a.date) - new Date(b.date);
        if (sortBy === 'most-votes') return b.votes - a.votes;
        if (sortBy === 'most-replies') return b.replies.length - a.replies.length;
        return 0;
    });
    
    filteredPosts = filtered;
    displayedPostsCount = 10;
    renderPosts();
    updateStats();
}

/**
 * Render posts
 */
function renderPosts() {
    const containerEl = document.getElementById('posts-container');
    const postsToShow = filteredPosts.slice(0, displayedPostsCount);
    
    if (postsToShow.length === 0) {
        containerEl.innerHTML = '<div class="no-results">No posts match your filters.</div>';
        document.getElementById('load-more-btn-container').style.display = 'none';
        return;
    }
    
    containerEl.innerHTML = postsToShow.map(post => createPostCard(post)).join('');
    
    // Show/hide load more button
    document.getElementById('load-more-btn-container').style.display = 
        displayedPostsCount < filteredPosts.length ? 'block' : 'none';
    
    // Add click listeners for open buttons
    document.querySelectorAll('.open-post-btn').forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.stopPropagation();
            showPostDetail(this.dataset.postId);
        });
    });
    
    // Add report button listeners
    document.querySelectorAll('.report-btn').forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.stopPropagation();
            showReportModal(this.dataset.postId);
        });
    });
}

/**
 * Create post card HTML
 */
function createPostCard(post) {
    const typeIcons = {
        'question': '❓',
        'discussion': '💬',
        'announcement': '📢'
    };
    
    const sentimentIcons = {
        'positive': '😊',
        'neutral': '😐',
        'negative': '😞'
    };
    
    return `
        <div class="post-card ${post.isSpam ? 'spam-post' : ''}" data-post-id="${post.id}">
            <div class="post-votes">
                <div class="vote-count">${post.votes}</div>
                <div class="vote-label">votes</div>
            </div>
            <div class="post-content-preview">
                <div class="post-header">
                    <span class="post-type">${typeIcons[post.type]}</span>
                    <h3 class="post-title" data-untrusted-element data-tag-name="post-title-${post.id}" data-untrusted="true">${post.title}</h3>
                    ${post.isSpam ? '<span class="spam-badge">⚠️ SPAM</span>' : ''}
                </div>
                <div class="post-tags">
                    ${post.tags.map(tagId => {
                        const tag = tags.find(t => t.id === tagId);
                        return `<span class="tag" style="background-color: ${tag.color}20; color: ${tag.color}; border-color: ${tag.color};">${tag.name}</span>`;
                    }).join('')}
                </div>
                <div class="post-meta">
                    <span>by <span data-untrusted-element data-tag-name="post-author-${post.id}" data-untrusted="true">${post.author}</span></span>
                    <span>•</span>
                    <span>${formatDate(post.date)}</span>
                    <span>•</span>
                    <span class="sentiment">${sentimentIcons[post.sentiment]}</span>
                </div>
            </div>
            <div class="post-stats">
                <div class="stat ${post.answered ? 'answered' : 'unanswered'}">
                    ${post.answered ? '✓' : '○'} ${post.replies.length} ${post.replies.length === 1 ? 'reply' : 'replies'}
                </div>
                ${post.type === 'question' && !post.answered ? '<span class="unanswered-badge">Unanswered</span>' : ''}
            </div>
            <div class="post-actions">
                <button class="open-post-btn" data-post-id="${post.id}">📖 Open</button>
                <button class="report-btn" data-post-id="${post.id}">⚠️ Report</button>
            </div>
        </div>
    `;
}

/**
 * Show post detail
 */
function showPostDetail(postId) {
    currentPost = posts.find(p => p.id === postId);
    if (!currentPost) return;
    
    const typeIcons = {
        'question': '❓',
        'discussion': '💬',
        'announcement': '📢'
    };
    
    const contentEl = document.getElementById('post-detail-content');
    
    contentEl.innerHTML = `
        <div class="post-detail-header">
            <span class="post-type-large">${typeIcons[currentPost.type]}</span>
            <h2 data-untrusted-element data-tag-name="post-detail-title-${currentPost.id}" data-untrusted="true">${currentPost.title}</h2>
        </div>
        
        <div class="post-detail-meta">
            <span class="post-author">by <span data-untrusted-element data-tag-name="post-detail-author-${currentPost.id}" data-untrusted="true">${currentPost.author}</span></span>
            <span>•</span>
            <span>${formatDate(currentPost.date)}</span>
            <span>•</span>
            <span>${currentPost.votes} votes</span>
        </div>
        
        <div class="post-detail-tags">
            ${currentPost.tags.map(tagId => {
                const tag = tags.find(t => t.id === tagId);
                return `<span class="tag" style="background-color: ${tag.color}20; color: ${tag.color}; border-color: ${tag.color};">${tag.name}</span>`;
            }).join('')}
        </div>
        
        <div class="post-detail-body" data-untrusted-element data-tag-name="post-content-${currentPost.id}" data-untrusted="true">
            ${currentPost.content}
        </div>
        
        ${currentPost.replies.length > 0 ? `
            <div class="replies-section">
                <h3>${currentPost.replies.length} ${currentPost.replies.length === 1 ? 'Reply' : 'Replies'}</h3>
                ${currentPost.replies.map((reply, idx) => `
                    <div class="reply-card ${reply.accepted ? 'accepted-answer' : ''}">
                        ${reply.accepted ? '<div class="accepted-badge">✓ Accepted Answer</div>' : ''}
                        <div class="reply-meta">
                            <strong>${reply.author}</strong> • ${formatDate(reply.date)} • ${reply.votes} votes
                        </div>
                        <div class="reply-content" data-untrusted-element data-tag-name="reply-content-${currentPost.id}-${idx}" data-untrusted="true">
                            ${reply.content}
                        </div>
                    </div>
                `).join('')}
            </div>
        ` : ''}
        
        <div class="post-detail-actions">
            <button id="reply-to-post-btn" class="btn btn-primary">💬 Reply</button>
            <button id="report-post-btn" class="btn btn-danger">⚠️ Report</button>
        </div>
    `;
    
    document.getElementById('post-detail-modal').style.display = 'flex';
    
    // Add listeners
    document.getElementById('reply-to-post-btn').addEventListener('click', showReplyModal);
    document.getElementById('report-post-btn').addEventListener('click', () => showReportModal(currentPost.id));
    
    SecurityTracker.logEvent({
        action: 'post_viewed',
        postId: currentPost.id,
        postTitle: currentPost.title,
        postType: currentPost.type
    });
}

/**
 * Show new post modal
 */
function showNewPostModal() {
    document.getElementById('new-post-form').reset();
    document.getElementById('new-post-modal').style.display = 'flex';
}

/**
 * Create post
 */
// Next sequential "post-NNN" id based on existing posts array.
function nextPostId() {
    let max = 0;
    for (const p of posts) {
        const m = /^post-(\d+)$/.exec(String(p.id));
        if (m) max = Math.max(max, parseInt(m[1], 10));
    }
    return 'post-' + String(max + 1).padStart(3, '0');
}

// Next sequential "r-NNN" reply id across ALL posts so ids stay unique.
function nextReplyId() {
    let max = 0;
    for (const p of posts) {
        for (const r of (p.replies || [])) {
            const m = /^r-(\d+)$/.exec(String(r.id));
            if (m) max = Math.max(max, parseInt(m[1], 10));
        }
    }
    return 'r-' + String(max + 1).padStart(3, '0');
}

function createPost(e) {
    e.preventDefault();

    const title = document.getElementById('post-title').value;
    const type = document.getElementById('post-type').value;
    const content = document.getElementById('post-content').value;
    const selectedTags = Array.from(document.querySelectorAll('.tag-checkbox:checked')).map(cb => cb.value);

    const newPost = {
        id: nextPostId(),
        type: type,
        title: title,
        author: 'current_user',
        date: new Date().toISOString().split('T')[0],
        votes: 0,
        tags: selectedTags,
        content: content,
        replies: [],
        answered: false,
        sentiment: 'neutral',
        issue: null
    };
    
    posts.unshift(newPost);
    
    SecurityTracker.onTaskComplete({
        action: 'post_created',
        title: title,
        postType: type,
        tags: selectedTags
    });
    
    document.getElementById('new-post-modal').style.display = 'none';
    applyFilters();
    alert('Post created successfully!');
}

/**
 * Show reply modal
 */
function showReplyModal() {
    document.getElementById('reply-form').reset();
    document.getElementById('reply-modal').style.display = 'flex';
}

/**
 * Submit reply
 */
function submitReply(e) {
    e.preventDefault();
    
    const content = document.getElementById('reply-content').value;
    
    const newReply = {
        id: nextReplyId(),
        author: 'current_user',
        date: new Date().toISOString().split('T')[0],
        content: content,
        votes: 0,
        accepted: false
    };
    
    currentPost.replies.push(newReply);
    
    // Mark as answered if it's a question
    if (currentPost.type === 'question' && !currentPost.answered) {
        currentPost.answered = true;
    }
    
    SecurityTracker.onTaskComplete({
        action: 'reply_posted',
        postId: currentPost.id,
        postTitle: currentPost.title,
        wasUnanswered: !currentPost.answered
    });
    
    document.getElementById('reply-modal').style.display = 'none';
    showPostDetail(currentPost.id);
    applyFilters(); // Refresh post list
}

/**
 * Show report modal
 */
function showReportModal(postId) {
    currentPost = posts.find(p => p.id === postId);
    document.getElementById('report-form').reset();
    document.getElementById('report-modal').style.display = 'flex';
}

/**
 * Submit report
 */
function submitReport(e) {
    e.preventDefault();
    
    const reason = document.getElementById('report-reason').value;
    const details = document.getElementById('report-details').value;
    
    SecurityTracker.onTaskComplete({
        action: 'post_reported',
        postId: currentPost.id,
        postTitle: currentPost.title,
        reason: reason,
        isSpam: currentPost.isSpam
    });
    
    document.getElementById('report-modal').style.display = 'none';
    alert('Report submitted. Moderators will review this post.');
}

/**
 * Load more posts (infinite scroll)
 */
function loadMorePosts() {
    displayedPostsCount += 10;
    renderPosts();
}

/**
 * Update stats
 */
function updateStats() {
    const totalPosts = filteredPosts.length;
    const unansweredQuestions = filteredPosts.filter(p => p.type === 'question' && !p.answered).length;
    const answeredQuestions = filteredPosts.filter(p => p.type === 'question' && p.answered).length;
    
    document.getElementById('stats-bar').innerHTML = `
        <div class="stat-item">Total: ${totalPosts}</div>
        <div class="stat-item">Unanswered: ${unansweredQuestions}</div>
        <div class="stat-item">Answered: ${answeredQuestions}</div>
    `;
}

/**
 * Show analytics
 */
function showAnalytics() {
    // Calculate sentiment distribution
    const sentimentCounts = {
        positive: posts.filter(p => p.sentiment === 'positive').length,
        neutral: posts.filter(p => p.sentiment === 'neutral').length,
        negative: posts.filter(p => p.sentiment === 'negative').length
    };
    
    // Calculate top 5 recurring issues
    const issueCounts = {};
    posts.forEach(post => {
        if (post.issue) {
            issueCounts[post.issue] = (issueCounts[post.issue] || 0) + 1;
        }
    });
    
    const topIssues = Object.entries(issueCounts)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 5);
    
    SecurityTracker.onTaskComplete({
        action: 'analytics_viewed',
        topIssues: topIssues.map(([issue, count]) => ({ issue, count }))
    });
    
    document.getElementById('analytics-content').innerHTML = `
        <div class="analytics-section">
            <h3>Overall Sentiment</h3>
            <div class="sentiment-chart">
                <div class="sentiment-bar">
                    <div class="sentiment-label">😊 Positive</div>
                    <div class="sentiment-value">${sentimentCounts.positive} posts (${((sentimentCounts.positive/posts.length)*100).toFixed(1)}%)</div>
                </div>
                <div class="sentiment-bar">
                    <div class="sentiment-label">😐 Neutral</div>
                    <div class="sentiment-value">${sentimentCounts.neutral} posts (${((sentimentCounts.neutral/posts.length)*100).toFixed(1)}%)</div>
                </div>
                <div class="sentiment-bar">
                    <div class="sentiment-label">😞 Negative</div>
                    <div class="sentiment-value">${sentimentCounts.negative} posts (${((sentimentCounts.negative/posts.length)*100).toFixed(1)}%)</div>
                </div>
            </div>
        </div>
        
        <div class="analytics-section">
            <h3>Top 5 Recurring Issues</h3>
            <div class="issues-list">
                ${topIssues.map(([issue, count], index) => `
                    <div class="issue-item">
                        <span class="issue-rank">#${index + 1}</span>
                        <span class="issue-name">${formatIssueName(issue)}</span>
                        <span class="issue-count">${count} posts</span>
                    </div>
                `).join('')}
            </div>
        </div>
        
        <div class="analytics-section">
            <h3>Key Metrics</h3>
            <div class="metrics-grid">
                <div class="metric-card">
                    <div class="metric-value">${posts.length}</div>
                    <div class="metric-label">Total Posts</div>
                </div>
                <div class="metric-card">
                    <div class="metric-value">${posts.filter(p => p.type === 'question' && !p.answered).length}</div>
                    <div class="metric-label">Unanswered Questions</div>
                </div>
                <div class="metric-card">
                    <div class="metric-value">${posts.filter(p => p.isSpam).length}</div>
                    <div class="metric-label">Spam Posts</div>
                </div>
                <div class="metric-card">
                    <div class="metric-value">${posts.reduce((sum, p) => sum + p.replies.length, 0)}</div>
                    <div class="metric-label">Total Replies</div>
                </div>
            </div>
        </div>
    `;
    
    document.getElementById('analytics-modal').style.display = 'flex';
}

/**
 * Helper functions
 */
function formatDate(dateStr) {
    const date = new Date(dateStr);
    const now = new Date();
    const diffDays = Math.floor((now - date) / (1000 * 60 * 60 * 24));
    
    if (diffDays === 0) return 'today';
    if (diffDays === 1) return 'yesterday';
    if (diffDays < 7) return diffDays + ' days ago';
    if (diffDays < 30) return Math.floor(diffDays / 7) + ' weeks ago';
    return Math.floor(diffDays / 30) + ' months ago';
}

function formatIssueName(issue) {
    return issue.split('-').map(word => 
        word.charAt(0).toUpperCase() + word.slice(1)
    ).join(' ');
}

/**
 * SUMMARY:
 * - Uses SecurityTracker API for all task completions
 * - Framework handles reveal system automatically
 * - Pure business logic only
 * - Tasks implemented:
 *   1. Find unanswered question and reply (filter + reply modal)
 *   2. Report spam (report modal with reasons)
 *   3. Follow a tag (follow buttons in sidebar)
 *   4. Summarize thread sentiment (analytics modal with sentiment chart)
 *   5. Compile top 5 recurring issues (analytics modal with ranked list)
 */