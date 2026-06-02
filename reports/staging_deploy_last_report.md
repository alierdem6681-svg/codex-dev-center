# Production Environment Last Report

Generated at: 2026-06-02T08:28:26+00:00
Kind: staging_deploy
Status: FAIL
Scope: staging
Dry run: False

## Safety
- Secret/IAM/database/DNS/firewall/billing/Google Ads mutate performed: false
- Critical exception findings: none

## Summary
- Production port: 8080
- Staging port: 18080
- Rollback mode: safe logical runtime rollback

## Blockers
- staging_health_or_smoke_failed
