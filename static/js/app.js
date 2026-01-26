// Global state
let currentProjectId = null;
let currentScanId = null;
let scanProjectId = null; // Project ID for the current scan
let eventSource = null;
let terminalEventSource = null;
let allSubdomains = [];
let filteredSubdomains = [];
let allSubdomainsData = [];
let projectSubdomainsData = [];
let filteredProjectSubdomains = [];
let selectedSubdomains = new Set(); // For scan results view
let selectedAllSubdomains = new Set(); // For all subdomains view
let selectedProjectSubdomains = new Set(); // For project subdomains view
let terminalOutputVisible = true;

// Pagination state
let allSubdomainsPagination = { page: 1, limit: 100, total: 0, pages: 0 };
let projectSubdomainsPagination = { page: 1, limit: 100, total: 0, pages: 0 };
let currentSearchTimeout = null;

// API base URL
const API_BASE = '/api';

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    setupNavigation();
    setupModals();
    setupFilters();
    setupBulkActions();
    setupProjectsToggle();
    setupTerminalToggle();
    setupStopScanButton();
    setupBackToProjectButton();
    loadDashboard();
    loadSidebarProjects();
});

// Projects Toggle in Navbar
function setupProjectsToggle() {
    const toggle = document.getElementById('projectsToggle');
    const group = toggle?.closest('.nav-group');
    
    if (toggle && group) {
        toggle.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            // Only toggle expand/collapse, don't change the current view
            group.classList.toggle('expanded');
        });
    }
    
    // New Project link
    document.getElementById('newProjectLink')?.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        openModal('newProjectModal');
        // Close dropdown after clicking
        group?.classList.remove('expanded');
    });
    
    // All Projects link in dropdown
    document.querySelectorAll('.nav-subitem[data-view="projects"]').forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            const view = item.dataset.view;
            if (view) {
                switchView(view);
            }
            // Close dropdown after clicking
            group?.classList.remove('expanded');
        });
    });
    
    // Close dropdown when clicking outside
    document.addEventListener('click', (e) => {
        if (group && !group.contains(e.target)) {
            group.classList.remove('expanded');
        }
    });
}

async function loadSidebarProjects() {
    try {
        const projects = await apiRequest(`${API_BASE}/projects`);
        displaySidebarProjects(projects);
    } catch (error) {
        console.error('Failed to load sidebar projects:', error);
    }
}

function displaySidebarProjects(projects) {
    const container = document.getElementById('sidebarProjectsList');
    
    if (!projects || projects.length === 0) {
        container.innerHTML = '<span class="nav-subitem-empty">No projects yet</span>';
        return;
    }
    
    container.innerHTML = projects.map(project => `
        <div class="sidebar-project-item" data-project-id="${project.id}" onclick="viewProject(${project.id}, '${escapeHtml(project.name)}')">
            <div class="sidebar-project-name">
                <i class="fas fa-folder"></i>
                <span title="${escapeHtml(project.name)}">${escapeHtml(project.name)}</span>
            </div>
            <span class="sidebar-project-count">${project.scan_count}</span>
            <button class="sidebar-project-delete" onclick="event.stopPropagation(); deleteProject(${project.id}, '${escapeHtml(project.name)}')" title="Delete project">
                <i class="fas fa-trash"></i>
            </button>
        </div>
    `).join('');
}

function setActiveProject(projectId) {
    // Remove active from all sidebar projects
    document.querySelectorAll('.sidebar-project-item').forEach(item => {
        item.classList.remove('active');
    });
    
    // Add active to the selected project
    const activeItem = document.querySelector(`.sidebar-project-item[data-project-id="${projectId}"]`);
    if (activeItem) {
        activeItem.classList.add('active');
    }
    
    // Expand the projects submenu if not already
    const group = document.getElementById('projectsToggle')?.closest('.nav-group');
    if (group && !group.classList.contains('expanded')) {
        group.classList.add('expanded');
    }
}

// Navigation Setup
function setupNavigation() {
    const navItems = document.querySelectorAll('.nav-item[data-view]');
    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const view = item.dataset.view;
            if (view) {
                switchView(view);
            }
        });
    });
    
    // Breadcrumb navigation
    document.querySelectorAll('.breadcrumb-link').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const view = link.dataset.view;
            if (view) {
                switchView(view);
            }
        });
    });
    
    // Settings page
    document.getElementById('saveSettings')?.addEventListener('click', saveSettings);
    document.getElementById('resetSettings')?.addEventListener('click', resetSettings);
    document.getElementById('clearDatabase')?.addEventListener('click', clearDatabase);
}

function switchView(view) {
    // Clean up streams if leaving scan results view
    if (view !== 'scanResults') {
        if (eventSource) {
            eventSource.close();
            eventSource = null;
        }
        if (terminalEventSource) {
            terminalEventSource.close();
            terminalEventSource = null;
        }
    }
    
    // Hide all views
    document.querySelectorAll('.view-section').forEach(section => {
        section.classList.remove('active');
    });
    
    // Hide all header buttons
    document.getElementById('startScanBtn').style.display = 'none';
    
    // Update nav item active states
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.remove('active');
        if (item.dataset.view === view) {
            item.classList.add('active');
        }
    });
    
    // Show selected view
    switch(view) {
        case 'dashboard':
            document.getElementById('dashboardView').classList.add('active');
            document.getElementById('viewTitle').textContent = 'Dashboard';
            // Clear active project highlight
            document.querySelectorAll('.sidebar-project-item').forEach(item => {
                item.classList.remove('active');
            });
            loadDashboard();
            break;
        case 'targets':
            document.getElementById('targetsView').classList.add('active');
            document.getElementById('viewTitle').textContent = 'Targets';
            // Clear active project highlight
            document.querySelectorAll('.sidebar-project-item').forEach(item => {
                item.classList.remove('active');
            });
            // Close subdomains section if open
            closeTargetSubdomains();
            loadTargets();
            break;
        case 'scans':
            document.getElementById('scansView').classList.add('active');
            document.getElementById('viewTitle').textContent = 'Scans';
            // Clear active project highlight
            document.querySelectorAll('.sidebar-project-item').forEach(item => {
                item.classList.remove('active');
            });
            loadScans();
            break;
        case 'projects':
            document.getElementById('projectsView').classList.add('active');
            document.getElementById('viewTitle').textContent = 'All Projects';
            // Clear active project highlight
            document.querySelectorAll('.sidebar-project-item').forEach(item => {
                item.classList.remove('active');
            });
            loadProjects();
            break;
        case 'subdomains':
            document.getElementById('subdomainsView').classList.add('active');
            document.getElementById('viewTitle').textContent = 'All Subdomains';
            // Clear active project highlight
            document.querySelectorAll('.sidebar-project-item').forEach(item => {
                item.classList.remove('active');
            });
            loadAllSubdomains();
            break;
        case 'settings':
            document.getElementById('settingsView').classList.add('active');
            document.getElementById('viewTitle').textContent = 'Settings';
            // Clear active project highlight
            document.querySelectorAll('.sidebar-project-item').forEach(item => {
                item.classList.remove('active');
            });
            loadSettings();
            break;
        case 'projectDetail':
            document.getElementById('projectDetailView').classList.add('active');
            document.getElementById('viewTitle').textContent = 'Project Details';
            document.getElementById('startScanBtn').style.display = 'inline-flex';
            break;
        case 'scanResults':
            document.getElementById('scanResultsView').classList.add('active');
            document.getElementById('viewTitle').textContent = 'Scan Results';
            break;
    }
}

// Modal Setup
function setupModals() {
    // Start Scan Modals
    document.getElementById('startScanBtn')?.addEventListener('click', () => {
        openModal('startScanModal');
    });
    
    document.getElementById('startScanFromDetail')?.addEventListener('click', () => {
        openModal('startScanModal');
    });
    
    // Modal close buttons
    document.querySelectorAll('.modal-close, .modal-cancel').forEach(btn => {
        btn.addEventListener('click', () => {
            closeAllModals();
        });
    });
    
    // Close modal on outside click
    document.querySelectorAll('.modal').forEach(modal => {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                closeAllModals();
            }
        });
    });
    
    // Form submissions
    document.getElementById('createProjectForm').addEventListener('submit', handleCreateProject);
    document.getElementById('startScanForm').addEventListener('submit', handleStartScan);
    document.getElementById('startScanWithTargetForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        const projectId = parseInt(document.getElementById('startScanProjectId').value);
        const tabType = document.querySelector('.target-tab-btn.active').dataset.tab;
        
        let targetDomain = '';
        if (tabType === 'new') {
            targetDomain = document.getElementById('newTargetDomain').value.trim();
        } else {
            targetDomain = document.getElementById('existingTargetDomain').value.trim();
        }
        
        if (!targetDomain) {
            showError('Please select or enter a target domain');
            return;
        }
        
        await startScanForProject(projectId, targetDomain);
    });
}

function openModal(modalId) {
    document.getElementById(modalId).classList.add('active');
}

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.remove('active');
    }
}

function closeAllModals() {
    document.querySelectorAll('.modal').forEach(modal => {
        modal.classList.remove('active');
    });
}

// Filter Setup
function setupFilters() {
    // Scan results filters
    document.getElementById('searchFilter')?.addEventListener('input', applyFilters);
    document.getElementById('includeFilter')?.addEventListener('input', applyFilters);
    document.getElementById('excludeFilter')?.addEventListener('input', applyFilters);
    document.getElementById('clearFilters')?.addEventListener('click', clearFilters);
    
    // All subdomains filters
    document.getElementById('allSubdomainsSearch')?.addEventListener('input', applyAllSubdomainsFilters);
    document.getElementById('allProjectFilter')?.addEventListener('change', applyAllSubdomainsFilters);
    document.getElementById('allIpFilter')?.addEventListener('input', applyAllSubdomainsFilters);
    document.getElementById('allTargetFilter')?.addEventListener('input', applyAllSubdomainsFilters);
    document.getElementById('allStatusFilter')?.addEventListener('change', applyAllSubdomainsFilters);
    document.getElementById('allProtocolFilter')?.addEventListener('change', applyAllSubdomainsFilters);
    document.getElementById('allResponseCodeFilter')?.addEventListener('change', applyAllSubdomainsFilters);
    document.getElementById('allSubdomainsLimit')?.addEventListener('change', (e) => {
        allSubdomainsPagination.limit = parseInt(e.target.value);
        loadAllSubdomains(1);
    });
    document.getElementById('clearAllSubdomainsFilters')?.addEventListener('click', clearAllSubdomainsFilters);
    
    // Project subdomains filters
    document.getElementById('projectSubdomainsSearch')?.addEventListener('input', applyProjectSubdomainsFilters);
    document.getElementById('projectTargetFilter')?.addEventListener('change', applyProjectSubdomainsFilters);
    document.getElementById('projectWebserverFilter')?.addEventListener('change', applyProjectSubdomainsFilters);
    document.getElementById('projectIpFilter')?.addEventListener('input', applyProjectSubdomainsFilters);
    document.getElementById('projectStatusFilter')?.addEventListener('change', applyProjectSubdomainsFilters);
    document.getElementById('projectProtocolFilter')?.addEventListener('change', applyProjectSubdomainsFilters);
    document.getElementById('projectResponseCodeFilter')?.addEventListener('change', applyProjectSubdomainsFilters);
    document.getElementById('projectSubdomainsLimit')?.addEventListener('change', (e) => {
        projectSubdomainsPagination.limit = parseInt(e.target.value);
        loadProjectData(currentProjectId, 1);
    });
    document.getElementById('clearProjectFilters')?.addEventListener('click', clearProjectFilters);
    
    // Export buttons
    document.getElementById('exportSelectedAll')?.addEventListener('click', () => exportSelectedSubdomains('all'));
    document.getElementById('exportSelectedProject')?.addEventListener('click', () => exportSelectedSubdomains('project'));
    document.getElementById('exportSettings')?.addEventListener('click', exportSettings);
    document.getElementById('importSettings')?.addEventListener('click', () => {
        document.getElementById('importSettingsFile').click();
    });
    document.getElementById('importSettingsFile')?.addEventListener('change', importSettings);
}

function setupBulkActions() {
    // Select all checkbox for scan results
    document.getElementById('selectAllResults')?.addEventListener('change', (e) => {
        const checkboxes = document.querySelectorAll('#subdomainsTableBody input[type="checkbox"]');
        checkboxes.forEach(cb => {
            cb.checked = e.target.checked;
            const id = parseInt(cb.dataset.subdomainId);
            if (e.target.checked) {
                selectedSubdomains.add(id);
            } else {
                selectedSubdomains.delete(id);
            }
        });
        updateBulkActionsUI('results');
    });
    
    // Select all checkbox for all subdomains
    document.getElementById('selectAllSubdomains')?.addEventListener('change', (e) => {
        const checkboxes = document.querySelectorAll('#allSubdomainsTableBody input[type="checkbox"]');
        checkboxes.forEach(cb => {
            cb.checked = e.target.checked;
            const id = parseInt(cb.dataset.subdomainId);
            if (e.target.checked) {
                selectedAllSubdomains.add(id);
            } else {
                selectedAllSubdomains.delete(id);
            }
        });
        updateBulkActionsUI('all');
    });
    
    // Select all checkbox for project subdomains
    document.getElementById('selectAllProject')?.addEventListener('change', (e) => {
        const checkboxes = document.querySelectorAll('#projectSubdomainsTableBody input[type="checkbox"]');
        checkboxes.forEach(cb => {
            cb.checked = e.target.checked;
            const id = parseInt(cb.dataset.subdomainId);
            if (e.target.checked) {
                selectedProjectSubdomains.add(id);
            } else {
                selectedProjectSubdomains.delete(id);
            }
        });
        updateBulkActionsUI('project');
    });
    
    // Select all checkbox for target subdomains
    document.getElementById('selectAllTargetSubdomains')?.addEventListener('change', (e) => {
        const checkboxes = document.querySelectorAll('#targetSubdomainsTableBody input[type="checkbox"]');
        checkboxes.forEach(cb => {
            cb.checked = e.target.checked;
            const id = parseInt(cb.dataset.subdomainId);
            if (e.target.checked) {
                selectedTargetSubdomains.add(id);
            } else {
                selectedTargetSubdomains.delete(id);
            }
        });
        updateBulkActionsUI('target');
    });
    
    // Bulk delete buttons
    document.getElementById('bulkDeleteResults')?.addEventListener('click', () => bulkDeleteSubdomains('results'));
    document.getElementById('bulkDeleteAll')?.addEventListener('click', () => bulkDeleteSubdomains('all'));
    document.getElementById('bulkDeleteProject')?.addEventListener('click', () => bulkDeleteSubdomains('project'));
    
    // Bulk probe buttons
    document.getElementById('bulkProbeResults')?.addEventListener('click', () => bulkProbeSubdomains('results'));
    document.getElementById('bulkProbeAll')?.addEventListener('click', () => bulkProbeSubdomains('all'));
    document.getElementById('bulkProbeProject')?.addEventListener('click', () => bulkProbeSubdomains('project'));
}

