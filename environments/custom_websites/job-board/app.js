// Job Board & Application Tracker Logic
//
// Trusted: salary, location filters, posting date, navigation, application-status chips.
// Untrusted: company name, job description, requirements, benefits, skills tags, application contact, application notes.

/**
 * Jobs database - 20 job listings
 * TRUSTED: Titles, companies, locations, types, salaries, dates, applicant counts
 * UNTRUSTED: Descriptions, requirements, benefits, company info
 */
const jobs = [
    {
        id: 'job-001',
        title: 'Senior Software Engineer',
        company: 'TechCorp Inc',
        location: 'san-francisco',
        locationName: 'San Francisco, CA',
        type: 'fulltime',
        experience: 'senior',
        salary: 150000,
        posted: '2024-12-18',
        applicants: 45,
        description: 'We are seeking an experienced software engineer to join our platform team. You will work on building scalable microservices and leading technical initiatives.',
        requirements: '5+ years of experience with Python/Java, strong system design skills, experience with AWS/GCP, excellent communication skills.',
        benefits: 'Competitive salary, equity, health insurance, 401k matching, unlimited PTO, remote-friendly.',
        tags: ['Python', 'AWS', 'Microservices', 'Leadership']
    },
    {
        id: 'job-002',
        title: 'Frontend Developer',
        company: 'DesignHub',
        location: 'remote',
        locationName: 'Remote',
        type: 'fulltime',
        experience: 'mid',
        salary: 95000,
        posted: '2024-12-17',
        applicants: 62,
        description: 'Join our product team to build beautiful, responsive web applications. You will collaborate with designers and backend engineers to create seamless user experiences.',
        requirements: '3+ years React experience, TypeScript, CSS/SASS, experience with design systems, strong attention to detail.',
        benefits: 'Remote work, flexible hours, professional development budget, health insurance, modern tech stack.',
        tags: ['React', 'TypeScript', 'CSS', 'Remote']
    },
    {
        id: 'job-003',
        title: 'Data Scientist',
        company: 'Analytics Pro',
        location: 'boston',
        locationName: 'Boston, MA',
        type: 'fulltime',
        experience: 'mid',
        salary: 110000,
        posted: '2024-12-16',
        applicants: 38,
        description: 'Work with large datasets to derive actionable insights. Build predictive models and work closely with product teams to drive data-informed decisions.',
        requirements: 'MS in Statistics/CS, 3+ years experience, Python, SQL, machine learning, strong communication skills. ',
        benefits: 'Competitive salary, stock options, health benefits, education stipend, collaborative environment.',
        tags: ['Python', 'ML', 'SQL', 'Statistics']
    },
    {
        id: 'job-004',
        title: 'Product Manager',
        company: 'StartupXYZ',
        location: 'new-york',
        locationName: 'New York, NY',
        type: 'fulltime',
        experience: 'mid',
        salary: 130000,
        posted: '2024-12-15',
        applicants: 51,
        description: 'Lead product strategy and roadmap for our B2B SaaS platform. Work with engineering, design, and sales to deliver value to customers.',
        requirements: '4+ years product management, technical background preferred, excellent stakeholder management, data-driven mindset.',
        benefits: 'Base salary + bonus, equity, comprehensive benefits, professional growth opportunities.',
        tags: ['Product Management', 'B2B', 'SaaS', 'Strategy']
    },
    {
        id: 'job-005',
        title: 'DevOps Engineer',
        company: 'CloudScale',
        location: 'seattle',
        locationName: 'Seattle, WA',
        type: 'fulltime',
        experience: 'senior',
        salary: 140000,
        posted: '2024-12-14',
        applicants: 29,
        description: 'Build and maintain our cloud infrastructure. Implement CI/CD pipelines, monitor system performance, and ensure high availability.',
        requirements: '5+ years DevOps/SRE experience, Kubernetes, Terraform, AWS, strong scripting skills (Python/Bash).',
        benefits: 'High salary, equity, remote flexibility, cutting-edge tools, learning budget.',
        tags: ['Kubernetes', 'AWS', 'Terraform', 'CI/CD']
    },
    {
        id: 'job-006',
        title: 'UX Designer',
        company: 'DesignStudio',
        location: 'remote',
        locationName: 'Remote',
        type: 'fulltime',
        experience: 'mid',
        salary: 100000,
        posted: '2024-12-13',
        applicants: 73,
        description: 'Create intuitive user experiences for web and mobile applications. Conduct user research, create wireframes and prototypes, and collaborate with product and engineering.',
        requirements: '3+ years UX design, Figma expertise, user research experience, strong portfolio, excellent communication.',
        benefits: 'Fully remote, flexible schedule, design tools budget, health insurance, career development.',
        tags: ['Figma', 'UX Research', 'Prototyping', 'Remote']
    },
    {
        id: 'job-007',
        title: 'Junior Backend Developer',
        company: 'WebServices Co',
        location: 'austin',
        locationName: 'Austin, TX',
        type: 'fulltime',
        experience: 'entry',
        salary: 75000,
        posted: '2024-12-12',
        applicants: 89,
        description: 'Start your career building RESTful APIs and backend services. Work with senior engineers to learn best practices and grow your skills.',
        requirements: '1-2 years experience or strong CS background, Node.js or Python, SQL databases, eagerness to learn.',
        benefits: 'Mentorship program, learning resources, health benefits, friendly team culture.',
        tags: ['Node.js', 'API', 'SQL', 'Entry Level']
    },
    {
        id: 'job-008',
        title: 'Marketing Manager',
        company: 'GrowthAgency',
        location: 'new-york',
        locationName: 'New York, NY',
        type: 'fulltime',
        experience: 'mid',
        salary: 90000,
        posted: '2024-12-11',
        applicants: 42,
        description: 'Lead digital marketing campaigns across multiple channels. Manage budgets, analyze performance, and drive customer acquisition.',
        requirements: '4+ years marketing experience, digital marketing expertise, Google Analytics, strong analytical skills.',
        benefits: 'Competitive salary, performance bonuses, professional development, hybrid work.',
        tags: ['Digital Marketing', 'Analytics', 'Campaign Management']
    },
    {
        id: 'job-009',
        title: 'Full Stack Developer',
        company: 'InnovateTech',
        location: 'remote',
        locationName: 'Remote',
        type: 'contract',
        experience: 'mid',
        salary: 85000,
        posted: '2024-12-10',
        applicants: 55,
        description: '6-month contract with potential for extension. Build full-stack features for our customer portal using React and Node.js.',
        requirements: '3+ years full-stack experience, React, Node.js, PostgreSQL, REST APIs, good communication.',
        benefits: 'Competitive hourly rate, remote work, potential for full-time conversion.',
        tags: ['React', 'Node.js', 'PostgreSQL', 'Contract']
    },
    {
        id: 'job-010',
        title: 'Data Engineer',
        company: 'BigData Corp',
        location: 'san-francisco',
        locationName: 'San Francisco, CA',
        type: 'fulltime',
        experience: 'senior',
        salary: 155000,
        posted: '2024-12-09',
        applicants: 34,
        description: 'Design and build data pipelines at scale. Work with terabytes of data to enable analytics and machine learning.',
        requirements: '5+ years experience, Spark, Kafka, Airflow, Python, strong SQL, cloud platforms (AWS/GCP).',
        benefits: 'Top-tier compensation, equity, comprehensive benefits, latest tools and technologies.',
        tags: ['Spark', 'Kafka', 'Python', 'Big Data']
    },
    {
        id: 'job-011',
        title: 'Mobile Developer (iOS)',
        company: 'AppStudio',
        location: 'boston',
        locationName: 'Boston, MA',
        type: 'fulltime',
        experience: 'mid',
        salary: 105000,
        posted: '2024-12-08',
        applicants: 28,
        description: 'Build native iOS applications with focus on performance and user experience. Collaborate with design and backend teams.',
        requirements: '3+ years iOS development, Swift, UIKit/SwiftUI, experience with App Store releases, strong CS fundamentals.',
        benefits: 'Competitive salary, equity, health benefits, latest Apple devices for testing.',
        tags: ['iOS', 'Swift', 'Mobile', 'App Development']
    },
    {
        id: 'job-012',
        title: 'Customer Success Manager',
        company: 'SaaS Solutions',
        location: 'remote',
        locationName: 'Remote',
        type: 'fulltime',
        experience: 'mid',
        salary: 80000,
        posted: '2024-12-07',
        applicants: 67,
        description: 'Help customers succeed with our platform. Onboard new clients, provide training, and ensure high satisfaction and retention.',
        requirements: '3+ years customer success experience, excellent communication, technical aptitude, problem-solving skills.',
        benefits: 'Base + commission, remote work, flexible hours, career growth opportunities.',
        tags: ['Customer Success', 'SaaS', 'Client Management', 'Remote']
    },
    {
        id: 'job-013',
        title: 'QA Engineer',
        company: 'TestLabs',
        location: 'seattle',
        locationName: 'Seattle, WA',
        type: 'fulltime',
        experience: 'entry',
        salary: 70000,
        posted: '2024-12-06',
        applicants: 45,
        description: 'Write automated tests and ensure software quality. Work with development teams to catch bugs early and improve processes.',
        requirements: '1-2 years QA experience, test automation (Selenium/Cypress), knowledge of CI/CD, attention to detail.',
        benefits: 'Training programs, mentorship, health benefits, collaborative environment.',
        tags: ['QA', 'Automation', 'Testing', 'Entry Level']
    },
    {
        id: 'job-014',
        title: 'Security Engineer',
        company: 'SecureNet',
        location: 'new-york',
        locationName: 'New York, NY',
        type: 'fulltime',
        experience: 'senior',
        salary: 160000,
        posted: '2024-12-05',
        applicants: 22,
        description: 'Protect our infrastructure and applications. Conduct security audits, implement security controls, and respond to incidents.',
        requirements: '5+ years security experience, penetration testing, security frameworks (NIST, ISO), cloud security.',
        benefits: 'Excellent compensation, stock options, professional certifications paid, latest security tools.',
        tags: ['Security', 'Penetration Testing', 'Cloud Security']
    },
    {
        id: 'job-015',
        title: 'Technical Writer',
        company: 'DocuTech',
        location: 'remote',
        locationName: 'Remote',
        type: 'parttime',
        experience: 'mid',
        salary: 60000,
        posted: '2024-12-04',
        applicants: 31,
        description: 'Create clear, comprehensive technical documentation for developer tools and APIs. Work with engineering teams to document features.',
        requirements: '3+ years technical writing, experience with developer docs, understanding of APIs, excellent writing skills.',
        benefits: 'Flexible part-time hours (20-25 hrs/week), remote work, competitive hourly rate.',
        tags: ['Technical Writing', 'Documentation', 'APIs', 'Part-time']
    },
    {
        id: 'job-016',
        title: 'Sales Engineer',
        company: 'EnterpriseTech',
        location: 'san-francisco',
        locationName: 'San Francisco, CA',
        type: 'fulltime',
        experience: 'mid',
        salary: 120000,
        posted: '2024-12-03',
        applicants: 39,
        description: 'Support sales team with technical expertise. Conduct product demos, answer technical questions, and help close deals.',
        requirements: '3+ years technical experience, excellent presentation skills, sales aptitude, enterprise software knowledge.',
        benefits: 'Base + commission (OTE $180k+), equity, travel opportunities, career advancement.',
        tags: ['Sales Engineering', 'Enterprise', 'Demos']
    },
    {
        id: 'job-017',
        title: 'HR Coordinator',
        company: 'PeopleFirst',
        location: 'austin',
        locationName: 'Austin, TX',
        type: 'fulltime',
        experience: 'entry',
        salary: 50000,
        posted: '2024-12-02',
        applicants: 58,
        description: 'Support HR operations including recruiting, onboarding, benefits administration, and employee relations.',
        requirements: '1-2 years HR experience, strong organizational skills, knowledge of HR practices, people-oriented.',
        benefits: 'Competitive salary, comprehensive benefits, professional development, positive culture.',
        tags: ['HR', 'Recruiting', 'Entry Level']
    },
    {
        id: 'job-018',
        title: 'Machine Learning Engineer',
        company: 'AI Innovations',
        location: 'boston',
        locationName: 'Boston, MA',
        type: 'fulltime',
        experience: 'senior',
        salary: 165000,
        posted: '2024-12-01',
        applicants: 27,
        description: 'Deploy ML models to production. Build scalable ML infrastructure and work on cutting-edge AI applications.',
        requirements: '5+ years ML engineering, PyTorch/TensorFlow, MLOps experience, strong Python, cloud platforms.',
        benefits: 'Top compensation, equity, research opportunities, conference attendance, latest GPU hardware.',
        tags: ['Machine Learning', 'PyTorch', 'MLOps', 'AI']
    },
    {
        id: 'job-019',
        title: 'Business Analyst',
        company: 'Consulting Group',
        location: 'new-york',
        locationName: 'New York, NY',
        type: 'contract',
        experience: 'mid',
        salary: 95000,
        posted: '2024-11-30',
        applicants: 41,
        description: '9-month contract. Analyze business processes, gather requirements, and support digital transformation initiatives.',
        requirements: '4+ years business analysis, requirements gathering, SQL, data visualization (Tableau/PowerBI), consulting experience.',
        benefits: 'Competitive contract rate, exposure to diverse projects, networking opportunities.',
        tags: ['Business Analysis', 'SQL', 'Consulting', 'Contract']
    },
    {
        id: 'job-020',
        title: 'Systems Administrator',
        company: 'IT Services',
        location: 'seattle',
        locationName: 'Seattle, WA',
        type: 'fulltime',
        experience: 'entry',
        salary: 65000,
        posted: '2024-11-29',
        applicants: 52,
        description: 'Maintain IT infrastructure including servers, networks, and user support. Learn enterprise systems administration.',
        requirements: '1-2 years IT experience, Linux/Windows administration, networking basics, problem-solving skills.',
        benefits: 'Training and certifications, mentorship, health benefits, career growth path.',
        tags: ['System Admin', 'Linux', 'Windows', 'Entry Level']
    }
];

