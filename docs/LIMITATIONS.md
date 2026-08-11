# Product Limitations

ATO Bot is a human-in-the-loop NIST SP 800-53 assessment platform. It does not replace a qualified assessor and does not make an authorization decision.

## Assessment Boundary

- Automated processing primarily performs document examination and draft objective/control determinations.
- Required interviews and technical tests must be performed and recorded by qualified personnel.
- Final findings require explicit human review; unresolved dissents, activities, tailoring decisions, POA&M records, and approvals block finalization.
- Model-generated narratives and artifacts are untrusted drafts until approved. Generated artifacts are ineligible as assessment evidence by default.
- Determinations depend on evidence completeness, currency, system scope, organization-defined parameters, and assessment policy configuration.

## Operational Boundary

- External connectors, optional security-posture snapshots, drift collection, and the cATO dashboard are experimental and disabled by default. They are not part of the supported assessment workflow.
- Calibration and synthetic-data capabilities are beta and must not be confused with operational evidence.
- OSCAL schema validity does not prove that required assessment activities actually occurred.
- Carry-forward is opt-in and is allowed only when evidence scope, policy version, model, and execution mode match.

See `EXPERIMENTAL_CAPABILITIES.md` for the complete disposition inventory.