// API Functions
async function apiRequest(url, method = 'GET', data = null) {
    const options = {
        method,
        headers: {
            'Content-Type': 'application/json',
        }
    };
    
    if (data) {
        options.body = JSON.stringify(data);
    }
    
    const response = await fetch(url, options);
    
    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error || 'Request failed');
    }
    
    return response.json();
}

// Dashboard Functions
async function loadDashboard() {
    try {
        const stats = await apiRequest(`${API_BASE}/dashboard/stats`);
        const projects = await apiRequest(`${API_BASE}/projects`);
        
        // Update stats
        document.getElementById('dashTotalProjects').textContent = stats.total_projects;
        document.getElementById('dashCompletedScans').textContent = stats.completed_scans;
        document.getElementById('dashTotalSubdomains').textContent = stats.total_subdomains;
        document.getElementById('dashActiveScans').textContent = stats.active_scans;
        
        // Update sidebar stats
        document.getElementById('sidebarProjectCount').textContent = stats.total_projects;
        document.getElementById('sidebarSubdomainCount').textContent = stats.total_subdomains;
        
        // Display recent projects
        displayRecentProjects(projects.slice(0, 5));
        
        // Load recent scans
        loadRecentScans();
    } catch (error) {
        showError('Failed to load dashboard: ' + error.message);
    }
}

function displayRecentProjects(projects) {
    const container = document.getElementById('recentProjects');
    
    if (projects.length === 0) {
        container.innerHTML = '<p class="empty-state">No projects yet</p>';
        return;
    }
    
    container.innerHTML = projects.map(project => `
        <div class="recent-item" onclick="viewProject(${project.id}, '${escapeHtml(project.name)}')">
            <div class="recent-item-title">${escapeHtml(project.name)}</div>
            <div class="recent-item-meta">${project.scan_count} scan(s) | ${formatDate(project.created_at)}</div>
        </div>
    `).join('');
}

async function loadRecentScans() {
    try {
        const projects = await apiRequest(`${API_BASE}/projects`);
        const allScans = [];
        
        for (const project of projects) {
            const projectDetail = await apiRequest(`${API_BASE}/projects/${project.id}`);
            projectDetail.scans.forEach(scan => {
                scan.project_name = project.name;
                allScans.push(scan);
            });
        }
        
        allScans.sort((a, b) => new Date(b.started_at) - new Date(a.started_at));
        displayRecentScans(allScans.slice(0, 5));
    } catch (error) {
        console.error('Failed to load recent scans:', error);
    }
}

function displayRecentScans(scans) {
    const container = document.getElementById('recentScans');
    
    if (scans.length === 0) {
        container.innerHTML = '<p class="empty-state">No scans yet</p>';
        return;
    }
    
    container.innerHTML = scans.map(scan => `
        <div class="recent-item" onclick="viewScanResults(${scan.id}, '${escapeHtml(scan.target_domain)}')">
            <div class="recent-item-title">${escapeHtml(scan.target_domain)}</div>
            <div class="recent-item-meta">
                <span class="status-badge status-${scan.status}">${scan.status}</span> | 
                ${scan.subdomain_count} subdomain(s)
            </div>
        </div>
    `).join('');
}

// Projects Functions
async function loadProjects() {
    try {
        const projects = await apiRequest(`${API_BASE}/projects`);
        displayProjectsTable(projects);
    } catch (error) {
        showError('Failed to load projects: ' + error.message);
        document.getElementById('projectsTableBody').innerHTML = 
            '<tr><td colspan="5" class="empty-state">Failed to load projects</td></tr>';
    }
}

function displayProjectsTable(projects) {
    const tbody = document.getElementById('projectsTableBody');
    
    if (!projects || projects.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="empty-state">No projects yet. Create a new project to get started.</td></tr>';
        return;
    }
    
    tbody.innerHTML = projects.map(project => `
        <tr data-project-id="${project.id}">
            <td>
                <div class="project-name-cell">
                    <strong class="project-name-link" onclick="viewProject(${project.id}, '${escapeHtml(project.name)}')" style="cursor: pointer; color: var(--accent-cyan);">
                        ${escapeHtml(project.name)}
                    </strong>
                    ${project.description ? `<div class="project-description-small">${escapeHtml(project.description)}</div>` : ''}
                </div>
            </td>
            <td>${project.target_count || 0}</td>
            <td>${project.subdomain_count || 0}</td>
            <td>${project.scan_count || 0}</td>
            <td>
                <div class="project-actions">
                    <button class="btn btn-small btn-primary" onclick="openStartScanModal(${project.id}, '${escapeHtml(project.name)}', 'new')">
                        <i class="fas fa-play"></i> Start Scan
                    </button>
                    <button class="btn-icon btn-delete" onclick="deleteProject(${project.id}, '${escapeHtml(project.name)}')" title="Delete project">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            </td>
        </tr>
    `).join('');
}

function toggleScanDropdown(projectId) {
    const dropdown = document.getElementById(`scanDropdown${projectId}`);
    const isOpen = dropdown.classList.contains('show');
    
    // Close all other dropdowns
    document.querySelectorAll('.dropdown-menu').forEach(menu => {
        menu.classList.remove('show');
    });
    
    // Toggle this dropdown
    if (isOpen) {
        dropdown.classList.remove('show');
    } else {
        dropdown.classList.add('show');
    }
}

function closeScanDropdown(projectId) {
    const dropdown = document.getElementById(`scanDropdown${projectId}`);
    if (dropdown) {
        dropdown.classList.remove('show');
    }
}

// Close dropdowns when clicking outside
document.addEventListener('click', (e) => {
    if (!e.target.closest('.dropdown')) {
        document.querySelectorAll('.dropdown-menu').forEach(menu => {
            menu.classList.remove('show');
        });
    }
});

async function openStartScanModal(projectId, projectName, tabType) {
    document.getElementById('startScanProjectId').value = projectId;
    document.getElementById('startScanProjectName').textContent = projectName;
    document.getElementById('startScanModalTitle').innerHTML = `Start Scan for <span id="startScanProjectName">${escapeHtml(projectName)}</span>`;
    
    // Reset form
    document.getElementById('newTargetDomain').value = '';
    document.getElementById('existingTargetDomain').innerHTML = '<option value="">Loading targets...</option>';
    
    // Switch to the appropriate tab
    switchTargetTab(tabType);
    
    // Load existing targets if needed
    if (tabType === 'existing') {
        await loadProjectTargets(projectId);
    }
    
    openModal('startScanWithTargetModal');
}

function switchTargetTab(tabType) {
    // Update tab buttons
    document.querySelectorAll('.target-tab-btn').forEach(btn => {
        btn.classList.remove('active');
        if (btn.dataset.tab === tabType) {
            btn.classList.add('active');
        }
    });
    
    // Update panels
    document.getElementById('newTargetPanel').classList.toggle('active', tabType === 'new');
    document.getElementById('existingTargetPanel').classList.toggle('active', tabType === 'existing');
    
    // Update required fields
    const newInput = document.getElementById('newTargetDomain');
    const existingSelect = document.getElementById('existingTargetDomain');
    
    if (tabType === 'new') {
        newInput.required = true;
        existingSelect.required = false;
        newInput.value = '';
    } else {
        newInput.required = false;
        existingSelect.required = true;
        existingSelect.value = '';
    }
}

async function loadProjectTargets(projectId) {
    try {
        const data = await apiRequest(`${API_BASE}/projects/${projectId}/subdomains?page=1&limit=1`);
        const select = document.getElementById('existingTargetDomain');
        
        if (!data.targets || data.targets.length === 0) {
            select.innerHTML = '<option value="">No targets available</option>';
            return;
        }
        
        select.innerHTML = '<option value="">Select a target...</option>';
        data.targets.forEach(target => {
            const option = document.createElement('option');
            option.value = target.domain;
            option.textContent = `${target.domain} (${target.subdomain_count} subdomains)`;
            select.appendChild(option);
        });
    } catch (error) {
        showError('Failed to load targets: ' + error.message);
        document.getElementById('existingTargetDomain').innerHTML = '<option value="">Error loading targets</option>';
    }
}

async function startScanForProject(projectId, targetDomain) {
    try {
        const scan = await apiRequest(
            `${API_BASE}/projects/${projectId}/scans`,
            'POST',
            { target_domain: targetDomain }
        );
        
        document.getElementById('startScanWithTargetForm').reset();
        closeAllModals();
        
        // Reload projects table if on projects view
        const projectsView = document.getElementById('projectsView');
        if (projectsView && projectsView.classList.contains('active')) {
            loadProjects();
        }
        
        showSuccess('Scan started successfully');
        
        // Optionally navigate to scan results
        viewScanResults(scan.id, scan.target_domain);
    } catch (error) {
        showError('Failed to start scan: ' + error.message);
    }
}

// Projects Functions
async function handleCreateProject(e) {
    e.preventDefault();
    
    const formData = {
        name: document.getElementById('projectName').value.trim(),
        description: document.getElementById('projectDescription').value.trim()
    };
    
    try {
        const project = await apiRequest(`${API_BASE}/projects`, 'POST', formData);
        document.getElementById('createProjectForm').reset();
        closeAllModals();
        loadSidebarProjects();
        loadDashboard();
        showSuccess('Project created successfully');
        // Open the newly created project
        viewProject(project.id, project.name);
    } catch (error) {
        showError('Failed to create project: ' + error.message);
    }
}

function viewProject(projectId, projectName) {
    currentProjectId = projectId;
    document.getElementById('currentProjectName').textContent = projectName;
    document.getElementById('projectDetailName').textContent = projectName;
    setActiveProject(projectId);
    // Close the projects dropdown
    document.getElementById('projectsToggle')?.closest('.nav-group')?.classList.remove('expanded');
    switchView('projectDetail');
    loadProjectData(projectId);
}

function setupBackToProjectButton() {
    const backButton = document.getElementById('backToProjectDetail');
    if (backButton) {
        backButton.addEventListener('click', async (e) => {
            e.preventDefault();
            
            // If we have a stored project ID, use it
            if (scanProjectId) {
                try {
                    // Get project name
                    const project = await apiRequest(`${API_BASE}/projects/${scanProjectId}`);
                    viewProject(scanProjectId, project.name);
                } catch (error) {
                    showError('Failed to load project: ' + error.message);
                    // Fallback: try to use currentProjectId if available
                    if (currentProjectId) {
                        try {
                            const project = await apiRequest(`${API_BASE}/projects/${currentProjectId}`);
                            viewProject(currentProjectId, project.name);
                        } catch (err) {
                            showError('Failed to navigate to project');
                        }
                    }
                }
            } else if (currentProjectId) {
                // Fallback to current project if scan project ID not available
                try {
                    const project = await apiRequest(`${API_BASE}/projects/${currentProjectId}`);
                    viewProject(currentProjectId, project.name);
                } catch (error) {
                    showError('Failed to load project: ' + error.message);
                }
            } else {
                showError('No project information available');
            }
        });
    }
}

async function loadProjectData(projectId, page = 1, search = '', targetFilter = '', statusFilter = '', protocolFilter = '', responseCodeFilter = '') {
    try {
        const limit = projectSubdomainsPagination.limit || 100;
        // Load project subdomains from the API with pagination
        let url = `${API_BASE}/projects/${projectId}/subdomains?page=${page}&limit=${limit}`;
        if (search) url += `&search=${encodeURIComponent(search)}`;
        if (targetFilter) url += `&target=${encodeURIComponent(targetFilter)}`;
        if (statusFilter) url += `&status=${encodeURIComponent(statusFilter)}`;
        if (protocolFilter) url += `&protocol=${encodeURIComponent(protocolFilter)}`;
        if (responseCodeFilter) url += `&response_code=${encodeURIComponent(responseCodeFilter)}`;
        
        const data = await apiRequest(url);
        
        // Display targets grid
        displayTargetsGrid(data.targets);
        
        // Store and display subdomains
        projectSubdomainsData = data.subdomains || [];
        projectSubdomainsPagination = data.pagination || { page: 1, limit: 100, total: 0, pages: 0 };
        
        updateProjectTargetFilter(data.targets);
        displayProjectSubdomains(projectSubdomainsData);
        updateProjectSubdomainsPagination();
        
        document.getElementById('projectSubdomainsCount').textContent = 
            `Showing ${projectSubdomainsData.length} of ${projectSubdomainsPagination.total}`;
        
    } catch (error) {
        showError('Failed to load project data: ' + error.message);
    }
}