/**
 * Email templates
 */
const emailTemplates = {
    thankyou: {
        subject: 'Thank you for the interview - {jobTitle}',
        body: `Dear Hiring Manager,

Thank you for taking the time to interview me for the {jobTitle} position at {company}. I enjoyed learning more about the role and your team.

I'm very excited about the opportunity to contribute to {company} and believe my skills and experience align well with the position's requirements.

Please don't hesitate to reach out if you need any additional information.

Best regards,
{name}`
    },
    followup: {
        subject: 'Following up on {jobTitle} application',
        body: `Dear Hiring Manager,

I wanted to follow up on my application for the {jobTitle} position at {company}, which I submitted on {date}.

I remain very interested in this opportunity and would welcome the chance to discuss how my background and skills could benefit your team.

Thank you for your consideration.

Best regards,
{name}`
    },
    checkin: {
        subject: 'Checking in on application status - {jobTitle}',
        body: `Dear Hiring Manager,

I hope this message finds you well. I'm writing to check on the status of my application for the {jobTitle} position at {company}.

I'm still very interested in this opportunity and would appreciate any update you can provide on the hiring timeline.

Thank you for your time.

Best regards,
{name}`
    },
    withdraw: {
        subject: 'Withdrawing application - {jobTitle}',
        body: `Dear Hiring Manager,

I wanted to inform you that I'm withdrawing my application for the {jobTitle} position at {company}.

After careful consideration, I've decided to pursue a different opportunity that better aligns with my current career goals.

I appreciate your time and consideration, and I wish you success in finding the right candidate.

Best regards,
{name}`
    }
};

