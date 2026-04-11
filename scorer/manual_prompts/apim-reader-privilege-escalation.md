# Security Change Scoring

You are a security analyst evaluating a documentation commit for security relevance.

Your task: classify this change along structured dimensions. Do NOT output a numeric score â€” only classify each dimension. The score is computed from your classifications.

## Scoring Dimensions

- **(CIA) confidentiality** (true/false, +1 point): Does this change affect data confidentiality (exposure, access control, data leakage)?
- **(CIA) integrity** (true/false, +1 point): Does this change affect data or system integrity? Includes unauthorized modification, trust boundary changes, token validation changes, and permission model alterations.
- **(CIA) availability** (true/false, +1 point): Does this change affect service availability? Includes lockouts, access loss from deprecations, workflow disruption from mandatory changes, or capacity impact.
- **change_nature** (choose one):
  - `cosmetic` (+0): Typo, grammar, formatting, broken links â€” no security posture change
  - `clarification` (+1): Explains existing behavior more clearly â€” no change to security posture
  - `new_feature` (+2): New optional security control or configuration introduced
  - `behavior_change` (+3): Changes defaults, existing permissions, access patterns, or makes previously optional controls mandatory
  - `critical` (+4): Breaking change, deprecation of security control, silent security fix, HTTP method change altering authorization model
- **actionability** (choose one):
  - `none` (+0): No action needed by users
  - `recommended` (+1): Action recommended but not immediately required
  - `required` (+2): Action required to maintain security posture or avoid breakage
- **broad_scope** (true/false, +1 point): Platform-wide or cross-service impact? Affects many tenants/subscriptions?

**Important notes:**
- HTTP method changes (GET to POST or vice versa) that alter the authorization model are always 'critical' change_nature, regardless of other factors.
- Cross-tenant impact always sets broad_scope=true.
- A deprecation with a migration deadline is 'required' actionability, even if the deadline is far out.
- Silent fixes (no advisory, found via diff only) are 'critical' change_nature.
- Mandatory enforcement of previously optional controls (e.g., MFA, soft-delete) is 'behavior_change', not 'critical', unless it breaks existing functionality.
- Availability includes access loss from deprecations and lockouts from enforcement changes, not just outages.

## Classification Examples

### API Connections DynamicInvoke: GET proxy allows Reader cross-tenant credential access
Diff:
```
-GET /apim/{connection-id}/DynamicInvoke
+POST /apim/{connection-id}/DynamicInvoke
+
+Note: The DynamicInvoke endpoint now requires POST method.
+Reader role users can no longer invoke backend connections via GET requests.
```
Output:
```json
{
  "cia": {
    "confidentiality": true,
    "integrity": true,
    "availability": true
  },
  "change_nature": "critical",
  "actionability": "required",
  "broad_scope": true,
  "rationale": "HTTP method change from GET to POST for DynamicInvoke proxy closed a cross-tenant credential access vulnerability exploitable by Reader-role users.",
  "summary": "HTTP method change from GET to POST for DynamicInvoke proxy closed a cross-tenant credential access vulnerability exploitable by Reader-role users.",
  "tags": [],
  "services": []
}
```

### Fix typo in Secret Manager rotation example
Diff:
```
-    rotation_schedule = client.create_secret(
-        parent=parent, secret_id=secret_id, roatation_period="86400s"
+    rotation_schedule = client.create_secret(
+        parent=parent, secret_id=secret_id, rotation_period="86400s"
```
Output:
```json
{
  "cia": {
    "confidentiality": false,
    "integrity": false,
    "availability": false
  },
  "change_nature": "cosmetic",
  "actionability": "none",
  "broad_scope": false,
  "rationale": "Typo fix with no security impact.",
  "summary": "Typo fix with no security impact.",
  "tags": [],
  "services": []
}
```

## Change to Evaluate

Repository: test-repo
Commit: 000000000000
Author: test@example.com
Date: 2024-01-01
Message: Update RBAC documentation: restrict subscription key access to Contributor role
Files changed: test-file.md

Diff:
```
-Users with Reader role can view subscription keys in the Azure portal.
+Subscription key access is now restricted to Contributor role and above.
+Reader role users can no longer view or copy subscription keys.
+
+This change prevents potential privilege escalation where Reader users
+could use subscription keys to invoke APIs beyond their intended access.

```

## Required Output

Respond with ONLY this JSON structure, no other text:

```json
{
  "cia": {
    "confidentiality": true/false,
    "integrity": true/false,
    "availability": true/false
  },
  "change_nature": "cosmetic|clarification|new_feature|behavior_change|critical",
  "actionability": "none|recommended|required",
  "broad_scope": true/false,
  "rationale": "One sentence explaining the primary security impact.",
  "summary": "2-3 sentence summary of what changed and why it matters.",
  "tags": ["tag1", "tag2"],
  "services": ["Affected Service 1", "Affected Service 2"]
}
```

Available tags: permission-change, default-behavior, deprecation, new-security-feature, auth-change, network-change, encryption, compliance, api-breaking, silent-fix, identity, monitoring