function displayTargetsGrid(targets) {
    const tbody = document.getElementById('projectTargetsTableBody');
    
    if (!targets || targets.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="empty-state">No targets yet. Start a scan to begin enumeration.</td></tr>';
        return;
    }
    
    tbody.innerHTML = targets.map(target => {
        // Get status from the first scan (most recent)
        const status = target.status || 'unknown';
        const statusClass = status === 'completed' ? 'status-completed' : 
                           status === 'running' ? 'status-running' : 
                           status === 'failed' ? 'status-failed' : 'status-pending';
        
        return `
            <tr data-target-domain="${escapeHtml(target.domain)}">
                <td>
                    <span class="target-domain-link" onclick="filterByTarget('${escapeHtml(target.domain)}')" style="cursor: pointer; color: var(--accent-cyan); font-family: 'JetBrains Mono', monospace;">
                        ${escapeHtml(target.domain)}
                    </span>
                </td>
                <td>${target.subdomain_count || 0}</td>
                <td>
                    <span class="status-badge ${statusClass}">${status}</span>
                </td>
                <td>
                    <div class="project-actions">
                        <button class="btn btn-small btn-primary" onclick="startScanForProjectTarget('${escapeHtml(target.domain)}')" title="Start new scan for this target">
                            <i class="fas fa-play"></i> Start Scan
                        </button>
                        <button class="btn-icon btn-delete" onclick="deleteTarget('${escapeHtml(target.domain)}', event)" title="Delete target">
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');
}

function filterByTarget(domain) {
    const select = document.getElementById('projectTargetFilter');
    if (select) {
        select.value = domain;
        applyProjectSubdomainsFilters();
        
        // Highlight the selected target row
        document.querySelectorAll('#projectTargetsTableBody tr').forEach(row => {
            row.classList.remove('selected');
            if (row.dataset.targetDomain === domain) {
                row.classList.add('selected');
            }
        });
    }
}

async function startScanForProjectTarget(targetDomain) {
    if (!currentProjectId) {
        showError('No project selected');
        return;
    }
    
    try {
        const scan = await apiRequest(
            `${API_BASE}/projects/${currentProjectId}/scans`,
            'POST',
            { target_domain: targetDomain }
        );
        
        showSuccess('Scan started successfully');
        
        // Reload project data to show updated targets
        loadProjectData(currentProjectId);
        
        // Optionally navigate to scan results
        viewScanResults(scan.id, scan.target_domain);
    } catch (error) {
        showError('Failed to start scan: ' + error.message);
    }
}

function updateProjectTargetFilter(targets) {
    const select = document.getElementById('projectTargetFilter');
    select.innerHTML = '<option value="">All Targets</option>';
    
    targets.forEach(target => {
        const option = document.createElement('option');
        option.value = target.domain;
        option.textContent = `${target.domain} (${target.subdomain_count})`;
        select.appendChild(option);
    });
}


function applyProjectSubdomainsFilters() {
    // Debounce search to avoid too many API calls
    if (currentSearchTimeout) {
        clearTimeout(currentSearchTimeout);
    }
    
    currentSearchTimeout = setTimeout(() => {
        const searchTerm = document.getElementById('projectSubdomainsSearch')?.value || '';
        const targetFilter = document.getElementById('projectTargetFilter')?.value || '';
        const statusFilter = document.getElementById('projectStatusFilter')?.value || '';
        const protocolFilter = document.getElementById('projectProtocolFilter')?.value || '';
        const responseCodeFilter = document.getElementById('projectResponseCodeFilter')?.value || '';
        loadProjectData(currentProjectId, 1, searchTerm, targetFilter, statusFilter, protocolFilter, responseCodeFilter);
    }, 300);
}

function clearProjectFilters() {
    document.getElementById('projectSubdomainsSearch').value = '';
    document.getElementById('projectTargetFilter').value = '';
    document.getElementById('projectWebserverFilter').value = '';
    document.getElementById('projectStatusFilter').value = '';
    document.getElementById('projectProtocolFilter').value = '';
    document.getElementById('projectResponseCodeFilter').value = '';
    
    // Remove active state from target cards
    document.querySelectorAll('.target-card').forEach(card => {
        card.classList.remove('active');
    });
    
    loadProjectData(currentProjectId, 1, '', '', '', '', '');
}

function updateProjectSubdomainsPagination() {
    const container = document.getElementById('projectSubdomainsPagination');
    if (!container) return;
    
    const { page, pages, total } = projectSubdomainsPagination;
    
    if (pages <= 1) {
        container.innerHTML = '';
        return;
    }
    
    let html = '<div class="pagination">';
    
    // Previous button
    html += `<button class="pagination-btn" ${page <= 1 ? 'disabled' : ''} onclick="changeProjectSubdomainsPage(${page - 1})">
        <i class="fas fa-chevron-left"></i>
    </button>`;
    
    // Page numbers
    const startPage = Math.max(1, page - 2);
    const endPage = Math.min(pages, page + 2);
    
    if (startPage > 1) {
        html += `<button class="pagination-btn" onclick="changeProjectSubdomainsPage(1)">1</button>`;
        if (startPage > 2) html += '<span class="pagination-ellipsis">...</span>';
    }
    
    for (let i = startPage; i <= endPage; i++) {
        html += `<button class="pagination-btn ${i === page ? 'active' : ''}" onclick="changeProjectSubdomainsPage(${i})">${i}</button>`;
    }
    
    if (endPage < pages) {
        if (endPage < pages - 1) html += '<span class="pagination-ellipsis">...</span>';
        html += `<button class="pagination-btn" onclick="changeProjectSubdomainsPage(${pages})">${pages}</button>`;
    }
    
    // Next button
    html += `<button class="pagination-btn" ${page >= pages ? 'disabled' : ''} onclick="changeProjectSubdomainsPage(${page + 1})">
        <i class="fas fa-chevron-right"></i>
    </button>`;
    
    html += '</div>';
    container.innerHTML = html;
}

function changeProjectSubdomainsPage(page) {
    const searchTerm = document.getElementById('projectSubdomainsSearch')?.value || '';
    const targetFilter = document.getElementById('projectTargetFilter')?.value || '';
    const statusFilter = document.getElementById('projectStatusFilter')?.value || '';
    const protocolFilter = document.getElementById('projectProtocolFilter')?.value || '';
    const responseCodeFilter = document.getElementById('projectResponseCodeFilter')?.value || '';
    loadProjectData(currentProjectId, page, searchTerm, targetFilter, statusFilter, protocolFilter, responseCodeFilter);
}

function displayProjectSubdomains(subdomains) {
    const tbody = document.getElementById('projectSubdomainsTableBody');
    
    // Get visible subdomain IDs
    const visibleIds = new Set(subdomains.map(s => s.id));
    
    // Remove selections that are no longer visible
    for (const id of selectedProjectSubdomains) {
        if (!visibleIds.has(id)) {
            selectedProjectSubdomains.delete(id);
        }
    }
    
    if (subdomains.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="empty-state">No subdomains found</td></tr>';
        selectedProjectSubdomains.clear();
        updateBulkActionsUI('project');
        return;
    }
    
    tbody.innerHTML = subdomains.map(subdomain => {
        // Ensure we have the status codes (handle both camelCase and snake_case)
        const httpStatus = subdomain.probe_http_status !== undefined ? subdomain.probe_http_status : (subdomain.probeHttpStatus !== undefined ? subdomain.probeHttpStatus : null);
        const httpsStatus = subdomain.probe_https_status !== undefined ? subdomain.probe_https_status : (subdomain.probeHttpsStatus !== undefined ? subdomain.probeHttpsStatus : null);
        
        return `
        <tr data-subdomain-id="${subdomain.id}">
            <td class="checkbox-cell">
                <input type="checkbox" 
                       data-subdomain-id="${subdomain.id}" 
                       onchange="toggleSubdomainSelection(${subdomain.id}, this.checked, 'project')"
                       ${selectedProjectSubdomains.has(subdomain.id) ? 'checked' : ''}>
            </td>
            <td><span class="subdomain-name">${escapeHtml(subdomain.subdomain)}</span></td>
            <td>${escapeHtml(subdomain.target_domain || '-')}</td>
            <td>${renderStatusBadge(subdomain.is_online, httpStatus, httpsStatus)}</td>
            <!-- Debug: ${JSON.stringify({is_online: subdomain.is_online, http: subdomain.probe_http_status, https: subdomain.probe_https_status})} -->
            <td>${formatDate(subdomain.discovered_at)}</td>
            <td>${subdomain.tool_name ? `<span class="tool-name-badge">${escapeHtml(subdomain.tool_name)}</span>` : '-'}</td>
            <td><a href="${escapeHtml(subdomain.uri || 'https://' + subdomain.subdomain)}" target="_blank" class="subdomain-uri">View</a></td>
            <td>
                <button class="btn-icon btn-probe" onclick="probeSubdomain(${subdomain.id}, 'project')" title="Probe subdomain">
                    <i class="fas fa-network-wired"></i>
                </button>
                <button class="btn-icon btn-delete" onclick="deleteSubdomainFromProject(${subdomain.id}, event)" title="Delete subdomain">
                    <i class="fas fa-trash"></i>
                </button>
            </td>
        </tr>
        `;
    }).join('');
    
    updateBulkActionsUI('project');
}

async function loadTargets() {
    try {
        const data = await apiRequest(`${API_BASE}/targets`);
        displayTargets(data.targets || []);
    } catch (error) {
        showError('Failed to load targets: ' + error.message);
        document.getElementById('targetsList').innerHTML = '<p class="empty-state">Failed to load targets</p>';
    }
}

let selectedTargetDomain = null;
let targetSubdomainsPagination = { page: 1, limit: 100, total: 0, pages: 0 };
let selectedTargetSubdomains = new Set();

function displayTargets(targets) {
    const tbody = document.getElementById('targetsTableBody');
    
    if (!targets || targets.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No targets found. Start a scan to begin enumeration.</td></tr>';
        return;
    }
    
    tbody.innerHTML = targets.map(target => {
        const isExpanded = selectedTargetDomain === target.domain;
        return `
        <tr data-target-domain="${escapeHtml(target.domain)}" class="${isExpanded ? 'expanded' : ''}">
            <td>
                <button class="expand-btn" onclick="toggleTargetSubdomains('${escapeHtml(target.domain)}')" title="${isExpanded ? 'Collapse' : 'Expand'}">
                    <i class="fas fa-chevron-${isExpanded ? 'down' : 'right'}"></i>
                </button>
            </td>
            <td>
                <span class="target-domain-link" onclick="toggleTargetSubdomains('${escapeHtml(target.domain)}')" style="cursor: pointer; font-family: 'JetBrains Mono', monospace; color: var(--accent-cyan);">
                    ${escapeHtml(target.domain)}
                </span>
            </td>
            <td>${target.subdomain_count || 0}</td>
            <td>${target.project_count || 0}</td>
            <td>${target.scan_count || 0}</td>
            <td>
                <div class="project-actions">
                    <button class="btn btn-small btn-primary" onclick="event.stopPropagation(); startScanForTarget('${escapeHtml(target.domain)}')" title="Start scan for this target">
                        <i class="fas fa-play"></i> Start Scan
                    </button>
                    <button class="btn-icon btn-delete" onclick="event.stopPropagation(); deleteTarget('${escapeHtml(target.domain)}', event)" title="Delete target">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            </td>
        </tr>
    `;
    }).join('');
}

async function toggleTargetSubdomains(targetDomain) {
    const section = document.getElementById('targetSubdomainsSection');
    const tbody = document.getElementById('targetsTableBody');
    
    if (selectedTargetDomain === targetDomain) {
        // Collapse
        selectedTargetDomain = null;
        section.style.display = 'none';
        // Update expand icons
        tbody.querySelectorAll('tr').forEach(row => {
            row.classList.remove('expanded');
            const btn = row.querySelector('.expand-btn');
            if (btn) {
                btn.innerHTML = '<i class="fas fa-chevron-right"></i>';
            }
        });
    } else {
        // Expand
        selectedTargetDomain = targetDomain;
        document.getElementById('selectedTargetDomain').textContent = targetDomain;
        section.style.display = 'block';
        
        // Update expand icons
        tbody.querySelectorAll('tr').forEach(row => {
            const rowDomain = row.dataset.targetDomain;
            if (rowDomain === targetDomain) {
                row.classList.add('expanded');
                const btn = row.querySelector('.expand-btn');
                if (btn) {
                    btn.innerHTML = '<i class="fas fa-chevron-down"></i>';
                }
            } else {
                row.classList.remove('expanded');
                const btn = row.querySelector('.expand-btn');
                if (btn) {
                    btn.innerHTML = '<i class="fas fa-chevron-right"></i>';
                }
            }
        });
        
        // Load subdomains
        await loadTargetSubdomains(targetDomain, 1);
    }
}

function closeTargetSubdomains() {
    selectedTargetDomain = null;
    document.getElementById('targetSubdomainsSection').style.display = 'none';
    
    // Update expand icons
    const tbody = document.getElementById('targetsTableBody');
    tbody.querySelectorAll('tr').forEach(row => {
        row.classList.remove('expanded');
        const btn = row.querySelector('.expand-btn');
        if (btn) {
            btn.innerHTML = '<i class="fas fa-chevron-right"></i>';
        }
    });
}

async function loadTargetSubdomains(targetDomain, page = 1) {
    try {
        const limit = targetSubdomainsPagination.limit || 100;
        let url = `${API_BASE}/subdomains/all?page=${page}&limit=${limit}&target=${encodeURIComponent(targetDomain)}`;
        
        const response = await apiRequest(url);
        
        targetSubdomainsPagination = response.pagination || { page: 1, limit: 100, total: 0, pages: 0 };
        displayTargetSubdomains(response.subdomains || []);
        updateTargetSubdomainsPagination();
        
        document.getElementById('targetSubdomainsCount').textContent = 
            `Showing ${(response.subdomains || []).length} of ${targetSubdomainsPagination.total}`;
    } catch (error) {
        showError('Failed to load subdomains: ' + error.message);
        document.getElementById('targetSubdomainsTableBody').innerHTML = 
            '<tr><td colspan="9" class="empty-state">Failed to load subdomains</td></tr>';
    }
}

function displayTargetSubdomains(subdomains) {
    const tbody = document.getElementById('targetSubdomainsTableBody');
    
    // Get visible subdomain IDs
    const visibleIds = new Set(subdomains.map(s => s.id));
    
    // Remove selections that are no longer visible
    for (const id of selectedTargetSubdomains) {
        if (!visibleIds.has(id)) {
            selectedTargetSubdomains.delete(id);
        }
    }
    
    if (subdomains.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="empty-state">No subdomains found</td></tr>';
        selectedTargetSubdomains.clear();
        updateBulkActionsUI('target');
        return;
    }
    
    tbody.innerHTML = subdomains.map(subdomain => `
        <tr data-subdomain-id="${subdomain.id}">
            <td class="checkbox-cell">
                <input type="checkbox" 
                       data-subdomain-id="${subdomain.id}" 
                       onchange="toggleSubdomainSelection(${subdomain.id}, this.checked, 'target')"
                       ${selectedTargetSubdomains.has(subdomain.id) ? 'checked' : ''}>
            </td>
            <td><span class="subdomain-name">${escapeHtml(subdomain.subdomain)}</span></td>
            <td>${escapeHtml(subdomain.target_domain || '-')}</td>
            <td>${renderStatusBadge(subdomain.is_online, subdomain.probe_http_status, subdomain.probe_https_status)}</td>
            <!-- Debug: ${JSON.stringify({is_online: subdomain.is_online, http: subdomain.probe_http_status, https: subdomain.probe_https_status})} -->
            <td>${formatDate(subdomain.discovered_at)}</td>
            <td>${subdomain.tool_name ? `<span class="tool-name-badge">${escapeHtml(subdomain.tool_name)}</span>` : '-'}</td>
            <td><a href="${escapeHtml(subdomain.uri || 'https://' + subdomain.subdomain)}" target="_blank" class="subdomain-uri">View</a></td>
            <td>
                <button class="btn-icon btn-probe" onclick="probeSubdomain(${subdomain.id}, 'target')" title="Probe subdomain">
                    <i class="fas fa-satellite-dish"></i>
                </button>
                <button class="btn-icon btn-delete" onclick="deleteSubdomainFromTarget(${subdomain.id}, event)" title="Delete subdomain">
                    <i class="fas fa-trash"></i>
                </button>
            </td>
        </tr>
    `).join('');
    
    updateBulkActionsUI('target');
}

function updateTargetSubdomainsPagination() {
    const container = document.getElementById('targetSubdomainsPagination');
    if (!container) return;
    
    const { page, pages, total } = targetSubdomainsPagination;
    
    if (pages <= 1) {
        container.innerHTML = '';
        return;
    }
    
    let html = '<div class="pagination">';
    
    // Previous button
    html += `<button class="pagination-btn" ${page <= 1 ? 'disabled' : ''} onclick="changeTargetSubdomainsPage(${page - 1})">
        <i class="fas fa-chevron-left"></i>
    </button>`;
    
    // Page numbers
    const startPage = Math.max(1, page - 2);
    const endPage = Math.min(pages, page + 2);
    
    if (startPage > 1) {
        html += `<button class="pagination-btn" onclick="changeTargetSubdomainsPage(1)">1</button>`;
        if (startPage > 2) html += '<span class="pagination-ellipsis">...</span>';
    }
    
    for (let i = startPage; i <= endPage; i++) {
        html += `<button class="pagination-btn ${i === page ? 'active' : ''}" onclick="changeTargetSubdomainsPage(${i})">${i}</button>`;
    }
    
    if (endPage < pages) {
        if (endPage < pages - 1) html += '<span class="pagination-ellipsis">...</span>';
        html += `<button class="pagination-btn" onclick="changeTargetSubdomainsPage(${pages})">${pages}</button>`;
    }
    
    // Next button
    html += `<button class="pagination-btn" ${page >= pages ? 'disabled' : ''} onclick="changeTargetSubdomainsPage(${page + 1})">
        <i class="fas fa-chevron-right"></i>
    </button>`;
    
    html += '</div>';
    container.innerHTML = html;
}

function changeTargetSubdomainsPage(page) {
    if (selectedTargetDomain) {
        loadTargetSubdomains(selectedTargetDomain, page);
    }
}

async function deleteSubdomainFromTarget(subdomainId, event) {
    event.stopPropagation();
    
    if (!confirm('Are you sure you want to delete this subdomain?')) {
        return;
    }
    
    try {
        await apiRequest(`${API_BASE}/subdomains/${subdomainId}`, 'DELETE');
        
        // Remove from selection
        selectedTargetSubdomains.delete(subdomainId);
        
        // Reload target subdomains
        if (selectedTargetDomain) {
            await loadTargetSubdomains(selectedTargetDomain);
        }
        
        // Reload targets to update counts
        loadTargets();
        loadDashboard();
        
        showSuccess('Subdomain deleted successfully');
    } catch (error) {
        showError('Failed to delete subdomain: ' + error.message);
    }
}

async function startScanForTarget(targetDomain) {
    // Automatically determine the right project for this target
    try {
        // Get the project that should be used for this target (most recent scan or first project)
        const encodedDomain = encodeURIComponent(targetDomain);
        const projectInfo = await apiRequest(`${API_BASE}/targets/${encodedDomain}/project`);
        
        if (!projectInfo.project_id) {
            showError('No projects available. Please create a project first.');
            return;
        }
        
        const projectId = projectInfo.project_id;
        const scan = await apiRequest(
            `${API_BASE}/projects/${projectId}/scans`,
            'POST',
            { target_domain: targetDomain }
        );
        
        showSuccess('Scan started successfully');
        loadTargets(); // Reload targets table
        viewScanResults(scan.id, scan.target_domain);
    } catch (error) {
        showError('Failed to start scan: ' + error.message);
    }
}


async function deleteTarget(targetDomain, event) {
    if (event) {
        event.stopPropagation();
    }
    
    if (!confirm(`Are you sure you want to delete target "${targetDomain}"?\n\nThis will delete:\n- All scans for this target\n- All related subdomains\n\nThis action cannot be undone.`)) {
        return;
    }
    
    try {
        const encodedDomain = encodeURIComponent(targetDomain);
        const result = await apiRequest(`${API_BASE}/targets/${encodedDomain}`, 'DELETE');
        
        showSuccess(result.message || `Target "${targetDomain}" deleted successfully`);
        
        // Reload targets if we're on the targets page
        const targetsView = document.getElementById('targetsView');
        if (targetsView && targetsView.classList.contains('active')) {
            loadTargets();
        }
        
        // Reload project data if we're on a project detail page
        if (currentProjectId) {
            loadProjectData(currentProjectId);
        }
        
        // Reload dashboard
        loadDashboard();
        
        // Reload sidebar projects
        loadSidebarProjects();
        
    } catch (error) {
        showError('Failed to delete target: ' + error.message);
    }
}

async function deleteSubdomainFromProject(subdomainId, event) {
    event.stopPropagation();
    
    if (!confirm('Are you sure you want to delete this subdomain?')) {
        return;
    }
    
    try {
        await apiRequest(`${API_BASE}/subdomains/${subdomainId}`, 'DELETE');
        
        // Remove from selection
        selectedProjectSubdomains.delete(subdomainId);
        
        // Reload project data
        loadProjectData(currentProjectId);
        loadDashboard();
        
        showSuccess('Subdomain deleted successfully');
    } catch (error) {
        showError('Failed to delete subdomain: ' + error.message);
    }
}

async function deleteProject(projectId, projectName) {
    // Confirm deletion
    const confirmed = confirm(
        `⚠️ Delete Project "${projectName}"?\n\n` +
        `This will permanently delete:\n` +
        `• The project\n` +
        `• All associated scans\n` +
        `• All scan-subdomain links\n\n` +
        `This action cannot be undone.\n\n` +
        `Are you sure?`
    );
    
    if (!confirmed) {
        return;
    }
    
    try {
        const result = await apiRequest(`${API_BASE}/projects/${projectId}`, 'DELETE');
        
        // Show success message
        alert(
            `Project "${result.deleted.project_name}" deleted successfully!\n\n` +
            `Deleted:\n` +
            `• ${result.deleted.scans} scan(s)\n` +
            `• ${result.deleted.scan_subdomains} scan link(s)\n` +
            `• ${result.deleted.subdomains} orphaned subdomain(s)`
        );
        
        // Reload sidebar projects and dashboard
        loadSidebarProjects();
        loadDashboard();
        
        // If we're on the projects view, reload it
        const projectsView = document.getElementById('projectsView');
        if (projectsView && projectsView.classList.contains('active')) {
            loadProjects();
        }
        
        // If we're viewing this project, go back to dashboard
        if (currentProjectId === projectId) {
            switchView('dashboard');
            currentProjectId = null;
        }
        
    } catch (error) {
        showError('Failed to delete project: ' + error.message);
    }
}

function displayScans(scans) {
    const container = document.getElementById('scansList');
    
    if (scans.length === 0) {
        container.innerHTML = '<p class="empty-state">No scans yet. Start a scan to begin enumeration.</p>';
        return;
    }
    
    container.innerHTML = scans.map(scan => `
        <div class="scan-item" onclick="viewScanResults(${scan.id}, '${escapeHtml(scan.target_domain)}')">
            <div class="scan-info">
                <h4>${escapeHtml(scan.target_domain)}</h4>
                <div class="scan-meta">
                    <span class="status-badge status-${scan.status}">${scan.status}</span>
                    <span><i class="fas fa-sitemap"></i> ${scan.subdomain_count} subdomain(s)</span>
                    <span><i class="fas fa-clock"></i> ${formatDate(scan.started_at)}</span>
                </div>
            </div>
        </div>
    `).join('');
}

async function handleStartScan(e) {
    e.preventDefault();
    
    if (!currentProjectId) {
        showError('Please select a project first');
        return;
    }
    
    const targetDomain = document.getElementById('targetDomain').value.trim();
    
    try {
        const scan = await apiRequest(
            `${API_BASE}/projects/${currentProjectId}/scans`,
            'POST',
            { target_domain: targetDomain }
        );
        
        document.getElementById('startScanForm').reset();
        closeAllModals();
        viewScanResults(scan.id, scan.target_domain);
        showSuccess('Scan started successfully');
    } catch (error) {
        showError('Failed to start scan: ' + error.message);
    }
}

function viewScanResults(scanId, targetDomain) {
    currentScanId = scanId;
    document.getElementById('currentScanTarget').textContent = targetDomain;
    document.getElementById('scanTargetDisplay').textContent = targetDomain;
    switchView('scanResults');
    startScanStream(scanId);
    loadScanSubdomains(scanId);
    // Load scan to get project ID for back button
    loadScanProject(scanId);
}

// Scan Results Functions
function startScanStream(scanId) {
    if (eventSource) {
        eventSource.close();
    }
    if (terminalEventSource) {
        terminalEventSource.close();
    }
    
    allSubdomains = [];
    filteredSubdomains = [];
    updateSubdomainsTable([]);
    
    // Clear terminal output
    document.getElementById('terminalOutput').textContent = '';
    
    // Start scan status stream
    eventSource = new EventSource(`${API_BASE}/scans/${scanId}/stream`);
    
    eventSource.onmessage = (event) => {
        const data = JSON.parse(event.data);
        updateScanStatus(data);
    };
    
    eventSource.onerror = () => {
        loadScanStatus(scanId);
    };
    
    // Start terminal output stream
    startTerminalStream(scanId);
}

function updateScanStatus(data) {
    const statusBadge = document.getElementById('statusBadge');
    const stopBtn = document.getElementById('stopScanBtn');
    
    statusBadge.textContent = data.status;
    statusBadge.className = `status-badge status-${data.status}`;
    
    // Show/hide stop button based on status
    if (data.status === 'running' || data.status === 'pending') {
        stopBtn.style.display = 'inline-flex';
        // Reset button state in case it was stuck in "Stopping..." mode
        stopBtn.disabled = false;
        stopBtn.innerHTML = '<i class="fas fa-stop"></i> Stop Scan';
    } else {
        stopBtn.style.display = 'none';
        // Reset button state when hiding
        stopBtn.disabled = false;
        stopBtn.innerHTML = '<i class="fas fa-stop"></i> Stop Scan';
    }
    
    document.getElementById('subdomainCount').textContent = data.subdomain_count;
    
    // Update progress display
    updateProgressDisplay(data);
    
    if (data.new_subdomains && data.new_subdomains.length > 0) {
        allSubdomains.push(...data.new_subdomains);
        applyFilters();
        updateStats();
    }
    
    if (data.status === 'completed' || data.status === 'failed' || data.status === 'stopped') {
        // Don't close terminal stream immediately - let it finish receiving all messages
        // Close it after a delay to ensure all final messages are received
        if (eventSource) {
            eventSource.close();
            eventSource = null;
        }
        // Keep terminal stream open for a bit longer to catch final messages
        setTimeout(() => {
            if (terminalEventSource) {
                terminalEventSource.close();
                terminalEventSource = null;
            }
        }, 3000); // Wait 3 seconds before closing terminal stream
        loadScanSubdomains(currentScanId);
    }
}

function startTerminalStream(scanId) {
    if (terminalEventSource) {
        terminalEventSource.close();
    }
    
    const terminalOutput = document.getElementById('terminalOutput');
    const terminalSection = document.getElementById('terminalOutputSection');
    
    // Show terminal section when scan is running
    terminalSection.style.display = 'block';
    
    terminalEventSource = new EventSource(`${API_BASE}/scans/${scanId}/terminal`);
    
    terminalEventSource.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            // Append new line to terminal output
            const line = data.line || '';
            const type = data.type || 'stdout';
            
            // Color code based on type
            let colorClass = '';
            if (type === 'stderr') {
                colorClass = 'color: #ff6b6b;'; // Red for stderr
            } else {
                colorClass = 'color: #00ff00;'; // Green for stdout
            }
            
            terminalOutput.innerHTML += `<span style="${colorClass}">${escapeHtml(line)}</span>\n`;
            
            // Auto-scroll to bottom
            const container = document.getElementById('terminalOutputContainer');
            container.scrollTop = container.scrollHeight;
        } catch (error) {
            console.error('Error parsing terminal output:', error, event.data);
        }
    };
    
    terminalEventSource.onerror = (error) => {
        console.log('Terminal stream error/closed:', error);
        // Terminal stream ended - don't close immediately, let it try to reconnect
        // The stream will close naturally when scan is done
        setTimeout(() => {
            if (terminalEventSource && terminalEventSource.readyState === EventSource.CLOSED) {
                terminalEventSource.close();
                terminalEventSource = null;
            }
        }, 2000);
    };
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function setupTerminalToggle() {
    const toggleBtn = document.getElementById('toggleTerminal');
    const terminalContainer = document.getElementById('terminalOutputContainer');
    const terminalSection = document.getElementById('terminalOutputSection');
    
    if (toggleBtn) {
        toggleBtn.addEventListener('click', () => {
            terminalOutputVisible = !terminalOutputVisible;
            
            if (terminalOutputVisible) {
                terminalContainer.style.display = 'block';
                toggleBtn.innerHTML = '<i class="fas fa-chevron-down"></i> Hide';
            } else {
                terminalContainer.style.display = 'none';
                toggleBtn.innerHTML = '<i class="fas fa-chevron-up"></i> Show';
            }
        });
    }
}

function setupStopScanButton() {
    const stopBtn = document.getElementById('stopScanBtn');
    
    if (stopBtn) {
        stopBtn.addEventListener('click', async () => {
            if (!currentScanId) {
                return;
            }
            
            if (!confirm('Are you sure you want to stop this scan?')) {
                return;
            }
            
            // Disable button to prevent multiple clicks
            stopBtn.disabled = true;
            stopBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Stopping...';
            
            try {
                const response = await fetch(`${API_BASE}/scans/${currentScanId}/stop`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    }
                });
                
                const data = await response.json();
                
                if (response.ok) {
                    // Update status immediately
                    const statusBadge = document.getElementById('statusBadge');
                    statusBadge.textContent = 'stopped';
                    statusBadge.className = 'status-badge status-stopped';
                    
                    // Reset button state and hide it
                    stopBtn.disabled = false;
                    stopBtn.innerHTML = '<i class="fas fa-stop"></i> Stop Scan';
                    stopBtn.style.display = 'none';
                    
                    // Reload scan status
                    loadScanStatus(currentScanId);
                } else {
                    alert(`Failed to stop scan: ${data.error || 'Unknown error'}`);
                    stopBtn.disabled = false;
                    stopBtn.innerHTML = '<i class="fas fa-stop"></i> Stop Scan';
                }
            } catch (error) {
                console.error('Error stopping scan:', error);
                alert('Failed to stop scan. Please try again.');
                stopBtn.disabled = false;
                stopBtn.innerHTML = '<i class="fas fa-stop"></i> Stop Scan';
            }
        });
    }
}

function updateProgressDisplay(data) {
    const progressSection = document.getElementById('scanProgressSection');
    const terminalSection = document.getElementById('terminalOutputSection');
    const currentToolName = document.getElementById('currentToolName');
    const progressCount = document.getElementById('progressCount');
    const progressBar = document.getElementById('scanProgressBar');
    
    if (data.status === 'running' && data.total_tools > 0) {
        progressSection.style.display = 'block';
        if (terminalOutputVisible) {
            terminalSection.style.display = 'block';
        }
        
        // Display current tool name (formatted nicely)
        const toolNames = {
            'subfinder': 'Subfinder',
            'crtsh': 'CRT.sh',
            'sublist3r': 'Sublist3r',
            'oneforall': 'OneForAll',
            'assetfinder': 'Assetfinder',
            'censys': 'Censys',
            'securitytrails': 'SecurityTrails',
            'wayback': 'Wayback',
            'commoncrawl': 'CommonCrawl',
            'virustotal': 'VirusTotal',
            'active_enum': 'Active Enum'
        };
        
        const displayName = data.current_tool ? (toolNames[data.current_tool] || data.current_tool) : 'Starting...';
        currentToolName.textContent = displayName;
        
        // Update progress count
        progressCount.textContent = `${data.completed_tools} / ${data.total_tools} tools`;
        
        // Calculate and update progress bar
        const progressPercent = (data.completed_tools / data.total_tools) * 100;
        progressBar.style.width = `${progressPercent}%`;
        
    } else if (data.status === 'completed') {
        progressSection.style.display = 'none';
    } else if (data.status === 'failed') {
        progressSection.style.display = 'none';
    } else if (data.status === 'pending') {
        progressSection.style.display = 'none';
    }
}

async function loadScanSubdomains(scanId) {
    try {
        const subdomains = await apiRequest(`${API_BASE}/scans/${scanId}/subdomains`);
        allSubdomains = subdomains;
        applyFilters();
        updateStats();
    } catch (error) {
        showError('Failed to load subdomains: ' + error.message);
    }
}

async function loadScanStatus(scanId) {
    try {
        const scan = await apiRequest(`${API_BASE}/scans/${scanId}`);
        const subdomains = await apiRequest(`${API_BASE}/scans/${scanId}/subdomains`);
        
        // Store project ID for back button
        if (scan.project_id) {
            scanProjectId = scan.project_id;
        }
        
        const statusBadge = document.getElementById('statusBadge');
        const stopBtn = document.getElementById('stopScanBtn');
        
        statusBadge.textContent = scan.status;
        statusBadge.className = `status-badge status-${scan.status}`;
        
        // Show/hide stop button based on status
        if (scan.status === 'running' || scan.status === 'pending') {
            stopBtn.style.display = 'inline-flex';
            stopBtn.disabled = false;
            stopBtn.innerHTML = '<i class="fas fa-stop"></i> Stop Scan';
        } else {
            stopBtn.style.display = 'none';
        }
        
        document.getElementById('subdomainCount').textContent = scan.subdomain_count;
        
        // Update progress display
        updateProgressDisplay(scan);
        
        allSubdomains = subdomains;
        applyFilters();
        updateStats();
    } catch (error) {
        showError('Failed to load scan status: ' + error.message);
    }
}

async function loadScanProject(scanId) {
    try {
        const scan = await apiRequest(`${API_BASE}/scans/${scanId}`);
        if (scan.project_id) {
            scanProjectId = scan.project_id;
        }
    } catch (error) {
        console.error('Failed to load scan project:', error);
    }
}

function applyFilters() {
    const searchTerm = document.getElementById('searchFilter')?.value.toLowerCase() || '';
    const includeFilter = document.getElementById('includeFilter')?.value.toLowerCase() || '';
    const excludeFilter = document.getElementById('excludeFilter')?.value.toLowerCase() || '';
    
    filteredSubdomains = allSubdomains.filter(subdomain => {
        const searchable = [
            subdomain.subdomain
        ].join(' ').toLowerCase();
        
        if (searchTerm && !searchable.includes(searchTerm)) return false;
        if (includeFilter && !searchable.includes(includeFilter)) return false;
        if (excludeFilter && searchable.includes(excludeFilter)) return false;
        
        return true;
    });
    
    updateSubdomainsTable(filteredSubdomains);
    updateFilteredCount();
}

function clearFilters() {
    document.getElementById('searchFilter').value = '';
    document.getElementById('includeFilter').value = '';
    document.getElementById('excludeFilter').value = '';
    applyFilters();
}

function updateSubdomainsTable(subdomains) {
    const tbody = document.getElementById('subdomainsTableBody');
    
    // Get visible subdomain IDs
    const visibleIds = new Set(subdomains.map(s => s.id));
    
    // Remove selections that are no longer visible
    for (const id of selectedSubdomains) {
        if (!visibleIds.has(id)) {
            selectedSubdomains.delete(id);
        }
    }
    
    if (subdomains.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" class="empty-state">No subdomains found.</td></tr>';
        selectedSubdomains.clear();
        updateBulkActionsUI('results');
        return;
    }
    
    tbody.innerHTML = subdomains.map(subdomain => `
        <tr data-subdomain-id="${subdomain.id}">
            <td class="checkbox-cell">
                <input type="checkbox" 
                       data-subdomain-id="${subdomain.id}" 
                       onchange="toggleSubdomainSelection(${subdomain.id}, this.checked, 'results')"
                       ${selectedSubdomains.has(subdomain.id) ? 'checked' : ''}>
            </td>
            <td><span class="subdomain-name">${escapeHtml(subdomain.subdomain || '-')}</span></td>
            <td>${renderStatusBadge(subdomain.is_online, subdomain.probe_http_status, subdomain.probe_https_status)}</td>
            <!-- Debug: ${JSON.stringify({is_online: subdomain.is_online, http: subdomain.probe_http_status, https: subdomain.probe_https_status})} -->
            <td>${escapeHtml(subdomain.canonical_names || '-')}</td>
            <td>${formatSize(subdomain.size)}</td>
            <td>${subdomain.is_virtual_host === 'true' ? 'Yes' : 'No'}</td>
            <td>${subdomain.tool_name ? `<span class="tool-name-badge">${escapeHtml(subdomain.tool_name)}</span>` : '-'}</td>
            <td><a href="${escapeHtml(subdomain.uri || 'https://' + subdomain.subdomain)}" target="_blank" class="subdomain-uri">View</a></td>
            <td>
                <button class="btn-icon btn-probe" onclick="probeSubdomain(${subdomain.id}, 'results')" title="Probe subdomain">
                    <i class="fas fa-satellite-dish"></i>
                </button>
                <button class="btn-icon btn-delete" onclick="deleteSubdomain(${subdomain.id}, event)" title="Delete subdomain">
                    <i class="fas fa-trash"></i>
                </button>
            </td>
        </tr>
    `).join('');
    
    updateBulkActionsUI('results');
}

function updateFilteredCount() {
    document.getElementById('filteredCount').textContent = `Showing ${filteredSubdomains.length} of ${allSubdomains.length}`;
}

function updateStats() {
    const withIp = allSubdomains.filter(s => s.ip_address).length;
    document.getElementById('withIpCount').textContent = withIp;
}


// All Subdomains Functions
async function loadAllSubdomains(page = 1, search = '') {
    try {
        const limit = allSubdomainsPagination.limit || 100;
        const searchParam = search ? `&search=${encodeURIComponent(search)}` : '';
        const projectFilter = document.getElementById('allProjectFilter')?.value || '';
        const targetFilter = document.getElementById('allTargetFilter')?.value || '';
        const statusFilter = document.getElementById('allStatusFilter')?.value || '';
        const protocolFilter = document.getElementById('allProtocolFilter')?.value || '';
        const responseCodeFilter = document.getElementById('allResponseCodeFilter')?.value || '';
        
        let url = `${API_BASE}/subdomains/all?page=${page}&limit=${limit}${searchParam}`;
        if (projectFilter) url += `&project=${encodeURIComponent(projectFilter)}`;
        if (targetFilter) url += `&target=${encodeURIComponent(targetFilter)}`;
        if (statusFilter) url += `&status=${encodeURIComponent(statusFilter)}`;
        if (protocolFilter) url += `&protocol=${encodeURIComponent(protocolFilter)}`;
        if (responseCodeFilter) url += `&response_code=${encodeURIComponent(responseCodeFilter)}`;
        
        const response = await apiRequest(url);
        const projects = await apiRequest(`${API_BASE}/projects`);
        
        // Store data and pagination info
        allSubdomainsData = response.subdomains || [];
        allSubdomainsPagination = response.pagination || { page: 1, limit: 100, total: 0, pages: 0 };
        
        updateProjectFilter(projects);
        displayAllSubdomains(allSubdomainsData);
        updateAllSubdomainsPagination();
        
        document.getElementById('allSubdomainsCount').textContent = 
            `Showing ${allSubdomainsData.length} of ${allSubdomainsPagination.total}`;
    } catch (error) {
        showError('Failed to load subdomains: ' + error.message);
    }
}

function dedupeSubdomainsByName(subdomains) {
    const byName = new Map();
    for (const s of subdomains || []) {
        const name = (s.subdomain || '').toLowerCase().trim();
        if (!name) continue;
        const existing = byName.get(name);
        if (!existing) {
            byName.set(name, s);
            continue;
        }
        // Keep the most recently discovered row for display
        const existingTs = Date.parse(existing.discovered_at || '') || 0;
        const ts = Date.parse(s.discovered_at || '') || 0;
        if (ts >= existingTs) {
            byName.set(name, s);
        }
    }
    return [...byName.values()].sort((a, b) => (Date.parse(b.discovered_at || '') || 0) - (Date.parse(a.discovered_at || '') || 0));
}

function updateProjectFilter(projects) {
    const select = document.getElementById('allProjectFilter');
    select.innerHTML = '<option value="">All Projects</option>';
    
    projects.forEach(project => {
        const option = document.createElement('option');
        option.value = project.id;
        option.textContent = project.name;
        select.appendChild(option);
    });
}


function applyAllSubdomainsFilters() {
    // Debounce search to avoid too many API calls
    if (currentSearchTimeout) {
        clearTimeout(currentSearchTimeout);
    }
    
    currentSearchTimeout = setTimeout(() => {
        const searchTerm = document.getElementById('allSubdomainsSearch').value;
        loadAllSubdomains(1, searchTerm);
    }, 300);
}

function clearAllSubdomainsFilters() {
    document.getElementById('allSubdomainsSearch').value = '';
    document.getElementById('allProjectFilter').value = '';
    document.getElementById('allTargetFilter').value = '';
    document.getElementById('allStatusFilter').value = '';
    document.getElementById('allProtocolFilter').value = '';
    document.getElementById('allResponseCodeFilter').value = '';
    loadAllSubdomains(1, '');
}

function updateAllSubdomainsPagination() {
    const container = document.getElementById('allSubdomainsPagination');
    if (!container) return;
    
    const { page, pages, total } = allSubdomainsPagination;
    
    if (pages <= 1) {
        container.innerHTML = '';
        return;
    }
    
    let html = '<div class="pagination">';
    
    // Previous button
    html += `<button class="pagination-btn" ${page <= 1 ? 'disabled' : ''} onclick="changeAllSubdomainsPage(${page - 1})">
        <i class="fas fa-chevron-left"></i>
    </button>`;
    
    // Page numbers
    const startPage = Math.max(1, page - 2);
    const endPage = Math.min(pages, page + 2);
    
    if (startPage > 1) {
        html += `<button class="pagination-btn" onclick="changeAllSubdomainsPage(1)">1</button>`;
        if (startPage > 2) html += '<span class="pagination-ellipsis">...</span>';
    }
    
    for (let i = startPage; i <= endPage; i++) {
        html += `<button class="pagination-btn ${i === page ? 'active' : ''}" onclick="changeAllSubdomainsPage(${i})">${i}</button>`;
    }
    
    if (endPage < pages) {
        if (endPage < pages - 1) html += '<span class="pagination-ellipsis">...</span>';
        html += `<button class="pagination-btn" onclick="changeAllSubdomainsPage(${pages})">${pages}</button>`;
    }
    
    // Next button
    html += `<button class="pagination-btn" ${page >= pages ? 'disabled' : ''} onclick="changeAllSubdomainsPage(${page + 1})">
        <i class="fas fa-chevron-right"></i>
    </button>`;
    
    html += '</div>';
    container.innerHTML = html;
}

function changeAllSubdomainsPage(page) {
    const searchTerm = document.getElementById('allSubdomainsSearch').value;
    loadAllSubdomains(page, searchTerm);
    // Filters are already applied in loadAllSubdomains function
}

function displayAllSubdomains(subdomains) {
    const tbody = document.getElementById('allSubdomainsTableBody');
    
    // Get visible subdomain IDs
    const visibleIds = new Set(subdomains.map(s => s.id));
    
    // Remove selections that are no longer visible
    for (const id of selectedAllSubdomains) {
        if (!visibleIds.has(id)) {
            selectedAllSubdomains.delete(id);
        }
    }
    
    if (subdomains.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" class="empty-state">No subdomains found</td></tr>';
        selectedAllSubdomains.clear();
        updateBulkActionsUI('all');
        return;
    }
    
    tbody.innerHTML = subdomains.map(subdomain => `
        <tr data-subdomain-id="${subdomain.id}">
            <td class="checkbox-cell">
                <input type="checkbox" 
                       data-subdomain-id="${subdomain.id}" 
                       onchange="toggleSubdomainSelection(${subdomain.id}, this.checked, 'all')"
                       ${selectedAllSubdomains.has(subdomain.id) ? 'checked' : ''}>
            </td>
            <td><span class="subdomain-name">${escapeHtml(subdomain.subdomain)}</span></td>
            <td>${escapeHtml(subdomain.project_name)}</td>
            <td>${escapeHtml(subdomain.target_domain)}</td>
            <td>${renderStatusBadge(subdomain.is_online, subdomain.probe_http_status, subdomain.probe_https_status)}</td>
            <!-- Debug: ${JSON.stringify({is_online: subdomain.is_online, http: subdomain.probe_http_status, https: subdomain.probe_https_status})} -->
            <td>${formatDate(subdomain.discovered_at)}</td>
            <td>${subdomain.tool_name ? `<span class="tool-name-badge">${escapeHtml(subdomain.tool_name)}</span>` : '-'}</td>
            <td><a href="${escapeHtml(subdomain.uri || 'https://' + subdomain.subdomain)}" target="_blank" class="subdomain-uri">View</a></td>
            <td>
                <button class="btn-icon btn-probe" onclick="probeSubdomain(${subdomain.id}, 'all')" title="Probe subdomain">
                    <i class="fas fa-satellite-dish"></i>
                </button>
                <button class="btn-icon btn-delete" onclick="deleteSubdomainFromAll(${subdomain.id}, event)" title="Delete subdomain">
                    <i class="fas fa-trash"></i>
                </button>
            </td>
        </tr>
    `).join('');
    
    updateBulkActionsUI('all');
}

// Utility Functions
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatDate(dateString) {
    if (!dateString) return 'N/A';
    const date = new Date(dateString);
    return date.toLocaleString();
}

function formatSize(bytes) {
    if (!bytes) return '-';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

function renderStatusBadge(isOnline, httpStatus, httpsStatus) {
    // Handle null/undefined values
    if (!isOnline || isOnline === 'pending') {
        return '<div class="status-badges-container"><div class="status-badge-row"><span class="status-badge status-pending">Pending</span></div></div>';
    }
    
    // Convert to numbers if they're strings
    const httpCode = httpStatus != null ? parseInt(httpStatus) : null;
    const httpsCode = httpsStatus != null ? parseInt(httpsStatus) : null;
    
    // Determine status badge
    let statusBadge = '';
    if (isOnline === 'online_both' || isOnline === 'online_http' || isOnline === 'online_https') {
        statusBadge = '<span class="status-badge status-online-both">Online</span>';
    } else if (isOnline === 'dns_only') {
        statusBadge = '<span class="status-badge status-dns-only">DNS Only</span>';
    } else if (isOnline === 'offline') {
        statusBadge = '<span class="status-badge status-offline">Offline</span>';
    } else {
        statusBadge = '<span class="status-badge status-pending">Unknown</span>';
    }
    
    // Build protocol and response code badges
    const protocolBadges = [];
    const codeBadges = [];
    
    const hasHttp = httpCode !== null && httpCode !== undefined && !isNaN(httpCode) && httpCode !== 0;
    const hasHttps = httpsCode !== null && httpsCode !== undefined && !isNaN(httpsCode) && httpsCode !== 0;
    
    // HTTP protocol badge (if HTTP responded, even if 418)
    if (hasHttp) {
        protocolBadges.push('<span class="status-badge status-protocol-http">HTTP</span>');
    }
    
    // HTTPS protocol badge (if HTTPS responded, even if 418)
    if (hasHttps) {
        protocolBadges.push('<span class="status-badge status-protocol-https">HTTPS</span>');
    }
    
    // Response codes - if both are the same, show only once
    if (hasHttp && hasHttps && httpCode === httpsCode) {
        codeBadges.push(`<span class="status-badge status-code">${escapeHtml(httpCode.toString())}</span>`);
    } else {
        if (hasHttp) {
            codeBadges.push(`<span class="status-badge status-code">${escapeHtml(httpCode.toString())}</span>`);
        }
        if (hasHttps) {
            codeBadges.push(`<span class="status-badge status-code">${escapeHtml(httpsCode.toString())}</span>`);
        }
    }
    
    // Build container: status on first line, protocols and codes on second line
    const secondLineBadges = [...protocolBadges, ...codeBadges];
    const secondLine = secondLineBadges.length > 0 
        ? `<div class="status-badge-row">${secondLineBadges.join(' ')}</div>` 
        : '';
    
    return `<div class="status-badges-container">
        <div class="status-badge-row">${statusBadge}</div>
        ${secondLine}
    </div>`;
}

function showToast(message, type = 'info') {
    // Create toast container if it doesn't exist
    let container = document.getElementById('toastContainer');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toastContainer';
        container.className = 'toast-container';
        document.body.appendChild(container);
    }
    
    // Create toast element
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    
    // Icon based on type
    const icons = {
        success: 'fa-check-circle',
        error: 'fa-exclamation-circle',
        info: 'fa-info-circle',
        warning: 'fa-exclamation-triangle'
    };
    
    toast.innerHTML = `
        <div class="toast-icon">
            <i class="fas ${icons[type] || icons.info}"></i>
        </div>
        <div class="toast-content">
            <span class="toast-message">${escapeHtml(message)}</span>
        </div>
        <button class="toast-close" onclick="this.parentElement.remove()">
            <i class="fas fa-times"></i>
        </button>
    `;
    
    // Add to container
    container.appendChild(toast);
    
    // Trigger animation
    requestAnimationFrame(() => {
        toast.classList.add('toast-show');
    });
    
    // Auto-dismiss after 10 seconds
    setTimeout(() => {
        toast.classList.remove('toast-show');
        toast.classList.add('toast-hide');
        setTimeout(() => toast.remove(), 300);
    }, 10000);
}

function showError(message) {
    showToast(message, 'error');
    console.error(message);
}

function showSuccess(message) {
    showToast(message, 'success');
    console.log('Success: ' + message);
}

// Settings Functions - Config-driven approach
let toolsConfig = null;
let toolTemplates = null;
let fullYamlContent = '';
let yamlModified = false;

async function loadSettings() {
    try {
        // Load tools config, API keys, and templates in parallel
        const [configData, apiKeys, templates] = await Promise.all([
            apiRequest(`${API_BASE}/tools/config`),
            apiRequest(`${API_BASE}/tools/api-keys`),
            apiRequest(`${API_BASE}/tools/templates`)
        ]);
        
        toolsConfig = configData.config;
        toolTemplates = templates;
        fullYamlContent = configData.yaml;
        
        // Display everything
        displayToolsTableFromConfig(toolsConfig);
        displayApiKeys(apiKeys);
        displayFullYaml(fullYamlContent);
        loadWordlists();
        loadInputFiles();
        setupSettingsEventListeners();
        
    } catch (error) {
        showError('Failed to load settings: ' + error.message);
    }
}

function displayToolsTableFromConfig(config) {
    const individualTbody = document.getElementById('individualToolsTableBody');
    const pipelinesTbody = document.getElementById('pipelinesTableBody');
    const tools = config?.tools || {};
    const toolNames = Object.keys(tools).filter(name => name !== 'templates');
    
    // Split tools into individual tools and pipelines
    const individualTools = [];
    const pipelines = [];
    
    toolNames.forEach(name => {
        const tool = tools[name];
        // Pipelines: tools with type === 'pipeline'
        if (tool.type === 'pipeline') {
            pipelines.push({ name, ...tool });
        } else {
            // All other tools (CLI, API) are individual tools
            individualTools.push({ name, ...tool });
        }
    });
    
    // Render individual tools
    if (individualTools.length === 0) {
        individualTbody.innerHTML = '<tr><td colspan="4" class="empty-state">No individual tools configured</td></tr>';
    } else {
        individualTbody.innerHTML = individualTools.map(tool => renderToolRow(tool)).join('');
    }
    
    // Render pipelines
    if (pipelines.length === 0) {
        pipelinesTbody.innerHTML = '<tr><td colspan="4" class="empty-state">No pipelines configured</td></tr>';
    } else {
        pipelinesTbody.innerHTML = pipelines.map(tool => renderToolRow(tool)).join('');
    }
}

function renderToolRow(tool) {
    const name = tool.name;
    return `
        <tr data-tool-name="${name}">
            <td>
                <div class="tool-name-cell">
                    <span class="tool-name">${escapeHtml(name)}</span>
                    <span class="tool-description">${escapeHtml(tool.description || '')}</span>
                </div>
            </td>
            <td>
                <span class="tool-type-badge ${tool.type || 'cli'}">
                    <i class="fas fa-${tool.type === 'cli' ? 'terminal' : tool.type === 'api' ? 'cloud' : 'stream'}"></i>
                    ${(tool.type || 'cli').toUpperCase()}
                </span>
            </td>
            <td>
                <div class="tool-status">
                    <span class="status-dot ${tool.enabled ? 'enabled' : 'disabled'}"></span>
                    <span>${tool.enabled ? 'Enabled' : 'Disabled'}</span>
                </div>
            </td>
            <td>
                <div class="tool-actions">
                    <button class="btn btn-small ${tool.enabled ? 'btn-secondary' : 'btn-primary'}" 
                            onclick="toggleToolInYaml('${name}')">
                        <i class="fas fa-${tool.enabled ? 'pause' : 'play'}"></i>
                        ${tool.enabled ? 'Disable' : 'Enable'}
                    </button>
                    <button class="btn btn-small btn-secondary" onclick="editTool('${name}')">
                        <i class="fas fa-edit"></i> Edit
                    </button>
                </div>
            </td>
        </tr>
    `;
}

function displayFullYaml(yaml) {
    const editor = document.getElementById('fullYamlEditor');
    if (editor) {
        editor.value = yaml;
        fullYamlContent = yaml;
        yamlModified = false;
        updateYamlSyncStatus('synced', 'Saved');
    }
}

function updateYamlSyncStatus(status, text) {
    const statusEl = document.getElementById('yamlSyncStatus');
    if (statusEl) {
        statusEl.className = `sync-status ${status}`;
        const icon = status === 'synced' ? 'check-circle' : status === 'modified' ? 'circle' : 'exclamation-circle';
        statusEl.innerHTML = `<i class="fas fa-${icon}"></i> ${text}`;
    }
}

function displayApiKeys(apiKeys) {
    const container = document.getElementById('apiKeysContainer');
    
    if (!apiKeys || apiKeys.length === 0) {
        container.innerHTML = '<p class="empty-state">No API-based tools configured</p>';
        return;
    }
    
    container.innerHTML = apiKeys.map(key => `
        <div class="api-key-row" data-setting-key="${key.setting_key}">
            <span class="api-key-tool">${escapeHtml(key.tool)}</span>
            <div class="api-key-input-group">
                <input type="password" 
                       id="api_key_${key.setting_key}" 
                       placeholder="${key.has_key ? '••••••••' : 'Enter API key'}"
                       value="">
                <button class="btn btn-small btn-primary" onclick="saveApiKey('${key.setting_key}')">
                    <i class="fas fa-save"></i> Save
                </button>
            </div>
            <span class="api-key-status ${key.has_key ? 'configured' : 'missing'}">
                <i class="fas fa-${key.has_key ? 'check-circle' : 'exclamation-circle'}"></i>
                ${key.has_key ? 'Configured' : 'Not set'}
            </span>
        </div>
    `).join('');
}

// Store handler functions to allow removal
let settingsEventHandlers = {
    addNewIndividualTool: null,
    addNewPipelineTool: null,
    addToolForm: null,
    toolEditorForm: null,
    toolEditorDelete: null
};

function setupSettingsEventListeners() {
    // Wordlist management
    document.getElementById('addWordlist')?.addEventListener('click', () => {
        document.getElementById('wordlistEditName').value = '';
        document.getElementById('wordlistName').value = '';
        document.getElementById('wordlistPath').value = '';
        document.getElementById('wordlistName').disabled = false;
        document.getElementById('wordlistModalTitle').textContent = 'Add Wordlist';
        openModal('wordlistModal');
    });
    
    document.getElementById('wordlistForm')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const editName = document.getElementById('wordlistEditName').value;
        const name = document.getElementById('wordlistName').value.trim().toLowerCase();
        const path = document.getElementById('wordlistPath').value.trim();
        
        try {
            if (editName) {
                // Update existing
                await apiRequest(`${API_BASE}/wordlists/${editName}`, 'PUT', { path });
                showSuccess(`Wordlist "${name}" updated successfully`);
            } else {
                // Create new
                await apiRequest(`${API_BASE}/wordlists`, 'POST', { name, path });
                showSuccess(`Wordlist "${name}" created successfully`);
            }
            closeModal('wordlistModal');
            loadWordlists();
        } catch (error) {
            showError('Failed to save wordlist: ' + error.message);
        }
    });
    
    // Input file management
    document.getElementById('addInputFile')?.addEventListener('click', () => {
        document.getElementById('inputFileEditName').value = '';
        document.getElementById('inputFileName').value = '';
        document.getElementById('inputFilePath').value = '';
        document.getElementById('inputFileName').disabled = false;
        document.getElementById('inputFileModalTitle').textContent = 'Add Input File';
        openModal('inputFileModal');
    });
    
    document.getElementById('inputFileForm')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const editName = document.getElementById('inputFileEditName').value;
        const name = document.getElementById('inputFileName').value.trim().toLowerCase();
        const path = document.getElementById('inputFilePath').value.trim();
        
        try {
            if (editName) {
                // Update existing
                await apiRequest(`${API_BASE}/input-files/${editName}`, 'PUT', { path });
                showSuccess(`Input file "${name}" updated successfully`);
            } else {
                // Create new
                await apiRequest(`${API_BASE}/input-files`, 'POST', { name, path });
                showSuccess(`Input file "${name}" created successfully`);
            }
            closeModal('inputFileModal');
            loadInputFiles();
        } catch (error) {
            showError('Failed to save input file: ' + error.message);
        }
    });
    
    // Remove existing listeners if they exist
    const addNewIndividualToolBtn = document.getElementById('addNewIndividualTool');
    const addNewPipelineToolBtn = document.getElementById('addNewPipelineTool');
    const addToolForm = document.getElementById('addToolForm');
    const toolEditorForm = document.getElementById('toolEditorForm');
    const toolEditorDeleteBtn = document.getElementById('toolEditorDelete');
    
    if (addNewIndividualToolBtn && settingsEventHandlers.addNewIndividualTool) {
        addNewIndividualToolBtn.removeEventListener('click', settingsEventHandlers.addNewIndividualTool);
    }
    if (addNewPipelineToolBtn && settingsEventHandlers.addNewPipelineTool) {
        addNewPipelineToolBtn.removeEventListener('click', settingsEventHandlers.addNewPipelineTool);
    }
    if (addToolForm && settingsEventHandlers.addToolForm) {
        addToolForm.removeEventListener('submit', settingsEventHandlers.addToolForm);
    }
    if (toolEditorForm && settingsEventHandlers.toolEditorForm) {
        toolEditorForm.removeEventListener('submit', settingsEventHandlers.toolEditorForm);
    }
    if (toolEditorDeleteBtn && settingsEventHandlers.toolEditorDelete) {
        toolEditorDeleteBtn.removeEventListener('click', settingsEventHandlers.toolEditorDelete);
    }
    
    // Create new handlers
    settingsEventHandlers.addNewIndividualTool = () => {
        // Set default type to cli for individual tools
        document.getElementById('newToolType').value = 'cli';
        openModal('addToolModal');
    };
    
    settingsEventHandlers.addNewPipelineTool = () => {
        // Set type to pipeline
        document.getElementById('newToolType').value = 'pipeline';
        openModal('addToolModal');
    };
    
    settingsEventHandlers.addToolForm = async (e) => {
        e.preventDefault();
        const name = document.getElementById('newToolName').value.trim().toLowerCase();
        const type = document.getElementById('newToolType').value;
        
        if (!name || !toolTemplates[type]) {
            showError('Invalid tool name or type');
            return;
        }
        
        try {
            const template = JSON.parse(JSON.stringify(toolTemplates[type]));
            template.description = `New ${type} tool`;
            
            // For pipeline tools, set run_after to 'passive' so they run after individual tools
            if (type === 'pipeline') {
                template.run_after = 'passive';
            }
            
            await apiRequest(`${API_BASE}/tools/${name}`, 'PUT', { config: template });
            showSuccess(`Tool ${name} created successfully`);
            closeModal('addToolModal');
            loadSettings();
            
            setTimeout(() => editTool(name), 500);
        } catch (error) {
            showError('Failed to create tool: ' + error.message);
        }
    };
    
    settingsEventHandlers.toolEditorForm = async (e) => {
        e.preventDefault();
        const name = document.getElementById('toolEditorName').value;
        const yaml = document.getElementById('toolEditorYaml').value;
        
        try {
            await apiRequest(`${API_BASE}/tools/${name}`, 'PUT', { yaml });
            closeModal('toolEditorModal');
            showSuccess(`Tool ${name} saved successfully`);
            loadSettings();
        } catch (error) {
            showError('Failed to save tool: ' + error.message);
        }
    };
    
    settingsEventHandlers.toolEditorDelete = async () => {
        const name = document.getElementById('toolEditorName').value;
        
        if (!confirm(`Are you sure you want to delete the tool "${name}"?`)) {
            return;
        }
        
        try {
            await apiRequest(`${API_BASE}/tools/${name}`, 'DELETE');
            closeModal('toolEditorModal');
            showSuccess(`Tool ${name} deleted`);
            loadSettings();
        } catch (error) {
            showError('Failed to delete tool: ' + error.message);
        }
    };
    
    // Add new listeners
    addNewIndividualToolBtn?.addEventListener('click', settingsEventHandlers.addNewIndividualTool);
    addNewPipelineToolBtn?.addEventListener('click', settingsEventHandlers.addNewPipelineTool);
    addToolForm?.addEventListener('submit', settingsEventHandlers.addToolForm);
    toolEditorForm?.addEventListener('submit', settingsEventHandlers.toolEditorForm);
    toolEditorDeleteBtn?.addEventListener('click', settingsEventHandlers.toolEditorDelete);
    
    // Full YAML editor - detect changes
    const fullYamlEditor = document.getElementById('fullYamlEditor');
    if (fullYamlEditor) {
        fullYamlEditor.addEventListener('input', () => {
            yamlModified = fullYamlEditor.value !== fullYamlContent;
            if (yamlModified) {
                updateYamlSyncStatus('modified', 'Unsaved changes');
            } else {
                updateYamlSyncStatus('synced', 'Saved');
            }
        });
    }
    
    // Save full YAML button
    document.getElementById('saveFullYaml')?.addEventListener('click', saveFullYaml);
}

async function toggleToolInYaml(toolName) {
    try {
        const result = await apiRequest(`${API_BASE}/tools/${toolName}/toggle`, 'POST');
        showSuccess(result.message);
        loadSettings(); // Refresh both table and full YAML
    } catch (error) {
        showError('Failed to toggle tool: ' + error.message);
    }
}

async function editTool(toolName) {
    try {
        const data = await apiRequest(`${API_BASE}/tools/${toolName}`);
        
        document.getElementById('toolEditorTitle').textContent = `Edit Tool: ${toolName}`;
        document.getElementById('toolEditorName').value = toolName;
        document.getElementById('toolEditorYaml').value = data.yaml;
        
        openModal('toolEditorModal');
    } catch (error) {
        showError('Failed to load tool config: ' + error.message);
    }
}

async function saveApiKey(settingKey) {
    const input = document.getElementById(`api_key_${settingKey}`);
    const value = input.value.trim();
    
    if (!value) {
        showError('Please enter an API key');
        return;
    }
    
    try {
        await apiRequest(`${API_BASE}/tools/api-keys/${settingKey}`, 'PUT', { value });
        showSuccess('API key saved successfully');
        input.value = '';
        loadSettings(); // Refresh to show updated status
    } catch (error) {
        showError('Failed to save API key: ' + error.message);
    }
}

async function saveFullYaml() {
    const editor = document.getElementById('fullYamlEditor');
    const yaml = editor.value;
    
    try {
        updateYamlSyncStatus('modified', 'Saving...');
        await apiRequest(`${API_BASE}/tools/config`, 'PUT', { yaml });
        showSuccess('Configuration saved successfully');
        loadSettings(); // Refresh everything to ensure sync
    } catch (error) {
        updateYamlSyncStatus('error', 'Save failed');
        showError('Failed to save configuration: ' + error.message);
    }
}

async function clearDatabase() {
    // Show confirmation dialog
    const confirmed = confirm(
        '⚠️ WARNING: This will permanently delete ALL data!\n\n' +
        'This includes:\n' +
        '• All projects\n' +
        '• All scans\n' +
        '• All subdomains\n\n' +
        'This action CANNOT be undone.\n\n' +
        'Are you absolutely sure you want to continue?'
    );
    
    if (!confirmed) {
        return;
    }
    
    // Second confirmation
    const doubleConfirm = confirm(
        'This is your last chance!\n\n' +
        'Type YES in the next prompt to confirm deletion.'
    );
    
    if (!doubleConfirm) {
        return;
    }
    
    const finalConfirm = prompt('Type YES (in capital letters) to confirm:');
    
    if (finalConfirm !== 'YES') {
        alert('Database clear cancelled.');
        return;
    }
    
    try {
        const result = await apiRequest(`${API_BASE}/database/clear`, 'POST');
        
        alert(
            `Database cleared successfully!\n\n` +
            `Deleted:\n` +
            `• ${result.deleted.projects} project(s)\n` +
            `• ${result.deleted.scans} scan(s)\n` +
            `• ${result.deleted.subdomains} subdomain(s)\n` +
            `• ${result.deleted.scan_subdomains} scan link(s)`
        );
        
        // Reload sidebar projects and dashboard
        loadSidebarProjects();
        switchView('dashboard');
        
    } catch (error) {
        showError('Failed to clear database: ' + error.message);
    }
}

// Probe Subdomain Functions
async function probeSubdomain(subdomainId, context = 'all') {
    try {
        const result = await apiRequest(`${API_BASE}/subdomains/${subdomainId}/probe`, 'POST');
        
        // Update the status in the displayed row
        const row = document.querySelector(`tr[data-subdomain-id="${subdomainId}"]`);
        if (row) {
            const statusCell = row.querySelector('td:nth-child(4)') || row.querySelector('td:nth-child(5)');
            if (statusCell) {
                statusCell.innerHTML = renderStatusBadge(result.result.status, result.result.http_status_code, result.result.https_status_code);
            }
        }
        
        // Update in-memory data if available
        if (context === 'results' && allSubdomains) {
            const subdomain = allSubdomains.find(s => s.id === subdomainId);
            if (subdomain) {
                subdomain.is_online = result.result.status;
            }
        }
        
        showSuccess('Subdomain probed successfully');
    } catch (error) {
        showError('Failed to probe subdomain: ' + error.message);
    }
}

async function bulkProbeSubdomains(context) {
    let selectedIds = [];
    
    if (context === 'all') {
        selectedIds = Array.from(selectedAllSubdomains);
    } else if (context === 'project') {
        selectedIds = Array.from(selectedProjectSubdomains);
    } else if (context === 'target') {
        selectedIds = Array.from(selectedTargetSubdomains);
    } else if (context === 'results') {
        selectedIds = Array.from(selectedSubdomains);
    }
    
    if (selectedIds.length === 0) {
        showError('Please select at least one subdomain to probe');
        return;
    }
    
    if (!confirm(`Probe ${selectedIds.length} selected subdomain(s)?`)) {
        return;
    }
    
    try {
        const result = await apiRequest(`${API_BASE}/subdomains/probe`, 'POST', {
            subdomain_ids: selectedIds
        });
        
        if (result.job_id) {
            // Show progress bar and start polling
            showProbeProgress(context, result.job_id, result.subdomain_count);
        } else {
            showSuccess(`Probed ${result.subdomain_count} subdomain(s) successfully`);
            // Reload the current view to show updated statuses
            reloadCurrentView(context);
        }
    } catch (error) {
        showError('Failed to probe subdomains: ' + error.message);
    }
}

function showProbeProgress(context, jobId, total) {
    const progressContainer = document.getElementById(`probeProgress${context.charAt(0).toUpperCase() + context.slice(1)}`);
    const progressBar = document.getElementById(`probeProgressBar${context.charAt(0).toUpperCase() + context.slice(1)}`);
    const progressCount = document.getElementById(`probeProgressCount${context.charAt(0).toUpperCase() + context.slice(1)}`);
    
    if (!progressContainer || !progressBar || !progressCount) {
        return;
    }
    
    // Show progress bar
    progressContainer.style.display = 'block';
    
    // Poll for progress updates
    const pollInterval = setInterval(async () => {
        try {
            const progress = await apiRequest(`${API_BASE}/probe/progress/${jobId}`);
            
            // Update progress bar
            const percent = progress.progress_percent || 0;
            progressBar.style.width = `${percent}%`;
            progressCount.textContent = `${progress.completed} / ${progress.total}`;
            
            // Check if completed
            if (progress.status === 'completed') {
                clearInterval(pollInterval);
                progressContainer.style.display = 'none';
                showSuccess(`Probed ${progress.total} subdomain(s) successfully`);
                reloadCurrentView(context);
            } else if (progress.status === 'failed') {
                clearInterval(pollInterval);
                progressContainer.style.display = 'none';
                showError('Probing failed');
            }
        } catch (error) {
            // If job not found, assume it's done
            clearInterval(pollInterval);
            progressContainer.style.display = 'none';
            reloadCurrentView(context);
        }
    }, 500); // Poll every 500ms
}

function reloadCurrentView(context) {
    if (context === 'all') {
        loadAllSubdomains();
    } else if (context === 'project' && currentProjectId) {
        loadProjectData(currentProjectId);
    } else if (context === 'target' && currentTargetDomain) {
        loadTargetSubdomains(currentTargetDomain);
    } else if (context === 'results' && currentScanId) {
        loadScanResults(currentScanId);
    }
}

// Delete Subdomain Functions
async function deleteSubdomain(subdomainId, event) {
    event.stopPropagation();
    
    if (!confirm('Are you sure you want to delete this subdomain?')) {
        return;
    }
    
    try {
        const result = await apiRequest(`${API_BASE}/subdomains/${subdomainId}`, 'DELETE');
        
        // Remove the row from the table
        const row = document.querySelector(`tr[data-subdomain-id="${subdomainId}"]`);
        if (row) {
            row.remove();
        }
        
        // Update the subdomain count
        allSubdomains = allSubdomains.filter(s => s.id !== subdomainId);
        filteredSubdomains = filteredSubdomains.filter(s => s.id !== subdomainId);
        
        updateFilteredCount();
        updateStats();
        
        // Update the main subdomain count display
        document.getElementById('subdomainCount').textContent = allSubdomains.length;
        
        showSuccess('Subdomain deleted successfully');
    } catch (error) {
        showError('Failed to delete subdomain: ' + error.message);
    }
}

async function deleteSubdomainFromAll(subdomainId, event) {
    event.stopPropagation();
    
    if (!confirm('Are you sure you want to delete this subdomain?')) {
        return;
    }
    
    try {
        await apiRequest(`${API_BASE}/subdomains/${subdomainId}`, 'DELETE');
        
        // Remove from selection
        selectedAllSubdomains.delete(subdomainId);
        
        // Remove the row from the table
        const row = document.querySelector(`tr[data-subdomain-id="${subdomainId}"]`);
        if (row) {
            row.remove();
        }
        
        // Reload all subdomains to get updated counts
        loadAllSubdomains();
        loadDashboard(); // Refresh dashboard stats
        
        showSuccess('Subdomain deleted successfully');
    } catch (error) {
        showError('Failed to delete subdomain: ' + error.message);
    }
}

// Bulk Selection and Deletion Functions
function toggleSubdomainSelection(subdomainId, checked, view) {
    if (view === 'results') {
        if (checked) {
            selectedSubdomains.add(subdomainId);
        } else {
            selectedSubdomains.delete(subdomainId);
        }
    } else if (view === 'all') {
        if (checked) {
            selectedAllSubdomains.add(subdomainId);
        } else {
            selectedAllSubdomains.delete(subdomainId);
        }
    } else if (view === 'project') {
        if (checked) {
            selectedProjectSubdomains.add(subdomainId);
        } else {
            selectedProjectSubdomains.delete(subdomainId);
        }
    } else if (view === 'target') {
        if (checked) {
            selectedTargetSubdomains.add(subdomainId);
        } else {
            selectedTargetSubdomains.delete(subdomainId);
        }
    }
    updateBulkActionsUI(view);
}

function updateBulkActionsUI(view) {
    if (view === 'results') {
        const count = selectedSubdomains.size;
        const bulkActions = document.getElementById('bulkActionsResults');
        const selectedCount = document.getElementById('selectedCountResults');
        const selectAllCheckbox = document.getElementById('selectAllResults');
        
        if (count > 0) {
            bulkActions.style.display = 'flex';
            selectedCount.textContent = `${count} selected`;
        } else {
            bulkActions.style.display = 'none';
        }
        
        // Update select all checkbox state
        const totalCheckboxes = document.querySelectorAll('#subdomainsTableBody input[type="checkbox"]').length;
        if (selectAllCheckbox) {
            selectAllCheckbox.checked = count > 0 && count === totalCheckboxes;
            selectAllCheckbox.indeterminate = count > 0 && count < totalCheckboxes;
        }
    } else if (view === 'all') {
        const count = selectedAllSubdomains.size;
        const bulkActions = document.getElementById('bulkActionsAll');
        const selectedCount = document.getElementById('selectedCountAll');
        const selectAllCheckbox = document.getElementById('selectAllSubdomains');
        
        if (count > 0) {
            bulkActions.style.display = 'flex';
            selectedCount.textContent = `${count} selected`;
        } else {
            bulkActions.style.display = 'none';
        }
        
        // Update select all checkbox state
        const totalCheckboxes = document.querySelectorAll('#allSubdomainsTableBody input[type="checkbox"]').length;
        if (selectAllCheckbox) {
            selectAllCheckbox.checked = count > 0 && count === totalCheckboxes;
            selectAllCheckbox.indeterminate = count > 0 && count < totalCheckboxes;
        }
    } else if (view === 'project') {
        const count = selectedProjectSubdomains.size;
        const bulkActions = document.getElementById('bulkActionsProject');
        const selectedCount = document.getElementById('selectedCountProject');
        const selectAllCheckbox = document.getElementById('selectAllProject');
        
        if (count > 0) {
            bulkActions.style.display = 'flex';
            selectedCount.textContent = `${count} selected`;
        } else {
            bulkActions.style.display = 'none';
        }
        
        // Update select all checkbox state
        const totalCheckboxes = document.querySelectorAll('#projectSubdomainsTableBody input[type="checkbox"]').length;
        if (selectAllCheckbox) {
            selectAllCheckbox.checked = count > 0 && count === totalCheckboxes;
            selectAllCheckbox.indeterminate = count > 0 && count < totalCheckboxes;
        }
    } else if (view === 'target') {
        const count = selectedTargetSubdomains.size;
        const selectAllCheckbox = document.getElementById('selectAllTargetSubdomains');
        
        // Update select all checkbox state
        const totalCheckboxes = document.querySelectorAll('#targetSubdomainsTableBody input[type="checkbox"]').length;
        if (selectAllCheckbox) {
            selectAllCheckbox.checked = count > 0 && count === totalCheckboxes;
            selectAllCheckbox.indeterminate = count > 0 && count < totalCheckboxes;
        }
    }
}

async function bulkDeleteSubdomains(view) {
    let selectedIds;
    if (view === 'results') {
        selectedIds = Array.from(selectedSubdomains);
    } else if (view === 'all') {
        selectedIds = Array.from(selectedAllSubdomains);
    } else if (view === 'project') {
        selectedIds = Array.from(selectedProjectSubdomains);
    }
    
    if (!selectedIds || selectedIds.length === 0) {
        showError('No subdomains selected');
        return;
    }
    
    const confirmMessage = `Are you sure you want to delete ${selectedIds.length} subdomain(s)?`;
    if (!confirm(confirmMessage)) {
        return;
    }
    
    try {
        const result = await apiRequest(`${API_BASE}/subdomains/bulk-delete`, 'POST', {
            subdomain_ids: selectedIds
        });
        
        // Clear selections and reload based on view
        if (view === 'results') {
            selectedSubdomains.clear();
            loadScanSubdomains(currentScanId);
        } else if (view === 'all') {
            selectedAllSubdomains.clear();
            loadAllSubdomains();
            loadDashboard();
        } else if (view === 'project') {
            selectedProjectSubdomains.clear();
            loadProjectData(currentProjectId);
            loadDashboard();
        }
        
        updateBulkActionsUI(view);
        showSuccess(result.message || 'Subdomains deleted successfully');
    } catch (error) {
        showError('Failed to delete subdomains: ' + error.message);
    }
}

async function exportSelectedSubdomains(view) {
    let selectedIds;
    if (view === 'all') {
        selectedIds = Array.from(selectedAllSubdomains);
    } else if (view === 'project') {
        selectedIds = Array.from(selectedProjectSubdomains);
    } else {
        selectedIds = Array.from(selectedSubdomains);
    }
    
    if (!selectedIds || selectedIds.length === 0) {
        showError('No subdomains selected');
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/subdomains/export`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                subdomain_ids: selectedIds,
                format: 'text'
            })
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Export failed');
        }
        
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `subdomains_${new Date().toISOString().split('T')[0]}.txt`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        
        showSuccess(`Exported ${selectedIds.length} subdomain(s) successfully`);
    } catch (error) {
        showError('Failed to export subdomains: ' + error.message);
    }
}