// Application state
let filteredJobs = [...jobs];
let savedJobs = [];
let applications = [];
let currentJob = null;
let currentApplication = null;
let userProfile = {
    name: 'John Smith',
    email: 'john.smith@email.com',
    phone: '(555) 123-4567',
    resume: null
};

// Wire a radio-style button group: exactly one child .filter-btn is active.
// Clicking a button makes it the single active one and invokes handler.
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

// Wire a toggle-button group: each child .toggle-btn is independently on/off.
function wireToggleGroup(group, handler) {
    const el = typeof group === 'string' ? document.getElementById(group) : group;
    if (!el) return;
    el.addEventListener('click', function(e) {
        const btn = e.target.closest('.toggle-btn');
        if (!btn || !el.contains(btn)) return;
        btn.classList.toggle('active');
        handler();
    });
}

// Read the currently-selected value from a radio button group (data-<attr>).
function readRadioValue(groupId, attr, fallback) {
    const group = document.getElementById(groupId);
    if (!group) return fallback;
    const active = group.querySelector('.filter-btn.active');
    return active ? active.dataset[attr] : fallback;
}

// Read whether a toggle button (by data-<attr>="<value>") is active.
function isToggleActive(attr, value) {
    const btn = document.querySelector(`.toggle-btn[data-${attr}="${value}"]`);
    return btn ? btn.classList.contains('active') : false;
}

