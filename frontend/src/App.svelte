<script>
  import { onMount } from 'svelte';
  import ChangesList from './lib/ChangesList.svelte';
  import ChangeDetail from './lib/ChangeDetail.svelte';
  import Stats from './lib/Stats.svelte';

  const API_URL = '';

  let changes = $state([]);
  let stats = $state(null);
  let loading = $state(false);
  let error = $state(null);
  let selectedChange = $state(null);
  let view = $state('list');

  // Read initial filters from URL query params
  const urlParams = new URLSearchParams(window.location.search);
  let minScore = $state(parseInt(urlParams.get('min_score') || '0', 10));
  let riskLevel = $state(urlParams.get('risk_level') || '');
  let searchQuery = $state(urlParams.get('search') || '');
  let selectedTag = $state('');
  let selectedService = $state('');
  let selectedRepo = $state('');
  let offset = $state(0);
  let hasMore = $state(false);
  const LIMIT = 50;

  let repos = $derived([...new Set(changes.map(c => c.repo_name))].sort());
  let services = $state([]);

  async function fetchChanges(append = false) {
    loading = true;
    error = null;
    try {
      const params = new URLSearchParams();
      if (minScore > 0) params.append('min_score', minScore);
      if (riskLevel) params.append('risk_level', riskLevel);
      if (searchQuery) params.append('search', searchQuery);
      if (selectedTag) params.append('tag', selectedTag);
      if (selectedService) params.append('service', selectedService);
      if (selectedRepo) params.append('repo', selectedRepo);
      params.append('limit', LIMIT);
      params.append('offset', append ? offset : 0);

      const url = `${API_URL}/changes?${params}`;
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const page = data.changes || [];
      changes = append ? [...changes, ...page] : page;
      hasMore = page.length === LIMIT;
    } catch (err) {
      error = err.message;
    } finally {
      loading = false;
    }
  }

  function loadMore() {
    offset = changes.length;
    fetchChanges(true);
  }

  async function fetchStats() {
    try {
      const res = await fetch(`${API_URL}/stats`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      stats = await res.json();
    } catch (err) {
      console.error('Stats error:', err);
    }
  }

  async function fetchServices() {
    try {
      const res = await fetch(`${API_URL}/services`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      services = data.services || [];
    } catch (err) {
      console.error('Services error:', err);
    }
  }

  async function fetchChangeByHash(commitHash) {
    loading = true;
    error = null;
    try {
      const res = await fetch(`${API_URL}/changes/hash/${encodeURIComponent(commitHash)}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      selectedChange = await res.json();
      view = 'detail';
    } catch (err) {
      error = `Failed to load change ${commitHash.slice(0, 8)}: ${err.message}`;
      view = 'list';
    } finally {
      loading = false;
    }
  }

  function selectChange(change) {
    selectedChange = change;
    view = 'detail';
    location.hash = `#/change/${change.commit_hash}`;
  }

  function filterByTag(tag) {
    selectedTag = tag;
    offset = 0;
    view = 'list';
    location.hash = '#/';
    fetchChanges();
  }

  function clearTag() {
    selectedTag = '';
    offset = 0;
    fetchChanges();
  }

  function filterByService(service) {
    selectedService = service;
    offset = 0;
    view = 'list';
    location.hash = '#/';
    fetchChanges();
  }

  function clearService() {
    selectedService = '';
    offset = 0;
    fetchChanges();
  }

  function goBack() {
    history.back();
  }

  function handleHashChange() {
    const hash = location.hash || '#/';
    if (hash.startsWith('#/change/')) {
      const commitHash = hash.slice('#/change/'.length);
      if (selectedChange && selectedChange.commit_hash === commitHash) return;
      fetchChangeByHash(commitHash);
    } else if (hash === '#/stats') {
      view = 'stats';
      selectedChange = null;
    } else {
      view = 'list';
      selectedChange = null;
    }
  }

  onMount(() => {
    fetchChanges();
    fetchStats();
    fetchServices();
    // If there's a hash on load, navigate to it; otherwise set default
    if (location.hash && location.hash !== '#/') {
      handleHashChange();
    } else {
      location.hash = '#/';
    }
    window.addEventListener('hashchange', handleHashChange);
    return () => window.removeEventListener('hashchange', handleHashChange);
  });

  function showStats() {
    view = 'stats';
    location.hash = '#/stats';
  }

  function showList() {
    view = 'list';
    location.hash = '#/';
  }
</script>

<main class="footnote-app">
  <header class="header">
    <div class="brand">
      <h1>📖 Footnote</h1>
      <span class="tagline">The real story is in the footnotes</span>
    </div>
    <nav class="nav">
      <button class:active={view === 'list'} onclick={showList}>Changes</button>
      <button class:active={view === 'stats'} onclick={showStats}>Stats</button>
    </nav>
  </header>

  {#if view === 'list'}
    <div class="filters">
      <div class="filter-group">
        <label>Min Score:</label>
        <input type="range" min="0" max="10" step="1" bind:value={minScore} onchange={() => { offset = 0; fetchChanges(); }} />
        <span class="score-badge">{minScore}</span>
      </div>

      <div class="filter-group">
        <label>Risk:</label>
        <select bind:value={riskLevel} onchange={() => { offset = 0; fetchChanges(); }}>
          <option value="">All</option>
          <option value="critical">Critical</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
          <option value="informational">Info</option>
        </select>
      </div>

      <div class="filter-group search">
        <input type="text" placeholder="Search commits..." bind:value={searchQuery} oninput={() => { offset = 0; fetchChanges(); }} />
      </div>

      {#if repos.length > 1}
        <div class="filter-group">
          <label>Repo:</label>
          <select bind:value={selectedRepo} onchange={() => { offset = 0; fetchChanges(); }}>
            <option value="">All</option>
            {#each repos as repo}
              <option value={repo}>{repo}</option>
            {/each}
          </select>
        </div>
      {/if}

      {#if selectedTag}
        <div class="filter-group">
          <span class="active-tag">🏷️ {selectedTag} <button class="clear-tag" onclick={clearTag}>✕</button></span>
        </div>
      {/if}

      {#if selectedService}
        <div class="filter-group">
          <span class="active-tag">☁️ {selectedService} <button class="clear-tag" onclick={clearService}>✕</button></span>
        </div>
      {/if}
    </div>

    {#if loading}
      <div class="loading">Loading changes...</div>
    {:else if error}
      <div class="error">Error: {error}</div>
    {:else}
      <ChangesList {changes} onSelect={selectChange} onTagClick={filterByTag} onServiceClick={filterByService} />

      {#if hasMore}
        <div class="load-more">
          <button onclick={loadMore} disabled={loading}>
            {loading ? 'Loading…' : 'Load more'}
          </button>
        </div>
      {/if}
    {/if}

  {:else if view === 'detail'}
    <ChangeDetail change={selectedChange} onBack={goBack} onServiceClick={filterByService} />

  {:else if view === 'stats'}
    <Stats {stats} onBack={showList} />
  {/if}

  <footer class="footer">
    <p>API: {API_URL || '(same domain)'}</p>
  </footer>
</main>

<style>
  :global(body) {
    margin: 0;
    font-family: system-ui, -apple-system, sans-serif;
    background: #0d1117;
    color: #c9d1d9;
  }

  .footnote-app {
    max-width: 1200px;
    margin: 0 auto;
    padding: 1rem;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
  }

  .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-bottom: 1.5rem;
    border-bottom: 1px solid #30363d;
    margin-bottom: 1.5rem;
  }

  .brand h1 {
    margin: 0;
    font-size: 1.8rem;
    color: #58a6ff;
  }

  .tagline {
    color: #8b949e;
    font-size: 0.9rem;
    margin-left: 0.5rem;
  }

  .nav button {
    background: #21262d;
    border: 1px solid #30363d;
    color: #c9d1d9;
    padding: 0.5rem 1rem;
    margin-left: 0.5rem;
    border-radius: 6px;
    cursor: pointer;
  }

  .nav button.active,
  .nav button:hover {
    background: #30363d;
    border-color: #58a6ff;
  }

  .filters {
    display: flex;
    gap: 1rem;
    align-items: center;
    margin-bottom: 1.5rem;
    flex-wrap: wrap;
  }

  .filter-group {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  .filter-group label {
    color: #8b949e;
    font-size: 0.9rem;
  }

  .filter-group input[type="range"] {
    width: 100px;
  }

  .filter-group select,
  .filter-group input[type="text"] {
    background: #21262d;
    border: 1px solid #30363d;
    color: #c9d1d9;
    padding: 0.4rem 0.8rem;
    border-radius: 4px;
  }

  .filter-group.search input {
    width: 250px;
  }

  .active-tag {
    background: #388bfd33;
    color: #58a6ff;
    border: 1px solid #388bfd66;
    padding: 0.2rem 0.6rem;
    border-radius: 12px;
    font-size: 0.85rem;
    display: flex;
    align-items: center;
    gap: 0.4rem;
  }

  .clear-tag {
    background: none;
    border: none;
    color: #58a6ff;
    cursor: pointer;
    padding: 0;
    font-size: 0.8rem;
    line-height: 1;
  }

  .filter-pills {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
    width: 100%;
  }

  .filter-pill {
    background: #388bfd33;
    color: #58a6ff;
    font-size: 0.75rem;
    padding: 0.15rem 0.5rem;
    border-radius: 12px;
    cursor: pointer;
    transition: background 0.15s;
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
  }

  .filter-pill:hover {
    background: #388bfd66;
  }

  .filter-pill.active {
    background: #388bfd66;
    border: 1px solid #58a6ff;
  }

  .pill-count {
    background: #30363d;
    color: #8b949e;
    font-size: 0.7rem;
    padding: 0 0.35rem;
    border-radius: 8px;
  }

  .score-badge {
    background: #238636;
    color: white;
    padding: 0.2rem 0.5rem;
    border-radius: 4px;
    font-weight: bold;
    min-width: 1.5rem;
    text-align: center;
  }

  .loading,
  .error {
    text-align: center;
    padding: 3rem;
    color: #8b949e;
  }

  .error {
    color: #f85149;
  }

  .load-more {
    text-align: center;
    margin-top: 1.5rem;
  }

  .load-more button {
    background: #21262d;
    border: 1px solid #30363d;
    color: #c9d1d9;
    padding: 0.5rem 2rem;
    border-radius: 6px;
    cursor: pointer;
  }

  .load-more button:hover:not(:disabled) {
    border-color: #58a6ff;
  }

  .load-more button:disabled {
    opacity: 0.5;
    cursor: default;
  }

  .footer {
    margin-top: auto;
    padding-top: 2rem;
    text-align: center;
    color: #484f58;
    font-size: 0.8rem;
  }
</style>
