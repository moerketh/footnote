<script>
  let { stats = null, onBack = () => {} } = $props();

  function getRiskColor(level) {
    const colors = {
      critical: '#a371f7',
      high: '#f85149',
      medium: '#d29922',
      low: '#d4a72c',
      informational: '#8b949e'
    };
    return colors[level] || '#8b949e';
  }

  let riskData = $derived(stats?.by_risk_level ? Object.entries(stats.by_risk_level) : []);
  let repoData = $derived(stats?.by_repo ? Object.entries(stats.by_repo) : []);
  let maxRisk = $derived(riskData.length > 0 ? Math.max(...riskData.map(([,v]) => v)) : 1);
</script>

<div class="stats-view">
  <button class="back-btn" on:click={onBack}>← Back to changes</button>

  <h2>📊 Statistics</h2>

  {#if !stats}
    <div class="loading">Loading stats...</div>
  {:else}
    <div class="stats-grid">
      <div class="stat-card total">
        <div class="stat-value">{stats.total_changes}</div>
        <div class="stat-label">Total Changes</div>
      </div>

      <div class="stat-card average">
        <div class="stat-value">{stats.avg_score?.toFixed(2)}</div>
        <div class="stat-label">Average Score</div>
      </div>
    </div>

    {#if riskData.length > 0}
      <section class="risk-distribution">
        <h3>Risk Level Distribution</h3>
        
        <div class="risk-bars">
          {#each riskData as [level, count]}
            <div class="risk-row">
              <span class="risk-label">{level}</span>
              <div class="bar-container">
                <div 
                  class="bar" 
                  style="width: {(count / maxRisk * 100)}%; background: {getRiskColor(level)}"
                >
                  {count}
                </div>
              </div>
            </div>
          {/each}
        </div>
      </section>
    {/if}

    {#if repoData.length > 0}
      <section class="repo-distribution">
        <h3>Changes by Repository</h3>
        
        <div class="repo-list">
          {#each repoData as [repo, count]}
            <div class="repo-row">
              <span class="repo-name">{repo}</span>
              <span class="repo-count">{count}</span>
            </div>
          {/each}
        </div>
      </section>
    {/if}
  {/if}
</div>

<style>
  .stats-view {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 1.5rem;
  }

  .back-btn {
    background: #21262d;
    border: 1px solid #30363d;
    color: #c9d1d9;
    padding: 0.5rem 1rem;
    border-radius: 6px;
    cursor: pointer;
    margin-bottom: 1.5rem;
  }

  .back-btn:hover {
    border-color: #58a6ff;
  }

  h2 {
    margin: 0 0 1.5rem 0;
    color: #e6edf3;
  }

  h3 {
    margin: 0 0 1rem 0;
    color: #8b949e;
    font-size: 1rem;
  }

  .loading {
    text-align: center;
    padding: 3rem;
    color: #8b949e;
  }

  .stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 1rem;
    margin-bottom: 2rem;
  }

  .stat-card {
    background: #0d1117;
    padding: 1.5rem;
    border-radius: 8px;
    text-align: center;
    border: 1px solid #30363d;
  }

  .stat-value {
    font-size: 2.5rem;
    font-weight: bold;
    color: #58a6ff;
    margin-bottom: 0.5rem;
  }

  .stat-label {
    color: #8b949e;
    font-size: 0.9rem;
  }

  section {
    margin-top: 2rem;
  }

  .risk-bars {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  .risk-row {
    display: flex;
    align-items: center;
    gap: 1rem;
  }

  .risk-label {
    min-width: 120px;
    text-transform: capitalize;
    color: #8b949e;
  }

  .bar-container {
    flex: 1;
    background: #21262d;
    border-radius: 4px;
    overflow: hidden;
  }

  .bar {
    padding: 0.5rem 0.75rem;
    border-radius: 4px;
    color: #0d1117;
    font-weight: bold;
    min-width: 30px;
    transition: width 0.3s ease;
  }

  .repo-list {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .repo-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.75rem;
    background: #0d1117;
    border-radius: 6px;
  }

  .repo-name {
    color: #c9d1d9;
    font-family: ui-monospace, monospace;
  }

  .repo-count {
    background: #388bfd33;
    color: #58a6ff;
    padding: 0.25rem 0.75rem;
    border-radius: 12px;
    font-weight: bold;
  }
</style>