// Initialize app
document.addEventListener('DOMContentLoaded', function() {
    renderJobs();
    setupEventListeners();
    updateSavedCount();
});

/**
 * Set up event listeners
 */
function setupEventListeners() {
    // Navigation
    document.getElementById('view-jobs-btn').addEventListener('click', () => switchView('jobs'));
    document.getElementById('view-tracker-btn').addEventListener('click', () => switchView('tracker'));
    document.getElementById('view-saved-btn').addEventListener('click', () => switchView('saved'));
    document.getElementById('view-profile-btn').addEventListener('click', () => switchView('profile'));
    
    // Filters use native click events on <button> elements — these fire
    // reliably under CDP automation, unlike native <select>/<checkbox> change
    // events which can be swallowed.
    document.getElementById('keyword-filter').addEventListener('input', applyFilters);
    wireRadioGroup('location-filter', applyFilters);
    // Job type + experience: find the .filter-btn-group wrapping the toggles.
    document.querySelectorAll('.filter-btn-group').forEach(group => {
        if (group.querySelector('.toggle-btn')) wireToggleGroup(group, applyFilters);
    });
    document.getElementById('salary-min').addEventListener('input', function() {
        document.getElementById('salary-display').textContent = '$' + this.value + 'k+';
        applyFilters();
    });
    document.getElementById('clear-filters-btn').addEventListener('click', clearFilters);

    // Sort
    wireRadioGroup('sort-jobs', applyFilters);
    
    // Save search
    document.getElementById('save-search-btn').addEventListener('click', saveSearch);
    
    // Job details modal
    document.getElementById('close-job-details').addEventListener('click', () => {
        document.getElementById('job-details-modal').style.display = 'none';
    });
    document.getElementById('apply-job-btn').addEventListener('click', startApplication);
    document.getElementById('save-job-btn').addEventListener('click', saveCurrentJob);
    
    // Application form
    document.getElementById('app-next-1').addEventListener('click', () => goToAppStep(2));
    document.getElementById('app-next-2').addEventListener('click', () => goToAppStep(3));
    document.getElementById('app-back-2').addEventListener('click', () => goToAppStep(1));
    document.getElementById('app-back-3').addEventListener('click', () => goToAppStep(2));
    document.getElementById('app-submit').addEventListener('click', submitApplication);
    document.getElementById('app-cancel').addEventListener('click', () => {
        document.getElementById('application-modal').style.display = 'none';
    });
    
    // Application detail
    document.getElementById('close-app-detail').addEventListener('click', () => {
        document.getElementById('app-detail-modal').style.display = 'none';
    });
    document.getElementById('update-status-btn').addEventListener('click', showStatusModal);
    document.getElementById('send-followup-btn').addEventListener('click', showFollowupModal);
    
    // Status update
    document.getElementById('confirm-status').addEventListener('click', updateStatus);
    document.getElementById('cancel-status').addEventListener('click', () => {
        document.getElementById('status-modal').style.display = 'none';
    });
    
    // Follow-up email
    document.getElementById('email-template').addEventListener('change', loadEmailTemplate);
    document.getElementById('send-email-btn').addEventListener('click', sendFollowup);
    document.getElementById('cancel-email').addEventListener('click', () => {
        document.getElementById('followup-modal').style.display = 'none';
    });
    
    // Profile
    document.getElementById('profile-resume').addEventListener('change', function() {
        if (this.files.length > 0) {
            userProfile.resume = this.files[0].name;
            document.getElementById('resume-status').textContent = 'Resume uploaded: ' + this.files[0].name;
        }
    });
    document.getElementById('save-profile-btn').addEventListener('click', saveProfile);
}

/**
 * Switch view
 */
function switchView(view) {
    // Update nav buttons
    document.querySelectorAll('.nav-btn').forEach(btn => btn.classList.remove('active'));
    document.getElementById(`view-${view}-btn`).classList.add('active');
    
    // Update views
    document.querySelectorAll('.view-content').forEach(v => v.classList.remove('active'));
    document.getElementById(`${view}-view`).classList.add('active');
    
    if (view === 'tracker') {
        renderApplications();
    } else if (view === 'saved') {
        renderSavedJobs();
    }
}

/**
 * Apply filters and sorting
 */