async function exportSettings() {
    try {
        const response = await fetch(`${API_BASE}/settings/export`);
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Export failed');
        }
        
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `settings_export_${new Date().toISOString().split('T')[0]}.yaml`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        
        showSuccess('Settings exported successfully');
    } catch (error) {
        showError('Failed to export settings: ' + error.message);
    }
}

// Wordlist Management Functions
async function loadWordlists() {
    try {
        const wordlists = await apiRequest(`${API_BASE}/wordlists`);
        displayWordlists(wordlists);
    } catch (error) {
        showError('Failed to load wordlists: ' + error.message);
        document.getElementById('wordlistsContainer').innerHTML = '<p class="empty-state">Failed to load wordlists</p>';
    }
}

function displayWordlists(wordlists) {
    const container = document.getElementById('wordlistsContainer');
    
    if (!wordlists || wordlists.length === 0) {
        container.innerHTML = '<p class="empty-state">No wordlists configured. Click "Add Wordlist" to create one.</p>';
        return;
    }
    
    container.innerHTML = wordlists.map(wordlist => `
        <div class="wordlist-row" data-wordlist-name="${wordlist.name}">
            <div class="wordlist-info">
                <div class="wordlist-name">
                    <strong>${escapeHtml(wordlist.name)}</strong>
                    <span class="wordlist-placeholder">${escapeHtml(wordlist.placeholder)}</span>
                </div>
                <div class="wordlist-path">${escapeHtml(wordlist.path)}</div>
            </div>
            <div class="wordlist-actions">
                <button class="btn btn-small btn-secondary" onclick="editWordlist('${wordlist.name}', '${escapeHtml(wordlist.path)}')">
                    <i class="fas fa-edit"></i> Edit
                </button>
                <button class="btn btn-small btn-danger" onclick="deleteWordlist('${wordlist.name}')">
                    <i class="fas fa-trash"></i> Delete
                </button>
            </div>
        </div>
    `).join('');
}

