<script>
  import { onMount } from 'svelte';
  import ChangesList from './lib/ChangesList.svelte';
  import ChangeDetail from './lib/ChangeDetail.svelte';
  import Stats from './lib/Stats.svelte';

  // API base URL - relative for same-domain deployment
  const API_URL = import.meta.env.VITE_API_URL || '';

  let changes = [];
  let stats = null;
  let loading = true;
  let error = null;
  let selectedChange = null;
  let view = 'list'; // 'list', 'detail', 'stats'
  let mounted = false;

  // Filters
  let minScore = 0;
  let riskLevel = '';
  let searchQuery = '';
  let repo = '';

  async function fetchChanges() {
    if (!mounted) return;
    loading = true;
    error = null;
    try {
      const params = new URLSearchParams();
      if (minScore > 0) params.append('min_score', minScore);
      if (riskLevel) params.append('risk_level', riskLevel);
      if (searchQuery) params.append('search', searchQuery);
      if (repo) params.append('repo', repo);

      const url = `${API_URL}/changes?${params}`;
      console.log('Fetching:', url);
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      const data = await res.json();
      changes = data.changes || [];
      console.log('Fetched', changes.length, 'changes');
    } catch (err) {
      error = err.message;
      console.error('Fetch error:', err);
    } finally {
      loading = false;
    }
  }

  async function fetchStats() {
    try {
      const res = await fetch(`${API_URL}/stats`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      stats = await res.json();
    } catch (err) {
      console.error('Failed to fetch stats:', err);
    }
  }

  function selectChange(change) {
    selectedChange = change;
    view = 'detail';
  }

  function goBack() {
    selectedChange = null;
    view = 'list';
  }

  function showStats() {
    view = 'stats';
  }

  function showList() {
    view = 'list';
  }

  onMount(() => {
    mounted = true;
    fetchChanges();
    fetchStats();
  });

  $: if (mounted && (minScore !== undefined || riskLevel !== undefined || searchQuery !== undefined || repo !== undefined)) {
    fetchChanges();
  }
</script>

<main class="footnote-app">
  <header class="header">
    <div class="brand">
      <h1>📖 Footnote</h1>
      <span class="tagline">The real story is in the footnotes</span>
    </div>
    <nav class="nav">
      <button class:active={view === 'list'} on:click={showList}>Changes</button>
      <button class:active={view === 'stats'} on:click={showStats}>Stats</button>
    </nav>
  </header>

  {#if view === 'list'}
    <div class="filters">
      <div class="filter-group">
        <label>Min Score:</label>
        <input type="range" min="0" max="10" step="1" bind:value={minScore} />
        <span class="score-badge">{minScore}</span>
      </div>

      <div class="filter-group">
        <label>Risk:</label>
        <select bind:value={riskLevel}>
          <option value="">All</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
          <option value="informational">Info</option>
        </select>
      </div>

      <div class="filter-group search">
        <input type="text" placeholder="Search commits..." bind:value={searchQuery} />
      </div>
    </div>

    {#if loading}
      <div class="loading">Loading changes...</div>
    {:else if error}
      <div class="error">Error: {error}</div>
    {:else}
      <ChangesList {changes} onSelect={selectChange} />
    {/if}

  {:else if view === 'detail'}
    <ChangeDetail change={selectedChange} onBack={goBack} />

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

  .footer {
    margin-top: auto;
    padding-top: 2rem;
    text-align: center;
    color: #484f58;
    font-size: 0.8rem;
  }
</style>