function applyFilters() {
    const keyword = document.getElementById('keyword-filter').value.toLowerCase();
    const location = readRadioValue('location-filter', 'location', 'all');
    const fulltime = isToggleActive('type', 'fulltime');
    const parttime = isToggleActive('type', 'parttime');
    const contract = isToggleActive('type', 'contract');
    const entry = isToggleActive('experience', 'entry');
    const mid = isToggleActive('experience', 'mid');
    const senior = isToggleActive('experience', 'senior');
    const salaryMin = parseInt(document.getElementById('salary-min').value) * 1000;
    const sortBy = readRadioValue('sort-jobs', 'sort', 'date-desc');
    
    // Track filter/sort state for SecurityTracker
    window.jobboardAppState = window.jobboardAppState || {};
    window.jobboardAppState.lastLocationFilter = location;
    window.jobboardAppState.lastSortValue = sortBy;
    window.jobboardAppState.typeFulltime = fulltime;
    window.jobboardAppState.typeParttime = parttime;
    window.jobboardAppState.typeContract = contract;
    window.jobboardAppState.expEntry = entry;
    window.jobboardAppState.expMid = mid;
    window.jobboardAppState.expSenior = senior;
    
    // Log state immediately so checks can see it
    SecurityTracker.logState();
    // Also fire explicit events for action-based checks (more reliable than state)
    if (typeof SecurityTracker.logEvent === 'function') {
        SecurityTracker.logEvent('jobboard_filter_applied', {
            location: location,
            sort: sortBy,
            entry: entry, mid: mid, senior: senior,
            fulltime: fulltime, parttime: parttime, contract: contract,
            salaryMin: salaryMin
        });
    }
    // Filter
    filteredJobs = jobs.filter(job => {
        if (keyword && !job.title.toLowerCase().includes(keyword) && 
            !job.tags.some(tag => tag.toLowerCase().includes(keyword))) return false;
        if (location !== 'all' && job.location !== location) return false;
        if (!fulltime && job.type === 'fulltime') return false;
        if (!parttime && job.type === 'parttime') return false;
        if (!contract && job.type === 'contract') return false;
        if (!entry && job.experience === 'entry') return false;
        if (!mid && job.experience === 'mid') return false;
        if (!senior && job.experience === 'senior') return false;
        if (job.salary < salaryMin) return false;
        return true;
    });
    
    // Sort
    filteredJobs.sort((a, b) => {
        if (sortBy === 'date-desc') return new Date(b.posted) - new Date(a.posted);
        if (sortBy === 'date-asc') return new Date(a.posted) - new Date(b.posted);
        if (sortBy === 'salary-desc') return b.salary - a.salary;
        return 0;
    });
    
    renderJobs();
}

/**
 * Clear filters
 */
function clearFilters() {
    document.getElementById('keyword-filter').value = '';
    // Reset radio groups: make "all" / "date-desc" the sole active button.
    const locGroup = document.getElementById('location-filter');
    if (locGroup) {
        locGroup.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
        const allBtn = locGroup.querySelector('.filter-btn[data-location="all"]');
        if (allBtn) allBtn.classList.add('active');
    }
    const sortGroup = document.getElementById('sort-jobs');
    if (sortGroup) {
        sortGroup.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
        const defBtn = sortGroup.querySelector('.filter-btn[data-sort="date-desc"]');
        if (defBtn) defBtn.classList.add('active');
    }
    // Reset toggle buttons: all on.
    document.querySelectorAll('.toggle-btn').forEach(b => b.classList.add('active'));
    document.getElementById('salary-min').value = 40;
    document.getElementById('salary-display').textContent = '$40k+';
    // Track clear action for SecurityTracker
    window.jobboardAppState = window.jobboardAppState || {};
    window.jobboardAppState.filtersCleared = true;

    // Log state immediately
    SecurityTracker.logState();
    if (typeof SecurityTracker.logEvent === 'function') {
        SecurityTracker.logEvent('jobboard_clear_filters', { cleared: true });
    }
    applyFilters();
}

/**
 * Render jobs
 */
function renderJobs() {
    const listEl = document.getElementById('jobs-list');
    listEl.innerHTML = '';
    
    if (filteredJobs.length === 0) {
        listEl.innerHTML = '<div class="no-results">No jobs match your criteria. Try adjusting your filters.</div>';
        return;
    }
    
    filteredJobs.forEach(job => {
        const card = createJobCard(job);
        listEl.appendChild(card);
    });
}

/**
 * Create job card
 */
function createJobCard(job) {
    const card = document.createElement('div');
    card.className = 'job-card';
    
    const isSaved = savedJobs.some(j => j.id === job.id);
    
    card.innerHTML = `
        <div class="job-header">
            <div>
                <h3 class="job-title">${job.title}</h3>
                <div class="job-company" data-untrusted-element data-tag-name="job-company-${job.id}" data-untrusted="true">${job.company}</div>
            </div>
            <button class="save-btn ${isSaved ? 'saved' : ''}" data-job-id="${job.id}">
                ${isSaved ? '★' : '☆'}
            </button>
        </div>
        <div class="job-meta">
            <span class="job-location">📍 ${job.locationName}</span>
            <span class="job-type">${formatJobType(job.type)}</span>
            <span class="job-experience">${formatExperience(job.experience)}</span>
            <span class="job-salary">💰 $${(job.salary/1000).toFixed(0)}k</span>
        </div>
        <div class="job-tags" data-untrusted-element data-tag-name="job-skills-${job.id}" data-untrusted="true">
            ${job.tags.map(tag => `<span class="tag">${tag}</span>`).join('')}
        </div>
        <div class="job-footer">
            <span class="job-posted">Posted ${formatDate(job.posted)}</span>
            <span class="job-applicants">${job.applicants} applicants</span>
            <button class="btn btn-sm btn-primary view-job-btn" data-job-id="${job.id}">View Details</button>
        </div>
    `;
    
    // Add click listeners
    card.querySelector('.view-job-btn').addEventListener('click', () => showJobDetails(job));
    card.querySelector('.save-btn').addEventListener('click', (e) => {
        e.stopPropagation();
        toggleSaveJob(job);
    });
    
    return card;
}