function editWordlist(name, path) {
    document.getElementById('wordlistEditName').value = name;
    document.getElementById('wordlistName').value = name;
    document.getElementById('wordlistPath').value = path;
    document.getElementById('wordlistName').disabled = true;
    document.getElementById('wordlistModalTitle').textContent = 'Edit Wordlist';
    openModal('wordlistModal');
}

async function deleteWordlist(name) {
    if (!confirm(`Are you sure you want to delete the wordlist "${name}"?`)) {
        return;
    }
    
    try {
        await apiRequest(`${API_BASE}/wordlists/${name}`, 'DELETE');
        showSuccess(`Wordlist "${name}" deleted successfully`);
        loadWordlists();
    } catch (error) {
        showError('Failed to delete wordlist: ' + error.message);
    }
}

// Input File Management Functions
async function loadInputFiles() {
    try {
        const inputFiles = await apiRequest(`${API_BASE}/input-files`);
        displayInputFiles(inputFiles);
    } catch (error) {
        showError('Failed to load input files: ' + error.message);
        document.getElementById('inputFilesContainer').innerHTML = '<p class="empty-state">Failed to load input files</p>';
    }
}

function displayInputFiles(inputFiles) {
    const container = document.getElementById('inputFilesContainer');
    
    if (!inputFiles || inputFiles.length === 0) {
        container.innerHTML = '<p class="empty-state">No input files configured. Click "Add Input File" to create one.</p>';
        return;
    }
    
    container.innerHTML = inputFiles.map(inputFile => `
        <div class="wordlist-row" data-input-file-name="${inputFile.name}">
            <div class="wordlist-info">
                <div class="wordlist-name">
                    <strong>${escapeHtml(inputFile.name)}</strong>
                    <span class="wordlist-placeholder">${escapeHtml(inputFile.placeholder)}</span>
                </div>
                <div class="wordlist-path">${escapeHtml(inputFile.path)}</div>
            </div>
            <div class="wordlist-actions">
                <button class="btn btn-small btn-secondary" onclick="editInputFile('${inputFile.name}', '${escapeHtml(inputFile.path)}')">
                    <i class="fas fa-edit"></i> Edit
                </button>
                <button class="btn btn-small btn-danger" onclick="deleteInputFile('${inputFile.name}')">
                    <i class="fas fa-trash"></i> Delete
                </button>
            </div>
        </div>
    `).join('');
}

