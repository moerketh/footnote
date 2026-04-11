# Footnote — Model Evaluation

Evaluation date: 2026-04-11. 9 calibration test cases from `scorer/test_cases/`, expected values calibrated against Claude Opus 4.6 as reference model.

## Recommended Models

| Model | Provider | Recommended | Exact Match | Avg Score Diff | Notes |
|-------|----------|-------------|-------------|----------------|-------|
| **Claude Opus 4.6** | Anthropic | **Reference** | **9/9 (100%)** | **0.0** | Gold standard. Expected values are derived from this model's classifications. |
| **GLM 5.1** | Zhipu AI (via Ollama Cloud) | **Primary** | **9/9 (100%)** | **0.0** | Perfect agreement with reference. Reasoning model — needs `max_tokens >= 4000`. |
| **Kimi K2.5** | Moonshot (via Ollama Cloud) | **Secondary** | **7/9 (78%)** | **0.2** | Fast and consistent. Slightly under-flags CIA on 2 borderline cases (-1 each). |
| Gemma4:31b | Google (via Ollama Cloud) | Acceptable | 5/9 (56%) | 0.9 | Mixed — underrates actionability (`required` → `none`) and under-flags CIA. |
| MiniMax M2.7 | MiniMax (via Ollama Cloud) | Not recommended | 3/9 (33%) | 1.4 | Systematically conservative. Underrates actionability, misses CIA dimensions. Scores trend 1-3 points low. |

## Detailed Results

```
Case                                     | Claude Opus 4.6 | GLM 5.1   | Kimi K2.5 | Gemma4:31b | MiniMax M2.7 | Expected
-----------------------------------------+-----------------+-----------+-----------+------------+--------------+---------
api-connections-dynamic-invoke           | 10.0  ✓         | 10.0  ✓   | 10.0  ✓   | 10.0  ✓    | 10.0  ✓      | 10.0
apim-reader-privilege-escalation         |  9.0  ✓         |  9.0  ✓   |  8.0 -1   |  6.0 -3    |  7.0 -2      |  9.0
azure-storage-public-blob-default        |  7.0  ✓         |  7.0  ✓   |  6.0 -1   |  5.0 -2    |  5.0 -2      |  7.0
entra-app-only-token-breaking            | 10.0  ✓         | 10.0  ✓   | 10.0  ✓   | 10.0  ✓    |  8.0 -2      | 10.0
entra-mfa-mandatory                      |  9.0  ✓         |  9.0  ✓   |  9.0  ✓   |  9.0  ✓    |  9.0  ✓      |  9.0
keyvault-soft-delete-always-on           |  8.0  ✓         |  8.0  ✓   |  8.0  ✓   |  6.0 -2    |  6.0 -2      |  8.0
rbac-classic-admin-deprecated            | 10.0  ✓         | 10.0  ✓   | 10.0  ✓   | 10.0  ✓    |  7.0 -3      | 10.0
sas-token-user-binding                   |  5.0  ✓         |  5.0  ✓   |  5.0  ✓   |  6.0 +1    |  3.0 -2      |  5.0
typo-fix-rotation-example                |  0.0  ✓         |  0.0  ✓   |  0.0  ✓   |  0.0  ✓    |  0.0  ✓      |  0.0
```

## Key Observations

### Claude Opus 4.6 as reference model
Expected values for all 9 test cases are derived from Claude Opus 4.6's dimension classifications. This model was chosen as the gold standard because its CIA reasoning aligns with security-conservative interpretation — it flags availability and integrity impacts that borderline cases arguably have, which is the safer failure mode for a security monitoring tool.

### GLM 5.1 has perfect agreement with Opus
GLM 5.1 produced identical scores to Claude Opus 4.6 on all 9 cases. This makes it the best cost-effective alternative for production use (accessible via Ollama Cloud with a single API key). It is a reasoning model requiring `max_tokens >= 4000`.

### Kimi K2.5 is fast but slightly under-flags CIA
Kimi K2.5 misses 2 borderline CIA flags where Opus (and GLM) flag availability or integrity:
- `apim-reader-privilege-escalation`: misses availability (Reader users losing key access is a workflow disruption)
- `azure-storage-public-blob-default`: misses integrity (public blob access allows unauthorized modification)

Both divergences are -1 point and stay within the same risk category in practice.

### Score differences are bounded
No model produced a score that crossed risk level boundaries in a dangerous direction (e.g., scoring a critical case as informational). The worst case was MiniMax scoring `rbac-classic-admin-deprecated` at 7.0 (high) vs expected 10.0 (critical) — a 3-point gap.

### Dimension-level disagreement patterns
- **CIA (C, I, A)** is the primary source of disagreement. Models differ on when availability and integrity are impacted by access-control changes.
- **Actionability** remains contested for weaker models — Gemma4 and MiniMax under-classify `required` actions.
- **Change nature** and **broad scope** are stable across all models.

### MiniMax M2.7 is systematically conservative
MiniMax consistently underrates across all dimensions. For a security monitoring tool, **over-flagging is preferable** to under-flagging, making GLM or Kimi the better production choices.

## Running the Evaluation

```bash
# Offline tests only (no API key needed, instant)
python scorer/tests/test_scoring.py

# Live evaluation against recommended models
CLOUD_API_KEY=your_key python scorer/tests/test_scoring.py --live \
    --models "kimi-k2.5@https://ollama.com/v1" \
             "glm-5.1@https://ollama.com/v1"

# Full cross-model comparison (slower, costs tokens)
CLOUD_API_KEY=your_key python scorer/tests/test_scoring.py --live \
    --models "glm-5.1@https://ollama.com/v1" \
             "minimax-m2.7@https://ollama.com/v1" \
             "kimi-k2.5@https://ollama.com/v1" \
             "gemma4:31b@https://ollama.com/v1"
```

## Configuration

Set the primary scorer model in `.env`:

```bash
CLOUD_OLLAMA_URL=https://ollama.com/v1   # Ollama Cloud (OpenAI-compatible)
CLOUD_MODEL=glm-5.1                      # Recommended (100% match with Opus reference, reasoning model)
# CLOUD_MODEL=kimi-k2.5                  # Alternative (78% match, faster, slightly under-flags CIA)
```

All models are accessed via Ollama Cloud with a single API key. The `scored_by` field in the database records which model produced each score.