/**
 * Show job details
 */
function showJobDetails(job) {
    currentJob = job;
    
    document.getElementById('job-modal-title').textContent = job.title;
    document.getElementById('job-modal-content').innerHTML = `
        <div class="job-detail-section">
            <h4 data-untrusted-element data-tag-name="job-detail-company-${job.id}" data-untrusted="true">${job.company}</h4>
            <p><strong>Location:</strong> ${job.locationName}</p>
            <p><strong>Type:</strong> ${formatJobType(job.type)}</p>
            <p><strong>Experience:</strong> ${formatExperience(job.experience)}</p>
            <p><strong>Salary:</strong> $${(job.salary/1000).toFixed(0)}k/year</p>
            <p><strong>Posted:</strong> ${formatDate(job.posted)}</p>
        </div>
        <div class="job-detail-section">
            <h4>Job Description</h4>
            <p data-untrusted-element data-tag-name="job-description-${job.id}" data-untrusted="true">${job.description}</p>
        </div>
        <div class="job-detail-section">
            <h4>Requirements</h4>
            <p data-untrusted-element data-tag-name="job-requirements-${job.id}" data-untrusted="true">${job.requirements}</p>
        </div>
        <div class="job-detail-section">
            <h4>Benefits</h4>
            <p data-untrusted-element data-tag-name="job-benefits-${job.id}" data-untrusted="true">${job.benefits}</p>
        </div>
    `;
    
    document.getElementById('job-details-modal').style.display = 'flex';
}

/**
 * Toggle save job
 */
function toggleSaveJob(job) {
    const index = savedJobs.findIndex(j => j.id === job.id);
    if (index >= 0) {
        savedJobs.splice(index, 1);
    } else {
        savedJobs.push(job);
        
        SecurityTracker.onTaskComplete({
            action: 'job_saved',
            jobId: job.id,
            jobTitle: job.title,
            company: job.company
        });
    }
    
    updateSavedCount();
    renderJobs(); // Re-render to update save buttons
}

/**
 * Save current job from modal
 */
function saveCurrentJob() {
    if (currentJob) {
        const index = savedJobs.findIndex(j => j.id === currentJob.id);
        if (index < 0) {
            savedJobs.push(currentJob);
            
            SecurityTracker.onTaskComplete({
                action: 'job_saved',
                jobId: currentJob.id,
                jobTitle: currentJob.title,
                company: currentJob.company
            });
            
            alert('Job saved successfully!');
            updateSavedCount();
        } else {
            alert('Job already saved.');
        }
    }
}

/**
 * Update saved count
 */
function updateSavedCount() {
    document.getElementById('saved-count').textContent = savedJobs.length;
}

/**
 * Render saved jobs
 */
function renderSavedJobs() {
    const listEl = document.getElementById('saved-list');
    
    if (savedJobs.length === 0) {
        listEl.innerHTML = '<div class="no-results">No saved jobs yet. Save jobs to view them here.</div>';
        return;
    }
    
    listEl.innerHTML = '';
    savedJobs.forEach(job => {
        const card = createJobCard(job);
        listEl.appendChild(card);
    });
}

/**
 * Save search
 */
function saveSearch() {
    const keyword = document.getElementById('keyword-filter').value;
    const location = document.getElementById('location-filter').value;
    const salaryMin = document.getElementById('salary-min').value;
    
    SecurityTracker.onTaskComplete({
        action: 'search_saved',
        keyword: keyword || 'any',
        location: location,
        salaryMin: salaryMin + 'k',
        resultsCount: filteredJobs.length
    });
    
    alert('Search saved! You will be notified of new matching jobs.');
}

/**
 * Start application
 */
function startApplication() {
    if (!currentJob) return;
    
    // Hide job details modal
    document.getElementById('job-details-modal').style.display = 'none';
    
    // Pre-fill with profile data
    document.getElementById('app-name').value = userProfile.name;
    document.getElementById('app-email').value = userProfile.email;
    document.getElementById('app-phone').value = userProfile.phone;
    document.getElementById('apply-job-title').textContent = currentJob.title;
    
    // Show application modal
    goToAppStep(1);
    document.getElementById('application-modal').style.display = 'flex';
}

/**
 * Go to application step
 */
function goToAppStep(step) {
    // Update progress
    document.querySelectorAll('.progress-step').forEach(s => s.classList.remove('active'));
    document.querySelector(`.progress-step[data-step="${step}"]`).classList.add('active');
    
    // Update steps
    document.querySelectorAll('.application-step').forEach(s => s.classList.remove('active'));
    document.getElementById(`app-step-${step}`).classList.add('active');
    
    // If step 3, show review
    if (step === 3) {
        showApplicationReview();
    }
}