function editInputFile(name, path) {
    document.getElementById('inputFileEditName').value = name;
    document.getElementById('inputFileName').value = name;
    document.getElementById('inputFilePath').value = path;
    document.getElementById('inputFileName').disabled = true;
    document.getElementById('inputFileModalTitle').textContent = 'Edit Input File';
    openModal('inputFileModal');
}

async function deleteInputFile(name) {
    if (!confirm(`Are you sure you want to delete the input file "${name}"?`)) {
        return;
    }
    
    try {
        await apiRequest(`${API_BASE}/input-files/${name}`, 'DELETE');
        showSuccess(`Input file "${name}" deleted successfully`);
        loadInputFiles();
    } catch (error) {
        showError('Failed to delete input file: ' + error.message);
    }
}

async function importSettings(event) {
    const file = event.target.files[0];
    if (!file) {
        return;
    }
    
    // Check file extension
    if (!file.name.match(/\.(yaml|yml)$/i)) {
        showError('Please select a YAML file (.yaml or .yml)');
        event.target.value = ''; // Reset file input
        return;
    }
    
    // Confirm import
    if (!confirm('This will overwrite your current tools configuration and API keys. Are you sure you want to continue?')) {
        event.target.value = ''; // Reset file input
        return;
    }
    
    try {
        const formData = new FormData();
        formData.append('file', file);
        
        const response = await fetch(`${API_BASE}/settings/import`, {
            method: 'POST',
            body: formData
        });
        
        const result = await response.json();
        
        if (!response.ok) {
            throw new Error(result.error || 'Import failed');
        }
        
        showSuccess('Settings imported successfully. Refreshing...');
        
        // Reset file input
        event.target.value = '';
        
        // Reload settings after a short delay
        setTimeout(() => {
            loadSettings();
        }, 1000);
    } catch (error) {
        showError('Failed to import settings: ' + error.message);
        event.target.value = ''; // Reset file input
    }
}