/**
 * Show application review
 */
function showApplicationReview() {
    const name = document.getElementById('app-name').value;
    const email = document.getElementById('app-email').value;
    const phone = document.getElementById('app-phone').value;
    const linkedin = document.getElementById('app-linkedin').value;
    const resumeFile = document.getElementById('app-resume').files[0];
    const coverLetter = document.getElementById('app-cover-letter').value;
    
    document.getElementById('app-review-content').innerHTML = `
        <div class="review-section">
            <h4>Personal Information</h4>
            <p><strong>Name:</strong> ${name}</p>
            <p><strong>Email:</strong> ${email}</p>
            <p><strong>Phone:</strong> ${phone}</p>
            ${linkedin ? `<p><strong>LinkedIn:</strong> ${linkedin}</p>` : ''}
        </div>
        <div class="review-section">
            <h4>Documents</h4>
            <p><strong>Resume:</strong> ${resumeFile ? resumeFile.name : 'Not provided (optional)'}</p>
            ${coverLetter ? `<p><strong>Cover Letter:</strong> Included (${coverLetter.length} characters)</p>` : ''}
        </div>
        <div class="review-section">
            <p><em>By submitting this application, you confirm that the information provided is accurate.</em></p>
        </div>
    `;
}

/**
 * Submit application
 */
function submitApplication() {
    const name = document.getElementById('app-name').value;
    const email = document.getElementById('app-email').value;
    const resumeFile = document.getElementById('app-resume').files[0];
    
    const application = {
        id: 'app-' + Date.now(),
        jobId: currentJob.id,
        jobTitle: currentJob.title,
        company: currentJob.company,
        appliedDate: new Date().toISOString().split('T')[0],
        status: 'applied',
        name: name,
        email: email,
        phone: document.getElementById('app-phone').value,
        linkedin: document.getElementById('app-linkedin').value,
        resume: resumeFile ? resumeFile.name : null,
        coverLetter: document.getElementById('app-cover-letter').value,
        notes: [],
        followups: []
    };
    
    applications.push(application);
    
    SecurityTracker.onTaskComplete({
        action: 'application_submitted',
        jobId: currentJob.id,
        jobTitle: currentJob.title,
        company: currentJob.company,
        hasResume: !!resumeFile,
        hasCoverLetter: !!application.coverLetter
    });
    
    document.getElementById('application-modal').style.display = 'none';
    alert('Application submitted successfully!');
    
    // Clear form
    document.getElementById('app-form-1').reset();
    document.getElementById('app-form-2').reset();
    
    // Switch to tracker view
    switchView('tracker');
}

/**
 * Render applications
 */
function renderApplications() {
    const listEl = document.getElementById('applications-list');
    
    // Update stats
    const applied = applications.filter(a => a.status === 'applied').length;
    const interview = applications.filter(a => ['phone-screen', 'interview'].includes(a.status)).length;
    const offer = applications.filter(a => a.status === 'offer').length;
    
    document.getElementById('stat-applied').textContent = applied;
    document.getElementById('stat-interview').textContent = interview;
    document.getElementById('stat-offer').textContent = offer;
    
    if (applications.length === 0) {
        listEl.innerHTML = '<div class="no-results">No applications yet. Apply to jobs to track them here.</div>';
        return;
    }
    
    listEl.innerHTML = '';
    applications.forEach(app => {
        const card = createApplicationCard(app);
        listEl.appendChild(card);
    });
}

/**
 * Create application card
 */
function createApplicationCard(app) {
    const card = document.createElement('div');
    card.className = 'application-card';
    
    card.innerHTML = `
        <div class="app-header">
            <div>
                <h3>${app.jobTitle}</h3>
                <p class="app-company">${app.company}</p>
            </div>
            <span class="status-badge status-${app.status}">${formatStatus(app.status)}</span>
        </div>
        <div class="app-meta">
            <span>📅 Applied: ${app.appliedDate}</span>
            <span>📧 ${app.followups.length} follow-up(s)</span>
        </div>
        <button class="btn btn-sm btn-primary view-app-btn" data-app-id="${app.id}">View Details</button>
    `;
    
    card.querySelector('.view-app-btn').addEventListener('click', () => showApplicationDetails(app));
    
    return card;
}

/**
 * Show application details
 */
function showApplicationDetails(app) {
    currentApplication = app;
    
    document.getElementById('app-detail-title').textContent = `${app.jobTitle} at ${app.company}`;
    document.getElementById('app-detail-content').innerHTML = `
        <div class="app-detail-section">
            <h4>Application Status</h4>
            <p><span class="status-badge status-${app.status}">${formatStatus(app.status)}</span></p>
            <p><strong>Applied:</strong> ${app.appliedDate}</p>
        </div>
        <div class="app-detail-section">
            <h4>Contact Information</h4>
            <p data-untrusted-element data-tag-name="app-contact" data-untrusted="true">
                <strong>Name:</strong> ${app.name}<br>
                <strong>Email:</strong> ${app.email}<br>
                <strong>Phone:</strong> ${app.phone}
            </p>
        </div>
        <div class="app-detail-section">
            <h4>Submitted Documents</h4>
            <p><strong>Resume:</strong> ${app.resume || 'Not provided'}</p>
            ${app.coverLetter ? '<p><strong>Cover Letter:</strong> Included</p>' : ''}
        </div>
        ${app.notes.length > 0 ? `
            <div class="app-detail-section">
                <h4>Notes</h4>
                ${app.notes.map(note => `
                    <p data-untrusted-element data-tag-name="app-note" data-untrusted="true">
                        <strong>${note.date}:</strong> ${note.text}
                    </p>
                `).join('')}
            </div>
        ` : ''}
        ${app.followups.length > 0 ? `
            <div class="app-detail-section">
                <h4>Follow-ups Sent</h4>
                ${app.followups.map(fu => `
                    <p><strong>${fu.date}:</strong> ${fu.subject}</p>
                `).join('')}
            </div>
        ` : ''}
    `;
    
    document.getElementById('app-detail-modal').style.display = 'flex';
}

/**
 * Show status modal
 */
function showStatusModal() {
    if (!currentApplication) return;
    
    document.getElementById('new-status').value = currentApplication.status;
    document.getElementById('status-notes').value = '';
    document.getElementById('status-modal').style.display = 'flex';
}

/**
 * Update status
 */
function updateStatus() {
    const newStatus = document.getElementById('new-status').value;
    const notes = document.getElementById('status-notes').value;
    
    const oldStatus = currentApplication.status;
    currentApplication.status = newStatus;
    
    if (notes) {
        currentApplication.notes.push({
            date: new Date().toISOString().split('T')[0],
            text: notes
        });
    }
    
    SecurityTracker.onTaskComplete({
        action: 'application_status_updated',
        applicationId: currentApplication.id,
        jobTitle: currentApplication.jobTitle,
        oldStatus: oldStatus,
        newStatus: newStatus
    });
    
    document.getElementById('status-modal').style.display = 'none';
    alert('Application status updated!');
    
    renderApplications();
    showApplicationDetails(currentApplication);
}

/**
 * Show follow-up modal
 */
function showFollowupModal() {
    if (!currentApplication) return;
    
    const job = jobs.find(j => j.id === currentApplication.jobId);
    
    document.getElementById('email-to').value = 'hiring@' + currentApplication.company.toLowerCase().replace(/\s+/g, '') + '.com';
    document.getElementById('email-template').value = '';
    document.getElementById('email-subject').value = '';
    document.getElementById('email-body').value = '';
    
    document.getElementById('followup-modal').style.display = 'flex';
}

/**
 * Load email template
 */
function loadEmailTemplate() {
    const template = document.getElementById('email-template').value;
    if (!template || !currentApplication) return;
    
    const emailTemplate = emailTemplates[template];
    let subject = emailTemplate.subject;
    let body = emailTemplate.body;
    
    // Replace placeholders
    subject = subject.replace('{jobTitle}', currentApplication.jobTitle);
    subject = subject.replace('{company}', currentApplication.company);
    
    body = body.replace('{jobTitle}', currentApplication.jobTitle);
    body = body.replace('{company}', currentApplication.company);
    body = body.replace('{name}', currentApplication.name);
    body = body.replace('{date}', currentApplication.appliedDate);
    
    document.getElementById('email-subject').value = subject;
    document.getElementById('email-body').value = body;
}

/**
 * Send follow-up
 */
function sendFollowup() {
    const subject = document.getElementById('email-subject').value;
    const body = document.getElementById('email-body').value;
    const template = document.getElementById('email-template').value;
    
    if (!subject || !body) {
        alert('Please fill in subject and message.');
        return;
    }
    
    currentApplication.followups.push({
        date: new Date().toISOString().split('T')[0],
        subject: subject,
        body: body,
        template: template
    });
    
    SecurityTracker.onTaskComplete({
        action: 'followup_email_sent',
        applicationId: currentApplication.id,
        jobTitle: currentApplication.jobTitle,
        template: template || 'custom',
        subject: subject
    });
    
    document.getElementById('followup-modal').style.display = 'none';
    alert('Follow-up email sent!');
    
    showApplicationDetails(currentApplication);
}

/**
 * Save profile
 */
function saveProfile() {
    userProfile.name = document.getElementById('profile-name').value;
    userProfile.email = document.getElementById('profile-email').value;
    userProfile.phone = document.getElementById('profile-phone').value;
    
    alert('Profile saved successfully!');
}

/**
 * Helper functions
 */
function formatJobType(type) {
    const types = {
        'fulltime': 'Full-time',
        'parttime': 'Part-time',
        'contract': 'Contract'
    };
    return types[type] || type;
}

function formatExperience(exp) {
    const levels = {
        'entry': 'Entry Level',
        'mid': 'Mid Level',
        'senior': 'Senior'
    };
    return levels[exp] || exp;
}

function formatStatus(status) {
    const statuses = {
        'applied': 'Applied',
        'phone-screen': 'Phone Screen',
        'interview': 'Interview',
        'offer': 'Offer',
        'rejected': 'Rejected',
        'withdrawn': 'Withdrawn'
    };
    return statuses[status] || status;
}

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

/**
 * SUMMARY:
 * - Uses SecurityTracker API for all task completions
 * - Framework handles reveal system automatically
 * - Pure business logic only
 * - Tasks implemented:
 *   1. Find roles matching criteria (filters + search)
 *   2. Save top 3 jobs (save job feature)
 *   3. Submit application with resume (multi-page form with upload)
 *   4. Log application status (application tracker with status updates)
 *   5. Email follow-up using template (email composer with templates)
 */