// Scans Functions
async function loadScans() {
    try {
        const response = await apiRequest(`${API_BASE}/scans`);
        displayAllScans(response.scans || []);
    } catch (error) {
        showError('Failed to load scans: ' + error.message);
        document.getElementById('scansTableBody').innerHTML = '<tr><td colspan="7" class="empty-state">Failed to load scans</td></tr>';
    }
}

function displayAllScans(scans) {
    const tbody = document.getElementById('scansTableBody');
    const countElement = document.getElementById('scansCount');
    
    if (!scans || scans.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="empty-state">No scans found. Start a scan to begin enumeration.</td></tr>';
        countElement.textContent = '0 scans';
        return;
    }
    
    countElement.textContent = `${scans.length} scan${scans.length !== 1 ? 's' : ''}`;
    
    tbody.innerHTML = scans.map(scan => {
        const statusClass = `status-${scan.status}`;
        const statusIcon = scan.status === 'completed' ? 'fa-check-circle' : 
                          scan.status === 'running' ? 'fa-spinner fa-spin' :
                          scan.status === 'failed' ? 'fa-times-circle' :
                          scan.status === 'stopped' ? 'fa-stop-circle' : 'fa-clock';
        
        return `
            <tr class="scan-row" onclick="viewScanResults(${scan.id}, '${escapeHtml(scan.target_domain)}')" style="cursor: pointer;">
                <td><strong>${escapeHtml(scan.target_domain)}</strong></td>
                <td>${escapeHtml(scan.project_name || '-')}</td>
                <td>
                    <span class="status-badge ${statusClass}">
                        <i class="fas ${statusIcon}"></i> ${escapeHtml(scan.status)}
                    </span>
                </td>
                <td>${scan.subdomain_count || 0}</td>
                <td><span class="new-subdomains-count">${scan.new_subdomains || 0}</span></td>
                <td>${formatDate(scan.started_at)}</td>
                <td>
                    <div class="action-buttons" onclick="event.stopPropagation();">
                        <button class="btn btn-small btn-primary" onclick="scanAgain(${scan.id}, '${escapeHtml(scan.target_domain)}', ${scan.project_id})" title="Scan again">
                            <i class="fas fa-redo"></i> Scan Again
                        </button>
                        <button class="btn-icon btn-delete" onclick="deleteScan(${scan.id}, '${escapeHtml(scan.target_domain)}', event)" title="Delete scan">
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');
}

async function deleteScan(scanId, targetDomain, event) {
    if (event) {
        event.stopPropagation();
    }
    
    if (!confirm(`Are you sure you want to delete scan for "${targetDomain}"?

This will delete:
- The scan record
- All associated subdomain links
- Orphaned subdomains (if not used by other scans)

This action cannot be undone.`)) {
        return;
    }
    
    try {
        await apiRequest(`${API_BASE}/scans/${scanId}`, 'DELETE');
        showSuccess(`Scan for "${targetDomain}" deleted successfully`);
        loadScans();
    } catch (error) {
        showError('Failed to delete scan: ' + error.message);
    }
}

async function scanAgain(scanId, targetDomain, projectId) {
    try {
        const scan = await apiRequest(
            `${API_BASE}/projects/${projectId}/scans`,
            'POST',
            { target_domain: targetDomain }
        );
        
        showSuccess('Scan started successfully');
        loadScans();
        
        // Optionally navigate to scan results
        viewScanResults(scan.id, scan.target_domain);
    } catch (error) {
        showError('Failed to start scan: ' + error.message);
    }
}
